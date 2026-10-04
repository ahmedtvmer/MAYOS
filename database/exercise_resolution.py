"""Shared resolution rules for Exercise library and Coach exercise rows."""

from typing import Any


EXERCISE_DISPLAY_JOIN = """
LEFT JOIN exercises e ON e.id = {exercise_id}
LEFT JOIN catalog.coach_exercises ce ON ce.id = {exercise_id}
"""
EXERCISE_DISPLAY_EQUIPMENT_SQL = "COALESCE(e.equipment, ce.equipment)"
EXERCISE_DISPLAY_BODY_PART_SQL = "COALESCE(e.body_part, ce.body_part)"
EXERCISE_DISPLAY_TARGET_MUSCLE_SQL = "COALESCE(e.target_muscle, ce.body_part)"


def exercise_display_join(exercise_id_expression: str) -> str:
    """Join a ledger exercise id to its library row or Coach exercise row."""
    return EXERCISE_DISPLAY_JOIN.format(exercise_id=exercise_id_expression)


def exercise_display_name_sql(
    exercise_id_expression: str, fallback_expression: str | None = None
) -> str:
    """SQL expression for the resolved exercise name, falling back to its id."""
    values = ["e.name", "ce.name", fallback_expression or exercise_id_expression]
    return f"COALESCE({', '.join(values)})"


def resolve_exercise_display_row(
    db: Any,
    exercise_id: str,
    *,
    library_entries: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Resolve an id to its shared-library row, then its Coach-owned row."""
    exercise_id = str(exercise_id)
    library_entry = (
        library_entries.get(exercise_id)
        if library_entries is not None
        else db.get_exercise_library_entry(exercise_id)
    )
    return library_entry or db.get_coach_exercise_unscoped(exercise_id)
