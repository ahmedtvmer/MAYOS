"""Deterministic debrief directives and the retired judge fixtures."""

import json
from pathlib import Path

import pytest

from agent.debrief import arabic_count_phrase, generate_session_debrief

EXERCISES = [{"name": "Squat", "volume_load": 1000.0, "current_e1rm": 150.0, "e1rm_delta": 0.0}]
DEBRIEF_CASES = Path(__file__).parent / "eval" / "datasets" / "debrief_cases.json"
GENERALIZATION_CASES = Path(__file__).parent / "eval" / "datasets" / "generalization_cases.json"


def _debrief(fatigue_info):
    return generate_session_debrief(
        split_name="Lower",
        readiness=1,
        session_notes="",
        exercise_summaries=EXERCISES,
        fatigue_info=fatigue_info,
    )


def test_active_deload_renders_exact_volume_cut():
    text = _debrief(
        {
            "deload_recommended": True,
            "volume_multiplier": 0.5,
            "intensity_cap_rpe": 7.0,
            "severity": "HIGH",
            "reason": "Acute readiness floor",
        }
    )
    assert "Cut sets by 50%" in text
    assert "cap at RIR ≥ 3" in text


def test_active_deload_nonstandard_multiplier():
    text = _debrief({"deload_recommended": True, "volume_multiplier": 0.6, "intensity_cap_rpe": 8.0})
    assert "Cut sets by 40%" in text
    assert "cap at RIR ≥ 2" in text


def test_active_deload_missing_or_invalid_multiplier_never_fabricates():
    for bad in ({}, {"volume_multiplier": None}, {"volume_multiplier": "abc"}, {"volume_multiplier": 0}, {"volume_multiplier": 1.0}, {"volume_multiplier": 1.5}):
        text = _debrief({"deload_recommended": True, "intensity_cap_rpe": 7.0, **bad})
        assert "Cut sets by" not in text
        assert "Reduce sets" in text
        assert "cap at RIR ≥ 3" in text


def test_inactive_deload_content_unaffected():
    text = _debrief({"deload_recommended": False})
    assert "DELOAD" not in text
    assert "Cut sets by" not in text
    assert "RPE cap" not in text
    assert "cap at RIR" not in text
    assert "Hold load" in text or "Advance load" in text


def test_missing_intensity_cap_never_fabricates_a_number():
    text = _debrief({"deload_recommended": True, "volume_multiplier": 0.5, "intensity_cap_rpe": None})
    assert "Cut sets by 50%" in text
    assert "cap at" not in text


def test_arabic_deload_summary_keeps_rir_kg_and_western_digits():
    output = generate_session_debrief(
        "Upper",
        3,
        "أشعر بإرهاق في الكتف",
        [{
            "name": "Bench Press",
            "volume_load": 2500.0,
            "current_e1rm": 100.0,
            "e1rm_delta": 2.0,
        }],
        fatigue_info={
            "deload_recommended": True,
            "volume_multiplier": 0.5,
            "intensity_cap_rpe": 7.0,
            "severity": "HIGH",
            "reason": "Readiness floor",
        },
        total_tonnage=2500.0,
        display_language="ar",
        pr_events=[
            {
                "exercise_id": "bench_press",
                "name": "Bench Press",
                "record_type": "max_weight",
                "value": 100.0,
                "prev_value": 95.0,
                "reps": 5,
            },
            {
                "exercise_id": "bench_press",
                "name": "Bench Press",
                "record_type": "max_e1rm",
                "value": 126.4,
                "prev_value": 100.0,
                "reps": 5,
            },
            {
                "exercise_id": "bench_press",
                "name": "Bench Press",
                "record_type": "most_reps",
                "value": 12,
                "prev_value": 8,
                "reps": 12,
            },
        ],
    )

    assert "تخفيف التدريب" in output
    assert "خفّض مجموعات التدريب بنسبة" in output
    assert "\u206650%\u2069" in output
    assert "بحيث لا يقل \u2068RIR\u2069 عن \u20663\u2069" in output
    assert "\u2068Bench Press\u2069" in output
    assert "\u2066(+2.5 kg)\u2069" in output
    assert "2,500.0 kg" in output
    assert "أشعر بإرهاق في الكتف" in output
    assert "رقم قياسي شخصي جديد" in output
    assert "أعلى وزن" in output
    assert "\u20665\u2069 تكرارات" in output
    assert "\u2068e1RM\u2069 \u2066126.4 kg\u2069" in output
    assert "أعلى عدد من التكرارات: \u206612\u2069 تكرارًا" in output
    assert not any(digit in output for digit in "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹")


def test_arabic_summary_labels_baseline_and_maintained_e1rm_clearly():
    output = generate_session_debrief(
        "Upper",
        3,
        "",
        [
            {"name": "Deadlift", "current_e1rm": 100.0},
            {"name": "Bench Press", "current_e1rm": 120.0, "e1rm_delta": 0.0},
        ],
        display_language="ar",
    )

    assert (
        "- \u2068Deadlift\u2069: خط الأساس لـ \u2068e1RM\u2069: "
        "\u2066100.0 kg\u2069. ثبّت الحمل."
    ) in output
    assert (
        "- \u2068Bench Press\u2069: \u2068e1RM\u2069 ثابت عند "
        "\u2066120.0 kg\u2069 \u2066(+0.0 kg)\u2069. ثبّت الحمل."
    ) in output


def test_arabic_count_phrase_uses_plural_for_zero():
    assert arabic_count_phrase(0, "training_set") == "0 مجموعات تدريب"
    assert arabic_count_phrase(0, "repetition") == "0 تكرارات"


@pytest.mark.parametrize(
    ("count", "training_sets", "repetitions", "repetitions_after_preposition"),
    [
        (1, "مجموعة تدريب واحدة", "تكرار واحد", "تكرار واحد"),
        (2, "مجموعتا تدريب", "تكراران", "تكرارين"),
        (3, "3 مجموعات تدريب", "3 تكرارات", "3 تكرارات"),
        (10, "10 مجموعات تدريب", "10 تكرارات", "10 تكرارات"),
        (11, "11 مجموعة تدريب", "11 تكرارًا", "11 تكرارًا"),
        (100, "100 مجموعة تدريب", "100 تكرار", "100 تكرار"),
        (101, "101 مجموعة تدريب", "101 تكرار", "101 تكرار"),
        (103, "103 مجموعات تدريب", "103 تكرارات", "103 تكرارات"),
        (111, "111 مجموعة تدريب", "111 تكرارًا", "111 تكرارًا"),
    ],
)
def test_arabic_summary_uses_count_agreement_for_all_repetition_ranges(
    count, training_sets, repetitions, repetitions_after_preposition
):
    output = generate_session_debrief(
        "Upper",
        3,
        "",
        [],
        total_tonnage=0,
        display_language="ar",
        pr_events=[
            {
                "exercise_id": "bench_press",
                "name": "Bench Press",
                "record_type": "max_weight",
                "value": 100.0,
                "prev_value": 95.0,
                "reps": count,
            },
            {
                "exercise_id": "bench_press",
                "name": "Bench Press",
                "record_type": "most_reps",
                "value": count,
                "prev_value": 2,
            },
        ],
    )

    assert arabic_count_phrase(count, "training_set") == training_sets
    assert arabic_count_phrase(count, "repetition") == repetitions
    assert (
        arabic_count_phrase(
            count,
            "repetition",
            grammatical_case="oblique",
        )
        == repetitions_after_preposition
    )
    visible_output = (
        output.replace("\u2066", "")
        .replace("\u2068", "")
        .replace("\u2069", "")
    )
    prefix = "ل" if count in (1, 2) else "لـ"
    assert f"{prefix}{repetitions_after_preposition}" in visible_output
    assert f"أعلى عدد من التكرارات: {repetitions}" in visible_output
    if count >= 3:
        assert f"\u2066{count}\u2069" in output


@pytest.mark.parametrize(
    ("language", "expected_directive"),
    [
        ("en", "- DELOAD: Cut sets by 50%."),
        ("ar", "- تخفيف التدريب: خفّض مجموعات التدريب بنسبة \u206650%\u2069."),
    ],
)
def test_unrated_deload_cap_omits_the_rir_clause(language, expected_directive):
    output = generate_session_debrief(
        "Upper",
        3,
        "",
        [],
        fatigue_info={
            "deload_recommended": True,
            "volume_multiplier": 0.5,
            "intensity_cap_rpe": None,
        },
        display_language=language,
    )

    assert expected_directive in output
    assert "not rated" not in output
    assert "RIR" not in output


@pytest.mark.parametrize("count, expected", [(1, "لتكرار واحد"), (2, "لتكرارين")])
def test_arabic_pr_repetition_preposition_joins_word_forms_without_tatweel(
    count, expected
):
    output = generate_session_debrief(
        "Upper",
        3,
        "",
        [],
        display_language="ar",
        pr_events=[
            {
                "exercise_id": "bench_press",
                "name": "Bench Press",
                "record_type": "max_weight",
                "value": 100.0,
                "prev_value": 95.0,
                "reps": count,
            }
        ],
    )

    assert expected in output.replace("\u2066", "").replace("\u2068", "").replace("\u2069", "")


def test_retired_debrief_cases_are_covered_by_deterministic_directives():
    cases = json.loads(DEBRIEF_CASES.read_text(encoding="utf-8"))
    cases.extend(json.loads(GENERALIZATION_CASES.read_text(encoding="utf-8"))["debrief"])

    for case in cases:
        summaries = case["exercise_summaries"]
        fatigue = case.get("fatigue_info") or {}
        output = generate_session_debrief(
            split_name=case["split_name"],
            readiness=case["readiness"],
            session_notes=case.get("session_notes", ""),
            exercise_summaries=summaries,
            fatigue_info=fatigue,
        )
        total_volume = sum(exercise.get("volume_load", 0.0) for exercise in summaries)

        assert f"Readiness: {case['readiness']}/5" in output, case["id"]
        assert f"Volume Load: {total_volume:,.1f} kg" in output, case["id"]
        if fatigue.get("deload_recommended"):
            multiplier = fatigue["volume_multiplier"]
            cap_rir = 10 - fatigue["intensity_cap_rpe"]
            assert f"Cut sets by {(1 - multiplier) * 100:g}%" in output, case["id"]
            assert f"cap at RIR ≥ {cap_rir:g}" in output, case["id"]
        else:
            assert "DELOAD" not in output, case["id"]
            for exercise in summaries:
                if exercise.get("action") == "increase" or (exercise.get("e1rm_delta") or 0) > 0:
                    assert f"Advance load (+2.5 kg) for {exercise['name']}" in output, case["id"]
                else:
                    assert f"Hold load; build reps in the {exercise['name']}" in output, case["id"]
