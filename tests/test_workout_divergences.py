"""Workout divergence contract tests (ticket #29 / ADR 028).

A player logs skipped or unplanned exercises truthfully: the divergence is
factual ledger history, never a program change, and the assigned coach sees the
same facts through the existing assignment-gated drill-down. A former or
unrelated coach sees nothing.
"""

import sqlite3
import threading
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


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
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
    return headers


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


def _duplicate_prescription_program_payload():
    return {
        "program_name": "Duplicate Day",
        "weekly_frequency": 3,
        "split_type": "Full Body",
        "days": [
            {
                "day_name": "Full A",
                "day_order": 1,
                "exercises": [
                    {"exercise_id": "sq", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                    {"exercise_id": "sq", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                    {"exercise_id": "bp", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                ],
            }
        ],
    }


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


def _program_fingerprint(db):
    db.switch_user("p1")
    rows = db.conn.execute("SELECT id, is_active, version FROM training_programs ORDER BY id").fetchall()
    return [tuple(row) for row in rows]


def _divergence_tuples(entries):
    return sorted((e["kind"], e["exercise_id"], e["exercise_name"]) for e in entries)


SKIPPED_BP = {"kind": "skipped", "exercise_id": "bp", "exercise_name": "Bench Press"}
SKIPPED_ROW = {"kind": "skipped", "exercise_id": "row", "exercise_name": "Row"}
UNPLANNED_OHP = {"kind": "unplanned", "exercise_id": "ohp", "exercise_name": "Overhead Press"}


def test_commit_records_skipped_and_unplanned_without_changing_program(api):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    db.switch_user("p1")
    db.upsert_user_profile({"current_goal": "Strength"})
    db.save_training_program(_program_payload())
    before = _program_fingerprint(db)

    commit = client.post(
        "/workouts/sessions",
        headers=headers,
        json={
            "day_order": 1,
            "readiness": 4,
            "session_notes": "",
            "sets": [
                {"exercise": _exercise_payload("sq", "Squat"), "sets": [{"weight_kg": 100.0, "reps": 5, "rpe": 8.0}]},
                {
                    "exercise": _exercise_payload("ohp", "Overhead Press"),
                    "sets": [{"weight_kg": 40.0, "reps": 5, "rpe": 8.0}],
                },
            ],
        },
    )
    assert commit.status_code == 201, commit.text
    body = commit.json()
    assert _divergence_tuples(body["divergences"]) == [
        ("skipped", "bp", "Bench Press"),
        ("skipped", "row", "Row"),
        ("unplanned", "ohp", "Overhead Press"),
    ]

    rows = db.list_session_divergences(body["session_id"])
    assert _divergence_tuples(rows) == _divergence_tuples(body["divergences"])
    # The program and its active version are untouched by logging a divergence.
    assert _program_fingerprint(db) == before


def test_all_prescribed_performed_records_no_divergences(api):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    db.switch_user("p1")
    db.upsert_user_profile({"current_goal": "Strength"})
    db.save_training_program(_program_payload())

    commit = client.post(
        "/workouts/sessions",
        headers=headers,
        json={
            "day_order": 1,
            "readiness": 4,
            "session_notes": "",
            "sets": [
                {"exercise": _exercise_payload("sq", "Squat"), "sets": [{"weight_kg": 100.0, "reps": 5, "rpe": 8.0}]},
                {"exercise": _exercise_payload("bp", "Bench Press"), "sets": [{"weight_kg": 80.0, "reps": 5, "rpe": 8.0}]},
                {"exercise": _exercise_payload("row", "Row"), "sets": [{"weight_kg": 60.0, "reps": 8, "rpe": 8.5}]},
            ],
        },
    )
    assert commit.status_code == 201, commit.text
    session_id = commit.json()["session_id"]
    assert commit.json()["divergences"] == []
    assert db.list_session_divergences(session_id) == []
    assert session_id not in db.list_divergences_by_session()
    assert db.get_latest_session_summary()["divergences"] == []


def test_exercise_with_only_warmup_sets_counts_as_skipped(api):
    client, db = api
    _register(client, "p1")
    day_plan = _day_plan()
    result = workouts_service.commit_session(
        db,
        "p1",
        day_plan,
        readiness=4,
        session_notes="",
        sets_by_exercise=[
            {
                "exercise": day_plan.exercises[0],
                "sets": [{"weight_kg": 60.0, "reps": 5, "rpe": 6.0, "is_warmup": True}],
                "previous_perf": [],
            },
            {
                "exercise": day_plan.exercises[1],
                "sets": [{"weight_kg": 80.0, "reps": 5, "rpe": 8.0}],
                "previous_perf": [],
            },
        ],
        now_iso="2026-09-26T10:00:00+00:00",
    )
    assert _divergence_tuples(result.body["divergences"]) == [
        ("skipped", "row", "Row"),
        ("skipped", "sq", "Squat"),
    ]
    rows = db.list_session_divergences(result.body["session_id"])
    assert _divergence_tuples(rows) == _divergence_tuples(result.body["divergences"])


def test_duplicate_prescribed_skipped_exercise_records_one_divergence(api):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    db.switch_user("p1")
    db.upsert_user_profile({"current_goal": "Strength"})
    db.save_training_program(_duplicate_prescription_program_payload())

    commit = client.post(
        "/workouts/sessions",
        headers=headers,
        json={
            "day_order": 1,
            "readiness": 4,
            "session_notes": "",
            "sets": [
                {"exercise": _exercise_payload("bp", "Bench Press"), "sets": [{"weight_kg": 80.0, "reps": 5, "rpe": 8.0}]},
            ],
        },
    )
    assert commit.status_code == 201, commit.text
    body = commit.json()
    assert _divergence_tuples(body["divergences"]) == [("skipped", "sq", "Squat")]

    session_id = body["session_id"]
    assert _divergence_tuples(db.list_session_divergences(session_id)) == [("skipped", "sq", "Squat")]

    db.switch_user("p1")
    sessions = db.conn.execute("SELECT COUNT(*) FROM workout_sessions WHERE id = ?", (session_id,)).fetchone()[0]
    sets = db.conn.execute("SELECT COUNT(*) FROM workout_sets WHERE session_id = ?", (session_id,)).fetchone()[0]
    assert sessions == 1
    assert sets == 1


def _assigned_divergent_player(api):
    """Coach "coach" is assigned "p1", who has committed one divergent session."""
    client, db = api
    coach_headers = _make_coach(client, db, "coach", capacity=5)
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    player = _register(client, "p1")
    player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem", headers=player_headers, json={"token": token, "consent": True}
    )
    assert redeemed.status_code == 200, redeemed.text
    assignment_id = redeemed.json()["assignment"]["assignment_id"]
    db.switch_user("p1")
    db.upsert_user_profile({"current_goal": "Strength"})
    db.save_training_program(_program_payload())
    commit = client.post(
        "/workouts/sessions",
        headers=player_headers,
        json={
            "day_order": 1,
            "readiness": 4,
            "session_notes": "",
            "sets": [
                {"exercise": _exercise_payload("sq", "Squat"), "sets": [{"weight_kg": 100.0, "reps": 5, "rpe": 8.0}]},
            ],
        },
    )
    assert commit.status_code == 201, commit.text
    return coach_headers, player_headers, assignment_id


def test_player_logger_and_coach_drill_down_show_same_divergences(api):
    client, db = api
    coach_headers, player_headers, assignment_id = _assigned_divergent_player(api)

    db.switch_user("p1")
    commit = client.post(
        "/workouts/sessions",
        headers=player_headers,
        json={
            "day_order": 1,
            "readiness": 4,
            "session_notes": "",
            "sets": [
                {
                    "exercise": _exercise_payload("ohp", "Overhead Press"),
                    "sets": [{"weight_kg": 40.0, "reps": 5, "rpe": 8.0}],
                },
            ],
        },
    )
    assert commit.status_code == 201, commit.text
    player_divergences = commit.json()["divergences"]

    db.switch_user("p1")
    latest = db.get_latest_session_summary()
    assert _divergence_tuples(latest["divergences"]) == _divergence_tuples(player_divergences)

    summary = client.get(f"/coach/assignments/{assignment_id}/player/summary", headers=coach_headers)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert _divergence_tuples(body["latest_session"]["divergences"]) == _divergence_tuples(player_divergences)
    assert _divergence_tuples(body["recent_sessions"][0]["divergences"]) == _divergence_tuples(player_divergences)


@pytest.mark.parametrize("ended_by", ["coach", "player"])
def test_divergences_unreachable_after_assignment_ends(api, ended_by):
    client, db = api
    coach_headers, player_headers, assignment_id = _assigned_divergent_player(api)
    summary_url = f"/coach/assignments/{assignment_id}/player/summary"
    assert client.get(summary_url, headers=coach_headers).status_code == 200

    if ended_by == "coach":
        ended = client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers)
    else:
        ended = client.post("/assignments/me/end", headers=player_headers)
    assert ended.status_code == 200, ended.text

    denied = client.get(summary_url, headers=coach_headers)
    assert denied.status_code == 403
    assert denied.json()["detail"] == coach_history_service.DENIED_ERROR


def test_divergences_unreachable_for_unrelated_coach_and_non_coach(api):
    client, db = api
    _, player_headers, assignment_id = _assigned_divergent_player(api)
    summary_url = f"/coach/assignments/{assignment_id}/player/summary"

    unrelated = _make_coach(client, db, "intruder", capacity=5)
    other = client.get(summary_url, headers=unrelated)
    assert other.status_code == 403
    assert other.json()["detail"] == coach_history_service.DENIED_ERROR

    non_coach = client.get(summary_url, headers=player_headers)
    assert non_coach.status_code == 403
    assert non_coach.json()["detail"] == "Coach capability required."
