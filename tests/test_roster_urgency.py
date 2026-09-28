"""Roster urgency order and roster entry basis contract tests (ticket #118).

Exercises the public FastAPI surface against real temporary SQLite catalogs and
player ledgers with a mocked model. Covers the new ``pending_requests`` and
``last_workout_on`` roster fields, the server-side roster urgency order end to
end (each key and its tie-break), the attendance seed at redemption, and that
the enriched roster read still mounts no player ledger.
"""

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema
from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import workouts as workouts_service
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
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
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db, tmp_path / "users"
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(client, username, password="correct-horse-1"):
    resp = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _make_coach(client, db, username, capacity=10):
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username)
    assert issued["ok"], issued
    assert client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code == 200
    assert (
        client.put(
            "/coach/profile",
            headers=headers,
            json={"display_name": f"Coach {username}", "bio": "b", "specialization": "s", "capacity": capacity},
        ).status_code
        == 200
    )
    return headers, db.get_active_account_by_username(username)["account_id"]


def _assign(api, player_name, coach_headers, player_headers=None):
    """Assigns ``player_name`` to the coach; returns the player's handle."""
    client, db, _ = api
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    if player_headers is None:
        player = _register(client, player_name)
        player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem", headers=player_headers, json={"token": token, "consent": True}
    )
    assert redeemed.status_code == 200, redeemed.text
    account = db.get_active_account_by_username(player_name)
    return {
        "headers": player_headers,
        "assignment_id": redeemed.json()["assignment"]["assignment_id"],
        "account_id": account["account_id"],
        "ledger_id": account["ledger_id"],
    }


def _roster(client, coach_headers):
    response = client.get("/coach/assignments", headers=coach_headers)
    assert response.status_code == 200, response.text
    return response.json()["assignments"]


def _day_plan():
    return ProgramDaySchema(
        day_name="Full A",
        day_order=1,
        exercises=[
            ProgramExerciseSchema(exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8),
            ProgramExerciseSchema(exercise_id="bp", exercise_name="Bench Press", target_reps_min=5, target_reps_max=8),
            ProgramExerciseSchema(exercise_id="row", exercise_name="Row", target_reps_min=5, target_reps_max=8),
        ],
    )


def _seed_workout(db, player, on):
    """Commits one real session dated ``on`` through the production hook path."""
    day_plan = _day_plan()
    workouts_service.commit_session(
        db,
        player["ledger_id"],
        day_plan,
        readiness=4,
        session_notes="",
        sets_by_exercise=[
            {"exercise": day_plan.exercises[0], "sets": [{"weight_kg": 100.0, "reps": 5, "rpe": 8.0}]}
        ],
        now_iso=f"{on}T10:00:00+00:00",
        today_date=on,
        account_id=player["account_id"],
    )


def _coach_generation(db, monkeypatch):
    def fake(**kwargs):
        program = GeneratedProgramSchema(
            program_name="Coach Plan",
            split_type="Full Body",
            weekly_frequency=1,
            days=[_day_plan()],
        )
        kwargs["ledger"].save_training_program(
            program.model_dump(),
            published_by_coach_account_id=kwargs.get("published_by_coach_account_id"),
        )
        return program, "md"

    monkeypatch.setattr("service.coach_programs.generate_program_pipeline", fake)


def _create_request(api, coach_headers, player, monkeypatch):
    """Publishes a coach program to the player, then records a pending request."""
    client, db, _ = api
    _coach_generation(db, monkeypatch)
    published = client.post(
        f"/coach/assignments/{player['assignment_id']}/program", headers=coach_headers, json={}
    )
    assert published.status_code == 200, published.text
    created = client.post(
        "/assignments/me/program-requests",
        headers=player["headers"],
        json={
            "kind": "exercise_substitution",
            "day_name": "Full A",
            "exercise_id": "sq",
            "replacement_exercise_id": "ohp",
            "reason": "prefer a variation",
        },
    )
    assert created.status_code == 200, created.text
    return created.json()


def _seed_alert(db, coach_account_id, player, state="new"):
    """Writes one catalog-side coach alert directly, in the requested state."""
    now_iso = datetime.now(UTC).isoformat()
    alert_id = uuid.uuid4().hex
    db.insert_coach_alert(
        alert_id,
        player["assignment_id"],
        coach_account_id,
        player["account_id"],
        "missed_expected_days",
        "2026-09-01",
        {"streak_start_date": "2026-09-01", "last_missed_date": "2026-09-02", "missed_count": 2},
        now_iso,
    )
    if state == "acknowledged":
        acknowledged = db.acknowledge_coach_alert(alert_id, coach_account_id, now_iso)
        assert acknowledged is not None and acknowledged["state"] == "acknowledged"
    return alert_id


def _backdate_start(db, assignment_id, days):
    """Moves the assignment's start ``days`` into the past to shape its follow-up date."""
    started_at = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    db.catalog_conn.execute(
        "UPDATE assignments SET started_at = ? WHERE assignment_id = ?",
        (started_at, assignment_id),
    )
    db.catalog_conn.commit()


# --------------------------------------------------------------------------
# Roster entry basis: pending_requests and last_workout_on
# --------------------------------------------------------------------------


def test_roster_entry_reports_pending_requests_and_last_workout_on(api, monkeypatch):
    client, db, _ = api
    coach_headers, _ = _make_coach(client, db, "coach", capacity=5)
    player = _assign(api, "p1", coach_headers)

    _seed_workout(db, player, "2026-09-20")
    rows = _roster(client, coach_headers)
    assert len(rows) == 1
    assert rows[0]["last_workout_on"] == "2026-09-20"
    assert rows[0]["pending_requests"] == 0

    request_id = _create_request(api, coach_headers, player, monkeypatch)["request_id"]
    rows = _roster(client, coach_headers)
    assert rows[0]["pending_requests"] == 1
    assert rows[0]["last_workout_on"] == "2026-09-20"

    # Resolving the request clears the pending count; the workout date stands.
    declined = client.post(
        f"/coach/assignments/{player['assignment_id']}/program-requests/{request_id}/decline",
        headers=coach_headers,
        json={"response": "Keep the squat."},
    )
    assert declined.status_code == 200, declined.text
    rows = _roster(client, coach_headers)
    assert rows[0]["pending_requests"] == 0
    assert rows[0]["last_workout_on"] == "2026-09-20"


def test_roster_read_with_new_fields_mounts_no_player_ledger(api, monkeypatch):
    client, db, _ = api
    coach_headers, _ = _make_coach(client, db, "coach", capacity=5)
    player = _assign(api, "p1", coach_headers)
    _seed_workout(db, player, "2026-09-20")
    _publish_coach_program(api, coach_headers, player, monkeypatch)

    mounted: list[str] = []
    real_open_ledger = db.open_ledger

    def spy(ledger_id):
        mounted.append(str(ledger_id))
        return real_open_ledger(ledger_id)

    monkeypatch.setattr(db, "open_ledger", spy)

    rows = _roster(client, coach_headers)
    assert rows[0]["last_workout_on"] == "2026-09-20"
    assert rows[0]["pending_requests"] == 0
    # The program name comes from the catalog cache, not a fresh ledger read.
    assert rows[0]["program_name"] == "Coach Plan"
    assert mounted == ["coach"]


def test_assignment_redemption_seeds_the_last_workout_date_immediately(api):
    client, db, _ = api
    coach_headers, _ = _make_coach(client, db, "coach", capacity=5)

    # The player trains before the assignment exists, so no evaluation has run.
    registered = _register(client, "p1")
    account = db.get_active_account_by_username("p1")
    _seed_workout(
        db,
        {"ledger_id": account["ledger_id"], "account_id": account["account_id"]},
        "2026-09-15",
    )
    coach_account_id = db.get_active_account_by_username("coach")["account_id"]
    assert db.list_roster_workout_basis(coach_account_id) == {}

    _assign(api, "p1", coach_headers, player_headers=_authed(registered["access_token"]))
    rows = _roster(client, coach_headers)
    assert rows[0]["last_workout_on"] == "2026-09-15"


# --------------------------------------------------------------------------
# Roster urgency order, end to end
# --------------------------------------------------------------------------


def test_pending_requests_and_new_alerts_rank_first_and_acknowledged_do_not(api, monkeypatch):
    client, db, _ = api
    coach_headers, coach_account_id = _make_coach(client, db, "coach", capacity=10)
    _assign(api, "alice", coach_headers)
    alerted = _assign(api, "bob", coach_headers)
    requested = _assign(api, "carol", coach_headers)
    acknowledged = _assign(api, "dave", coach_headers)

    _seed_alert(db, coach_account_id, alerted, state="new")
    _seed_alert(db, coach_account_id, acknowledged, state="acknowledged")
    _create_request(api, coach_headers, requested, monkeypatch)

    rows = _roster(client, coach_headers)
    assert [(row["player_username"], row["alerts_new"], row["pending_requests"]) for row in rows] == [
        ("bob", 1, 0),
        ("carol", 0, 1),
        ("alice", 0, 0),
        ("dave", 0, 0),
    ]


def test_missed_streak_breaks_the_alert_and_request_tie(api, monkeypatch):
    client, db, _ = api
    coach_headers, _ = _make_coach(client, db, "coach", capacity=10)
    streaked = _assign(api, "zoe", coach_headers)
    requested = _assign(api, "ann", coach_headers)

    _create_request(api, coach_headers, streaked, monkeypatch)
    _create_request(api, coach_headers, requested, monkeypatch)
    db.upsert_roster_attendance(
        streaked["assignment_id"], 3, datetime.now(UTC).isoformat()
    )

    rows = _roster(client, coach_headers)
    # Equal on key 1; the streak outranks the username tie-break ("ann" < "zoe").
    assert [row["player_username"] for row in rows] == ["zoe", "ann"]
    assert rows[0]["current_missed_streak"] == 3
    assert rows[1]["current_missed_streak"] == 0


def test_follow_up_order_is_overdue_then_today_then_not_due(api):
    client, db, _ = api
    coach_headers, _ = _make_coach(client, db, "coach", capacity=10)
    overdue = _assign(api, "zoe", coach_headers)
    due_today = _assign(api, "mia", coach_headers)
    not_due = _assign(api, "ann", coach_headers)

    # started_at + the 7-day cadence decides the follow-up date, so pinning the
    # start days ago shapes overdue / due-today / not-due without touching time.
    _backdate_start(db, overdue["assignment_id"], 8)
    _backdate_start(db, due_today["assignment_id"], 7)
    _backdate_start(db, not_due["assignment_id"], 6)

    today = datetime.now(UTC).date()
    rows = _roster(client, coach_headers)
    assert [row["player_username"] for row in rows] == ["zoe", "mia", "ann"]
    assert rows[0]["next_follow_up_on"] == (today - timedelta(days=1)).isoformat()
    assert rows[1]["next_follow_up_on"] == today.isoformat()
    assert rows[2]["next_follow_up_on"] == (today + timedelta(days=1)).isoformat()


def test_last_workout_ranks_never_trained_first_then_oldest(api):
    client, db, _ = api
    coach_headers, _ = _make_coach(client, db, "coach", capacity=10)
    _assign(api, "zoe", coach_headers)
    trained_late = _assign(api, "ann", coach_headers)
    trained_early = _assign(api, "bob", coach_headers)

    _seed_workout(db, trained_late, "2026-09-20")
    _seed_workout(db, trained_early, "2026-09-01")

    rows = _roster(client, coach_headers)
    # "zoe" sorts last by username, so only the workout key can put her first.
    assert [row["player_username"] for row in rows] == ["zoe", "bob", "ann"]
    assert rows[0]["last_workout_on"] is None
    assert rows[1]["last_workout_on"] == "2026-09-01"
    assert rows[2]["last_workout_on"] == "2026-09-20"


# --------------------------------------------------------------------------
# Roster entry basis: program_name (#120)
# --------------------------------------------------------------------------


def _publish_coach_program(api, coach_headers, player, monkeypatch) -> None:
    client, db, _ = api
    _coach_generation(db, monkeypatch)
    published = client.post(
        f"/coach/assignments/{player['assignment_id']}/program", headers=coach_headers, json={}
    )
    assert published.status_code == 200, published.text


def test_roster_entry_reports_the_active_program_name(api, monkeypatch):
    client, db, _ = api
    coach_headers, _ = _make_coach(client, db, "coach", capacity=5)
    player = _assign(api, "p1", coach_headers)

    # No program on the assignment: the row has nothing to label.
    assert _roster(client, coach_headers)[0]["program_name"] is None

    # A coach publication caches the name catalog-side for the next read.
    _publish_coach_program(api, coach_headers, player, monkeypatch)
    assert _roster(client, coach_headers)[0]["program_name"] == "Coach Plan"


def test_attendance_evaluation_caches_the_active_program_name(api):
    client, db, _ = api
    coach_headers, _ = _make_coach(client, db, "coach", capacity=5)
    player = _assign(api, "p1", coach_headers)

    # The player's own program is read while the ledger is open during
    # evaluation, then served from the catalog cache.
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.save_training_program(
            GeneratedProgramSchema(
                program_name="Player Plan",
                split_type="Full Body",
                weekly_frequency=1,
                days=[_day_plan()],
            ).model_dump()
        )
    assert _roster(client, coach_headers)[0]["program_name"] is None

    _seed_workout(db, player, "2026-09-20")
    rows = _roster(client, coach_headers)
    assert rows[0]["program_name"] == "Player Plan"
    assert rows[0]["last_workout_on"] == "2026-09-20"
