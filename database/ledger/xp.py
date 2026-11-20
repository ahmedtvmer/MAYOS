"""XP awards and processed-session marks in the Training ledger (#743, #795).

Awards are append-only: XP never decreases. A session is processed once,
whether or not it earned workout XP (imported history and a second workout on
the same local day earn none), so a later read never revisits it.
"""

from __future__ import annotations

from typing import Any

XP_DDL = (
    "CREATE TABLE IF NOT EXISTS xp_sessions ("
    " session_id TEXT PRIMARY KEY,"
    " counted INTEGER NOT NULL CHECK(counted IN (0, 1)),"
    " session_date TEXT NOT NULL,"
    " processed_at TEXT NOT NULL"
    ")",
    "CREATE TABLE IF NOT EXISTS xp_awards ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " kind TEXT NOT NULL CHECK(kind IN ('planned_workout','all_sets','effort_in_range',"
    "'personal_record','cardio','weekly_streak')),"
    " xp INTEGER NOT NULL CHECK(xp >= 0),"
    " session_id TEXT,"
    " week_start TEXT,"
    " created_at TEXT NOT NULL,"
    " CHECK((session_id IS NULL) <> (week_start IS NULL))"
    ")",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_xp_awards_session_kind"
    " ON xp_awards(session_id, kind) WHERE session_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_xp_awards_week_kind"
    " ON xp_awards(week_start, kind) WHERE week_start IS NOT NULL",
)


class LedgerXpMixin:
    """Reads and writes the account's XP awards."""

    conn: Any

    def list_sessions_for_xp(self) -> list[dict[str, Any]]:
        """Every committed session, oldest first by insertion, with its program day."""
        rows = self.conn.execute(
            "SELECT id AS session_id, session_date, program_version,"
            " program_day_order, program_week_order"
            " FROM workout_sessions ORDER BY rowid"
        ).fetchall()
        return [dict(row) for row in rows]

    def xp_processed_session_ids(self) -> set[str]:
        return {str(row[0]) for row in self.conn.execute("SELECT session_id FROM xp_sessions")}

    def xp_session_counted(self, session_id: str) -> bool | None:
        """True or False once processed; None before the session is processed."""
        row = self.conn.execute(
            "SELECT counted FROM xp_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return None if row is None else bool(row[0])

    def xp_counted_dates(self) -> set[str]:
        return {
            str(row[0])
            for row in self.conn.execute(
                "SELECT session_date FROM xp_sessions WHERE counted = 1"
            )
        }

    def mark_xp_session(
        self, session_id: str, *, counted: bool, session_date: str, now_iso: str
    ) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO xp_sessions(session_id, counted, session_date, processed_at)"
            " VALUES (?, ?, ?, ?)",
            (session_id, 1 if counted else 0, session_date, now_iso),
        )

    def add_xp_award(
        self,
        kind: str,
        xp: int,
        *,
        now_iso: str,
        session_id: str | None = None,
        week_start: str | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO xp_awards(kind, xp, session_id, week_start, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (kind, int(xp), session_id, week_start, now_iso),
        )

    def xp_total(self) -> int:
        row = self.conn.execute("SELECT COALESCE(SUM(xp), 0) FROM xp_awards").fetchone()
        return int(row[0])

    def xp_awards_for_session(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT kind, xp FROM xp_awards WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [{"kind": str(row[0]), "xp": int(row[1])} for row in rows]

    def xp_awarded_weeks(self) -> set[str]:
        return {
            str(row[0])
            for row in self.conn.execute(
                "SELECT week_start FROM xp_awards WHERE week_start IS NOT NULL"
            )
        }

    def xp_session_working_sets(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT exercise_id, rpe FROM workout_sets"
            " WHERE session_id = ? AND COALESCE(is_warmup, 0) = 0 ORDER BY rowid",
            (session_id,),
        ).fetchall()
        return [{"exercise_id": str(row[0]), "rpe": row[1]} for row in rows]

    def xp_session_record_exercises(self, session_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(DISTINCT exercise_id) FROM personal_records WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return int(row[0])

    def xp_session_has_cardio(self, session_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM session_cardio_entries WHERE session_id = ? LIMIT 1",
            (session_id,),
        ).fetchone()
        return row is not None
