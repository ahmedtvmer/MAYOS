"""Deterministic debrief directives and the retired judge fixtures."""

import json
from pathlib import Path

from agent.debrief import generate_session_debrief

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
