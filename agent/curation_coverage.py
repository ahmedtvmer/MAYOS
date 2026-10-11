"""Coverage of movement-slot signatures in the curated Exercise library."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import sqlite3

from agent.program_blueprints import SLOT_SPECS, SLOT_STAPLES, SlotSpec
from database.exercise_library.schema import exercise_library_visible_sql
from utils.equipment_access import EQUIPMENT_ACCESS_VALUES, equipment_access_allows


@dataclass(frozen=True)
class CurationCoverage:
    slot: str
    equipment_access: str
    primary_actions: tuple[str, ...]
    primary_muscles: tuple[str, ...]
    staple_count: int
    curated_signature_count: int
    candidate_count: int


def read_curation_coverage_rows(
    connection: sqlite3.Connection,
) -> list[dict[str, object]]:
    cursor = connection.execute(
        "SELECT e.id, e.equipment, COALESCE(cf.primary_action, '') AS primary_action, "
        "COALESCE(cf.primary_muscle, '') AS primary_muscle "
        "FROM exercises e LEFT JOIN exercise_curated_fields cf ON cf.exercise_id = e.id "
        f"WHERE {exercise_library_visible_sql()} "
        "ORDER BY e.id"
    )
    column_names = [column[0] for column in cursor.description]
    return [dict(zip(column_names, row, strict=True)) for row in cursor.fetchall()]


def build_curation_coverage_report(
    exercise_rows: Iterable[Mapping[str, object]],
) -> tuple[CurationCoverage, ...]:
    """Count Staples and signature matches from rows already filtered for visibility."""
    exercises_by_id = {str(row["id"]): row for row in exercise_rows}
    allowed_by_access = {
        access: _allowed_exercises(exercises_by_id, access)
        for access in EQUIPMENT_ACCESS_VALUES
    }
    return tuple(
        _slot_coverage(slot_key, spec, allowed_by_access[access], access)
        for slot_key, spec in SLOT_SPECS.items()
        for access in EQUIPMENT_ACCESS_VALUES
    )


def _slot_coverage(
    slot_key: str,
    spec: SlotSpec,
    allowed: dict[str, Mapping[str, object]],
    equipment_access: str,
) -> CurationCoverage:
    staple_ids = set(SLOT_STAPLES[slot_key]) & allowed.keys()
    signature_ids = _matching_signature_ids(allowed, spec)
    return CurationCoverage(
        slot=slot_key,
        equipment_access=equipment_access,
        primary_actions=spec.primary_actions,
        primary_muscles=spec.primary_muscles,
        staple_count=len(staple_ids),
        curated_signature_count=len(signature_ids),
        candidate_count=len(staple_ids | signature_ids),
    )


def _allowed_exercises(
    exercises_by_id: dict[str, Mapping[str, object]], equipment_access: str
) -> dict[str, Mapping[str, object]]:
    return {
        exercise_id: row
        for exercise_id, row in exercises_by_id.items()
        if equipment_access_allows(equipment_access, row["equipment"])
    }


def _matching_signature_ids(
    allowed: dict[str, Mapping[str, object]], spec: SlotSpec
) -> set[str]:
    return {
        exercise_id
        for exercise_id, row in allowed.items()
        if row["primary_action"] in spec.primary_actions
        and row["primary_muscle"] in spec.primary_muscles
    }
