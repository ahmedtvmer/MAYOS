"""Main-muscle attribution and per-exercise fractional set credits.

The defaults and group mapping follow ``docs/research/program-design.md``
Sections 3 and 5. Owner-directed mappings combine front and side delts under
shoulders while keeping rear delts distinct. Lats and traps are separate
groups; a generic source label of "back" is ambiguous and remains uncounted.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

MAIN_MUSCLE_GROUPS = (
    "chest",
    "lats",
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
    "lats": "Lats",
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
    "lats": "lats",
    "latissimus dorsi": "lats",
    "lat": "lats",
    "upper back": "traps",
    "mid back": "traps",
    "middle back": "traps",
    "rhomboids": "traps",
    "rhomboid": "traps",
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
    "upper trapezius": "traps",
    "upper trapezius muscle": "traps",
    "upper traps": "traps",
    "upper trap": "traps",
    "mid traps": "traps",
    "middle traps": "traps",
    "mid trap": "traps",
    "middle trap": "traps",
    "mid trapezius": "traps",
    "middle trapezius": "traps",
    "lower traps": "traps",
    "lower trap": "traps",
    "lower trapezius": "traps",
    "lower trapezius muscle": "traps",
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
    "lats": "lats",
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
    normalized = " ".join(
        str(muscle or "").strip().casefold().replace("_", " ").replace("-", " ").split()
    )
    return _MUSCLE_ALIASES.get(normalized)


def main_group_for_focus(focus_muscle: object) -> str | None:
    """Map an existing Weak point key to the one main group it affects."""
    key = str(focus_muscle or "").strip().casefold()
    # Old profile values migrate to lats; keep the fallback for restored snapshots.
    if key == "back":
        return "lats"
    return FOCUS_MAIN_GROUPS.get(key)


def default_muscle_credits(
    primary_muscle: object,
    helper_muscles: Iterable[object] = (),
    *,
    exercise_name: object = None,
) -> dict[str, float]:
    """Return direct=1 and helper=0.5 credits, with row-specific attribution."""
    primary_group = normalize_main_muscle(primary_muscle)
    exercise_label = str(exercise_name or "").casefold()
    is_labeled_row = bool(
        re.search(r"\brow\b", exercise_label)
        and not re.search(r"\bupright\s+row\b", exercise_label)
    )
    if is_labeled_row and primary_group in {"lats", "traps"}:
        # The owner-directed row policy treats upper-back pulling as traps-led.
        credits: dict[str, float] = {
            "traps": 1.0, "lats": 0.5, "rear delts": 0.5, "biceps": 0.5,
        }
    else:
        credits = {primary_group: 1.0} if primary_group else {}
    for helper_muscle in helper_muscles:
        group = normalize_main_muscle(helper_muscle)
        if group and group not in credits:
            credits[group] = 0.5
    return credits


