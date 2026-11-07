"""In-process coverage for the standalone remote load-test runner."""

import asyncio

import httpx
import pytest
from fastapi.responses import JSONResponse

from scripts import load_test
from svc.app import create_app
from svc.dependencies import get_db


@pytest.fixture(autouse=True)
def reset_rate_limits():
    from svc.rate_limit import limiter

    limiter._storage.reset()


def test_load_runner_exercises_two_players_and_reports_workout_saves(fresh_store, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-0123456789abcdef")
    db = fresh_store
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    transport = httpx.ASGITransport(app=app)

    async def exercise():
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await load_test.run(client, base_url="http://testserver", players=2,
                                       duration=2, account_prefix="loadtest-script-",
                                       think_time=(0.01, 0.02))

    summary = asyncio.run(exercise())
    assert {"setup_seconds", "players_ready", "setup_errors_by_status_code",
            "total_requests", "requests_per_second", "errors_by_status_code",
            "requests_by_type", "latency_ms"} <= summary.keys()
    assert summary["players_ready"] == 2
    assert summary["requests_by_type"]["workout_save"] > 0
    assert summary["errors_by_type"].get("workout_save", {}) == {}
    assert summary["latency_ms"]["workout_save"]["median"] is not None
    assert summary["latency_ms"]["workout_save"]["p95"] is not None


def test_setup_retries_register_rate_limit_and_all_players_become_ready(fresh_store, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-0123456789abcdef")
    db = fresh_store
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    retry_count = {"remaining": 2}
    from starlette.middleware.base import BaseHTTPMiddleware

    class LowRegisterLimit(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.url.path == "/auth/register" and retry_count["remaining"]:
                retry_count["remaining"] -= 1
                return JSONResponse({"detail": "rate limited"}, status_code=429,
                                    headers={"Retry-After": "0"})
            return await call_next(request)

    app.add_middleware(LowRegisterLimit)
    transport = httpx.ASGITransport(app=app)

    async def exercise():
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await load_test.run(client, base_url="http://testserver", players=2,
                                       duration=0.1, account_prefix="loadtest-retry-",
                                       think_time=(0.001, 0.002), setup_timeout=30)

    summary = asyncio.run(exercise())
    assert summary["players_ready"] == 2
    assert summary["setup_errors_by_status_code"]["429"] == 2


def test_setup_concurrency_caps_players_in_flight(fresh_store, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-0123456789abcdef")
    db = fresh_store
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    inner = httpx.ASGITransport(app=app)
    state = {"active": 0, "maximum": 0}

    class CountingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if not request.url.path.startswith(("/auth/", "/onboarding/")):
                return await inner.handle_async_request(request)
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
            try:
                return await inner.handle_async_request(request)
            finally:
                state["active"] -= 1

    async def exercise():
        async with httpx.AsyncClient(transport=CountingTransport(), base_url="http://testserver") as client:
            return await load_test.run(client, base_url="http://testserver", players=5,
                                       duration=0.02, account_prefix="loadtest-cap-",
                                       setup_concurrency=2, think_time=(0.001, 0.002))

    summary = asyncio.run(exercise())
    assert summary["players_ready"] == 5
    assert state["maximum"] <= 2


def test_ramp_up_staggers_measured_requests_and_is_reported(monkeypatch):
    # #622: neither HTTP processing nor CPU contention should consume the ramp window.
    class VirtualClock:
        def __init__(self):
            self.now = 0.0
            self.sleepers = []

        def __call__(self):
            return self.now

        async def sleep(self, delay):
            future = asyncio.get_running_loop().create_future()
            self.sleepers.append((self.now + delay, future))
            if len(self.sleepers) == 1:
                asyncio.get_running_loop().call_soon(self.advance)
            await future

        def advance(self):
            self.now = min(deadline for deadline, _ in self.sleepers)
            due = [future for deadline, future in self.sleepers if deadline <= self.now]
            self.sleepers = [(deadline, future) for deadline, future in self.sleepers
                             if deadline > self.now]
            for future in due:
                future.set_result(None)
            if self.sleepers:
                asyncio.get_running_loop().call_soon(self.advance)

    clock = VirtualClock()
    measured_starts = {}
    tokens = iter(range(3))
    monkeypatch.setattr(load_test.random, "random", lambda: 0.5)

    class RecordingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if request.url.path == "/auth/register":
                return httpx.Response(200, json={"access_token": str(next(tokens))})
            if request.url.path == "/programs/active":
                return httpx.Response(200, json={"days": [{"day_order": 1, "exercises": ["squat"]}]})
            assert request.url.path == "/workouts/sessions"
            measured_starts.setdefault(request.headers["authorization"], []).append(clock())
            return httpx.Response(200, json={})

    async def exercise():
        async with httpx.AsyncClient(transport=RecordingTransport(), base_url="http://testserver") as client:
            return await load_test.run(client, base_url="http://testserver", players=3,
                                       duration=0.05, ramp_up=0.08,
                                       account_prefix="loadtest-ramp-", think_time=(0.01, 0.01),
                                       monotonic=clock, perf_counter=clock, sleep=clock.sleep)

    summary = asyncio.run(exercise())
    assert summary["ramp_up_seconds"] == 0.08
    first_starts = [starts[0] for starts in measured_starts.values()]
    assert len(first_starts) == 3
    assert max(first_starts) - min(first_starts) >= 0.07
    assert sorted(first_starts) == pytest.approx([0, 0.04, 0.08])
    measured_boundary = max(first_starts)
    expected_measured_requests = sum(
        started >= measured_boundary
        for starts in measured_starts.values()
        for started in starts
    )
    assert 0 < expected_measured_requests < sum(map(len, measured_starts.values()))
    assert summary["total_requests"] == expected_measured_requests


def test_reuse_accounts_controls_existing_account_setup(fresh_store, monkeypatch):
    from svc.rate_limit import limiter

    monkeypatch.setenv("JWT_SECRET", "test-secret-key-0123456789abcdef")
    db = fresh_store
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    inner = httpx.ASGITransport(app=app)
    intake_requests = []

    class RecordingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if request.url.path.startswith("/onboarding/intake"):
                intake_requests.append(request.url.path)
            return await inner.handle_async_request(request)

    async def exercise():
        async with httpx.AsyncClient(transport=RecordingTransport(), base_url="http://testserver") as client:
            await load_test.run(client, base_url="http://testserver", players=2, duration=0.01,
                                account_prefix="loadtest-reuse-", think_time=(0.001, 0.002))
            limiter._storage.reset()
            intake_requests.clear()
            no_reuse = await load_test.run(client, base_url="http://testserver", players=2, duration=0.01,
                                           account_prefix="loadtest-reuse-", think_time=(0.001, 0.002))
            assert no_reuse["players_ready"] == 0
            assert no_reuse["setup_errors_by_status_code"]["account_exists"] == 2
            limiter._storage.reset()
            intake_requests.clear()
            reuse = await load_test.run(client, base_url="http://testserver", players=2, duration=0.01,
                                        account_prefix="loadtest-reuse-", reuse_accounts=True,
                                        think_time=(0.001, 0.002))
            return no_reuse, reuse

    no_reuse, summary = asyncio.run(exercise())
    assert intake_requests == []
    assert no_reuse["players_ready"] == 0
    assert summary["players_reused"] == 2
    assert summary["players_ready"] == 2


def test_production_host_refusal():
    assert load_test.is_production_url("https://api.mayos.online")
    with pytest.raises(ValueError, match="production host"):
        asyncio.run(_refuse_production())


async def _refuse_production():
    await load_test.run(httpx.AsyncClient(), base_url="https://mayos-api.fly.dev", duration=1)
