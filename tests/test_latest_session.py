"""Latest committed session read contract (ticket #53).

`GET /workouts/sessions/latest` returns the player's most recent committed
session identity (session id, performed date, day name, program version) so
Home can derive the next program day without relying on pruned local drafts.
It is authenticated, read-only, and scoped to the player's own ledger.
"""

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import workouts as workouts_service
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
FIXED_NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setattr(workouts_service, "_now", lambda: FIXED_NOW)
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
    cat_conn.execute(
        "INSERT INTO exercises (id, name, body_part, target_muscle) VALUES"
        " ('sq', 'Squat', 'Upper Legs', 'Quads'), ('bp', 'Bench Press', 'Chest', 'Chest'),"
        " ('row', 'Row', 'Back', 'Back');"
    )
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
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def _register(client, username, password="correct-horse-1"):
    resp = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _program_payload(day_name="Full A"):
    return {
        "program_name": "Assigned Split",
        "weekly_frequency": 1,
        "split_type": "Full Body",
        "days": [
            {
                "day_name": day_name,
                "day_order": 1,
                "exercises": [
                    {
                        "exercise_id": "sq",
                        "target_sets": 3,
                        "target_reps_min": 5,
                        "target_reps_max": 8,
                        "target_rpe": 8.5,
                        "rest_seconds": 120,
                    },
                    {
                        "exercise_id": "bp",
                        "target_sets": 3,
                        "target_reps_min": 5,
                        "target_reps_max": 8,
                        "target_rpe": 8.5,
                        "rest_seconds": 120,
                    },
                    {
                        "exercise_id": "row",
                        "target_sets": 3,
                        "target_reps_min": 5,
                        "target_reps_max": 8,
                        "target_rpe": 8.5,
                        "rest_seconds": 120,
                    },
                ],
            }
        ],
    }


def _prepare_player(client, db, username="p1", day_name="Full A"):
    player = _register(client, username)
    headers = _authed(player["access_token"])
    db.switch_user(username)
    db.upsert_user_profile({"current_goal": "Strength"})
    db.save_training_program(_program_payload(day_name))
    version = db.get_active_program().version
    return headers, version


def _commit(client, headers, version, *, date, client_id):
    body = {
        "day_order": 1,
        "readiness": 4,
        "session_notes": "",
        "sets": [
            {
                "exercise": {
                    "exercise_id": "sq",
                    "exercise_name": "Squat",
                    "target_sets": 3,
                    "target_reps_min": 5,
                    "target_reps_max": 8,
                    "target_rpe": 8.5,
                    "rest_seconds": 120,
                    "notes": None,
                },
                "sets": [{"weight_kg": 100.0, "reps": 5, "rpe": 8.0}],
            }
        ],
        "client_session_id": client_id,
        "performed_date": date,
        "performed_timezone": "UTC",
        "program_version": version,
        "captured_at": f"{date}T11:30:00+00:00",
    }
    resp = client.post("/workouts/sessions", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_latest_session_requires_auth(api):
    client, _ = api
    assert client.get("/workouts/sessions/latest").status_code == 401


def test_latest_session_none_is_404(api):
    client, db = api
    headers, _ = _prepare_player(client, db)
    resp = client.get("/workouts/sessions/latest", headers=headers)
    assert resp.status_code == 404, resp.text


def test_latest_session_returns_the_most_recent_committed(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    first = _commit(client, headers, version, date="2026-09-24", client_id="11111111-1111-4111-8111-111111111111")
    latest = _commit(client, headers, version, date="2026-09-26", client_id="22222222-2222-4222-8222-222222222222")
    _commit(client, headers, version, date="2026-09-25", client_id="33333333-3333-4333-8333-333333333333")

    resp = client.get("/workouts/sessions/latest", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == latest["session_id"]
    assert body["session_id"] != first["session_id"]
    assert body["session_date"] == "2026-09-26"
    assert body["split_name"] == "Full A"
    assert body["day_order"] is None  # not stored on the ledger
    assert body["program_version"] == version


def test_latest_session_is_isolated_per_account(api):
    client, db = api
    headers_a, version_a = _prepare_player(client, db, username="alice", day_name="Full A")
    headers_b, _ = _prepare_player(client, db, username="bob", day_name="Full B")

    # Bob has no sessions yet.
    assert client.get("/workouts/sessions/latest", headers=headers_b).status_code == 404

    alice = _commit(client, headers_a, version_a, date="2026-09-26", client_id="44444444-4444-4444-8444-444444444444")

    alice_latest = client.get("/workouts/sessions/latest", headers=headers_a).json()
    assert alice_latest["session_id"] == alice["session_id"]
    assert alice_latest["split_name"] == "Full A"
    # Bob still sees none — Alice's session is not visible.
    assert client.get("/workouts/sessions/latest", headers=headers_b).status_code == 404
