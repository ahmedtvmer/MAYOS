import pytest
from langchain_core.messages import AIMessageChunk, SystemMessage
from types import SimpleNamespace

from tests.eval import run_evaluation
from tests.eval.run_player_memory_sweep import (
    STATIC_SYSTEM_CORE,
    StreamingInvokeAdapter,
    check_expected_fact,
    load_memory_cases,
    render_markdown,
    run_memory_cases,
    select_best_scoring_setting,
    summarize_usage,
)


def test_memory_sweep_fixtures_cover_old_facts_long_replies_and_controls():
    cases = load_memory_cases()

    assert len(cases) == 8
    assert {case["memory_need"] for case in cases} == {
        "outside_window",
        "reply_tail",
        "control",
    }
    assert sum(case["memory_need"] == "control" for case in cases) == 2
    assert all(case.get("expected_fact") for case in cases)
    assert all(check_expected_fact(case, case["expected_fact"])["passed"] for case in cases)

    long_reply_cases = [case for case in cases if case["memory_need"] == "reply_tail"]
    assert len(long_reply_cases) >= 1
    assert all(
        any(
            message["role"] == "assistant"
            and message["content"].find(case["expected_fact"]) > 500
            for message in case["history"]
        )
        for case in long_reply_cases
    )


def test_expected_fact_check_ignores_case_and_punctuation_but_requires_full_fact():
    case = {"expected_fact": "76.4 kg"}

    assert check_expected_fact(case, "You mentioned 76.4 KG.")["passed"] is True
    assert check_expected_fact(case, "You mentioned 76 kg.")["passed"] is False


def test_memory_setting_runs_eight_fixtures_and_prints_case_progress(monkeypatch, capsys):
    judges = [{"name": "judge_1"}, {"name": "judge_2"}]
    context = SimpleNamespace(judges=judges, retry_policy=None)
    monkeypatch.setattr(
        run_evaluation,
        "_generate_reply",
        lambda case: (case["expected_fact"], 0.01),
    )
    monkeypatch.setattr(
        run_evaluation,
        "evaluate_case",
        lambda case, _reply, configured_judges, _policy: {
            "case_id": case["id"],
            "judges": {judge["name"]: {"passed": True} for judge in configured_judges},
            "passed": True,
        },
    )

    summary, turns = run_memory_cases(context, [], "window-6_truncate-500")

    assert summary["all_checks_passed_cases"] == 8
    assert summary["total_cases"] == 8
    assert len(turns) == 8
    assert "setting=window-6_truncate-500 case=synthetic-memory-reply-tail-row-en elapsed=" in capsys.readouterr().out


def test_best_scoring_setting_uses_baseline_as_a_tie_breaker():
    baseline = {
        "label": "window-6_truncate-500",
        "window_size": 6,
        "assistant_reply_max_chars": 500,
        "status": "complete",
        "memory_cases": {"all_checks_passed_cases": 6},
    }
    wider = {
        "label": "window-10_untruncated",
        "window_size": 10,
        "assistant_reply_max_chars": None,
        "status": "complete",
        "memory_cases": {"all_checks_passed_cases": 6},
    }

    assert select_best_scoring_setting([wider, baseline]) is baseline


def test_eval_generation_and_judge_prompts_receive_synthetic_history(monkeypatch):
    case = load_memory_cases()[2]
    captured = {}

    def capture_state(state):
        captured["state"] = state
        return {"response_content": "A concise remembered answer."}

    monkeypatch.setattr(run_evaluation, "_invoke_assistant_graph", capture_state)
    reply, _seconds = run_evaluation._generate_reply(case)

    assert reply == "A concise remembered answer."
    assert [message.type for message in captured["state"]["messages"]] == [
        "human" if message["role"] == "user" else "ai" for message in case["history"]
    ] + ["human"]
    judged_prompt = run_evaluation._judge_messages(case, reply)[1].content
    assert "[EARLIER CONVERSATION]" in judged_prompt
    assert case["expected_fact"] in judged_prompt


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


def test_markdown_report_includes_memory_scores_and_regression_separately():
    markdown = render_markdown(
        {
            "generated_at": "2026-10-13T00:00:00+00:00",
            "player_model": "deepseek-ai/DeepSeek-V4-Flash",
            "judges": [{"model": "judge-one"}, {"model": "judge-two"}],
            "expected_runtime": "About 25 minutes for six settings.",
            "settings": [
                {
                    "label": "window-6_truncate-500",
                    "window_size": 6,
                    "assistant_reply_max_chars": 500,
                    "memory_cases": {
                        "both_judges_passed_cases": 6,
                        "deterministic_fact_passed_cases": 7,
                        "all_checks_passed_cases": 5,
                        "total_cases": 8,
                        "judge_scores": {
                            "judge_1": {"passed_cases": 7, "total_cases": 8},
                            "judge_2": {"passed_cases": 6, "total_cases": 8},
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
            "regression": {
                "status": "complete",
                "best_scoring_setting": "window-6_truncate-500",
                "coaching_qa": {"both_judges_passed_cases": 40, "total_judged_cases": 50},
                "arabic_replies": {"mostly_arabic_cases": 30, "total_cases": 33},
            },
        }
    )

    assert "judge-one, judge-two" in markdown
    assert "7/8 / 6/8" in markdown
    assert "5/8" in markdown
    assert "Regression pass" in markdown
    assert "50" in markdown
    assert "$0.001000" in markdown
    assert "2.100s" in markdown
    assert "40.0%" in markdown
