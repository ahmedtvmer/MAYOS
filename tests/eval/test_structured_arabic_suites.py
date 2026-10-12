"""Hermetic contract tests for the #199 model-gate suites."""

import json

import pytest

from tests.eval import run_evaluation
from tests.eval.parity_gate import RetryPolicy, evaluate_report
from tests.eval.suites import arabic_replies, structured_output


def test_hermetic_gate_includes_both_suites_and_marks_egyptian_unreviewed():
    report = run_evaluation._hermetic_report()

    passed, reasons, summaries = evaluate_report(report, run_evaluation.SUITES)
    summaries_by_name = {summary["name"]: summary for summary in summaries}

    assert passed is True
    assert reasons == []
    assert summaries_by_name["structured_output"]["score"] == 10
    assert summaries_by_name["arabic_replies"]["mostly_arabic"]["passed"] is True
    assert summaries_by_name["arabic_replies"]["egyptian_register"]["status"] == "unreviewed"
    assert summaries_by_name["arabic_replies"]["egyptian_register"]["passed"] is None
    assert summaries_by_name["arabic_replies"]["unreviewed_count"] == 1


def test_split_plan_cases_generate_schema_valid_programs_from_real_catalog(fresh_store):
    from agent.program_rules import get_default_split

    cases = structured_output._load_cases()
    for case in cases["split_plans"]:
        plan = get_default_split(case["frequency"], case["gender"])
        program = structured_output._generate_split_program(plan, case, fresh_store)

        assert structured_output._validate_generated_program(program, case["frequency"], fresh_store) == []


def test_substitution_cases_resolve_real_program_and_library_entries(fresh_store):
    from agent.assistant_graph import SubstitutionResolution

    cases = structured_output._load_cases()
    for case in cases["substitution_resolutions"]:
        _program, source_id = structured_output._case_program(case, fresh_store)
        resolution = SubstitutionResolution(
            source_exercise=case["program_exercise"], target_exercise=case["expected_target"]
        )
        evidence = {"source_exercise_id": source_id, "expected_target": case["expected_target"]}

        assert structured_output._validate_substitution(case, resolution, evidence, fresh_store, False) == []


def test_overlong_raw_split_plan_fails_even_when_generation_trims_it(fresh_store):
    from agent.program_rules import get_default_split

    case = structured_output._load_cases()["split_plans"][0]
    raw_plan = get_default_split(case["frequency"] + 1, case["gender"])
    record = structured_output._run_split_case(
        case, ParsedStructuredModel(raw_plan), RetryPolicy(max_attempts=1), fresh_store
    )
    report = run_evaluation._hermetic_report()
    entry = report["suite_results"]["structured_output"]
    entry["cases"][0] = record

    summary, reasons = structured_output.SUITE.validate(entry, report)

    assert len(record["parsed_output"]["days"]) == case["frequency"] + 1
    assert len(record["generated_program"]["days"]) == case["frequency"]
    assert summary["cases"][0]["passed"] is False
    assert any("required sanitizing" in reason for reason in reasons)


class ParsedStructuredModel:
    def __init__(self, parsed):
        self.parsed = parsed

    def with_structured_output(self, _schema, **_options):
        return self

    def bind(self, **_options):
        return self

    def invoke(self, _prompt):
        from langchain_core.messages import AIMessage

        return {
            "raw": AIMessage(content="", response_metadata={"finish_reason": "stop"}),
            "parsed": self.parsed,
            "parsing_error": None,
        }


@pytest.mark.parametrize("split_request", ["standard", "full body"])
def test_split_dataset_rejects_deterministic_requests(tmp_path, monkeypatch, split_request):
    payload = json.loads(structured_output.DATASET.read_text(encoding="utf-8"))
    payload["split_plans"][0]["request"] = split_request
    dataset_path = tmp_path / "cases.json"
    dataset_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(structured_output, "DATASET", dataset_path)

    summary = structured_output.SUITE.run_hermetic(None)

    assert summary["passed"] is False
    assert any(
        "split-01" in reason and "bypasses the player model" in reason
        for reason in summary["failure_reasons"]
    )


def test_summary_comparison_does_not_mutate_original_failure_reasons():
    original_reasons = ["existing validation reason"]
    summary = {
        "score": 1,
        "total": 1,
        "bar": {"kind": "count", "value": 1},
        "passed": True,
        "failure_reasons": original_reasons,
        "cases": [],
    }
    recorded = {**summary, "score": 0}

    compared, reasons = structured_output._compare_summary(recorded, summary, original_reasons)

    assert original_reasons == ["existing validation reason"]
    assert reasons is not original_reasons
    assert compared["failure_reasons"] is not original_reasons


def test_arabic_player_context_seeds_training_program_and_profile(fresh_store):
    from tests.eval.run_arabic_evaluation import load_scenarios, seed_arabic_player_context

    scenario = load_scenarios()["cases"]["ar-prog-03"]
    with fresh_store.open_ledger("issue_199_arabic_seed") as ledger:
        seed_arabic_player_context(fresh_store, ledger, scenario)
        program = ledger.get_active_program()
        profile = ledger.get_player_profile()

    assert program is not None
    assert program.weekly_frequency == scenario["seed_program"]["weekly_frequency"]
    assert profile["weekly_frequency"] == program.weekly_frequency
    assert profile["equipment_access"] == "Commercial gym"


def test_structured_output_truncation_fails_the_case_and_ten_case_bar():
    from agent.ProgramState import DynamicSplitPlan

    report = run_evaluation._hermetic_report()
    call = structured_output._call_structured(
        LengthFinishedModel(), DynamicSplitPlan, [], RetryPolicy(max_attempts=1), 1200
    )
    report["suite_results"]["structured_output"]["cases"][0] = {
        "case_id": "split-01",
        "kind": "split_plan",
        **structured_output._call_record(call),
    }

    summary, reasons = structured_output.SUITE.validate(
        report["suite_results"]["structured_output"], report
    )

    assert summary["score"] == 9
    assert summary["passed"] is False
    assert any("truncated" in reason for reason in reasons)


class LengthFinishedModel:
    def with_structured_output(self, _schema, **_options):
        return self

    def bind(self, **_options):
        return self

    def invoke(self, _prompt):
        from langchain_core.messages import AIMessage

        return {
            "raw": AIMessage(content="", response_metadata={"finish_reason": "length"}),
            "parsed": None,
            "parsing_error": None,
        }


def test_reviewed_calibration_is_bound_to_exact_ten_reply_sample(tmp_path, monkeypatch):
    report, report_path = _prepare_sample_report(tmp_path, monkeypatch)
    sample_path = arabic_replies.write_review_sample(report_path)
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    _assert_balanced_pending_sample(sample, tmp_path)
    _mark_sample_reviewed(tmp_path)
    arabic_report = _arabic_only_report(report)
    _assert_reviewed_measure(arabic_report)

    other_player_report = {**arabic_report, "player_model": "another-player-model"}
    changed_model_summary, _ = arabic_replies.SUITE.validate(
        other_player_report["suite_results"]["arabic_replies"], other_player_report
    )
    assert changed_model_summary["egyptian_register"]["status"] == "unreviewed"

    sample["examples"][0]["assistant_reply"] += "!"
    sample_path.write_text(json.dumps(sample), encoding="utf-8")
    pending_summary, _ = arabic_replies.SUITE.validate(
        arabic_report["suite_results"]["arabic_replies"], arabic_report
    )
    assert pending_summary["egyptian_register"]["status"] == "unreviewed"


def _prepare_sample_report(tmp_path, monkeypatch):
    monkeypatch.setattr(arabic_replies, "REVIEW_DIR", tmp_path)
    monkeypatch.setattr(arabic_replies, "REVIEW_FILE", tmp_path / "REVIEW.json")
    monkeypatch.setattr(arabic_replies, "SAMPLE_FILE", tmp_path / "sample.json")
    report = run_evaluation._hermetic_report()
    report["mode"] = "live"
    report_path = tmp_path / "gate.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report, report_path


def _assert_balanced_pending_sample(sample, tmp_path):
    assert len(sample["examples"]) == 10
    assert [example["expected_register"] for example in sample["examples"]].count("egyptian") == 5
    assert [example["expected_register"] for example in sample["examples"]].count("standard") == 5
    review = json.loads((tmp_path / "REVIEW.json").read_text(encoding="utf-8"))
    assert review["review_status"] == "pending"


def _mark_sample_reviewed(tmp_path):
    review = json.loads((tmp_path / "REVIEW.json").read_text(encoding="utf-8"))
    review.update(
        {"review_status": "reviewed", "reviewed_by": "test reviewer", "reviewed_on": "2026-10-12"}
    )
    (tmp_path / "REVIEW.json").write_text(json.dumps(review), encoding="utf-8")


def _arabic_only_report(report):
    return {
        "mode": "hermetic",
        "player_model": report["player_model"],
        "judges": report["judges"],
        "suite_results": {"arabic_replies": report["suite_results"]["arabic_replies"]},
    }


def _assert_reviewed_measure(arabic_report):
    passed, reasons, summaries = evaluate_report(arabic_report, (arabic_replies.SUITE,))

    assert passed is True
    assert reasons == []
    assert summaries[0]["egyptian_register"]["status"] == "reviewed"
    assert summaries[0]["egyptian_register"]["passed"] is True
