"""Player chat history, keyword search, and assistant preference persistence."""

import json
import re
import sqlite3
import uuid
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from agent.chat_markers import is_session_pointer_text
from core.arabic import normalize_arabic_text

MAX_CHAT_HISTORY_SEARCH_RESULTS = 10


def _chat_search_text(role: str, content: str) -> str | None:
    if role not in {"user", "assistant"}:
        return None
    if role == "assistant" and is_session_pointer_text(content):
        return None
    normalized = normalize_arabic_text(content.casefold()).strip()
    return normalized or None


def _chat_search_expression(query: str) -> str | None:
    normalized = normalize_arabic_text(query.casefold())
    tokens = re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
    return " AND ".join(f'"{token}"' for token in tokens) or None


def _recent_chat_search_exclusions(
    conn: sqlite3.Connection, window_size: int | None = None
) -> list[str]:
    from agent.player_prompt import recent_history_messages

    rows = conn.execute(
        "SELECT id, role, content FROM chat_history ORDER BY created_at ASC"
    ).fetchall()
    recent_messages = recent_history_messages(
        [dict(row) for row in rows], window_size=window_size
    )
    return [message["id"] for message in recent_messages]


def _chat_search_clauses(
    conn: sqlite3.Connection,
    expression: str,
    start_date: date | None,
    end_date: date | None,
    recent_window_size: int | None,
) -> tuple[list[str], list[Any]]:
    clauses = ["chat_history_fts MATCH ?", "chat_history.role IN ('user', 'assistant')"]
    params: list[Any] = [expression]
    recent_ids = _recent_chat_search_exclusions(conn, recent_window_size)
    if recent_ids:
        placeholders = ", ".join("?" for _ in recent_ids)
        clauses.append(f"chat_history.id NOT IN ({placeholders})")
        params.extend(recent_ids)
    if start_date is not None:
        clauses.append("chat_history.created_at >= ?")
        params.append(f"{start_date.isoformat()}T00:00:00")
    if end_date is not None and end_date < date.max:
        clauses.append("chat_history.created_at < ?")
        params.append(f"{(end_date + timedelta(days=1)).isoformat()}T00:00:00")
    return clauses, params


def _search_chat_rows(
    conn: sqlite3.Connection, clauses: list[str], params: list[Any], limit: int
) -> list[dict[str, Any]]:
    params.append(min(max(limit, 1), MAX_CHAT_HISTORY_SEARCH_RESULTS))
    rows = conn.execute(
        "SELECT chat_history.role, chat_history.content, chat_history.created_at "
        "FROM chat_history_fts JOIN chat_history "
        "ON chat_history.id = chat_history_fts.message_id WHERE "
        + " AND ".join(clauses)
        + " ORDER BY chat_history.created_at DESC, chat_history.rowid DESC LIMIT ?",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


class LedgerChatMixin:
    def set_pending_chat_program_edit(self, proposal: dict[str, Any], offer_text: str) -> str:
        offer_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            "INSERT INTO assistant_goal_weak_point_pending "
            "(id, muscles_json, offer_id, kind, offer_text, created_at) VALUES (1, ?, ?, 'program_edit', ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET muscles_json = excluded.muscles_json, "
            "offer_id = excluded.offer_id, kind = excluded.kind, offer_text = excluded.offer_text, "
            "created_at = excluded.created_at",
            (json.dumps(proposal), offer_id, offer_text, now),
        )
        self._commit_ledger()
        return offer_id

    def get_pending_chat_program_edit(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT muscles_json, offer_id, offer_text, created_at "
            "FROM assistant_goal_weak_point_pending WHERE id = 1 AND kind = 'program_edit'"
        ).fetchone()
        if row is None:
            return None
        try:
            created = datetime.fromisoformat(row["created_at"])
            proposal = json.loads(row["muscles_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            self.clear_pending_chat_program_edit()
            return None
        if (datetime.now(UTC) - created).total_seconds() > 1800 or not isinstance(proposal, dict):
            self.clear_pending_chat_program_edit()
            return None
        return {"proposal": proposal, "offer_id": row["offer_id"], "offer_text": row["offer_text"]}

    def clear_pending_chat_program_edit(self) -> None:
        self.conn.execute(
            "DELETE FROM assistant_goal_weak_point_pending WHERE id = 1 AND kind = 'program_edit'"
        )
        self._commit_ledger()

    def update_pending_chat_program_edit_offer(self, offer_id: str, offer_text: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE assistant_goal_weak_point_pending SET offer_text = ?, created_at = ? "
            "WHERE id = 1 AND kind = 'program_edit' AND offer_id = ?",
            (offer_text, datetime.now(UTC).isoformat(), offer_id),
        )
        self._commit_ledger()
        return cursor.rowcount == 1

    def set_pending_goal_weak_point_suggestion(
        self, muscles: list[str], kind: str, offer_text: str
    ) -> None:
        now = datetime.now(UTC).isoformat()
        offer_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO assistant_goal_weak_point_pending "
            "(id, muscles_json, offer_id, kind, offer_text, created_at) VALUES (1, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET muscles_json = excluded.muscles_json, "
            "offer_id = excluded.offer_id, kind = excluded.kind, offer_text = excluded.offer_text, "
            "created_at = excluded.created_at",
            (json.dumps(muscles), offer_id, kind, offer_text, now),
        )
        self._commit_ledger()

    def get_pending_goal_weak_point_suggestion(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT muscles_json, offer_id, kind, offer_text, created_at "
            "FROM assistant_goal_weak_point_pending WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        try:
            created = datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError):
            created = datetime.min.replace(tzinfo=UTC)
        if (datetime.now(UTC) - created).total_seconds() > 1800:
            self.clear_pending_goal_weak_point_suggestion()
            return None
        muscles = json.loads(row["muscles_json"])
        return {
            "muscles": muscles, "offer_id": row["offer_id"], "kind": row["kind"],
            "offer_text": row["offer_text"],
        } if isinstance(muscles, list) else None

    def clear_pending_goal_weak_point_suggestion(self) -> None:
        self.conn.execute("DELETE FROM assistant_goal_weak_point_pending WHERE id = 1")
        self._commit_ledger()

    def set_pending_movement_restriction_offer(self, restrictions: list[str], offer_text: str) -> str:
        now = datetime.now(UTC).isoformat()
        offer_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO assistant_goal_weak_point_pending "
            "(id, muscles_json, offer_id, kind, offer_text, created_at) VALUES (1, ?, ?, 'movement_restriction', ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET muscles_json=excluded.muscles_json, offer_id=excluded.offer_id, "
            "kind=excluded.kind, offer_text=excluded.offer_text, created_at=excluded.created_at",
            (json.dumps(restrictions), offer_id, offer_text, now),
        )
        self._commit_ledger()
        return offer_id

    def get_pending_movement_restriction_offer(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT muscles_json, offer_id, offer_text, created_at FROM assistant_goal_weak_point_pending "
            "WHERE id=1 AND kind='movement_restriction'"
        ).fetchone()
        if row is None:
            return None
        try:
            created = datetime.fromisoformat(row["created_at"])
            restrictions = json.loads(row["muscles_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            self.clear_pending_goal_weak_point_suggestion()
            return None
        if (datetime.now(UTC) - created).total_seconds() > 1800 or not isinstance(restrictions, list):
            self.clear_pending_goal_weak_point_suggestion()
            return None
        return {"restrictions": restrictions, "offer_id": row["offer_id"], "offer_text": row["offer_text"]}

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
        msg_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()
        with self.ledger_transaction():
            self.conn.execute(
                "INSERT INTO chat_history (id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (msg_id, role, content, created_at),
            )
            search_text = _chat_search_text(role, content)
            if search_text is not None:
                self.conn.execute(
                    "INSERT INTO chat_history_fts (message_id, search_text) VALUES (?, ?)",
                    (msg_id, search_text),
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

    def search_chat_history(
        self,
        query: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 10,
        recent_window_size: int | None = None,
    ) -> list[dict[str, Any]]:
        if start_date is not None and end_date is not None and start_date > end_date:
            return []
        expression = _chat_search_expression(query)
        if expression is None:
            return []
        clauses, params = _chat_search_clauses(
            self.conn, expression, start_date, end_date, recent_window_size
        )
        return _search_chat_rows(self.conn, clauses, params, limit)

    def clear_chat_history(self) -> None:
        with self.ledger_transaction():
            self.conn.execute("DELETE FROM chat_history")
            self.conn.execute("DELETE FROM chat_history_fts")
            self.conn.execute("DELETE FROM assistant_preference_pending")
            self.conn.execute("DELETE FROM assistant_goal_weak_point_pending")
            self._commit_ledger()
