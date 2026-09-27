"""LedgerOnboardingMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import json
from datetime import UTC, datetime
from typing import Any


class LedgerOnboardingMixin:
    def save_onboarding_state(self, state: dict[str, Any]) -> None:
        """Persists onboarding intake progress in the bound user's ledger (survives restarts)."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO onboarding_state (id, intake_step, is_complete, profile_data, messages, updated_at)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                intake_step = excluded.intake_step, is_complete = excluded.is_complete,
                profile_data = excluded.profile_data, messages = excluded.messages,
                updated_at = excluded.updated_at
            """,
            (
                int(state.get("intake_step", 1)),
                1 if state.get("is_complete") else 0,
                json.dumps(state.get("profile_data")),
                json.dumps(state.get("messages", [])),
                datetime.now(UTC).isoformat(),
            ),
        )
        self.conn.commit()

    def load_onboarding_state(self) -> dict[str, Any] | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT intake_step, is_complete, profile_data, messages FROM onboarding_state WHERE id = 1")
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "intake_step": row["intake_step"],
            "is_complete": bool(row["is_complete"]),
            "profile_data": json.loads(row["profile_data"]) if row["profile_data"] else None,
            "messages": json.loads(row["messages"]) if row["messages"] else [],
        }

    def clear_onboarding_state(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM onboarding_state WHERE id = 1")
        self.conn.commit()

    #: Writable columns of the single-row ``intake_state`` status table (ADR 021).
    _INTAKE_STATE_COLUMNS = (
        "status",
        "disclosure_acknowledged",
        "confirmed_at",
        "program_name",
        "weekly_frequency",
        "program_message",
    )

    def save_intake_answer(self, field: str, value: Any, prefilled: bool = False) -> None:
        """Upserts one named intake decision with its own ``updated_at`` (ADR 021).

        ``value`` is stored as JSON so a decision keeps its real type (string,
        number, or bool) across the ledger. The service layer owns validation;
        this layer only persists and returns what it stored.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO intake_answers (field, value, prefilled, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(field) DO UPDATE SET
                value = excluded.value, prefilled = excluded.prefilled, updated_at = excluded.updated_at
            """,
            (str(field), json.dumps(value), 1 if prefilled else 0, datetime.now(UTC).isoformat()),
        )
        self.conn.commit()

    def load_intake_answers(self) -> dict[str, dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT field, value, prefilled, updated_at FROM intake_answers")
        answers: dict[str, dict[str, Any]] = {}
        for row in cursor.fetchall():
            answers[row["field"]] = {
                "value": json.loads(row["value"]),
                "prefilled": bool(row["prefilled"]),
                "updated_at": row["updated_at"],
            }
        return answers

    def get_intake_state(self) -> dict[str, Any] | None:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT status, disclosure_acknowledged, confirmed_at, program_name, weekly_frequency,"
            " program_message, updated_at FROM intake_state WHERE id = 1"
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "status": row["status"],
            "disclosure_acknowledged": bool(row["disclosure_acknowledged"]),
            "confirmed_at": row["confirmed_at"],
            "program_name": row["program_name"],
            "weekly_frequency": row["weekly_frequency"],
            "program_message": row["program_message"],
            "updated_at": row["updated_at"],
        }

    def save_intake_state(self, **fields: Any) -> None:
        """Ensures the single status row exists, then updates the given columns.

        Only :attr:`_INTAKE_STATE_COLUMNS` are writable; unknown keys are ignored
        so a caller cannot smuggle an arbitrary column into the UPDATE.
        """
        now = datetime.now(UTC).isoformat()
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO intake_state (id, status, disclosure_acknowledged, updated_at)"
            " VALUES (1, 'in_progress', 0, ?)",
            (now,),
        )
        updates = {key: value for key, value in fields.items() if key in self._INTAKE_STATE_COLUMNS}
        if updates:
            assignments = ", ".join(f"{key} = ?" for key in updates)
            cursor.execute(
                f"UPDATE intake_state SET {assignments}, updated_at = ? WHERE id = 1",
                (*updates.values(), now),
            )
        self.conn.commit()

    def claim_intake_confirmation(self, now_iso: str) -> bool:
        """Atomically claims confirmation by moving the row in_progress->confirming.

        Runs inside one ``BEGIN IMMEDIATE`` ledger transaction, so two
        connections (request threads) racing ``POST /intake/confirm`` serialize:
        exactly one sees ``rowcount == 1``. The winner commits the claim before
        generating, so a concurrent caller observes ``confirming`` and is refused
        rather than generating a second program (ADR 021).
        """
        with self.ledger_transaction():
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE intake_state SET status = 'confirming', updated_at = ?"
                " WHERE id = 1 AND status = 'in_progress'",
                (str(now_iso),),
            )
            return cursor.rowcount == 1

    def release_intake_confirmation(self, now_iso: str) -> bool:
        """Releases a claim back to ``in_progress`` after a failed generation.

        Only a currently-``confirming`` row is touched, so a late failure cannot
        clobber an already-confirmed result.
        """
        with self.ledger_transaction():
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE intake_state SET status = 'in_progress', updated_at = ?"
                " WHERE id = 1 AND status = 'confirming'",
                (str(now_iso),),
            )
            return cursor.rowcount == 1
