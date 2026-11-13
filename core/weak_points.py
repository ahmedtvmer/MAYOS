"""Shared Weak point vocabulary and validation."""

from typing import Any

WEAK_POINT_MUSCLES = (
    "chest", "upper_chest", "lats", "shoulders", "side_delts", "traps", "biceps",
    "triceps", "forearms", "quads", "hamstrings", "glutes", "adductors",
    "calves", "abs",
)
WEAK_POINT_SOURCES = ("named", "default", "migrated")


def validate_weak_points(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 2:
        raise ValueError("Weak points must be a list of at most two entries.")
    validated_entries = []
    seen_muscles = set()
    for weak_point in value:
        if not isinstance(weak_point, dict):
            raise ValueError("Weak point muscle is unknown.")
        muscle = "lats" if weak_point.get("muscle") == "back" else weak_point.get("muscle")
        if muscle not in WEAK_POINT_MUSCLES:
            raise ValueError("Weak point muscle is unknown.")
        source = weak_point.get("source", "named")
        if (
            muscle in seen_muscles
            or source not in WEAK_POINT_SOURCES
            or (source in ("default", "migrated") and muscle != "glutes")
        ):
            raise ValueError("Weak points must be unique and have a valid source.")
        seen_muscles.add(muscle)
        validated_entries.append({"muscle": muscle, "source": source})
    if len(validated_entries) > 1 and any(
        item["source"] in ("default", "migrated") for item in validated_entries
    ):
        raise ValueError("Default and migrated Weak points must be the only entry.")
    return validated_entries
