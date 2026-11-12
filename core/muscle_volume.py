"""Main-muscle attribution and per-exercise fractional set credits.

The defaults and group mapping follow ``docs/research/program-design.md``
Sections 3 and 5. Owner-directed mappings combine front and side delts under
shoulders while keeping rear delts distinct.
"""

from __future__ import annotations

from collections.abc import Iterable

MAIN_MUSCLE_GROUPS = (
    "chest",
    "back",
    "shoulders",
    "rear delts",
    "traps",
    "quads",
    "hamstrings",
    "glutes",
    "biceps",
    "triceps",
    "calves",
    "core",
)

MAIN_MUSCLE_LABELS = {
    "chest": "Chest",
    "back": "Back",
    "shoulders": "Shoulders",
    "rear delts": "Rear Delts",
    "traps": "Traps",
    "quads": "Quads",
    "hamstrings": "Hamstrings",
    "glutes": "Glutes",
    "biceps": "Biceps",
    "triceps": "Triceps",
    "calves": "Calves",
    "core": "Core",
}

_MUSCLE_ALIASES = {
    "chest": "chest",
    "upper chest": "chest",
    "pectorals": "chest",
    "pectoral": "chest",
    "pecs": "chest",
    "pectoral muscles": "chest",
    "back": "back",
    "lats": "back",
    "latissimus dorsi": "back",
    "lat": "back",
    "upper back": "back",
    "mid back": "back",
    "rhomboids": "back",
    "rhomboid": "back",
    "shoulders": "shoulders",
    "shoulder": "shoulders",
    "delts": "shoulders",
    "deltoids": "shoulders",
    "front delts": "shoulders",
    "front delt": "shoulders",
    "anterior delts": "shoulders",
    "side delts": "shoulders",
    "side delt": "shoulders",
    "lateral delts": "shoulders",
    "lateral delt": "shoulders",
    "rear delts": "rear delts",
    "rear delt": "rear delts",
    "posterior delts": "rear delts",
    "posterior delt": "rear delts",
    "traps": "traps",
    "trap": "traps",
    "trapezius": "traps",
    "trapezius muscles": "traps",
    "upper traps": "traps",
    "upper trap": "traps",
    "quads": "quads",
    "quadriceps": "quads",
    "hamstrings": "hamstrings",
    "hamstring": "hamstrings",
    "glutes": "glutes",
    "glute": "glutes",
    "biceps": "biceps",
    "bicep": "biceps",
    "brachialis": "biceps",
    "triceps": "triceps",
    "tricep": "triceps",
    "calves": "calves",
    "calf": "calves",
    "gastrocnemius": "calves",
    "soleus": "calves",
    "core": "core",
    "abs": "core",
    "abdominals": "core",
    "abdominal": "core",
    "rectus abdominis": "core",
    "transverse abdominis": "core",
    "obliques": "core",
    "external obliques": "core",
    "internal obliques": "core",
    "waist": "core",
}

FOCUS_MAIN_GROUPS = {
    "chest": "chest",
    "upper_chest": "chest",
    "back": "back",
    "shoulders": "shoulders",
    "side_delts": "shoulders",
    "rear_delts": "rear delts",
    "traps": "traps",
    "biceps": "biceps",
    "triceps": "triceps",
    "forearms": None,
    "quads": "quads",
    "hamstrings": "hamstrings",
    "glutes": "glutes",
    "adductors": None,
    "calves": "calves",
    "abs": "core",
}


def normalize_main_muscle(muscle: object) -> str | None:
    """Map a curated/source muscle label to one main group, if supported."""
    normalized = " ".join(str(muscle or "").strip().casefold().replace("_", " ").split())
    return _MUSCLE_ALIASES.get(normalized)


def main_group_for_focus(focus_muscle: object) -> str | None:
    """Map an existing Weak point key to the one main group it affects."""
    return FOCUS_MAIN_GROUPS.get(str(focus_muscle or "").strip().casefold())


def default_muscle_credits(
    primary_muscle: object,
    helper_muscles: Iterable[object] = (),
) -> dict[str, float]:
    """Return direct=1 and distinct helper=0.5 credits for a catalog row."""
    primary_group = normalize_main_muscle(primary_muscle)
    credits: dict[str, float] = {}
    if primary_group:
        credits[primary_group] = 1.0
    for helper in helper_muscles:
        group = normalize_main_muscle(helper)
        if group and group not in credits:
            credits[group] = 0.5
    return credits


