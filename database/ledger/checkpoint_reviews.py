"""Checkpoint review queries and writes for one training ledger (#221)."""

from typing import Any


class LedgerCheckpointReviewsMixin:
    def list_checkpoint_workouts(self) -> list[dict[str, str]]:
        rows = self.conn.execute(
            "SELECT id AS session_id, session_date "
            "FROM workout_sessions ORDER BY rowid"
        ).fetchall()
        return [dict(row) for row in rows]

    def list_checkpoint_working_sets(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT session_id, exercise_id, weight_kg, reps, rpe, is_warmup "
            "FROM workout_sets ORDER BY rowid"
        ).fetchall()
        return [dict(row) for row in rows]

    def list_checkpoint_personal_records(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT session_id, exercise_id FROM personal_records "
            "WHERE session_id IS NOT NULL ORDER BY rowid"
        ).fetchall()
        return [dict(row) for row in rows]

    def insert_checkpoint_review(self, review: dict[str, Any]) -> bool:
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO checkpoint_reviews "
            "(checkpoint, session_id, period_start, period_end, facts_json, "
            "rating_json, text, text_language, created_at, opened_at) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL)",
            (
                review["checkpoint"],
                review["session_id"],
                review["period_start"],
                review["period_end"],
                review["facts_json"],
                review["rating_json"],
                review["created_at"],
            ),
        )
        return cursor.rowcount == 1

    def list_checkpoint_review_rows(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT checkpoint, period_start, period_end, rating_json, opened_at "
            "FROM checkpoint_reviews ORDER BY checkpoint DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_checkpoint_review_row(self, checkpoint: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT checkpoint, period_start, period_end, facts_json, rating_json, text "
            "FROM checkpoint_reviews WHERE checkpoint = ?",
            (checkpoint,),
        ).fetchone()
        return None if row is None else dict(row)

    def mark_checkpoint_review_opened(self, checkpoint: int, opened_at: str) -> None:
        self.conn.execute(
            "UPDATE checkpoint_reviews SET opened_at = COALESCE(opened_at, ?) "
            "WHERE checkpoint = ?",
            (opened_at, checkpoint),
        )
        self._commit_ledger()
