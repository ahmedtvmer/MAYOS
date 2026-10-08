"""Read-time display labels resolved from the Exercise library."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from database.registry.coach_exercises import is_coach_exercise_id


@dataclass(frozen=True)
class ExerciseLabels:
    image_path: str | None = None
    primary_muscle: str | None = None
    primary_action: str | None = None
    equipment_category: str | None = None
    load_type: str | None = None
    coach_equipment: str | None = None


def exercise_labels(db: Any, exercise_ids: Iterable[str]) -> dict[str, ExerciseLabels]:
    ids = list(dict.fromkeys(exercise_id for exercise_id in exercise_ids if exercise_id))
    coach_ids = [
        exercise_id for exercise_id in ids if is_coach_exercise_id(exercise_id)
    ]
    library_ids = [
        exercise_id
        for exercise_id in ids
        if not is_coach_exercise_id(exercise_id)
    ]
    library_entries = db.get_exercise_library_entries(library_ids)
    coach_entries = db.get_coach_exercises_unscoped(coach_ids)
    labels = {exercise_id: _library_labels(entry) for exercise_id, entry in library_entries.items()}
    labels.update(
        {
            exercise_id: _coach_labels(entry)
            for exercise_id, entry in coach_entries.items()
        }
    )
    return labels


def _library_labels(entry: dict[str, Any]) -> ExerciseLabels:
    return ExerciseLabels(
        image_path=entry.get("image_path"),
        primary_muscle=entry.get("primary_muscle"),
        primary_action=entry.get("primary_action"),
        equipment_category=entry.get("equipment_category"),
        load_type=entry.get("load_type"),
    )


def _coach_labels(entry: dict[str, Any]) -> ExerciseLabels:
    return ExerciseLabels(
        primary_muscle=entry.get("body_part"),
        coach_equipment=entry.get("equipment"),
    )
