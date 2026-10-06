"""Exercise library lookup with display names and aliases (ADR 053, #225)."""

import re
from dataclasses import dataclass
from typing import Any, Iterable, Literal
from database.shared import _normalize_exercise_name
from database.exercise_library.filters import ExerciseFilters
from database.exercise_library.names import near_miss_exercise_ids
from database.exercise_library.schema import (
    EFFECTIVE_EXERCISE_NAME_SQL,
    effective_exercise_name_sql,
    exercise_library_visible_sql,
)
from utils.equipment_access import equipment_access_sql


@dataclass(frozen=True)
class _NameSearch:
    query: str
    normalized_query: str
    filter_clause: str
    filter_params: tuple[str, ...]
    equipment_clause: str | None
    filter_browse: bool
    limit: int | None


def _exercise_name_rows(
    cursor,
    where_sql: str,
    params: list[str],
    limit: int | None,
    *,
    ranking: Literal["name_length", "display_name_first"] = "name_length",
):
    name_expression, display_name_join = effective_exercise_name_sql()
    if ranking == "display_name_first":
        order_by = (
            "CASE WHEN COALESCE(d.is_reviewed, 0) = 1 THEN 0 ELSE 1 END, "
            f"LOWER({name_expression}), e.id"
        )
    else:
        order_by = "LENGTH(e.name)"
    where_sql = f"({where_sql}) AND ({exercise_library_visible_sql('e.id')})"
    query = """
        SELECT e.id AS id, {name_expression} AS display_name, e.body_part AS body_part,
               e.target_muscle AS target_muscle, e.equipment AS equipment,
               e.image_path AS image_path, e.name AS source_name,
               cf.primary_muscle AS primary_muscle,
               cf.primary_action AS primary_action,
               COALESCE(cf.secondary_actions, '') AS secondary_actions
        FROM exercises e
        {display_name_join}
        LEFT JOIN exercise_curated_fields cf ON cf.exercise_id = e.id
        WHERE {where_sql}
        ORDER BY {order_by}
    """.format(
        name_expression=name_expression,
        display_name_join=display_name_join,
        where_sql=where_sql,
        order_by=order_by,
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
        "primary_muscle": row["primary_muscle"],
        "primary_action": row["primary_action"],
        "secondary_actions": _split_secondary_actions(row["secondary_actions"]),
    }


def _split_secondary_actions(value: str | None) -> list[str]:
    return [action for action in (value or "").split("|") if action]


def _name_match_results(rows):
    return [_name_match_result(row) for row in rows]


def _exact_name_rows(cursor, search: _NameSearch):
    where = (
        f"({search.filter_clause}) AND (LOWER(e.name) = ? "
        f"OR LOWER({EFFECTIVE_EXERCISE_NAME_SQL}) = ? "
        "OR EXISTS (SELECT 1 FROM exercise_aliases a "
        "WHERE a.exercise_id = e.id AND a.normalized_alias = ?))"
    )
    params = [*search.filter_params, search.query, search.query, search.normalized_query]
    return _exercise_name_rows(cursor, where, params, search.limit)


def _normalized_name_rows(cursor, search: _NameSearch):
    rows = _exercise_name_rows(cursor, search.filter_clause, list(search.filter_params), None)
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
        f"({search.filter_clause}) AND (LOWER(e.name) LIKE ? "
        f"OR LOWER({EFFECTIVE_EXERCISE_NAME_SQL}) LIKE ? "
        "OR EXISTS (SELECT 1 FROM exercise_aliases a "
        "WHERE a.exercise_id = e.id AND LOWER(a.alias) LIKE ?))"
    )
    return _exercise_name_rows(
        cursor, where, [*search.filter_params, like, like, like], search.limit
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
        f"({search.filter_clause}) AND (({source_pattern}) OR ({display_pattern}) "
        "OR EXISTS (SELECT 1 FROM exercise_aliases a "
        f"WHERE a.exercise_id = e.id AND {alias_pattern}))"
    )
    token_values = [f"%{token}%" for token in tokens]
    params = [*search.filter_params, *token_values, *token_values, *token_values]
    return _exercise_name_rows(cursor, where, params, search.limit)


def _find_name_rows(cursor, search: _NameSearch):
    if search.filter_browse:
        where = search.filter_clause
        if search.equipment_clause:
            where += f" AND ({search.equipment_clause})"
        return _exercise_name_rows(
            cursor,
            where,
            list(search.filter_params),
            search.limit,
            ranking="display_name_first",
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
    def get_exercise_library_entries(
        self,
        exercise_ids: Iterable[str],
    ) -> dict[str, dict[str, Any]]:
        """Fetch Exercise library rows in batches, without one query per exercise."""
        ids = list(dict.fromkeys(
            exercise_id
            for exercise_id in exercise_ids
            if isinstance(exercise_id, str) and exercise_id
        ))
        if not ids:
            return {}

        name_expression, display_name_join = effective_exercise_name_sql()
        entries: dict[str, dict[str, Any]] = {}
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            for start in range(0, len(ids), 500):
                batch = ids[start : start + 500]
                placeholders = ", ".join("?" for _ in batch)
                cursor.execute(
                    f"SELECT e.id, {name_expression} AS name, e.body_part, e.target_muscle, "
                    f"e.equipment, e.instructions, e.image_path, e.gif_path, "
                    "COALESCE(p.provenance, 'ExerciseDB') AS provenance, cf.primary_muscle, "
                    "cf.primary_action, COALESCE(cf.secondary_actions, '') "
                    f"FROM exercises e {display_name_join} "
                    "LEFT JOIN exercise_curated_fields cf ON cf.exercise_id = e.id "
                    "LEFT JOIN exercise_provenance p ON p.exercise_id = e.id "
                    f"WHERE e.id IN ({placeholders})",
                    batch,
                )
                for row in cursor.fetchall():
                    exercise_id = str(row[0])
                    entries[exercise_id] = {
                        "id": exercise_id,
                        "name": row[1],
                        "body_part": row[2],
                        "target_muscle": row[3],
                        "equipment": row[4],
                        "instructions": row[5],
                        "image_path": row[6],
                        "gif_path": row[7],
                        "provenance": row[8],
                        "primary_muscle": row[9],
                        "primary_action": row[10],
                        "secondary_actions": _split_secondary_actions(row[11]),
                    }
        return entries

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
                "COALESCE(p.provenance, 'ExerciseDB') AS provenance, cf.primary_muscle, "
                "cf.primary_action, COALESCE(cf.secondary_actions, '') "
                f"FROM exercises e {display_name_join} "
                "LEFT JOIN exercise_curated_fields cf ON cf.exercise_id = e.id "
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
            "primary_muscle": row[9],
            "primary_action": row[10],
            "secondary_actions": _split_secondary_actions(row[11]),
        }

    def is_exercise_library_exercise_visible(self, exercise_id: str) -> bool:
        """Whether an Exercise library id may be offered as a new candidate."""
        if not isinstance(exercise_id, str) or not exercise_id:
            return False
        visible_sql = exercise_library_visible_sql("e.id")
        with self._catalog_lock:
            row = self.catalog_conn.execute(
                f"SELECT 1 FROM exercises e WHERE e.id = ? AND {visible_sql}",
                (exercise_id,),
            ).fetchone()
        return row is not None

    def get_exercise_library_detail(self, exercise_id: str) -> dict[str, Any] | None:
        """One catalog exercise for the read-only exercise-detail view (#53).

        ``name`` uses the Exercise display name when present. ``category`` mirrors
        ``body_part`` in the source data, so the client sees the real value under both names.
        The curated ``primary_muscle`` is separate from source ``target_muscle``;
        secondary muscles come from ``exercise_secondary_muscles``. Instructions
        are the catalog's stored (English) text.
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
            "primary_muscle": entry.get("primary_muscle"),
            "primary_action": entry.get("primary_action"),
            "secondary_actions": entry.get("secondary_actions", []),
            "secondary_muscles": secondary,
            "instructions": entry.get("instructions"),
            "image_path": entry.get("image_path"),
            "gif_path": entry.get("gif_path"),
        }
        detail["provenance"] = entry["provenance"]
        return detail

    def find_unique_exercise_id_by_exact_name(self, query: str) -> str | None:
        """Return an exercise id only when an exact source, display, or alias name is unique."""
        clean = query.strip().lower()
        normalized = _normalize_exercise_name(clean)
        if not normalized:
            return None
        search = _NameSearch(
            query=clean,
            normalized_query=normalized,
            filter_clause="1 = 1",
            filter_params=(),
            equipment_clause=None,
            filter_browse=False,
            limit=None,
        )
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            rows = _exact_name_rows(cursor, search)
        exercise_ids = {str(row["id"]) for row in rows}
        return next(iter(exercise_ids)) if len(exercise_ids) == 1 else None

    def find_exercises_by_name(
        self,
        query: str,
        limit: int | None = 5,
        target_muscle: str | None = None,
        equipment_access: str | None = None,
        filter_browse: bool = False,
        *,
        filters: ExerciseFilters | None = None,
    ) -> list[dict[str, Any]]:
        """Ranked Exercise library matches across source names, display names, and aliases.

        Name tiers are exact → punctuation-insensitive → substring → token-AND.

        Each tier short-circuits: weaker-tier matches are only returned when every stronger
        tier came up empty. The substitution resolver uses this so an explicitly named
        exercise either resolves by name or refuses — it never falls through to semantic
        (embedding) ranking and installs a lexical sibling.

        ``target_muscle`` (#162) narrows results by the source column, while
        ``filters`` narrows by curated fields. Target and different curated filters
        combine with AND; multiple values in one curated filter combine with OR.
        A filter permits an empty query. ``equipment_access`` applies only to
        filter-only browse.
        """
        clean = query.strip().lower()
        muscle = (target_muscle or "").strip().lower()
        active_filters = filters if filters is not None else ExerciseFilters()
        has_filter = bool(muscle or active_filters.has_curated_filters)
        browse = filter_browse or (not clean and has_filter)
        if (limit is not None and limit <= 0) or (not clean and not has_filter):
            return []
        filter_clause, filter_params = _exercise_filter_predicate(
            active_filters, muscle
        )
        search = _NameSearch(
            query=clean,
            normalized_query=_normalize_exercise_name(clean),
            filter_clause=filter_clause,
            filter_params=filter_params,
            filter_browse=browse,
            equipment_clause=(
                equipment_access_sql(equipment_access)
                if equipment_access and browse
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


def _exercise_filter_predicate(
    filters: ExerciseFilters, target_muscle: str
) -> tuple[str, tuple[str, ...]]:
    clauses: list[str] = []
    params: list[str] = []
    if target_muscle:
        clauses.append("LOWER(e.target_muscle) = ?")
        params.append(target_muscle)
    if filters.primary_muscles:
        placeholders = ", ".join("?" for _ in filters.primary_muscles)
        clauses.append(f"cf.primary_muscle IN ({placeholders})")
        params.extend(filters.primary_muscles)
    if filters.primary_actions:
        placeholders = ", ".join("?" for _ in filters.primary_actions)
        clauses.append(f"cf.primary_action IN ({placeholders})")
        params.extend(filters.primary_actions)
    return " AND ".join(clauses) or "1 = 1", tuple(params)
