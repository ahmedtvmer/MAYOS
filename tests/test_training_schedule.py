"""Expected training schedule and pause contract tests (ticket #30, ADR 029).

A player sets expected weekdays and timezone separately from the program's day
order. Schedule edits append effective-dated versions and never rewrite earlier
expectations. A pause is prospective, lasts at most 14 days, carries no reason,
and is visible to the assigned coach through the existing assignment gate with a
best-effort in-app notice.
"""

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import analytics
from service import coach as coach_service
from service import coach_history as coach_history_service
from service import schedule as schedule_service
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


def _register(client, username, password="correct-horse-1"):
    resp = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _make_coach(client, db, username, capacity=10):
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
    active = db.ledger.get_active_program()
    return (
        [tuple(row) for row in rows],
        active.version if active else None,
        active.weekly_frequency if active else None,
        [(day.day_name, day.day_order) for day in active.days] if active else None,
    )


def _put_schedule(client, headers, **overrides):
    body = {"weekdays": [1, 3, 5], "timezone": "Europe/London", **overrides}
    return client.put("/profile/schedule", headers=headers, json=body)


def test_schedule_and_pause_analytics_follow_their_committed_writes(api, recording_analytics, monkeypatch):
    monkeypatch.setenv("MAYOS_ENV", "test")
    client, db = api
    player = _register(client, "p1")
    headers = {**_authed(player["access_token"]), "X-MAYOS-Client": "web/2.0.0"}

    schedule = _put_schedule(client, headers, weekdays=[1, 4, 6])
    assert schedule.status_code == 200, schedule.text
    pauses_before = _post_pause(client, headers, starts_on=_iso(-1), ends_on=_iso(0))
    assert pauses_before.status_code == 400
    pause = _post_pause(client, headers, starts_on=_iso(2), ends_on=_iso(4))
    assert pause.status_code == 201, pause.text

    events = [event for event in recording_analytics.events if event["event"] in {
        "training_schedule_set", "schedule_pause_scheduled"
    }]
    assert [event["event"] for event in events] == ["training_schedule_set", "schedule_pause_scheduled"]
    assert events[0]["properties"]["days_per_week"] == 3
    assert events[0]["properties"]["platform"] == "web"
    assert events[1]["properties"]["length_days"] == 3
    account = db.get_active_account_by_username("p1")
    ledger_id = account["ledger_id"]
    assert events[0]["uuid"] == analytics.deterministic_event_uuid(
        "training_schedule_set", schedule.json()["version"]["schedule_id"]
    )
    assert events[1]["uuid"] == analytics.deterministic_event_uuid(
        "schedule_pause_scheduled", pause.json()["pause"]["pause_id"]
    )
    with db.open_ledger(ledger_id) as ledger:
        assert len(ledger.list_training_schedules(ledger_id)) == 1
        assert len(ledger.list_training_pauses(ledger_id)) == 1


def test_raising_analytics_sink_does_not_fail_schedule_or_pause_writes(api):
    class RaisingSink:
        def capture(self, *_args):
            raise RuntimeError("analytics unavailable")

        def set_person(self, *_args):
            raise RuntimeError("analytics unavailable")

        def set_person_once(self, *_args):
            raise RuntimeError("analytics unavailable")

        def delete_person(self, *_args):
            raise RuntimeError("analytics unavailable")

    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    analytics.set_sink(RaisingSink())

    schedule = _put_schedule(client, headers, weekdays=[2, 4])
    pause = _post_pause(client, headers, starts_on=_iso(2), ends_on=_iso(3))

    assert schedule.status_code == 200, schedule.text
    assert pause.status_code == 201, pause.text
    account = db.get_active_account_by_username("p1")
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert len(ledger.list_training_schedules(account["ledger_id"])) == 1
        assert len(ledger.list_training_pauses(account["ledger_id"])) == 1


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

    # Historical versions are seeded through the ledger, not the service: the
    # service refuses to backdate, the DB layer stays permissive.
    db.switch_user("p1")
    db.ledger.append_training_schedule(
        "p1", [1, 3, 5], "Europe/London", _iso(-20, "Europe/London"), "2026-01-01T00:00:00+00:00"
    )
    db.ledger.append_training_schedule(
        "p1", [2, 4], "America/New_York", _iso(-5, "America/New_York"), "2026-01-02T00:00:00+00:00"
    )
    assert db.ledger.get_schedule_effective_on("p1", _iso(-10, "Europe/London"))["weekdays"] == [1, 3, 5]
    assert db.ledger.get_schedule_effective_on("p1", _iso(0, "America/New_York"))["weekdays"] == [2, 4]

    # A new edit today appends a version; it does not rewrite the earlier ones.
    appended = _put_schedule(client, headers, weekdays=[6], timezone="Asia/Tokyo")
    assert appended.status_code == 200, appended.text
    assert appended.json()["version"]["weekdays"] == [6]
    assert appended.json()["current"]["weekdays"] == [6]

    assert db.ledger.get_schedule_effective_on("p1", _iso(-10, "Europe/London"))["weekdays"] == [1, 3, 5]
    assert db.ledger.get_schedule_effective_on("p1", _iso(-1, "America/New_York"))["weekdays"] == [2, 4]
    assert len(db.ledger.list_training_schedules("p1")) == 3

    listed = client.get("/profile/schedule", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["current"]["weekdays"] == [6]
    assert [version["weekdays"] for version in body["versions"]] == [[1, 3, 5], [2, 4], [6]]


def test_set_schedule_does_not_touch_program_frequency_or_day_order(api):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    db.switch_user("p1")
    db.ledger.upsert_player_profile({"current_goal": "Strength"})
    db.ledger.save_training_program(_program_payload(frequency=3))
    before = _program_snapshot(db)

    assert _put_schedule(client, headers, weekdays=[2, 4]).status_code == 200
    assert _put_schedule(client, headers, weekdays=[6], timezone="Asia/Tokyo").status_code == 200

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
    _register(client, "p1")

    same_day = _iso(-2, "UTC")
    db.switch_user("p1")
    db.ledger.append_training_schedule("p1", [1], "UTC", same_day, "2026-01-01T00:00:00+00:00")
    second = db.ledger.append_training_schedule("p1", [5], "UTC", same_day, "2026-01-02T00:00:00+00:00")

    effective = db.ledger.get_schedule_effective_on("p1", same_day)
    assert effective["weekdays"] == [5]
    assert effective["schedule_id"] == second["schedule_id"]


def test_past_effective_from_is_refused_and_history_is_unchanged(api):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    db.switch_user("p1")
    db.ledger.append_training_schedule(
        "p1", [1, 3, 5], "UTC", _iso(-20), "2026-01-01T00:00:00+00:00"
    )

    refused = _put_schedule(client, headers, weekdays=[2], timezone="UTC", effective_from=_iso(-1))
    assert refused.status_code == 400, refused.text
    assert db.ledger.get_schedule_effective_on("p1", _iso(-10))["weekdays"] == [1, 3, 5]
    assert len(db.ledger.list_training_schedules("p1")) == 1

    # An edit effective today is allowed and still leaves the past untouched.
    allowed = _put_schedule(client, headers, weekdays=[2, 4], timezone="UTC", effective_from=_iso(0))
    assert allowed.status_code == 200, allowed.text
    assert db.ledger.get_schedule_effective_on("p1", _iso(-10))["weekdays"] == [1, 3, 5]
    assert db.ledger.get_schedule_effective_on("p1", _iso(0))["weekdays"] == [2, 4]


@pytest.mark.parametrize("bad_date", ["20260926", "2026-W39-1", "2026-9-26", "26-09-26"])
def test_non_canonical_effective_from_is_refused(api, bad_date):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    refused = _put_schedule(client, headers, weekdays=[1], timezone="UTC", effective_from=bad_date)
    assert refused.status_code == 400, refused.text
    db.switch_user("p1")
    assert db.ledger.list_training_schedules("p1") == []


def test_set_schedule_defaults_to_player_local_today(api, monkeypatch):
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            moment = datetime(2026, 9, 26, 20, 0, tzinfo=UTC)
            return moment.astimezone(tz) if tz is not None else moment.replace(tzinfo=None)

    monkeypatch.setattr(schedule_service, "datetime", _FrozenDatetime)
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    # UTC is still 2026-09-26; Pacific/Kiritimati (UTC+14) is already 2026-09-27.
    saved = _put_schedule(client, headers, weekdays=[1, 4], timezone="Pacific/Kiritimati")
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"]["effective_from"] == "2026-09-27"
    assert saved.json()["current"]["effective_from"] == "2026-09-27"

    listed = client.get("/profile/schedule", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["current"]["effective_from"] == "2026-09-27"


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
    assert db.ledger.list_training_schedules("p1") == []


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
    assert len(db.ledger.list_training_pauses("p1")) == 2
    covered = db.ledger.list_active_or_upcoming_training_pauses("p1", _iso(4))
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
    assert db.ledger.list_training_pauses("p1") == []


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
        client, player_headers, weekdays=[1, 4], timezone="Europe/Berlin"
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
    assert pause_notices[0]["message"] == (
        f"p1 scheduled a training pause from {_iso(1, 'Europe/Berlin')} to {_iso(6, 'Europe/Berlin')}."
    )


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
    assert _put_schedule(client, player_headers, weekdays=[2]).status_code == 200
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
    assert _put_schedule(client, player_headers, weekdays=[2]).status_code == 200
    assert _post_pause(
        client, player_headers, starts_on=_iso(1, "Europe/London"), ends_on=_iso(3, "Europe/London")
    ).status_code == 201

    intruder = _make_coach(client, db, "intruder", capacity=5)
    denied = client.get(
        f"/coach/assignments/{assignment_id}/player/summary", headers=intruder
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == coach_history_service.DENIED_ERROR
