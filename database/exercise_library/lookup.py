"""Exercise library lookup with display names and aliases (ADR 053, #225)."""

import re
from dataclasses import dataclass
from typing import Any
from database.shared import _normalize_exercise_name
from database.exercise_library.names import near_miss_exercise_ids
from database.exercise_library.schema import (
    EFFECTIVE_EXERCISE_NAME_SQL,
    effective_exercise_name_sql,
)
from utils.equipment_access import equipment_access_sql


@dataclass(frozen=True)
class _NameSearch:
    query: str
    normalized_query: str
    muscle: str
    muscle_clause: str
    muscle_params: tuple[str, ...]
    equipment_clause: str | None
    limit: int


def _exercise_name_rows(cursor, where_sql: str, params: list[str], limit: int | None):
    name_expression, display_name_join = effective_exercise_name_sql()
    query = """
        SELECT e.id AS id, {name_expression} AS display_name, e.body_part AS body_part,
               e.target_muscle AS target_muscle, e.equipment AS equipment,
               e.image_path AS image_path, e.name AS source_name
        FROM exercises e
        {display_name_join}
        WHERE {where_sql}
        ORDER BY LENGTH(e.name)
    """.format(
        name_expression=name_expression,
        display_name_join=display_name_join,
        where_sql=where_sql,
    )
    if limit is not None:
        query += " LIMIT ?"
        params = [*params, limit]
    cursor.execute(query, params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _name_match_result(row):
    return {
        "id": str(row["id"]),
        "name": row["display_name"],
        "body_part": row["body_part"],
        "target_muscle": row["target_muscle"],
        "equipment": row["equipment"],
        "image_path": row["image_path"],
    }


def _name_match_results(rows):
    return [_name_match_result(row) for row in rows]


def _exact_name_rows(cursor, search: _NameSearch):
    where = (
        f"({search.muscle_clause}) AND (LOWER(e.name) = ? "
        f"OR LOWER({EFFECTIVE_EXERCISE_NAME_SQL}) = ? "
        "OR EXISTS (SELECT 1 FROM exercise_aliases a "
        "WHERE a.exercise_id = e.id AND a.normalized_alias = ?))"
    )
    params = [*search.muscle_params, search.query, search.query, search.normalized_query]
    return _exercise_name_rows(cursor, where, params, search.limit)


def _normalized_name_rows(cursor, search: _NameSearch):
    rows = _exercise_name_rows(cursor, search.muscle_clause, list(search.muscle_params), None)
    matches = [
        row for row in rows
        if _normalize_exercise_name(row["display_name"]) == search.normalized_query
        or _normalize_exercise_name(row["source_name"]) == search.normalized_query
    ]
    matches.sort(key=lambda row: len(row["source_name"] or ""))
    return matches[:search.limit]


def _substring_name_rows(cursor, search: _NameSearch):
    like = f"%{search.query}%"
    where = (
        f"({search.muscle_clause}) AND (LOWER(e.name) LIKE ? "
        f"OR LOWER({EFFECTIVE_EXERCISE_NAME_SQL}) LIKE ? "
        "OR EXISTS (SELECT 1 FROM exercise_aliases a "
        "WHERE a.exercise_id = e.id AND LOWER(a.alias) LIKE ?))"
    )
    return _exercise_name_rows(
        cursor, where, [*search.muscle_params, like, like, like], search.limit
    )


def _token_name_rows(cursor, search: _NameSearch):
    tokens = [token for token in re.split(r"\s+", search.query) if len(token) > 2]
    if not tokens:
        return []
    source_pattern = " AND ".join("LOWER(e.name) LIKE ?" for _ in tokens)
    display_pattern = " AND ".join(
        f"LOWER({EFFECTIVE_EXERCISE_NAME_SQL}) LIKE ?" for _ in tokens
    )
    alias_pattern = " AND ".join("LOWER(a.alias) LIKE ?" for _ in tokens)
    where = (
        f"({search.muscle_clause}) AND (({source_pattern}) OR ({display_pattern}) "
        "OR EXISTS (SELECT 1 FROM exercise_aliases a "
        f"WHERE a.exercise_id = e.id AND {alias_pattern}))"
    )
    token_values = [f"%{token}%" for token in tokens]
    params = [*search.muscle_params, *token_values, *token_values, *token_values]
    return _exercise_name_rows(cursor, where, params, search.limit)


def _find_name_rows(cursor, search: _NameSearch):
    if search.muscle and not search.query:
        where = search.muscle_clause
        if search.equipment_clause:
            where += f" AND ({search.equipment_clause})"
        return _exercise_name_rows(
            cursor, where, list(search.muscle_params), search.limit
        )
    if not search.normalized_query:
        return []
    for search_tier in (
        _exact_name_rows,
        _normalized_name_rows,
        _substring_name_rows,
        _token_name_rows,
    ):
        matches = search_tier(cursor, search)
        if matches:
            return matches
    return []


class ExerciseLookupMixin:
    def get_exercise_library_entry(self, exercise_id: str) -> dict[str, Any] | None:
        """One exercise by exact id, using its display name when it has one."""
        if not isinstance(exercise_id, str) or not exercise_id:
            return None
        name_expression, display_name_join = effective_exercise_name_sql()
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            cursor.execute(
                f"SELECT e.id, {name_expression} AS name, e.body_part, e.target_muscle, "
                f"e.equipment, e.instructions, e.image_path, e.gif_path, "
                "COALESCE(p.provenance, 'ExerciseDB') AS provenance "
                f"FROM exercises e {display_name_join} "
                f"LEFT JOIN exercise_provenance p ON p.exercise_id = e.id WHERE e.id = ?",
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
            "provenance": row[8],
        }

    def get_exercise_library_detail(self, exercise_id: str) -> dict[str, Any] | None:
        """One catalog exercise for the read-only exercise-detail view (#53).

        ``name`` uses the Exercise display name when present. ``category`` mirrors
        ``body_part`` in the source data, so the client sees the real value under both names.
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
        detail = {
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
        detail["provenance"] = entry["provenance"]
        return detail

    def find_exercises_by_name(
        self,
        query: str,
        limit: int = 5,
        target_muscle: str | None = None,
        equipment_access: str | None = None,
    ) -> list[dict[str, Any]]:
        """Ranked Exercise library matches across source names, display names, and aliases.

        Name tiers are exact → punctuation-insensitive → substring → token-AND.

        Each tier short-circuits: weaker-tier matches are only returned when every stronger
        tier came up empty. The substitution resolver uses this so an explicitly named
        exercise either resolves by name or refuses — it never falls through to semantic
        (embedding) ranking and installs a lexical sibling.

        ``target_muscle`` (#162) narrows every tier to one target in the Exercise
        library (case-insensitive ``target_muscle`` column). With a muscle and no name
        query it lists that muscle's exercises, so the logger's Replace search
        can open pre-filtered before the player types. ``equipment_access``
        filters only that unnamed muscle browse; explicit name queries remain
        unfiltered so players can still find movements outside their usual setup.
        """
        clean = query.strip().lower()
        muscle = (target_muscle or "").strip().lower()
        if limit <= 0 or (not clean and not muscle):
            return []
        search = _NameSearch(
            query=clean,
            normalized_query=_normalize_exercise_name(clean),
            muscle=muscle,
            muscle_clause="LOWER(e.target_muscle) = ?" if muscle else "1 = 1",
            muscle_params=(muscle,) if muscle else (),
            equipment_clause=(
                equipment_access_sql(equipment_access)
                if equipment_access and not clean
                else None
            ),
            limit=limit,
        )
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            rejected_ids = near_miss_exercise_ids(clean)
            rows = _find_name_rows(cursor, search)
            return _name_match_results(
                [row for row in rows if str(row["id"]) not in rejected_ids]
            )

    def find_exercise_by_name(self, query: str) -> dict[str, Any] | None:
        """Best Exercise library match (exact → punctuation-insensitive → substring → token-AND)."""
        matches = self.find_exercises_by_name(query, limit=1)
        return matches[0] if matches else None
