"""MAYOS display names and aliases for rows in the Exercise library."""

import sqlite3
from typing import TypedDict

from database.exercise_library import authored
from database.shared import _normalize_exercise_name


EXERCISE_NEAR_MISSES: dict[str, frozenset[str]] = {
    "pendulum squat": frozenset({"744"}),
    "kelso shrug": frozenset({"329"}),
    "bayesian curl": frozenset({"190"}),
}


def near_miss_exercise_ids(query: str) -> frozenset[str]:
    return EXERCISE_NEAR_MISSES.get(_normalize_exercise_name(query), frozenset())


def apply_curated_exercise_names(cursor: sqlite3.Cursor) -> None:
    name_rows = [
        (exercise_id, name_data["display_name"], name_data["aliases"])
        for exercise_id, name_data in EXERCISE_NAMES.items()
    ]
    name_rows.extend(
        (exercise["id"], exercise["display_name"], exercise["aliases"])
        for exercise in authored.MAYOS_AUTHORED_EXERCISES
    )
    for exercise_id, display_name, aliases in name_rows:
        if cursor.execute("SELECT 1 FROM exercises WHERE id = ?", (exercise_id,)).fetchone() is None:
            continue
        cursor.execute(
            "INSERT INTO exercise_display_names (exercise_id, display_name) VALUES (?, ?) "
            "ON CONFLICT(exercise_id) DO UPDATE SET display_name = excluded.display_name",
            (exercise_id, display_name),
        )
        cursor.execute("DELETE FROM exercise_aliases WHERE exercise_id = ?", (exercise_id,))
        cursor.executemany(
            "INSERT INTO exercise_aliases (exercise_id, alias, normalized_alias) VALUES (?, ?, ?)",
            [
                (exercise_id, alias, _normalize_exercise_name(alias))
                for alias in aliases
            ],
        )


class ExerciseNameMetadata(TypedDict):
    display_name: str
    aliases: tuple[str, ...]


EXERCISE_NAMES: dict[str, ExerciseNameMetadata] = {
    "2330": {
        "display_name": "Wide-Grip Lat Pulldown",
        "aliases": (
            "frontal lat pulldown",
            "lat pull-down",
            "lat pulldown",
            "wide grip pulldown",
        ),
    },
    "150": {
        "display_name": "Lat Pulldown",
        "aliases": (
            "frontal lat pulldown",
            "lat pull-down",
            "lat pulldown",
            "wide grip pulldown",
        ),
    },
    "596": {
        "display_name": "Pec Deck",
        "aliases": ("pec deck", "pec deck machine", "machine chest fly"),
    },
    "602": {
        "display_name": "Reverse Pec Deck",
        "aliases": ("reverse pec deck", "reverse fly machine", "rear delt machine fly"),
    },
    "3562": {
        "display_name": "Barbell Hip Thrust",
        "aliases": ("barbell hip thrust", "hip thrust barbell"),
    },
    "757": {
        "display_name": "Smith Incline Press",
        "aliases": ("smith incline press", "smith machine incline press"),
    },
    "175": {
        "display_name": "Cable Crunch",
        "aliases": ("cable crunch", "kneeling cable crunch"),
    },
    "3541": {
        "display_name": "Incline DB Y-Raise",
        "aliases": ("incline db y raise", "incline dumbbell y raise"),
    },
    "318": {
        "display_name": "Incline DB Curl",
        "aliases": ("incline db curl", "incline dumbbell curl"),
    },
    "598": {
        "display_name": "Hip Adduction",
        "aliases": ("hip adduction", "seated hip adduction", "adductor machine"),
    },
}
