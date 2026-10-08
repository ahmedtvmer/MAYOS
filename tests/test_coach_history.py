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
    "/player/checkpoint-reviews",
    "/player/checkpoint-reviews/10",
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
    issued = coach_service.issue_coach_invite(db, username, actor="cli")
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
    db.catalog_conn.execute("UPDATE exercises SET equipment = 'body weight' WHERE id = 'sq'")
    db.catalog_conn.commit()
    history = client.get(f"{base}/exercises/sq/history", headers=coach_headers)
    assert history.status_code == 200, history.text
    assert history.json()["equipment"] == "body weight"

    for response in (summary, records, exercises, history):
        assert not _contains_chat_field(response.json()), response.text


def test_history_reads_enrich_exercises_and_group_recent_working_sets(
    api, seed_exercise_curation
):
    client, db, _ = api
    coach_headers, _, assignment_id = _assigned_player(api)
    created = client.post(
        "/coach/exercises",
        headers=coach_headers,
        json={"name": "Coach Press", "body_part": "Shoulders"},
    )
    assert created.status_code == 201, created.text
    coach_exercise_id = created.json()["id"]

    with db.catalog_locked() as connection:
        connection.execute(
            "UPDATE exercises SET image_path = 'images/squat.jpg' WHERE id = 'sq'"
        )
        connection.commit()
    seed_exercise_curation(
        db,
        {"sq": {"primary_muscle": "Quads", "primary_action": "Knee Extension"}},
    )

    exercises = [
        ProgramExerciseSchema(
            exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8
        ),
        ProgramExerciseSchema(
            exercise_id=coach_exercise_id,
            exercise_name="Coach Press",
            target_reps_min=5,
            target_reps_max=8,
        ),
        ProgramExerciseSchema(
            exercise_id="unknown:lift",
            exercise_name="Unknown Lift",
            target_reps_min=5,
            target_reps_max=8,
        ),
    ]
    outcome = workouts_service.commit_session(
        db,
        "p1",
        ProgramDaySchema(day_name="Full A", day_order=1, exercises=exercises),
        readiness=4,
        session_notes="",
        sets_by_exercise=[
            {
                "exercise": exercises[0],
                "sets": [
                    {"weight_kg": 40.0, "reps": 10, "rpe": 7.0, "is_warmup": True},
                    {"weight_kg": 100.0, "reps": 5, "rpe": 8.0},
                    {"weight_kg": 105.0, "reps": 4, "rpe": 9.0},
                ],
                "previous_perf": [],
            },
            {
                "exercise": exercises[1],
                "sets": [{"weight_kg": 50.0, "reps": 8, "rpe": 8.0}],
                "previous_perf": [],
            },
            {
                "exercise": exercises[2],
                "sets": [{"weight_kg": 0.0, "reps": 12, "rpe": None}],
                "previous_perf": [],
            },
        ],
        now_iso="2026-09-26T10:00:00+00:00",
    )
    session_id = outcome.body["session_id"]
    with db.open_ledger("p1") as ledger:
        ledger.conn.executemany(
            "INSERT INTO personal_records "
            "(id, exercise_id, record_type, reps, value, prev_value, achieved_at, session_id) "
            "VALUES (?, ?, 'max_weight', 5, 100.0, 90.0, '2026-09-26', ?)",
            [
                ("pr-sq", "sq", session_id),
                ("pr-coach", coach_exercise_id, session_id),
                ("pr-unknown", "unknown:lift", session_id),
            ],
        )
        ledger.conn.commit()
        before = {
            table: [tuple(row) for row in ledger.conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in ("workout_sessions", "workout_sets", "personal_records")
        }

    base = f"/coach/assignments/{assignment_id}/player"
    summary_response = client.get(f"{base}/summary", headers=coach_headers)
    records_response = client.get(f"{base}/personal-records", headers=coach_headers)
    exercises_response = client.get(f"{base}/exercises", headers=coach_headers)
    assert summary_response.status_code == 200, summary_response.text
    assert records_response.status_code == 200, records_response.text
    assert exercises_response.status_code == 200, exercises_response.text

    summary = summary_response.json()
    latest = summary["latest_session"]
    recent = summary["recent_sessions"][0]
    expected_ids = {"sq", coach_exercise_id, "unknown:lift"}
    for session in (latest, recent):
        assert {exercise["exercise_id"] for exercise in session["exercises"]} == expected_ids
        assert session["sets_count"] == sum(exercise["sets"] for exercise in session["exercises"]) == 4
        assert session["total_volume_kg"] == sum(
            exercise["volume_kg"] for exercise in session["exercises"]
        ) == 1320.0
        assert {exercise["exercise_id"]: exercise["sets"] for exercise in session["exercises"]} == {
            "sq": 2,
            coach_exercise_id: 1,
            "unknown:lift": 1,
        }

    by_id = {exercise["exercise_id"]: exercise for exercise in latest["exercises"]}
    assert by_id["sq"] == {
        "exercise_id": "sq",
        "name": "Squat",
        "sets": 2,
        "reps": 9,
        "volume_kg": 920.0,
        "image_path": "images/squat.jpg",
        "primary_muscle": "Quads",
        "primary_action": "Knee Extension",
    }
    assert by_id[coach_exercise_id]["primary_muscle"] == "Shoulders"
    assert by_id[coach_exercise_id]["image_path"] is None
    assert by_id[coach_exercise_id]["primary_action"] is None
    assert by_id["unknown:lift"]["primary_muscle"] is None
    assert by_id["unknown:lift"]["image_path"] is None
    assert by_id["unknown:lift"]["primary_action"] is None

    records_by_id = {
        record["exercise_id"]: record for record in records_response.json()
    }
    assert set(records_by_id) == expected_ids
    assert records_by_id["sq"]["image_path"] == "images/squat.jpg"
    assert records_by_id["sq"]["primary_muscle"] == "Quads"
    assert records_by_id[coach_exercise_id]["primary_muscle"] == "Shoulders"
    assert records_by_id[coach_exercise_id]["image_path"] is None
    assert records_by_id["unknown:lift"]["primary_muscle"] is None
    assert records_by_id["unknown:lift"]["image_path"] is None

    listed_by_id = {
        exercise["id"]: exercise for exercise in exercises_response.json()["exercises"]
    }
    assert set(listed_by_id) == expected_ids
    assert listed_by_id["sq"]["image_path"] == "images/squat.jpg"
    assert listed_by_id["sq"]["primary_muscle"] == "Quads"
    assert listed_by_id[coach_exercise_id]["primary_muscle"] == "Shoulders"
    assert listed_by_id[coach_exercise_id]["image_path"] is None
    assert listed_by_id["unknown:lift"]["primary_muscle"] is None
    assert listed_by_id["unknown:lift"]["image_path"] is None

    with db.open_ledger("p1") as ledger:
        after = {
            table: [tuple(row) for row in ledger.conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in ("workout_sessions", "workout_sets", "personal_records")
        }
    assert after == before


def test_coach_checkpoint_review_reads_do_not_open_player_review(api):
    client, db, _ = api
    coach_headers, player_headers, assignment_id = _assigned_player(api)
    outcome = _seed_session(db, "p1", 100.0, 5, "2026-09-24T10:00:00+00:00")
    db.switch_user("p1")
    db.conn.execute(
        "INSERT INTO checkpoint_reviews "
        "(checkpoint, session_id, period_start, period_end, facts_json, rating_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            10,
            outcome.body["session_id"],
            "2026-09-01",
            "2026-09-24",
            '{"workouts_in_period": 10}',
            '[{"part":"Consistency","label":"Strong"}]',
            "2026-09-24T10:00:00+00:00",
        ),
    )
    db.conn.commit()

    base = f"/coach/assignments/{assignment_id}/player/checkpoint-reviews"
    listed = client.get(base, headers=coach_headers)
    detail = client.get(f"{base}/10", headers=coach_headers)
    assert listed.status_code == detail.status_code == 200
    assert listed.json()[0]["checkpoint"] == 10
    assert detail.json()["text"] == "Checkpoint 10: 10 workouts since you started logging in MAYOS."
    assert detail.json()["text_is_template"] is True
    assert detail.json()["rating"] == [{"part": "Consistency", "label": "Strong"}]
    db.switch_user("p1")
    assert db.conn.execute(
        "SELECT opened_at FROM checkpoint_reviews WHERE checkpoint = 10"
    ).fetchone()[0] is None

    player_read = client.get("/checkpoint-reviews/10", headers=player_headers)
    assert player_read.status_code == 200, player_read.text
    assert player_read.json()["text_is_template"] is True
    assert client.get("/checkpoint-reviews", headers=player_headers).json()[0]["opened"] is True


@pytest.mark.parametrize(
    ("ended", "status", "detail"),
    [(False, 404, "Checkpoint review not found."), (True, 403, coach_history_service.DENIED_ERROR)],
)
def test_coach_missing_checkpoint_review_distinguishes_assignment_denial(
    api, ended, status, detail
):
    client, _, _ = api
    coach_headers, player_headers, assignment_id = _assigned_player(api)
    if ended:
        ended_response = client.post(
            "/assignments/me/end", headers=player_headers
        )
        assert ended_response.status_code == 200, ended_response.text

    response = client.get(
        f"/coach/assignments/{assignment_id}/player/checkpoint-reviews/25",
        headers=coach_headers,
    )
    assert response.status_code == status, response.text
    assert response.json()["detail"] == detail


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
        "alerts_new_lapsing",
        "alerts_acknowledged",
        "current_missed_streak",
        "stall_length",
        "next_follow_up_on",
        "pending_requests",
        "last_workout_on",
        "program_name",
    }
    assert rows[0]["assignment_id"] == assignment_id
    assert rows[0]["player_username"] == "p1"
    assert rows[0]["pending_requests"] == 0
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
