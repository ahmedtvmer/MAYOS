import json
import math
from pathlib import Path

from agent.fitness_abbreviations import FITNESS_ABBREVIATIONS
from utils import player_output_budgets


REPORT_PATH = Path(__file__).parents[1] / "reports" / "player_output_budgets.json"
SPLIT_MEASUREMENT_PATH = Path(__file__).parents[1] / "reports" / "issue_406_split_plan_measurement.json"
STRUCTURED_CALL_SITES = (
    "intent_routing",
    "abbreviation_expansion",
)


def test_structured_player_budgets_cover_measured_maxima():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    for call_site in STRUCTURED_CALL_SITES:
        measured = report["call_sites"][call_site]
        budget = player_output_budgets.CALL_SITE_BUDGETS[call_site]

        if measured["max_completion_tokens"] is None:
            assert measured["n"] == 0, call_site
            continue
        assert budget >= measured["max_completion_tokens"], call_site
        assert measured["finish_reason_length_count"] == 0, call_site
        assert measured["configured_budget_tokens"] == budget, call_site

    substitution = report["call_sites"]["substitution_resolution"]
    assert (
        player_output_budgets.SUBSTITUTION_RESOLUTION_MAX_OUTPUT_TOKENS
        >= substitution["max_completion_tokens"]
    )
    assert player_output_budgets.SUBSTITUTION_RESOLUTION_MAX_OUTPUT_TOKENS == substitution["previous_budget_tokens"]


def test_dynamic_split_budget_covers_historical_and_issue_406_maxima():
    historical = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    targeted = json.loads(SPLIT_MEASUREMENT_PATH.read_text(encoding="utf-8"))
    historical_split = historical["call_sites"]["dynamic_split_plan"]
    measured_maximum = max(
        historical_split["max_completion_tokens"], targeted["max_completion_tokens"]
    )
    margin = max(16, math.ceil(measured_maximum * 0.25))
    expected_budget = math.ceil((measured_maximum + margin) / 8) * 8
    cases = targeted["cases"]

    assert historical_split["n"] == 11
    assert historical_split["p95_completion_tokens"] == 1019
    assert historical_split["max_completion_tokens"] == 1019
    assert targeted["all_valid"] is True
    assert targeted["max_completion_tokens"] == 654
    assert {case["case_id"] for case in cases} == {
        "split-01",
        "split-02",
        "split-03",
        "split-04",
        "split-05",
    }
    assert len(cases) == 7
    assert targeted["max_reported_reasoning_tokens"] is None
    assert any(
        probe["budget_tokens"] == 824 and probe["valid_plan"]
        for probe in targeted["budget_cap_probes"]
    )
    assert player_output_budgets.DYNAMIC_SPLIT_PLAN_MAX_OUTPUT_TOKENS == expected_budget


def test_report_covers_every_measured_player_call_site():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert set(report["call_sites"]) == set(player_output_budgets.CALL_SITE_BUDGETS)
    assert report["status"] in {"complete", "complete with reduced n"}
    target_n = report["sample_count_per_language_per_call_site"] * 2
    assert all(0 <= metrics["n"] <= target_n for metrics in report["call_sites"].values())
    assert all(metrics["n"] == len(metrics["samples"]) for metrics in report["call_sites"].values())
    assert report["sample_shortfalls"] == {
        site: target_n - metrics["n"]
        for site, metrics in report["call_sites"].items()
        if metrics["n"] < target_n
    }
    if report["sample_shortfalls"]:
        assert report["status"] == "complete with reduced n"
    else:
        assert report["status"] == "complete"
    for site, metrics in report["call_sites"].items():
        failures = report["failure_counts"][site]
        assert failures["samples_recorded"] == metrics["n"]
        assert failures["failed_or_unrecorded_requests"] == max(
            0, failures["requests_sent"] - metrics["n"] - failures["diagnostic_requests"]
        )
    assert {
        site: metrics["previous_budget_tokens"]
        for site, metrics in report["call_sites"].items()
    } == {
        "chat_reply": 200,
        "intent_routing": 200,
        "substitution_resolution": 200,
        "abbreviation_expansion": 200,
        "dynamic_split_plan": 1200,
        "checkpoint_review": 200,
    }
    assert report["call_sites"]["chat_reply"]["configured_budget_tokens"] == (
        player_output_budgets.PLAYER_CHAT_REPLY_MAX_OUTPUT_TOKENS
    )
    abbreviations = [sample["input"].lower() for sample in report["call_sites"]["abbreviation_expansion"]["samples"]]
    assert len(set(abbreviations)) == report["call_sites"]["abbreviation_expansion"]["n"]
    assert set(abbreviations) <= FITNESS_ABBREVIATIONS.keys()
    checkpoint = report["call_sites"]["checkpoint_review"]
    assert checkpoint["configured_budget_tokens"] == player_output_budgets.CHECKPOINT_REVIEW_MAX_OUTPUT_TOKENS
    assert checkpoint["measurement_status"] is None
    assert checkpoint["n_by_language"] == {"ar": 10, "en": 10}
    assert checkpoint["measured_output_n"] == checkpoint["n"] == 20
    assert report["checkpoint_diagnosis"]["message_roles"] == ["system", "user"]
    assert report["checkpoint_diagnosis"]["extracted_empty_count"] == 0
    assert checkpoint["p50_completion_tokens"] == 75
    assert checkpoint["p95_completion_tokens"] == 130
    assert checkpoint["max_completion_tokens"] == 139
    assert checkpoint["recommended_p95_plus_margin_tokens"] == 168
    assert checkpoint["finish_reason_length_count"] == 0


def test_measurement_budget_override_does_not_change_production_budget():
    production_budget = player_output_budgets.player_output_budget("intent_routing")

    with player_output_budgets.override_player_output_budgets({"intent_routing": 2400}):
        assert player_output_budgets.player_output_budget("intent_routing") == 2400

    assert player_output_budgets.player_output_budget("intent_routing") == production_budget
