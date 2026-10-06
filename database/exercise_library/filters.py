"""Filter values accepted by Exercise library search."""

from dataclasses import dataclass

from database.exercise_library.vocabulary import PRIMARY_ACTIONS, PRIMARY_MUSCLES


@dataclass(frozen=True)
class ExerciseFilters:
    primary_muscles: tuple[str, ...] = ()
    primary_actions: tuple[str, ...] = ()

    @property
    def has_curated_filters(self) -> bool:
        return bool(self.primary_muscles or self.primary_actions)


def exercise_filters_for(
    primary_muscles: list[str] | None,
    primary_actions: list[str] | None = None,
) -> ExerciseFilters:
    """Validate API filter labels and preserve their first-seen order."""
    muscles = tuple(dict.fromkeys(primary_muscles or ()))
    for muscle in muscles:
        if muscle not in PRIMARY_MUSCLES:
            raise ValueError(f"Invalid primary_muscle value: {muscle!r}.")
    actions = tuple(dict.fromkeys(primary_actions or ()))
    for action in actions:
        if action not in PRIMARY_ACTIONS:
            raise ValueError(f"Invalid primary_action value: {action!r}.")
    return ExerciseFilters(primary_muscles=muscles, primary_actions=actions)
