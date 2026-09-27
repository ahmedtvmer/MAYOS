"""Coach drill-down history contract tests (ticket #25).

Exercises the public FastAPI surface against real temporary SQLite catalogs and
player ledgers with a mocked model. Covers the active-assignment gate for all
four drill-downs, indistinguishable denial for unknown/revoked/other-coach
assignments, immediate revocation (including history logged before the end),
catalog-only roster listing, the coach capability requirement, and the absence
of player-assistant chat data from every coach response.
"""

import sqlite3
from pathlib import Path

import jwt as pyjwt
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

DRILL_DOWN_SUFFIXES = (
    "/player/summary",
    "/player/personal-records",
    "/player/exercises",
    "/player/exercises/sq/history",
)


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


def _subject(token):
    return pyjwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])["sub"]


def _make_coach(client, db, username, capacity=10):
    """Registers a player, grants coach capability via an owner invite, sets capacity."""
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
    return headers


def _issue(client, coach_headers):
    resp = client.post("/coach/assignments/invites", headers=coach_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _redeem(client, player_headers, token):
    return client.post(
        "/assignments/invites/redeem", headers=player_headers, json={"token": token, "consent": True}
    )


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


def _seed_session(db, player, weight_kg, reps, started_at):
    """Commits one real session so volume, history, and PRs are non-empty."""
    day_plan = _day_plan()
    payload = [
        {
            "exercise": day_plan.exercises[0],
            "sets": [{"weight_kg": weight_kg, "reps": reps, "rpe": 8.0}],
            "previous_perf": [],
        }
    ]
    return workouts_service.commit_session(
        db,
        player,
        day_plan,
        readiness=4,
        session_notes="",
        sets_by_exercise=payload,
        now_iso=started_at,
    )


def _assigned_player(api, player_name="p1"):
    """Coach "coach" is actively assigned "p1"; returns headers and the assignment id."""
    client, db, _ = api
    coach_headers = _make_coach(client, db, "coach", capacity=5)
    token = _issue(client, coach_headers)["token"]
    player = _register(client, player_name)
    player_headers = _authed(player["access_token"])
    redeemed = _redeem(client, player_headers, token)
    assert redeemed.status_code == 200, redeemed.text
    return coach_headers, player_headers, redeemed.json()["assignment"]["assignment_id"]


def _contains_chat_field(payload) -> bool:
    forbidden = ("chat", "message", "conversation", "assistant")
    if isinstance(payload, dict):
        for key, value in payload.items():
            if any(token in key.lower() for token in forbidden):
                return True
            if _contains_chat_field(value):
                return True
    elif isinstance(payload, list):
        return any(_contains_chat_field(item) for item in payload)
    return False


# --------------------------------------------------------------------------
# Active-assignment reads
# --------------------------------------------------------------------------


def test_coach_reads_all_drill_downs_for_active_assignment(api):
    client, db, _ = api
    coach_headers, _, assignment_id = _assigned_player(api)
    _seed_session(db, "p1", 100.0, 5, "2026-09-24T10:00:00+00:00")
    _seed_session(db, "p1", 105.0, 5, "2026-09-25T10:00:00+00:00")

    base = f"/coach/assignments/{assignment_id}/player"
    summary = client.get(f"{base}/summary", headers=coach_headers)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["player_username"] == "p1"
    assert body["status"] == "active"
    assert body["volume"]["Quads"] == 2.0
    assert body["latest_session"]["total_volume_kg"] == 105.0 * 5
    assert len(body["recent_sessions"]) == 2
    assert body["recent_sessions"][0]["total_volume_kg"] == 105.0 * 5

    records = client.get(f"{base}/personal-records", headers=coach_headers)
    assert records.status_code == 200, records.text
    assert any(record["exercise_id"] == "sq" for record in records.json())

    exercises = client.get(f"{base}/exercises", headers=coach_headers)
    assert exercises.status_code == 200, exercises.text
    assert {entry["id"] for entry in exercises.json()["exercises"]} == {"sq"}

    history = client.get(f"{base}/exercises/sq/history", headers=coach_headers)
    assert history.status_code == 200, history.text
    assert history.json()["history"]
    assert history.json()["caption"] is not None
    assert history.json()["records"]

    for response in (summary, records, exercises, history):
        assert not _contains_chat_field(response.json()), response.text


def test_roster_listing_is_catalog_only_and_shape_unchanged(api, monkeypatch):
    client, db, _ = api
    coach_headers, _, assignment_id = _assigned_player(api)
    _seed_session(db, "p1", 100.0, 5, "2026-09-24T10:00:00+00:00")

    mounted: list[str] = []
    real_open_ledger = db.open_ledger

    def spy(ledger_id):
        mounted.append(str(ledger_id))
        return real_open_ledger(ledger_id)

    monkeypatch.setattr(db, "open_ledger", spy)

    roster = client.get("/coach/assignments", headers=coach_headers)
    assert roster.status_code == 200, roster.text
    rows = roster.json()["assignments"]
    assert len(rows) == 1
    assert set(rows[0].keys()) == {
        "assignment_id",
        "player_username",
        "started_at",
        "status",
        "alerts_new",
        "alerts_acknowledged",
        "current_missed_streak",
        "next_follow_up_on",
    }
    assert rows[0]["assignment_id"] == assignment_id
    assert rows[0]["player_username"] == "p1"
    # Only the coach's own ledger mounted; the player ledger was never opened.
    assert "p1" not in mounted
    assert mounted == ["coach"]


# --------------------------------------------------------------------------
# Denial is generic and immediate
# --------------------------------------------------------------------------


def test_other_coach_and_unknown_and_revoked_are_indistinguishable(api):
    client, db, _ = api
    coach_headers, player_headers, assignment_id = _assigned_player(api)
    _seed_session(db, "p1", 100.0, 5, "2026-09-24T10:00:00+00:00")

    other_headers = _make_coach(client, db, "intruder", capacity=5)
    base = f"/coach/assignments/{assignment_id}/player"
    other = client.get(f"{base}/summary", headers=other_headers)
    unknown = client.get("/coach/assignments/does-not-exist/player/summary", headers=other_headers)
    assert other.status_code == unknown.status_code == 403
    assert other.json()["detail"] == unknown.json()["detail"] == coach_history_service.DENIED_ERROR

    # Revoking the real assignment yields the same generic denial.
    assert client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers).status_code == 200
    revoked = client.get(f"{base}/summary", headers=coach_headers)
    assert revoked.status_code == 403
    assert revoked.json()["detail"] == coach_history_service.DENIED_ERROR


@pytest.mark.parametrize("ended_by", ["coach", "player"])
def test_ending_assignment_denies_all_reads_including_earlier_history(api, ended_by):
    client, db, _ = api
    coach_headers, player_headers, assignment_id = _assigned_player(api)
    _seed_session(db, "p1", 100.0, 5, "2026-09-24T10:00:00+00:00")
    _seed_session(db, "p1", 105.0, 5, "2026-09-25T10:00:00+00:00")

    if ended_by == "coach":
        ended = client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers)
    else:
        ended = client.post("/assignments/me/end", headers=player_headers)
    assert ended.status_code == 200, ended.text

    # The player keeps training after the end; that new history is denied too.
    _seed_session(db, "p1", 110.0, 5, "2026-09-26T10:00:00+00:00")

    base = f"/coach/assignments/{assignment_id}"
    for suffix in DRILL_DOWN_SUFFIXES:
        denied = client.get(f"{base}{suffix}", headers=coach_headers)
        assert denied.status_code == 403, (suffix, denied.text)
        assert denied.json()["detail"] == coach_history_service.DENIED_ERROR


def test_non_coach_cannot_read_player_drill_down(api):
    client, _, _ = api
    _, player_headers, assignment_id = _assigned_player(api)
    denied = client.get(
        f"/coach/assignments/{assignment_id}/player/summary", headers=player_headers
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Coach capability required."
