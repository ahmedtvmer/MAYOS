"""Shared ExerciseDB catalog columns and SQL fragments."""

EXERCISE_COLUMNS = (
    "id",
    "name",
    "body_part",
    "target_muscle",
    "equipment",
    "image_path",
    "gif_path",
    "instructions",
)

EFFECTIVE_EXERCISE_NAME_SQL = "COALESCE(d.display_name, e.name)"


def effective_exercise_name_sql(schema: str | None = None) -> tuple[str, str]:
    """Return the effective-name expression and its display-name join."""
    display_names = f"{schema}.exercise_display_names" if schema else "exercise_display_names"
    return (
        EFFECTIVE_EXERCISE_NAME_SQL,
        f"LEFT JOIN {display_names} d ON d.exercise_id = e.id",
    )
