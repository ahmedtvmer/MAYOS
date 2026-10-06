"""Filter values accepted by Exercise library search."""

from dataclasses import dataclass

from database.exercise_library.vocabulary import PRIMARY_MUSCLES


@dataclass(frozen=True)
class ExerciseFilters:
    primary_muscles: tuple[str, ...] = ()

    @property
    def has_curated_filters(self) -> bool:
        return bool(self.primary_muscles)


def exercise_filters_for(primary_muscles: list[str] | None) -> ExerciseFilters:
    """Validate API filter labels and preserve their first-seen order."""
    muscles = tuple(dict.fromkeys(primary_muscles or ()))
    for muscle in muscles:
        if muscle not in PRIMARY_MUSCLES:
            raise ValueError(f"Invalid primary_muscle value: {muscle!r}.")
    return ExerciseFilters(primary_muscles=muscles)
