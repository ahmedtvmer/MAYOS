from copy import deepcopy

import pytest

from agent.ProgramState import ProgramExerciseSchema, ProgramSetGroupSchema
from agent.program_order import main_muscles_for_slot, order_program_exercises, shares_main_muscle


def _exercise(exercise_id, slot, *, sets=2, equipment="Cable"):
    set_groups = [ProgramSetGroupSchema(
        sets=1,
        reps_min=8,
        reps_max=12,
        target_rir=3.0 if sets > 1 else 2.0,
    )]
    if sets > 1:
        set_groups.append(ProgramSetGroupSchema(
            sets=sets - 1, reps_min=8, reps_max=12, target_rir=2.0,
        ))
    return ProgramExerciseSchema(
        exercise_id=exercise_id,
        exercise_name=exercise_id,
        slot_key=slot,
        equipment=equipment,
        target_sets=sets,
        target_reps_min=8,
        target_reps_max=12,
        set_groups=set_groups,
    )


def _rationale(exercise):
    working_sets = exercise.working_sets
    test_set_count = int(working_sets > 1)
    return {
        "position": {"code": "position.isolation", "params": {}},
        "prescription": {
            "sets": {"code": "sets.coach_dose", "params": {"count": working_sets}},
            "rir": {
                "code": "rir.test_set_rule",
                "params": {
                    "target_rir": 2.0,
                    "test_set_count": test_set_count,
                    "test_set_rir": 3.0 if test_set_count else 2.0,
                },
            },
        },
    }


def _order(exercises, rationales=None, *, experience="intermediate"):
    return order_program_exercises(
        exercises,
        rationales or [_rationale(exercise) for exercise in exercises],
        day_family="arms",
        experience_level=experience,
    )


def test_lats_and_traps_are_distinct_for_program_ordering():
    assert main_muscles_for_slot("vertical_pull") == frozenset({"lats"})
    assert main_muscles_for_slot("horizontal_row") == frozenset({"traps"})
    assert not shares_main_muscle("vertical_pull", "horizontal_row")


def test_isolation_that_starts_after_compound_moves_before_it():
    ordered = _order([
        _exercise("row", "horizontal_row"),
        _exercise("press", "flat_press"),
        _exercise("fly", "chest_fly"),
    ])

    assert [entry.exercise.exercise_id for entry in ordered] == ["row", "fly", "press"]
    assert ordered[1].rationale["position"]["code"] == "position.pre_exhaust"


def test_issue_716_beginner_keeps_compounds_first_without_changing_prescriptions():
    exercises = [
        _exercise("calf", "calf"),
        _exercise("row", "horizontal_row"),
        _exercise("fly", "chest_fly"),
        _exercise("press", "flat_press"),
    ]

    ordered = _order(exercises, experience="beginner")

    assert [entry.exercise.exercise_id for entry in ordered] == [
        "row", "press", "calf", "fly",
    ]
    assert [entry.exercise.working_sets for entry in ordered] == [2, 2, 2, 2]
    assert ordered[1].rationale["position"]["code"] == "position.beginner_compound_first"
    assert ordered[3].rationale["position"]["code"] == "position.isolation"


def test_issue_716_beginner_main_lift_stays_first_when_template_starts_with_isolation():
    ordered = _order(
        [_exercise("side-delts", "side_delts"), _exercise("press", "incline_press")],
        experience="beginner",
    )

    assert [entry.exercise.exercise_id for entry in ordered] == ["press", "side-delts"]
    assert ordered[0].rationale["position"]["code"] == "position.main_progressed_lift"


def test_issue_716_calf_does_not_open_a_day_with_larger_isolations():
    ordered = _order([
        _exercise("calf", "calf", equipment="Body Weight"),
        _exercise("quads", "quad_iso", equipment="Body Weight"),
        _exercise("abs", "abs", equipment="Body Weight"),
    ])

    assert [entry.exercise.exercise_id for entry in ordered] == [
        "quads", "calf", "abs",
    ]


@pytest.mark.parametrize(
    ("isolation_slot", "compound_slot", "equipment"),
    [
        ("ham_curl", "quad_compound", "Barbell"),
        ("ham_curl", "ham_hinge", "Dumbbell"),
        ("forearm_wrist", "horizontal_row", "Barbell"),
        ("forearm_reverse", "horizontal_row", "Dumbbell"),
    ],
)
def test_stabilizer_isolation_stays_after_free_weight_lift(
    isolation_slot, compound_slot, equipment
):
    ordered = _order([
        _exercise("isolation", isolation_slot),
        _exercise("lift", compound_slot, equipment=equipment),
    ])

    assert [entry.exercise.exercise_id for entry in ordered] == ["lift", "isolation"]
    assert ordered[1].rationale["position"]["code"] == "position.stabilizer_safety"


def test_safety_isolation_variants_keep_source_order_after_free_weight_pull():
    ordered = _order([
        _exercise("wrist-curl", "forearm_wrist"),
        _exercise("reverse-curl", "forearm_reverse"),
        _exercise("row", "horizontal_row", equipment="Barbell"),
    ])

    assert [entry.exercise.exercise_id for entry in ordered] == [
        "row", "wrist-curl", "reverse-curl",
    ]


def test_focus_variants_keep_order_and_respect_aggregate_pre_exhaust_cap_on_second_pass():
    exercises = [
        _exercise("focus-fly", "chest_fly"),
        _exercise("row", "horizontal_row"),
        _exercise("base-fly", "chest_fly"),
        _exercise("press", "flat_press"),
    ]
    rationales = [_rationale(exercise) for exercise in exercises]
    rationales[0]["selection"] = {"code": "selection.focus_muscle_extra", "params": {}}
    rationales[0]["position"]["code"] = "position.focus_first"

    first = _order(exercises, rationales)
    first_state = [
        (
            entry.exercise.exercise_id,
            entry.exercise.model_dump(),
            deepcopy(entry.rationale),
        )
        for entry in first
    ]
    second = _order(
        [entry.exercise for entry in first],
        [entry.rationale for entry in first],
    )
    second_state = [
        (entry.exercise.exercise_id, entry.exercise.model_dump(), entry.rationale)
        for entry in second
    ]

    assert second_state == first_state
    assert [entry.exercise.exercise_id for entry in first] == [
        "row", "focus-fly", "press", "base-fly",
    ]
    press_index = next(
        index for index, entry in enumerate(first)
        if entry.exercise.exercise_id == "press"
    )
    assert sum(
        entry.exercise.working_sets
        for index, entry in enumerate(first)
        if index < press_index
        if entry.exercise.slot_key == "chest_fly"
    ) == 2
    assert sum(entry.exercise.working_sets for entry in first) == 8


def test_issue_716_separated_focus_extra_keeps_its_position_on_second_pass():
    exercises = [
        _exercise("row", "horizontal_row"),
        _exercise("focus-fly", "chest_fly"),
        _exercise("calf", "calf"),
        _exercise("press", "flat_press"),
    ]
    rationales = [_rationale(exercise) for exercise in exercises]
    rationales[1]["selection"] = {"code": "selection.focus_muscle_extra", "params": {}}
    rationales[1]["position"]["code"] = "position.focus_first"

    first = _order(exercises, rationales)
    second = _order(
        [entry.exercise for entry in first],
        [entry.rationale for entry in first],
    )

    assert [entry.exercise.exercise_id for entry in first] == [
        "row", "focus-fly", "calf", "press",
    ]
    assert [entry.exercise.exercise_id for entry in second] == [
        entry.exercise.exercise_id for entry in first
    ]


def test_issue_716_focus_extra_follows_main_before_unrelated_pre_exhaust():
    exercises = [
        _exercise("quad-isolation", "quad_iso"),
        _exercise("bench", "incline_press"),
        _exercise("quad-compound", "quad_compound"),
        _exercise("focus-fly", "chest_fly"),
    ]
    rationales = [_rationale(exercise) for exercise in exercises]
    rationales[-1]["selection"] = {
        "code": "selection.focus_muscle_extra",
        "params": {},
    }
    rationales[-1]["position"]["code"] = "position.focus_first"

    ordered = _order(exercises, rationales)

    assert [entry.exercise.exercise_id for entry in ordered] == [
        "bench", "focus-fly", "quad-isolation", "quad-compound",
    ]
    assert ordered[1].rationale["position"]["code"] == "position.focus_first"


def test_issue_716_focus_extra_cannot_relocate_the_only_main_lift():
    exercises = [
        _exercise("fly", "chest_fly"),
        _exercise("side-delts", "side_delts"),
        _exercise("biceps_preacher", "biceps_preacher"),
        _exercise("focus-row", "horizontal_row"),
    ]
    rationales = [_rationale(exercise) for exercise in exercises]
    rationales[-1]["selection"] = {
        "code": "selection.focus_muscle_extra",
        "params": {},
    }
    rationales[-1]["position"]["code"] = "position.focus_first"

    ordered = _order(exercises, rationales)

    assert [entry.exercise.exercise_id for entry in ordered] == [
        "focus-row", "fly", "side-delts", "biceps_preacher",
    ]


def test_issue_716_bodyweight_opener_keeps_focus_exercise_first():
    exercises = [
        _exercise("focus-adductors", "adductors", equipment="Body Weight"),
        _exercise("quad-iso", "quad_iso", equipment="Body Weight"),
        _exercise("calf", "calf", equipment="Body Weight"),
        _exercise("ham-curl", "ham_curl", equipment="Body Weight"),
    ]
    rationales = [_rationale(exercise) for exercise in exercises]
    rationales[0]["selection"] = {
        "code": "selection.focus_muscle_extra",
        "params": {},
    }
    rationales[0]["position"]["code"] = "position.focus_first"

    ordered = _order(exercises, rationales)

    assert [entry.exercise.exercise_id for entry in ordered] == [
        "focus-adductors", "quad-iso", "calf", "ham-curl",
    ]


def test_sets_cut_from_pre_exhaust_isolation_are_reassigned():
    exercises = [
        _exercise("row", "horizontal_row"),
        _exercise("fly", "chest_fly", sets=3),
        _exercise("press", "flat_press", sets=2),
    ]
    original_chest_sets = sum(
        exercise.working_sets for exercise in exercises
        if exercise.slot_key in {"chest_fly", "flat_press"}
    )

    ordered = _order(exercises)
    ordered_state = [
        (entry.exercise.model_dump(), deepcopy(entry.rationale))
        for entry in ordered
    ]
    fly = next(entry for entry in ordered if entry.exercise.exercise_id == "fly")
    press = next(entry for entry in ordered if entry.exercise.exercise_id == "press")
    retained_chest_sets = sum(
        entry.exercise.working_sets for entry in ordered
        if entry.exercise.slot_key in {"chest_fly", "flat_press"}
    )

    assert fly.exercise.working_sets == 2
    assert press.exercise.working_sets == 3
    assert retained_chest_sets == original_chest_sets
    assert fly.rationale["prescription"]["sets"]["params"]["redistributed_to"] == "press"
    assert press.rationale["prescription"]["sets"]["params"]["redistributed_from"] == "fly"
    assert fly.rationale["prescription"]["sets"]["params"]["redistribution_reason_en"]
    assert fly.rationale["prescription"]["sets"]["params"]["redistribution_reason_ar"]
    repeated = _order(
        [entry.exercise for entry in ordered],
        [entry.rationale for entry in ordered],
    )
    assert [
        (entry.exercise.model_dump(), entry.rationale) for entry in repeated
    ] == ordered_state
