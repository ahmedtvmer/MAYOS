"""Ledger queries and writes for per-muscle Volume reviews."""

from typing import Any


class LedgerVolumeReviewsMixin:
    def _curated_primary_muscles(self, placeholders: str, ids: list[str]) -> dict[str, str]:
        rows = self.conn.execute(
            f"SELECT exercise_id, primary_muscle FROM catalog.exercise_curated_fields WHERE exercise_id IN ({placeholders})",
            ids,
        ).fetchall()
        return {str(row["exercise_id"]): row["primary_muscle"] for row in rows if row["primary_muscle"]}

    def _catalog_target_muscles(self, placeholders: str, ids: list[str]) -> dict[str, str]:
        rows = self.conn.execute(
            f"SELECT id, target_muscle FROM exercises WHERE id IN ({placeholders})", ids
        ).fetchall()
        return {str(row["id"]): str(row["target_muscle"]).title() for row in rows if row["target_muscle"]}

    def volume_review_exercise_targets(self, exercise_ids: list[str]) -> dict[str, str | None]:
        """Returns curated primary muscles, falling back to catalog targets."""
        ids = sorted({str(value) for value in exercise_ids if value})
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        curated = self._curated_primary_muscles(placeholders, ids)
        fallback = self._catalog_target_muscles(placeholders, ids)
        return {exercise_id: curated.get(exercise_id) or fallback.get(exercise_id) for exercise_id in ids}

    def volume_review_workout_rows(self, version: int, start: str, end: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT s.id AS session_id, s.session_date, s.readiness_score, s.started_at, "
            "ws.exercise_id, ws.weight_kg, ws.reps, ws.rpe, ws.logged_at "
            "FROM workout_sets ws JOIN workout_sessions s ON s.id = ws.session_id "
            "WHERE s.program_version = ? AND s.session_date >= ? AND s.session_date <= ? "
            "AND ws.is_warmup = 0 AND ws.weight_kg >= 0 AND ws.reps > 0 "
            "ORDER BY s.session_date, s.started_at, ws.rowid",
            (version, start, end),
        ).fetchall()
        return [dict(row) for row in rows]

    def volume_review_workout_count(self, version: int, start: str, end: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM workout_sessions WHERE program_version = ? AND session_date >= ? AND session_date <= ?",
            (version, start, end),
        ).fetchone()
        return int(row[0])

    def volume_review_staple(self, exercise_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT name, equipment FROM exercises WHERE id = ?", (exercise_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_volume_review(self, version: int, review_date: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM volume_reviews WHERE program_version = ? AND review_date = ?",
            (version, review_date),
        ).fetchone()
        return dict(row) if row else None

    def latest_volume_review(self, version: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT status, next_eligible_date FROM volume_reviews "
            "WHERE program_version = ? ORDER BY review_date DESC LIMIT 1",
            (version,),
        ).fetchone()
        return dict(row) if row else None

    def save_volume_review(self, review: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO volume_reviews "
            "(id, program_version, review_date, next_eligible_date, status, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                review["id"], review["program_version"], review["review_date"],
                review["next_eligible_date"], review["status"], review["payload_json"],
                review["created_at"],
            ),
        )
        self._commit_ledger()

    def list_volume_reviews(self, version: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM volume_reviews WHERE program_version = ? AND (status = 'pending' "
            "OR (status = 'informational' AND review_date = ("
            "SELECT MAX(review_date) FROM volume_reviews WHERE program_version = ?))) "
            "ORDER BY review_date DESC",
            (version, version),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_volume_review_by_id(self, review_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM volume_reviews WHERE id = ?", (review_id,)
        ).fetchone()
        return dict(row) if row else None

    def set_volume_review_status(self, review_id: str, status: str, decided_at: str) -> None:
        self.conn.execute(
            "UPDATE volume_reviews SET status = ?, decided_at = ? WHERE id = ?",
            (status, decided_at, review_id),
        )
