"""Coach-owned exercise definitions stored in the shared catalog."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


COACH_EXERCISE_COLUMNS = "id, name, body_part, equipment, note, video_url"


@dataclass(frozen=True)
class CoachExerciseCreate:
    name: str
    body_part: str | None = None
    equipment: str | None = None
    note: str | None = None
    video_url: str | None = None


class RegistryCoachExercisesMixin:
    def create_coach_exercise(
        self, coach_account_id: str, fields: CoachExerciseCreate
    ) -> dict[str, Any]:
        exercise_id = f"coach:{uuid.uuid4()}"
        created_at = datetime.now(UTC).isoformat()
        with self.catalog_transaction(immediate=True):
            self.catalog_conn.execute(
                "INSERT INTO coach_exercises "
                "(id, coach_account_id, name, body_part, equipment, note, video_url, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    exercise_id,
                    str(coach_account_id),
                    fields.name,
                    fields.body_part,
                    fields.equipment,
                    fields.note,
                    fields.video_url,
                    created_at,
                ),
            )
        return self.get_coach_exercise(coach_account_id, exercise_id)

    def get_coach_exercise(self, coach_account_id: str, exercise_id: str) -> dict[str, Any] | None:
        with self._catalog_lock:
            row = self.catalog_conn.execute(
                f"SELECT {COACH_EXERCISE_COLUMNS} "
                "FROM coach_exercises WHERE coach_account_id = ? AND id = ?",
                (str(coach_account_id), str(exercise_id)),
            ).fetchone()
        return self._coach_exercise_from_row(row)

    def get_coach_exercise_unscoped(self, exercise_id: str) -> dict[str, Any] | None:
        """Resolves an existing Coach exercise id without checking its owner."""
        with self._catalog_lock:
            row = self.catalog_conn.execute(
                f"SELECT {COACH_EXERCISE_COLUMNS} "
                "FROM coach_exercises WHERE id = ?",
                (str(exercise_id),),
            ).fetchone()
        return self._coach_exercise_from_row(row)

    def search_coach_exercises(self, coach_account_id: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
        clean_query = query.strip().casefold()
        if not clean_query or limit < 1:
            return []
        like_query = clean_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._catalog_lock:
            rows = self.catalog_conn.execute(
                f"SELECT {COACH_EXERCISE_COLUMNS} "
                "FROM coach_exercises WHERE coach_account_id = ? "
                "AND lower(name) LIKE lower(?) ESCAPE '\\' "
                "ORDER BY CASE WHEN lower(name) = lower(?) THEN 0 "
                "WHEN lower(name) LIKE lower(?) ESCAPE '\\' THEN 1 ELSE 2 END, lower(name), id LIMIT ?",
                (str(coach_account_id), f"%{like_query}%", clean_query, f"{like_query}%", int(limit)),
            ).fetchall()
        return [self._coach_exercise_from_row(row) for row in rows]

    @staticmethod
    def _coach_exercise_from_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "name": str(row[1]),
            "body_part": row[2],
            "equipment": row[3],
            "note": row[4],
            "video_url": row[5],
            "image_path": None,
            "gif_path": None,
            "is_coach_exercise": True,
        }
