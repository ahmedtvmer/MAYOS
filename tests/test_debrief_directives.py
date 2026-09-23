"""Deterministic active-deload directives must state the exact volume cut."""

from agent.debrief import generate_session_debrief

EXERCISES = [{"name": "Squat", "volume_load": 1000.0, "current_e1rm": 150.0, "e1rm_delta": 0.0}]


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
    assert "cap at RPE 7.0" in text


def test_active_deload_nonstandard_multiplier():
    text = _debrief({"deload_recommended": True, "volume_multiplier": 0.6, "intensity_cap_rpe": 8.0})
    assert "Cut sets by 40%" in text
    assert "cap at RPE 8.0" in text


def test_active_deload_missing_or_invalid_multiplier_never_fabricates():
    for bad in ({}, {"volume_multiplier": None}, {"volume_multiplier": "abc"}, {"volume_multiplier": 0}, {"volume_multiplier": 1.0}, {"volume_multiplier": 1.5}):
        text = _debrief({"deload_recommended": True, "intensity_cap_rpe": 7.0, **bad})
        assert "Cut sets by" not in text
        assert "Reduce sets" in text
        assert "cap at RPE 7.0" in text


def test_inactive_deload_content_unaffected():
    text = _debrief({"deload_recommended": False})
    assert "DELOAD" not in text
    assert "Cut sets by" not in text
    assert "RPE cap" not in text
    assert "Hold load" in text or "Advance load" in text
