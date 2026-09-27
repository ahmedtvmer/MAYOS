"""ExerciseSimilarityMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import sqlite_vec
from typing import Any


class ExerciseSimilarityMixin:
    def search_similar_exercises(self, query_vector: list[float], limit: int = 5) -> list[dict[str, Any]]:
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            serialized_vector = sqlite_vec.serialize_float32(query_vector)
            query = """
                WITH knn_matches AS (
                    SELECT exercise_id, distance
                    FROM vec_exercises
                    WHERE embedding MATCH ? AND k = ?
                )
                SELECT e.id, e.name, e.body_part, e.target_muscle, e.equipment, e.instructions, m.distance
                FROM knn_matches m
                JOIN exercises e ON CAST(e.id AS INTEGER) = m.exercise_id
                ORDER BY m.distance ASC;
            """
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
