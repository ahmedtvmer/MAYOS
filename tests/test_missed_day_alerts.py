"""Missed expected-day alert tests (ticket #31, ADR 030).

Exercises the deterministic, idempotent evaluation and sweep against real
temporary SQLite catalogs and ledgers: alert creation on a two-day streak, the
coach notice, retry safety, streak extension, system auto-resolution when the
streak breaks, the catalog-side roster summary, and sweep resilience.
"""

import sqlite3
import threading
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import ProgramDaySchema, ProgramExerciseSchema
from database.database_manager import DatabaseManager
from service import alert_sweep
from service import coach as coach_service
from service import missed_day_alerts as alerts_service
from service import workouts as workouts_service
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
ALL_DAYS = [1, 2, 3, 4, 5, 6, 7]


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
        " ('sq', 'Squat', 'Upper Legs', 'Quads'), ('bp', 'Bench Press', 'Chest', 'Chest');"
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


def _assign(api, coach_name="coach", player_name="p1"):
    client, db = api
    coach_headers = _make_coach(client, db, coach_name, capacity=5)
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    player = _register(client, player_name)
    player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem", headers=player_headers, json={"token": token, "consent": True}
    )
    assert redeemed.status_code == 200, redeemed.text
    assignment_id = redeemed.json()["assignment"]["assignment_id"]
    coach_account_id = db.get_active_account_by_username(coach_name)["account_id"]
    return coach_headers, player_headers, assignment_id, coach_account_id


def _backdate_assignment(db, assignment_id, started_at):
    db.catalog_conn.execute(
        "UPDATE assignments SET started_at = ? WHERE assignment_id = ?",
        (started_at.isoformat(), assignment_id),
    )
    db.catalog_conn.commit()


def _seed_schedule(db, player, weekdays, effective_from):
    db.switch_user(player)
    db.append_training_schedule(
        player, weekdays, "UTC", effective_from.isoformat(), "2026-01-01T00:00:00+00:00"
    )


def _seed_session(db, player, session_date):
    db.switch_user(player)
    now_iso = session_date.isoformat() + "T10:00:00+00:00"
    db.log_workout_session(
        uuid.uuid4().hex, session_date.isoformat(), "Full A", now_iso, now_iso, 4, ""
    )


def _notices(db, coach_account_id, kind=alerts_service.MISSED_DAY_KIND):
    return [
        notice
        for notice in db.list_assignment_notices(coach_account_id, limit=50)
        if notice["kind"] == kind
    ]


def test_sweep_creates_one_alert_and_notice_for_a_two_day_streak(api):
    client, db = api
    _, _, assignment_id, coach_account_id = _assign(api)
    now = datetime.now(UTC)
    started = now - timedelta(days=10)
    _backdate_assignment(db, assignment_id, started)
    _seed_schedule(db, "p1", ALL_DAYS, started.date() - timedelta(days=1))

    counts = alert_sweep.run_sweep(db, now=now)

    assert counts == {
        "evaluated": 1,
        "skipped": 0,
        "alerts_created": 1,
        "alerts_resolved": 0,
        "follow_ups_created": 1,
        "errors": 0,
    }
    alerts = [
        alert
        for alert in db.list_coach_alerts(coach_account_id, ("new",))
        if alert["kind"] == alerts_service.MISSED_DAY_KIND
    ]
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["kind"] == alerts_service.MISSED_DAY_KIND
    assert alert["assignment_id"] == assignment_id
    assert alert["details"]["streak_start_date"] == started.date().isoformat()
    assert alert["details"]["missed_count"] == 9
    assert alert["state"] == "new"
    assert len(_notices(db, coach_account_id)) == 1
    summary = db.get_roster_alert_badges(coach_account_id)[assignment_id]
    assert summary["current_missed_streak"] == 9
    assert summary["alerts_acknowledged"] == 0
    # The badge count spans every alert kind, so the due follow-up is counted too.
    assert summary["alerts_new"] == 2


def test_sweep_is_idempotent_and_does_not_duplicate_the_notice(api):
    client, db = api
    _, _, assignment_id, coach_account_id = _assign(api)
    now = datetime.now(UTC)
    started = now - timedelta(days=10)
    _backdate_assignment(db, assignment_id, started)
    _seed_schedule(db, "p1", ALL_DAYS, started.date() - timedelta(days=1))

    first = alert_sweep.run_sweep(db, now=now)
    alert_id = [
        alert
        for alert in db.list_coach_alerts(coach_account_id, ("new",))
        if alert["kind"] == alerts_service.MISSED_DAY_KIND
    ][0]["alert_id"]
    second = alert_sweep.run_sweep(db, now=now)

    assert first["alerts_created"] == 1
    assert second["alerts_created"] == 0
    assert first["follow_ups_created"] == 1
    assert second["follow_ups_created"] == 0
    alerts = [
        alert
        for alert in db.list_coach_alerts(coach_account_id, ("new", "acknowledged", "resolved"))
        if alert["kind"] == alerts_service.MISSED_DAY_KIND
    ]
    assert len(alerts) == 1
    assert alerts[0]["alert_id"] == alert_id
    assert len(_notices(db, coach_account_id)) == 1


def test_longer_streak_extends_the_same_alert(api):
    client, db = api
    _, _, assignment_id, coach_account_id = _assign(api)
    now = datetime.now(UTC)
    started = now - timedelta(days=3)
    _backdate_assignment(db, assignment_id, started)
    _seed_schedule(db, "p1", ALL_DAYS, started.date() - timedelta(days=1))

    alert_sweep.run_sweep(db, now=now)
    first = [
        alert
        for alert in db.list_coach_alerts(coach_account_id, ("new",))
        if alert["kind"] == alerts_service.MISSED_DAY_KIND
    ][0]
    assert first["details"]["missed_count"] == 2

    alert_sweep.run_sweep(db, now=now + timedelta(days=1))
    alerts = [
        alert
        for alert in db.list_coach_alerts(coach_account_id, ("new", "acknowledged", "resolved"))
        if alert["kind"] == alerts_service.MISSED_DAY_KIND
    ]
    assert len(alerts) == 1
    assert alerts[0]["alert_id"] == first["alert_id"]
    assert alerts[0]["details"]["missed_count"] == 3
    assert alerts[0]["details"]["last_missed_date"] == (now.date() - timedelta(days=1)).isoformat()
    assert len(_notices(db, coach_account_id)) == 1


def test_streak_breaks_and_the_open_alert_auto_resolves(api):
    client, db = api
    _, _, assignment_id, coach_account_id = _assign(api)
    now = datetime.now(UTC)
    started = now - timedelta(days=3)
    _backdate_assignment(db, assignment_id, started)
    _seed_schedule(db, "p1", ALL_DAYS, started.date() - timedelta(days=1))

    alert_sweep.run_sweep(db, now=now)
    assert len(db.list_coach_alerts(coach_account_id, ("new",))) == 1

    _seed_session(db, "p1", now.date() - timedelta(days=1))
    counts = alert_sweep.run_sweep(db, now=now)

    assert counts["alerts_resolved"] == 1
    open_alerts = db.list_coach_alerts(coach_account_id, ("new", "acknowledged"))
    assert open_alerts == []
    resolved = db.list_coach_alerts(coach_account_id, ("resolved",))
    assert len(resolved) == 1
    assert resolved[0]["resolved_by"] == "system"
    assert resolved[0]["resolved_at"] is not None
    assert db.get_roster_alert_badges(coach_account_id)[assignment_id]["current_missed_streak"] == 0


def test_commit_hook_resolves_alert_when_an_expected_day_is_satisfied(api):
    client, db = api
    _, _, assignment_id, coach_account_id = _assign(api)
    now = datetime.now(UTC)
    started = now - timedelta(days=3)
    _backdate_assignment(db, assignment_id, started)
    _seed_schedule(db, "p1", ALL_DAYS, started.date() - timedelta(days=1))
    assert alert_sweep.run_sweep(db, now=now)["alerts_created"] == 1
    assert len(db.list_coach_alerts(coach_account_id, ("new",))) == 1

    db.switch_user("p1")
    db.upsert_user_profile({"current_goal": "Strength"})
    player_account_id = db.get_active_account_by_username("p1")["account_id"]
    day_plan = ProgramDaySchema(
        day_name="Full A",
        day_order=1,
        exercises=[
            ProgramExerciseSchema(exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8),
            ProgramExerciseSchema(exercise_id="bp", exercise_name="Bench Press", target_reps_min=5, target_reps_max=8),
            ProgramExerciseSchema(exercise_id="row", exercise_name="Row", target_reps_min=5, target_reps_max=8),
        ],
    )

    # A workout today satisfies an expected day; the commit hook resolves at once.
    workouts_service.commit_session(
        db,
        "p1",
        day_plan,
        readiness=4,
        session_notes="",
        sets_by_exercise=[],
        account_id=player_account_id,
    )

    open_alerts = db.list_coach_alerts(coach_account_id, ("new", "acknowledged"))
    assert open_alerts == []
    resolved = db.list_coach_alerts(coach_account_id, ("resolved",))
    assert len(resolved) == 1
    assert resolved[0]["resolved_by"] == "system"


def test_commit_session_defaults_to_the_player_local_today(api, monkeypatch):
    client, db = api
    _register(client, "p1")
    db.switch_user("p1")
    db.append_training_schedule(
        "p1", ALL_DAYS, "Pacific/Kiritimati", "2026-01-01", "2026-01-01T00:00:00+00:00"
    )
    db.upsert_user_profile({"current_goal": "Strength"})
    # UTC 2026-09-20T12:00Z is already 2026-09-21 for a UTC+14 player.
    local_day = date(2026, 9, 21)
    monkeypatch.setattr(workouts_service, "local_today", lambda db_arg, trainee: local_day)
    day_plan = ProgramDaySchema(
        day_name="Full A",
        day_order=1,
        exercises=[
            ProgramExerciseSchema(exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8),
            ProgramExerciseSchema(exercise_id="bp", exercise_name="Bench Press", target_reps_min=5, target_reps_max=8),
            ProgramExerciseSchema(exercise_id="row", exercise_name="Row", target_reps_min=5, target_reps_max=8),
        ],
    )

    result = workouts_service.commit_session(
        db, "p1", day_plan, readiness=4, session_notes="", sets_by_exercise=[]
    )

    row = db.conn.execute(
        "SELECT session_date FROM workout_sessions WHERE id = ?", (result.body["session_id"],)
    ).fetchone()
    assert row[0] == local_day.isoformat()


def test_sweep_skips_a_player_without_a_ledger_and_never_creates_one(api):
    client, db = api
    now = datetime.now(UTC)
    account_id = db.create_account("ghost")
    assert account_id is not None
    db.catalog_conn.execute(
        "INSERT INTO assignments"
        " (assignment_id, coach_account_id, player_account_id, status, started_at, ended_at, ended_by)"
        " VALUES (?, ?, ?, 'active', ?, NULL, NULL)",
        ("ghost-assignment", "coach-x", account_id, (now - timedelta(days=5)).isoformat()),
    )
    db.catalog_conn.commit()
    assert not db.user_exists("ghost")

    counts = alert_sweep.run_sweep(db, now=now)

    assert counts["skipped"] == 1
    assert counts["evaluated"] == 0
    assert not db.user_exists("ghost")


def test_sweep_unbinds_the_ledger_from_the_worker_thread(api):
    client, db = api
    _, _, assignment_id, _ = _assign(api)
    now = datetime.now(UTC)
    started = now - timedelta(days=3)
    _backdate_assignment(db, assignment_id, started)
    _seed_schedule(db, "p1", ALL_DAYS, started.date() - timedelta(days=1))

    alert_sweep.run_sweep(db, now=now)

    assert db.user_conn is None


def test_sweep_unbinds_the_ledger_even_when_evaluation_raises(api, monkeypatch):
    client, db = api
    _, _, assignment_id, _ = _assign(api)
    now = datetime.now(UTC)
    started = now - timedelta(days=3)
    _backdate_assignment(db, assignment_id, started)
    _seed_schedule(db, "p1", ALL_DAYS, started.date() - timedelta(days=1))

    from service._base import bind_user

    def boom(db_arg, assignment, now=None):
        bind_user(db_arg, "p1")
        raise RuntimeError("boom")

    monkeypatch.setattr(alert_sweep, "evaluate_assignment", boom)
    counts = alert_sweep.run_sweep(db, now=now)

    assert counts["errors"] == 1
    assert db.user_conn is None


def test_sweep_continues_after_one_player_failure(api, monkeypatch):
    client, db = api
    _, _, first_assignment, _ = _assign(api, coach_name="coach1", player_name="p1")
    _, _, second_assignment, _ = _assign(api, coach_name="coach2", player_name="p2")
    now = datetime.now(UTC)
    started = now - timedelta(days=5)
    for assignment_id, player in ((first_assignment, "p1"), (second_assignment, "p2")):
        _backdate_assignment(db, assignment_id, started)
        _seed_schedule(db, player, ALL_DAYS, started.date() - timedelta(days=1))

    real_evaluate = alerts_service.evaluate_assignment

    def flaky(db_arg, assignment, now=None):
        if assignment["assignment_id"] == first_assignment:
            raise RuntimeError("boom")
        return real_evaluate(db_arg, assignment, now=now)

    monkeypatch.setattr(alert_sweep, "evaluate_assignment", flaky)
    counts = alert_sweep.run_sweep(db, now=now)

    assert counts["errors"] == 1
    assert counts["evaluated"] == 1
    assert len(db.list_coach_alerts(db.get_active_account_by_username("coach2")["account_id"], ("new",))) == 1
