import json
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from agent.player_prompt import build_player_chat_prompt
from service import coach_ai
from core.reply_language import resolve_reply_language

ROUTING_CASES_PATH = (
    Path(__file__).parent / "eval" / "datasets" / "routing_cases.json"
)
ROUTING_CASES = json.loads(ROUTING_CASES_PATH.read_text())["cases"]


@pytest.mark.parametrize(
    ("message", "display_language", "expected"),
    [
        ("What is my Training program?", "ar", "en"),
        ("How is أحمد doing?", "ar", "en"),
        ("Call me أحمد", "ar", "en"),
        ("بدّل الـ bench press", "en", "ar"),
        ("ممكن تشرحلي الـ Training program؟", "en", "ar"),
        ("إيه معنى RIR؟", "en", "ar"),
        ("💪 123", "ar", "ar"),
        ("💪 123", "en", "en"),
        ("hi أنا", "en", "ar"),
        ("hi أنا", "ar", "ar"),
    ],
)
def test_resolve_reply_language_uses_clear_message_before_display_language(
    message, display_language, expected
):
    assert resolve_reply_language(message, display_language) == expected


@pytest.mark.parametrize("case", ROUTING_CASES, ids=lambda case: case["id"])
def test_routing_cases_resolve_to_their_declared_language_for_both_display_languages(
    case,
):
    expected = {"arabic": "ar", "english": "en"}[case["language"]]
    for display_language in ("en", "ar"):
        assert resolve_reply_language(case["text"], display_language) == expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("How is أحمد doing?", "en"),
        ("How is محمد علي doing this week?", "en"),
        ("call me أحمد", "en"),
        ("swap bench press for dumbbell press يا كابتن", "en"),
        ("بدّل الـ bench press", "ar"),
        ("عايز أبدّل البنش", "ar"),
        ("قمرـ barbell bench press بتمرين dumbbell bench press", "ar"),
        (
            "استبدل تمرين Barbell Bench Press بتمرين Dumbbell Bench Press.",
            "ar",
        ),
    ],
)
def test_reply_language_uses_the_grammatical_frame_for_mixed_messages(
    message, expected
):
    for display_language in ("en", "ar"):
        assert resolve_reply_language(message, display_language) == expected


@pytest.mark.parametrize(
    ("message", "display_language", "expected"),
    [
        ("👍", "en", "en"),
        ("👍", "ar", "ar"),
        ("12", "en", "en"),
        ("12", "ar", "ar"),
        ("cat بيت", "en", "en"),
        ("cat بيت", "ar", "ar"),
        ("cat قمر", "en", "en"),
        ("cat قمر", "ar", "ar"),
        ("cats قمر", "en", "en"),
        ("cats قمر", "ar", "ar"),
        ("ok", "en", "en"),
        ("ok", "ar", "en"),
    ],
)
def test_reply_language_uses_display_fallback_for_no_or_near_tied_letters(
    message, display_language, expected
):
    assert resolve_reply_language(message, display_language) == expected


def test_player_prompt_names_resolved_language_and_shared_glossary():
    payload = build_player_chat_prompt(
        {
            "messages": [HumanMessage(content="ممكن تشرحلي الـ Training program؟")],
            "display_language": "en",
        },
        prompt_budget=lambda: 100_000,
    )

    assert "Reply language for this turn: Arabic" in payload[0].content
    assert "Display language fallback: English" in payload[0].content
    assert "polite everyday Egyptian Arabic" in payload[0].content
    assert "برنامج تدريبي" in payload[0].content
    assert "سيتات" in payload[0].content
    assert "عدّات" in payload[0].content


def test_coach_prompt_names_resolved_language_and_shared_glossary():
    context = coach_ai.render_context(coach_ai.CANONICAL_FIXTURE)
    messages = coach_ai.build_messages(
        context,
        "ممكن تشرحلي الـ Training program؟",
        [],
        display_language="en",
    )

    prompt = " ".join(messages[0].content.split())
    assert "Reply language for this turn: Arabic" in prompt
    assert "Display language fallback: English" in prompt
    assert "polite everyday Egyptian Arabic" in prompt
    assert "برنامج تدريبي" in prompt
    assert "مكتبة التمارين" in prompt
    assert "محطة تقدم" in prompt
    assert "سيتات" in prompt
    assert "عدّات" in prompt


def test_player_and_coach_prompts_keep_english_for_english_questions_with_arabic_names():
    for message in ("How is أحمد doing?", "How is محمد علي doing this week?"):
        player_prompt = build_player_chat_prompt(
            {
                "messages": [HumanMessage(content=message)],
                "display_language": "ar",
            },
            prompt_budget=lambda: 100_000,
        )
        player_text = " ".join(prompt.content for prompt in player_prompt)

        coach_context = coach_ai.render_context(coach_ai.CANONICAL_FIXTURE)
        coach_prompt = coach_ai.build_messages(
            coach_context, message, [], display_language="ar"
        )
        coach_text = " ".join(prompt.content for prompt in coach_prompt)

        assert "Reply language for this turn: English" in player_text
        assert "Reply language for this turn: English" in coach_text
