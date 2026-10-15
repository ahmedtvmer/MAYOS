"""Fixed injury vocabulary and Exercise library body-part mapping."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

INJURY_BODY_AREAS = (
    "knee",
    "hip",
    "lower_back",
    "shoulder",
    "elbow",
    "wrist",
    "ankle",
    "neck",
)
INJURY_STATUSES = ("reported", "physician_seen", "resolved")

INJURY_BODY_AREA_LABELS = {
    "en": {
        "knee": "knee",
        "hip": "hip",
        "lower_back": "lower back",
        "shoulder": "shoulder",
        "elbow": "elbow",
        "wrist": "wrist",
        "ankle": "ankle",
        "neck": "neck",
    },
    "ar": {
        "knee": "الركبة",
        "hip": "الورك",
        "lower_back": "أسفل الظهر",
        "shoulder": "الكتف",
        "elbow": "الكوع",
        "wrist": "الرسغ",
        "ankle": "الكاحل",
        "neck": "الرقبة",
    },
}
INJURY_STATUS_LABELS = {
    "en": {
        "reported": "reported",
        "physician_seen": "physician seen",
        "resolved": "resolved",
    },
    "ar": {
        "reported": "تم الإبلاغ",
        "physician_seen": "تمت مراجعة الطبيب",
        "resolved": "تم التعافي",
    },
}

# Values are the ExerciseDB ``body_part`` vocabulary, case-folded for SQL.
INJURY_BODY_PARTS: dict[str, tuple[str, ...]] = {
    "knee": ("upper legs", "lower legs"),
    "hip": ("upper legs", "waist"),
    "lower_back": ("back", "waist"),
    "shoulder": ("shoulders", "upper arms"),
    "elbow": ("upper arms", "lower arms"),
    "wrist": ("lower arms",),
    "ankle": ("lower legs",),
    "neck": ("neck", "back"),
}

_BODY_AREA_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "lower_back",
        re.compile(
            r"\b(?:lower[\s-]+back|lumbar|spine)\b|"
            r"\bback\s+pain\b|\b(?:hurt|hurts|hurting)\s+(?:my\s+)?back\b|"
            r"\bmy\s+back\b(?!\s+(?:squat|extension|row|day|workout|exercise|to\s+training))|"
            r"أسفل\s+الظهر|ألم\s+في\s+الظهر|وجع\s+ضهري|ضهري|ظهري",
            re.I,
        ),
    ),
    ("knee", re.compile(r"\bknees?\b|ركب(?:ة|تي|تيه|تين)|الركبة", re.I)),
    ("hip", re.compile(r"\bhips?\b|ورك(?:ي|يّ)?|الورك", re.I)),
    ("shoulder", re.compile(r"\bshoulders?\b|أكتاف|كتف(?:ي|يّ)?", re.I)),
    ("elbow", re.compile(r"\belbows?\b|مرفق(?:ي|يّ)?|كوع(?:ي|يّ)?", re.I)),
    ("wrist", re.compile(r"\bwrists?\b|معصم(?:ي|يّ)?|رسغ(?:ي|يّ)?", re.I)),
    ("ankle", re.compile(r"\bankles?\b|كاحل(?:ي|يّ)?", re.I)),
    ("neck", re.compile(r"\bnecks?\b|رقبة|رقبتي", re.I)),
)
_CLARIFICATION_AREA_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "lower_back",
        re.compile(
            r"(?:my\s+)?(?:(?:left|right)\s+)?(?:lower[\s-]+back|back|lumbar|spine)|"
            r"أسفل\s+الظهر|الظهر|ضهري|ظهري|ألم\s+في\s+الظهر|وجع\s+ضهري",
            re.I,
        ),
    ),
    ("knee", re.compile(r"(?:my\s+)?(?:(?:left|right)\s+)?knees?|ركب(?:ة|تي|تيه|تين)|الركبة", re.I)),
    ("hip", re.compile(r"(?:my\s+)?(?:(?:left|right)\s+)?hips?|ورك(?:ي|يّ)?|الورك", re.I)),
    ("shoulder", re.compile(r"(?:my\s+)?(?:(?:left|right)\s+)?shoulders?|أكتاف|كتف(?:ي|يّ)?", re.I)),
    ("elbow", re.compile(r"(?:my\s+)?(?:(?:left|right)\s+)?elbows?|مرفق(?:ي|يّ)?|كوع(?:ي|يّ)?", re.I)),
    ("wrist", re.compile(r"(?:my\s+)?(?:(?:left|right)\s+)?wrists?|معصم(?:ي|يّ)?|رسغ(?:ي|يّ)?", re.I)),
    ("ankle", re.compile(r"(?:my\s+)?(?:(?:left|right)\s+)?ankles?|كاحل(?:ي|يّ)?", re.I)),
    ("neck", re.compile(r"(?:my\s+)?neck|رقبة|رقبتي", re.I)),
)


def normalize_body_area(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {"lowerback": "lower_back"}
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in INJURY_BODY_AREAS else None


def injury_body_area_label(body_area: str, language: str) -> str:
    area = normalize_body_area(body_area)
    if area is None:
        return str(body_area).replace("_", " ")
    return INJURY_BODY_AREA_LABELS.get(language, INJURY_BODY_AREA_LABELS["en"]).get(
        area, area.replace("_", " ")
    )


def injury_status_label(status: str, language: str) -> str:
    return INJURY_STATUS_LABELS.get(language, INJURY_STATUS_LABELS["en"]).get(
        status, status.replace("_", " ")
    )


def body_area_in_text(text: str) -> str | None:
    """Returns the first recognized fixed body area in English or Arabic."""
    for area, pattern in _BODY_AREA_PATTERNS:
        if pattern.search(text):
            return area
    return None


def clarification_body_area_in_text(text: str) -> str | None:
    """Recognize a short, direct body-area answer to the clarification question."""
    reply = text.strip().strip(".!?,;:؟، ")
    if not reply or len(reply.split()) > 4:
        return None
    for area, pattern in _CLARIFICATION_AREA_PATTERNS:
        if pattern.fullmatch(reply):
            return area
    return None


def injury_body_parts(body_area: str | None) -> tuple[str, ...]:
    area = normalize_body_area(body_area)
    return INJURY_BODY_PARTS.get(area, ()) if area else ()


def render_injury_record(record: dict[str, Any]) -> dict[str, Any]:
    area = normalize_body_area(record.get("body_area"))
    return {
        **record,
        "body_area": area,
        "catalog_body_parts": list(injury_body_parts(area)),
    }


def is_none_answer(value: Any) -> bool:
    if not isinstance(value, str):
        return value is None
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return normalized in {"", "none", "no injuries", "لا شيء", "لا توجد إصابات"}
