"""Exercise library lookup with display names and aliases (ADR 053, #225)."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable, Literal
from database.shared import _normalize_exercise_name
from database.exercise_library.filters import ExerciseFilters
from database.exercise_library.values import split_curation_values
from database.exercise_library.names import near_miss_exercise_ids
from database.exercise_library.ranking import replacement_rank_sql
from database.exercise_library.schema import (
    effective_exercise_name_sql,
    exercise_library_visible_sql,
)
from database.exercise_library.vocabulary import equipment_category_for, equipment_category_sql
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
    replacing_exercise_id: str | None = None


@dataclass(frozen=True)
class _NameRowsOptions:
    limit: int | None
    ranking: Literal["name_length", "display_name_first"] = "name_length"
    replacing_exercise_id: str | None = None
    include_aliases: bool = False


@dataclass(frozen=True)
class _NameCandidate:
    normalized: str
    compact: str
    words: tuple[str, ...]
    compact_grams: frozenset[str]
    word_grams: tuple[frozenset[str], ...]


@dataclass(frozen=True)
class _NameQuery:
    compact: str
    words: tuple[str, ...]
    compact_grams: frozenset[str]
    word_grams: tuple[frozenset[str], ...]


@dataclass(frozen=True)
class _PreparedNameRow:
    row: dict[str, Any]
    candidates: tuple[_NameCandidate, ...]
    forms: frozenset[str]
    exact_names: frozenset[str]
    normalized_aliases: frozenset[str]


def _exercise_name_rows(
    cursor,
    where_sql: str,
    params: list[str],
    options: _NameRowsOptions,
):
    name_expression, display_name_join = effective_exercise_name_sql()
    if options.ranking == "display_name_first":
        display_name_order = (
            "CASE WHEN COALESCE(d.is_reviewed, 0) = 1 THEN 0 ELSE 1 END, "
            f"LOWER({name_expression}), e.id"
        )
        order_by = display_name_order
        if options.replacing_exercise_id:
            order_by = f"{replacement_rank_sql()}, {display_name_order}"
    else:
        order_by = "LENGTH(e.name)"
    aliases_expression = (
        "(SELECT GROUP_CONCAT(a.alias, char(31)) FROM exercise_aliases a "
        "WHERE a.exercise_id = e.id) AS aliases"
        if options.include_aliases
        else "NULL AS aliases"
    )
    replacement_join = ""
    if options.replacing_exercise_id:
        replacement_join = (
            "LEFT JOIN exercise_curated_fields replacement_cf "
            "ON replacement_cf.exercise_id = ?"
        )
        params = [options.replacing_exercise_id, *params]
    where_sql = f"({where_sql}) AND ({exercise_library_visible_sql('e.id')})"
    query = """
        SELECT e.id AS id, {name_expression} AS display_name, e.body_part AS body_part,
               e.target_muscle AS target_muscle, e.equipment AS equipment,
               e.image_path AS image_path, e.name AS source_name,
               {aliases_expression},
               cf.primary_muscle AS primary_muscle,
               cf.primary_action AS primary_action,
               COALESCE(cf.secondary_actions, '') AS secondary_actions,
               cf.load_type AS load_type
        FROM exercises e
        {display_name_join}
        LEFT JOIN exercise_curated_fields cf ON cf.exercise_id = e.id
        {replacement_join}
        WHERE {where_sql}
        ORDER BY {order_by}
    """.format(
        name_expression=name_expression,
        display_name_join=display_name_join,
        replacement_join=replacement_join,
        where_sql=where_sql,
        order_by=order_by,
        aliases_expression=aliases_expression,
    )
    if options.limit is not None:
        query += " LIMIT ?"
        params = [*params, options.limit]
    cursor.execute(query, params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _name_match_result(row):
    result = {
        "id": str(row["id"]),
        "name": row["display_name"],
        "source_name": row["source_name"],
        "body_part": row["body_part"],
        "target_muscle": row["target_muscle"],
        "equipment": row["equipment"],
        "equipment_category": equipment_category_for(row["equipment"]),
        "load_type": row["load_type"],
        "image_path": row["image_path"],
        "primary_muscle": row["primary_muscle"],
        "primary_action": row["primary_action"],
        "secondary_actions": list(split_curation_values(row["secondary_actions"])),
    }
    from agent.movement_signatures import infer_candidate_slots

    slots = infer_candidate_slots(result)
    if len(slots) == 1:
        result["slot_key"] = next(iter(slots))
    return result


def _name_match_results(rows):
    return [_name_match_result(row) for row in rows]


def _normalized_name_forms(normalized: str) -> set[str]:
    forms = {normalized, normalized.replace(" ", "")}
    if normalized in {"pulldown", "pull down"}:
        forms.update(("lat pulldown", "latpulldown"))
    return {form for form in forms if form}


def _character_trigrams(text: str) -> frozenset[str]:
    return frozenset(text[index : index + 3] for index in range(len(text) - 2))


def _prepare_name_candidate(name: str) -> _NameCandidate:
    normalized = _normalize_exercise_name(name)
    compact = normalized.replace(" ", "")
    words = tuple(normalized.split())
    return _NameCandidate(
        normalized=normalized,
        compact=compact,
        words=words,
        compact_grams=_character_trigrams(compact),
        word_grams=tuple(_character_trigrams(word) for word in words),
    )


def _prepare_name_rows(rows: list[dict[str, Any]]) -> list[_PreparedNameRow]:
    prepared = []
    for row in rows:
        aliases = (row.get("aliases") or "").split("\x1f")
        display_source_candidates = tuple(
            _prepare_name_candidate(str(name))
            for name in (row.get("display_name"), row.get("source_name"))
            if name
        )
        alias_candidates = tuple(
            _prepare_name_candidate(alias) for alias in aliases if alias
        )
        candidates = tuple(dict.fromkeys((*display_source_candidates, *alias_candidates)))
        forms = frozenset().union(*(
            _normalized_name_forms(candidate.normalized) for candidate in candidates
        )) if candidates else frozenset()
        prepared.append(
            _PreparedNameRow(
                row=row,
                candidates=candidates,
                forms=forms,
                exact_names=frozenset(
                    str(name).lower()
                    for name in (row.get("display_name"), row.get("source_name"))
                    if name
                ),
                normalized_aliases=frozenset(
                    candidate.normalized for candidate in alias_candidates
                ),
            )
        )
    return prepared


def _exact_name_rows(rows: list[_PreparedNameRow], search: _NameSearch):
    matches = [
        candidate.row
        for candidate in rows
        if search.query in candidate.exact_names
        or search.normalized_query in candidate.normalized_aliases
    ]
    matches.sort(key=lambda row: len(row["source_name"] or ""))
    return matches[:search.limit]


def _normalized_name_rows(rows: list[_PreparedNameRow], search: _NameSearch):
    query_forms = _normalized_name_forms(search.normalized_query)
    matches = [candidate.row for candidate in rows if query_forms & candidate.forms]
    matches.sort(key=lambda row: len(row["source_name"] or ""))
    return matches[:search.limit]


def _substring_name_rows(rows: list[_PreparedNameRow], search: _NameSearch):
    query_forms = tuple(
        form for form in _normalized_name_forms(search.normalized_query) if len(form) > 1
    )
    if not query_forms:
        return []
    matches = [
        candidate.row
        for candidate in rows
        if any(
            query_form in name.normalized or query_form in name.compact
            for name in candidate.candidates
            for query_form in query_forms
        )
    ]
    matches.sort(key=lambda row: len(row["source_name"] or ""))
    return matches[:search.limit]


def _token_name_rows(rows: list[_PreparedNameRow], search: _NameSearch):
    query_tokens = tuple(search.normalized_query.split())
    if not query_tokens:
        return []
    required_tokens = set(query_tokens)
    matches = [
        candidate.row
        for candidate in rows
        if any(required_tokens.issubset(name.words) for name in candidate.candidates)
    ]
    matches.sort(key=lambda row: len(row["source_name"] or ""))
    return matches[:search.limit]


def _passes_fuzzy_prefilter(
    query: str, query_grams: frozenset[str], candidate: str, candidate_grams: frozenset[str]
) -> bool:
    if not query or not candidate:
        return False
    if abs(len(query) - len(candidate)) > max(2, max(len(query), len(candidate)) // 3):
        return False
    if min(len(query), len(candidate)) < 4:
        return query == candidate
    return bool(query_grams & candidate_grams)


def _fuzzy_name_score(query: _NameQuery, candidate: _NameCandidate) -> float:
    scores = []
    if _passes_fuzzy_prefilter(
        query.compact, query.compact_grams, candidate.compact, candidate.compact_grams
    ):
        scores.append(SequenceMatcher(None, query.compact, candidate.compact).ratio())
    token_scores = []
    for word, word_grams in zip(query.words, query.word_grams, strict=True):
        possible_scores = [
            SequenceMatcher(None, word, candidate_word).ratio()
            for candidate_word, candidate_grams in zip(
                candidate.words, candidate.word_grams, strict=True
            )
            if _passes_fuzzy_prefilter(word, word_grams, candidate_word, candidate_grams)
        ]
        if possible_scores:
            token_scores.append(max(possible_scores))
    if len(token_scores) == len(query.words):
        scores.append(sum(token_scores) / len(token_scores))
    return max(scores, default=0.0)


def _prepare_name_query(search: _NameSearch) -> _NameQuery:
    words = tuple(search.normalized_query.split())
    compact = search.normalized_query.replace(" ", "")
    return _NameQuery(
        compact=compact,
        words=words,
        compact_grams=_character_trigrams(compact),
        word_grams=tuple(_character_trigrams(word) for word in words),
    )


def _score_fuzzy_name_rows(rows: list[_PreparedNameRow], search: _NameSearch):
    query = _prepare_name_query(search)
    if len(query.compact) < 3:
        return []
    scored = []
    for candidate in rows:
        score = max(
            (
                _fuzzy_name_score(query, name)
                for name in candidate.candidates
            ),
            default=0.0,
        )
        if score >= 0.72:
            scored.append((score, candidate.row))
    return scored


def _fuzzy_name_rows(rows: list[_PreparedNameRow], search: _NameSearch):
    scored = _score_fuzzy_name_rows(rows, search)
    if not scored:
        return []
    scored.sort(key=lambda candidate: (-candidate[0], str(candidate[1]["display_name"])))
    best_score = scored[0][0]
    matches = [row for score, row in scored if score >= max(0.72, best_score - 0.08)]
    return matches[:search.limit]


def _find_name_rows(rows: list[_PreparedNameRow], search: _NameSearch):
    for search_tier in (
        _exact_name_rows,
        _normalized_name_rows,
        _substring_name_rows,
        _token_name_rows,
        _fuzzy_name_rows,
    ):
        matches = search_tier(rows, search)
        if matches:
            return matches
    return []


class ExerciseLookupMixin:
    def get_exercise_name_vocabulary(self) -> list[tuple[str, str]]:
        """Visible library source/display names and aliases for deterministic mentions."""
        name_expression, display_join = effective_exercise_name_sql()
        with self._catalog_lock:
            rows = self.catalog_conn.execute(
                f"SELECT e.id, e.name, {name_expression} AS display_name "
                f"FROM exercises e {display_join} "
                f"WHERE {exercise_library_visible_sql('e.id')}"
            ).fetchall()
            aliases = self.catalog_conn.execute(
                "SELECT a.exercise_id, a.alias FROM exercise_aliases a "
                f"WHERE {exercise_library_visible_sql('a.exercise_id')}"
            ).fetchall()
        return [
            (str(row[0]), name) for row in rows for name in (row[1], row[2]) if name
        ] + [(str(row[0]), row[1]) for row in aliases if row[1]]

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
                    "cf.primary_action, COALESCE(cf.secondary_actions, ''), cf.load_type "
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
                        "equipment_category": equipment_category_for(row[4]),
                        "instructions": row[5],
                        "image_path": row[6],
                        "gif_path": row[7],
                        "provenance": row[8],
                        "primary_muscle": row[9],
                        "primary_action": row[10],
                        "secondary_actions": list(split_curation_values(row[11])),
                        "load_type": row[12],
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
                "cf.primary_action, COALESCE(cf.secondary_actions, ''), cf.load_type, e.name "
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
            "equipment_category": equipment_category_for(row[4]),
            "instructions": row[5],
            "image_path": row[6],
            "gif_path": row[7],
            "provenance": row[8],
            "primary_muscle": row[9],
            "primary_action": row[10],
            "secondary_actions": list(split_curation_values(row[11])),
            "load_type": row[12],
            "source_name": row[13],
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
            "equipment_category": entry["equipment_category"],
            "load_type": entry.get("load_type"),
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
        """Return an id only when its normalized source, display, or alias is unique."""
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
            rows = _exercise_name_rows(
                cursor,
                "1 = 1",
                [],
                _NameRowsOptions(limit=None, include_aliases=True),
            )
        rows = _normalized_name_rows(_prepare_name_rows(rows), search)
        rejected_ids = near_miss_exercise_ids(clean)
        exercise_ids = {
            str(row["id"]) for row in rows if str(row["id"]) not in rejected_ids
        }
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
        replacing_exercise_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Rank source names, display names, and aliases by name-match strength.

        Name tiers are exact, normalized, substring, token-AND, then fuzzy. Normalization
        folds common plurals and spacing, aliases include gym nicknames, and typo matches
        stay behind every stronger tier.

        Each tier short-circuits: weaker-tier matches are only returned when every stronger
        tier came up empty. The substitution resolver uses this so an explicitly named
        exercise either resolves by name or refuses — it never falls through to semantic
        (embedding) ranking and installs a lexical sibling.

        ``target_muscle`` (#162) narrows results by the source column, while
        ``filters`` narrows by curated fields. Target and distinct filter sections
        combine with AND; multiple values in one section combine with OR. A filter
        permits an empty query. ``equipment_access`` applies only to filter-only browse.
        An explicit replacement ranking can also browse the full library with an
        empty query. ``replacing_exercise_id`` ranks candidates by matching Primary
        action and Primary muscle before the usual display-name order. An
        uncurated, Coach, or unknown id keeps today's order.
        """
        clean = query.strip().lower()
        muscle = (target_muscle or "").strip().lower()
        active_filters = filters if filters is not None else ExerciseFilters()
        has_filter = bool(muscle or active_filters.has_curated_filters)
        has_replacement_reference = bool(replacing_exercise_id)
        browse = filter_browse or (
            not clean and (has_filter or has_replacement_reference)
        )
        if (limit is not None and limit <= 0) or (
            not clean and not has_filter and not has_replacement_reference and not filter_browse
        ):
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
            equipment_clause=equipment_access_sql(equipment_access) if equipment_access else None,
            limit=limit,
            replacing_exercise_id=(replacing_exercise_id or None),
        )
        with self._catalog_lock:
            cursor = self.catalog_conn.cursor()
            if search.filter_browse:
                where = search.filter_clause
                if search.equipment_clause:
                    where += f" AND ({search.equipment_clause})"
                rows = _exercise_name_rows(
                    cursor,
                    where,
                    list(search.filter_params),
                    _NameRowsOptions(
                        limit=search.limit,
                        ranking="display_name_first",
                        replacing_exercise_id=search.replacing_exercise_id,
                    ),
                )
            else:
                if not search.normalized_query:
                    return []
                where = search.filter_clause
                if search.equipment_clause:
                    where += f" AND ({search.equipment_clause})"
                rows = _exercise_name_rows(
                    cursor,
                    where,
                    list(search.filter_params),
                    _NameRowsOptions(limit=None, include_aliases=True),
                )
        if not search.filter_browse:
            rows = _find_name_rows(_prepare_name_rows(rows), search)
        rejected_ids = near_miss_exercise_ids(clean)
        return _name_match_results(
            [row for row in rows if str(row["id"]) not in rejected_ids]
        )

    def find_exercise_by_name(self, query: str) -> dict[str, Any] | None:
        """Return a name match only when the lookup has one clear candidate."""
        matches = self.find_exercises_by_name(query, limit=3)
        return matches[0] if len(matches) == 1 else None


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
    if filters.load_types:
        placeholders = ", ".join("?" for _ in filters.load_types)
        clauses.append(f"cf.load_type IN ({placeholders})")
        params.extend(filters.load_types)
    if filters.equipment_categories:
        placeholders = ", ".join("?" for _ in filters.equipment_categories)
        category_sql = equipment_category_sql("e.equipment")
        clauses.append(f"({category_sql}) IN ({placeholders})")
        params.extend(filters.equipment_categories)
    return " AND ".join(clauses) or "1 = 1", tuple(params)
