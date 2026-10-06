"""Coach-owned exercise definitions stored in the shared catalog."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from database.exercise_library.vocabulary import (
    equipment_category_for,
    equipment_category_sql,
)


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

    def search_coach_exercises(
        self,
        coach_account_id: str,
        query: str,
        limit: int | None = 10,
        equipment_categories: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        clean_query = query.strip().casefold()
        if (not clean_query and not equipment_categories) or (limit is not None and limit < 1):
            return []
        like_query = clean_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where = ["coach_account_id = ?"]
        params: list[Any] = [str(coach_account_id)]
        if clean_query:
            where.append("lower(name) LIKE lower(?) ESCAPE '\\'")
            params.append(f"%{like_query}%")
        if equipment_categories:
            placeholders = ", ".join("?" for _ in equipment_categories)
            where.append(
                f"({equipment_category_sql('equipment')}) IN ({placeholders})"
            )
            params.extend(equipment_categories)
        if clean_query:
            order_by = (
                "CASE WHEN lower(name) = lower(?) THEN 0 "
                "WHEN lower(name) LIKE lower(?) ESCAPE '\\' THEN 1 ELSE 2 END, lower(name), id"
            )
            params.extend((clean_query, f"{like_query}%"))
        else:
            order_by = "lower(name), id"
        limit_clause = " LIMIT ?" if limit is not None else ""
        if limit is not None:
            params.append(int(limit))
        with self._catalog_lock:
            rows = self.catalog_conn.execute(
                f"SELECT {COACH_EXERCISE_COLUMNS} "
                f"FROM coach_exercises WHERE {' AND '.join(where)} "
                f"ORDER BY {order_by}{limit_clause}",
                params,
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
            "equipment_category": equipment_category_for(row[3]),
            "load_type": None,
            "note": row[4],
            "video_url": row[5],
            "image_path": None,
            "gif_path": None,
            "primary_muscle": None,
            "primary_action": None,
            "secondary_actions": [],
            "is_coach_exercise": True,
        }
