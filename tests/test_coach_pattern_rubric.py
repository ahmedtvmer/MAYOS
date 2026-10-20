"""Plain pytest rubric for the deterministic coach-pattern program generator."""

import json
from pathlib import Path

import pytest

from agent.program_generator import generate_program_pipeline
from agent.program_blueprints import SLOT_SPECS, SLOT_STAPLES


MUSCLE_GROUPS = {
    "chest": {"incline_press", "flat_press", "chest_fly"},
    "back": {"vertical_pull", "horizontal_row", "upper_back_pull", "pullover", "shrug"},
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
# Some bodyweight-only day blueprints have no available small-muscle opener.
BODYWEIGHT_OPENER_FALLBACKS = {
    "flat_press", "horizontal_row", "biceps_alt", "glute_thrust",
    "vertical_pull",
}


def _generate_matrix_program(db, *, experience, days, equipment, glute_priority):
    user = f"coach_rubric_{experience}_{days}_{equipment}_{glute_priority}"
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
    split = "female_full_body" if glute_priority else None
    return generate_program_pipeline(user_split_override=split, ledger=db.ledger)[0]


@pytest.fixture
def seed_bodyweight_curation(tmp_path, monkeypatch):
    from database.exercise_library import embeddings
    from database.exercise_library.curation import DEFAULT_CURATION_CSV_PATH
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
        db.initialize_and_seed(seed_path, DEFAULT_CURATION_CSV_PATH)

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
                        "target_sets": exercise.target_sets,
                    }
                    for exercise in day.exercises
                ],
            }
            for day in program.days
        ],
    }


def test_commercial_and_home_program_outputs_match_baseline_snapshot(fresh_store):
    snapshot_path = Path(__file__).parent / "fixtures" / "coach_pattern_program_baseline.json"
    expected = json.loads(snapshot_path.read_text())
    actual = {}
    for equipment in ("Commercial gym", "Home gym"):
        for experience in ("beginner", "intermediate", "advanced"):
            for days in (3, 4, 5):
                for glute_priority in (False, True):
                    key = f"{experience}|{days}|{equipment}|{str(glute_priority).lower()}"
                    program = _generate_matrix_program(
                        fresh_store,
                        experience=experience,
                        days=days,
                        equipment=equipment,
                        glute_priority=glute_priority,
                    )
                    actual[key] = _program_snapshot(program)
    assert actual == expected


@pytest.mark.parametrize("days", [3, 4, 5])
def test_bodyweight_only_does_not_relabel_ham_curl_as_ham_hinge(fresh_store, days):
    program = _generate_matrix_program(
        fresh_store,
        experience="beginner",
        days=days,
        equipment="Bodyweight only",
        glute_priority=False,
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
        glute_priority=False,
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
@pytest.mark.parametrize("glute_priority", [False, True])
def test_generated_programs_pass_the_coach_pattern_rubric(
    fresh_store, seed_bodyweight_curation, experience, days, equipment, glute_priority
):
    db = fresh_store
    if equipment == "Bodyweight only":
        seed_bodyweight_curation(db)
    program = _generate_matrix_program(
        db,
        experience=experience,
        days=days,
        equipment=equipment,
        glute_priority=glute_priority,
    )

    expected_split = (
        "Full Body (Glute Priority)"
        if glute_priority
        else {
            3: "Full Body Tri-Phase",
            4: "Upper / Lower (Arms & Delts Augmented)",
            5: "PPL × UL",
        }[days]
    )
    assert program.split_type == expected_split
    assert len(program.days) == days
    for muscle, slots in MUSCLE_GROUPS.items():
        if equipment == "Bodyweight only" and muscle == "shoulders":
            slots = {"shoulder_press"}
        exercises_by_day = [
            [exercise for exercise in day.exercises if exercise.slot_key in slots]
            for day in program.days
        ]
        exercises = [exercise for day in exercises_by_day for exercise in day]
        weekly_sets = sum(exercise.target_sets for exercise in exercises)
        frequency = sum(bool(day) for day in exercises_by_day)
        expected_glute_sets = (6 if glute_priority else 4) if muscle == "glutes" else None
        if equipment == "Bodyweight only" and muscle in BODYWEIGHT_RUBRIC_EXCEPTIONS:
            expected_sets, expected_frequency, _reason = BODYWEIGHT_RUBRIC_EXCEPTIONS[muscle]
            assert (weekly_sets, frequency) == (expected_sets, expected_frequency), (
                f"{muscle}: expected {expected_sets} sets/{expected_frequency} days, "
                f"got {weekly_sets} sets/{frequency} days"
            )
            continue
        if expected_glute_sets is None:
            assert 4 <= weekly_sets <= 6, f"{muscle}: {weekly_sets} sets"
        else:
            assert weekly_sets == expected_glute_sets, f"glutes: {weekly_sets} sets"
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
                sum(exercise.target_sets for exercise in selected),
                sum(any(exercise.slot_key == slot for exercise in day.exercises) for day in program.days),
            ) == expected, f"{slot}: expected {expected} sets/days"

    exercises = [exercise for day in program.days for exercise in day.exercises]
    if equipment == "Bodyweight only":
        assert all((exercise.equipment or "").casefold() == "body weight" for exercise in exercises)
        if days == 5 and not glute_priority:
            pull_days = [day for day in program.days if "pull" in day.day_name.casefold()]
            assert pull_days
            assert all(
                any(exercise.slot_key == "vertical_pull" for exercise in day.exercises)
                for day in pull_days
            )
            assert all(len(day.exercises) >= 3 for day in pull_days)
    for staple_slot in CORE_STAPLE_SLOTS:
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
        available_small_openers = [
            exercise.slot_key for exercise in day.exercises
            if exercise.slot_key in SMALL_MUSCLE_OPENERS
        ]
        if equipment == "Bodyweight only" and not available_small_openers:
            assert day.exercises[0].slot_key in BODYWEIGHT_OPENER_FALLBACKS
        else:
            assert day.exercises[0].slot_key == available_small_openers[0]
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
