"""Session pointers share their formatter and parser for both display languages."""

import pytest

from agent.chat_markers import (
    SessionPointerFacts,
    chat_message_kind,
    format_session_pointer,
    is_session_pointer_text,
)


@pytest.mark.parametrize("count", [1, 2, 3, 11, 100])
def test_arabic_generated_session_pointer_is_a_debrief_pointer(count):
    pointer = format_session_pointer(
        SessionPointerFacts(
            display_language="ar",
            day_name="Upper/Lower",
            performed_date="2026-10-12",
            total_working_sets=count,
            total_tonnage_kg=1234.5,
            readiness=4,
        )
    )

    assert is_session_pointer_text(pointer)
    assert chat_message_kind("assistant", pointer) == "debrief"
    assert "\u2068Upper/Lower\u2069" in pointer
    assert "\u20662026-10-12\u2069" in pointer
    assert "\u20661,234.5 kg\u2069" in pointer
    assert "\u20664/5\u2069" in pointer


def test_english_session_pointer_keeps_its_existing_format_and_classification():
    pointer = (
        "📋 **Session Logged:** Upper/Lower (2026-10-12) | 12 Sets | "
        "Volume: 1,234.5 kg | Readiness: 4/5 | Saved to Ledger."
    )

    assert format_session_pointer(
        SessionPointerFacts("en", "Upper/Lower", "2026-10-12", 12, 1234.5, 4)
    ) == pointer
    assert is_session_pointer_text(pointer)
    assert chat_message_kind("assistant", pointer) == "debrief"
    assert chat_message_kind("user", pointer) == "message"


def test_legacy_arabic_pointer_without_isolates_remains_classified():
    pointer = (
        "📋 **تم تسجيل الحصة التدريبية:** Upper (2026-10-12) | "
        "3 مجموعات تدريب | إجمالي الوزن المرفوع: 120.0 kg | "
        "الاستعداد: 4/5 | حُفظت في سجل التدريب."
    )

    assert chat_message_kind("assistant", pointer) == "debrief"


def test_arabic_pointer_rejects_count_forms_the_generator_never_emits():
    pointer = format_session_pointer(
        SessionPointerFacts("ar", "Upper", "2026-10-12", 2, 1.0, 3)
    )
    assert is_session_pointer_text(pointer.replace("مجموعتا تدريب", "مجموعتي تدريب")) is False
