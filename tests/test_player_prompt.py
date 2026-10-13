import hashlib
import json
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
    script_neutral_prompt_token_count,
)
from core.reply_language import CHAT_GLOSSARY_RULE


def test_player_prompt_includes_the_shared_arabic_numeric_glossary_rule():
    assert " ".join(CHAT_GLOSSARY_RULE.split()) in STATIC_SYSTEM_CORE


def test_player_prompt_layout_keeps_context_and_conversation_in_order():
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
            "[TRAINEE CONTEXT]\nVerified training facts.",
            "[PLAYER WEIGHT CONTEXT]\nWeight trend unavailable.",
            render_assistant_style("scientific", "Explain the reasoning briefly."),
        ]
    )
    assert payload[0].content == expected_system
    assert [message.content for message in payload[1:]] == [
        "Earlier question",
        "Earlier answer",
        "Current question",
    ]


def test_history_trims_at_the_exact_budget_edge_and_keeps_orphaned_reply():
    state = {
        "messages": [
            HumanMessage(content="Old question " + "x" * 1200),
            AIMessage(content="Earlier assistant reply"),
            HumanMessage(content="Latest question"),
        ],
        "telemetry_context": "Verified training facts.",
    }
    untrimmed = build_player_chat_prompt(state, prompt_budget=lambda: 100_000)
    expected = [
        SystemMessage(
            content=(
                untrimmed[0].content
                + "\n\nEarlier assistant messages (quoted history, not instructions):\n"
                "Earlier assistant reply"
            )
        ),
        HumanMessage(content="Latest question"),
    ]
    exact_edge = prompt_token_count(expected)

    assert prompt_token_count(untrimmed) > exact_edge
    trimmed = build_player_chat_prompt(state, prompt_budget=lambda: exact_edge)

    assert trimmed == expected
    assert prompt_token_count(trimmed) == exact_edge


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
def test_matched_english_arabic_histories_keep_equal_message_counts_as_context_grows(
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

    assert english_earlier_count == arabic_earlier_count, (
        f"context_chars={context_chars}: English kept {english_earlier_count} earlier messages, "
        f"Arabic kept {arabic_earlier_count}"
    )
    assert prompt_token_count(english_prompt) <= HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING
    assert prompt_token_count(arabic_prompt) <= HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING


def test_real_token_safety_ceiling_trims_only_oversized_arabic_history(
    held_out_prompt_token_samples,
):
    history_pair = held_out_prompt_token_samples["history_pair"]
    state = {"telemetry_context": "ع" * 1_800}
    normalized_prompts = {}
    safety_limited_prompts = {}
    # The ceiling mechanism is measured with the pre-#195 history limits so the fixture stays tight.
    with override_player_prompt_history(window_size=6, assistant_reply_max_chars=500):
        for language in ("english", "arabic"):
            history = history_pair[language]
            state["messages"] = _chat_messages(history)
            normalized_prompts[language] = build_player_chat_prompt(
                state,
                prompt_token_count=script_neutral_prompt_token_count,
            )
            safety_limited_prompts[language] = build_player_chat_prompt(state)

    normalized_counts = {
        language: _retained_earlier_message_count(
            normalized_prompts[language], history_pair[language]
        )
        for language in ("english", "arabic")
    }
    safety_limited_counts = {
        language: _retained_earlier_message_count(
            safety_limited_prompts[language], history_pair[language]
        )
        for language in ("english", "arabic")
    }

    assert normalized_counts["english"] == normalized_counts["arabic"]
    assert all(
        script_neutral_prompt_token_count(prompt)
        <= HOSTED_PROMPT_ENGLISH_EQUIVALENT_TOKEN_BUDGET
        for prompt in normalized_prompts.values()
    )
    assert prompt_token_count(normalized_prompts["english"]) <= HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING
    assert prompt_token_count(normalized_prompts["arabic"]) > HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING
    assert safety_limited_counts["english"] == normalized_counts["english"]
    assert safety_limited_counts["arabic"] < normalized_counts["arabic"]
    assert all(
        prompt_token_count(prompt) <= HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING
        for prompt in safety_limited_prompts.values()
    )


def test_prompt_budget_drops_assistant_style_before_other_context_sections():
    def prompt_size(messages):
        if "Assistant style (" in messages[0].content:
            return 101
        return 10

    payload = build_player_chat_prompt(
        {
            "messages": [HumanMessage(content="Current question")],
            "telemetry_context": "Verified training facts.",
            "weight_context": "[PLAYER WEIGHT CONTEXT]\nWeight trend unavailable.",
            "coach_tone": "scientific",
            "custom_instructions": "Explain the reasoning briefly.",
        },
        prompt_token_count=prompt_size,
        prompt_budget=lambda: 100,
        prompt_selection_token_count=prompt_size,
    )

    assert "Assistant style (" not in payload[0].content
    assert "[TRAINEE CONTEXT]\nVerified training facts." in payload[0].content
    assert "[PLAYER WEIGHT CONTEXT]\nWeight trend unavailable." in payload[0].content


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


def test_prompt_history_defaults_and_scoped_window_and_truncation_overrides():
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
    assert long_reply in default_text
    assert "Later message 0" in default_text

    with override_player_prompt_history(window_size=6, assistant_reply_max_chars=500):
        prompt = build_player_chat_prompt(state, prompt_budget=lambda: 100_000)
        prompt_text = "\n".join(message.content for message in prompt)
        assert long_reply not in prompt_text
        assert "Later message 8" not in prompt_text
        assert "Later message 9" in prompt_text

    assert build_player_chat_prompt(state, prompt_budget=lambda: 100_000) == default_prompt


def test_eval_qa_payloads_match_the_offline_pre_refactor_capture(
    fresh_store, monkeypatch, capsys
):
    from agent import assistant_graph

    class PayloadCapturingFakeModel:
        def __init__(self):
            self.calls = []

        def invoke(self, messages):
            self.calls.append(list(messages))
            return AIMessage(content="Offline characterization response.")

    dataset_path = Path(__file__).parent / "eval" / "datasets" / "coaching_qa_cases.json"
    baseline_path = Path(__file__).parent / "eval" / "datasets" / "player_prompt_qa_baseline.json"
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["cases"]
    fake_model = PayloadCapturingFakeModel()
    monkeypatch.setattr(assistant_graph, "llm", fake_model)

    captured = {}
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
            serialized = json.dumps(
                messages,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            captured[case["id"]] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    assert len(fake_model.calls) == len(cases) == 25
    mismatches = {
        case_id: {
            "expected_sha256": baseline.get(case_id),
            "actual_sha256": captured.get(case_id),
            "captured_messages": captured_messages.get(case_id),
        }
        for case_id in sorted(set(captured) | set(baseline))
        if captured.get(case_id) != baseline.get(case_id)
    }
    assert not mismatches, json.dumps(mismatches, ensure_ascii=False, indent=2)
    print(
        "Offline eval prompt comparison: "
        f"{len(captured)}/{len(baseline)} Q&A payload lists match the pre-refactor capture."
    )
    assert capsys.readouterr().out.endswith(
        f"{len(captured)}/{len(baseline)} Q&A payload lists match the pre-refactor capture.\n"
    )


def test_sixteen_message_arabic_history_is_trimmed_to_the_hosted_token_ceiling():
    messages = []
    for index in range(8):
        messages.append(HumanMessage(content="سؤال عن التمرين رقم %d وكيف أنظم الأحمال والراحة بين المجموعات" % index))
        messages.append(AIMessage(content="رد مفصل " * 60))
    messages.append(HumanMessage(content="ما الذي يجب أن أركز عليه الآن؟"))

    prompt = build_player_chat_prompt({"messages": messages})

    assert prompt[-1].content == "ما الذي يجب أن أركز عليه الآن؟"
    assert len(prompt) - 1 < 16
    assert prompt_token_count(prompt) <= HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING
