"""LedgerScheduleMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import json
import uuid
from typing import Any


class LedgerScheduleMixin:
    @staticmethod
    def _training_schedule_from_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "schedule_id": str(row["id"]),
            "trainee_id": str(row["trainee_id"]),
            "weekdays": json.loads(row["weekdays"]),
            "timezone": str(row["timezone"]),
            "effective_from": str(row["effective_from"]),
            "created_at": str(row["created_at"]),
        }

    def append_training_schedule(
        self,
        trainee_id: str,
        weekdays: list[int],
        timezone: str,
        effective_from: str,
        now_iso: str,
    ) -> dict[str, Any]:
        """Appends a new effective-dated schedule version; earlier versions are never rewritten."""
        schedule_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO training_schedules"
            " (id, trainee_id, weekdays, timezone, effective_from, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                schedule_id,
                str(trainee_id),
                json.dumps([int(day) for day in weekdays]),
                str(timezone),
                str(effective_from),
                now_iso,
            ),
        )
        self.conn.commit()
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM training_schedules WHERE id = ?", (schedule_id,))
        return self._training_schedule_from_row(cursor.fetchone())

    def _schedule_effective_on(self, trainee_id: str, on_date: str) -> dict[str, Any] | None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM training_schedules
            WHERE trainee_id = ? AND effective_from <= ?
            ORDER BY effective_from DESC, created_at DESC, rowid DESC
            LIMIT 1
        """,
            (str(trainee_id), str(on_date)),
        )
        return self._training_schedule_from_row(cursor.fetchone())

    def get_schedule_effective_on(self, trainee_id: str, on_date: str) -> dict[str, Any] | None:
        """Latest schedule effective on ``on_date`` — attendance for a past date uses it."""
        return self._schedule_effective_on(trainee_id, on_date)

    def list_training_schedules(self, trainee_id: str) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM training_schedules WHERE trainee_id = ?"
            " ORDER BY effective_from ASC, created_at ASC, rowid ASC",
            (str(trainee_id),),
        )
        return [self._training_schedule_from_row(row) for row in cursor.fetchall()]

    @staticmethod
    def _training_pause_from_row(row: Any) -> dict[str, Any]:
        return {
            "pause_id": str(row["id"]),
            "trainee_id": str(row["trainee_id"]),
            "starts_on": str(row["starts_on"]),
            "ends_on": str(row["ends_on"]),
            "created_at": str(row["created_at"]),
        }

    def schedule_training_pause(
        self, trainee_id: str, starts_on: str, ends_on: str, now_iso: str
    ) -> dict[str, Any]:
        """Persists one prospective pause; overlap between pauses is allowed."""
        pause_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO training_pauses (id, trainee_id, starts_on, ends_on, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (pause_id, str(trainee_id), str(starts_on), str(ends_on), now_iso),
        )
        self.conn.commit()
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM training_pauses WHERE id = ?", (pause_id,))
        return self._training_pause_from_row(cursor.fetchone())

    def list_training_pauses(self, trainee_id: str) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM training_pauses WHERE trainee_id = ?"
            " ORDER BY starts_on DESC, created_at DESC, rowid DESC",
            (str(trainee_id),),
        )
        return [self._training_pause_from_row(row) for row in cursor.fetchall()]

    def list_active_or_upcoming_training_pauses(
        self, trainee_id: str, on_date: str
    ) -> list[dict[str, Any]]:
        """Pauses still covering or yet to cover ``on_date`` (``ends_on >= on_date``)."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM training_pauses WHERE trainee_id = ? AND ends_on >= ?"
            " ORDER BY starts_on ASC, created_at ASC, rowid ASC",
            (str(trainee_id), str(on_date)),
        )
        return [self._training_pause_from_row(row) for row in cursor.fetchall()]
