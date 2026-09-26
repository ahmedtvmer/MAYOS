"""Offline workout sync contract tests (ticket #34 / ADR 020/033).

A draft captured on the device commits idempotently: a retry or a reconciled
lost response produces exactly one session with its sets and derived records,
all in one ledger transaction. Validation is timezone-correct and time-bounded,
and a captured program version that no longer matches the active program is
refused with 409 pending ticket #35.
"""

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import ProgramDaySchema, ProgramExerciseSchema
from database.database_manager import DatabaseManager
from service import workouts as workouts_service
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"

#: Pinned "now" so validation never depends on the wall clock (UTC Saturday).
FIXED_NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
CLIENT_ID = "11111111-1111-4111-8111-111111111111"


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
        " ('row', 'Row', 'Back', 'Back'), ('ohp', 'Overhead Press', 'Shoulders', 'Shoulders');"
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


def _program_payload():
    return {
        "program_name": "Assigned Split",
        "weekly_frequency": 3,
        "split_type": "Full Body",
        "days": [
            {
                "day_name": "Full A",
                "day_order": 1,
                "exercises": [
                    {"exercise_id": "sq", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                    {"exercise_id": "bp", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                    {"exercise_id": "row", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                ],
            }
        ],
    }


def _sets_body():
    return [
        {"exercise": _exercise_payload("sq", "Squat"), "sets": [{"weight_kg": 100.0, "reps": 5, "rpe": 8.0}]},
        {"exercise": _exercise_payload("bp", "Bench Press"), "sets": [{"weight_kg": 80.0, "reps": 5, "rpe": 8.0}]},
        {"exercise": _exercise_payload("row", "Row"), "sets": [{"weight_kg": 60.0, "reps": 8, "rpe": 8.5}]},
    ]


def _prepare_player(client, db, username="p1"):
    player = _register(client, username)
    headers = _authed(player["access_token"])
    db.switch_user(username)
    db.upsert_user_profile({"current_goal": "Strength"})
    db.save_training_program(_program_payload())
    version = db.get_active_program().version
    return headers, version


def _sync_body(*, client_session_id=CLIENT_ID, version, day_order=1, performed_date="2026-09-26",
               performed_timezone="UTC", captured_at="2026-09-26T11:30:00+00:00"):
    return {
        "day_order": day_order,
        "readiness": 4,
        "session_notes": "",
        "sets": _sets_body(),
        "client_session_id": client_session_id,
        "performed_date": performed_date,
        "performed_timezone": performed_timezone,
        "program_version": version,
        "captured_at": captured_at,
    }


def test_first_commit_returns_201_and_records_sync_fields(api):
    client, db = api
    headers, version = _prepare_player(client, db)

    resp = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["session_id"]

    db.switch_user("p1")
    row = db.conn.execute(
        "SELECT client_session_id, session_date, performed_timezone, program_version, captured_at, uploaded_at"
        " FROM workout_sessions WHERE id = ?",
        (body["session_id"],),
    ).fetchone()
    assert row["client_session_id"] == CLIENT_ID
    assert row["session_date"] == "2026-09-26"
    assert row["performed_timezone"] == "UTC"
    assert row["program_version"] == version
    assert row["captured_at"] == "2026-09-26T11:30:00+00:00"
    assert row["uploaded_at"] == FIXED_NOW.isoformat()


def test_identical_retry_returns_200_same_body_and_one_session(api):
    client, db = api
    headers, version = _prepare_player(client, db)

    first = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert first.status_code == 201, first.text
    retry = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()

    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sets").fetchone()[0] == 3
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM personal_records").fetchone()[0] == 6


def test_committed_client_id_replays_after_catalog_exercise_disappears(api):
    """A retry replays the stored response before any mutable catalog validation (ADR 033)."""
    client, db = api
    headers, version = _prepare_player(client, db)

    first = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert first.status_code == 201, first.text

    # The catalog changes after the commit: the prescribed exercise is gone.
    db.catalog_conn.execute("DELETE FROM exercises WHERE id = 'sq'")
    db.catalog_conn.commit()

    retry = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 1


def test_uncommitted_client_id_still_validates_the_catalog(api):
    """Replay precedence must not let a genuinely new commit skip catalog validation."""
    client, db = api
    headers, version = _prepare_player(client, db)

    db.catalog_conn.execute("DELETE FROM exercises WHERE id = 'sq'")
    db.catalog_conn.commit()

    resp = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert resp.status_code == 400, resp.text
    assert "unknown exercise" in resp.json()["detail"].lower()
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0


def test_failed_commit_writes_nothing_and_retry_succeeds(api, monkeypatch):
    client, db = api
    headers, version = _prepare_player(client, db)

    original = workouts_service.evaluate_session_prs

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated failure mid-commit")

    monkeypatch.setattr(workouts_service, "evaluate_session_prs", _boom)
    with pytest.raises(RuntimeError, match="simulated failure"):
        client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))

    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sets").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 0

    monkeypatch.setattr(workouts_service, "evaluate_session_prs", original)
    retry = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert retry.status_code == 201, retry.text
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 1


def test_status_lookup_404_then_200(api):
    client, db = api
    headers, version = _prepare_player(client, db)

    missing = client.get(f"/workouts/sessions/by-client-id/{CLIENT_ID}", headers=headers)
    assert missing.status_code == 404

    committed = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert committed.status_code == 201, committed.text

    found = client.get(f"/workouts/sessions/by-client-id/{CLIENT_ID}", headers=headers)
    assert found.status_code == 200
    assert found.json() == committed.json()


def test_legacy_commit_without_client_session_id_still_works(api):
    client, db = api
    headers, _ = _prepare_player(client, db)

    resp = client.post(
        "/workouts/sessions",
        headers=headers,
        json={"day_order": 1, "readiness": 4, "session_notes": "", "sets": _sets_body()},
    )
    assert resp.status_code == 201, resp.text
    db.switch_user("p1")
    row = db.conn.execute("SELECT client_session_id FROM workout_sessions").fetchone()
    assert row["client_session_id"] is None


def test_program_version_mismatch_returns_409_and_writes_nothing(api):
    client, db = api
    headers, version = _prepare_player(client, db)

    resp = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version + 1))
    assert resp.status_code == 409, resp.text
    assert resp.json() == {"error": "program_version_mismatch", "active_version": version}
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 0


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"performed_date": "2026-09-27"}, "future"),
        ({"performed_date": "2026-09-22"}, "more than 3 days"),
        ({"performed_date": "2026/09/26"}, "ISO date"),
        ({"performed_timezone": "Mars/Olympus"}, "Unknown timezone"),
        ({"performed_timezone": ""}, "timezone is required"),
        ({"captured_at": "2026-09-26T12:21:00+00:00"}, "future"),
        ({"captured_at": "2026-09-26T12:00:00"}, "timezone offset"),
        ({"client_session_id": "not-a-uuid"}, "UUID"),
    ],
)
def test_sync_validation_errors_are_400(api, overrides, expected):
    client, db = api
    headers, version = _prepare_player(client, db)
    body = _sync_body(version=version)
    body.update(overrides)

    resp = client.post("/workouts/sessions", headers=headers, json=body)
    assert resp.status_code == 400, resp.text
    assert expected.lower() in resp.json()["detail"].lower()
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0


def test_missing_program_version_is_400(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    body = _sync_body(version=version)
    del body["program_version"]

    resp = client.post("/workouts/sessions", headers=headers, json=body)
    assert resp.status_code == 400, resp.text
    assert "program_version is required" in resp.json()["detail"]


@pytest.mark.parametrize(
    "timezone,local_today",
    [("Pacific/Kiritimati", "2026-09-27"), ("Pacific/Honolulu", "2026-09-26")],
)
def test_performed_date_uses_player_local_today_across_utc_boundary(api, timezone, local_today):
    client, db = api
    headers, version = _prepare_player(client, db)
    # FIXED_NOW is 2026-09-26T12:00Z: UTC+14 is already 2026-09-27, UTC-10 is 2026-09-26.
    ok = _sync_body(version=version, performed_timezone=timezone, performed_date=local_today)
    assert client.post("/workouts/sessions", headers=headers, json=ok).status_code == 201

    other_id = "22222222-2222-4222-8222-222222222222"
    ahead = (datetime.fromisoformat(local_today) + timedelta(days=1)).date().isoformat()
    rejected = _sync_body(
        client_session_id=other_id, version=version, performed_timezone=timezone, performed_date=ahead
    )
    resp = client.post("/workouts/sessions", headers=headers, json=rejected)
    assert resp.status_code == 400
    assert "future" in resp.json()["detail"].lower()


@pytest.mark.parametrize("timezone", ["Pacific/Kiritimati", "Pacific/Honolulu"])
def test_backdate_window_uses_local_capture_date(api, timezone):
    client, db = api
    headers, version = _prepare_player(client, db)
    captured_local = datetime(2026, 9, 26, 11, 30, tzinfo=UTC).astimezone(
        workouts_service.ZoneInfo(timezone)
    ).date()
    at_limit = (captured_local - timedelta(days=3)).isoformat()
    beyond = (captured_local - timedelta(days=4)).isoformat()

    ok = _sync_body(
        client_session_id="33333333-3333-4333-8333-333333333333",
        version=version,
        performed_timezone=timezone,
        performed_date=at_limit,
    )
    assert client.post("/workouts/sessions", headers=headers, json=ok).status_code == 201

    rejected = _sync_body(
        client_session_id="44444444-4444-4444-8444-444444444444",
        version=version,
        performed_timezone=timezone,
        performed_date=beyond,
    )
    resp = client.post("/workouts/sessions", headers=headers, json=rejected)
    assert resp.status_code == 400
    assert "3 days" in resp.json()["detail"]


def test_captured_at_within_clock_skew_is_accepted(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    body = _sync_body(version=version, captured_at=(FIXED_NOW + timedelta(minutes=5)).isoformat())
    assert client.post("/workouts/sessions", headers=headers, json=body).status_code == 201


def test_concurrent_duplicate_submission_commits_one_session(api):
    client, db = api
    _headers, version = _prepare_player(client, db)
    day_plan = ProgramDaySchema(
        day_name="Full A",
        day_order=1,
        exercises=[
            ProgramExerciseSchema(exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8),
            ProgramExerciseSchema(exercise_id="bp", exercise_name="Bench Press", target_reps_min=5, target_reps_max=8),
            ProgramExerciseSchema(exercise_id="row", exercise_name="Row", target_reps_min=5, target_reps_max=8),
        ],
    )
    sets_payload = [
        {
            "exercise": day_plan.exercises[0],
            "sets": [{"weight_kg": 100.0, "reps": 5, "rpe": 8.0}],
            "previous_perf": [],
        }
    ]

    barrier = threading.Barrier(2)
    outcomes = []
    errors = []

    def _worker():
        try:
            barrier.wait()
            outcomes.append(
                workouts_service.commit_logged_session(
                    db,
                    "p1",
                    day_plan.day_order,
                    4,
                    "",
                    sets_payload,
                    sync=workouts_service.SyncMetadata(
                        client_session_id=CLIENT_ID,
                        performed_date="2026-09-26",
                        performed_timezone="UTC",
                        program_version=version,
                        captured_at="2026-09-26T11:30:00+00:00",
                    ),
                    now_iso="2026-09-26T12:00:00+00:00",
                )
            )
        except Exception as exc:  # pragma: no cover - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(outcomes) == 2
    assert sum(1 for outcome in outcomes if outcome.created) == 1
    assert len({outcome.body["session_id"] for outcome in outcomes}) == 1

    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 1


def test_warmup_flag_is_honored_in_ledger_and_excluded_from_prs(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    body = _sync_body(version=version)
    body["sets"][0]["sets"] = [
        {"weight_kg": 40.0, "reps": 5, "rpe": 6.0, "is_warmup": True},
        {"weight_kg": 100.0, "reps": 5, "rpe": 8.0, "is_warmup": False},
    ]

    resp = client.post("/workouts/sessions", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    session_id = resp.json()["session_id"]

    db.switch_user("p1")
    rows = db.conn.execute(
        "SELECT weight_kg, is_warmup FROM workout_sets WHERE session_id = ? AND exercise_id = 'sq' ORDER BY set_index",
        (session_id,),
    ).fetchall()
    assert [(row["weight_kg"], row["is_warmup"]) for row in rows] == [(40.0, 1), (100.0, 0)]
    # The warm-up set is excluded from PR detection: only the 100kg working set can PR.
    prs = db.conn.execute(
        "SELECT value FROM personal_records WHERE exercise_id = 'sq' AND record_type = 'max_weight'"
    ).fetchall()
    assert [row["value"] for row in prs] == [100.0]


def test_unknown_exercise_id_is_400(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    body = _sync_body(version=version)
    body["sets"][0]["exercise"]["exercise_id"] = "not-a-catalog-exercise"

    resp = client.post("/workouts/sessions", headers=headers, json=body)
    assert resp.status_code == 400, resp.text
    assert "unknown exercise" in resp.json()["detail"].lower()
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0


def test_player_b_cannot_read_player_a_commit_by_client_id(api):
    client, db = api
    headers_a, version = _prepare_player(client, db, username="p1")
    committed = client.post("/workouts/sessions", headers=headers_a, json=_sync_body(version=version))
    assert committed.status_code == 201, committed.text

    headers_b, _ = _prepare_player(client, db, username="p2")
    resp = client.get(f"/workouts/sessions/by-client-id/{CLIENT_ID}", headers=headers_b)
    assert resp.status_code == 404


def test_sync_fields_without_client_session_id_are_422(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    body = _sync_body(version=version)
    del body["client_session_id"]

    resp = client.post("/workouts/sessions", headers=headers, json=body)
    assert resp.status_code == 422, resp.text


def test_catalog_exercise_search_returns_matches_for_an_offline_unplanned_pick(api):
    client, db = api
    headers, _ = _prepare_player(client, db)

    resp = client.get("/workouts/exercises", headers=headers, params={"query": "squat"})
    assert resp.status_code == 200, resp.text
    matches = resp.json()["exercises"]
    assert [entry["id"] for entry in matches] == ["sq"]
    assert matches[0]["name"] == "Squat"


def test_catalog_exercise_search_requires_authentication(api):
    client, _ = api

    resp = client.get("/workouts/exercises", params={"query": "squat"})
    assert resp.status_code == 401, resp.text
