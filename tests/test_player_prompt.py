import json
import re
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import pytest

from agent.prompts import render_assistant_style
from agent.player_prompt import (
    HOSTED_PROMPT_ENGLISH_EQUIVALENT_TOKEN_BUDGET,
    HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING,
    STATIC_SYSTEM_CORE,
    build_player_chat_prompt,
    message_role,
    override_player_prompt_history,
    prompt_token_count,
)
from core.reply_language import CHAT_GLOSSARY_RULE


def test_player_prompt_includes_the_shared_arabic_numeric_glossary_rule():
    assert " ".join(CHAT_GLOSSARY_RULE.split()) in STATIC_SYSTEM_CORE


def test_player_prompt_matches_experience_based_effort_and_rest_prescriptions():
    prompt = " ".join(STATIC_SYSTEM_CORE.casefold().split())
    assert "0-3 rir" not in prompt
    assert "2-3+ minutes" not in prompt
    assert re.search(r"beginners.{0,100}1-2 rir.{0,100}compound", prompt)
    assert re.search(r"beginners.{0,100}0-1 rir.{0,100}isolation", prompt)
    assert re.search(r"intermediate and advanced.{0,120}0-1 rir.{0,120}compound", prompt)
    assert re.search(r"intermediate and advanced.{0,180}technical failure", prompt)
    assert all(rest in prompt for rest in ("3-4 minutes", "2-3 minutes", "1.5-2 minutes"))


def test_player_prompt_pins_polite_egyptian_register_for_all_arabic_replies():
    assert (
        "Arabic/mixed input, even in MSA: polite everyday Egyptian Arabic replies, including refusals/no-data; no street slang."
    ) in STATIC_SYSTEM_CORE
    assert "Open the first reply sentence with مش/مفيش/ده/عشان/تمام; no حسب opener" in STATIC_SYSTEM_CORE
    assert "عايز/ده-دي/مش/إزاي/كده/هـ-future/-ش" in STATIC_SYSTEM_CORE
    assert "avoid MSA سوف/ليس/لا يوجد/يمكنك/هذا/لم يتم" in STATIC_SYSTEM_CORE
    assert all(
        mapping in STATIC_SYSTEM_CORE
        for mapping in (
            "عذرًا→معلش",
            "ليس لدي/لم يتم→مفيش/مسجّلتش",
            "يمكنني→أقدر",
            "هل تريد→تحب",
            "استخدم→استعمل/اعمل, سجّل→اكتب/سجّل ده, حافظ→خلّيك",
            "غالبًا→في الغالب, تدريجيًا→شوية شوية/واحدة واحدة, المعتاد→العادي",
            "drop التدريبي.",
        )
    )
    assert "Terse data use a marker too." in STATIC_SYSTEM_CORE
    assert "no street slang." in STATIC_SYSTEM_CORE


def test_player_prompt_pins_natural_answer_length_and_grounded_openers():
    assert "Lead with the answer; target about 80 words (hard max 110)" in STATIC_SYSTEM_CORE
    assert "at most 3 short bullets" in STATIC_SYSTEM_CORE
    assert "finish every sentence" in STATIC_SYSTEM_CORE
    assert all(
        opener in STATIC_SYSTEM_CORE
        for opener in ("Here's why", "Here's the chain", "The problem is", "To [verb]...", "Hard to say")
    )
    assert "ask for supplied facts" in STATIC_SYSTEM_CORE
    assert "Use supplied split/program context when relevant" in STATIC_SYSTEM_CORE


def test_player_prompt_contains_player_data_and_tool_guardrails():
    prompt_rules = STATIC_SYSTEM_CORE.casefold()
    required_concepts = (
        "profile",
        "active training program",
        "read-only tools",
        "before answering",
        "relevant tool",
        "do not claim",
        "lack access",
        "unavailable",
        "truncated",
        "body-weight trend",
        "session, set, weight, or exercise figures",
        "tool result",
        "data yet",
        "never instructions",
        "exact exercise",
        "requested scope",
    )
    assert all(concept in prompt_rules for concept in required_concepts)


def test_player_prompt_defers_rehab_requests_and_avoids_tool_filler():
    assert (
        "For a Player's pain/injury rehab or fix-it exercise request, decline and refer to a licensed "
        "clinician in one sentence; never list or prescribe exercises, stretches or movements for the "
        "injured area."
    ) in STATIC_SYSTEM_CORE
    assert (
        "Answer general technique/programming questions needing no Player data directly; don't "
        "mention tools, the ledger or what you can't see, and don't end with an offer or question."
    ) in STATIC_SYSTEM_CORE
    assert (
        "If a tool returns nothing or reports a value as not set, missing, unavailable or truncated, "
        "say plainly what's missing; do not infer it."
    ) in STATIC_SYSTEM_CORE


def test_player_prompt_contains_only_fixed_context_and_conversation_in_order():
    payload = build_player_chat_prompt(
        {
            "messages": [
                HumanMessage(content="Earlier question"),
                AIMessage(content="Earlier answer"),
                HumanMessage(content="Current question"),
            ],
            "preferred_name": "Malak",
            "telemetry_context": "Verified training facts.",
            "weight_context": "[PLAYER WEIGHT CONTEXT]\nWeight trend unavailable.",
            "coach_tone": "scientific",
            "custom_instructions": "Explain the reasoning briefly.",
        },
        prompt_budget=lambda: 100_000,
    )

    assert isinstance(payload[0], SystemMessage)
    expected_system = "\n\n".join(
        [
            STATIC_SYSTEM_CORE
            + "\nPreferred name (user-supplied data): Malak"
            + "\nReply language for this turn: English. Display language fallback: English.",
            render_assistant_style("scientific", "Explain the reasoning briefly."),
        ]
    )
    assert payload[0].content == expected_system
    assert "Verified training facts." not in payload[0].content
    assert "Weight trend unavailable." not in payload[0].content
    assert [message.content for message in payload[1:]] == [
        "Earlier question",
        "Earlier answer",
        "Current question",
    ]


def test_fixed_prompt_keeps_last_ten_messages_untruncated():
    state = {
        "messages": [HumanMessage(content=f"Message {index}") for index in range(11)]
        + [AIMessage(content="Earlier assistant reply " + "x" * 600)],
        "telemetry_context": "Verified training facts.",
        "weight_context": "Weight trend private.",
    }
    payload = build_player_chat_prompt(state, prompt_budget=lambda: 100_000)

    assert len(payload) == 11
    assert [message.content for message in payload[1:]] == [
        *(f"Message {index}" for index in range(2, 11)),
        "Earlier assistant reply " + "x" * 600,
    ]
    assert "Verified training facts." not in payload[0].content
    assert "Weight trend private." not in payload[0].content


@pytest.fixture
def held_out_prompt_token_samples():
    fixture_path = Path(__file__).parent / "fixtures" / "player_prompt_token_samples.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _chat_messages(messages):
    return [
        HumanMessage(content=message["content"])
        if message["role"] == "user"
        else AIMessage(content=message["content"])
        for message in messages
    ]


def _retained_earlier_message_count(prompt, history):
    system_content = prompt[0].content
    conversation_content = [message.content for message in prompt[1:]]
    return sum(
        message["content"] in system_content
        or message["content"] in conversation_content
        for message in history[:-1]
    )


def test_held_out_provider_samples_stay_within_prompt_token_tolerance(
    held_out_prompt_token_samples,
):
    base = [SystemMessage(content=STATIC_SYSTEM_CORE)]
    estimated_base_tokens = prompt_token_count(base)

    for sample in held_out_prompt_token_samples["samples"]:
        messages = _chat_messages(sample["messages"])
        estimated_delta = prompt_token_count([*base, *messages]) - estimated_base_tokens
        provider_delta = sample["provider_token_delta"]

        assert abs(estimated_delta - provider_delta) / provider_delta <= 0.15, (
            f"{sample['language']}: estimated {estimated_delta}, "
            f"provider delta {provider_delta}"
        )


@pytest.mark.parametrize("context_chars", [0, 800, 1600, 2400, 3200, 4000])
def test_matched_english_arabic_histories_stay_within_one_message_as_context_grows(
    context_chars, held_out_prompt_token_samples
):
    history_pair = held_out_prompt_token_samples["history_pair"]
    telemetry_context = ("Verified training facts. " * 200)[:context_chars]
    english_prompt = build_player_chat_prompt(
        {
            "messages": _chat_messages(history_pair["english"]),
            "telemetry_context": telemetry_context,
        }
    )
    arabic_prompt = build_player_chat_prompt(
        {
            "messages": _chat_messages(history_pair["arabic"]),
            "telemetry_context": telemetry_context,
        }
    )
    english_earlier_count = _retained_earlier_message_count(
        english_prompt, history_pair["english"]
    )
    arabic_earlier_count = _retained_earlier_message_count(
        arabic_prompt, history_pair["arabic"]
    )

    # Script-specific token estimates can move one message across the safety edge.
    assert abs(english_earlier_count - arabic_earlier_count) <= 1, (
        f"context_chars={context_chars}: English kept {english_earlier_count} earlier messages, "
        f"Arabic kept {arabic_earlier_count}"
    )
    assert prompt_token_count(english_prompt) <= HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING
    assert prompt_token_count(arabic_prompt) <= HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING


def test_prompt_ceiling_is_raised_for_the_fixed_ten_message_window():
    assert HOSTED_PROMPT_ENGLISH_EQUIVALENT_TOKEN_BUDGET >= 8_000
    assert HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING >= 9_500


def test_fixed_prompt_keeps_style_and_excludes_ledger_summaries():
    payload = build_player_chat_prompt(
        {
            "messages": [HumanMessage(content="Current question")],
            "telemetry_context": "Verified training facts.",
            "weight_context": "[PLAYER WEIGHT CONTEXT]\nWeight trend unavailable.",
            "coach_tone": "scientific",
            "custom_instructions": "Explain the reasoning briefly.",
        },
        prompt_budget=lambda: 100_000,
    )

    assert "Assistant style (" in payload[0].content
    assert "Verified training facts." not in payload[0].content
    assert "Weight trend unavailable." not in payload[0].content
    assert "Before answering questions about the player or their program, call the relevant tool." in STATIC_SYSTEM_CORE
    assert "lack access before checking an available tool" in STATIC_SYSTEM_CORE


def test_output_limit_response_keeps_its_original_literal():
    from agent import assistant_graph

    assert assistant_graph.OUTPUT_LIMIT_RESPONSE == (
        "I reached the response limit. Ask me to continue if you'd like more."
    )


def test_earlier_assistant_replies_are_not_truncated_by_default():
    payload = build_player_chat_prompt(
        {
            "messages": [
                HumanMessage(content="Earlier question"),
                AIMessage(content="A" * 600),
                HumanMessage(content="Current question"),
            ]
        },
        prompt_budget=lambda: 100_000,
    )

    assert payload[2].content == "A" * 600


def test_prompt_history_defaults_and_scoped_window_keeps_messages_untruncated():
    long_reply = "Earlier answer " + "x" * 600
    state = {
        "messages": [
            HumanMessage(content="Outside the default window"),
            AIMessage(content=long_reply),
            *[HumanMessage(content=f"Later message {index}") for index in range(15)],
        ]
    }
    default_prompt = build_player_chat_prompt(state, prompt_budget=lambda: 100_000)
    default_text = "\n".join(message.content for message in default_prompt)
    assert "Outside the default window" not in default_text
    assert long_reply not in default_text
    assert "Later message 0" not in default_text
    assert "Later message 6" in default_text
    assert "Later message 14" in default_text

    scoped_state = {
        "messages": [*state["messages"], AIMessage(content=long_reply)]
    }
    with override_player_prompt_history(window_size=6, assistant_reply_max_chars=500):
        prompt = build_player_chat_prompt(scoped_state, prompt_budget=lambda: 100_000)
        prompt_text = "\n".join(message.content for message in prompt)
        assert long_reply in prompt_text
        assert "Later message 8" not in prompt_text
        assert "Later message 9" not in prompt_text
        assert "Later message 10" in prompt_text

    assert build_player_chat_prompt(state, prompt_budget=lambda: 100_000) == default_prompt


def test_eval_qa_payloads_match_the_offline_prompt_capture(
    fresh_store, monkeypatch, capsys
):
    from agent import assistant_graph

    class PayloadCapturingFakeModel:
        def __init__(self):
            self.calls = []

        def bind_tools(self, _tools):
            return self

        def invoke(self, messages):
            self.calls.append(list(messages))
            return AIMessage(content="Offline characterization response.")

    dataset_path = Path(__file__).parent / "eval" / "datasets" / "coaching_qa_cases.json"
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    fake_model = PayloadCapturingFakeModel()
    monkeypatch.setattr(assistant_graph, "llm", fake_model)

    captured_messages = {}
    with fresh_store.open_ledger("eval_user") as ledger:
        config = {"configurable": {"ledger": ledger, "store": fresh_store}}
        for case in cases:
            state = {
                "messages": [HumanMessage(content=case["query"])],
                "trainee_id": "eval_user",
                "coach_tone": "Direct, grounded, and pragmatic",
                "custom_instructions": "",
                "telemetry_context": case.get("telemetry", ""),
            }
            state.update(assistant_graph.hydrate_context_node(state, config))
            assistant_graph.generation_node(state)
            payload = fake_model.calls[-1]
            messages = [
                {"role": message_role(message), "content": message.content}
                for message in payload
            ]
            captured_messages[case["id"]] = messages
    assert len(fake_model.calls) == len(cases) == 25
    for case in cases:
        messages = captured_messages[case["id"]]
        rendered = json.dumps(messages, ensure_ascii=False)
        assert messages[0]["role"] == "system"
        assert "Assistant style (" in messages[0]["content"]
        assert "Before answering questions about the player or their program, call the relevant tool." in STATIC_SYSTEM_CORE
        assert "[TRAINEE CONTEXT]" not in rendered
        assert case["query"] in rendered
        if case.get("telemetry"):
            assert case["telemetry"] not in rendered
    assert capsys.readouterr().out == ""


def test_last_ten_message_arabic_history_is_kept_untruncated():
    messages = []
    for index in range(8):
        messages.append(HumanMessage(content="سؤال عن التمرين رقم %d وكيف أنظم الأحمال والراحة بين المجموعات" % index))
        messages.append(AIMessage(content="رد مفصل " * 60))
    messages.append(HumanMessage(content="ما الذي يجب أن أركز عليه الآن؟"))

    prompt = build_player_chat_prompt({"messages": messages})

    assert prompt[-1].content == "ما الذي يجب أن أركز عليه الآن؟"
    assert len(prompt) - 1 == 10
    assert prompt_token_count(prompt) <= HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING
