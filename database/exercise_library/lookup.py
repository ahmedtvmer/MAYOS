"""ExerciseLookupMixin (database split, #78).

Extracted from DatabaseManager; behaviour is unchanged.
"""

import re
import sqlite3
from typing import Any
from database.shared import _normalize_exercise_name


class ExerciseLookupMixin:
    def get_exercise_library_entry(self, exercise_id: str) -> dict[str, Any] | None:
        """One catalog exercise by exact id, with the fields needed to swap it into a program."""
        if not isinstance(exercise_id, str) or not exercise_id:
            return None
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT id, name, body_part, target_muscle, equipment, instructions, image_path, gif_path"
                " FROM exercises WHERE id = ?",
                (str(exercise_id),),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "name": row[1],
            "body_part": row[2],
            "target_muscle": row[3],
            "equipment": row[4],
            "instructions": row[5],
            "image_path": row[6],
            "gif_path": row[7],
        }

    def get_exercise_library_detail(self, exercise_id: str) -> dict[str, Any] | None:
        """One catalog exercise for the read-only exercise-detail view (#53).

        ``category`` mirrors ``body_part`` in the source data (they are the same
        field upstream), so the client sees the real value under both names.
        Primary muscles come from ``target_muscle``; secondary muscles come from
        the ``exercise_secondary_muscles`` table. Instructions are the catalog's
        stored (English) text.
        """
        entry = self.get_exercise_library_entry(exercise_id)
        if entry is None:
            return None
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                "SELECT muscle FROM exercise_secondary_muscles WHERE exercise_id = ? ORDER BY muscle",
                (str(exercise_id),),
            )
            secondary = [str(row[0]) for row in cursor.fetchall()]
        target = entry.get("target_muscle")
        return {
            "id": entry["id"],
            "name": entry["name"],
            "category": entry["body_part"],
            "body_part": entry["body_part"],
            "equipment": entry["equipment"],
            "primary_muscles": [target] if target else [],
            "secondary_muscles": secondary,
            "instructions": entry.get("instructions"),
            "image_path": entry.get("image_path"),
            "gif_path": entry.get("gif_path"),
        }

    def find_exercises_by_name(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Ranked catalog name matches: exact → punctuation-insensitive → substring → token-AND.

        Each tier short-circuits: weaker-tier matches are only returned when every stronger
        tier came up empty. The substitution resolver uses this so an explicitly named
        exercise either resolves by name or refuses — it never falls through to semantic
        (embedding) ranking and installs a lexical sibling.
        """
        clean = query.strip().lower()
        if not clean or limit <= 0:
            return []

        columns = "id, name, body_part, target_muscle, equipment"
        matches: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _collect(row: sqlite3.Row | tuple | None) -> None:
            if row is None:
                return
            match_id = str(row[0])
            if match_id in seen:
                return
            seen.add(match_id)
            matches.append(
                {
                    "id": match_id,
                    "name": row[1],
                    "body_part": row[2],
                    "target_muscle": row[3],
                    "equipment": row[4],
                }
            )

        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(f"SELECT {columns} FROM exercises WHERE LOWER(name) = ? LIMIT ?", (clean, limit))
            for row in cursor.fetchall():
                _collect(row)
            if matches:
                return matches

            normalized = _normalize_exercise_name(clean)
            if normalized:
                cursor.execute(f"SELECT {columns} FROM exercises")
                normalized_rows = [row for row in cursor.fetchall() if _normalize_exercise_name(row[1]) == normalized]
                normalized_rows.sort(key=lambda row: len(row[1] or ""))
                for row in normalized_rows[:limit]:
                    _collect(row)
                if matches:
                    return matches

            cursor.execute(
                f"SELECT {columns} FROM exercises WHERE LOWER(name) LIKE ? ORDER BY LENGTH(name) ASC LIMIT ?",
                (f"%{clean}%", limit),
            )
            for row in cursor.fetchall():
                _collect(row)
            if matches:
                return matches

            tokens = [t for t in re.split(r"\s+", clean) if len(t) > 2]
            if tokens:
                where_clauses = ["LOWER(name) LIKE ?" for _ in tokens]
                cursor.execute(
                    f"SELECT {columns} FROM exercises WHERE {' AND '.join(where_clauses)}"
                    " ORDER BY LENGTH(name) ASC LIMIT ?",
                    [*[f"%{t}%" for t in tokens], limit],
                )
                for row in cursor.fetchall():
                    _collect(row)

        return matches

    def find_exercise_by_name(self, query: str) -> dict[str, Any] | None:
        """Best catalog name match (exact → punctuation-insensitive → substring → token-AND)."""
        matches = self.find_exercises_by_name(query, limit=1)
        return matches[0] if matches else None
