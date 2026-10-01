"""Exercise semantic search, returning display names when present (ADR 053)."""

import sqlite_vec
from typing import Any
from database.exercise_library.schema import effective_exercise_name_sql


class ExerciseSimilarityMixin:
    def search_similar_exercises(self, query_vector: list[float], limit: int = 5) -> list[dict[str, Any]]:
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            serialized_vector = sqlite_vec.serialize_float32(query_vector)
            name_expression, display_name_join = effective_exercise_name_sql()
            query = """
                WITH knn_matches AS (
                    SELECT exercise_id, distance
                    FROM vec_exercises
                    WHERE embedding MATCH ? AND k = ?
                )
                SELECT e.id, {name_expression}, e.body_part,
                       e.target_muscle, e.equipment, e.instructions, m.distance
                FROM knn_matches m
                JOIN exercises e ON e.id = CASE
                    WHEN m.exercise_id < 0 THEN 'mayos:' || CAST(-m.exercise_id AS TEXT)
                    ELSE CAST(m.exercise_id AS TEXT)
                END
                {display_name_join}
                ORDER BY m.distance ASC;
            """.format(
                name_expression=name_expression,
                display_name_join=display_name_join,
            )
            cursor.execute(query, (serialized_vector, limit * 3))
            columns = ["id", "name", "body_part", "target_muscle", "equipment", "instructions", "distance"]
            candidates = []
            for row in cursor.fetchall():
                record = dict(zip(columns, row))
                if any(p in record["name"].lower() for p in self.EXCLUDED_BIOMECHANICAL_PATTERNS):
                    continue
                candidates.append(record)
                if len(candidates) >= limit:
                    break
            return candidates
