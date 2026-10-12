"""Deterministic form-intake outcomes for the retired onboarding cases."""

import json
from pathlib import Path

import pytest

from service.intake import IntakeValidationError, validate_answer

FORM_CASES_PATH = Path(__file__).parent / "fixtures" / "form_intake_cases.json"
FORM_CASES = json.loads(FORM_CASES_PATH.read_text(encoding="utf-8"))
FORM_ANSWERS = {
    "gender": "female",
    "proportions": "long_legs",
    "age": 29,
    "height_cm": 168.0,
    "weight_kg": 64.5,
    "training_age_years": 3.0,
    "current_goal": "build glutes and legs",
    "long_term_goal": "stronger and more muscular",
    "weekly_frequency": 4,
    "equipment_access": "commercial gym",
    "injuries_or_limitations": "None",
    "stress_and_sleep": "moderate stress, 7 hours sleep",
}


@pytest.mark.parametrize("case", FORM_CASES, ids=lambda case: case["id"])
def test_converted_onboarding_cases_use_deterministic_form_validation(case):
    normalized = {name: validate_answer(name, value) for name, value in case.get("answers", {}).items()}

    assert normalized == case.get("normalized", {}), case["id"]
    for name, value in case.get("invalid_answers", {}).items():
        with pytest.raises(IntakeValidationError, match=case["errors"][name]):
            validate_answer(name, value)
    assert all(name not in normalized for name in case.get("optional_fields_absent", []))


def test_named_form_intake_accepts_a_complete_valid_answer_set():
    normalized = {name: validate_answer(name, answer) for name, answer in FORM_ANSWERS.items()}
    expected = {**FORM_ANSWERS, "equipment_access": "Commercial gym"}

    assert normalized == expected


@pytest.mark.parametrize(
    ("frequency", "valid"),
    [(0, False), (1, True), (5, True), (6, False)],
)
def test_form_weekly_frequency_accepts_only_one_through_five_days(frequency, valid):
    if valid:
        assert validate_answer("weekly_frequency", frequency) == frequency
    else:
        with pytest.raises(IntakeValidationError, match="weekly_frequency"):
            validate_answer("weekly_frequency", frequency)
