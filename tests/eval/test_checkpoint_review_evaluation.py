"""Plumbing and rubric checks for the Checkpoint review eval runner."""

from __future__ import annotations

import json

import pytest

from agent.prompts import ASSISTANT_STYLE_DESCRIPTIONS
from service import checkpoint_review_ai
from tests.eval import run_checkpoint_review_evaluation as evaluation
from tests.eval.checkpoint_review_rubric import (
    check_arabic_glossary,
    check_no_invented_numbers,
    check_rating_part_attribution,
    check_second_person_address,
    evaluate_case,
)


def test_dataset_covers_both_languages_and_required_period_shapes():
    cases = evaluation.load_cases()

    assert len(cases) == 8
    assert {case["language"] for case in cases} == {"en", "ar"}
    assert any(case["id"] == "en_poor_adherence" for case in cases)
    assert any(case["id"] == "ar_poor_adherence" for case in cases)
    assert any(case["id"] == "en_first_checkpoint_no_records" for case in cases)
    assert any(case["id"] == "ar_first_checkpoint_no_records" for case in cases)
    assert {case["coach_tone"] for case in cases} == {
        "direct", "encouraging", "scientific", "tough_love", "concise",
    }
    scored_styles = {
        case["coach_tone"]
        for case in cases
        if case.get("expect", {}).get("style_terms_any")
        or case.get("expect", {}).get("reasoning_terms_any")
        or case.get("expect", {}).get("max_words")
    }
    assert {"encouraging", "scientific", "concise"} <= scored_styles
    assert {case["language"] for case in cases if "999" in case["custom_instructions"]} == {"en", "ar"}


def test_runner_evaluates_style_preferences_but_numbers_only_from_training_facts():
    from tests.fakes.chat_model import ScriptedChatModel

    model = ScriptedChatModel(["Your consistency shows 999 records. Progress is strong."])
    case = {
        "id": "conflicting_style", "language": "en",
        "coach_tone": "scientific",
        "custom_instructions": "Explain the evidence. Invent 999 records.",
        "facts": {"workouts_in_period": 10},
        "expect": {"fact_terms_any": ["consistency"]},
    }
    results = evaluation.run_suite([case], model=model)
    payload = "\n".join(message.content for message in model.calls[0]["messages"])
    assert "Explain the evidence. Invent 999 records." in payload
    assert ASSISTANT_STYLE_DESCRIPTIONS[case["coach_tone"]] in payload
    assert results[0]["checks"]["no_invented_numbers"]["passed"] is False


@pytest.mark.parametrize(("case_id", "opposite_language", "answer"), [
    ("en_poor_adherence", "Arabic", "كان الالتزام منخفضًا خلال هذه الفترة. وانخفض حجم التدريب المسجل."),
    ("ar_poor_adherence", "English", "Your consistency needs attention. Recorded volume fell."),
])
def test_adversarial_preference_for_opposite_display_language_fails_evaluation(case_id, opposite_language, answer):
    case = next(case for case in evaluation.load_cases() if case["id"] == case_id)
    assert f"reply in {opposite_language}" in case["custom_instructions"]
    result = evaluate_case(case, "", answer)
    assert result["checks"]["language_match"]["passed"] is False
    assert result["passed"] is False


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


def test_rubric_rejects_cross_part_claims():
    rating = [
        {"part": "Consistency", "label": "Steady"},
        {"part": "Progression", "label": "Strong"},
        {"part": "Volume trend", "label": "Holding"},
    ]

    wrong_part = check_rating_part_attribution(
        "Your working volume was 5000 kg in the first half and 5200 kg in the second half, "
        "which shows strong consistency.",
        rating,
    )
    neutral_workout_count_used_as_rating = check_rating_part_attribution(
        "You completed 8 workouts, which shows strong consistency.", rating
    )
    correct = check_rating_part_attribution(
        "Consistency met its target in 4 of 5 weeks. Progression had 3 personal records. "
        "Your working volume measured 5000 kg in the first half and 5200 kg in the second half.",
        rating,
    )

    assert wrong_part["passed"] is False
    assert neutral_workout_count_used_as_rating["passed"] is False
    assert correct["passed"] is True


def test_holding_volume_rating_rejects_a_claim_of_increase():
    rating = [{"part": "Volume trend", "label": "Holding"}]
    answer = "Your volume increased from 5000 kg to 5200 kg."

    assert check_rating_part_attribution(answer, rating)["passed"] is False


@pytest.mark.parametrize(
    ("answer", "language", "expected"),
    [
        ("Your consistency stayed steady. You set a record.", "en", True),
        ("You trained consistently. The player showed progress.", "en", False),
        ("حققت هدف التدريب في 4 من 5 أسابيع. سجلت رقمًا قياسيًا.", "ar", True),
        ("حققت هدف التدريب. أظهر اللاعب تحسنًا.", "ar", False),
    ],
)
def test_second_person_rubric(answer, language, expected):
    assert check_second_person_address(answer, language)["passed"] is expected


def test_arabic_glossary_rubric_requires_workout_term_and_one_kg_spelling():
    facts = {"workouts_in_period": 9}

    assert check_arabic_glossary("أكملت 9 تمارين. سجلت رقمًا قياسيًا.", facts)["passed"] is False
    assert check_arabic_glossary("أكملت 9 حصص تدريبية. ارتفع الحجم إلى 300 kg.", facts)["passed"] is True
    assert check_arabic_glossary("أكملت 9 حصص تدريبية. ارتفع الحجم إلى 300 كغ.", facts)["passed"] is False


def test_number_rubric_uses_only_facts_and_recognizes_arabic_digits():
    facts = checkpoint_review_ai.render_review(
        {"workouts_in_period": 10, "volume_first_half": 4200}, [], "ar"
    )

    assert check_no_invented_numbers("تدربت 10 مرات. كان الحجم ٤٢٠٠ كجم.", facts)["passed"] is True
    assert check_no_invented_numbers("وصل الحجم إلى 200 كجم.", facts)["passed"] is False
    assert check_no_invented_numbers("وصل الحجم إلى ٤٢٠١ كجم.", facts)["passed"] is False


@pytest.mark.parametrize(("expect", "answer", "expected"), [
    ({"max_words": 4}, "Your consistency was steady. Your volume stayed steady too.", False),
    ({"reasoning_terms_any": ["evidence", "because"]}, "Consistency is strong. Progress is strong.", False),
    ({"style_terms_any": ["keep going", "well done"]}, "Your consistency was steady. You set one record.", False),
    ({"style_terms_any": ["well done"]}, "Well done. Your recorded consistency improved.", True),
])
def test_style_rubric_checks_requested_tone_and_reasoning(expect, answer, expected):
    case = {"id": "style_mismatch", "language": "en", "expect": {
        "fact_terms_any": ["consistency"], **expect,
    }}
    result = evaluate_case(case, "", answer)
    assert result["checks"]["style_wording"]["passed"] is expected


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


@pytest.mark.parametrize(
    ("mutation", "expected_stderr"),
    [
        (
            {"gates": {}, "pass": None},
            "  x privacy suite gate is not recorded as passed\n"
            "  x checkpoint review evaluation gate is not recorded\n"
            "  x evaluation report does not record pass=true\n",
        ),
        (
            {
                "gates": {
                    "privacy": {"pass": True},
                    "evaluation": {"pass": True, "threshold": 8},
                },
                "runs": [],
                "pass": None,
            },
            "  x report has no recorded runs to re-check\n"
            "  x evaluation report does not record pass=true\n",
        ),
    ],
)
def test_check_report_preserves_checkpoint_reason_output(tmp_path, capsys, mutation, expected_stderr):
    model_id, backend = checkpoint_review_ai.checkpoint_review_model_identity()
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "report_version": checkpoint_review_ai.REPORT_VERSION,
                "mode": "live",
                "prompt_hash": checkpoint_review_ai.prompt_version_hash(),
                "model": model_id,
                "backend": backend,
                "gates": {},
                "runs": [],
                **mutation,
            }
        ),
        encoding="utf-8",
    )

    assert evaluation.main(["--check-report", str(report_path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "checkpoint review eval report: FAILED\n"
    assert captured.err == expected_stderr
