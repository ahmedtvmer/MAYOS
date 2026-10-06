"""Exercise library facts formatted for assistant model context."""

from collections.abc import Iterable, Mapping
from typing import Any

from database.exercise_library.vocabulary import equipment_category_for

_NOT_LOOKED_UP = object()


def describe_exercise_facts(entry: Mapping[str, Any]) -> str:
    """Render the populated curated facts for one Exercise library row."""
    secondary = ", ".join(
        str(action) for action in (entry.get("secondary_actions") or ()) if action
    )
    load_labels = {"selectorized": "Pin-loaded", "plate_loaded": "Plate-loaded"}
    fields = [
        ("Primary action", entry.get("primary_action")),
        ("Secondary actions", secondary),
        ("Primary muscle", entry.get("primary_muscle")),
        ("Load type", load_labels.get(entry.get("load_type"))),
    ]
    category = entry.get("equipment_category") or equipment_category_for(entry.get("equipment"))
    facts = [f"{label}: {value}" for label, value in fields if value]
    facts.append(f"Equipment category: {category}")
    return f"{entry['name']} — " + "; ".join(facts)


def describe_exercise(
    store: Any,
    exercise_id: str,
    fallback_name: str,
    *,
    entry: Mapping[str, Any] | None | object = _NOT_LOOKED_UP,
) -> str:
    """Look up and describe one exercise, falling back to its display name."""
    if entry is _NOT_LOOKED_UP:
        entry = store.get_exercise_library_entry(str(exercise_id))
    return describe_exercise_facts(entry) if isinstance(entry, Mapping) else fallback_name


def describe_exercises(
    store: Any, exercises: Iterable[tuple[str, str]]
) -> list[str]:
    """Describe exercise refs with one public batch lookup."""
    refs = [(str(exercise_id), name) for exercise_id, name in exercises]
    entries = store.get_exercise_library_entries([exercise_id for exercise_id, _ in refs])
    entries = entries if isinstance(entries, dict) else {}
    return [
        describe_exercise(store, exercise_id, name, entry=entries.get(exercise_id))
        for exercise_id, name in refs
    ]
