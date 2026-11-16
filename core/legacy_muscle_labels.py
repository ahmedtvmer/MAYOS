"""Legacy saved muscle labels shared by ledger upgrades and template copies."""

_LEGACY_BACK_DAY_LABELS = {
    "chest & back": "Chest, Lats & Traps",
    "chest and back": "Chest, Lats & Traps",
}


def replace_legacy_back_muscle(stored_value, *, string_list: bool = False):
    """Rename legacy Focus values and the retired Chest & Back day label."""
    if isinstance(stored_value, dict):
        return _replace_legacy_back_fields(stored_value)
    if isinstance(stored_value, list):
        return _replace_legacy_back_list(stored_value, string_list=string_list)
    return stored_value, False


def _replace_legacy_back_fields(stored_object: dict):
    migrated_object = {}
    has_changes = False
    for key, nested_value in stored_object.items():
        if key in {"muscle", "focus_muscle"} and nested_value == "back":
            migrated_object[key] = "lats"
            has_changes = True
            continue
        if key == "day_name" and isinstance(nested_value, str):
            label = _LEGACY_BACK_DAY_LABELS.get(nested_value.strip().casefold())
            if label is not None:
                migrated_object[key] = label
                has_changes = True
                continue
        if key in {"muscles", "focus_muscles", "weak_points"} and isinstance(nested_value, list):
            migrated_nested_value, nested_changed = replace_legacy_back_muscle(
                nested_value, string_list=True
            )
        else:
            migrated_nested_value, nested_changed = replace_legacy_back_muscle(nested_value)
        migrated_object[key] = migrated_nested_value
        has_changes = has_changes or nested_changed
    return migrated_object, has_changes


def _replace_legacy_back_list(stored_list: list, *, string_list: bool):
    migrated_values = []
    has_changes = False
    for nested_value in stored_list:
        if string_list and nested_value == "back":
            migrated_values.append("lats")
            has_changes = True
            continue
        migrated_nested_value, nested_changed = replace_legacy_back_muscle(nested_value)
        migrated_values.append(migrated_nested_value)
        has_changes = has_changes or nested_changed
    return migrated_values, has_changes


