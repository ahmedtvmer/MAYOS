"""RegistryProgramRequestsMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

from typing import Any


class RegistryProgramRequestsMixin:
    _PROGRAM_REQUEST_COLUMNS = (
        "request_id, assignment_id, coach_account_id, player_account_id, kind, program_version,"
        " day_name, exercise_id, replacement_exercise_id, desired_weekly_frequency,"
        " desired_split_preference, reason, status, response, created_at, resolved_at, resolved_by"
    )
    #: The same columns qualified for the joined cross-roster listing (#118).
    _PROGRAM_REQUEST_COLUMNS_JOINED = ", ".join(
        f"pr.{column.strip()}" for column in _PROGRAM_REQUEST_COLUMNS.split(",")
    )

    @staticmethod
    def _program_request_from_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "request_id": str(row[0]),
            "assignment_id": str(row[1]),
            "coach_account_id": str(row[2]),
            "player_account_id": str(row[3]),
            "kind": str(row[4]),
            "program_version": int(row[5]),
            "day_name": row[6],
            "exercise_id": row[7],
            "replacement_exercise_id": row[8],
            "desired_weekly_frequency": int(row[9]) if row[9] is not None else None,
            "desired_split_preference": row[10],
            "reason": str(row[11]),
            "status": str(row[12]),
            "response": row[13],
            "created_at": str(row[14]),
            "resolved_at": row[15],
            "resolved_by": row[16],
        }

    def create_program_request(
        self,
        request_id: str,
        assignment_id: str,
        coach_account_id: str,
        player_account_id: str,
        kind: str,
        program_version: int,
        day_name: str | None,
        exercise_id: str | None,
        replacement_exercise_id: str | None,
        desired_weekly_frequency: int | None,
        desired_split_preference: str | None,
        reason: str,
        now_iso: str,
    ) -> str:
        """Inserts a pending player program request. Never touches the player ledger."""
        self.ensure_account_schema()
        with self._catalog_lock:
            self.catalog_conn.execute(
                "INSERT INTO program_requests"
                " (request_id, assignment_id, coach_account_id, player_account_id, kind, program_version,"
                " day_name, exercise_id, replacement_exercise_id, desired_weekly_frequency,"
                " desired_split_preference, reason, status, response, created_at, resolved_at, resolved_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, ?, NULL, NULL)",
                (
                    str(request_id),
                    str(assignment_id),
                    str(coach_account_id),
                    str(player_account_id),
                    str(kind),
                    int(program_version),
                    day_name,
                    exercise_id,
                    replacement_exercise_id,
                    desired_weekly_frequency,
                    desired_split_preference,
                    reason,
                    now_iso,
                ),
            )
            self.catalog_conn.commit()
        return request_id

    def get_program_request(self, request_id: str) -> dict[str, Any] | None:
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._PROGRAM_REQUEST_COLUMNS} FROM program_requests WHERE request_id = ?",
                (str(request_id),),
            )
            return self._program_request_from_row(cursor.fetchone())

    def list_program_requests_for_assignment(self, assignment_id: str) -> list[dict[str, Any]]:
        """Requests for one assignment, newest-first. Catalog-only; no ledger mount."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._PROGRAM_REQUEST_COLUMNS} FROM program_requests"
                " WHERE assignment_id = ? ORDER BY created_at DESC",
                (str(assignment_id),),
            )
            return [self._program_request_from_row(row) for row in cursor.fetchall()]

    def list_program_requests_for_player(self, player_account_id: str) -> list[dict[str, Any]]:
        """The player's own requests across assignments, newest-first."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._PROGRAM_REQUEST_COLUMNS} FROM program_requests"
                " WHERE player_account_id = ? ORDER BY created_at DESC",
                (str(player_account_id),),
            )
            return [self._program_request_from_row(row) for row in cursor.fetchall()]

    def pending_program_request_counts(self, coach_account_id: str) -> dict[str, int]:
        """Pending request counts per active assignment for one coach (catalog-only, #118).

        Requests on ended assignments are excluded with the assignment itself.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT pr.assignment_id, COUNT(*)"
                " FROM program_requests pr"
                " JOIN assignments a ON a.assignment_id = pr.assignment_id"
                " WHERE a.coach_account_id = ? AND a.status = 'active' AND pr.status = 'pending'"
                " GROUP BY pr.assignment_id",
                (str(coach_account_id),),
            )
            return {str(row[0]): int(row[1]) for row in cursor.fetchall()}

    def list_program_requests_for_coach(self, coach_account_id: str) -> list[dict[str, Any]]:
        """The coach's requests across active assignments, pending first (#118).

        Pending rows come first, oldest created first; answered rows follow,
        most recently resolved first. Ended assignments and other coaches'
        requests are excluded by the assignment join, and each row carries the
        requesting player's username beside the per-assignment fields.
        Catalog-only; no ledger mount.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._PROGRAM_REQUEST_COLUMNS_JOINED}, acc.username"
                " FROM program_requests pr"
                " JOIN assignments a ON a.assignment_id = pr.assignment_id"
                " LEFT JOIN accounts acc ON acc.account_id = pr.player_account_id"
                " WHERE a.coach_account_id = ? AND a.status = 'active'"
                " ORDER BY CASE WHEN pr.status = 'pending' THEN 0 ELSE 1 END,"
                " CASE WHEN pr.status = 'pending' THEN pr.created_at ELSE '' END ASC,"
                " CASE WHEN pr.status = 'pending' THEN ''"
                " ELSE COALESCE(pr.resolved_at, pr.created_at) END DESC,"
                " pr.request_id ASC",
                (str(coach_account_id),),
            )
            rows = []
            for row in cursor.fetchall():
                item = self._program_request_from_row(row)
                item["player_username"] = str(row[17]) if row[17] is not None else "former player"
                rows.append(item)
            return rows

    def resolve_program_request(
        self, request_id: str, status: str, response: str | None, resolved_by: str, now_iso: str
    ) -> dict[str, Any]:
        """Atomically claims a pending request; a second resolver sees ``rowcount == 0``."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE program_requests SET status = ?, response = ?, resolved_at = ?, resolved_by = ?"
                " WHERE request_id = ? AND status = 'pending'",
                (str(status), response, now_iso, str(resolved_by), str(request_id)),
            )
            self.catalog_conn.commit()
            return {"ok": cursor.rowcount == 1, "rowcount": int(cursor.rowcount)}

    def reopen_program_request(self, request_id: str, now_iso: str) -> dict[str, Any]:
        """Reverts an applied request back to pending after a post-claim write failure.

        Resets response and resolution provenance; only a currently-applied row is
        touched, so a racing cancel or decline is never clobbered.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "UPDATE program_requests SET status = 'pending', response = NULL,"
                " resolved_at = NULL, resolved_by = NULL"
                " WHERE request_id = ? AND status = 'applied'",
                (str(request_id),),
            )
            self.catalog_conn.commit()
            return {"ok": cursor.rowcount == 1, "rowcount": int(cursor.rowcount)}
