"""Exercise the production API image through a short real HTTP scenario."""

from __future__ import annotations

import argparse
import http.client
import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

class SmokeFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class ApiRequest:
    method: str = "GET"
    body: dict | None = None
    token: str | None = None


ONBOARDING_ANSWERS = {
    "gender": "female",
    "proportions": "balanced",
    "age": 29,
    "height_cm": 168.0,
    "weight_kg": 64.5,
    "training_age_years": 3.0,
    "current_goal": "build strength",
    "long_term_goal": "stay healthy",
    "weekly_frequency": 3,
    "equipment_access": "commercial gym",
    "injuries_or_limitations": "None",
    "stress_and_sleep": "moderate stress",
}


def request(base_url: str, path: str, options: ApiRequest = ApiRequest()):
    headers = {"Content-Type": "application/json"}
    if options.token:
        headers["Authorization"] = f"Bearer {options.token}"
    data = json.dumps(options.body).encode() if options.body is not None else None
    req = urllib.request.Request(base_url + path, data=data, headers=headers, method=options.method)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read()
            if response.status < 200 or response.status >= 300:
                raise SmokeFailure(f"{options.method} {path} returned HTTP {response.status}")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raise SmokeFailure(f"{options.method} {path} returned HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
    except urllib.error.URLError as exc:
        raise SmokeFailure(f"{options.method} {path} failed: {exc}") from exc
    except (ConnectionError, TimeoutError, http.client.HTTPException, OSError) as exc:
        raise SmokeFailure(f"{options.method} {path} failed: {exc}") from exc


def wait_until_ready(base_url: str, timeout: int, request_func=request) -> None:
    deadline = time.monotonic() + timeout
    last_error = "service has not started"
    while time.monotonic() < deadline:
        try:
            status = request_func(base_url, "/readyz")
            if status and status.get("status") == "ready":
                return
            last_error = f"/readyz returned {status!r}"
        except SmokeFailure as exc:
            last_error = str(exc)
        time.sleep(3)
    raise SmokeFailure(f"API did not become ready within {timeout}s: {last_error}")


def register_player(base_url: str, request_func) -> str:
    username = f"ci-smoke-{uuid.uuid4().hex[:12]}"
    registered = request_func(
        base_url, "/auth/register",
        ApiRequest(method="POST", body={"trainee_id": username, "password": "ci-smoke-password-123"}),
    )
    token = registered.get("access_token") if registered else None
    if not token:
        raise SmokeFailure("registration did not return an access token")
    return token


def complete_onboarding(base_url: str, token: str, request_func) -> None:
    request_func(base_url, "/onboarding/intake/disclosure", ApiRequest(method="POST", body={}, token=token))
    for field, value in ONBOARDING_ANSWERS.items():
        request_func(base_url, f"/onboarding/intake/answers/{field}", ApiRequest(method="PUT", body={"value": value}, token=token))
    confirmed = request_func(
        base_url, "/onboarding/intake/confirm",
        ApiRequest(method="POST", body={}, token=token),
    )
    if not confirmed or confirmed.get("status") != "confirmed":
        raise SmokeFailure(f"onboarding did not confirm: {confirmed!r}")


def workout_payload(program: dict) -> dict:
    if not program or not program.get("days"):
        raise SmokeFailure("onboarding did not produce a readable training program")
    day = program["days"][0]
    if not day.get("exercises"):
        raise SmokeFailure("the active program has no exercise to log")
    program_exercise = day["exercises"][0]
    exercise = {
        field: program_exercise[field]
        for field in ("exercise_id", "exercise_name", "target_reps_min", "target_reps_max")
    }
    return {
        "day_order": day["day_order"],
        "week_order": day.get("week_order", 1),
        "readiness": 4,
        "sets": [{
            "exercise": exercise,
            "sets": [{"weight_kg": 20, "reps": exercise["target_reps_min"]}],
        }],
    }


def save_program_workout(base_url: str, token: str, program: dict, request_func) -> None:
    saved_workout = request_func(
        base_url, "/workouts/sessions",
        ApiRequest(method="POST", token=token, body=workout_payload(program)),
    )
    if not saved_workout or not saved_workout.get("session_id"):
        raise SmokeFailure(f"workout commit did not return a saved session: {saved_workout!r}")


def run(base_url: str, timeout: int, request_func=request) -> None:
    wait_until_ready(base_url, timeout, request_func)
    token = register_player(base_url, request_func)
    complete_onboarding(base_url, token, request_func)
    program = request_func(base_url, "/programs/active", ApiRequest(token=token))
    save_program_workout(base_url, token, program, request_func)
    final_readiness = request_func(base_url, "/readyz")
    if not final_readiness or final_readiness.get("status") != "ready":
        raise SmokeFailure(f"final /readyz check failed: {final_readiness!r}")
    print("Production image smoke scenario passed: register, onboard, save workout, read program, readyz.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    run(args.base_url.rstrip("/"), args.timeout)
