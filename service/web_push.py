"""VAPID delivery and minute sweep; no network work runs in domain transactions."""

import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from database import push as storage
from database.ledger import push as ledger_push
from service.push_messages import EVENT_COPY, ROUTES, choose_reminder
from service.schedule import timezone_for_versions
from service.attendance import is_expected_day
from service.training_status import TrainingStatusFacts, compute_training_status

logger = logging.getLogger(__name__)
SELF_COACH_SLIP = "self_coach_slip"
MAX_DELIVERY_ATTEMPTS = 5
DELIVERY_COLUMN_MAPPING = {
    "event_id": "d.event_id",
    "subscription_id": "d.subscription_id",
    "attempts": "d.attempts",
    "next_attempt": "d.next_attempt",
    "account_id": "e.account_id",
    "notification_type": "e.notification_type",
    "payload_json": "e.payload_json",
    "created_at": "e.created_at",
    "endpoint": "s.endpoint",
    "keys_json": "s.keys_json",
    "state": "d.state",
}


@dataclass(frozen=True)
class DeliveryClaim:
    row: dict
    attempts: int
    lease_token: str


def configured():
    return all(os.getenv(name, "").strip() for name in
               ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT"))


def queue_event(conn, account_id, event, key, now=None):
    """Called with the catalog lock/transaction held; contains no training details."""
    account = conn.execute("SELECT display_language FROM accounts WHERE account_id=? AND status='active'",
                           (account_id,)).fetchone()
    if account is None:
        return False
    language = account[0] or "en"
    copy_key = "swap_reply" if event == "food_swap_reply" else event
    body = EVENT_COPY[copy_key][1 if language.startswith("ar") else 0]
    category = "alerts" if event in ("coach_alert", "program_request", "food_swap_request", SELF_COACH_SLIP) else "coach_updates"
    payload = dict(title="MAYOS", body=body, url=ROUTES[event], tag=key)
    return storage.enqueue(conn, account_id, key, category, payload, now)


def send_notification(db, account_id, event, dedupe_key):
    """Best-effort durable send seam; #741 owns its Pro eligibility decision.

    A notification failure never rolls back the already committed domain fact.
    """
    try:
        with db.catalog_transaction(immediate=True):
            return queue_event(db.catalog_conn, account_id, event, dedupe_key)
    except Exception:
        logger.warning("Could not enqueue Web Push notification", exc_info=False)
        return False


def in_quiet_hours(now, prefs):
    clock = now.astimezone(ZoneInfo(prefs["timezone"])).strftime("%H:%M")
    start, end = prefs["quiet_start"], prefs["quiet_end"]
    if start == end:
        return False
    return start <= clock < end if start < end else clock >= start or clock < end


def _quiet_end(now, prefs):
    local = now.astimezone(ZoneInfo(prefs["timezone"]))
    hour, minute = map(int, prefs["quiet_end"].split(":"))
    end = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if end <= local:
        end += timedelta(days=1)
    return end.astimezone(UTC)


def _reminder_context(program, facts, performed):
    streak = compute_training_status(facts).weekly_streak
    latest = max((date.fromisoformat(str(day)[:10]) for day in performed), default=None)
    return dict(session_ready=program is not None, streak=streak,
                returning=latest is not None and (facts.local_today - latest).days >= 7)


def _prepare_reminder(db, account, prefs, now):
    with db.open_ledger(account["ledger_id"]) as ledger:
        versions = ledger.list_training_schedules(account["ledger_id"])
        prefs["timezone"] = timezone_for_versions(versions, prefs["timezone"])
        local = now.astimezone(ZoneInfo(prefs["timezone"]))
        today = local.date()
        pauses = ledger.list_training_pauses(account["ledger_id"])
        if not is_expected_day(versions, pauses, today):
            return None
        # Late sweeps never send yesterday's reminder. Quiet hours defer within today.
        if local.strftime("%H:%M") < prefs["reminder_time"] or in_quiet_hours(now, prefs):
            return None
        performed = ledger.list_performed_dates()
        if today.isoformat() in [str(day)[:10] for day in performed]:
            return None
        program = ledger.get_active_program_view()
        facts = TrainingStatusFacts(versions=versions, pauses=pauses, performed_dates=performed,
                                    weekly_frequency=int(program.weekly_frequency) if program else 0,
                                    local_today=today, mayos_workouts=len(performed))
        return today, _reminder_context(program, facts, performed)


def schedule_reminder(db, account, now):
    prefs = storage.preferences(db, account["account_id"])
    if not prefs["workout_reminders"]:
        return False
    prepared = _prepare_reminder(db, account, prefs, now)
    if prepared is None:
        return False
    today, context = prepared
    key = f"workout-reminder:{today.isoformat()}"
    with db.catalog_transaction(immediate=True):
        conn = db.catalog_conn
        recent = [row[0] for row in conn.execute(
            "SELECT template_id FROM push_events WHERE account_id=? AND template_id IS NOT NULL "
            "ORDER BY created_at DESC, rowid DESC LIMIT 5", (account["account_id"],))]
        template, body = choose_reminder(account.get("display_language") or "en", recent, **context)
        payload = dict(title="MAYOS", body=body, url=ROUTES["workout_reminder"], tag=key)
        return storage.enqueue(conn, account["account_id"], key, "workout_reminders", payload,
                               now.isoformat(), template)


def _webpush(subscription, payload):
    from pywebpush import webpush

    webpush(subscription_info=subscription, data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
            vapid_claims={"sub": os.environ["VAPID_SUBJECT"]}, ttl=payload.get("ttl", 3600), timeout=10)


def _delivery_from_row(row):
    return dict(zip(DELIVERY_COLUMN_MAPPING, row))


def account_preferences(db, account_id):
    prefs = storage.preferences(db, account_id)
    account = db.get_account(account_id)
    if account and account["is_player"] and db.ledger_exists(account["ledger_id"]):
        with db.open_ledger(account["ledger_id"]) as ledger:
            prefs["timezone"] = timezone_for_versions(
                ledger.list_training_schedules(account["ledger_id"]), prefs["timezone"])
    return prefs


def deliver_pending(db, now=None, sender=None):
    if not configured():
        return 0
    fixed_now = now
    now = now or datetime.now(UTC)
    sender = sender or _webpush
    with db.catalog_locked() as conn:
        columns = ", ".join(DELIVERY_COLUMN_MAPPING.values())
        rows = [_delivery_from_row(row) for row in conn.execute(
            f"SELECT {columns} FROM push_deliveries d "
            "JOIN push_events e USING(event_id) JOIN push_subscriptions s USING(subscription_id) "
            "JOIN accounts a ON a.account_id=e.account_id "
            "WHERE a.status='active' AND d.state='pending' AND d.next_attempt<=? LIMIT 100", (now.isoformat(),))]
    return sum(_deliver_one(db, row, fixed_now or datetime.now(UTC), sender) for row in rows)


def _delivery_preferences(db, claim, now):
    row = claim.row
    prefs = account_preferences(db, row["account_id"])
    expired = now - datetime.fromisoformat(row["created_at"]) > timedelta(days=1)
    if row["notification_type"] == "workout_reminders" and not expired:
        expired = not _reminder_still_due(db, row, now, prefs)
    if not prefs[row["notification_type"]] or expired:
        _finish(db, claim, "skipped", now)
        return None
    if in_quiet_hours(now, prefs):
        _finish(db, claim, "deferred", _quiet_end(now, prefs))
        return None
    return prefs


def _reminder_still_due(db, row, now, prefs):
    zone = ZoneInfo(prefs["timezone"])
    today = now.astimezone(zone).date()
    if datetime.fromisoformat(row["created_at"]).astimezone(zone).date() != today:
        return False
    account = db.get_account(row["account_id"])
    with db.open_ledger(account["ledger_id"]) as ledger:
        return is_expected_day(ledger.list_training_schedules(account["ledger_id"]),
                               ledger.list_training_pauses(account["ledger_id"]), today) and (
            today.isoformat() not in ledger.list_performed_dates())


def _claim_delivery(db, row, now):
    # Reserve across workers. A crash is retried after the lease; IndexedDB in
    # the worker suppresses repeat presentation after an ambiguous timeout.
    with db.catalog_transaction(immediate=True):
        exhausted = db.catalog_conn.execute(
            "UPDATE push_deliveries SET state='failed', lease_token=NULL "
            "WHERE event_id=? AND subscription_id=? AND state='pending' "
            "AND attempts>=? AND next_attempt<=?",
            (row["event_id"], row["subscription_id"], MAX_DELIVERY_ATTEMPTS, now.isoformat()),
        )
        if exhausted.rowcount == 1:
            return None
        lease_token = uuid.uuid4().hex
        claimed = db.catalog_conn.execute(
            "UPDATE push_deliveries SET next_attempt=?, attempts=attempts+1, lease_token=? "
            "WHERE event_id=? AND subscription_id=? AND state='pending' AND next_attempt<=? "
            "AND attempts<?",
            ((now + timedelta(minutes=5)).isoformat(), lease_token, row["event_id"],
             row["subscription_id"], now.isoformat(), MAX_DELIVERY_ATTEMPTS))
        if claimed.rowcount != 1:
            return None
        attempts = db.catalog_conn.execute(
            "SELECT attempts FROM push_deliveries WHERE event_id=? AND subscription_id=? AND lease_token=?",
            (row["event_id"], row["subscription_id"], lease_token),
        ).fetchone()[0]
        return DeliveryClaim(row, attempts, lease_token)


def _deliver_one(db, row, now, sender):
    claim = _claim_delivery(db, row, now)
    if claim is None:
        return 0
    try:
        row = claim.row
        prefs = _delivery_preferences(db, claim, now)
        if prefs is None:
            return 0
        payload = json.loads(row["payload_json"])
        payload["ttl"] = _delivery_ttl(now, prefs)
        sender(dict(endpoint=row["endpoint"], keys=json.loads(row["keys_json"])), payload)
    except Exception as error:
        # WebPushException/transport failures may include credentials in their
        # text. Keep the boundary broad, persist retry state and log only status.
        _delivery_failed(db, claim, now, getattr(getattr(error, "response", None), "status_code", None))
        return 0
    return int(_finish(db, claim, "sent", now))


def _delivery_ttl(now, prefs):
    if prefs["quiet_start"] == prefs["quiet_end"]:
        return 3600
    local = now.astimezone(ZoneInfo(prefs["timezone"]))
    hour, minute = map(int, prefs["quiet_start"].split(":"))
    start = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if start <= local:
        start += timedelta(days=1)
    return max(0, min(3600, int((start.astimezone(UTC) - now).total_seconds())))


def _delivery_failed(db, claim, now, status):
    row = claim.row
    if status in (404, 410):
        with db.catalog_transaction(immediate=True):
            db.catalog_conn.execute(
                "DELETE FROM push_subscriptions WHERE subscription_id=? AND endpoint=? "
                "AND EXISTS (SELECT 1 FROM push_deliveries WHERE event_id=? "
                "AND subscription_id=? AND lease_token=?)",
                (row["subscription_id"], row["endpoint"], row["event_id"],
                 row["subscription_id"], claim.lease_token),
            )
    elif claim.attempts >= MAX_DELIVERY_ATTEMPTS or (
        status is not None and 400 <= status < 500 and status != 429
    ):
        _finish(db, claim, "failed", now)
    else:
        _finish(db, claim, "pending", now + timedelta(minutes=2 ** claim.attempts))
    logger.warning("Web Push delivery failed (HTTP %s)", status or "unavailable")


def drain_push_intents(db, ledger):
    """Transfer committed ledger intents into the catalog outbox idempotently."""
    intents = ledger_push.pending_intents(ledger.conn)
    for intent in intents:
        with db.catalog_transaction(immediate=True):
            queue_event(db.catalog_conn, intent["account_id"], intent["event"],
                        intent["dedupe_key"], intent["created_at"])
        with ledger.ledger_transaction(immediate=True):
            ledger_push.delete_intent(ledger.conn, intent["intent_id"])


def _finish(db, claim, state, next_attempt):
    row = claim.row
    stored_state = "pending" if state == "deferred" else state
    attempt_adjustment = "attempts=attempts-1, " if state in ("skipped", "deferred") else ""
    with db.catalog_transaction(immediate=True):
        updated = db.catalog_conn.execute(
            f"UPDATE push_deliveries SET {attempt_adjustment}state=?, next_attempt=?, lease_token=NULL "
            "WHERE event_id=? AND subscription_id=? AND state='pending' AND lease_token=?",
            (stored_state, next_attempt.isoformat(), row["event_id"], row["subscription_id"], claim.lease_token),
        )
        return updated.rowcount == 1


def _sweep_player(db, account_id, now):
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_player"] or not db.ledger_exists(account["ledger_id"]):
        return 0
    try:
        with db.open_ledger(account["ledger_id"]) as ledger:
            drain_push_intents(db, ledger)
    except Exception:
        logger.warning("Push intent reconciliation failed", exc_info=False)
    try:
        return int(schedule_reminder(db, account, now))
    except Exception:
        logger.warning("Push reminder evaluation failed", exc_info=False)
        return 0


def run_sweep(db, now=None):
    delivery_now = now
    now = now or datetime.now(UTC)
    if not configured():
        return {"reminders": 0, "sent": 0}
    with db.catalog_locked() as conn:
        ids = [row[0] for row in conn.execute("SELECT DISTINCT account_id FROM push_subscriptions")]
    reminders = sum(_sweep_player(db, account_id, now) for account_id in ids)
    sent = deliver_pending(db, delivery_now)
    with db.catalog_transaction(immediate=True):
        db.catalog_conn.execute("DELETE FROM push_events WHERE created_at<?", ((now - timedelta(days=90)).isoformat(),))
    return {"reminders": reminders, "sent": sent}
