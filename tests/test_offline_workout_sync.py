"""Offline workout sync contract tests (ticket #34 / ADR 020/033).

A draft captured on the device commits idempotently: a retry or a reconciled
lost response produces exactly one session with its sets and derived records,
all in one ledger transaction. Validation is timezone-correct and time-bounded.
A draft captured against the current program commits against it; a draft
captured against an older version that still exists in the ledger commits as
history without rewriting the newer active program, and both the player and the
active coach see the version difference (ADR 034). A captured version that is
newer than the active one or absent from the ledger is refused with 409.
"""

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import ProgramDaySchema, ProgramExerciseSchema
from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import coach_history as coach_history_service
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
        default_ledger_id="bootstrap",
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


def _program_payload_v2():
    """A structurally different newer program: another day name, exercises, and targets."""
    return {
        "program_name": "Assigned Split v2",
        "weekly_frequency": 3,
        "split_type": "Full Body",
        "days": [
            {
                "day_name": "Full B",
                "day_order": 1,
                "exercises": [
                    {"exercise_id": "ohp", "target_sets": 4, "target_reps_min": 4, "target_reps_max": 6, "target_rpe": 8.0},
                    {"exercise_id": "bp", "target_sets": 2, "target_reps_min": 6, "target_reps_max": 10, "target_rpe": 8.0},
                    {"exercise_id": "sq", "target_sets": 4, "target_reps_min": 4, "target_reps_max": 6, "target_rpe": 8.0},
                ],
            }
        ],
    }


def _program_row_snapshot(db, program_id):
    """Every persisted day and exercise row for one program, for an unchanged check."""
    days = db.conn.execute(
        "SELECT id, day_name, day_order, warmup_json, cardio FROM program_days"
        " WHERE program_id = ? ORDER BY day_order, id",
        (program_id,),
    ).fetchall()
    exercises = db.conn.execute(
        "SELECT pe.id, pe.day_id, pe.exercise_id, pe.order_in_day, pe.target_sets,"
        " pe.target_reps_min, pe.target_reps_max, pe.target_rpe, pe.rest_seconds, pe.notes,"
        " pe.slot_key, pe.warmup_sets"
        " FROM program_exercises pe JOIN program_days pd ON pe.day_id = pd.id"
        " WHERE pd.program_id = ? ORDER BY pe.day_id, pe.order_in_day, pe.id",
        (program_id,),
    ).fetchall()
    return [tuple(row) for row in days], [tuple(row) for row in exercises]


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
    db.ledger.upsert_user_profile({"current_goal": "Strength"})
    db.ledger.save_training_program(_program_payload())
    version = db.ledger.get_active_program().version
    return headers, version


def _make_coach(client, db, username, capacity=5):
    """Registers a player, grants the coach capability, and sets roster capacity."""
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username)
    assert issued["ok"], issued
    assert (
        client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code
        == 200
    )
    assert (
        client.put(
            "/coach/profile",
            headers=headers,
            json={"display_name": f"Coach {username}", "bio": "b", "specialization": "s", "capacity": capacity},
        ).status_code
        == 200
    )
    return headers


def _assign(client, coach_headers, player_headers):
    """Issues an invite and has the player accept it; returns the assignment id."""
    invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert invite.status_code == 200, invite.text
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite.json()["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    return redeemed.json()["assignment"]["assignment_id"]


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
    assert body["program_version"] == version
    assert body["active_program_version_at_sync"] == version
    assert body["is_historical_program"] is False

    db.switch_user("p1")
    row = db.conn.execute(
        "SELECT client_session_id, session_date, performed_timezone, program_version,"
        " active_program_version_at_sync, captured_at, uploaded_at"
        " FROM workout_sessions WHERE id = ?",
        (body["session_id"],),
    ).fetchone()
    assert row["client_session_id"] == CLIENT_ID
    assert row["session_date"] == "2026-09-26"
    assert row["performed_timezone"] == "UTC"
    assert row["program_version"] == version
    assert row["active_program_version_at_sync"] == version
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
    # The stored response is overlaid with the live session date and correction
    # history (ADR 035); every original field is unchanged.
    body = found.json()
    assert {key: value for key, value in body.items() if key in committed.json()} == committed.json()
    assert body["session_id"] == committed.json()["session_id"]
    assert body["session_date"] == "2026-09-26"
    assert body["edited_at"] is None
    assert body["corrections"] == []


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


def test_newer_program_version_is_refused_and_writes_nothing(api):
    client, db = api
    headers, version = _prepare_player(client, db)

    resp = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version + 1))
    assert resp.status_code == 409, resp.text
    assert resp.json() == {"error": "program_version_mismatch", "active_version": version}
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 0


def test_unknown_older_program_version_is_refused(api):
    """An older version that is not in the ledger cannot be resolved as history."""
    client, db = api
    headers, version = _prepare_player(client, db)

    # Version 0 predates every stored program row.
    resp = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=0))
    assert resp.status_code == 409, resp.text
    assert resp.json() == {"error": "program_version_mismatch", "active_version": version}
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0


def test_older_program_version_syncs_as_history_without_rewriting_active_program(api):
    client, db = api
    headers, captured_version = _prepare_player(client, db)

    db.switch_user("p1")
    active_program_id = db.ledger.save_training_program(_program_payload_v2())
    active_version = db.ledger.get_active_program().version
    assert active_version == captured_version + 1
    v2_rows_before = _program_row_snapshot(db, active_program_id)

    resp = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=captured_version))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["program_version"] == captured_version
    assert body["active_program_version_at_sync"] == active_version
    assert body["is_historical_program"] is True
    # Resolved against v1's day plan, not the active v2 plan: v1 prescribed
    # exactly the three performed movements, while v2 prescribes OHP and drops Row.
    assert [summary["name"] for summary in body["exercise_summaries"]] == ["Squat", "Bench Press", "Row"]
    assert body["divergences"] == []

    db.switch_user("p1")
    row = db.conn.execute(
        "SELECT split_name, program_version, active_program_version_at_sync"
        " FROM workout_sessions WHERE id = ?",
        (body["session_id"],),
    ).fetchone()
    assert row["split_name"] == "Full A"
    assert row["program_version"] == captured_version
    assert row["active_program_version_at_sync"] == active_version
    # The captured prescription is retained and the newer program stays active,
    # with every v2 program row byte-for-byte unchanged.
    assert db.ledger.get_program_by_version(captured_version) is not None
    assert db.ledger.get_active_program().version == active_version
    assert _program_row_snapshot(db, active_program_id) == v2_rows_before
    assert (
        db.conn.execute("SELECT COUNT(*) FROM training_programs WHERE is_active = 1").fetchone()[0] == 1
    )


def test_older_program_version_replay_is_unchanged(api):
    """Idempotent replay behaviour is identical for a historical-version commit (#34)."""
    client, db = api
    headers, captured_version = _prepare_player(client, db)
    db.switch_user("p1")
    db.ledger.save_training_program(_program_payload())

    first = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=captured_version))
    assert first.status_code == 201, first.text
    assert first.json()["is_historical_program"] is True

    retry = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=captured_version))
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()

    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 1


#: Every coach read that can expose the assigned player's sessions or exercise history.
COACH_SESSION_READS = (
    "/player/summary",
    "/player/personal-records",
    "/player/exercises",
    "/player/exercises/sq/history",
    "/check-ins",
)


def test_revoked_coach_cannot_read_a_workout_synced_after_revocation(api):
    client, db = api
    headers, captured_version = _prepare_player(client, db, username="p1")

    coach_a = _make_coach(client, db, "coachA")
    assignment_a = _assign(client, coach_a, headers)
    revoked = client.post(f"/coach/assignments/{assignment_a}/revoke", headers=coach_a)
    assert revoked.status_code == 200, revoked.text

    # A newer program is published after the coach is revoked but before the
    # captured draft syncs; the sync still commits as history.
    db.switch_user("p1")
    db.ledger.save_training_program(_program_payload())
    synced = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=captured_version))
    assert synced.status_code == 201, synced.text

    # The revoked coach is denied on every session-exposing coach read.
    for suffix in COACH_SESSION_READS:
        denied = client.get(f"/coach/assignments/{assignment_a}{suffix}", headers=coach_a)
        assert denied.status_code == 403, (suffix, denied.text)
        assert denied.json()["detail"] == coach_history_service.DENIED_ERROR

    # A coach currently assigned can read the same workout and sees the difference.
    coach_b = _make_coach(client, db, "coachB")
    assignment_b = _assign(client, coach_b, headers)
    summary = client.get(f"/coach/assignments/{assignment_b}/player/summary", headers=coach_b)
    assert summary.status_code == 200, summary.text
    latest = summary.json()["latest_session"]
    assert latest["program_version"] == captured_version
    assert latest["active_program_version_at_sync"] == captured_version + 1
    assert latest["is_historical_program"] is True
    recent = summary.json()["recent_sessions"][0]
    assert recent["program_version"] == captured_version
    assert recent["active_program_version_at_sync"] == captured_version + 1
    assert recent["is_historical_program"] is True
    # The other session-exposing reads the active coach is allowed to make still work.
    records = client.get(
        f"/coach/assignments/{assignment_b}/player/personal-records", headers=coach_b
    )
    assert records.status_code == 200, records.text
    assert any(record["exercise_id"] == "sq" for record in records.json())
    exercises = client.get(f"/coach/assignments/{assignment_b}/player/exercises", headers=coach_b)
    assert exercises.status_code == 200, exercises.text
    assert {entry["id"] for entry in exercises.json()["exercises"]} >= {"sq", "bp", "row"}
    history = client.get(
        f"/coach/assignments/{assignment_b}/player/exercises/sq/history", headers=coach_b
    )
    assert history.status_code == 200, history.text
    assert history.json()["history"]
    check_ins = client.get(f"/coach/assignments/{assignment_b}/check-ins", headers=coach_b)
    assert check_ins.status_code == 200, check_ins.text


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


def test_performed_date_after_the_capture_date_is_refused(api):
    """A draft can never claim a performed date later than when it was captured."""
    client, db = api
    headers, version = _prepare_player(client, db)
    # Captured yesterday (2026-09-25); the ceiling is the capture's local date.
    body = _sync_body(
        client_session_id="55555555-5555-4555-8555-555555555555",
        version=version,
        performed_date="2026-09-26",
        captured_at="2026-09-25T11:00:00+00:00",
    )
    resp = client.post("/workouts/sessions", headers=headers, json=body)
    assert resp.status_code == 400, resp.text
    assert "capture" in resp.json()["detail"].lower()
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0


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
