"""Plain pytest rubric for the deterministic coach-pattern program generator."""

import json
from math import ceil
from pathlib import Path

import pytest

from agent.program_generator import (
    ProgramGenerationRequest,
    generate_program_draft_pipeline,
    generate_program_pipeline,
)
from agent.program_blueprints import SLOT_SPECS, SLOT_STAPLES
from agent.program_rules import SPLIT_OPTIONS_BY_FREQUENCY
from agent.focus_muscles import FOCUS_MUSCLE_SLOTS
from core.muscle_volume import main_group_for_focus
from core.weak_points import WEAK_POINT_MUSCLES


MUSCLE_GROUPS = {
    "chest": {"incline_press", "flat_press", "chest_fly"},
    "lats": {"vertical_pull", "pullover"},
    "traps": {"horizontal_row", "upper_back_pull", "shrug"},
    "shoulders": {"shoulder_press", "side_delts", "rear_delts"},
    "biceps": {"biceps_preacher", "biceps_alt"},
    "triceps": {"triceps_pushdown", "triceps_overhead"},
    "forearms": {"forearm_wrist", "forearm_reverse"},
    "quads": {"quad_compound", "quad_lunge", "quad_iso"},
    "hamstrings": {"ham_curl", "ham_hinge"},
    "glutes": {"glute_thrust", "glute_iso"},
    "adductors": {"adductors"},
    "calves": {"calf"},
    "abs": {"abs"},
}
SMALL_MUSCLE_OPENERS = {"side_delts", "calf", "adductors", "rear_delts", "forearm_wrist", "abs"}
COACH_PATTERN_BACK_SLOT_ADDITIONS = {
    3: {"Full Body #3": {"vertical_pull": 1, "horizontal_row": 1}},
    4: {"Upper 1": {"horizontal_row": 1}, "Upper 2": {"vertical_pull": 1}},
    5: {"Upper": {"horizontal_row": 1}, "Pull": {"vertical_pull": 1}},
}
COMPOUND_CLASSES = {"heavy_compound", "medium_compound"}
CORE_STAPLE_SLOTS = {
    "incline_press", "flat_press", "vertical_pull", "horizontal_row", "side_delts",
    "rear_delts", "shoulder_press", "biceps_preacher", "biceps_alt", "triceps_overhead", "forearm_wrist",
    "forearm_reverse", "quad_compound", "quad_iso", "ham_curl", "ham_hinge",
    "glute_thrust", "glute_iso", "adductors", "calf", "abs", "shrug",
}
BODYWEIGHT_RUBRIC_EXCEPTIONS = {
    "shoulders": (2, 1, "Owner-agreed bodyweight-only shoulder dose is one two-set shoulder press day."),
    "forearms": (0, 0, "The library has no bodyweight wrist-flexion or wrist-extension rows."),
    "hamstrings": (2, 1, "Bodyweight-only retains its available two-set hamstring-curl dose; hinge work is unavailable."),
}
BODYWEIGHT_SLOT_EXCEPTIONS = {
    "side_delts": "Bodyweight-only has no direct side-delt movement slot.",
    "rear_delts": "The library has no bodyweight rear-delt movement rows.",
    "shrug": "The library has no bodyweight scapular-elevation movement rows.",
    "ham_hinge": "Bodyweight-only has no hamstring-hinge slot; hamstring curls remain prescribed.",
    "forearm_wrist": BODYWEIGHT_RUBRIC_EXCEPTIONS["forearms"][2],
    "forearm_reverse": BODYWEIGHT_RUBRIC_EXCEPTIONS["forearms"][2],
}
BODYWEIGHT_SLOT_EXCEPTION_VALUES = {
    "side_delts": (0, 0),
    "rear_delts": (0, 0),
    "shrug": (0, 0),
    "ham_hinge": (0, 0),
    "forearm_wrist": (0, 0),
    "forearm_reverse": (0, 0),
}
BODYWEIGHT_STAPLE_EQUIVALENTS = {
    "incline_press": {("flat_press", "662")},
    "flat_press": {("flat_press", "662")},
    "shoulder_press": {("shoulder_press", "471")},
    "biceps_preacher": {("biceps_alt", "1769")},
    "quad_iso": {("quad_iso", "1489")},
}
BODYWEIGHT_STAPLE_EXCEPTIONS = BODYWEIGHT_SLOT_EXCEPTIONS
def _generate_matrix_program(db, *, experience, days, equipment):
    user = f"coach_rubric_{experience}_{days}_{equipment}"
    db.switch_user(user)
    db.ledger.upsert_player_profile(
        {
            "gender": "female",
            "proportions": "balanced",
            "age": 28,
            "weight_kg": 70.0,
            "height_cm": 165.0,
            "rep_preference": "balanced",
            "current_goal": "hypertrophy",
            "long_term_goal": "progressive overload",
            "weekly_frequency": days,
            "training_age_years": {"beginner": 0.5, "intermediate": 3.0, "advanced": 6.0}[experience],
            "equipment_access": equipment,
            "injuries_or_limitations": "None",
            "stress_and_sleep": "normal",
        }
    )
    return generate_program_pipeline(ledger=db.ledger)[0]


@pytest.fixture
def seed_bodyweight_curation(tmp_path, monkeypatch):
    from database.exercise_library import embeddings
    from database.schema.definitions import EMBEDDING_DIM

    class LocalEmbeddingStub:
        def embed_query(self, _text):
            return [1.0] + [0.0] * (EMBEDDING_DIM - 1)

    monkeypatch.setattr(embeddings, "_load_embedding_model", lambda: LocalEmbeddingStub())

    def apply(db):
        seed_path = tmp_path / "empty-exercises.csv"
        seed_path.write_text(
            "id,name,bodyPart,target,equipment,image_path,gif_path,instructions\n",
            encoding="utf-8",
        )
        db.initialize_and_seed(seed_path, db.curation_path)

    return apply


def _program_snapshot(program):
    return {
        "split_type": program.split_type,
        "days": [
            {
                "day_name": day.day_name,
                "exercises": [
                    {
                        "exercise_id": exercise.exercise_id,
                        "slot_key": exercise.slot_key,
                        "target_sets": exercise.working_sets,
                    }
                    for exercise in day.exercises
                ],
            }
            for day in program.days
        ],
    }


def _main_progressed_exercise(program, day):
    rationale_day = next(
        item for item in program.program_rationale["days"]
        if item["day_order"] == day.day_order
    )
    main_record = next(
        (
            item for item in rationale_day["exercises"]
            if item["rationale"]["position"]["code"]
            == "position.main_progressed_lift"
        ),
        None,
    )
    if main_record is None:
        return None
    return next(
        exercise for exercise in day.exercises
        if exercise.exercise_id == main_record["exercise_id"]
    )


def _assert_focus_exercises_keep_opening_position(program, day, focus_ids):
    focus_exercises = [
        exercise for exercise in day.exercises if exercise.exercise_id in focus_ids
    ]
    assert {exercise.exercise_id for exercise in focus_exercises} == focus_ids
    rationale_day = next(
        item for item in program.program_rationale["days"]
        if item["day_order"] == day.day_order
    )
    rationale_by_id = {
        item["exercise_id"]: item["rationale"]
        for item in rationale_day["exercises"]
    }
    focus_rationale = rationale_by_id[focus_exercises[0].exercise_id]
    experience_level = focus_rationale["prescription"]["rir"]["params"][
        "experience_level"
    ]
    position_codes = {
        exercise_id: rationale["position"]["code"]
        for exercise_id, rationale in rationale_by_id.items()
    }
    main_exercise = _main_progressed_exercise(program, day)
    if main_exercise is not None:
        assert day.exercises[0] is main_exercise
        for focus_exercise in focus_exercises:
            assert day.exercises.index(main_exercise) < day.exercises.index(
                focus_exercise
            )
    for focus_exercise in focus_exercises:
        earlier_exercises = day.exercises[:day.exercises.index(focus_exercise)]
        for exercise in earlier_exercises:
            assert (
                exercise is main_exercise
                or exercise.exercise_id in focus_ids
                or position_codes[exercise.exercise_id] == "position.stabilizer_safety"
                or (
                    experience_level == "beginner"
                    and SLOT_SPECS[exercise.slot_key].archetype in COMPOUND_CLASSES
                )
            )


def _remove_expected_back_slot_additions(snapshot, additions):
    for day in snapshot["days"]:
        for slot_key, count in additions.get(day["day_name"], {}).items():
            indexes = [
                index for index, exercise in enumerate(day["exercises"])
                if exercise["slot_key"] == slot_key
            ]
            assert len(indexes) >= count, (day["day_name"], slot_key)
            for index in reversed(indexes[-count:]):
                day["exercises"].pop(index)
    return snapshot


def _remove_rebalanced_coach_slots(snapshot, days):
    # Compare the rest of the template; focused assertions cover these trades.
    split_type = snapshot["split_type"]
    if days == 3:
        removed_by_day = {
            "Full Body #2": {"horizontal_row", "shrug"},
            "Full Body #3": {"chest_fly", "shrug"},
        }
    elif split_type == "PPL × UL":
        removed_by_day = {
            "Push": {"chest_fly", "triceps_pushdown"},
            "Pull": {"horizontal_row", "shrug"},
        }
    elif split_type == "Upper / Lower (Arms & Delts Augmented)":
        removed_by_day = {"Upper 2": {"horizontal_row", "shrug"}}
    else:
        removed_by_day = {
            day["day_name"]: {"chest_fly"} for day in snapshot["days"]
        }
    for day in snapshot["days"]:
        removed = removed_by_day.get(day["day_name"], set())
        day["exercises"] = [
            exercise for exercise in day["exercises"]
            if exercise["slot_key"] not in removed
        ]
    return snapshot


def test_commercial_and_home_program_outputs_match_baseline_snapshot(real_library_store):
    fresh_store = real_library_store
    snapshot_path = Path(__file__).parent / "fixtures" / "coach_pattern_program_baseline.json"
    expected = json.loads(snapshot_path.read_text())
    expected = {
        key: _remove_rebalanced_coach_slots(snapshot, int(key.split("|", 2)[1]))
        for key, snapshot in expected.items()
    }
    actual = {}
    for equipment in ("Commercial gym", "Home gym"):
        for experience in ("beginner", "intermediate", "advanced"):
            for days in (3, 4, 5):
                key = f"{experience}|{days}|{equipment}|false"
                program = _generate_matrix_program(
                    fresh_store,
                    experience=experience,
                    days=days,
                    equipment=equipment,
                )
                actual[key] = _remove_rebalanced_coach_slots(
                    _remove_expected_back_slot_additions(
                        _program_snapshot(program),
                        COACH_PATTERN_BACK_SLOT_ADDITIONS[days],
                    ),
                    days,
                )
    assert actual == expected


@pytest.mark.parametrize("days", [3, 4, 5])
def test_bodyweight_only_does_not_relabel_ham_curl_as_ham_hinge(real_library_store, days):
    # The assertion names library id 1766, whose name/relationship is not
    # supplied by the permitted fixture sources.
    fresh_store = real_library_store
    program = _generate_matrix_program(
        fresh_store,
        experience="beginner",
        days=days,
        equipment="Bodyweight only",
    )
    assert not any(
        exercise.slot_key == "ham_hinge"
        for day in program.days
        for exercise in day.exercises
    )
    curls = [
        exercise
        for day in program.days
        for exercise in day.exercises
        if exercise.slot_key == "ham_curl"
    ]
    assert curls and all(exercise.exercise_id == "1766" for exercise in curls)


def test_focus_chest_adds_a_variant_after_the_main_lift_on_lightest_day(fresh_store):
    db = fresh_store
    user = "focus_chest_rubric"
    db.switch_user(user)
    profile = {
        "gender": "male", "proportions": "balanced", "age": 28,
        "weight_kg": 70.0, "height_cm": 175.0, "rep_preference": "balanced",
        "current_goal": "hypertrophy", "long_term_goal": "progressive overload",
        "weekly_frequency": 5, "training_age_years": 3.0,
        "equipment_access": "Commercial gym", "injuries_or_limitations": "None",
        "stress_and_sleep": "normal", "weak_points": [{"muscle": "chest", "source": "named"}],
    }
    db.ledger.upsert_player_profile(profile)
    program = generate_program_pipeline(ledger=db.ledger)[0]

    focus = program.program_rationale["focus_muscles"][0]
    assert focus["muscle"] == "chest" and focus["source"] == "named"
    assert focus["status"] == "added"
    assert focus["exercise_id"] in {exercise.exercise_id for day in program.days for exercise in day.exercises}
    target_day = next(day for day in program.days if day.day_order == focus["day_order"])
    _assert_focus_exercises_keep_opening_position(
        program, target_day, {focus["exercise_id"]}
    )
    assert all(
        exercise.exercise_id != focus["exercise_id"]
        for day in program.days if day is not target_day
        for exercise in day.exercises
    )
    reason = next(item["rationale"] for item in program.program_rationale["days"][focus["day_order"] - 1]["exercises"] if item["exercise_id"] == focus["exercise_id"])
    assert reason["selection"]["code"] == "selection.focus_muscle_extra"
    assert reason["position"]["code"] == "position.focus_first"
    assert reason["prescription"]["sets"]["code"] == "sets.focus_multiplier"
    set_params = reason["prescription"]["sets"]["params"]
    actual_weekly_sets = sum(
        exercise.working_sets for day in program.days for exercise in day.exercises
        if exercise.slot_key in {"incline_press", "flat_press", "chest_fly"}
    )
    assert set_params["actual_weekly_sets"] == actual_weekly_sets
    assert set_params["actual_weekly_sets"] >= set_params["target_weekly_sets"]
    day_reasons = program.program_rationale["days"][focus["day_order"] - 1]["exercises"]
    assert all(
        item["rationale"]["position"]["code"] != "position.small_muscle_opener"
        for item in day_reasons[1:]
    )


@pytest.mark.parametrize(("muscle", "source", "equipment", "expected_status"), [
    ("glutes", "default", "Commercial gym", "added"),
    ("calves", "named", "Commercial gym", "added"),
    ("forearms", "named", "Bodyweight only", "unavailable"),
])
def test_focus_source_and_unavailable_equipment_are_recorded(
    fresh_store, seed_bodyweight_curation, muscle, source, equipment, expected_status
):
    if equipment == "Bodyweight only":
        seed_bodyweight_curation(fresh_store)
    fresh_store.switch_user(f"focus_{muscle}_{equipment}")
    fresh_store.ledger.upsert_player_profile({
        "gender": "female", "proportions": "balanced", "age": 28, "weight_kg": 70.0,
        "height_cm": 165.0, "rep_preference": "balanced", "current_goal": "hypertrophy",
        "long_term_goal": "progressive overload", "weekly_frequency": 3, "training_age_years": 3.0,
        "equipment_access": equipment, "injuries_or_limitations": "None", "stress_and_sleep": "normal",
        "weak_points": [{"muscle": muscle, "source": source}],
    })
    program = generate_program_pipeline(user_split_override="PPL", ledger=fresh_store.ledger)[0]
    focus = program.program_rationale["focus_muscles"][0]
    assert (focus["muscle"], focus["source"], focus["status"]) == (muscle, source, expected_status)
    if muscle == "calves":
        assert focus["exercise_id"] == "1371"
    if expected_status == "unavailable":
        assert focus["reason"]["code"] == "focus.unavailable"
        assert focus["reason"]["params"]["equipment_access"] == equipment


# #713: upper-chest credit must cover the later named chest target.
def test_two_focus_muscles_keep_named_order_when_opening_same_day(fresh_store):
    fresh_store.switch_user("focus_two_same_day")
    fresh_store.ledger.upsert_player_profile({
        "gender": "male", "proportions": "balanced", "age": 28, "weight_kg": 70.0,
        "height_cm": 175.0, "rep_preference": "balanced", "current_goal": "hypertrophy",
        "long_term_goal": "progressive overload", "weekly_frequency": 1, "training_age_years": 3.0,
        "equipment_access": "Commercial gym", "injuries_or_limitations": "None", "stress_and_sleep": "normal",
        "weak_points": [{"muscle": "upper_chest", "source": "named"}, {"muscle": "chest", "source": "named"}],
    })
    program = generate_program_pipeline(ledger=fresh_store.ledger)[0]
    focus = program.program_rationale["focus_muscles"]
    assert [item["muscle"] for item in focus] == ["upper_chest", "chest"]
    upper_chest = focus[0]
    assert upper_chest["status"] == "added"
    assert upper_chest["exercise_id"] == "171" or upper_chest["slot"] == "incline_press"
    chest = focus[1]
    assert chest["status"] == "covered"
    assert chest["reason"]["code"] == "focus.already_at_target"
    assert chest["reason"]["params"]["missing_weekly_sets"] == 0
    assert chest["reason"]["messages"]["en"] == (
        "Chest already gets its Focus volume from Upper chest work."
    )
    assert chest["reason"]["messages"]["ar"] == (
        "يحصل الصدر بالفعل على حجم التركيز من تمارين أعلى الصدر."
    )
    assert chest["covered_by_muscle"] == "upper_chest"
    assert (chest["day_order"], chest["exercise_id"]) == (
        upper_chest["day_order"], upper_chest["exercise_id"]
    )
    day = next(day for day in program.days if day.day_order == upper_chest["day_order"])
    _assert_focus_exercises_keep_opening_position(
        program, day, {upper_chest["exercise_id"]}
    )


def test_barbell_only_chest_extra_candidates_fall_through_to_unavailable(
    fresh_store, monkeypatch
):
    import agent.program_generator as generator

    fresh_store.switch_user("focus_barbell_only_candidates")
    fresh_store.ledger.upsert_player_profile({
        "gender": "male", "proportions": "balanced", "age": 28, "weight_kg": 70.0,
        "height_cm": 175.0, "rep_preference": "balanced", "current_goal": "hypertrophy",
        "long_term_goal": "progressive overload", "weekly_frequency": 5, "training_age_years": 3.0,
        "equipment_access": "Commercial gym", "injuries_or_limitations": "None", "stress_and_sleep": "normal",
        "weak_points": [{"muscle": "chest", "source": "named"}],
    })
    original_generate_days = generator._generate_program_days
    original_fetch = generator._fetch_generation_candidates
    generation_complete = False

    def generate_days(*args, **kwargs):
        nonlocal generation_complete
        result = original_generate_days(*args, **kwargs)
        generation_complete = True
        return result

    def fetch_candidates(slot_key, context, excluded_ids, *, ledger):
        if generation_complete and slot_key == "flat_press":
            return ([{
                "id": "barbell-row-focus-test", "name": "Barbell row signature match",
                "equipment": "barbell", "_candidate_source": "signature",
            }], False)
        return original_fetch(slot_key, context, excluded_ids, ledger=ledger)

    monkeypatch.setattr(generator, "_generate_program_days", generate_days)
    monkeypatch.setattr(generator, "_fetch_generation_candidates", fetch_candidates)
    program = generate_program_pipeline(ledger=fresh_store.ledger)[0]

    focus = program.program_rationale["focus_muscles"][0]
    assert focus["status"] == "unavailable"
    assert not any(exercise.exercise_id == "barbell-row-focus-test" for day in program.days for exercise in day.exercises)


def test_unanswered_weak_points_produce_no_focus_rationale(fresh_store):
    fresh_store.switch_user("focus_weak_points_unanswered")
    fresh_store.ledger.upsert_player_profile({
        "gender": "female", "proportions": "balanced", "age": 28, "weight_kg": 70.0,
        "height_cm": 165.0, "rep_preference": "balanced", "current_goal": "hypertrophy",
        "long_term_goal": "progressive overload", "weekly_frequency": 3, "training_age_years": 3.0,
        "equipment_access": "Commercial gym", "injuries_or_limitations": "None", "stress_and_sleep": "normal",
        "weak_points": None,
    })
    program = generate_program_pipeline(ledger=fresh_store.ledger)[0]
    assert program.program_rationale["focus_muscles"] == []


@pytest.mark.parametrize("days", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("equipment", ["Commercial gym", "Home gym", "Bodyweight only"])
def test_focus_chest_generation_supports_every_frequency_and_equipment(
    fresh_store, seed_bodyweight_curation, days, equipment
):
    if equipment == "Bodyweight only":
        seed_bodyweight_curation(fresh_store)
    fresh_store.switch_user(f"focus_axis_{days}_{equipment}")
    fresh_store.ledger.upsert_player_profile({
        "gender": "male", "proportions": "balanced", "age": 28, "weight_kg": 70.0,
        "height_cm": 175.0, "rep_preference": "balanced", "current_goal": "hypertrophy",
        "long_term_goal": "progressive overload", "weekly_frequency": days, "training_age_years": 3.0,
        "equipment_access": equipment, "injuries_or_limitations": "None", "stress_and_sleep": "normal",
        "weak_points": [{"muscle": "chest", "source": "named"}],
    })
    program = generate_program_pipeline(ledger=fresh_store.ledger)[0]
    focus = program.program_rationale["focus_muscles"][0]
    assert focus["muscle"] == "chest" and focus["source"] == "named"
    if focus["status"] == "added":
        day = next(day for day in program.days if day.day_order == focus["day_order"])
        _assert_focus_exercises_keep_opening_position(
            program, day, {focus["exercise_id"]}
        )
        assert all(
            exercise.exercise_id != focus["exercise_id"]
            for candidate_day in program.days if candidate_day is not day
            for exercise in candidate_day.exercises
        )
        set_reason = next(
            record["rationale"]["prescription"]["sets"]["params"]
            for record in program.program_rationale["days"][focus["day_order"] - 1]["exercises"]
            if record["exercise_id"] == focus["exercise_id"]
        )
        actual_weekly_sets = sum(
            exercise.working_sets for candidate_day in program.days for exercise in candidate_day.exercises
            if exercise.slot_key in {"incline_press", "flat_press", "chest_fly"}
        )
        assert actual_weekly_sets >= set_reason["target_weekly_sets"]


def test_arm_focus_extras_add_exposure_on_lightest_eligible_days(fresh_store):
    fresh_store.switch_user("focus_arms_new_exposure")
    program = _focus_draft(fresh_store, "ppl_x_ul", 5, ("biceps", "triceps"))
    extras = _focus_extra_records(program)
    by_muscle = {item["muscle"]: item for item in program.program_rationale["focus_muscles"]}
    assert any("leg" in day.day_name.casefold() or "lower" in day.day_name.casefold()
               for day, _item in extras)
    for muscle in ("biceps", "triceps"):
        focus = by_muscle[muscle]
        assert focus["day_choice_reason"]["code"] in {
            "focus.new_weekly_exposure", "focus.lightest_training_day",
        }
        assert focus["day_choice_reason"]["params"]["exposures_after"] > focus["day_choice_reason"]["params"]["exposures_before"]


def test_focus_extras_are_capped_at_two_per_day(fresh_store):
    fresh_store.switch_user("focus_day_cap")
    program = _focus_draft(fresh_store, "ppl_x_ul", 5, ("biceps", "triceps"))
    counts = {}
    for day, _item in _focus_extra_records(program):
        counts[day.day_order] = counts.get(day.day_order, 0) + 1
    assert max(counts.values()) <= 2


def test_chest_focus_extra_never_crosses_to_lower_body(fresh_store):
    fresh_store.switch_user("focus_chest_no_cross_region")
    program = _focus_draft(fresh_store, "ppl_x_ul", 5, ("chest",))
    focus = program.program_rationale["focus_muscles"][0]
    day = next(day for day in program.days if day.day_order == focus["day_order"])
    assert "leg" not in day.day_name.casefold() and "lower" not in day.day_name.casefold()
    assert focus["day_choice_reason"]["params"]["day_order"] == day.day_order


def test_focus_region_policy_covers_weak_point_vocabulary():
    from agent import focus_muscles

    policy = focus_muscles.FOCUS_REGION_POLICY
    assert set(policy) == set(WEAK_POINT_MUSCLES)
    expected = {
        **{muscle: ("upper", ()) for muscle in (
            "chest", "upper_chest", "lats", "traps", "shoulders", "rear_delts",
        )},
        **{muscle: ("upper", ("lower",)) for muscle in (
            "side_delts", "biceps", "triceps", "forearms",
        )},
        **{muscle: ("lower", ()) for muscle in ("quads", "hamstrings", "glutes")},
        "adductors": ("lower", ("upper",)),
        "calves": ("lower", ("upper",)),
        "abs": ("neutral", ("upper", "lower")),
    }
    assert {
        muscle: (entry["home_region"], entry["isolation_cross_regions"])
        for muscle, entry in policy.items()
    } == expected


def test_abs_focus_extra_adds_exposure_to_upper_day(fresh_store):
    fresh_store.switch_user("focus_abs_new_exposure")
    program = _focus_draft(fresh_store, "ppl_x_ul", 5, ("abs",))
    focus = program.program_rationale["focus_muscles"][0]
    day = next(day for day in program.days if day.day_order == focus["day_order"])
    assert day.day_name.casefold().startswith("upper")
    focus_ids_on_day = {
        item["exercise_id"]
        for extra_day, item in _focus_extra_records(program)
        if extra_day.day_order == day.day_order
    }
    assert len(focus_ids_on_day) == 1
    _assert_focus_exercises_keep_opening_position(
        program, day, focus_ids_on_day
    )
    abs_exercises = [exercise for exercise in day.exercises if exercise.slot_key == "abs"]
    assert len(abs_exercises) == 1
    assert abs_exercises[0].exercise_id in focus_ids_on_day
    extra = next(item for _day, item in _focus_extra_records(program))
    assert extra["rationale"]["day_choice"]["code"] == "focus.new_weekly_exposure"


def test_every_focus_extra_keeps_its_own_day_choice_reason(fresh_store, monkeypatch):
    import agent.program_generator as generator

    fresh_store.switch_user("focus_multiple_extra_reasons")
    original_generate_days = generator._generate_program_days

    def baseline_ten(profile, request, split_plan, ledger):
        days, rationale = original_generate_days(profile, request, split_plan, ledger)
        _set_lats_slot_baseline(days, ledger, 10)
        return days, rationale

    monkeypatch.setattr(generator, "_generate_program_days", baseline_ten)
    program = _focus_draft(fresh_store, "ppl", 3, ("lats",))
    focus = program.program_rationale["focus_muscles"][0]
    assert len(focus["extras"]) == 2
    assert all(extra["day_choice_reason"]["code"] for extra in focus["extras"])
    rationale_extras = [item for _day, item in _focus_extra_records(program)]
    assert all(item["rationale"]["day_choice"]["code"] for item in rationale_extras)
    assert len({item["rationale"]["day_choice"]["params"]["day_order"] for item in rationale_extras}) == 2
    by_id = {item["exercise_id"]: item for item in rationale_extras}
    rationale_extras = [by_id[extra["exercise_id"]] for extra in focus["extras"]]
    extra_ids = {item["exercise_id"] for item in rationale_extras}
    expected_exposures = sum(
        any(ex.slot_key in FOCUS_MUSCLE_SLOTS["lats"] and ex.exercise_id not in extra_ids
            for ex in day.exercises)
        for day in program.days
    )
    for item in rationale_extras:
        choice = item["rationale"]["day_choice"]
        before = choice["params"]["exposures_before"]
        assert before == expected_exposures
        assert choice["params"]["exposures_after"] == before + (
            1 if choice["code"] == "focus.new_weekly_exposure" else 0
        )
        if choice["code"] == "focus.new_weekly_exposure":
            expected_exposures += 1
    assert sum(ex.working_sets for day in program.days for ex in day.exercises
               if ex.slot_key in FOCUS_MUSCLE_SLOTS["lats"]) > 0


def test_focus_compound_extra_fallback_stays_in_eligible_region(fresh_store):
    fresh_store.switch_user("focus_compound_region_fallback")
    program = _focus_draft(fresh_store, "arnold_x_ul", 5, ("shoulders",))
    focus = next(item for item in program.program_rationale["focus_muscles"] if item["muscle"] == "shoulders")
    day = next(day for day in program.days if day.day_order == focus["day_order"])
    assert not ("lower" in day.day_name.casefold() or "leg" in day.day_name.casefold())


def _focus_draft(db, split_type, frequency, muscles=()):
    profile = {
        "gender": "male", "proportions": "balanced", "age": 28, "weight_kg": 70.0,
        "height_cm": 175.0, "rep_preference": "balanced", "current_goal": "hypertrophy",
        "long_term_goal": "progressive overload", "weekly_frequency": frequency,
        "training_age_years": 3.0, "equipment_access": "Commercial gym",
        "injuries_or_limitations": "None", "stress_and_sleep": "normal",
        "weak_points": [{"muscle": muscle, "source": "named"} for muscle in muscles],
    }
    request = ProgramGenerationRequest(
        user_split_override=split_type,
        frequency_override=frequency,
    )
    return generate_program_draft_pipeline(request, ledger=db.ledger, profile=profile)[0]


def _focus_extra_records(program):
    return [
        (day, item)
        for day, day_reason in zip(program.days, program.program_rationale["days"])
        for item in day_reason["exercises"]
        if item["rationale"]["selection"]["code"] == "selection.focus_muscle_extra"
    ]


def _weekly_slot_sets(program, slots):
    return sum(
        exercise.working_sets
        for day in program.days
        for exercise in day.exercises
        if exercise.slot_key in slots
    )


@pytest.mark.parametrize("muscle", ["forearms", "adductors"])
def test_nonaggregate_focus_muscles_keep_extra_gym_work(fresh_store, muscle):
    fresh_store.switch_user(f"focus_nonaggregate_{muscle}")
    baseline = _focus_draft(fresh_store, "ppl_x_ul", 5)
    focused = _focus_draft(fresh_store, "ppl_x_ul", 5, (muscle,))
    focus = focused.program_rationale["focus_muscles"][0]
    assert focus["status"] == "added"
    assert _weekly_slot_sets(focused, FOCUS_MUSCLE_SLOTS[muscle]) >= (
        _weekly_slot_sets(baseline, FOCUS_MUSCLE_SLOTS[muscle]) + 2
    )
    baseline_ids = {exercise.exercise_id for day in baseline.days for exercise in day.exercises}
    assert not baseline_ids.intersection(focus["extra_exercise_ids"])
    for day, record in _focus_extra_records(focused):
        focus_ids_on_day = {
            item["exercise_id"]
            for extra_day, item in _focus_extra_records(focused)
            if extra_day.day_order == day.day_order
        }
        _assert_focus_exercises_keep_opening_position(
            focused, day, focus_ids_on_day
        )
        dose = record["rationale"]["prescription"]["sets"]["params"]
        assert dose["actual_weekly_sets"] >= dose["target_weekly_sets"]
    credits = fresh_store.ledger.volume_review_exercise_credits(focus["extra_exercise_ids"])
    assert all(muscle not in attribution for attribution in credits.values())


def _weekly_credited_sets(program, ledger, focus_muscle):
    main_group = main_group_for_focus(focus_muscle)
    exercise_ids = [
        str(exercise.exercise_id) for day in program.days for exercise in day.exercises
    ]
    credits = ledger.volume_review_exercise_credits(exercise_ids)
    return sum(
        exercise.working_sets
        * float(
            credits.get(str(exercise.exercise_id), {}).get(main_group, {}).get("credit", 0)
        )
        for day in program.days
        for exercise in day.exercises
    )


def _set_lats_slot_baseline(days, ledger, target_weekly_sets):
    lat_exercises = [
        exercise for day in days for exercise in day.exercises
        if exercise.slot_key in FOCUS_MUSCLE_SLOTS["lats"]
    ]
    exercise_ids = [str(exercise.exercise_id) for exercise in lat_exercises]
    credits = ledger.volume_review_exercise_credits(exercise_ids)
    weekly_sets = sum(
        exercise.working_sets
        * float(
            credits.get(str(exercise.exercise_id), {}).get("lats", {}).get("credit", 0)
        )
        for exercise in lat_exercises
    )
    direct_exercise = next(
        exercise for exercise in lat_exercises
        if float(
            credits.get(str(exercise.exercise_id), {}).get("lats", {}).get("credit", 0)
        ) == 1.0
    )
    direct_exercise.set_groups[-1].sets += ceil(max(0, target_weekly_sets - weekly_sets))


def test_focus_dose_reaches_rounded_targets_with_multiple_extras(
    fresh_store, monkeypatch
):
    import agent.program_generator as generator

    fresh_store.switch_user("focus_dose_multi_extra")
    ppl_lats = _focus_draft(fresh_store, "ppl", 3, ("lats",))
    assert len(_focus_extra_records(ppl_lats)) == 1
    reason = ppl_lats.program_rationale["days"]
    lats_dose = next(
        item["rationale"]["prescription"]["sets"]["params"]
        for day in reason for item in day["exercises"]
        if item["rationale"]["selection"]["code"] == "selection.focus_muscle_extra"
    )
    assert lats_dose["target_weekly_sets"] >= lats_dose["baseline_weekly_sets"] + 2
    assert lats_dose["target_weekly_sets"] % 2 == 0
    assert lats_dose["actual_weekly_sets"] >= lats_dose["target_weekly_sets"]

    arnold_chest = _focus_draft(fresh_store, "arnold_x_ul", 5, ("chest",))
    chest_dose = next(
        item["rationale"]["prescription"]["sets"]["params"]
        for day in arnold_chest.program_rationale["days"] for item in day["exercises"]
        if item["rationale"]["selection"]["code"] == "selection.focus_muscle_extra"
    )
    assert chest_dose["actual_weekly_sets"] >= chest_dose["target_weekly_sets"]

    original_generate_days = generator._generate_program_days

    def baseline_ten(profile, request, split_plan, ledger):
        days, rationale = original_generate_days(profile, request, split_plan, ledger)
        _set_lats_slot_baseline(days, ledger, 10)
        return days, rationale

    monkeypatch.setattr(generator, "_generate_program_days", baseline_ten)
    synthetic = _focus_draft(fresh_store, "ppl", 3, ("lats",))
    synthetic_records = _focus_extra_records(synthetic)
    synthetic_dose = synthetic_records[0][1]["rationale"]["prescription"]["sets"]["params"]
    assert synthetic_dose["baseline_weekly_sets"] == 11
    assert synthetic_dose["target_weekly_sets"] == 14
    assert synthetic_dose["actual_weekly_sets"] >= 14
    assert len(synthetic_records) == 2

    original_candidate_search = generator.fetch_slot_candidates
    generation_complete = False

    def only_one_extra_variant(slot_key, equipment, limitations, limit=6, *, ledger):
        if generation_complete:
            if slot_key != "pullover":
                return []
            return original_candidate_search(
                slot_key, equipment, limitations, limit, ledger=ledger
            )[:1]
        return original_candidate_search(
            slot_key, equipment, limitations, limit, ledger=ledger
        )

    def mark_generation_complete(*args, **kwargs):
        nonlocal generation_complete
        result = baseline_ten(*args, **kwargs)
        generation_complete = True
        return result

    monkeypatch.setattr(generator, "_generate_program_days", mark_generation_complete)
    monkeypatch.setattr(generator, "fetch_slot_candidates", only_one_extra_variant)
    limited = _focus_draft(fresh_store, "ppl", 3, ("lats",))
    focus_reason = limited.program_rationale["focus_muscles"][0]
    assert focus_reason["status"] == "added"
    assert focus_reason["reason"]["code"] == "focus.unavailable"
    assert focus_reason["reason"]["params"]["missing_weekly_sets"] == 1


# #713: a muscle can be covered by credited work from the other named Focus.
def test_focus_rubric_covers_every_selectable_split_and_frequency(fresh_store):
    fresh_store.switch_user("focus_split_muscle_rubric")
    pairs = (
        ("chest", "quads"), ("upper_chest", "glutes"),
        ("lats", "side_delts"), ("traps", "rear_delts"),
    )
    for frequency, options in SPLIT_OPTIONS_BY_FREQUENCY.items():
        for split_type, _display_name in options:
            baseline = _focus_draft(fresh_store, split_type, frequency)
            baseline_ids = {
                exercise.exercise_id for day in baseline.days for exercise in day.exercises
            }
            for pair in pairs:
                focused = _focus_draft(fresh_store, split_type, frequency, pair)
                extra_records = _focus_extra_records(focused)
                extra_ids = {item["exercise_id"] for _, item in extra_records}
                assert len(extra_ids) == len(extra_records)
                assert not extra_ids.intersection(baseline_ids)
                for muscle in pair:
                    focus = next(
                        item for item in focused.program_rationale["focus_muscles"]
                        if item["muscle"] == muscle
                    )
                    assert focus["status"] in {"added", "covered"}, (
                        split_type, frequency, muscle, focus["status"]
                    )
                    if focus["status"] == "covered":
                        assert focus["reason"]["code"] == "focus.already_at_target"
                        covered = focus["reason"]["params"]
                        assert covered["missing_weekly_sets"] == 0
                        assert covered["actual_weekly_sets"] >= covered["target_weekly_sets"]
                        continue
                    dose = next(
                        item["rationale"]["prescription"]["sets"]["params"]
                        for _, item in extra_records
                        if item["rationale"]["selection"]["params"]["muscle"] == muscle
                    )
                    actual = _weekly_credited_sets(focused, fresh_store.ledger, muscle)
                    assert dose["actual_weekly_sets"] == actual
                    assert actual >= dose["target_weekly_sets"]
                for day, item in extra_records:
                    focus_ids_on_day = {
                        candidate["exercise_id"]
                        for extra_day, candidate in extra_records if extra_day.day_order == day.day_order
                    }
                    _assert_focus_exercises_keep_opening_position(
                        focused, day, focus_ids_on_day
                    )
                focused_slots = set().union(*(FOCUS_MUSCLE_SLOTS[muscle] for muscle in pair))
                for muscle in set(FOCUS_MUSCLE_SLOTS) - set(pair):
                    unchanged_slots = FOCUS_MUSCLE_SLOTS[muscle] - focused_slots
                    if not unchanged_slots:
                        continue
                    assert _weekly_slot_sets(focused, unchanged_slots) == _weekly_slot_sets(
                        baseline, unchanged_slots
                    ), (split_type, frequency, muscle)


def test_bodyweight_quad_isolation_uses_curated_sissy_squat(
    fresh_store, seed_bodyweight_curation
):
    seed_bodyweight_curation(fresh_store)
    entry = fresh_store.get_exercise_library_entry("1489")
    assert (entry["primary_action"], entry["primary_muscle"], entry["equipment"]) == (
        "Knee Extension", "Quads", "body weight"
    ), entry
    assert fresh_store.is_exercise_library_exercise_visible("1489")
    program = _generate_matrix_program(
        fresh_store,
        experience="beginner",
        days=3,
        equipment="Bodyweight only",
    )
    selected = [
        (exercise.exercise_id, exercise.slot_key)
        for day in program.days
        for exercise in day.exercises
    ]
    assert ("1489", "quad_iso") in selected, [
        item for item in selected if item[1].startswith("quad") or item[0] == "1489"
    ]


@pytest.mark.parametrize("experience", ["beginner", "intermediate", "advanced"])
@pytest.mark.parametrize("days", [3, 4, 5])
@pytest.mark.parametrize("equipment", ["Commercial gym", "Home gym", "Bodyweight only"])
def test_generated_programs_pass_the_coach_pattern_rubric(
    fresh_store, seed_bodyweight_curation, experience, days, equipment, request
):
    db = fresh_store
    if equipment != "Commercial gym":
        # This rubric requires exact library staples for home/bodyweight access,
        # including ids without a tracked id/name relationship.
        db = request.getfixturevalue("real_library_store")
    if equipment == "Bodyweight only":
        seed_bodyweight_curation(db)
    program = _generate_matrix_program(
        db,
        experience=experience,
        days=days,
        equipment=equipment,
    )

    expected_split = {
        3: "Full Body Tri-Phase",
        4: "Upper / Lower (Arms & Delts Augmented)",
        5: "PPL × UL",
    }[days]
    assert program.split_type == expected_split
    assert len(program.days) == days
    rationale = program.program_rationale
    assert rationale is not None
    assert rationale["split"]["code"] in {
        "split.frequency_default", "split.lifter_request", "split.coach_pick",
        "split.unsupported_frequency",
    }
    if expected_split == "PPL × UL":
        assert rationale["day_order"]["code"] == "day_order.ppl_x_ul_spaces_leg_days"
    assert len(rationale["days"]) == len(program.days)
    for program_day, rationale_day in zip(program.days, rationale["days"]):
        assert len(rationale_day["exercises"]) == len(program_day.exercises)
        for position, exercise_record in enumerate(rationale_day["exercises"], start=1):
            assert exercise_record["position"] == position
            assert exercise_record["exercise_id"] == program_day.exercises[position - 1].exercise_id
            exercise_reasons = exercise_record["rationale"]
            expected_reasons = {"selection", "position", "prescription"}
            if exercise_reasons["selection"]["code"] == "selection.focus_muscle_extra":
                expected_reasons.add("day_choice")
            assert set(exercise_reasons) == expected_reasons
            assert exercise_reasons["selection"]["code"].startswith("selection.")
            assert exercise_reasons["position"]["code"].startswith("position.")
            assert set(exercise_reasons["prescription"]) == {"sets", "reps", "rir", "rest"}
            assert all(
                reason["code"]
                for reason in exercise_reasons["prescription"].values()
            )
    for muscle, slots in MUSCLE_GROUPS.items():
        if equipment == "Bodyweight only" and muscle == "shoulders":
            slots = {"shoulder_press"}
        exercises_by_day = [
            [exercise for exercise in day.exercises if exercise.slot_key in slots]
            for day in program.days
        ]
        exercises = [exercise for day in exercises_by_day for exercise in day]
        weekly_sets = sum(exercise.working_sets for exercise in exercises)
        frequency = sum(bool(day) for day in exercises_by_day)
        if equipment == "Bodyweight only" and muscle in BODYWEIGHT_RUBRIC_EXCEPTIONS:
            expected_sets, expected_frequency, _reason = BODYWEIGHT_RUBRIC_EXCEPTIONS[muscle]
            assert (weekly_sets, frequency) == (expected_sets, expected_frequency), (
                f"{muscle}: expected {expected_sets} sets/{expected_frequency} days, "
                f"got {weekly_sets} sets/{frequency} days"
            )
            continue
        assert 4 <= weekly_sets <= 6, f"{muscle}: {weekly_sets} sets"
        assert 2 <= frequency <= 3, f"{muscle}: trained {frequency} days"

    slots = {exercise.slot_key for day in program.days for exercise in day.exercises}
    assert {"calf", "adductors"} <= slots
    if equipment == "Bodyweight only":
        assert not {"side_delts", "ham_hinge"} & slots
        for slot, expected in BODYWEIGHT_SLOT_EXCEPTION_VALUES.items():
            selected = [
                exercise for exercise in exercises if exercise.slot_key == slot
            ]
            assert (
                sum(exercise.working_sets for exercise in selected),
                sum(any(exercise.slot_key == slot for exercise in day.exercises) for day in program.days),
            ) == expected, f"{slot}: expected {expected} sets/days"

    exercises = [exercise for day in program.days for exercise in day.exercises]
    if equipment == "Bodyweight only":
        assert all((exercise.equipment or "").casefold() == "body weight" for exercise in exercises)
        if days == 5:
            pull_days = [day for day in program.days if "pull" in day.day_name.casefold()]
            assert pull_days
            assert all(
                any(exercise.slot_key == "vertical_pull" for exercise in day.exercises)
                for day in pull_days
            )
            assert all(len(day.exercises) >= 3 for day in pull_days)
    for staple_slot in CORE_STAPLE_SLOTS:
        if staple_slot == "shrug" and (
            days == 3
            or expected_split in {
                "Upper / Lower (Arms & Delts Augmented)", "PPL × UL",
            }
        ):
            # Separate row days meet the traps dose; shrug is an optional third exposure.
            continue
        if equipment == "Bodyweight only" and staple_slot in BODYWEIGHT_STAPLE_EXCEPTIONS:
            continue
        if equipment == "Bodyweight only":
            acceptable_staples = BODYWEIGHT_STAPLE_EQUIVALENTS.get(
                staple_slot,
                {(staple_slot, exercise_id) for exercise_id in SLOT_STAPLES[staple_slot]},
            )
        else:
            acceptable_staples = {
                (staple_slot, exercise_id) for exercise_id in SLOT_STAPLES[staple_slot]
            }
        assert any(
            (exercise.slot_key, exercise.exercise_id) in acceptable_staples
            for exercise in exercises
        ), f"No staple selected for {staple_slot}"

    muscle_for_slot = {
        slot: muscle for muscle, muscle_slots in MUSCLE_GROUPS.items() for slot in muscle_slots
    }
    for day in program.days:
        main_exercise = _main_progressed_exercise(program, day)
        if main_exercise:
            assert day.exercises[0] is main_exercise
        elif equipment == "Bodyweight only":
            assert not any(
                SLOT_SPECS[exercise.slot_key].archetype in COMPOUND_CLASSES
                for exercise in day.exercises
            )
            assert day.exercises[0].slot_key != "calf"
        else:
            assert day.exercises[0].slot_key in SMALL_MUSCLE_OPENERS
        if experience == "beginner":
            compound_indexes = [
                index for index, exercise in enumerate(day.exercises)
                if SLOT_SPECS[exercise.slot_key].archetype in COMPOUND_CLASSES
            ]
            isolation_indexes = [
                index for index, exercise in enumerate(day.exercises)
                if SLOT_SPECS[exercise.slot_key].archetype == "isolation"
            ]
            if compound_indexes and isolation_indexes:
                assert max(compound_indexes) < min(isolation_indexes)
        for index in range(len(day.exercises) - 2):
            pre_exhaust, first_compound, second_compound = day.exercises[index : index + 3]
            compound_slots = (first_compound.slot_key, second_compound.slot_key)
            if (
                SLOT_SPECS[pre_exhaust.slot_key].archetype == "isolation"
                and all(SLOT_SPECS[slot].archetype in COMPOUND_CLASSES for slot in compound_slots)
                and len({muscle_for_slot[pre_exhaust.slot_key], *(muscle_for_slot[slot] for slot in compound_slots)}) == 1
            ):
                pytest.fail(f"{day.day_name} puts two same-muscle compounds after a pre-exhaust")

    if equipment == "Commercial gym":
        gym_equipment = sum(
            any(term in (exercise.equipment or "").casefold() for term in ("machine", "cable", "smith"))
            for exercise in exercises
        )
        assert gym_equipment > len(exercises) / 2
        assert all(
            (exercise.equipment or "").casefold() not in {"band", "resistance band", "body weight", "bodyweight"}
            for exercise in exercises
        )


def test_bodyweight_classic_split_keeps_its_blueprint_opener(fresh_store):
    fresh_store.switch_user("bodyweight_classic_ppl")
    fresh_store.ledger.upsert_player_profile(
        {
            "gender": "male",
            "proportions": "balanced",
            "age": 28,
            "weight_kg": 70.0,
            "height_cm": 175.0,
            "rep_preference": "balanced",
            "current_goal": "hypertrophy",
            "long_term_goal": "progressive overload",
            "weekly_frequency": 3,
            "training_age_years": 3.0,
            "equipment_access": "Bodyweight only",
            "injuries_or_limitations": "None",
            "stress_and_sleep": "normal",
        }
    )
    program = generate_program_pipeline(user_split_override="PPL", ledger=fresh_store.ledger)[0]

    legs = next(day for day in program.days if "leg" in day.day_name.lower())
    assert legs.exercises[0].slot_key == "quad_compound"


def test_coach_pattern_rubric_accepts_missing_adductors_and_ham_curl_when_restricted(fresh_store):
    db = fresh_store
    db.ledger.upsert_player_profile({
        "gender": "male", "proportions": "balanced", "age": 28,
        "weight_kg": 75.0, "height_cm": 175.0, "rep_preference": "balanced",
        "current_goal": "hypertrophy", "long_term_goal": "progressive overload",
        "weekly_frequency": 3, "training_age_years": 3.0,
        "equipment_access": "Commercial gym", "injuries_or_limitations": "None",
        "stress_and_sleep": "normal", "movement_restrictions": ["Knee flexion", "Hip adduction"],
    })
    from agent.program_generator import generate_program_pipeline
    program = generate_program_pipeline(ledger=db.ledger)[0]
    exercises = [exercise for day in program.days for exercise in day.exercises]
    restricted_slots = {"ham_curl", "adductors"}
    assert not {exercise.slot_key for exercise in exercises} & restricted_slots
    assert len(program.days) == 3
    for muscle, slots in MUSCLE_GROUPS.items():
        if muscle in {"hamstrings", "adductors"}:
            continue
        count = sum(ex.working_sets for ex in exercises if ex.slot_key in slots)
        assert 4 <= count <= 6, f"{muscle}: {count} sets"
