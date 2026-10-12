"""Formatting and recognition for the assistant session-logged pointer.

A committed workout writes one assistant pointer into chat history. The prompt
builder trims it before model context and the history API labels it for the
client, so its format, parser, and bidi isolation live together here.
"""

import re
from dataclasses import dataclass

from agent.debrief import arabic_count_phrase

_ENGLISH_SESSION_POINTER = re.compile(
    r"(?:"
    r"[^\w]*\*\*Session Logged:\*\* .+ \(\d{4}-\d{2}-\d{2}\) \| \d+ Sets \| "
    r"Volume: [\d,.]+ kg \| Readiness: [1-5]/5 \| Saved to Ledger\."
    r")"
)
_ARABIC_SESSION_POINTER = re.compile(
    r"[^\w]*\*\*تم تسجيل الحصة التدريبية:\*\* "
    r"(?P<name>\u2068[^\u2069]+\u2069|.+?) \("
    r"(?P<date>\u2066\d{4}-\d{2}-\d{2}\u2069|\d{4}-\d{2}-\d{2})\) \| "
    r"(?P<sets>[^|]+) \| إجمالي الوزن المرفوع: "
    r"(?P<weight>\u2066[\d,.]+ kg\u2069|[\d,.]+ kg) \| الاستعداد: "
    r"(?P<readiness>\u2066[1-5]/5\u2069|[1-5]/5) \| حُفظت في سجل التدريب\."
)
_ISOLATED_OR_PLAIN_COUNT = re.compile(
    r"(?:\u2066(?P<isolated_count>\d+)\u2069|(?P<plain_count>\d+)) "
    r"(?P<form>مجموعات تدريب|مجموعة تدريب)"
)


@dataclass(frozen=True)
class SessionPointerFacts:
    display_language: str
    day_name: str
    performed_date: str
    total_working_sets: int
    total_tonnage_kg: float
    readiness: int


def _isolate_first_strong(value: str) -> str:
    return f"\u2068{value}\u2069"


def _isolate_left_to_right(value: str) -> str:
    return f"\u2066{value}\u2069"


def format_session_pointer(facts: SessionPointerFacts) -> str:
    """Render the saved chat pointer without changing its recorded facts."""
    if facts.display_language != "ar":
        return (
            f"📋 **Session Logged:** {facts.day_name} ({facts.performed_date}) | "
            f"{facts.total_working_sets} Sets | Volume: "
            f"{facts.total_tonnage_kg:,.1f} kg | Readiness: {facts.readiness}/5 | "
            "Saved to Ledger."
        )

    count_phrase = arabic_count_phrase(
        facts.total_working_sets,
        "training_set",
        numeral_direction="isolated",
    )
    return (
        f"📋 **تم تسجيل الحصة التدريبية:** {_isolate_first_strong(facts.day_name)} "
        f"({_isolate_left_to_right(facts.performed_date)}) | {count_phrase} | "
        "إجمالي الوزن المرفوع: "
        f"{_isolate_left_to_right(f'{facts.total_tonnage_kg:,.1f} kg')} | "
        f"الاستعداد: {_isolate_left_to_right(f'{facts.readiness}/5')} | "
        "حُفظت في سجل التدريب."
    )


def _has_generated_count_form(value: str) -> bool:
    if value == arabic_count_phrase(1, "training_set"):
        return True
    if value == arabic_count_phrase(2, "training_set"):
        return True
    match = _ISOLATED_OR_PLAIN_COUNT.fullmatch(value)
    if match is None:
        return False
    count_text = match.group("isolated_count") or match.group("plain_count")
    expected = arabic_count_phrase(
        int(count_text),
        "training_set",
        numeral_direction="isolated" if match.group("isolated_count") else "plain",
    )
    return value == expected


def is_session_pointer_text(text: str) -> bool:
    """True when ``text`` is a generated English or Arabic session pointer."""
    if _ENGLISH_SESSION_POINTER.fullmatch(text):
        return True
    match = _ARABIC_SESSION_POINTER.fullmatch(text)
    return match is not None and _has_generated_count_form(match.group("sets"))


def chat_message_kind(role: str, content: str) -> str:
    """The wire ``kind`` for one stored message: ``debrief`` or ``message``."""
    if role == "assistant" and is_session_pointer_text(content):
        return "debrief"
    return "message"
