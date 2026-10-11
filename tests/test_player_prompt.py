import hashlib
import json
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.prompts import render_assistant_style
from agent.player_prompt import (
    STATIC_SYSTEM_CORE,
    build_player_chat_prompt,
    message_role,
    prompt_token_count,
)


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
            STATIC_SYSTEM_CORE + "\nPreferred name (user-supplied data): Malak",
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
    )

    assert "Assistant style (" not in payload[0].content
    assert "[TRAINEE CONTEXT]\nVerified training facts." in payload[0].content
    assert "[PLAYER WEIGHT CONTEXT]\nWeight trend unavailable." in payload[0].content


def test_output_limit_response_keeps_its_original_literal():
    from agent import assistant_graph

    assert assistant_graph.OUTPUT_LIMIT_RESPONSE == (
        "I reached the response limit. Ask me to continue if you'd like more."
    )


def test_earlier_assistant_replies_are_truncated_to_500_characters():
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

    assert payload[2].content == "A" * 500


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
