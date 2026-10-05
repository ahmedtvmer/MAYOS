from agent.ProgramState import PersistedProgramSchema
from service.program_change_summary import summarize_program_change


def _program(days):
    return PersistedProgramSchema.model_validate(
        {
            "program_name": "Plan",
            "split_type": "Custom",
            "weekly_frequency": len(days),
            "days": days,
        }
    )


def _exercise(exercise_id, name, **changes):
    return {
        "exercise_id": exercise_id,
        "exercise_name": name,
        "target_sets": 3,
        "target_reps_min": 6,
        "target_reps_max": 8,
        "target_rpe": 8,
        "rest_seconds": 120,
        **changes,
    }


def test_diff_reports_day_exercise_and_prescription_changes():
    previous = _program(
        [
            {
                "day_name": "Lower A",
                "day_order": 1,
                "exercises": [
                    _exercise("squat", "Back Squat", slot_key="squat"),
                    _exercise("press", "Bench Press", slot_key="press"),
                ],
            },
            {
                "day_name": "Upper A",
                "day_order": 2,
                "exercises": [
                    _exercise("row", "Cable Row"),
                    _exercise("curl", "Cable Curl"),
                ],
            },
            {
                "day_name": "Core",
                "day_order": 3,
                "exercises": [_exercise("crunch", "Cable Crunch")],
            },
            {
                "day_name": "Mobility",
                "day_order": 4,
                "exercises": [_exercise("stretch", "Hip Stretch")],
            },
        ]
    )
    current = _program(
        [
            {
                "day_name": "Lower 1",
                "day_order": 1,
                "exercises": [
                    _exercise(
                        "safety-squat",
                        "Safety Bar Squat",
                        slot_key="squat",
                        target_sets=4,
                        target_reps_min=5,
                        target_reps_max=7,
                        target_rpe=9,
                        rest_seconds=180,
                    ),
                    _exercise("press", "Bench Press", slot_key="press"),
                    _exercise("fly", "Cable Fly", slot_key="fly"),
                ],
            },
            {
                "day_name": "Pull",
                "day_order": 2,
                "exercises": [_exercise("row", "Cable Row")],
            },
            {
                "day_name": "Conditioning",
                "day_order": 3,
                "exercises": [_exercise("bike", "Bike")],
            },
        ]
    )

    summary = summarize_program_change(previous, current, lambda exercise_id: exercise_id)

    changes = summary["changes"]
    assert {change["type"] for change in changes} >= {
        "day_renamed",
        "day_removed",
        "exercise_replaced",
        "exercise_added",
        "exercise_removed",
        "prescription_changed",
    }
    replacement = next(change for change in changes if change["type"] == "exercise_replaced")
    assert replacement["before"] == "squat"
    assert replacement["after"] == "safety-squat"
    prescription = next(
        change
        for change in changes
        if change["type"] == "prescription_changed" and change["exercise"] == "safety-squat"
    )
    assert prescription["fields"] == {
        "sets": {"before": 3, "after": 4},
        "reps": {"before": "6–8", "after": "5–7"},
        "rir": {"before": 2, "after": 1},
        "rest_seconds": {"before": 120, "after": 180},
    }
    assert "load" not in prescription["fields"]


def test_identical_program_has_no_structural_changes():
    program = _program(
        [{"day_name": "Full A", "day_order": 1, "exercises": [_exercise("sq", "Squat")]}]
    )
    previous = program.model_copy(
        update={"version": 2, "published_by_coach_account_id": "coach-old", "created_at": "old"}
    )
    current = program.model_copy(
        update={"version": 3, "published_by_coach_account_id": "coach-new", "created_at": "new"}
    )

    assert summarize_program_change(previous, current, lambda exercise_id: exercise_id) == {
        "version": 1,
        "unchanged": True,
        "changes": [],
    }


def test_first_publish_lists_every_day_and_exercise_as_added():
    program = _program(
        [{"day_name": "Full A", "day_order": 1, "exercises": [_exercise("sq", "Squat")]}]
    )

    summary = summarize_program_change(None, program, lambda exercise_id: exercise_id)

    assert summary["unchanged"] is False
    assert [change["type"] for change in summary["changes"]] == ["day_added", "exercise_added"]


def test_duplicate_slot_keys_match_exercises_in_order():
    previous = _program(
        [
            {
                "day_name": "Upper",
                "day_order": 1,
                "exercises": [
                    _exercise("old-press-1", "Press One", slot_key="press"),
                    _exercise("old-press-2", "Press Two", slot_key="press"),
                ],
            }
        ]
    )
    current = _program(
        [
            {
                "day_name": "Upper",
                "day_order": 1,
                "exercises": [
                    _exercise("new-press-1", "New Press One", slot_key="press"),
                    _exercise("new-press-2", "New Press Two", slot_key="press"),
                ],
            }
        ]
    )

    summary = summarize_program_change(previous, current, lambda exercise_id: exercise_id)

    assert [change["type"] for change in summary["changes"]] == [
        "exercise_replaced",
        "exercise_replaced",
    ]
    assert [change["before"] for change in summary["changes"]] == [
        "old-press-1",
        "old-press-2",
    ]


def test_inserted_day_matches_existing_days_by_name_before_position():
    previous = _program(
        [
            {"day_name": "Push", "day_order": 1, "exercises": [_exercise("bench", "Bench Press")]},
            {"day_name": "Pull", "day_order": 2, "exercises": [_exercise("row", "Cable Row")]},
            {"day_name": "Legs", "day_order": 3, "exercises": [_exercise("squat", "Back Squat")]},
        ]
    )
    current = _program(
        [
            {"day_name": "Push", "day_order": 1, "exercises": [_exercise("bench", "Bench Press")]},
            {"day_name": "Upper", "day_order": 2, "exercises": [_exercise("fly", "Cable Fly")]},
            {"day_name": "Pull", "day_order": 3, "exercises": [_exercise("row", "Cable Row")]},
            {"day_name": "Legs", "day_order": 4, "exercises": [_exercise("squat", "Back Squat")]},
        ]
    )

    summary = summarize_program_change(previous, current, lambda exercise_id: exercise_id)

    assert summary["changes"] == [
        {"type": "day_added", "day": "Upper"},
        {"type": "exercise_added", "day": "Upper", "exercise": "fly"},
    ]


def test_exercise_reordering_emits_generic_details_line_instead_of_approval():
    previous = _program(
        [
            {
                "day_name": "Upper",
                "day_order": 1,
                "exercises": [
                    _exercise("bench", "Bench Press"),
                    _exercise("row", "Cable Row"),
                ],
            }
        ]
    )
    current = _program(
        [
            {
                "day_name": "Upper",
                "day_order": 1,
                "exercises": [
                    _exercise("row", "Cable Row"),
                    _exercise("bench", "Bench Press"),
                ],
            }
        ]
    )

    summary = summarize_program_change(previous, current, lambda exercise_id: exercise_id)

    assert summary["unchanged"] is False
    assert summary["changes"] == [{"type": "other_details_changed"}]


def test_repeated_exercise_ids_are_matched_without_false_additions_or_replacements():
    previous = _program(
        [
            {
                "day_name": "Upper",
                "day_order": 1,
                "exercises": [
                    _exercise("row", "Cable Row", slot_key="row_a", notes="Pause at the chest."),
                    _exercise("row", "Cable Row", slot_key="row_b", notes="Keep elbows tucked."),
                ],
            }
        ]
    )
    current = _program(
        [
            {
                "day_name": "Upper",
                "day_order": 1,
                "exercises": [
                    _exercise("row", "Cable Row", slot_key="row_a", notes="Pause at the chest."),
                    _exercise("row", "Cable Row", slot_key="row_b", notes="Keep the chest tall."),
                ],
            }
        ]
    )

    summary = summarize_program_change(previous, current, lambda exercise_id: exercise_id)

    assert summary["unchanged"] is False
    assert summary["changes"] == [{"type": "other_details_changed"}]


def test_fixed_rep_targets_do_not_render_as_a_range():
    previous = _program(
        [
            {
                "day_name": "Upper",
                "day_order": 1,
                "exercises": [_exercise("bench", "Bench Press", target_reps_min=8, target_reps_max=8)],
            }
        ]
    )
    current = _program(
        [
            {
                "day_name": "Upper",
                "day_order": 1,
                "exercises": [_exercise("bench", "Bench Press", target_reps_min=10, target_reps_max=10)],
            }
        ]
    )

    summary = summarize_program_change(previous, current, lambda exercise_id: exercise_id)

    prescription = summary["changes"][0]
    assert prescription["fields"]["reps"] == {"before": "8", "after": "10"}
