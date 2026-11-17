"""Durable notification intents for domain changes stored in a player ledger."""

from dataclasses import dataclass
import uuid


PUSH_INTENTS_DDL = """
CREATE TABLE IF NOT EXISTS push_intents (
    intent_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    event TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(account_id, dedupe_key)
)
"""


@dataclass(frozen=True)
class PushIntent:
    account_id: str
    event: str
    dedupe_key: str
    created_at: str


def record_intent(conn, intent):
    conn.execute(
        "INSERT OR IGNORE INTO push_intents VALUES (?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, intent.account_id, intent.event, intent.dedupe_key, intent.created_at),
    )


def pending_intents(conn):
    return [dict(row) for row in conn.execute(
        "SELECT intent_id, account_id, event, dedupe_key, created_at "
        "FROM push_intents ORDER BY rowid"
    )]


def delete_intent(conn, intent_id):
    conn.execute("DELETE FROM push_intents WHERE intent_id=?", (intent_id,))


class LedgerPushMixin:
    """Ledger-handle surface for the durable push intents (#742).

    Layers must not reach for the handle's raw connection, so the intent
    writers go through the handle like every other ledger operation.
    """

    def record_push_intent(self, intent: PushIntent) -> None:
        record_intent(self.conn, intent)

    def pending_push_intents(self) -> list[dict]:
        return pending_intents(self.conn)

    def delete_push_intent(self, intent_id: str) -> None:
        delete_intent(self.conn, intent_id)
