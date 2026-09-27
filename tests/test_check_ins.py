"""Check-in and follow-up-due alert tests (ticket #32, ADR 031).

Exercises the catalog-side check-in facts and the weekly follow-up cadence:
create/list visibility for the active coach, validation, the player's durable
history across unassignment, the generic denial for foreign/ended coaches, the
deduplicated due alert created by the sweep, the system resolution by a new
check-in, the shifting due date, and the in-place coach_alerts shape migration.
"""

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import alert_sweep
from service import assignments as assignments_service
from service import check_ins as check_ins_service
from service import coach as coach_service
from service.missed_day_alerts import present_alert
from service.assignments import DENIED_ERROR
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"

#: A fixed instant in the buggy window (after 10:00 UTC, when Pacific/Kiritimati
#: has already rolled into the next calendar day). Every test runs at this frozen
#: clock so results never depend on the hour the suite happens to execute.
_FROZEN_NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _FROZEN_NOW.astimezone(tz) if tz is not None else _FROZEN_NOW.replace(tzinfo=None)


def _now() -> datetime:
    return _FROZEN_NOW


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    # Pin the wall clock for both the check-in validation seam and assignment
    # creation, so the check-in bounds and the assignment start are deterministic.
    monkeypatch.setattr(check_ins_service, "_now", _now)
    monkeypatch.setattr(assignments_service, "datetime", _FrozenDatetime)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
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
    coach_headers = _make_coach(client, db, coach_name)
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    player = _register(client, player_name)
    player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem", headers=player_headers, json={"token": token, "consent": True}
    )
    assert redeemed.status_code == 200, redeemed.text
    assignment_id = redeemed.json()["assignment"]["assignment_id"]
    coach_account_id = db.get_active_account_by_username(coach_name)["account_id"]
    player_account_id = db.get_active_account_by_username(player_name)["account_id"]
    return coach_headers, player_headers, assignment_id, coach_account_id, player_account_id


def _backdate_assignment(db, assignment_id, started_at):
    db.catalog_conn.execute(
        "UPDATE assignments SET started_at = ? WHERE assignment_id = ?",
        (started_at.isoformat(), assignment_id),
    )
    db.catalog_conn.commit()


def _today() -> date:
    return _now().date()


def _follow_up_alerts(db, coach_account_id, states):
    return [
        alert
        for alert in db.list_coach_alerts(coach_account_id, states)
        if alert["kind"] == check_ins_service.FOLLOW_UP_KIND
    ]


def test_coach_records_and_lists_a_check_in(api):
    client, db = api
    coach_headers, player_headers, assignment_id, _, _ = _assign(api)

    created = client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": _today().isoformat(), "channel": "phone", "note": "  Weekly call  "},
    )
    assert created.status_code == 200, created.text
    check_in = created.json()["check_in"]
    assert check_in["checked_in_on"] == _today().isoformat()
    assert check_in["channel"] == "phone"
    assert check_in["note"] == "Weekly call"
    assert created.json()["next_follow_up_on"] == (_today() + timedelta(days=7)).isoformat()

    listed = client.get(
        f"/coach/assignments/{assignment_id}/check-ins", headers=coach_headers
    )
    assert listed.status_code == 200, listed.text
    assert [row["check_in_id"] for row in listed.json()["check_ins"]] == [check_in["check_in_id"]]

    player_list = client.get("/assignments/me/check-ins", headers=player_headers)
    assert player_list.status_code == 200, player_list.text
    rows = player_list.json()["check_ins"]
    assert len(rows) == 1
    assert rows[0]["check_in_id"] == check_in["check_in_id"]
    assert rows[0]["coach_username"] == "coach"


def test_check_in_validation_rejects_bad_input(api):
    client, db = api
    coach_headers, _, assignment_id, _, _ = _assign(api)
    _backdate_assignment(db, assignment_id, _now() - timedelta(days=5))
    base = f"/coach/assignments/{assignment_id}/check-ins"

    # Two days out is beyond even UTC+14's today (the most permissive bound).
    future = client.post(
        base, headers=coach_headers,
        json={"checked_in_on": (_today() + timedelta(days=2)).isoformat(), "channel": "phone"},
    )
    assert future.status_code == 400

    before_start = client.post(
        base, headers=coach_headers,
        json={"checked_in_on": (_today() - timedelta(days=10)).isoformat(), "channel": "phone"},
    )
    assert before_start.status_code == 400

    bad_channel = client.post(
        base, headers=coach_headers,
        json={"checked_in_on": _today().isoformat(), "channel": "telepathy"},
    )
    assert bad_channel.status_code == 400

    long_note = client.post(
        base, headers=coach_headers,
        json={
            "checked_in_on": _today().isoformat(),
            "channel": "phone",
            "note": "x" * (check_ins_service.MAX_CHECK_IN_NOTE_LENGTH + 1),
        },
    )
    assert long_note.status_code == 400

    malformed = client.post(
        base, headers=coach_headers,
        json={"checked_in_on": "20260926", "channel": "phone"},
    )
    assert malformed.status_code == 400

    assert db.list_assignment_check_ins(assignment_id) == []


def test_former_coach_is_denied_but_the_player_still_sees_history(api):
    client, db = api
    coach_headers, player_headers, assignment_id, _, _ = _assign(api)
    assert client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": _today().isoformat(), "channel": "in_person"},
    ).status_code == 200

    assert client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers).status_code == 200

    denied_list = client.get(f"/coach/assignments/{assignment_id}/check-ins", headers=coach_headers)
    assert denied_list.status_code == 403
    assert denied_list.json()["detail"] == DENIED_ERROR
    denied_create = client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": _today().isoformat(), "channel": "phone"},
    )
    assert denied_create.status_code == 403
    assert denied_create.json()["detail"] == DENIED_ERROR

    still_visible = client.get("/assignments/me/check-ins", headers=player_headers)
    assert still_visible.status_code == 200
    assert len(still_visible.json()["check_ins"]) == 1


def test_player_ending_the_assignment_ends_coach_access_not_history(api):
    client, db = api
    coach_headers, player_headers, assignment_id, _, _ = _assign(api)
    assert client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": _today().isoformat(), "channel": "video"},
    ).status_code == 200

    assert client.post("/assignments/me/end", headers=player_headers).status_code == 200

    assert client.get(f"/coach/assignments/{assignment_id}/check-ins", headers=coach_headers).status_code == 403
    rows = client.get("/assignments/me/check-ins", headers=player_headers).json()["check_ins"]
    assert len(rows) == 1
    assert rows[0]["channel"] == "video"


def test_unrelated_coach_is_denied(api):
    client, db = api
    coach_headers, _, assignment_id, _, _ = _assign(api)
    intruder_headers = _make_coach(client, db, "intruder")

    assert client.get(f"/coach/assignments/{assignment_id}/check-ins", headers=intruder_headers).status_code == 403
    create = client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=intruder_headers,
        json={"checked_in_on": _today().isoformat(), "channel": "phone"},
    )
    assert create.status_code == 403
    assert create.json()["detail"] == DENIED_ERROR


def test_follow_up_alert_is_created_once_when_due(api):
    client, db = api
    coach_headers, _, assignment_id, coach_account_id, _ = _assign(api)
    now = _now()
    started = now - timedelta(days=10)
    _backdate_assignment(db, assignment_id, started)

    first = alert_sweep.run_sweep(db, now=now)
    second = alert_sweep.run_sweep(db, now=now)

    assert first["follow_ups_created"] == 1
    assert second["follow_ups_created"] == 0
    follow_ups = _follow_up_alerts(db, coach_account_id, ("new",))
    assert len(follow_ups) == 1
    assert follow_ups[0]["dedupe_key"] == (started.date() + timedelta(days=7)).isoformat()
    assert follow_ups[0]["details"]["due_on"] == (started.date() + timedelta(days=7)).isoformat()
    assert follow_ups[0]["details"]["last_check_in_on"] is None

    listed = client.get("/coach/alerts", headers=coach_headers).json()["alerts"]
    assert any(row["kind"] == check_ins_service.FOLLOW_UP_KIND and row["due_on"] for row in listed)


def test_follow_up_is_not_created_before_due(api):
    client, db = api
    _, _, assignment_id, coach_account_id, _ = _assign(api)
    now = _now()
    _backdate_assignment(db, assignment_id, now - timedelta(days=3))

    counts = alert_sweep.run_sweep(db, now=now)

    assert counts["follow_ups_created"] == 0
    assert _follow_up_alerts(db, coach_account_id, ("new", "acknowledged")) == []


def test_new_check_in_resolves_the_follow_up_alert(api):
    client, db = api
    coach_headers, _, assignment_id, coach_account_id, _ = _assign(api)
    now = _now()
    _backdate_assignment(db, assignment_id, now - timedelta(days=10))
    assert alert_sweep.run_sweep(db, now=now)["follow_ups_created"] == 1
    assert len(_follow_up_alerts(db, coach_account_id, ("new",))) == 1

    created = client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": _today().isoformat(), "channel": "message"},
    )
    assert created.status_code == 200, created.text

    assert _follow_up_alerts(db, coach_account_id, ("new", "acknowledged")) == []
    resolved = _follow_up_alerts(db, coach_account_id, ("resolved",))
    assert len(resolved) == 1
    assert resolved[0]["resolved_by"] == "system"
    # The next due date is a full cadence past the new check-in.
    assert created.json()["next_follow_up_on"] == (_today() + timedelta(days=7)).isoformat()


def test_due_date_shifts_with_check_ins_and_shows_on_the_roster(api):
    client, db = api
    coach_headers, _, assignment_id, _, _ = _assign(api)
    started = _now() - timedelta(days=20)
    _backdate_assignment(db, assignment_id, started)

    first_day = _today() - timedelta(days=6)
    first = client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": first_day.isoformat(), "channel": "phone"},
    )
    assert first.json()["next_follow_up_on"] == (first_day + timedelta(days=7)).isoformat()

    # Due date is now in the future, so the sweep creates nothing.
    counts = alert_sweep.run_sweep(db, now=_now())
    assert counts["follow_ups_created"] == 0

    roster = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    entry = next(row for row in roster if row["assignment_id"] == assignment_id)
    assert entry["next_follow_up_on"] == (first_day + timedelta(days=7)).isoformat()

    second = client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": _today().isoformat(), "channel": "in_app"},
    )
    assert second.json()["next_follow_up_on"] == (_today() + timedelta(days=7)).isoformat()


def test_legacy_coach_alerts_shape_migrates_in_place(tmp_path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    catalog_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(catalog_path)
    conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    conn.execute("""
        CREATE TABLE coach_alerts (
            alert_id TEXT PRIMARY KEY,
            assignment_id TEXT NOT NULL,
            coach_account_id TEXT NOT NULL,
            player_account_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            streak_start_date TEXT NOT NULL,
            last_missed_date TEXT NOT NULL,
            missed_count INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL,
            acknowledged_at TEXT,
            resolved_at TEXT,
            resolved_by TEXT
        )
    """)
    conn.execute(
        "CREATE UNIQUE INDEX idx_coach_alerts_streak"
        " ON coach_alerts(assignment_id, kind, streak_start_date)"
    )
    conn.execute(
        "INSERT INTO coach_alerts"
        " (alert_id, assignment_id, coach_account_id, player_account_id, kind,"
        " streak_start_date, last_missed_date, missed_count, state, created_at,"
        " acknowledged_at, resolved_at, resolved_by)"
        " VALUES ('legacy-1', 'a1', 'c1', 'p1', 'missed_expected_days',"
        " '2026-01-01', '2026-01-03', 3, 'acknowledged', '2026-01-03T00:00:00+00:00',"
        " '2026-01-04T00:00:00+00:00', NULL, NULL)"
    )
    conn.commit()
    conn.close()

    db = DatabaseManager(
        catalog_path=catalog_path,
        users_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        active_user="bootstrap",
    )
    try:
        alert = db.get_coach_alert("legacy-1")
        assert alert is not None
        assert alert["dedupe_key"] == "2026-01-01"
        # The database row keeps the kind-specific fields nested under details.
        assert alert["details"] == {
            "streak_start_date": "2026-01-01",
            "last_missed_date": "2026-01-03",
            "missed_count": 3,
        }
        assert "streak_start_date" not in alert
        # The service layer flattens them for the API/mobile response shape.
        assert present_alert(alert)["streak_start_date"] == "2026-01-01"
        assert present_alert(alert)["last_missed_date"] == "2026-01-03"
        assert present_alert(alert)["missed_count"] == 3
        assert alert["state"] == "acknowledged"
        assert alert["acknowledged_at"] == "2026-01-04T00:00:00+00:00"

        # Idempotent: running init again leaves the migrated row intact.
        db._account_schema_ready = False
        db.ensure_account_schema()
        again = db.get_coach_alert("legacy-1")
        assert again["details"]["missed_count"] == 3
        columns = {
            str(row[1])
            for row in db.catalog_conn.execute("PRAGMA table_info(coach_alerts)").fetchall()
        }
        assert "dedupe_key" in columns and "streak_start_date" not in columns
    finally:
        db.catalog_conn.close()


# --------------------------------------------------------------------------
# Follow-up transition rules (review fix 2)
# --------------------------------------------------------------------------


def _started_days_ago(days: int) -> datetime:
    """An assignment start at 00:00 UTC, `days` ago: its local date is unambiguous."""
    day = _today() - timedelta(days=days)
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def test_backdated_check_in_does_not_clear_an_overdue_alert(api):
    client, db = api
    coach_headers, _, assignment_id, coach_account_id, _ = _assign(api)
    started = _started_days_ago(10)
    _backdate_assignment(db, assignment_id, started)
    assert alert_sweep.run_sweep(db, now=_now())["follow_ups_created"] == 1
    due_key = (started.date() + timedelta(days=7)).isoformat()

    # Dating the check-in at the assignment start does not move due_on, so the
    # overdue alert must stay open.
    created = client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": started.date().isoformat(), "channel": "phone"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["next_follow_up_on"] == due_key
    open_alerts = _follow_up_alerts(db, coach_account_id, ("new", "acknowledged"))
    assert len(open_alerts) == 1
    assert open_alerts[0]["dedupe_key"] == due_key


def test_check_in_that_moves_due_on_resolves_the_old_alert(api):
    client, db = api
    coach_headers, _, assignment_id, coach_account_id, _ = _assign(api)
    started = _started_days_ago(10)
    _backdate_assignment(db, assignment_id, started)
    assert alert_sweep.run_sweep(db, now=_now())["follow_ups_created"] == 1
    old_key = (started.date() + timedelta(days=7)).isoformat()

    client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": _today().isoformat(), "channel": "phone"},
    )

    resolved = _follow_up_alerts(db, coach_account_id, ("resolved",))
    assert [alert["dedupe_key"] for alert in resolved] == [old_key]
    assert resolved[0]["resolved_by"] == "system"
    assert _follow_up_alerts(db, coach_account_id, ("new", "acknowledged")) == []


def test_acknowledged_follow_up_is_resolved_by_a_new_check_in(api):
    client, db = api
    coach_headers, _, assignment_id, coach_account_id, _ = _assign(api)
    started = _started_days_ago(10)
    _backdate_assignment(db, assignment_id, started)
    alert_sweep.run_sweep(db, now=_now())
    alert = _follow_up_alerts(db, coach_account_id, ("new",))[0]
    ack = client.post(f"/coach/alerts/{alert['alert_id']}/acknowledge", headers=coach_headers)
    assert ack.status_code == 200
    assert ack.json()["state"] == "acknowledged"

    client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": _today().isoformat(), "channel": "message"},
    )

    assert _follow_up_alerts(db, coach_account_id, ("new", "acknowledged")) == []
    resolved = _follow_up_alerts(db, coach_account_id, ("resolved",))
    assert len(resolved) == 1
    assert resolved[0]["resolved_by"] == "system"


def test_stale_follow_up_key_is_resolved_on_the_next_sweep(api):
    client, db = api
    _, _, assignment_id, coach_account_id, player_account_id = _assign(api)
    started = _started_days_ago(10)
    _backdate_assignment(db, assignment_id, started)
    # A stale key, as if computed under the UTC fallback before a timezone was cached.
    db.insert_coach_alert(
        "stale-alert",
        assignment_id,
        coach_account_id,
        player_account_id,
        check_ins_service.FOLLOW_UP_KIND,
        "2000-01-01",
        {"due_on": "2000-01-01", "last_check_in_on": None},
        "2026-01-01T00:00:00+00:00",
    )

    alert_sweep.run_sweep(db, now=_now())

    stale = db.get_coach_alert("stale-alert")
    assert stale["state"] == "resolved"
    assert stale["resolved_by"] == "system"
    current = _follow_up_alerts(db, coach_account_id, ("new",))
    assert [alert["dedupe_key"] for alert in current] == [
        (started.date() + timedelta(days=7)).isoformat()
    ]


def test_stale_follow_up_key_is_resolved_when_no_longer_due(api):
    client, db = api
    _, _, assignment_id, coach_account_id, player_account_id = _assign(api)
    db.insert_coach_alert(
        "stale-alert",
        assignment_id,
        coach_account_id,
        player_account_id,
        check_ins_service.FOLLOW_UP_KIND,
        "2000-01-01",
        {"due_on": "2000-01-01", "last_check_in_on": None},
        "2026-01-01T00:00:00+00:00",
    )

    alert_sweep.run_sweep(db, now=_now())

    assert db.get_coach_alert("stale-alert")["state"] == "resolved"
    assert _follow_up_alerts(db, coach_account_id, ("new", "acknowledged")) == []


# --------------------------------------------------------------------------
# Unknown-timezone validation (review fix 3)
# --------------------------------------------------------------------------


def test_unknown_timezone_accepts_a_player_today_ahead_of_utc(api):
    client, db = api
    _, _, assignment_id, coach_account_id, _ = _assign(api)
    _backdate_assignment(db, assignment_id, _started_days_ago(400))
    # UTC 2026-09-20T23:00Z is already 2026-09-21 for a UTC+14 player.
    fixed_now = datetime(2026, 9, 20, 23, 0, tzinfo=UTC)

    accepted = check_ins_service.create_check_in(
        db,
        coach_account_id,
        assignment_id,
        {"checked_in_on": "2026-09-21", "channel": "phone"},
        now=fixed_now,
    )
    assert accepted["ok"] is True, accepted

    rejected = check_ins_service.create_check_in(
        db,
        coach_account_id,
        assignment_id,
        {"checked_in_on": "2026-09-22", "channel": "phone"},
        now=fixed_now,
    )
    assert rejected["ok"] is False
    assert "future" in rejected["error"]


# --------------------------------------------------------------------------
# Hour-independent bounds without a cached timezone (UTC+14 upper, UTC-12 lower)
# --------------------------------------------------------------------------


#: The assignment starts at 12:00 UTC on 2026-09-26, the exact bug window: it is
#: still 2026-09-26 in UTC but already 2026-09-27 at UTC+14. The old code used
#: UTC+14 for the start bound too, so it rejected a check-in dated 2026-09-26.
_STARTED_AT = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
_PINNED_NOWS = [
    datetime(2026, 9, 26, 9, 59, tzinfo=UTC),
    datetime(2026, 9, 26, 10, 1, tzinfo=UTC),
    datetime(2026, 9, 26, 23, 30, tzinfo=UTC),
]


def _undated_assignment(api):
    """An assignment at the bug-window start with no cached timezone."""
    _, db = api
    _, _, assignment_id, coach_account_id, _ = _assign(api)
    _backdate_assignment(db, assignment_id, _STARTED_AT)
    assert db.get_roster_timezone(assignment_id) is None
    return db, assignment_id, coach_account_id


@pytest.mark.parametrize("now", _PINNED_NOWS)
def test_check_in_on_the_assignment_start_day_is_accepted_without_a_cached_timezone(api, now):
    db, assignment_id, coach_account_id = _undated_assignment(api)
    assert now.date() == _STARTED_AT.date()

    result = check_ins_service.create_check_in(
        db,
        coach_account_id,
        assignment_id,
        {"checked_in_on": "2026-09-26", "channel": "phone"},
        now=now,
    )
    assert result["ok"] is True, result


@pytest.mark.parametrize(
    "now,accepted",
    [
        (datetime(2026, 9, 26, 9, 59, tzinfo=UTC), False),
        (datetime(2026, 9, 26, 10, 1, tzinfo=UTC), True),
        (datetime(2026, 9, 26, 23, 30, tzinfo=UTC), True),
    ],
)
def test_utc_plus_14_tomorrow_is_accepted_only_when_it_is_today_somewhere(api, now, accepted):
    db, assignment_id, coach_account_id = _undated_assignment(api)
    result = check_ins_service.create_check_in(
        db,
        coach_account_id,
        assignment_id,
        {"checked_in_on": "2026-09-27", "channel": "phone"},
        now=now,
    )
    assert result["ok"] is accepted, result
    if not accepted:
        assert "future" in result["error"]


@pytest.mark.parametrize("now", _PINNED_NOWS)
def test_check_in_beyond_utc_plus_14_today_is_rejected_as_future(api, now):
    db, assignment_id, coach_account_id = _undated_assignment(api)
    result = check_ins_service.create_check_in(
        db,
        coach_account_id,
        assignment_id,
        {"checked_in_on": "2026-09-28", "channel": "phone"},
        now=now,
    )
    assert result["ok"] is False
    assert "future" in result["error"]


def test_a_cached_timezone_still_bounds_both_sides(api):
    db, assignment_id, coach_account_id = _undated_assignment(api)
    db.upsert_roster_attendance(
        assignment_id, 0, _now().isoformat(), timezone="Pacific/Kiritimati"
    )

    # At 12:00 UTC Kiritimati is already 2026-09-27, so the 12:00 UTC start is the
    # 27th locally; the real start day (the 26th) now correctly predates it.
    rejected = check_ins_service.create_check_in(
        db,
        coach_account_id,
        assignment_id,
        {"checked_in_on": "2026-09-26", "channel": "phone"},
        now=_now(),
    )
    assert rejected["ok"] is False
    assert "predate" in rejected["error"]

    accepted = check_ins_service.create_check_in(
        db,
        coach_account_id,
        assignment_id,
        {"checked_in_on": "2026-09-27", "channel": "phone"},
        now=_now(),
    )
    assert accepted["ok"] is True, accepted


# --------------------------------------------------------------------------
# Sequential assignments (review item 10)
# --------------------------------------------------------------------------


def test_sequential_assignments_isolate_check_ins(api):
    client, db = api
    coach_a_headers, player_headers, assignment_a, _, _ = _assign(
        api, coach_name="coachA", player_name="p1"
    )
    assert client.post(
        f"/coach/assignments/{assignment_a}/check-ins",
        headers=coach_a_headers,
        json={"checked_in_on": _today().isoformat(), "channel": "phone"},
    ).status_code == 200
    assert client.post("/assignments/me/end", headers=player_headers).status_code == 200

    coach_b_headers = _make_coach(client, db, "coachB")
    token_b = client.post("/coach/assignments/invites", headers=coach_b_headers).json()["token"]
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": token_b, "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    assignment_b = redeemed.json()["assignment"]["assignment_id"]
    assert client.post(
        f"/coach/assignments/{assignment_b}/check-ins",
        headers=coach_b_headers,
        json={"checked_in_on": _today().isoformat(), "channel": "video"},
    ).status_code == 200

    # The new coach sees only their own check-in; the old coach is denied entirely.
    b_check_ins = client.get(
        f"/coach/assignments/{assignment_b}/check-ins", headers=coach_b_headers
    ).json()["check_ins"]
    assert [row["assignment_id"] for row in b_check_ins] == [assignment_b]
    denied = client.get(
        f"/coach/assignments/{assignment_a}/check-ins", headers=coach_a_headers
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == DENIED_ERROR

    # The player still sees both coaches' check-ins.
    rows = client.get("/assignments/me/check-ins", headers=player_headers).json()["check_ins"]
    assert {row["assignment_id"] for row in rows} == {assignment_a, assignment_b}
    assert {row["coach_username"] for row in rows} == {"coacha", "coachb"}


# --------------------------------------------------------------------------
# Migration crash-safety (review fix 1)
# --------------------------------------------------------------------------

_LEGACY_COACH_ALERTS_SQL = """
    CREATE TABLE coach_alerts (
        alert_id TEXT PRIMARY KEY,
        assignment_id TEXT NOT NULL,
        coach_account_id TEXT NOT NULL,
        player_account_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        streak_start_date TEXT NOT NULL,
        last_missed_date TEXT NOT NULL,
        missed_count INTEGER NOT NULL,
        state TEXT NOT NULL DEFAULT 'new',
        created_at TEXT NOT NULL,
        acknowledged_at TEXT,
        resolved_at TEXT,
        resolved_by TEXT
    )
"""

_LEGACY_COACH_ALERTS_ROW = (
    "INSERT INTO coach_alerts"
    " (alert_id, assignment_id, coach_account_id, player_account_id, kind,"
    " streak_start_date, last_missed_date, missed_count, state, created_at,"
    " acknowledged_at, resolved_at, resolved_by)"
    " VALUES ('legacy-1', 'a1', 'c1', 'p1', 'missed_expected_days',"
    " '2026-01-01', '2026-01-03', 3, 'new', '2026-01-03T00:00:00+00:00',"
    " NULL, NULL, NULL)"
)


def _prepare_migration_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    catalog_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(catalog_path)
    conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    return catalog_path, conn


def _open_db(catalog_path, tmp_path):
    return DatabaseManager(
        catalog_path=catalog_path,
        users_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        active_user="bootstrap",
    )


def _table_names(conn):
    return {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_migration_drops_a_leftover_orphan_new_table(tmp_path, monkeypatch):
    catalog_path, conn = _prepare_migration_catalog(tmp_path, monkeypatch)
    conn.execute(_LEGACY_COACH_ALERTS_SQL)
    conn.execute(
        "CREATE UNIQUE INDEX idx_coach_alerts_streak"
        " ON coach_alerts(assignment_id, kind, streak_start_date)"
    )
    conn.execute(_LEGACY_COACH_ALERTS_ROW)
    # Orphan left by a crash after CREATE TABLE coach_alerts_new.
    conn.execute(DatabaseManager._coach_alerts_create_sql("coach_alerts_new"))
    conn.commit()
    conn.close()

    db = _open_db(catalog_path, tmp_path)
    try:
        alert = db.get_coach_alert("legacy-1")
        assert alert is not None and alert["details"]["missed_count"] == 3
        assert "coach_alerts_new" not in _table_names(db.catalog_conn)
    finally:
        db.catalog_conn.close()


def test_migration_finishes_when_only_the_new_table_survived(tmp_path, monkeypatch):
    catalog_path, conn = _prepare_migration_catalog(tmp_path, monkeypatch)
    # A crash between DROP TABLE coach_alerts and the RENAME leaves only the new table.
    conn.execute(DatabaseManager._coach_alerts_create_sql("coach_alerts_new"))
    conn.execute(
        "INSERT INTO coach_alerts_new"
        " (alert_id, assignment_id, coach_account_id, player_account_id, kind,"
        " dedupe_key, details, state, created_at, acknowledged_at, resolved_at, resolved_by)"
        " VALUES ('half-1', 'a1', 'c1', 'p1', 'missed_expected_days', '2026-02-01',"
        " '{\"streak_start_date\": \"2026-02-01\", \"last_missed_date\": \"2026-02-02\","
        " \"missed_count\": 2}', 'new', '2026-02-02T00:00:00+00:00', NULL, NULL, NULL)"
    )
    conn.commit()
    conn.close()

    db = _open_db(catalog_path, tmp_path)
    try:
        alert = db.get_coach_alert("half-1")
        assert alert is not None and alert["dedupe_key"] == "2026-02-01"
        assert alert["details"]["missed_count"] == 2
        assert "coach_alerts_new" not in _table_names(db.catalog_conn)
    finally:
        db.catalog_conn.close()


def test_migration_failure_rolls_back_and_keeps_the_old_rows(tmp_path, monkeypatch):
    catalog_path, conn = _prepare_migration_catalog(tmp_path, monkeypatch)
    conn.execute(_LEGACY_COACH_ALERTS_SQL)
    conn.execute(_LEGACY_COACH_ALERTS_ROW)
    conn.commit()
    conn.close()

    def boom(self, cursor):
        raise RuntimeError("injected rebuild failure")

    monkeypatch.setattr(DatabaseManager, "_copy_legacy_coach_alert_rows", boom)
    with pytest.raises(RuntimeError, match="injected rebuild failure"):
        _open_db(catalog_path, tmp_path)

    conn = sqlite3.connect(catalog_path)
    try:
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(coach_alerts)")}
        assert "streak_start_date" in columns
        row = conn.execute(
            "SELECT missed_count FROM coach_alerts WHERE alert_id = 'legacy-1'"
        ).fetchone()
        assert row is not None and row[0] == 3
        assert "coach_alerts_new" not in _table_names(conn)
    finally:
        conn.close()
