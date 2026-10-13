"""Focused replay and cap-decision checks for paired trial usage (#262)."""

from datetime import UTC, datetime
from pathlib import Path

from service import model_limits
from service.trial_usage_measurement import decide_trial_cap, replay_trial_day
from tests.eval.run_trial_usage_measurement import load_workloads


def test_trial_workload_pairs_are_synthetic_and_pending_owner_review():
    fixture = load_workloads(
        Path(__file__).parent / "eval" / "datasets" / "trial_usage_workloads_262.json"
    )

    assert fixture["facts_are_synthetic"] is True
    assert fixture["status"] == "pending_owner_review"
    assert {pair["task_type"] for pair in fixture["pairs"]} == {
        "short_question",
        "long_history",
        "arabic_english_mixing",
        "program_action",
        "coach_analysis",
    }
    assert all(pair["review_status"] == "pending_owner_review" for pair in fixture["pairs"])
    assert fixture["ordinary_day_assumptions"]["launch_request_counts"] is False


def test_shared_day_replay_counts_every_call_and_keeps_checkpoint_exempt(monkeypatch):
    monkeypatch.setattr(model_limits, "daily_token_limit", lambda: 100)
    monkeypatch.setattr(model_limits, "request_limit_per_minute", lambda: 0)
    moment = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
    turns = [
        {
            "case_id": "player-multi-call",
            "role": "player",
            "purpose": "chat",
            "calls": [
                {"model": "deepseek-ai/DeepSeek-V4-Flash", "input_tokens": 20, "output_tokens": 10, "estimated": False},
                {"model": "deepseek-ai/DeepSeek-V4-Flash", "input_tokens": 10, "output_tokens": 10, "estimated": False},
            ],
        },
        {
            "case_id": "checkpoint-review",
            "role": "player",
            "purpose": "checkpoint_review",
            "calls": [
                {"model": "deepseek-ai/DeepSeek-V4-Flash", "input_tokens": 900, "output_tokens": 100, "estimated": False}
            ],
        },
        {
            "case_id": "coach-analysis",
            "role": "coach",
            "purpose": "coach_assistant",
            "calls": [
                {"model": "deepseek-ai/DeepSeek-V4-Flash", "input_tokens": 30, "output_tokens": 20, "estimated": False}
            ],
        },
        {
            "case_id": "next-player-turn",
            "role": "player",
            "purpose": "chat",
            "calls": [
                {"model": "deepseek-ai/DeepSeek-V4-Flash", "input_tokens": 1, "output_tokens": 1, "estimated": False}
            ],
        },
    ]

    replay = replay_trial_day(turns, account_id="dual-capability-account", now=moment)

    assert replay["first_refusal"] == {
        "turn_index": 3,
        "case_id": "next-player-turn",
        "role": "player",
        "kind": "daily_tokens",
        "tokens_before_refusal": 100,
        "measured_turn_tokens": 2,
    }
    assert replay["admitted_role_counts"] == {"coach": 1, "player": 2}
    assert replay["daily_tokens_after_replay"] == 100
    assert replay["potential_tokens_if_all_scheduled_turns_admitted"] == 102
    assert replay["minimum_limit_to_admit_all_scheduled_turns"] == 101
    assert replay["persisted_call_count"] == 4
    assert replay["estimated_call_count"] == 0
    assert replay["persisted_cost_usd"] > 0

    pending = decide_trial_cap(
        {"first_refusal": None},
        replay,
        current_limit=100,
        ordinary_use_day=False,
        equivalent_successful_work=False,
    )
    assert pending == {
        "setting": 100,
        "decision": "retain",
        "reason": "The replay is not yet an eligible ordinary-use equivalent-work day.",
        "trigger_met": False,
    }

    eligible = decide_trial_cap(
        {"first_refusal": None},
        replay,
        current_limit=100,
        ordinary_use_day=True,
        equivalent_successful_work=True,
    )
    assert eligible["decision"] == "raise"
    assert eligible["setting"] == 101
    assert eligible["trigger_met"] is True
