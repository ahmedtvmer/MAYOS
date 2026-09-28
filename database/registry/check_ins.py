"""RegistryCheckInsMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

from typing import Any


class RegistryCheckInsMixin:
    def upsert_roster_attendance(
        self,
        assignment_id: str,
        current_missed_streak: int,
        now_iso: str,
        timezone: str | None = None,
        last_workout_on: str | None = None,
        program_name: str | None = None,
    ) -> None:
        """Records the latest catalog-side attendance summary for one assignment.

        ``timezone`` is the player's local timezone as of this evaluation; when
        omitted the previously cached value is preserved (absent means UTC).
        ``last_workout_on`` is the newest committed session date (``None`` while
        the player has never trained) and ``program_name`` the active program's
        display name (``None`` while the player has no program); an omitted or
        ``None`` value likewise preserves what an earlier evaluation recorded.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT INTO roster_attendance"
                " (assignment_id, current_missed_streak, last_evaluated_at, timezone,"
                " last_workout_on, program_name)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(assignment_id) DO UPDATE SET"
                " current_missed_streak = excluded.current_missed_streak,"
                " last_evaluated_at = excluded.last_evaluated_at,"
                " timezone = COALESCE(excluded.timezone, roster_attendance.timezone),"
                " last_workout_on = COALESCE(excluded.last_workout_on, roster_attendance.last_workout_on),"
                " program_name = COALESCE(excluded.program_name, roster_attendance.program_name)",
                (
                    str(assignment_id),
                    int(current_missed_streak),
                    now_iso,
                    timezone,
                    last_workout_on,
                    program_name,
                ),
            )
            self.catalog_conn.commit()

    def set_roster_program_name(self, assignment_id: str, program_name: str | None) -> None:
        """Caches the active program's display name for one roster row (#120).

        Written by the evaluation and by a coach program publication, so the
        roster read never opens the player's ledger (ADR 025/030).
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT INTO roster_attendance (assignment_id, current_missed_streak, program_name)"
                " VALUES (?, 0, ?)"
                " ON CONFLICT(assignment_id) DO UPDATE SET"
                " program_name = excluded.program_name",
                (str(assignment_id), program_name),
            )
            self.catalog_conn.commit()

    def get_roster_timezone(self, assignment_id: str) -> str | None:
        """The player's cached timezone for an assignment, or ``None`` when unknown."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT timezone FROM roster_attendance WHERE assignment_id = ?",
                (str(assignment_id),),
            )
            row = cursor.fetchone()
            if row is None or row[0] is None or not str(row[0]).strip():
                return None
            return str(row[0])

    def latest_check_in_on(self, assignment_id: str) -> str | None:
        """The most recent check-in date for an assignment, or ``None`` if never."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT MAX(checked_in_on) FROM check_ins WHERE assignment_id = ?",
                (str(assignment_id),),
            )
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] else None

    def get_roster_alert_badges(self, coach_account_id: str) -> dict[str, dict[str, int]]:
        """New/acknowledged alert counts and streak length per active assignment (catalog-only)."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT a.assignment_id,"
                " COALESCE(r.current_missed_streak, 0) AS streak,"
                " COALESCE(SUM(CASE WHEN c.state = 'new' THEN 1 ELSE 0 END), 0) AS new_count,"
                " COALESCE(SUM(CASE WHEN c.state = 'acknowledged' THEN 1 ELSE 0 END), 0) AS ack_count"
                " FROM assignments a"
                " LEFT JOIN roster_attendance r ON r.assignment_id = a.assignment_id"
                " LEFT JOIN coach_alerts c ON c.assignment_id = a.assignment_id"
                " AND c.state IN ('new', 'acknowledged')"
                " WHERE a.coach_account_id = ? AND a.status = 'active'"
                " GROUP BY a.assignment_id",
                (str(coach_account_id),),
            )
            return {
                str(row[0]): {
                    "current_missed_streak": int(row[1]),
                    "alerts_new": int(row[2]),
                    "alerts_acknowledged": int(row[3]),
                }
                for row in cursor.fetchall()
            }

    _CHECK_IN_COLUMNS = (
        "check_in_id, assignment_id, coach_account_id, player_account_id,"
        " checked_in_on, channel, note, created_at"
    )

    @staticmethod
    def _check_in_from_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "check_in_id": str(row[0]),
            "assignment_id": str(row[1]),
            "coach_account_id": str(row[2]),
            "player_account_id": str(row[3]),
            "checked_in_on": str(row[4]),
            "channel": str(row[5]),
            "note": row[6],
            "created_at": str(row[7]),
        }

    def create_check_in(
        self,
        check_in_id: str,
        assignment_id: str,
        coach_account_id: str,
        player_account_id: str,
        checked_in_on: str,
        channel: str,
        note: str | None,
        now_iso: str,
    ) -> dict[str, Any]:
        """Inserts one immutable check-in row and returns it."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "INSERT INTO check_ins"
                " (check_in_id, assignment_id, coach_account_id, player_account_id,"
                " checked_in_on, channel, note, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(check_in_id),
                    str(assignment_id),
                    str(coach_account_id),
                    str(player_account_id),
                    str(checked_in_on),
                    str(channel),
                    note,
                    now_iso,
                ),
            )
            self.catalog_conn.commit()
            cursor.execute(
                f"SELECT {self._CHECK_IN_COLUMNS} FROM check_ins WHERE check_in_id = ?",
                (str(check_in_id),),
            )
            return self._check_in_from_row(cursor.fetchone())

    def list_assignment_check_ins(self, assignment_id: str) -> list[dict[str, Any]]:
        """Every check-in for one assignment, newest date first."""
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {self._CHECK_IN_COLUMNS} FROM check_ins"
                " WHERE assignment_id = ? ORDER BY checked_in_on DESC, rowid DESC",
                (str(assignment_id),),
            )
            return [self._check_in_from_row(row) for row in cursor.fetchall()]

    def list_player_check_ins(self, player_account_id: str) -> list[dict[str, Any]]:
        """Every check-in the player ever received, across active and ended assignments.

        The coach's current username is joined for display without ever reading
        another player's rows. A coach account that was deleted, or one whose row
        is gone, is presented as "Former coach" with no reusable username
        (ADR 031/039).
        """
        self.ensure_account_schema()
        columns = ", ".join("ci." + column for column in self._CHECK_IN_COLUMNS.split(", "))
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT {columns}, acc.username, a.status"
                " FROM check_ins ci"
                " LEFT JOIN accounts acc ON acc.account_id = ci.coach_account_id"
                " AND acc.deleted_at IS NULL"
                " LEFT JOIN assignments a ON a.assignment_id = ci.assignment_id"
                " WHERE ci.player_account_id = ?"
                " ORDER BY ci.checked_in_on DESC, ci.rowid DESC",
                (str(player_account_id),),
            )
            rows = []
            for row in cursor.fetchall():
                item = self._check_in_from_row(row)
                item["coach_username"] = str(row[8]) if row[8] else "Former coach"
                item["assignment_status"] = str(row[9]) if row[9] else "ended"
                rows.append(item)
            return rows

    def list_roster_follow_up_basis(self, coach_account_id: str) -> dict[str, dict[str, Any]]:
        """Catalog-only follow-up inputs per active assignment for the roster.

        Returns ``assignment_id -> {started_at, timezone, latest_check_in_on}`` so
        the service can compute ``next_follow_up_on`` without mounting a ledger.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT a.assignment_id, a.started_at, r.timezone, MAX(ci.checked_in_on)"
                " FROM assignments a"
                " LEFT JOIN roster_attendance r ON r.assignment_id = a.assignment_id"
                " LEFT JOIN check_ins ci ON ci.assignment_id = a.assignment_id"
                " WHERE a.coach_account_id = ? AND a.status = 'active'"
                " GROUP BY a.assignment_id, a.started_at, r.timezone",
                (str(coach_account_id),),
            )
            return {
                str(row[0]): {
                    "started_at": str(row[1]),
                    "timezone": str(row[2]) if row[2] else None,
                    "latest_check_in_on": str(row[3]) if row[3] else None,
                }
                for row in cursor.fetchall()
            }

    def list_roster_workout_basis(self, coach_account_id: str) -> dict[str, dict[str, Any]]:
        """Newest workout date and cached program name per active assignment (catalog-only).

        Returns ``assignment_id -> {last_workout_on, program_name}`` from the
        attendance summary, so the roster row labels both without mounting a
        player ledger (#118, #120). ``None`` covers both a player who has never
        trained (or has no program) and one whose attendance has not been
        evaluated yet.
        """
        self.ensure_account_schema()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT a.assignment_id, r.last_workout_on, r.program_name"
                " FROM assignments a"
                " LEFT JOIN roster_attendance r ON r.assignment_id = a.assignment_id"
                " WHERE a.coach_account_id = ? AND a.status = 'active'",
                (str(coach_account_id),),
            )
            return {
                str(row[0]): {
                    "last_workout_on": str(row[1]) if row[1] else None,
                    "program_name": str(row[2]) if row[2] else None,
                }
                for row in cursor.fetchall()
            }
