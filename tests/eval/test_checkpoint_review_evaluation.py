"""Plumbing and rubric checks for the Checkpoint review eval runner."""

from __future__ import annotations

import json

from service import checkpoint_review_ai
from tests.eval import run_checkpoint_review_evaluation as evaluation
from tests.eval.checkpoint_review_rubric import check_no_invented_numbers, evaluate_case


def test_dataset_covers_both_languages_and_required_period_shapes():
    cases = evaluation.load_cases()

    assert len(cases) == 8
    assert {case["language"] for case in cases} == {"en", "ar"}
    assert any(case["id"] == "en_poor_adherence" for case in cases)
    assert any(case["id"] == "ar_poor_adherence" for case in cases)
    assert any(case["id"] == "en_first_checkpoint_no_records" for case in cases)
    assert any(case["id"] == "ar_first_checkpoint_no_records" for case in cases)


def test_rubric_rejects_invented_numbers_wrong_language_and_medical_advice():
    case = {
        "id": "bad_answer",
        "language": "en",
        "expect": {"fact_terms_any": ["consistency"]},
    }
    prompt = "Consistency: Needs attention\nWeeks that met the training target: 1"
    answer = "Your consistency was strong at 99 weeks. You should take painkillers."

    result = evaluate_case(case, prompt, answer)

    assert result["checks"]["no_invented_numbers"]["passed"] is False
    assert result["checks"]["no_medical_advice"]["passed"] is False
    assert result["checks"]["sentence_count"]["passed"] is True


def test_number_rubric_uses_only_facts_and_recognizes_arabic_digits():
    facts = checkpoint_review_ai.render_review(
        {"workouts_in_period": 10, "volume_first_half": 4200}, [], "ar"
    )

    assert check_no_invented_numbers("تدربت 10 مرات. كان الحجم ٤٢٠٠ كجم.", facts)["passed"] is True
    assert check_no_invented_numbers("وصل الحجم إلى 200 كجم.", facts)["passed"] is False
    assert check_no_invented_numbers("وصل الحجم إلى ٤٢٠١ كجم.", facts)["passed"] is False


def test_mock_runner_writes_a_report_that_the_live_gate_refuses(tmp_path):
    report_path = tmp_path / "checkpoint_review_mock.json"

    assert evaluation.main(["--mock", "--write-report", str(report_path), "--no-privacy"]) == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mode"] == "mock"
    assert report["prompt_hash"] == checkpoint_review_ai.prompt_version_hash()
    model_id, backend = checkpoint_review_ai.checkpoint_review_model_identity()
    assert report["model"] == model_id
    assert report["backend"] == backend
    assert len(report["runs"]) == 8
    assert checkpoint_review_ai.validate_report(report)[0] is False
