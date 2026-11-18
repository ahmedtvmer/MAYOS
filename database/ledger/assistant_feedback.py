"""Private, account-owned assistant reply feedback in the Training ledger."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any


ASSISTANT_FEEDBACK_DDL = (
    "CREATE TABLE IF NOT EXISTS assistant_reply_feedback ("
    " feedback_id TEXT PRIMARY KEY,"
    " account_id TEXT NOT NULL,"
    " message_id TEXT NOT NULL,"
    " reply_text TEXT NOT NULL CHECK(length(reply_text) <= 20000),"
    " question_text TEXT NOT NULL CHECK(length(question_text) <= 10000),"
    " reply_language TEXT NOT NULL CHECK(reply_language IN ('en','ar')) ,"
    " route TEXT NOT NULL CHECK(length(route) <= 120),"
    " model TEXT CHECK(model IS NULL OR length(model) <= 120),"
    " prompt_version TEXT CHECK(prompt_version IS NULL OR length(prompt_version) <= 160),"
    " vote TEXT CHECK(vote IS NULL OR vote IN ('up','down')) ,"
    " vote_reasons_json TEXT NOT NULL DEFAULT '[]',"
    " vote_note TEXT CHECK(vote_note IS NULL OR length(vote_note) <= 500),"
    " vote_updated_at TEXT,"
    " report_reasons_json TEXT,"
    " report_note TEXT CHECK(report_note IS NULL OR length(report_note) <= 500),"
    " report_redact_terms_json TEXT,"
    " reported_at TEXT,"
    " report_delivered_at TEXT,"
    " created_at TEXT NOT NULL,"
    " updated_at TEXT NOT NULL,"
    " UNIQUE(account_id, message_id),"
    " CHECK((reported_at IS NULL) = (report_reasons_json IS NULL))"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_assistant_feedback_vote_time "
    "ON assistant_reply_feedback(vote_updated_at, vote)",
    "CREATE INDEX IF NOT EXISTS idx_assistant_feedback_report_time "
    "ON assistant_reply_feedback(reported_at)",
)


class LedgerAssistantFeedbackMixin:
    """Write and read feedback only through the current account's ledger handle."""

    def get_assistant_feedback_for_messages(
        self, account_id: str, message_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not message_ids:
            return {}
        placeholders = ", ".join("?" for _ in message_ids)
        rows = self.conn.execute(
            "SELECT message_id, feedback_id, vote, reported_at "
            f"FROM assistant_reply_feedback WHERE account_id = ? AND message_id IN ({placeholders})",
            (str(account_id), *message_ids),
        ).fetchall()
        return {
            str(row[0]): {
                "feedback_id": str(row[1]),
                "vote": row[2],
                "reported": row[3] is not None,
            }
            for row in rows
        }

    def get_chat_message_feedback_source(self, message_id: str) -> dict[str, Any] | None:
        """Loads one persisted assistant reply and the user question before it.

        Lets the server re-derive a feedback context for a message id the client
        already holds, so a vote or report works even after the client's cached
        context is gone. ``None`` when the id is not a stored assistant reply or
        no user message precedes it.
        """
        row = self.conn.execute(
            "SELECT rowid, role, content, reply_language, assistant_route, "
            "assistant_model, assistant_prompt_version FROM chat_history WHERE id = ?",
            (str(message_id),),
        ).fetchone()
        if row is None or str(row[1]) != "assistant":
            return None
        question = self.conn.execute(
            "SELECT content FROM chat_history "
            "WHERE role = 'user' AND rowid < ? ORDER BY rowid DESC LIMIT 1",
            (int(row[0]),),
        ).fetchone()
        if question is None:
            return None
        return {
            "message_id": str(message_id),
            "reply_text": str(row[2]),
            "question_text": str(question[0]),
            "language": row[3],
            "route": row[4],
            "model": row[5],
            "prompt_version": row[6],
        }

    def set_assistant_reply_vote(
        self,
        context: dict[str, Any],
        account_id: str,
        vote: str | None,
        reasons: list[str],
        note: str | None,
    ) -> dict[str, Any] | None:
        """Sets or clears a reply's current vote; replaying a value is idempotent.

        Reasons and a note belong to a 👎: for 👍/clear they are dropped here so
        the stored state stays consistent (switching 👎→👍 clears them), and a
        bare replay of an unchanged 👎 never erases its stored reasons or note.
        """
        if vote != "down":
            reasons, note = [], None
        now = datetime.now(UTC).isoformat()
        message_id = str(context["message_id"])
        encoded_reasons = json.dumps(reasons, ensure_ascii=False, separators=(",", ":"))
        with self.ledger_transaction(immediate=True):
            row = self.conn.execute(
                "SELECT feedback_id, vote, vote_reasons_json, vote_note "
                "FROM assistant_reply_feedback "
                "WHERE account_id = ? AND message_id = ?",
                (str(account_id), message_id),
            ).fetchone()
            if vote is None:
                if row is None:
                    return None
                self.conn.execute(
                    "UPDATE assistant_reply_feedback SET vote = NULL, vote_reasons_json = '[]', "
                    "vote_note = NULL, vote_updated_at = NULL, updated_at = ? "
                    "WHERE account_id = ? AND message_id = ?",
                    (now, str(account_id), message_id),
                )
                result = {"feedback_id": str(row[0]), "vote": None}
            elif row is None:
                feedback_id = str(uuid.uuid4())
                self.conn.execute(
                    "INSERT INTO assistant_reply_feedback "
                    "(feedback_id, account_id, message_id, reply_text, question_text, reply_language, "
                    "route, model, prompt_version, vote, vote_reasons_json, vote_note, vote_updated_at, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        feedback_id, str(account_id), message_id, context["reply_text"],
                        context["question_text"], context["language"], context["route"],
                        context.get("model"), context.get("prompt_version"), vote,
                        encoded_reasons, note, now, now, now,
                    ),
                )
                result = {"feedback_id": feedback_id, "vote": vote}
            elif row[1] == vote and not reasons and not note and (
                vote == "down" or (row[2] in (None, "[]") and row[3] is None)
            ):
                # Idempotent replay: a bare 👎 retry never erases the stored
                # reasons or note, and a 👍 replay on an already-clean row
                # changes nothing. A stale 👍 row (reasons/note present) falls
                # through to the update and is cleaned.
                result = {"feedback_id": str(row[0]), "vote": vote}
            else:
                feedback_id, old_vote = str(row[0]), row[1]
                changed = old_vote != vote
                self.conn.execute(
                    "UPDATE assistant_reply_feedback SET vote = ?, vote_reasons_json = ?, vote_note = ?, "
                    "vote_updated_at = CASE WHEN ? THEN ? ELSE vote_updated_at END, "
                    "updated_at = ? WHERE account_id = ? AND message_id = ?",
                    (
                        vote,
                        encoded_reasons,
                        note,
                        int(changed), now, now, str(account_id), message_id,
                    ),
                )
                result = {"feedback_id": feedback_id, "vote": vote}
            self._commit_ledger()
        return result

    def record_assistant_reply_report(
        self,
        context: dict[str, Any],
        account_id: str,
        reasons: list[str],
        note: str | None,
    ) -> dict[str, Any]:
        """Records one report per reply, making client retries safe."""
        now = datetime.now(UTC).isoformat()
        message_id = str(context["message_id"])
        encoded_reasons = json.dumps(reasons, ensure_ascii=False, separators=(",", ":"))
        with self.ledger_transaction(immediate=True):
            row = self.conn.execute(
                "SELECT feedback_id, reported_at, report_delivered_at FROM assistant_reply_feedback "
                "WHERE account_id = ? AND message_id = ?",
                (str(account_id), message_id),
            ).fetchone()
            if row is not None and row[1] is not None:
                return {
                    "feedback_id": str(row[0]),
                    "created": False,
                    "delivery_pending": row[2] is None,
                }
            if row is None:
                feedback_id = str(uuid.uuid4())
                self.conn.execute(
                    "INSERT INTO assistant_reply_feedback "
                    "(feedback_id, account_id, message_id, reply_text, question_text, reply_language, "
                    "route, model, prompt_version, report_reasons_json, report_note, "
                    "report_redact_terms_json, reported_at, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        feedback_id, str(account_id), message_id, context["reply_text"],
                        context["question_text"], context["language"], context["route"],
                        context.get("model"), context.get("prompt_version"), encoded_reasons,
                        note, json.dumps(context.get("redact_terms", []), ensure_ascii=False),
                        now, now, now,
                    ),
                )
            else:
                feedback_id = str(row[0])
                self.conn.execute(
                    "UPDATE assistant_reply_feedback SET report_reasons_json = ?, report_note = ?, "
                    "report_redact_terms_json = ?, reported_at = ?, updated_at = ? "
                    "WHERE account_id = ? AND message_id = ?",
                    (encoded_reasons, note,
                     json.dumps(context.get("redact_terms", []), ensure_ascii=False),
                     now, now, str(account_id), message_id),
                )
            self._commit_ledger()
        return {"feedback_id": feedback_id, "created": True}

    def mark_assistant_feedback_report_delivered(self, feedback_id: str) -> None:
        self.conn.execute(
            "UPDATE assistant_reply_feedback SET report_delivered_at = ?, updated_at = ? "
            "WHERE feedback_id = ? AND reported_at IS NOT NULL",
            (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat(), feedback_id),
        )
        self._commit_ledger()

    def assistant_feedback_week_summary(
        self, account_id: str, start_at: str, end_at: str
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT vote, vote_reasons_json, route, reply_language FROM assistant_reply_feedback "
            "WHERE account_id = ? AND vote_updated_at >= ? AND vote_updated_at < ? AND vote IS NOT NULL",
            (str(account_id), start_at, end_at),
        ).fetchall()
        return [
            {
                "vote": row[0],
                "reasons": json.loads(row[1]) if row[1] else [],
                "route": row[2],
                "language": row[3],
            }
            for row in rows
        ]

    def pending_assistant_feedback_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT feedback_id, reply_text, question_text, reply_language, route, "
                "report_reasons_json, report_note, reported_at, report_redact_terms_json "
                "FROM assistant_reply_feedback "
            "WHERE reported_at IS NOT NULL AND report_delivered_at IS NULL "
            "ORDER BY reported_at LIMIT ?",
            (min(max(int(limit), 1), 100),),
        ).fetchall()
        return [
            {
                "feedback_id": str(row[0]),
                "reply_text": str(row[1]),
                "question_text": str(row[2]),
                "language": str(row[3]),
                "route": str(row[4]),
                "reasons": json.loads(row[5]) if row[5] else [],
                "note": row[6],
                "reported_at": str(row[7]),
                "redact_terms": json.loads(row[8]) if row[8] else [],
            }
            for row in rows
        ]

    def delete_delivered_feedback_without_message(self) -> int:
        """Removes delivered feedback rows whose chat message no longer exists.

        Clearing the chat history keeps undelivered reports so the owner still
        receives them; once the retry pass delivers one, the reply it belonged
        to is already gone and the row has no remaining surface (#748).
        """
        with self.ledger_transaction():
            cursor = self.conn.execute(
                "DELETE FROM assistant_reply_feedback "
                "WHERE reported_at IS NOT NULL AND report_delivered_at IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM chat_history WHERE id = message_id)"
            )
            self._commit_ledger()
        return int(cursor.rowcount)


__all__ = ["ASSISTANT_FEEDBACK_DDL", "LedgerAssistantFeedbackMixin"]
