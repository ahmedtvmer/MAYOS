"""The 14-day workout reminder plan Android schedules offline (#840)."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from database import push as storage
from service import local_reminders
from svc.app import create_app
from svc.dependencies import get_db
from tests.test_web_push import NOW, push_store  # noqa: F401

# NOW is Monday 2026-11-16 12:00 UTC, 14:00 in Cairo.
TODAY = date(2026, 11, 16)


def _prefs(db, account, **values):
    storage.save_preferences(db, account["account_id"], {
        **storage.DEFAULTS, "workout_reminders": True, "reminder_time": "18:00",
        "quiet_start": "22:00", "quiet_end": "08:00", **values,
    })


def _schedule(db, account, weekdays=range(1, 8)):
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.append_training_schedule(account["ledger_id"], list(weekdays), "Africa/Cairo",
                                        "2026-11-01", "2026-11-01T00:00:00+00:00")


def _plan(db, account):
    return local_reminders.reminder_plan(db, account, NOW)


def test_daily_schedule_plans_two_weeks_at_the_reminder_time_without_repeats(push_store):  # noqa: F811
    db, account = push_store
    _prefs(db, account)
    _schedule(db, account)

    plan = _plan(db, account)

    assert plan["timezone"] == "Africa/Cairo"
    reminders = plan["reminders"]
    assert [item["date"] for item in reminders] == [
        (TODAY + timedelta(days=offset)).isoformat() for offset in range(14)
    ]
    assert all(item["at"].endswith("T18:00:00+02:00") for item in reminders)
    assert all(item["url"] == "/home?push=program" and item["title"] == "MAYOS" for item in reminders)
    templates = [item["template"] for item in reminders]
    for index in range(len(templates)):
        assert templates[index] not in templates[max(0, index - 5):index], templates


def test_only_expected_untrained_unpaused_days_get_a_reminder(push_store):  # noqa: F811
    db, account = push_store
    _prefs(db, account)
    _schedule(db, account, weekdays=[1, 3])  # Mondays and Wednesdays
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.conn.execute(
            "INSERT INTO workout_sessions(id, session_date, split_name, started_at) VALUES (?, ?, ?, ?)",
            ("done", TODAY.isoformat(), "Upper", NOW.isoformat()))
        ledger.conn.commit()
        ledger.schedule_training_pause(account["ledger_id"], "2026-11-23", "2026-11-23", NOW.isoformat())

    dates = [item["date"] for item in _plan(db, account)["reminders"]]

    # Today is trained and Monday the 23rd is paused.
    assert dates == ["2026-11-18", "2026-11-25"]


@pytest.mark.parametrize(("reminder_time", "expected"), [
    ("07:00", "T08:00:00+02:00"),  # deferred to the end of quiet hours that day
    ("23:00", None),  # quiet until tomorrow: never moved to the next day
])
def test_quiet_hours_defer_within_the_day_only(push_store, reminder_time, expected):  # noqa: F811
    db, account = push_store
    _prefs(db, account, reminder_time=reminder_time)
    _schedule(db, account)

    reminders = _plan(db, account)["reminders"]

    if expected is None:
        assert reminders == []
    else:
        assert reminders and all(item["at"].endswith(expected) for item in reminders)


def test_a_time_already_past_today_starts_tomorrow(push_store):  # noqa: F811
    db, account = push_store
    _prefs(db, account, reminder_time="09:17")
    _schedule(db, account)

    assert _plan(db, account)["reminders"][0]["date"] == "2026-11-17"


def test_turned_off_reminders_plan_nothing(push_store):  # noqa: F811
    db, account = push_store
    _prefs(db, account, workout_reminders=False)
    _schedule(db, account)

    assert _plan(db, account)["reminders"] == []


def test_arabic_players_get_arabic_reminder_copy(push_store):  # noqa: F811
    db, account = push_store
    _prefs(db, account)
    _schedule(db, account)

    plan = local_reminders.reminder_plan(db, {**account, "display_language": "ar"}, NOW)

    assert all(any("؀" <= char <= "ۿ" for char in item["body"]) for item in plan["reminders"])


def test_local_reminders_endpoint_is_account_scoped(fresh_store, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-0123456789abcdef")
    app = create_app()
    app.dependency_overrides[get_db] = lambda: fresh_store
    with TestClient(app) as client:
        assert client.get("/push/local-reminders").status_code == 401
        response = client.post("/auth/register", json={"trainee_id": "local-reminders", "password": "correct-horse-1"})
        assert response.status_code == 201, response.text
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        plan = client.get("/push/local-reminders", headers=headers)

    assert plan.status_code == 200, plan.text
    # Reminders start off until the Player turns them on.
    assert plan.json()["reminders"] == []
