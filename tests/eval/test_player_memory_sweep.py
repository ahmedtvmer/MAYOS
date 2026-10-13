import pytest
from langchain_core.messages import AIMessageChunk, SystemMessage

from tests.eval import run_evaluation
from tests.eval.run_player_memory_sweep import (
    STATIC_SYSTEM_CORE,
    StreamingInvokeAdapter,
    load_memory_cases,
    render_markdown,
    summarize_usage,
)


def test_memory_sweep_fixtures_reach_beyond_six_and_ten_messages():
    six_message_case, ten_message_case = load_memory_cases()
    first_reply = six_message_case["history"][1]["content"]
    second_reply = ten_message_case["history"][1]["content"]

    assert len(six_message_case["history"]) == 8
    assert "22 kg per hand for 8 reps" in first_reply
    assert first_reply.index("22 kg per hand for 8 reps") > 500
    assert len(ten_message_case["history"]) == 14
    assert "18 kg per hand for 8 reps" in second_reply
    assert second_reply.index("18 kg per hand for 8 reps") > 500


def test_eval_generation_and_judge_prompts_receive_synthetic_history(monkeypatch):
    case = load_memory_cases()[0]
    captured = {}

    def capture_state(state):
        captured["state"] = state
        return {"response_content": "A concise remembered answer."}

    monkeypatch.setattr(run_evaluation, "_invoke_assistant_graph", capture_state)
    reply, _seconds = run_evaluation._generate_reply(case)

    assert reply == "A concise remembered answer."
    assert [message.type for message in captured["state"]["messages"]] == [
        "human",
        "ai",
        "human",
        "ai",
        "human",
        "ai",
        "human",
        "ai",
        "human",
    ]
    judged_prompt = run_evaluation._judge_messages(case, reply)[1].content
    assert "[EARLIER CONVERSATION]" in judged_prompt
    assert "22 kg per hand for 8 reps" in judged_prompt


def test_usage_summary_prices_cached_tokens_and_reports_cached_share():
    summary = summarize_usage(
        [
            {
                "model": "deepseek-ai/DeepSeek-V4-Flash",
                "input_tokens": 1_000_000,
                "cached_input_tokens": 200_000,
                "output_tokens": 100,
                "estimated": False,
            }
        ],
        turn_count=2,
    )

    assert summary["cost_usd"] == pytest.approx(0.075618)
    assert summary["cost_per_turn_usd"] == pytest.approx(0.037809)
    assert summary["cached_input_share"] == pytest.approx(0.2)
    assert summary["estimated_calls"] == 0


def test_streaming_adapter_measures_player_reply_first_content_chunk():
    class ChunkedModel:
        def stream(self, _prompt):
            yield AIMessageChunk(content="Remembered ")
            yield AIMessageChunk(content="answer.")

    ttft_samples = []
    adapter = StreamingInvokeAdapter(ChunkedModel(), ttft_samples)
    response = adapter.invoke([SystemMessage(content=STATIC_SYSTEM_CORE)])

    assert response.content == "Remembered answer."
    assert len(ttft_samples) == 1
    assert ttft_samples[0] >= 0


def test_markdown_report_includes_both_judges_and_memory_measurements():
    markdown = render_markdown(
        {
            "generated_at": "2026-10-13T00:00:00+00:00",
            "player_model": "deepseek-ai/DeepSeek-V4-Flash",
            "judges": [{"model": "judge-one"}, {"model": "judge-two"}],
            "settings": [
                {
                    "label": "window-6_truncate-500",
                    "window_size": 6,
                    "assistant_reply_max_chars": 500,
                    "coaching_qa": {
                        "both_judges_passed_cases": 40,
                        "total_judged_cases": 54,
                        "judge_scores": {
                            "judge_1": {"passed_cases": 44, "total_cases": 54},
                            "judge_2": {"passed_cases": 42, "total_cases": 54},
                        },
                    },
                    "arabic_replies": {
                        "mostly_arabic_cases": 30,
                        "total_cases": 33,
                        "judge_scores": {
                            "judge_1": {"expected_register_matches": 27, "total_cases": 33},
                            "judge_2": {"expected_register_matches": 29, "total_cases": 33},
                        },
                    },
                    "measurements": {
                        "cost_per_turn_usd": 0.001,
                        "cost_change_vs_baseline_percent": 0.0,
                        "median_ttft_seconds": 2.1,
                        "ttft_delta_vs_baseline_seconds": 0.0,
                        "cached_input_share": 0.4,
                    },
                }
            ],
        }
    )

    assert "judge-one, judge-two" in markdown
    assert "44/54 / 42/54" in markdown
    assert "27/33 / 29/33" in markdown
    assert "$0.001000" in markdown
    assert "2.100s" in markdown
    assert "40.0%" in markdown
