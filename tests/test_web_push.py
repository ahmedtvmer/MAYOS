"""Web Push account/device isolation, policy, retries and reminder behavior (#742)."""

import base64
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from string import Formatter

import pytest
from fastapi.testclient import TestClient
from pywebpush import WebPushException
from requests import Response

from agent.ProgramState import (
    PersistedProgramDaySchema,
    PersistedProgramExerciseSchema,
    PersistedProgramSchema,
    ProgramLoadSchema,
    ProgramSetGroupSchema,
)
from database import push as storage
from database.ledger import push as ledger_push
from database.registry.assignments import AssignmentNoticeRecord
from service import web_push
from service.push_messages import EVENT_COPY, MESSAGES, choose_reminder
from service.training_status import TrainingStatusFacts
from svc.app import create_app
from svc.dependencies import get_db

NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)
KEYS = {"p256dh": base64.urlsafe_b64encode(b"\x04" + b"a" * 64).decode().rstrip("="),
        "auth": base64.urlsafe_b64encode(b"b" * 16).decode().rstrip("=")}


@pytest.fixture
def push_store(fresh_store, monkeypatch):
    for name in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT"):
        monkeypatch.setenv(name, "test-only")
    account_id = fresh_store.create_account("push-player")
    account = fresh_store.get_account(account_id)
    with fresh_store.open_ledger(account["ledger_id"]):
        pass
    storage.save_preferences(fresh_store, account_id, {**storage.DEFAULTS, "quiet_start": "00:00", "quiet_end": "00:00"})
    storage.subscribe(fresh_store, account_id, "phone", "https://fcm.googleapis.com/phone", KEYS, NOW.isoformat())
    return fresh_store, account


def _queue(db, account, event="coach_alert", key="alert:1"):
    with db.catalog_transaction(immediate=True):
        return web_push.queue_event(db.catalog_conn, account["account_id"], event, key, NOW.isoformat())


def _deliveries(db):
    columns = ", ".join(web_push.DELIVERY_COLUMN_MAPPING.values())
    with db.catalog_locked() as conn:
        rows = conn.execute(
            f"SELECT {columns} FROM push_deliveries d "
            "JOIN push_events e USING(event_id) JOIN push_subscriptions s USING(subscription_id)")
        return [web_push._delivery_from_row(row) for row in rows]


def test_742_existing_delivery_table_gains_a_lease_token_column():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE accounts(account_id TEXT PRIMARY KEY, status TEXT)")
    conn.execute(
        "CREATE TABLE push_deliveries(event_id TEXT, subscription_id TEXT, state TEXT, "
        "attempts INTEGER, next_attempt TEXT, PRIMARY KEY(event_id, subscription_id))"
    )

    storage.ensure_schema(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(push_deliveries)")}
    assert "lease_token" in columns
    conn.close()


def test_subscription_refresh_and_delete_are_account_scoped(fresh_store, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-0123456789abcdef")
    for name in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT"):
        monkeypatch.setenv(name, "test-only")
    app = create_app()
    app.dependency_overrides[get_db] = lambda: fresh_store
    with TestClient(app) as client:
        headers = []
        for username in ("push-one", "push-two"):
            response = client.post("/auth/register", json={"trainee_id": username, "password": "correct-horse-1"})
            assert response.status_code == 201, response.text
            headers.append({"Authorization": f"Bearer {response.json()['access_token']}"})
        body = dict(device_id="phone", endpoint="https://fcm.googleapis.com/one", keys=KEYS)
        assert client.put("/push/subscriptions", json=body).status_code == 401
        assert client.put("/push/subscriptions", json=body, headers=headers[0]).status_code == 200
        body["endpoint"] = "https://fcm.googleapis.com/refreshed"
        assert client.put("/push/subscriptions", json=body, headers=headers[0]).status_code == 200
        assert client.delete("/push/subscriptions/phone", headers=headers[1]).status_code == 200
        assert client.get("/push?device_id=phone", headers=headers[0]).json()["subscribed"]
        # An endpoint transferred to the currently signed-in account must not
        # keep receiving the previous account's private notifications.
        assert client.put("/push/subscriptions", json=body, headers=headers[1]).status_code == 200
        assert not client.get("/push?device_id=phone", headers=headers[0]).json()["subscribed"]
        assert client.delete("/push/subscriptions/phone", headers=headers[1]).status_code == 200
        assert not client.get("/push?device_id=phone", headers=headers[1]).json()["subscribed"]
        monkeypatch.delenv("VAPID_PRIVATE_KEY")
        status = client.get("/push", headers=headers[1]).json()
        assert status["enabled"] is False and status["public_key"] is None
        assert client.put("/push/subscriptions", json=body, headers=headers[1]).status_code == 503


@pytest.mark.parametrize(("event", "toggle"), [("coach_alert", "alerts"), ("program_published", "coach_updates"),
                                                ("self_coach_slip", "alerts")])
def test_disabled_type_suppresses_delivery(push_store, event, toggle):
    db, account = push_store
    prefs = storage.preferences(db, account["account_id"])
    storage.save_preferences(db, account["account_id"], {**prefs, toggle: False})
    _queue(db, account, event)
    sent = []
    assert web_push.deliver_pending(db, NOW, lambda sub, payload: sent.append(payload)) == 0
    assert not sent
    assert _deliveries(db)[0]["state"] == "skipped"


@pytest.mark.parametrize(("instant", "start", "end", "zone", "quiet"), [
    ("2026-11-16T19:59:00+00:00", "22:00", "08:00", "Africa/Cairo", False),
    ("2026-11-16T20:00:00+00:00", "22:00", "08:00", "Africa/Cairo", True),
    ("2026-11-17T05:59:00+00:00", "22:00", "08:00", "Africa/Cairo", True),
    ("2026-11-17T06:00:00+00:00", "22:00", "08:00", "Africa/Cairo", False),
    ("2026-11-16T12:00:00+00:00", "10:00", "13:00", "UTC", True),
    ("2026-11-16T12:00:00+00:00", "00:00", "00:00", "UTC", False),
    ("2026-11-01T06:30:00+00:00", "22:00", "08:00", "America/New_York", True),
])
def test_quiet_hours_follow_recipient_timezone_and_boundaries(instant, start, end, zone, quiet):
    assert web_push.in_quiet_hours(datetime.fromisoformat(instant),
                                   dict(timezone=zone, quiet_start=start, quiet_end=end)) is quiet


def test_one_fact_is_sent_once_per_device_even_after_sweep_replay(push_store):
    db, account = push_store
    storage.subscribe(db, account["account_id"], "laptop", "https://fcm.googleapis.com/laptop", KEYS, NOW.isoformat())
    assert _queue(db, account)
    assert not _queue(db, account)
    sent = []
    sender = lambda sub, payload: sent.append((sub["endpoint"], payload))
    assert web_push.deliver_pending(db, NOW, sender) == 2
    assert web_push.deliver_pending(db, NOW + timedelta(minutes=10), sender) == 0
    assert len(sent) == 2 and sent[0][1]["tag"] == sent[1][1]["tag"]


def test_catalog_facts_enqueue_coach_alerts_and_player_updates_once(push_store):
    db, player = push_store
    coach_id = db.create_account("push-coach")
    with db.catalog_transaction(immediate=True):
        db.catalog_conn.execute("UPDATE accounts SET is_coach=1 WHERE account_id=?", (coach_id,))
        db.catalog_conn.execute("INSERT INTO assignments (assignment_id, coach_account_id, player_account_id, started_at) "
                                "VALUES (?, ?, ?, ?)", ("push-assignment", coach_id, player["account_id"], NOW.isoformat()))
    storage.subscribe(db, coach_id, "coach-phone", "https://fcm.googleapis.com/coach", KEYS, NOW.isoformat())
    alerts = [
        db.insert_coach_alert(alert_id, "push-assignment", coach_id, player["account_id"],
                              "missed_expected_days", "same-streak", {}, NOW.isoformat())
        for alert_id in ("alert-one", "retry-with-other-id")
    ]
    publication = AssignmentNoticeRecord(player["account_id"], "push-assignment", "program_published",
                                         "Published", NOW.isoformat(), message_params={"version": 2})
    db.create_assignment_notice_record(publication)
    db.create_assignment_notice_record(publication)
    db.create_assignment_notice_record(AssignmentNoticeRecord(
        player["account_id"], "push-assignment", "program_request", "Coach replied", NOW.isoformat()))
    db.create_assignment_notice_record(AssignmentNoticeRecord(
        coach_id, "push-assignment", "program_request", "Player requested", NOW.isoformat()))
    with db.catalog_locked() as conn:
        events = list(conn.execute("SELECT account_id, notification_type, payload_json FROM push_events"))
    # The retry uses the same alert fact, so it creates no second alert or push.
    # Request pushes are written with request changes, not by this notice hook.
    assert [alert["created"] for alert in alerts] == [True, False]
    assert len(events) == 2
    assert sorted((row[0], row[1]) for row in events) == sorted([
        (coach_id, "alerts"),
        (player["account_id"], "coach_updates")])
    assert len({json.loads(row[2])["tag"] for row in events}) == 2


def test_transient_failure_retries_after_backoff_without_duplicate_success(push_store):
    db, account = push_store
    _queue(db, account)
    response = Response()
    response.status_code = 503
    def unavailable(_sub, _payload):
        raise WebPushException("test unavailable", response=response)
    assert web_push.deliver_pending(db, NOW, unavailable) == 0
    sent = []
    sender = lambda sub, payload: sent.append(payload)
    assert web_push.deliver_pending(db, NOW + timedelta(minutes=1), sender) == 0
    assert web_push.deliver_pending(db, NOW + timedelta(minutes=3), sender) == 1
    assert web_push.deliver_pending(db, NOW + timedelta(minutes=10), sender) == 0
    assert len(sent) == 1


def test_742_fifth_transient_failure_terminates_the_delivery(push_store):
    db, account = push_store
    _queue(db, account)
    response = Response()
    response.status_code = 503

    def unavailable(_sub, _payload):
        raise WebPushException("test unavailable", response=response)

    instant = NOW
    # Attempts 1–4 retry; attempt 5 terminates; no sixth attempt is claimable.
    for attempt in range(1, 6):
        assert web_push.deliver_pending(db, instant, unavailable) == 0
        delivery = _deliveries(db)[0]
        assert delivery["attempts"] == attempt
        assert delivery["state"] == ("failed" if attempt == 5 else "pending")
        instant = datetime.fromisoformat(delivery["next_attempt"])
    assert web_push.deliver_pending(db, instant, unavailable) == 0
    assert _deliveries(db)[0]["attempts"] == 5


def test_742_fifth_attempt_crash_is_terminal_before_a_sixth_dispatch(push_store):
    db, account = push_store
    _queue(db, account)
    instant = NOW
    dispatches = []

    def crash_after_claim(_subscription, _payload):
        dispatches.append("started")
        raise SystemExit("simulated worker crash")

    for attempt in range(1, 6):
        with pytest.raises(SystemExit, match="simulated worker crash"):
            web_push.deliver_pending(db, instant, crash_after_claim)
        delivery = _deliveries(db)[0]
        assert delivery["state"] == "pending"
        assert delivery["attempts"] == attempt
        instant = datetime.fromisoformat(delivery["next_attempt"])

    sent = []
    assert web_push.deliver_pending(db, instant, lambda *_args: sent.append("sent")) == 0
    assert len(dispatches) == 5
    assert sent == []
    delivery = _deliveries(db)[0]
    assert delivery["state"] == "failed"
    assert delivery["attempts"] == 5


def test_742_stale_delivery_lease_cannot_resurrect_a_finished_delivery(push_store):
    db, account = push_store
    _queue(db, account)
    row = _deliveries(db)[0]
    first = web_push._claim_delivery(db, row, NOW)
    second = web_push._claim_delivery(db, row, NOW + timedelta(minutes=5))

    assert first.attempts == 1 and second.attempts == 2
    assert first.lease_token != second.lease_token
    assert web_push._finish(db, second, "sent", NOW + timedelta(minutes=5))
    assert not web_push._finish(db, first, "pending", NOW + timedelta(minutes=6))
    delivery = _deliveries(db)[0]
    assert delivery["state"] == "sent" and delivery["attempts"] == 2
    web_push._delivery_failed(db, first, NOW + timedelta(minutes=6), 410)
    with db.catalog_locked() as conn:
        assert conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] == 1


@pytest.mark.parametrize("status", [404, 410])
def test_gone_subscription_is_pruned(push_store, status):
    db, account = push_store
    _queue(db, account)
    response = Response()
    response.status_code = status
    def gone(_sub, _payload):
        raise WebPushException("test gone", response=response)
    web_push.deliver_pending(db, NOW, gone)
    with db.catalog_locked() as conn:
        assert conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] == 0
    assert not _deliveries(db)


def test_expired_old_endpoint_does_not_prune_concurrently_refreshed_device(push_store):
    db, account = push_store
    _queue(db, account)
    response = Response()
    response.status_code = 410
    def rotated_during_send(_sub, _payload):
        storage.subscribe(db, account["account_id"], "phone", "https://fcm.googleapis.com/new", KEYS,
                          (NOW + timedelta(minutes=1)).isoformat())
        raise WebPushException("old endpoint expired", response=response)
    assert web_push.deliver_pending(db, NOW, rotated_during_send) == 0
    endpoints = []
    assert web_push.deliver_pending(db, NOW + timedelta(minutes=6),
                                    lambda sub, payload: endpoints.append(sub["endpoint"])) == 1
    assert endpoints == ["https://fcm.googleapis.com/new"]


def test_quiet_delivery_waits_until_morning(push_store):
    db, account = push_store
    prefs = {**storage.DEFAULTS, "timezone": "Africa/Cairo"}
    storage.save_preferences(db, account["account_id"], prefs)
    _queue(db, account)
    sent = []
    sender = lambda sub, payload: sent.append(payload)
    assert web_push.deliver_pending(db, NOW.replace(hour=21), sender) == 0
    assert _deliveries(db)[0]["attempts"] == 0
    assert web_push.deliver_pending(db, (NOW + timedelta(days=1)).replace(hour=6), sender) == 1
    assert len(sent) == 1


def test_push_service_ttl_cannot_extend_into_quiet_hours(push_store):
    db, account = push_store
    storage.save_preferences(db, account["account_id"], {**storage.DEFAULTS, "timezone": "Africa/Cairo"})
    _queue(db, account)
    sent = []
    web_push.deliver_pending(db, NOW.replace(hour=19, minute=59, second=30),
                             lambda sub, payload: sent.append(payload))
    assert len(sent) == 1 and sent[0]["ttl"] == 30


def test_account_deletion_removes_device_preferences_and_pending_delivery(push_store):
    db, account = push_store
    _queue(db, account)
    with db.catalog_transaction(immediate=True):
        db.catalog_conn.execute("UPDATE accounts SET status='deleted', deleted_at=? WHERE account_id=?",
                                (NOW.isoformat(), account["account_id"]))
    with db.catalog_locked() as conn:
        for table in ("push_subscriptions", "push_preferences", "push_events", "push_deliveries"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("missing", ["VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT"])
def test_missing_keys_disable_push_without_consuming_outbox(push_store, monkeypatch, missing):
    db, account = push_store
    _queue(db, account)
    monkeypatch.delenv(missing)
    assert not web_push.configured()
    assert web_push.run_sweep(db, NOW) == {"reminders": 0, "sent": 0}
    assert web_push.deliver_pending(db, NOW, lambda *_: pytest.fail("sent without credentials")) == 0
    assert _deliveries(db)[0]["attempts"] == 0


@pytest.mark.parametrize("language", ["en", "ar"])
def test_reminder_rotation_survives_saved_history_without_recent_repeats(push_store, language):
    db, account = push_store
    db.set_account_display_language(account["account_id"], language)
    account = db.get_account(account["account_id"])
    storage.save_preferences(db, account["account_id"], {**storage.DEFAULTS, "workout_reminders": True,
                                                       "reminder_time": "09:17"})
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.append_training_schedule(account["ledger_id"], list(range(1, 8)), "Africa/Cairo",
                                        "2026-11-01", "2026-11-01T00:00:00+00:00")
    for offset in range(14):
        instant = NOW + timedelta(days=offset)
        assert web_push.schedule_reminder(db, account, instant)
        assert not web_push.schedule_reminder(db, account, instant)
    with db.catalog_locked() as conn:
        events = list(conn.execute("SELECT template_id, payload_json FROM push_events ORDER BY rowid"))
    assert len(events) == 14
    for index, (template, payload) in enumerate(events):
        assert template not in [row[0] for row in events[max(0, index - 5):index]]
        assert json.loads(payload)["body"] == MESSAGES[template][language == "ar"]


@pytest.mark.parametrize(("context", "template", "fragment"), [
    ({"session_ready": True}, "session", "Your session"), ({"streak": 4}, "streak", "4"),
    ({"returning": True}, "return", "Welcome back"),
])
def test_reminders_use_generic_or_non_sensitive_context(context, template, fragment):
    key, body = choose_reminder("en", [], **context)
    assert key == template and fragment in body


def test_742_notification_templates_do_not_interpolate_sensitive_training_details():
    allowed_fields = {"streak"}
    for title, body in [*MESSAGES.values(), *EVENT_COPY.values()]:
        for text in (title, body):
            assert {field for _, field, _, _ in Formatter().parse(text) if field} <= allowed_fields


def test_742_reminder_copy_excludes_private_training_details():
    program = PersistedProgramSchema(
        program_name="Knee rehabilitation",
        split_type="custom",
        weekly_frequency=3,
        days=[PersistedProgramDaySchema(
            day_name="Knee rehabilitation",
            day_order=1,
            exercises=[PersistedProgramExerciseSchema(
                exercise_id="sq",
                exercise_name="Squat",
                body_part="Knee",
                note="Coach note: protect the knee.",
                target_reps_min=5,
                target_reps_max=8,
                set_groups=[ProgramSetGroupSchema(
                    sets=3,
                    reps_min=5,
                    reps_max=8,
                    target_rir=2,
                    load=ProgramLoadSchema(kind="kg", value=100),
                )],
            )],
        )],
    )
    facts = TrainingStatusFacts([], [], [], 3, NOW.date(), 0)

    context = web_push._reminder_context(program, facts, [])
    template, body = choose_reminder("en", [], **context)

    assert template == "session"
    assert body == "Your session is ready for you today. Start gently and enjoy it."
    assert all(detail not in body for detail in (
        "Knee rehabilitation", "Squat", "Knee", "100", "Coach note"
    ))


def test_742_ledger_notification_intent_survives_until_catalog_enqueue(push_store, monkeypatch):
    db, account = push_store
    monkeypatch.setattr(web_push, "_webpush", lambda _subscription, _payload: None)
    key = "nutrition-published:assignment-1:version-7"
    with db.open_ledger(account["ledger_id"]) as ledger:
        with ledger.ledger_transaction(immediate=True):
            ledger_push.record_intent(ledger.conn, ledger_push.PushIntent(
                account["account_id"], "nutrition_published", key, NOW.isoformat()))

    assert web_push.run_sweep(db, NOW)["sent"] == 1
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert ledger_push.pending_intents(ledger.conn) == []
    with db.catalog_locked() as conn:
        event = conn.execute("SELECT dedupe_key FROM push_events").fetchone()
    assert event[0] == key


@pytest.mark.parametrize("reason", ["before_time", "rest_day", "paused", "finished", "disabled"])
def test_reminders_skip_ineligible_local_days(push_store, reason):
    db, account = push_store
    storage.save_preferences(db, account["account_id"], {**storage.DEFAULTS,
        "workout_reminders": reason != "disabled", "reminder_time": "15:00" if reason == "before_time" else "09:17"})
    with db.open_ledger(account["ledger_id"]) as ledger:
        weekdays = [2] if reason == "rest_day" else [1]
        ledger.append_training_schedule(account["ledger_id"], weekdays, "Africa/Cairo",
                                        "2026-11-01", "2026-11-01T00:00:00+00:00")
        if reason == "paused":
            ledger.schedule_training_pause(account["ledger_id"], "2026-11-16", "2026-11-16", NOW.isoformat())
        if reason == "finished":
            ledger.conn.execute("INSERT INTO workout_sessions(id, session_date, split_name, started_at) VALUES (?, ?, ?, ?)",
                                ("done", "2026-11-16", "Upper", NOW.isoformat()))
            ledger.conn.commit()
    assert not web_push.schedule_reminder(db, account, NOW)


@pytest.mark.parametrize("change", ["completed", "next_day"])
def test_retry_drops_reminder_after_workout_or_local_day_ends(push_store, change):
    db, account = push_store
    storage.save_preferences(db, account["account_id"], {**storage.DEFAULTS,
                                                       "workout_reminders": True, "reminder_time": "09:17"})
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.append_training_schedule(account["ledger_id"], list(range(1, 8)), "Africa/Cairo",
                                        "2026-11-01", "2026-11-01T00:00:00+00:00")
    assert web_push.schedule_reminder(db, account, NOW)
    if change == "completed":
        with db.open_ledger(account["ledger_id"]) as ledger:
            ledger.conn.execute("INSERT INTO workout_sessions(id, session_date, split_name, started_at) VALUES (?, ?, ?, ?)",
                                ("done-later", "2026-11-16", "Upper", NOW.isoformat()))
            ledger.conn.commit()
    later = NOW + (timedelta(hours=18) if change == "next_day" else timedelta(minutes=10))
    assert web_push.deliver_pending(db, later, lambda *_: pytest.fail("sent an obsolete reminder")) == 0
    assert _deliveries(db)[0]["state"] == "skipped"
