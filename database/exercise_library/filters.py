"""Filter values accepted by Exercise library search."""

from dataclasses import dataclass

from database.exercise_library.vocabulary import (
    EQUIPMENT_CATEGORIES,
    LOAD_TYPES,
    PRIMARY_ACTIONS,
    PRIMARY_MUSCLES,
)


@dataclass(frozen=True)
class ExerciseFilters:
    primary_muscles: tuple[str, ...] = ()
    primary_actions: tuple[str, ...] = ()
    load_types: tuple[str, ...] = ()
    equipment_categories: tuple[str, ...] = ()

    @property
    def has_curated_filters(self) -> bool:
        return bool(
            self.primary_muscles
            or self.primary_actions
            or self.load_types
            or self.equipment_categories
        )

    @property
    def excludes_coach_exercises(self) -> bool:
        return bool(self.primary_muscles or self.primary_actions or self.load_types)


def exercise_filters_for(
    primary_muscles: list[str] | None,
    primary_actions: list[str] | None = None,
    load_types: list[str] | None = None,
    equipment_categories: list[str] | None = None,
) -> ExerciseFilters:
    """Validate API filter labels and preserve their first-seen order."""
    muscles = tuple(dict.fromkeys(primary_muscles or ()))
    actions = tuple(dict.fromkeys(primary_actions or ()))
    loads = tuple(dict.fromkeys(load_types or ()))
    categories = tuple(dict.fromkeys(equipment_categories or ()))
    for muscle in muscles:
        if muscle not in PRIMARY_MUSCLES:
            raise ValueError(f"Invalid primary_muscle value: {muscle!r}.")
    for action in actions:
        if action not in PRIMARY_ACTIONS:
            raise ValueError(f"Invalid primary_action value: {action!r}.")
    for load_type in loads:
        if load_type not in LOAD_TYPES:
            raise ValueError(f"Invalid load_type value: {load_type!r}.")
    for category in categories:
        if category not in EQUIPMENT_CATEGORIES:
            raise ValueError(f"Invalid equipment_category value: {category!r}.")
    return ExerciseFilters(
        primary_muscles=muscles,
        primary_actions=actions,
        load_types=loads,
        equipment_categories=categories,
    )
