"""Catalog storage for device subscriptions and the durable Web Push outbox."""

import json
import uuid
from datetime import UTC, datetime


def ensure_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS push_preferences (
            account_id TEXT PRIMARY KEY REFERENCES accounts(account_id) ON DELETE CASCADE,
            workout_reminders INTEGER NOT NULL DEFAULT 0,
            alerts INTEGER NOT NULL DEFAULT 1,
            coach_updates INTEGER NOT NULL DEFAULT 1,
            reminder_time TEXT NOT NULL DEFAULT '18:00',
            quiet_start TEXT NOT NULL DEFAULT '22:00',
            quiet_end TEXT NOT NULL DEFAULT '08:00',
            timezone TEXT NOT NULL DEFAULT 'UTC'
        );
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            subscription_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
            device_id TEXT NOT NULL,
            endpoint TEXT NOT NULL UNIQUE,
            keys_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(account_id, device_id)
        );
        CREATE TABLE IF NOT EXISTS push_events (
            event_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
            dedupe_key TEXT NOT NULL,
            notification_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            template_id TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(account_id, dedupe_key)
        );
        CREATE TABLE IF NOT EXISTS push_deliveries (
            event_id TEXT NOT NULL REFERENCES push_events(event_id) ON DELETE CASCADE,
            subscription_id TEXT NOT NULL REFERENCES push_subscriptions(subscription_id) ON DELETE CASCADE,
            state TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt TEXT NOT NULL,
            lease_token TEXT,
            PRIMARY KEY(event_id, subscription_id)
        );
        CREATE INDEX IF NOT EXISTS push_due ON push_deliveries(state, next_attempt);
        CREATE TRIGGER IF NOT EXISTS clear_deleted_account_push
        AFTER UPDATE OF status ON accounts WHEN NEW.status = 'deleted' BEGIN
            DELETE FROM push_deliveries WHERE event_id IN
                (SELECT event_id FROM push_events WHERE account_id=NEW.account_id);
            DELETE FROM push_events WHERE account_id=NEW.account_id;
            DELETE FROM push_subscriptions WHERE account_id=NEW.account_id;
            DELETE FROM push_preferences WHERE account_id=NEW.account_id;
        END;
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(push_deliveries)")}
    if "lease_token" not in columns:
        conn.execute("ALTER TABLE push_deliveries ADD COLUMN lease_token TEXT")


DEFAULTS = dict(workout_reminders=False, alerts=True, coach_updates=True,
                reminder_time="18:00", quiet_start="22:00", quiet_end="08:00", timezone="UTC")


def preferences(db, account_id):
    with db.catalog_locked() as conn:
        columns = ", ".join(DEFAULTS)
        row = conn.execute(f"SELECT {columns} FROM push_preferences WHERE account_id=?", (account_id,)).fetchone()
    if row is None:
        return dict(DEFAULTS)
    result = {key: row[index] for index, key in enumerate(DEFAULTS)}
    for key in ("workout_reminders", "alerts", "coach_updates"):
        result[key] = bool(result[key])
    return result


def save_preferences(db, account_id, values):
    with db.catalog_transaction(immediate=True):
        conn = db.catalog_conn
        columns = ", ".join(DEFAULTS)
        updates = ", ".join(f"{key}=excluded.{key}" for key in DEFAULTS)
        conn.execute(f"INSERT INTO push_preferences (account_id, {columns}) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                     f"ON CONFLICT(account_id) DO UPDATE SET {updates}",
                     (account_id, *(values[key] for key in DEFAULTS)))
    return preferences(db, account_id)


def subscribe(db, account_id, device_id, endpoint, keys, now):
    with db.catalog_transaction(immediate=True):
        conn = db.catalog_conn
        # An endpoint belongs to the account currently signed in on that browser.
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint=? AND (account_id!=? OR device_id!=?)",
                     (endpoint, account_id, device_id))
        existing = conn.execute("SELECT subscription_id FROM push_subscriptions WHERE account_id=? AND device_id=?",
                                (account_id, device_id)).fetchone()
        if existing is None and conn.execute("SELECT COUNT(*) FROM push_subscriptions WHERE account_id=?",
                                             (account_id,)).fetchone()[0] >= 20:
            raise ValueError("Too many push devices. Remove an old device first.")
        conn.execute("INSERT INTO push_subscriptions VALUES (?, ?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT(account_id, device_id) DO UPDATE SET endpoint=excluded.endpoint, "
                     "keys_json=excluded.keys_json, updated_at=excluded.updated_at",
                     (uuid.uuid4().hex, account_id, device_id, endpoint, json.dumps(keys), now, now))


def unsubscribe(db, account_id, device_id):
    with db.catalog_transaction(immediate=True):
        conn = db.catalog_conn
        conn.execute("DELETE FROM push_subscriptions WHERE account_id=? AND device_id=?", (account_id, device_id))


def enqueue(conn, account_id, key, notification_type, payload, now=None, template_id=None):
    """Enqueue inside the caller's transaction; replay never adds new deliveries."""
    now = now or datetime.now(UTC).isoformat()
    event_id = uuid.uuid4().hex
    payload = {**payload, "tag": event_id}
    cursor = conn.execute("INSERT OR IGNORE INTO push_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (event_id, account_id, key, notification_type,
                           json.dumps(payload, ensure_ascii=False), template_id, now))
    if cursor.rowcount != 1:
        return False
    conn.execute("INSERT INTO push_deliveries (event_id, subscription_id, next_attempt) "
                 "SELECT ?, subscription_id, ? FROM push_subscriptions WHERE account_id=?",
                 (event_id, now, account_id))
    return True
