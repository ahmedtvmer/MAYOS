"""LedgerChatMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import uuid
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any


class LedgerChatMixin:
    def list_assistant_preferences(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, text, created_at, updated_at FROM assistant_preferences "
            "ORDER BY created_at, id"
        ).fetchall()
        return [dict(row) for row in rows]

    def add_assistant_preference(self, text: str) -> dict[str, Any] | None:
        cleaned = text.strip()
        if not cleaned or len(cleaned) > 200:
            raise ValueError("Preference must be between 1 and 200 characters.")
        now = datetime.now(UTC).isoformat()
        with self.ledger_transaction():
            count = self.conn.execute(
                "SELECT COUNT(*) FROM assistant_preferences"
            ).fetchone()[0]
            if count >= 50:
                return None
            preference_id = str(uuid.uuid4())
            self.conn.execute(
                "INSERT INTO assistant_preferences (id, text, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (preference_id, cleaned, now, now),
            )
        return {"id": preference_id, "text": cleaned, "created_at": now, "updated_at": now}

    def update_assistant_preference(self, preference_id: str, text: str) -> dict[str, Any] | None:
        cleaned = text.strip()
        if not cleaned or len(cleaned) > 200:
            raise ValueError("Preference must be between 1 and 200 characters.")
        now = datetime.now(UTC).isoformat()
        cursor = self.conn.execute(
            "UPDATE assistant_preferences SET text = ?, updated_at = ? WHERE id = ?",
            (cleaned, now, preference_id),
        )
        if cursor.rowcount != 1:
            return None
        self.conn.execute(
            "DELETE FROM assistant_preference_pending WHERE preference_id = ?",
            (preference_id,),
        )
        row = self.conn.execute(
            "SELECT id, text, created_at, updated_at FROM assistant_preferences WHERE id = ?",
            (preference_id,),
        ).fetchone()
        self._commit_ledger()
        return dict(row)

    def delete_assistant_preference(self, preference_id: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM assistant_preferences WHERE id = ?", (preference_id,)
        )
        if cursor.rowcount == 1:
            self.conn.execute(
                "DELETE FROM assistant_preference_pending WHERE preference_id = ?",
                (preference_id,),
            )
            self._commit_ledger()
            return True
        return False

    def closest_assistant_preference(self, query: str) -> dict[str, Any] | None:
        preferences = self.list_assistant_preferences()
        if not preferences:
            return None
        normalized_query = " ".join(query.casefold().split())
        return max(
            preferences,
            key=lambda preference: SequenceMatcher(
                None,
                normalized_query,
                " ".join(preference["text"].casefold().split()),
            ).ratio(),
        )

    def set_pending_assistant_preference_deletion(self, preference_id: str) -> None:
        self.conn.execute(
            "INSERT INTO assistant_preference_pending (id, preference_id, created_at) "
            "VALUES ('forget', ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "preference_id = excluded.preference_id, created_at = excluded.created_at",
            (preference_id, datetime.now(UTC).isoformat()),
        )
        self._commit_ledger()

    def get_pending_assistant_preference_deletion(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT p.id, p.text FROM assistant_preference_pending AS pending "
            "JOIN assistant_preferences AS p ON p.id = pending.preference_id "
            "WHERE pending.id = 'forget'"
        ).fetchone()
        return dict(row) if row else None

    def clear_pending_assistant_preference_deletion(self) -> None:
        self.conn.execute("DELETE FROM assistant_preference_pending WHERE id = 'forget'")
        self._commit_ledger()

    def add_chat_message(self, role: str, content: str) -> str:
        cursor = self.conn.cursor()
        msg_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO chat_history (id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (msg_id, role, content, datetime.now(UTC).isoformat()),
        )
        self._commit_ledger()
        return msg_id

    def get_chat_history(self, limit: int | None = None) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        if limit:
            cursor.execute(
                "SELECT id, role, content, created_at FROM chat_history ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            return [dict(r) for r in reversed(cursor.fetchall())]
        cursor.execute("SELECT id, role, content, created_at FROM chat_history ORDER BY created_at ASC")
        return [dict(r) for r in cursor.fetchall()]

    def clear_chat_history(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM chat_history")
        cursor.execute("DELETE FROM assistant_preference_pending")
        self.conn.commit()
