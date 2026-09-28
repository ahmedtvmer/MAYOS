"""``GET /workouts/baselines``: shape, aggregates shared with commit, caller isolation (#122, ADR 042)."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.progression_engine import calculate_e1rm
from database.database_manager import DatabaseManager
from service import workouts as workouts_service
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"

#: Pinned "now" so the performed-date window never depends on the wall clock.
FIXED_NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)

CLIENT_A = "11111111-1111-4111-8111-111111111111"
CLIENT_B = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setattr(workouts_service, "_now", lambda: FIXED_NOW)
    from svc.rate_limit import limiter

    limiter._storage.reset()
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
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(client, username):
    resp = client.post("/auth/register", json={"trainee_id": username, "password": "correct-horse-1"})
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _exercise_payload(exercise_id, exercise_name):
    return {
        "exercise_id": exercise_id,
        "exercise_name": exercise_name,
        "target_sets": 3,
        "target_reps_min": 5,
        "target_reps_max": 8,
        "target_rpe": 8.5,
        "rest_seconds": 120,
        "notes": None,
    }


def _prepare_player(client, db, username="alice"):
    headers = _register(client, username)
    db.switch_user(username)
    db.ledger.upsert_player_profile({"current_goal": "Strength"})
    db.ledger.save_training_program(
        {
            "program_name": "Split",
            "weekly_frequency": 3,
            "split_type": "Full Body",
            "days": [
                {
                    "day_name": "Full A",
                    "day_order": 1,
                    "exercises": [
                        {"exercise_id": ex_id, "target_sets": 3, "target_reps_min": 5,
                         "target_reps_max": 8, "target_rpe": 8.5}
                        for ex_id in ("sq", "bp", "row")
                    ],
                }
            ],
        }
    )
    return headers, db.ledger.get_active_program().version


def _commit(client, headers, version, sets, *, client_session_id, performed_date, captured_at):
    resp = client.post(
        "/workouts/sessions",
        headers=headers,
        json={
            "day_order": 1,
            "readiness": 4,
            "session_notes": "",
            "sets": sets,
            "client_session_id": client_session_id,
            "performed_date": performed_date,
            "performed_timezone": "UTC",
            "program_version": version,
            "captured_at": captured_at,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _session_one_sets():
    return [
        {
            "exercise": _exercise_payload("sq", "Squat"),
            "sets": [
                {"weight_kg": 40.0, "reps": 5, "rpe": 6.0, "is_warmup": True},
                {"weight_kg": 100.0, "reps": 5, "rpe": 8.0},
                {"weight_kg": 90.0, "reps": 8, "rpe": 8.5},
            ],
        },
        {"exercise": _exercise_payload("bp", "Bench Press"), "sets": [{"weight_kg": 80.0, "reps": 5, "rpe": 8.0}]},
    ]


def _session_two_sets():
    return [
        {
            "exercise": _exercise_payload("sq", "Squat"),
            "sets": [
                {"weight_kg": 102.5, "reps": 5, "rpe": 8.5},
                {"weight_kg": 60.0, "reps": 10, "rpe": 9.0},
            ],
        }
    ]


def test_baselines_shape_uses_the_commit_aggregates(api):
    client, db = api
    headers, version = _prepare_player(client, db)

    first = _commit(
        client, headers, version, _session_one_sets(),
        client_session_id=CLIENT_A, performed_date="2026-09-25", captured_at="2026-09-25T11:00:00+00:00",
    )
    # The baseline session announces no record, yet its sets are already a baseline.
    assert first["new_prs"] == []

    second = _commit(
        client, headers, version, _session_two_sets(),
        client_session_id=CLIENT_B, performed_date="2026-09-26", captured_at="2026-09-26T11:00:00+00:00",
    )
    weight_event = next(event for event in second["new_prs"] if event["record_type"] == "max_weight")
    assert weight_event["prev_value"] == 100.0
    e1rm_event = next(event for event in second["new_prs"] if event["record_type"] == "max_e1rm")
    assert e1rm_event["prev_value"] == round(calculate_e1rm(100.0, 5, 8.0), 2)

    resp = client.get("/workouts/baselines", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"baselines"}
    rows = {row["exercise_id"]: row for row in body["baselines"]}
    # One row per exercise with a committed working set; 'row' was never trained.
    assert set(rows) == {"sq", "bp"}

    squat = rows["sq"]
    assert squat["sessions_logged"] == 2
    assert squat["max_weight_kg"] == 102.5
    assert squat["best_e1rm_kg"] == round(calculate_e1rm(102.5, 5, 8.5), 2)
    assert squat["last_session"] == {
        "performed_date": "2026-09-26",
        "sets": [
            {"weight_kg": 102.5, "reps": 5, "rir": 1.5},
            {"weight_kg": 60.0, "reps": 10, "rir": 1.0},
        ],
    }

    # An exercise whose only session was its first session is still a baseline row.
    bench = rows["bp"]
    assert bench["sessions_logged"] == 1
    assert bench["max_weight_kg"] == 80.0
    assert bench["best_e1rm_kg"] == round(calculate_e1rm(80.0, 5, 8.0), 2)
    assert bench["last_session"] == {
        "performed_date": "2026-09-25",
        "sets": [{"weight_kg": 80.0, "reps": 5, "rir": 2.0}],
    }

    # Warm-ups never appear in a baseline row.
    warmups = [set_ for row in body["baselines"] for set_ in row["last_session"]["sets"] if set_["weight_kg"] == 40.0]
    assert warmups == []


def test_baselines_report_unrated_sets_as_null_rir(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    _commit(
        client, headers, version, _session_one_sets(),
        client_session_id=CLIENT_A, performed_date="2026-09-25", captured_at="2026-09-25T11:00:00+00:00",
    )

    # Unrate one working set at the storage boundary (RPE stays internal).
    db.switch_user("alice")
    db.conn.execute(
        "UPDATE workout_sets SET rpe = NULL"
        " WHERE exercise_id = 'bp' AND is_warmup = 0"
    )
    db.conn.commit()

    resp = client.get("/workouts/baselines", headers=headers)
    assert resp.status_code == 200
    bench = next(row for row in resp.json()["baselines"] if row["exercise_id"] == "bp")
    assert bench["last_session"]["sets"] == [{"weight_kg": 80.0, "reps": 5, "rir": None}]
    assert bench["best_e1rm_kg"] == round(calculate_e1rm(80.0, 5, 8.5), 2)


def test_baselines_never_leak_another_players_data(api):
    client, db = api
    headers, version = _prepare_player(client, db, username="alice")
    _commit(
        client, headers, version, _session_one_sets(),
        client_session_id=CLIENT_A, performed_date="2026-09-25", captured_at="2026-09-25T11:00:00+00:00",
    )
    assert {row["exercise_id"] for row in client.get("/workouts/baselines", headers=headers).json()["baselines"]} == {
        "sq",
        "bp",
    }

    bob_headers = _register(client, "bob")
    bob = client.get("/workouts/baselines", headers=bob_headers)
    assert bob.status_code == 200
    assert bob.json() == {"baselines": []}

    assert client.get("/workouts/baselines").status_code in {401, 403}
