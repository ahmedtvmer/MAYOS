"""Exercise the hosted MAYOS API with concurrent simulated Players."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    import httpx

INTAKE = {
    "gender": "female", "proportions": "balanced", "age": 29,
    "height_cm": 168.0, "weight_kg": 64.5, "training_age_years": 3.0,
    "current_goal": "build strength", "long_term_goal": "stay healthy",
    "weekly_frequency": 4, "equipment_access": "commercial gym",
    "injuries_or_limitations": "None", "stress_and_sleep": "moderate stress",
}


def is_production_url(base_url: str) -> bool:
    return (urlparse(base_url).hostname or "").lower() in {"api.mayos.online", "mayos-api.fly.dev"}


async def run(client: httpx.AsyncClient, *, base_url: str, players: int = 20,
              duration: float = 180, account_prefix: str = "loadtest-",
              chat_share: float = 0.0, think_time: tuple[float, float] = (0.05, 0.25),
              allow_production: bool = False, setup_timeout: float = 600,
              setup_concurrency: int = 5, ramp_up: float = 0,
              reuse_accounts: bool = False) -> dict:
    """Run a load rehearsal through an injected httpx client."""
    if is_production_url(base_url) and not allow_production:
        raise ValueError("Refusing to load test a production host without --allow-production.")
    if (players < 1 or duration <= 0 or setup_timeout <= 0 or setup_concurrency < 1
            or ramp_up < 0 or not 0 <= chat_share <= 1):
        raise ValueError("players, duration, setup_timeout, and setup_concurrency must be positive; ramp_up must be nonnegative and chat_share must be in [0, 1].")
    import httpx

    base_url = base_url.rstrip("/")
    measured_latencies: dict[str, list[float]] = defaultdict(list)
    measured_statuses: Counter[str] = Counter()
    measured_errors_by_type: dict[str, Counter[str]] = defaultdict(Counter)
    setup_errors: Counter[str] = Counter()
    reused_players = 0
    setup_semaphore = asyncio.Semaphore(setup_concurrency)
    totals = 0
    lock = asyncio.Lock()
    setup_deadline = time.monotonic() + setup_timeout

    async def measured_request(kind: str, method: str, path: str, **kwargs) -> httpx.Response:
        nonlocal totals
        started = time.perf_counter()
        measured = started >= measured_start
        try:
            response = await client.request(method, base_url + path, **kwargs)
            code = str(response.status_code)
        except httpx.RequestError:
            response = None
            code = "network_error"
        elapsed = (time.perf_counter() - started) * 1000
        if measured:
            async with lock:
                totals += 1
                measured_latencies[kind].append(elapsed)
                if response is None or response.is_error:
                    measured_statuses[code] += 1
                    measured_errors_by_type[kind][code] += 1
        return response

    async def setup_request(method: str, path: str, *, expected_statuses: frozenset[int] = frozenset(), **kwargs) -> httpx.Response | None:
        while time.monotonic() < setup_deadline:
            try:
                response = await client.request(method, base_url + path, **kwargs)
            except httpx.RequestError:
                setup_errors["network_error"] += 1
                return None
            if response.status_code != 429:
                if response.is_error and response.status_code not in expected_statuses:
                    setup_errors[str(response.status_code)] += 1
                return response
            setup_errors["429"] += 1
            retry_after = response.headers.get("Retry-After", "")
            try:
                wait_seconds = max(0.0, float(retry_after))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    wait_seconds = max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    wait_seconds = 0.5
            await asyncio.sleep(min(wait_seconds, max(0.0, setup_deadline - time.monotonic())))
        setup_errors["setup_timeout"] += 1
        return None

    async def player_setup(index: int) -> dict | None:
        async with setup_semaphore:
            return await limited_player_setup(index)

    async def limited_player_setup(index: int) -> dict | None:
        nonlocal reused_players
        username = f"{account_prefix}{index}"
        credentials = {"trainee_id": username, "password": "LoadTest-pass-2026"}
        response = await setup_request("POST", "/auth/register", json=credentials, expected_statuses=frozenset({409}))
        if response is None:
            return None
        registration_conflict = response.status_code == 409
        if registration_conflict:
            if not reuse_accounts:
                setup_errors["account_exists"] += 1
                return None
            response = await setup_request("POST", "/auth/login", json=credentials)
        if response is None or response.is_error:
            return None
        if registration_conflict:
            reused_players += 1
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        existing_program = await setup_request("GET", "/programs/active", headers=headers)
        if existing_program is None or existing_program.is_error:
            return None
        existing_data = existing_program.json()
        if existing_data and existing_data.get("days"):
            return {"headers": headers, "program": existing_data}
        disclosure = await setup_request("POST", "/onboarding/intake/disclosure", headers=headers)
        if disclosure is None or disclosure.is_error:
            return None
        for field, value in INTAKE.items():
            answer = await setup_request("PUT", f"/onboarding/intake/answers/{field}", headers=headers, json={"value": value})
            if answer is None or answer.is_error:
                return None
        confirmed = await setup_request("POST", "/onboarding/intake/confirm", headers=headers, json={})
        if confirmed is None or confirmed.is_error:
            return None
        program_response = await setup_request("GET", "/programs/active", headers=headers)
        if program_response is None or program_response.is_error:
            return None
        program = program_response.json()
        days = program.get("days") or []
        if not days or not days[0].get("exercises"):
            return None
        return {"headers": headers, "program": program}

    setup_started = time.monotonic()
    setups = await asyncio.gather(*(player_setup(i) for i in range(players)))
    setup_seconds = round(time.monotonic() - setup_started, 3)
    ready_players = [setup for setup in setups if setup is not None]
    ready_at = time.monotonic()
    ramp_interval = ramp_up / max(len(ready_players) - 1, 1)
    measured_start = ready_at + ramp_up
    end_at = measured_start + duration

    async def player_task(index: int, setup: dict) -> None:
        await asyncio.sleep(ramp_interval * index)
        headers = setup["headers"]
        program = setup["program"]
        days = program.get("days") or []
        day = days[0]
        while time.monotonic() < end_at:
            roll = random.random()
            if roll < chat_share:
                await measured_request("chat", "POST", "/chat/messages", headers=headers, json={"content": "How should I approach my next workout?"})
            elif roll < chat_share + 0.15:
                await measured_request("program_read", "GET", "/programs/active", headers=headers)
            else:
                sets = [{"exercise": exercise, "sets": [{"weight_kg": 20, "reps": 8, "rpe": 8.0}]}
                        for exercise in day["exercises"][:1]]
                await measured_request("workout_save", "POST", "/workouts/sessions", headers=headers,
                                       json={"day_order": day["day_order"], "week_order": day.get("week_order", 1),
                                             "readiness": 3, "session_notes": "", "sets": sets})
            await asyncio.sleep(random.uniform(*think_time))

    await asyncio.gather(*(player_task(index, setup) for index, setup in enumerate(ready_players)))
    elapsed = max(time.monotonic() - measured_start, 0.000001)

    def percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        if fraction == .5:
            return round(statistics.median(ordered), 2)
        return round(ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)], 2)

    summary = {
        "setup_seconds": setup_seconds,
        "ramp_up_seconds": ramp_up,
        "players_reused": reused_players,
        "players_ready": len(ready_players),
        "setup_errors_by_status_code": dict(sorted(setup_errors.items())),
        "total_requests": totals,
        "duration_seconds": round(elapsed, 3),
        "requests_per_second": round(totals / elapsed, 2),
        "errors_by_status_code": dict(sorted(measured_statuses.items())),
        "errors_by_type": {kind: dict(sorted(codes.items())) for kind, codes in sorted(measured_errors_by_type.items())},
        "requests_by_type": {kind: len(values) for kind, values in sorted(measured_latencies.items())},
        "latency_ms": {kind: {"count": len(values), "median": percentile(values, .5), "p95": percentile(values, .95)}
                       for kind, values in sorted(measured_latencies.items())},
    }
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--players", type=int, default=20)
    parser.add_argument("--duration", type=float, default=180)
    parser.add_argument("--setup-timeout", type=float, default=600)
    parser.add_argument("--setup-concurrency", type=int, default=5)
    parser.add_argument("--ramp-up", type=float, default=0)
    parser.add_argument("--request-timeout", type=float, default=30)
    parser.add_argument("--account-prefix", default="loadtest-")
    parser.add_argument("--chat-share", type=float, default=0.0)
    parser.add_argument("--think-time", type=float, nargs=2, metavar=("MIN", "MAX"), default=(0.05, 0.25))
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--reuse-accounts", action="store_true")
    return parser


async def _main(args: argparse.Namespace) -> int:
    if is_production_url(args.base_url) and not args.allow_production:
        print("Refusing to load test a production host without --allow-production.")
        return 2
    if not 0 <= args.chat_share <= 1:
        print("--chat-share must be between 0 and 1.")
        return 2
    import httpx

    async with httpx.AsyncClient(timeout=args.request_timeout) as client:
        summary = await run(client, base_url=args.base_url, players=args.players,
                            duration=args.duration, account_prefix=args.account_prefix,
                            chat_share=args.chat_share, think_time=tuple(args.think_time),
                            setup_timeout=args.setup_timeout, allow_production=args.allow_production,
                            setup_concurrency=args.setup_concurrency, ramp_up=args.ramp_up,
                            reuse_accounts=args.reuse_accounts)
    print(f"Total requests: {summary['total_requests']}")
    print(f"Requests/s: {summary['requests_per_second']}")
    print(f"Errors by status code: {summary['errors_by_status_code']}")
    print(f"Setup: {summary['setup_seconds']} s; ready Players: {summary['players_ready']}/{args.players}; setup errors: {summary['setup_errors_by_status_code']}")
    for kind, stats in summary["latency_ms"].items():
        print(f"{kind}: count={stats['count']} median={stats['median']} ms p95={stats['p95']} ms")
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as output:
            json.dump(summary, output, indent=2)
            output.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parser().parse_args())))
