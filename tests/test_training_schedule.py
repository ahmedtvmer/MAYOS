"""Expected training schedule and pause contract tests (ticket #30, ADR 029).

A player sets expected weekdays and timezone separately from the program's day
order. Schedule edits append effective-dated versions and never rewrite earlier
expectations. A pause is prospective, lasts at most 14 days, carries no reason,
and is visible to the assigned coach through the existing assignment gate with a
best-effort in-app notice.
"""

import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import coach_history as coach_history_service
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"


def _today(timezone: str = "UTC") -> date:
    return datetime.now(ZoneInfo(timezone)).date()


def _iso(offset_days: int, timezone: str = "UTC") -> str:
    return (_today(timezone) + timedelta(days=offset_days)).isoformat()


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


def _assigned_player(api, player_name="p1"):
    client, db = api
    coach_headers = _make_coach(client, db, "coach", capacity=5)
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    player = _register(client, player_name)
    player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem", headers=player_headers, json={"token": token, "consent": True}
    )
    assert redeemed.status_code == 200, redeemed.text
    assignment_id = redeemed.json()["assignment"]["assignment_id"]
    coach_account_id = db.get_active_account_by_username("coach")["account_id"]
    return coach_headers, player_headers, assignment_id, coach_account_id


def _program_payload(frequency=3):
    exercises = [
        {"exercise_id": "sq", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
        {"exercise_id": "bp", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
        {"exercise_id": "row", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
    ]
    return {
        "program_name": "Assigned Split",
        "weekly_frequency": frequency,
        "split_type": "Full Body",
        "days": [
            {"day_name": "Full A", "day_order": 1, "exercises": [dict(exercise) for exercise in exercises]},
            {"day_name": "Full B", "day_order": 2, "exercises": [dict(exercise) for exercise in exercises]},
        ],
    }


def _program_snapshot(db, player="p1"):
    db.switch_user(player)
    rows = db.conn.execute(
        "SELECT id, is_active, version, weekly_frequency FROM training_programs ORDER BY id"
    ).fetchall()
    active = db.get_active_program()
    return (
        [tuple(row) for row in rows],
        active.version if active else None,
        active.weekly_frequency if active else None,
        [(day.day_name, day.day_order) for day in active.days] if active else None,
    )


def _put_schedule(client, headers, **overrides):
    body = {"weekdays": [1, 3, 5], "timezone": "Europe/London", **overrides}
    return client.put("/profile/schedule", headers=headers, json=body)


def _post_pause(client, headers, **overrides):
    body = {"starts_on": _iso(0), "ends_on": _iso(13), **overrides}
    return client.post("/profile/schedule/pauses", headers=headers, json=body)


# --------------------------------------------------------------------------
# Schedule versions are append-only and separate from the program
# --------------------------------------------------------------------------


def test_set_schedule_appends_versions_without_rewriting_earlier_weekdays(api):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    first = _put_schedule(
        client, headers, weekdays=[1, 3, 5], effective_from=_iso(-20)
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"]["weekdays"] == [1, 3, 5]
    assert first.json()["current"]["weekdays"] == [1, 3, 5]

    second = _put_schedule(
        client, headers, weekdays=[2, 4], timezone="America/New_York", effective_from=_iso(-5)
    )
    assert second.status_code == 200, second.text
    assert second.json()["version"]["weekdays"] == [2, 4]
    assert second.json()["current"]["weekdays"] == [2, 4]

    db.switch_user("p1")
    assert db.get_schedule_effective_on("p1", _iso(-10))["weekdays"] == [1, 3, 5]
    assert db.get_schedule_effective_on("p1", _iso(0))["weekdays"] == [2, 4]
    assert len(db.list_training_schedules("p1")) == 2

    listed = client.get("/profile/schedule", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["current"]["weekdays"] == [2, 4]
    assert [version["weekdays"] for version in body["versions"]] == [[1, 3, 5], [2, 4]]


def test_set_schedule_does_not_touch_program_frequency_or_day_order(api):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    db.switch_user("p1")
    db.upsert_user_profile({"current_goal": "Strength"})
    db.save_training_program(_program_payload(frequency=3))
    before = _program_snapshot(db)

    assert _put_schedule(client, headers, weekdays=[2, 4], effective_from=_iso(-2)).status_code == 200
    assert _put_schedule(client, headers, weekdays=[6], timezone="Asia/Tokyo", effective_from=_iso(-1)).status_code == 200

    assert _program_snapshot(db) == before
    assert before[1] == 1
    assert before[2] == 3
    assert before[3] == [("Full A", 1), ("Full B", 2)]


def test_future_effective_from_has_no_current_schedule(api):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    saved = _put_schedule(client, headers, weekdays=[2, 4], effective_from=_iso(5))
    assert saved.status_code == 200, saved.text
    assert saved.json()["current"] is None

    listed = client.get("/profile/schedule", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["current"] is None
    assert [version["effective_from"] for version in body["versions"]] == [_iso(5)]


def test_same_effective_from_returns_later_created_version(api):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    same_day = _iso(-2)
    first = _put_schedule(client, headers, weekdays=[1], effective_from=same_day)
    second = _put_schedule(client, headers, weekdays=[5], effective_from=same_day)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    db.switch_user("p1")
    effective = db.get_schedule_effective_on("p1", same_day)
    assert effective["weekdays"] == [5]
    assert effective["schedule_id"] == second.json()["version"]["schedule_id"]


@pytest.mark.parametrize(
    "body",
    [
        {"weekdays": [], "timezone": "UTC"},
        {"weekdays": [1, 1], "timezone": "UTC"},
        {"weekdays": [0], "timezone": "UTC"},
        {"weekdays": [8], "timezone": "UTC"},
        {"weekdays": [1, 3], "timezone": "Mars/Phobos"},
        {"weekdays": [1, 3], "timezone": "UTC", "effective_from": "not-a-date"},
    ],
)
def test_set_schedule_validation_failures_are_400(api, body):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    refused = client.put("/profile/schedule", headers=headers, json=body)
    assert refused.status_code == 400, refused.text
    db.switch_user("p1")
    assert db.list_training_schedules("p1") == []


# --------------------------------------------------------------------------
# Pauses: prospective, bounded, reasonless
# --------------------------------------------------------------------------


def test_valid_prospective_pause_is_created(api):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    created = _post_pause(client, headers, starts_on=_iso(2), ends_on=_iso(15))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["pause"]["starts_on"] == _iso(2)
    assert body["pause"]["ends_on"] == _iso(15)
    assert body["notice_sent"] is False
    assert "reason" not in body["pause"]

    listed = client.get("/profile/schedule/pauses", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [pause["pause_id"] for pause in listed.json()["pauses"]] == [body["pause"]["pause_id"]]


def test_overlapping_pauses_are_both_active_on_covered_date(api):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    first = _post_pause(client, headers, starts_on=_iso(1), ends_on=_iso(5))
    second = _post_pause(client, headers, starts_on=_iso(3), ends_on=_iso(7))
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    db.switch_user("p1")
    assert len(db.list_training_pauses("p1")) == 2
    covered = db.get_active_training_pauses("p1", _iso(4))
    assert {pause["pause_id"] for pause in covered} == {
        first.json()["pause"]["pause_id"],
        second.json()["pause"]["pause_id"],
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"starts_on": _iso(-1), "ends_on": _iso(3)},
        {"starts_on": _iso(0), "ends_on": _iso(14)},
        {"starts_on": _iso(5), "ends_on": _iso(4)},
    ],
)
def test_invalid_pauses_are_400(api, overrides):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    refused = client.post("/profile/schedule/pauses", headers=headers, json=overrides)
    assert refused.status_code == 400, refused.text
    db.switch_user("p1")
    assert db.list_training_pauses("p1") == []


def test_fourteen_day_pause_is_allowed_and_reason_is_ignored(api):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    created = client.post(
        "/profile/schedule/pauses",
        headers=headers,
        json={"starts_on": _iso(0), "ends_on": _iso(13), "reason": "holiday"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["pause"]["ends_on"] == _iso(13)
    assert "reason" not in created.json()["pause"]


def test_pause_with_no_active_assignment_still_created_with_no_notice(api):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    created = _post_pause(client, headers, starts_on=_iso(1), ends_on=_iso(3))
    assert created.status_code == 201, created.text
    assert created.json()["notice_sent"] is False
    count = db.catalog_conn.execute(
        "SELECT COUNT(*) FROM assignment_notices WHERE kind = 'training_pause'"
    ).fetchone()[0]
    assert int(count) == 0


# --------------------------------------------------------------------------
# Coach visibility through the existing assignment gate
# --------------------------------------------------------------------------


def test_coach_drill_down_shows_schedule_pause_and_notice(api):
    client, db = api
    coach_headers, player_headers, assignment_id, coach_account_id = _assigned_player(api)

    assert _put_schedule(
        client, player_headers, weekdays=[1, 4], timezone="Europe/Berlin", effective_from=_iso(-1)
    ).status_code == 200
    created = _post_pause(client, player_headers, starts_on=_iso(1, "Europe/Berlin"), ends_on=_iso(6, "Europe/Berlin"))
    assert created.status_code == 201, created.text
    assert created.json()["notice_sent"] is True

    summary = client.get(f"/coach/assignments/{assignment_id}/player/summary", headers=coach_headers)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["schedule"] == {"weekdays": [1, 4], "timezone": "Europe/Berlin"}
    assert body["pauses"] == [{"starts_on": _iso(1, "Europe/Berlin"), "ends_on": _iso(6, "Europe/Berlin")}]

    notices = db.list_assignment_notices(coach_account_id)
    pause_notices = [notice for notice in notices if notice["kind"] == "training_pause"]
    assert len(pause_notices) == 1
    assert "p1" in pause_notices[0]["message"]


def test_notice_failure_still_creates_pause(api, monkeypatch):
    client, db = api
    _, player_headers, assignment_id, _ = _assigned_player(api)

    def boom(*args, **kwargs):
        raise RuntimeError("notice store down")

    monkeypatch.setattr(db, "create_assignment_notice", boom)

    created = _post_pause(client, player_headers, starts_on=_iso(2), ends_on=_iso(4))
    assert created.status_code == 201, created.text
    assert created.json()["notice_sent"] is False

    summary = client.get(f"/coach/assignments/{assignment_id}/player/summary", headers=player_headers)
    assert summary.status_code == 403


@pytest.mark.parametrize("ended_by", ["coach", "player"])
def test_schedule_and_pauses_unreachable_after_assignment_ends(api, ended_by):
    client, db = api
    coach_headers, player_headers, assignment_id, _ = _assigned_player(api)
    assert _put_schedule(client, player_headers, weekdays=[2], effective_from=_iso(-1)).status_code == 200
    assert _post_pause(
        client, player_headers, starts_on=_iso(1, "Europe/London"), ends_on=_iso(3, "Europe/London")
    ).status_code == 201

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
    body = denied.json()
    assert "weekdays" not in body and "pauses" not in body


def test_schedule_and_pauses_unreachable_for_unrelated_coach(api):
    client, db = api
    _, player_headers, assignment_id, _ = _assigned_player(api)
    assert _put_schedule(client, player_headers, weekdays=[2], effective_from=_iso(-1)).status_code == 200
    assert _post_pause(
        client, player_headers, starts_on=_iso(1, "Europe/London"), ends_on=_iso(3, "Europe/London")
    ).status_code == 201

    intruder = _make_coach(client, db, "intruder", capacity=5)
    denied = client.get(
        f"/coach/assignments/{assignment_id}/player/summary", headers=intruder
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == coach_history_service.DENIED_ERROR
