"""Canonical Equipment access values and legacy free-text mapping."""

import re

COMMERCIAL_GYM = "Commercial gym"
HOME_GYM = "Home gym"
BODYWEIGHT_ONLY = "Bodyweight only"

EQUIPMENT_ACCESS_VALUES = (COMMERCIAL_GYM, HOME_GYM, BODYWEIGHT_ONLY)

# ExerciseDB's ``equipment`` values describe the kind of load or apparatus used.
# Keep these lists in one place so generation and contextual suggestions apply
# the same Equipment access rules.
_BODYWEIGHT_EQUIPMENT = frozenset({"body weight", "bodyweight", "weighted"})
_BAND_EQUIPMENT = frozenset({"band", "resistance band"})
_FREE_WEIGHT_EQUIPMENT = frozenset(
    {"barbell", "dumbbell", "ez barbell", "olympic barbell", "kettlebell", "trap bar"}
)


def equipment_access_filter(access: object) -> tuple[bool, frozenset[str]]:
    """Return whether an equipment value is allowed for a player's Equipment access.

    The boolean says whether the set is an allow-list; otherwise it is a
    deny-list. Unknown legacy access values retain the safe Commercial gym
    behavior through :func:`map_equipment_access`.
    """
    canonical = map_equipment_access(access)
    if canonical == HOME_GYM:
        return True, _FREE_WEIGHT_EQUIPMENT | _BAND_EQUIPMENT | (_BODYWEIGHT_EQUIPMENT - {"weighted"})
    if canonical == BODYWEIGHT_ONLY:
        return True, _BODYWEIGHT_EQUIPMENT - {"weighted"}
    return False, _BAND_EQUIPMENT | _BODYWEIGHT_EQUIPMENT


def equipment_access_allows(access: object, equipment: object) -> bool:
    """Whether a catalog exercise's equipment category fits Equipment access."""
    allow_list, values = equipment_access_filter(access)
    category = " ".join(str(equipment or "").strip().casefold().split())
    return category in values if allow_list else category not in values


def equipment_access_sql(access: object, column: str = "equipment") -> str:
    """Build the fixed catalog equipment predicate for an Equipment access value."""
    allow_list, values = equipment_access_filter(access)
    ordered = sorted(values)
    quoted = ", ".join("'" + value.replace("'", "''") + "'" for value in ordered)
    operator = "IN" if allow_list else "NOT IN"
    return f"LOWER({column}) {operator} ({quoted})"

_COMMERCIAL_GYM_HINTS = re.compile(
    r"\b(?:commercial\s+gym|big\s+gym|my\s+gym|the\s+gym)\b"
)
_BODYWEIGHT_HINTS = re.compile(
    r"\b(?:body\s*weight(?:\s+only)?|calisthenics|no\s+(?:gym|equipment)|"
    r"without\s+equipment|zero\s+equipment|nothing|hotel\s+room)\b"
)
_EQUIPMENT_HINTS = re.compile(
    r"\b(?:dumbbells?|benches?|racks?|barbells?|kettlebells?|bands?)\b"
)
_HOME_HINTS = re.compile(
    r"\b(?:home|house|garage|apartment|basement|spare\s+room|living\s+room)\b"
)


def map_equipment_access(free_text: object) -> str:
    """Give unrecognized legacy wording a stable Commercial gym fallback."""
    text = " ".join(str(free_text or "").strip().split())
    normalized = re.sub(r"[-_/]+", " ", text.casefold())

    if not normalized:
        return COMMERCIAL_GYM
    if _COMMERCIAL_GYM_HINTS.search(normalized):
        return COMMERCIAL_GYM
    if _BODYWEIGHT_HINTS.search(normalized) and not _EQUIPMENT_HINTS.search(normalized):
        return BODYWEIGHT_ONLY
    if _EQUIPMENT_HINTS.search(normalized) or _HOME_HINTS.search(normalized):
        return HOME_GYM
    return COMMERCIAL_GYM
