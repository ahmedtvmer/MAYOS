"""Exercise semantic search, returning display names when present (ADR 053)."""

import sqlite_vec
from typing import Any
from database.exercise_library.embeddings import exercise_id_for_vector_sql
from database.exercise_library.schema import (
    effective_exercise_name_sql,
    exercise_library_visible_sql,
)


class ExerciseSimilarityMixin:
    def search_similar_exercises(self, query_vector: list[float], limit: int = 5) -> list[dict[str, Any]]:
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            serialized_vector = sqlite_vec.serialize_float32(query_vector)
            name_expression, display_name_join = effective_exercise_name_sql()
            visible_sql = exercise_library_visible_sql("e.id")
            exercise_id_expression = exercise_id_for_vector_sql("m.exercise_id")
            query = """
                WITH knn_matches AS (
                    SELECT exercise_id, distance
                    FROM vec_exercises
                    WHERE embedding MATCH ? AND k = ?
                )
                SELECT e.id, {name_expression}, e.body_part,
                       e.target_muscle, e.equipment, e.instructions, m.distance, e.name
                FROM knn_matches m
                JOIN exercises e ON e.id = {exercise_id_expression}
                {display_name_join}
                WHERE {visible_sql}
                ORDER BY m.distance ASC;
            """.format(
                name_expression=name_expression,
                display_name_join=display_name_join,
                exercise_id_expression=exercise_id_expression,
                visible_sql=visible_sql,
            )
            cursor.execute(query, (serialized_vector, limit * 3))
            columns = [
                "id", "name", "body_part", "target_muscle", "equipment", "instructions", "distance",
                "source_name",
            ]
            candidates = []
            for row in cursor.fetchall():
                record = dict(zip(columns, row))
                # Patterns match source names; a curated display name may spell them differently.
                names = f"{record['name']} {record['source_name']}".lower()
                if any(p in names for p in self.EXCLUDED_BIOMECHANICAL_PATTERNS):
                    continue
                candidates.append(record)
                if len(candidates) >= limit:
                    break
            return candidates
