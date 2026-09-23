"""Public FastAPI chat/onboarding endpoints obey ``LLM_MAX_CONCURRENT``.

Requests go through the real HTTP contract with the real (temporary SQLite)
ledger; only the model/graph is doubled. Peak active work is measured across
concurrent requests, so an ungated endpoint would exceed the configured cap.
"""

import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from database.database_manager import DatabaseManager
from svc.app import create_app
from svc.dependencies import get_current_trainee, get_db
from svc.llm import reset_inference_gate

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    monkeypatch.setattr(DatabaseManager, "_instance", None)
    monkeypatch.setattr(DatabaseManager, "_local", threading.local())
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.commit()
    cat_conn.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        users_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        active_user="bootstrap",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_trainee] = lambda: "alice"
    with TestClient(app) as test_client:
        test_client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})
        yield test_client
    if db.user_conn is not None:
        db.user_conn.close()
    db.catalog_conn.close()


@pytest.fixture(autouse=True)
def _reset_gate():
    reset_inference_gate()
    yield
    reset_inference_gate()


def _measure_peak(client, monkeypatch, *, install_double, request, max_concurrent, workers=4):
    """Fires ``workers`` concurrent requests; returns (peak active work, responses).

    Uses the cloud backend so the thread-unsafe local llama.cpp serial lock does
    not mask the configurable gate. Waits until the gate is saturated (or all
    workers are active), then holds an observation window before releasing; that
    window is what catches an ungated endpoint overshooting the cap.
    """
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("LLM_MAX_CONCURRENT", str(max_concurrent))
    reset_inference_gate()

    state = {"active": 0, "peak": 0}
    lock = threading.Lock()
    release = threading.Event()

    def work() -> None:
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        release.wait(timeout=5)
        with lock:
            state["active"] -= 1

    install_double(work)

    responses: list = []

    def issue() -> None:
        responses.append(request())

    threads = [threading.Thread(target=issue) for _ in range(workers)]
    try:
        for thread in threads:
            thread.start()
        saturation = min(max_concurrent, workers)
        deadline = time.time() + 5.0
        while time.time() < deadline:
            with lock:
                current = state["active"]
            if current >= saturation:
                break
            time.sleep(0.02)
        # Let any ungated/slow request enter so an overshoot is observed.
        observation_until = time.time() + 0.6
        while time.time() < observation_until:
            time.sleep(0.02)
        release.set()
        for thread in threads:
            thread.join(timeout=10)
    finally:
        release.set()
    return state["peak"], responses


def test_chat_endpoint_streaming_is_bounded(client, monkeypatch):
    from svc.routers import chat as chat_router

    def install_double(work):
        def fake_turn(state):
            work()
            state["response_content"] = "pong"
            yield "pong"

        monkeypatch.setattr(chat_router, "stream_assistant_turn", fake_turn)

    peak, responses = _measure_peak(
        client,
        monkeypatch,
        install_double=install_double,
        request=lambda: client.post("/chat/messages", json={"content": "hi"}),
        max_concurrent=1,
        workers=4,
    )
    assert peak == 1
    assert len(responses) == 4
    assert all(response.status_code == 200 for response in responses)
    assert all("pong" in response.text for response in responses)


def test_onboarding_endpoint_invoke_is_bounded(client, monkeypatch):
    from agent import onboarding_graph as onboarding_module

    def install_double(work):
        def fake_invoke(state):
            work()
            return {
                "messages": [AIMessage(content="Q1?")],
                "trainee_id": "alice",
                "intake_step": 1,
                "is_complete": False,
                "profile_data": None,
            }

        monkeypatch.setattr(onboarding_module, "onboarding_graph", type("FakeGraph", (), {"invoke": staticmethod(fake_invoke)})())

    peak, responses = _measure_peak(
        client,
        monkeypatch,
        install_double=install_double,
        request=lambda: client.post("/onboarding/start"),
        max_concurrent=2,
        workers=4,
    )
    assert peak == 2
    assert len(responses) == 4
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["messages"] == ["Q1?"] for response in responses)
