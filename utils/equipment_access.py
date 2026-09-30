"""Canonical Equipment access values and legacy free-text mapping."""

import re

COMMERCIAL_GYM = "Commercial gym"
HOME_GYM = "Home gym"
BODYWEIGHT_ONLY = "Bodyweight only"

EQUIPMENT_ACCESS_VALUES = (COMMERCIAL_GYM, HOME_GYM, BODYWEIGHT_ONLY)

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
