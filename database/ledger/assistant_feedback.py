"""Private, account-owned assistant reply feedback in the Training ledger."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
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
    " vote_notified_at TEXT,"
    " vote_redact_terms_json TEXT,"
    " report_reasons_json TEXT,"
    " report_note TEXT CHECK(report_note IS NULL OR length(report_note) <= 500),"
    " report_redact_terms_json TEXT,"
    " reported_at TEXT,"
    " report_delivered_at TEXT,"
    " delivery_claimed_at TEXT,"
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


# Preferred names the Player used before, kept only so a later report of an old
# reply still masks them (#838). Deleted with the ledger, and pruned once no
# chat message is old enough to contain one.
PREFERRED_NAME_HISTORY_DDL = (
    "CREATE TABLE IF NOT EXISTS preferred_name_history ("
    " name TEXT PRIMARY KEY CHECK(length(name) BETWEEN 1 AND 60),"
    " replaced_at TEXT NOT NULL"
    ")",
)

# Delivered reports and their excerpts are kept this many days (#838, policy 1.15).
REPORT_RETENTION_DAYS = 90


# A 👎 owes its owner a Discord send exactly when it carries at least one
# reason or a note and has never been sent (issue #764).
_VOTE_PENDING_PREDICATE = (
    "vote = 'down' AND vote_updated_at IS NOT NULL AND vote_notified_at IS NULL "
    "AND ((vote_reasons_json IS NOT NULL AND vote_reasons_json != '[]') "
    "OR vote_note IS NOT NULL)"
)
_VOTE_PENDING_PREDICATE_WHERE = "WHERE " + _VOTE_PENDING_PREDICATE + " "

# A report is still owed when it exists but has never been delivered (issue #748).
_REPORT_PENDING_PREDICATE = "reported_at IS NOT NULL AND report_delivered_at IS NULL"

# One row holds both a reply's report and its 👎, so a row may be dropped only
# when nothing on it is still owed: the report is absent or delivered AND the
# 👎 send is not owed. Both cleanup queries use this one predicate (#764).
ASSISTANT_FEEDBACK_ROW_DISPOSABLE_PREDICATE = (
    f"NOT ({_REPORT_PENDING_PREDICATE}) AND NOT ({_VOTE_PENDING_PREDICATE})"
)

# A send claim is a short-lived lease: a holder that crashed without marking
# or releasing loses it after this many minutes (issue #764).
DELIVERY_CLAIM_STALE_MINUTES = 10


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
        encoded_terms = json.dumps(
            context.get("redact_terms", []), ensure_ascii=False
        )
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
                    "vote_note = NULL, vote_redact_terms_json = NULL, vote_updated_at = NULL, "
                    "updated_at = ? "
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
                    "vote_redact_terms_json, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        feedback_id, str(account_id), message_id, context["reply_text"],
                        context["question_text"], context["language"], context["route"],
                        context.get("model"), context.get("prompt_version"), vote,
                        encoded_reasons, note, now, encoded_terms, now, now,
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
                    "vote_redact_terms_json = ?, "
                    "updated_at = ? WHERE account_id = ? AND message_id = ?",
                    (
                        vote,
                        encoded_reasons,
                        note,
                        int(changed), now, encoded_terms, now, str(account_id), message_id,
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
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            "UPDATE assistant_reply_feedback SET report_delivered_at = ?, "
            "delivery_claimed_at = NULL, updated_at = ? "
            "WHERE feedback_id = ? AND reported_at IS NOT NULL",
            (now, now, feedback_id),
        )
        self._commit_ledger()

    def claim_assistant_feedback_report_delivery(self, feedback_id: str) -> bool:
        """Atomically claims one pending report send for this process.

        Returns True only when this call took the claim; a concurrent retry or
        immediate send that loses the race gets False and must not post, so the
        same pending report is never posted twice. A claim older than
        ``DELIVERY_CLAIM_STALE_MINUTES`` is taken over: its holder crashed
        without marking or releasing. The claim is per row and covers both
        owed sends (report and 👎), so two sends on one row serialize instead
        of posting concurrently.
        """
        return self._claim_assistant_feedback_delivery(
            str(feedback_id), _REPORT_PENDING_PREDICATE
        )

    def claim_assistant_feedback_vote_delivery(self, feedback_id: str) -> bool:
        """Atomically claims one pending 👎 send; see the report claim."""
        return self._claim_assistant_feedback_delivery(
            str(feedback_id), _VOTE_PENDING_PREDICATE
        )

    def _claim_assistant_feedback_delivery(
        self, feedback_id: str, pending_predicate: str
    ) -> bool:
        # One claim per row serializes the row's two sends: a report and a 👎
        # on the same reply never post concurrently — the second waits for the
        # first. A holder that crashes after a successful post but before
        # marking leaves its claim to age out, which can cause one duplicate
        # post after the stale window; that trade-off is accepted (#764).
        now = datetime.now(UTC)
        stale_before = (
            now - timedelta(minutes=DELIVERY_CLAIM_STALE_MINUTES)
        ).isoformat()
        cursor = self.conn.execute(
            "UPDATE assistant_reply_feedback SET delivery_claimed_at = ?, updated_at = ? "
            f"WHERE feedback_id = ? AND {pending_predicate} "
            "AND (delivery_claimed_at IS NULL OR delivery_claimed_at < ?)",
            (now.isoformat(), now.isoformat(), feedback_id, stale_before),
        )
        self._commit_ledger()
        return cursor.rowcount == 1

    def release_assistant_feedback_delivery_claim(self, feedback_id: str) -> None:
        """Clears the send claim so the next retry pass can pick the row up."""
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            "UPDATE assistant_reply_feedback SET delivery_claimed_at = NULL, updated_at = ? "
            "WHERE feedback_id = ? AND delivery_claimed_at IS NOT NULL",
            (now, feedback_id),
        )
        self._commit_ledger()

    def pending_assistant_feedback_vote(self, feedback_id: str) -> dict[str, Any] | None:
        """Returns one 👎 row that still owes its owner Discord send, else None.

        Pending means: the current vote is 👎 with at least one reason or a
        note, and it has never been sent (``vote_notified_at`` is NULL). A 👍,
        an undo, a bare 👎, or an already-sent 👎 is never pending, so a flip
        back to 👍 cancels the send and a later edit is saved but not re-sent.
        """
        return self._pending_vote_row(
            "WHERE feedback_id = ? AND " + _VOTE_PENDING_PREDICATE, (str(feedback_id),)
        )

    def pending_assistant_feedback_votes(self, limit: int = 20) -> list[dict[str, Any]]:
        """Lists 👎 rows still owing their owner Discord send, oldest first."""
        rows = self.conn.execute(
            "SELECT feedback_id, question_text, reply_text, reply_language, route, "
            "vote_reasons_json, vote_note, vote_redact_terms_json, vote_updated_at "
            "FROM assistant_reply_feedback "
            f"{_VOTE_PENDING_PREDICATE_WHERE}ORDER BY vote_updated_at LIMIT ?",
            (min(max(int(limit), 1), 100),),
        ).fetchall()
        return [self._pending_vote_dict(row) for row in rows]

    def _pending_vote_row(
        self, clause: str, params: tuple[Any, ...]
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT feedback_id, question_text, reply_text, reply_language, route, "
            "vote_reasons_json, vote_note, vote_redact_terms_json, vote_updated_at "
            "FROM assistant_reply_feedback "
            + clause,
            params,
        ).fetchone()
        return self._pending_vote_dict(row) if row is not None else None

    @staticmethod
    def _pending_vote_dict(row: Any) -> dict[str, Any]:
        return {
            "feedback_id": str(row[0]),
            "question_text": str(row[1]),
            "reply_text": str(row[2]),
            "language": str(row[3]),
            "route": str(row[4]),
            "reasons": json.loads(row[5]) if row[5] else [],
            "note": row[6],
            "redact_terms": json.loads(row[7]) if row[7] else [],
            "vote_updated_at": str(row[8]),
        }

    def mark_assistant_feedback_vote_sent(self, feedback_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        # Only a still-standing 👎 can be marked: if the vote flipped away
        # during the send, the pending send is cancelled instead. Delivering
        # also clears the claim so the row's other owed send can claim.
        self.conn.execute(
            "UPDATE assistant_reply_feedback SET vote_notified_at = ?, "
            "delivery_claimed_at = NULL, updated_at = ? "
            "WHERE feedback_id = ? AND vote = 'down'",
            (now, now, feedback_id),
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
            f"WHERE {_REPORT_PENDING_PREDICATE} "
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
        """Removes rows whose chat message no longer exists and that owe nothing.

        Clearing the chat history keeps undelivered reports and undelivered 👎
        feedback so the owner still receives them. A row holds both a reply's
        report and its 👎, so it is removed only when both are absent or done
        (``ASSISTANT_FEEDBACK_ROW_DISPOSABLE_PREDICATE``) and the reply it
        belonged to is already gone (#748, #764). Coach-side feedback rows
        carry a synthetic message id that never has a chat message, so a fully
        delivered one is removed here too.
        """
        with self.ledger_transaction():
            cursor = self.conn.execute(
                "DELETE FROM assistant_reply_feedback "
                f"WHERE {ASSISTANT_FEEDBACK_ROW_DISPOSABLE_PREDICATE} "
                "AND NOT EXISTS (SELECT 1 FROM chat_history WHERE id = message_id)"
            )
            self._commit_ledger()
        return int(cursor.rowcount)

    def delete_expired_feedback_reports(self, now: datetime | None = None) -> int:
        """Removes reports delivered more than ``REPORT_RETENTION_DAYS`` ago (#838).

        The row goes with its excerpts; a row that still owes a 👎 send stays
        until that send is done.
        """
        cutoff = ((now or datetime.now(UTC)) - timedelta(days=REPORT_RETENTION_DAYS)).isoformat()
        with self.ledger_transaction():
            cursor = self.conn.execute(
                "DELETE FROM assistant_reply_feedback "
                "WHERE report_delivered_at IS NOT NULL AND report_delivered_at < ? "
                f"AND {ASSISTANT_FEEDBACK_ROW_DISPOSABLE_PREDICATE}",
                (cutoff,),
            )
            self._commit_ledger()
        return int(cursor.rowcount)

    def past_preferred_names(self) -> list[str]:
        return [str(row[0]) for row in self.conn.execute(
            "SELECT name FROM preferred_name_history ORDER BY replaced_at")]

    def prune_past_preferred_names(self) -> int:
        """Drops past names older than every remaining chat message (#838).

        A name can appear only in replies written before it was replaced, and
        reports already captured keep their own redaction terms.
        """
        with self.ledger_transaction():
            cursor = self.conn.execute(
                "DELETE FROM preferred_name_history WHERE NOT EXISTS ("
                "SELECT 1 FROM chat_history "
                "WHERE chat_history.created_at < preferred_name_history.replaced_at)"
            )
            self._commit_ledger()
        return int(cursor.rowcount)


__all__ = [
    "ASSISTANT_FEEDBACK_DDL",
    "PREFERRED_NAME_HISTORY_DDL",
    "REPORT_RETENTION_DAYS",
    "ASSISTANT_FEEDBACK_ROW_DISPOSABLE_PREDICATE",
    "LedgerAssistantFeedbackMixin",
]
