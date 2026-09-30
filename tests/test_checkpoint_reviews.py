"""Pure fact and rating rules for Checkpoint reviews (#221)."""

import pytest

from service.checkpoint_reviews import (
    CheckpointFactsInput,
    compute_checkpoint_facts,
    rate_checkpoint_facts,
    template_text,
)
from service.training_status import is_checkpoint, previous_checkpoint


def test_checkpoint_boundaries_share_training_status_rules():
    assert [is_checkpoint(number) for number in (10, 25, 50, 100, 200, 225)] == [
        True,
        True,
        True,
        True,
        True,
        False,
    ]
    assert [previous_checkpoint(number) for number in (10, 25, 50, 100, 200)] == [
        None,
        10,
        25,
        50,
        100,
    ]


def _rating_facts(
    *, weeks_met=0, weeks_counted=0, records=0, regressed=0, first_volume=0, second_volume=0
):
    return {
        "weeks_met": weeks_met,
        "weeks_counted": weeks_counted,
        "personal_records": records,
        "regressed_exercises": regressed,
        "volume_first_half": first_volume,
        "volume_second_half": second_volume,
    }


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (_rating_facts(), ("Not enough weeks yet", "Holding", "Not enough data")),
        (_rating_facts(weeks_met=8, weeks_counted=10), ("Strong", "Holding", "Not enough data")),
        (_rating_facts(weeks_met=5, weeks_counted=10), ("Steady", "Holding", "Not enough data")),
        (_rating_facts(weeks_met=4, weeks_counted=10), ("Needs attention", "Holding", "Not enough data")),
        (_rating_facts(records=2), ("Not enough weeks yet", "Strong", "Not enough data")),
        (_rating_facts(records=1), ("Not enough weeks yet", "Steady", "Not enough data")),
        (_rating_facts(records=2, regressed=2), ("Not enough weeks yet", "Steady", "Not enough data")),
        (_rating_facts(regressed=1), ("Not enough weeks yet", "Needs attention", "Not enough data")),
        (_rating_facts(first_volume=100, second_volume=105), ("Not enough weeks yet", "Holding", "Rising")),
        (_rating_facts(first_volume=100, second_volume=95), ("Not enough weeks yet", "Holding", "Falling")),
        (_rating_facts(first_volume=100, second_volume=104.9), ("Not enough weeks yet", "Holding", "Holding")),
    ],
)
def test_each_rating_uses_its_fixed_thresholds(facts, expected):
    assert tuple(part["label"] for part in rate_checkpoint_facts(facts)) == expected


def test_facts_deduplicate_record_types_exclude_warmups_and_put_middle_workout_second():
    workouts = [
        {"session_id": f"s{index}", "session_date": f"2026-09-{26 + index:02d}"}
        for index in range(3)
    ]
    facts = compute_checkpoint_facts(
        CheckpointFactsInput(
            workouts=workouts,
            previous_workouts=[{"session_id": "prior", "session_date": "2026-09-23"}],
            working_sets=[
                {"session_id": "s0", "exercise_id": "sq", "weight_kg": 100, "reps": 5, "rpe": 8, "is_warmup": 0},
                {"session_id": "s1", "exercise_id": "sq", "weight_kg": 90, "reps": 5, "rpe": 8, "is_warmup": 0},
                {"session_id": "s1", "exercise_id": "bp", "weight_kg": 200, "reps": 5, "rpe": 8, "is_warmup": 1},
                {"session_id": "s2", "exercise_id": "bp", "weight_kg": 50, "reps": 10, "rpe": 8, "is_warmup": 0},
                {"session_id": "prior", "exercise_id": "sq", "weight_kg": 110, "reps": 5, "rpe": 8, "is_warmup": 0},
            ],
            personal_records=[
                {"session_id": "s0", "exercise_id": "sq", "record_type": "max_weight"},
                {"session_id": "s1", "exercise_id": "sq", "record_type": "max_e1rm"},
            ],
            schedule_versions=[],
            pauses=[],
            weekly_frequency=1,
        )
    )
    assert facts == {
        "workouts_in_period": 3,
        "weeks_met": 1,
        "weeks_counted": 1,
        "personal_records": 1,
        "regressed_exercises": 1,
        "volume_first_half": 500.0,
        "volume_second_half": 950.0,
    }


@pytest.mark.parametrize(
    ("dates", "weeks_met", "weeks_counted"),
    [
        (["2026-09-27", "2026-09-28"], 0, 0),
        (["2026-09-27", "2026-09-28", "2026-09-29"], 1, 1),
    ],
)
def test_partial_edge_week_counts_only_when_target_is_met(
    dates, weeks_met, weeks_counted
):
    workouts = [
        {"session_id": f"s{index}", "session_date": day}
        for index, day in enumerate(dates)
    ]
    inputs = CheckpointFactsInput(
        workouts=workouts,
        previous_workouts=[],
        working_sets=[],
        personal_records=[],
        schedule_versions=[],
        pauses=[],
        weekly_frequency=3,
    )
    facts = compute_checkpoint_facts(inputs)
    assert facts["weeks_met"] == weeks_met
    assert facts["weeks_counted"] == weeks_counted


def test_template_text_has_fixed_english_and_arabic_sentences():
    assert template_text(10, 10, "en", True) == (
        "Checkpoint 10: 10 workouts since you started logging in MAYOS."
    )
    assert template_text(25, 15, "en", False) == (
        "Checkpoint 25: 15 workouts since your last checkpoint."
    )
    assert template_text(10, 10, "ar", True) == (
        "نقطة التحقق 10: 10 تمرينًا منذ بدء تسجيلك في MAYOS."
    )
