"""Exercise name matching behavior that stays outside the curation data."""

from database.shared import _normalize_exercise_name


EXERCISE_NEAR_MISSES: dict[str, frozenset[str]] = {
    "pendulum squat": frozenset({"744"}),
    "kelso shrug": frozenset({"329"}),
    "bayesian curl": frozenset({"190"}),
}


def near_miss_exercise_ids(query: str) -> frozenset[str]:
    return EXERCISE_NEAR_MISSES.get(_normalize_exercise_name(query), frozenset())
