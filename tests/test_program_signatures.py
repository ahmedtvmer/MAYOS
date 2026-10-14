"""Signature-first program generation behavior."""

import gzip
import json
from pathlib import Path

import pytest

from agent import program_generator
from agent.program_blueprints import SLOT_STAPLES
from agent.ProgramState import CustomDayPlan
from agent.program_rules import NO_LIMITATIONS, fetch_slot_candidates
from utils.equipment_access import (
    BODYWEIGHT_ONLY,
    COMMERCIAL_GYM,
    HOME_GYM,
    equipment_access_allows,
)


def _insert_exercises(store, rows):
    with store.catalog_conn:
        store.catalog_conn.executemany(
            "INSERT INTO exercises "
            "(id, name, body_part, target_muscle, equipment, instructions) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )


def _profile(equipment_access, gender, frequency, limitations="None"):
    return {
        "gender": gender,
        "proportions": "balanced",
        "age": 28,
        "weight_kg": 80.0,
        "height_cm": 175.0,
        "rep_preference": "balanced",
        "current_goal": "hypertrophy",
        "long_term_goal": "progressive overload",
        "weekly_frequency": frequency,
        "training_age_years": 3.0,
        "equipment_access": equipment_access,
        "injuries_or_limitations": limitations,
        "stress_and_sleep": "normal",
    }


def _generate_program(store, profile, preference=None, user_suffix=None):
    user = "program_signature_" + "_".join(
        (profile["equipment_access"], profile["gender"], str(profile["weekly_frequency"]))
    ).replace(" ", "_")
    if user_suffix:
        user = f"{user}_{user_suffix.replace(' ', '_')}"
    store.switch_user(user)
    store.ledger.upsert_player_profile(profile)
    return program_generator.generate_program_pipeline(
        user_split_override=preference, ledger=store.ledger
    )[0]


def test_automatic_generator_persists_one_repeating_program_week(fresh_store):
    generated = _generate_program(
        fresh_store, _profile(COMMERCIAL_GYM, "male", 3), "Full Body"
    )

    active = fresh_store.ledger.get_active_program()

    assert len(generated.days) == 3
    assert len(active.weeks) == 1
    assert active.weeks[0].week_order == 1
    assert [day.week_order for day in active.days] == [1, 1, 1]


def test_bodyweight_flat_press_prefers_standard_push_up(fresh_store):
    candidates = fetch_slot_candidates(
        "flat_press", BODYWEIGHT_ONLY, limit=100, ledger=fresh_store.ledger
    )
    day = CustomDayPlan(
        day_order=1,
        day_name="Bodyweight flat press",
        target_slots=["flat_press", "biceps_alt", "calf"],
        warmup_family="upper",
    )
    context = program_generator.DayGenerationContext(
        equipment_access=BODYWEIGHT_ONLY,
        limitations=NO_LIMITATIONS,
        rep_preference="balanced",
        recovery_cut=False,
        experience_level="intermediate",
    )
    generated = program_generator.assemble_deterministic_day(
        day, context, set(), ledger=fresh_store.ledger
    )
    flat_press = next(
        exercise for exercise in generated.exercises if exercise.slot_key == "flat_press"
    )

    assert candidates
    assert str(candidates[0]["id"]) == "662"
    assert flat_press.exercise_id == "662"


@pytest.mark.parametrize(
    ("slot_key", "excluded_ids"),
    [
        (
            "flat_press",
            {"33", "1300", "301", "302", "303", "1260", "342", "531", "664"},
        ),
        ("incline_press", {"171", "319", "279"}),
        ("horizontal_row", {"1349", "1351", "1313", "293", "292"}),
        ("quad_compound", {"24", "1759", "53", "514"}),
        ("biceps_alt", {"592", "70"}),
    ],
)
def test_curated_signature_rows_keep_existing_slot_exclusions(
    fresh_store, slot_key, excluded_ids
):
    candidates = fetch_slot_candidates(
        slot_key, HOME_GYM, limit=100, ledger=fresh_store.ledger
    )

    assert excluded_ids.isdisjoint({str(candidate["id"]) for candidate in candidates})


def test_home_gym_suggestions_keep_decline_and_incline_fly_exclusions(fresh_store):
    program = _generate_program(
        fresh_store, _profile(HOME_GYM, "male", 3), "Full Body"
    )
    suggestions_by_slot = {
        slot_key: {
            substitute.exercise_id
            for day in program.days
            for exercise in day.exercises
            if exercise.slot_key == slot_key
            for substitute in exercise.suggested_substitutes
        }
        for slot_key in ("flat_press", "incline_press")
    }

    assert suggestions_by_slot["flat_press"]
    assert suggestions_by_slot["incline_press"]
    assert "33" not in suggestions_by_slot["flat_press"]
    assert "319" not in suggestions_by_slot["incline_press"]


def test_coach_pattern_program_ids_are_stable_across_experience_levels(
    fresh_store,
):
    """Pin coach-pattern output ids across frequencies and experience tiers."""
    expected_by_frequency = {
        3: [
            ["1375", "743", "869", "314", "150", "598", "592", "599", "1723"],
            ["1375", "1350", "576", "mayos:4", "175", "318", "1412", "178", "194"],
            ["598", "85", "175", "596", "1411", "2286", "585", "mayos:3", "305"],
        ],
        4: [
            ["178", "85", "314", "175", "318", "2286", "194"],
            ["598", "1350", "576", "mayos:4", "1412", "1723"],
            ["598", "1375", "596", "1411", "585", "mayos:3", "305"],
            ["175", "743", "869", "150", "592", "1375", "599"],
        ],
        5: [
            ["598", "mayos:4", "314", "592", "194"],
            ["1375", "743", "576", "175", "1412", "305"],
            ["175", "869", "1375", "596", "1411", "585"],
            ["178", "150", "318", "2286", "599"],
            ["598", "85", "1350", "mayos:3", "1723"],
        ],
    }

    for frequency, expected_ids in expected_by_frequency.items():
        for training_age in (1.0, 3.0, 6.0):
            profile = _profile(COMMERCIAL_GYM, "male", frequency)
            profile["training_age_years"] = training_age
            program = _generate_program(fresh_store, profile, "Full Body")
            actual_ids = [
                [exercise.exercise_id for exercise in day.exercises]
                for day in program.days
            ]

            assert actual_ids == expected_ids, (frequency, training_age)


def test_commercial_horizontal_row_exhaustion_keeps_master_candidates(fresh_store):
    day = CustomDayPlan(
        day_order=1,
        day_name="Repeated commercial horizontal rows",
        target_slots=["horizontal_row"] * 6,
        warmup_family="upper",
    )
    context = program_generator.DayGenerationContext(
        equipment_access=COMMERCIAL_GYM,
        limitations=NO_LIMITATIONS,
        rep_preference="balanced",
        recovery_cut=False,
        experience_level="intermediate",
    )
    generated = program_generator.assemble_deterministic_day(
        day, context, set(), ledger=fresh_store.ledger
    )
    horizontal_row_ids = [exercise.exercise_id for exercise in generated.exercises]

    assert horizontal_row_ids == ["1350", "327", "571", "588", "1348", "3200"]
    assert {"1349", "1351", "1313", "293", "292"}.isdisjoint(horizontal_row_ids)


def _seed_flat_press_fixture(store, seed_exercise_curation, curated_ids):
    rows = [
        ("361:signature", "bodyweight bench press signature", "chest", "pectorals", "body weight", None),
        ("361:uncurated", "bodyweight flat press uncurated", "chest", "pectorals", "body weight", None),
        ("361:mismatch", "bodyweight chest press wrong movement", "chest", "pectorals", "body weight", None),
    ]
    _insert_exercises(store, rows)
    curation = {
        exercise_id: {
            "primary_action": action,
            "primary_muscle": muscle,
            "display_name": f"Curated {exercise_id}",
        }
        for exercise_id, (action, muscle) in curated_ids.items()
    }
    seed_exercise_curation(store, curation)


def test_signature_match_precedes_uncurated_pattern_and_rejects_mismatch(
    fresh_store, seed_exercise_curation
):
    _seed_flat_press_fixture(
        fresh_store,
        seed_exercise_curation,
        {
            "361:signature": ("Shoulder Horizontal Adduction", "Chest"),
            "361:mismatch": ("Shoulder Flexion", "Front Delts"),
        },
    )

    candidates = fetch_slot_candidates(
        "flat_press", BODYWEIGHT_ONLY, limit=100, ledger=fresh_store.ledger
    )
    assert "361:mismatch" not in {str(candidate["id"]) for candidate in candidates}

    program = _generate_program(
        fresh_store, _profile(BODYWEIGHT_ONLY, "male", 3), "Full Body"
    )
    flat_press = next(
        exercise
        for exercise in program.days[0].exercises
        if exercise.slot_key == "flat_press"
    )

    assert flat_press.exercise_id == "361:signature"


@pytest.mark.parametrize("equipment_access", [BODYWEIGHT_ONLY, HOME_GYM])
def test_equipment_access_uses_allowed_signature_before_slot_fallback(
    fresh_store, equipment_access
):
    with fresh_store.catalog_conn:
        fresh_store.catalog_conn.execute(
            "UPDATE exercises SET equipment = 'cable' "
            "WHERE id IN (SELECT exercise_id FROM exercise_curated_fields "
            "WHERE primary_action = 'Shoulder Horizontal Adduction' "
            "AND primary_muscle = 'Chest' AND exercise_id != '662')"
        )
        fresh_store.catalog_conn.executemany(
            "UPDATE exercises SET equipment = 'cable' WHERE id = ?",
            [(staple_id,) for staple_id in SLOT_STAPLES["flat_press"]],
        )
        fresh_store.catalog_conn.execute(
            "UPDATE exercises SET equipment = 'body weight' WHERE id = '662'"
        )

    day = CustomDayPlan(
        day_order=1,
        day_name="Equipment signature fallback",
        target_slots=["flat_press", "biceps_alt", "calf"],
        warmup_family="upper",
    )
    context = program_generator.DayGenerationContext(
        equipment_access=equipment_access,
        limitations=NO_LIMITATIONS,
        rep_preference="balanced",
        recovery_cut=False,
        experience_level="intermediate",
    )
    generated = program_generator.assemble_deterministic_day(
        day, context, set(), ledger=fresh_store.ledger
    )
    flat_press = next(
        exercise for exercise in generated.exercises if exercise.slot_key == "flat_press"
    )

    assert flat_press.exercise_id == "662"
    assert equipment_access_allows(
        equipment_access,
        fresh_store.get_exercise_library_entry(flat_press.exercise_id)["equipment"],
    )


def test_equipment_slot_fallback_waits_until_no_allowed_signature_exists(fresh_store):
    with fresh_store.catalog_conn:
        fresh_store.catalog_conn.execute(
            "UPDATE exercises SET equipment = 'dumbbell' "
            "WHERE id IN (SELECT exercise_id FROM exercise_curated_fields "
            "WHERE primary_action = 'Shoulder Horizontal Adduction' "
            "AND primary_muscle = 'Chest')"
        )
        fresh_store.catalog_conn.executemany(
            "UPDATE exercises SET equipment = 'dumbbell' WHERE id = ?",
            [(staple_id,) for staple_id in SLOT_STAPLES["flat_press"]],
        )

    day = CustomDayPlan(
        day_order=1,
        day_name="No allowed signature",
        target_slots=["flat_press", "biceps_alt", "calf"],
        warmup_family="upper",
    )
    context = program_generator.DayGenerationContext(
        equipment_access=BODYWEIGHT_ONLY,
        limitations=NO_LIMITATIONS,
        rep_preference="balanced",
        recovery_cut=False,
        experience_level="intermediate",
    )
    generated = program_generator.assemble_deterministic_day(
        day, context, set(), ledger=fresh_store.ledger
    )

    assert "flat_press" not in {exercise.slot_key for exercise in generated.exercises}
    assert {"quad_lunge", "vertical_pull"} & {
        exercise.slot_key for exercise in generated.exercises
    }


def test_suggested_substitutes_top_up_ordered_staples_with_signature_matches(
    fresh_store, seed_exercise_curation
):
    signature_ids = ("362:signature-a", "362:signature-b")
    hidden_id = "362:hidden-signature"
    _insert_exercises(
        fresh_store,
        [
            (signature_ids[0], "synthetic signature press A", "chest", "pectorals", "dumbbell", None),
            (signature_ids[1], "synthetic signature press B", "chest", "pectorals", "dumbbell", None),
            (hidden_id, "synthetic hidden signature press", "chest", "pectorals", "dumbbell", None),
        ],
    )
    seed_exercise_curation(
        fresh_store,
        {
            signature_ids[0]: {
                "primary_action": "Shoulder Horizontal Adduction",
                "primary_muscle": "Chest",
                "display_name": "A Signature Press",
            },
            signature_ids[1]: {
                "primary_action": "Shoulder Horizontal Adduction",
                "primary_muscle": "Chest",
                "display_name": "B Signature Press",
            },
            hidden_id: {
                "primary_action": "Shoulder Horizontal Adduction",
                "primary_muscle": "Chest",
                "hidden": True,
            },
        },
    )
    with fresh_store.catalog_conn:
        fresh_store.catalog_conn.execute(
            "UPDATE exercises SET equipment = 'cable' "
            "WHERE id IN (SELECT exercise_id FROM exercise_curated_fields "
            "WHERE primary_action = 'Shoulder Horizontal Adduction' "
            "AND primary_muscle = 'Chest' AND exercise_id NOT LIKE '362:%')"
        )
        fresh_store.catalog_conn.executemany(
            "UPDATE exercises SET equipment = 'cable' WHERE id = ?",
            [
                (staple_id,)
                for staple_id in SLOT_STAPLES["flat_press"]
                if staple_id not in {"25", "289"}
            ],
        )
        fresh_store.catalog_conn.execute(
            "UPDATE exercises SET equipment = 'barbell' WHERE id = '25'"
        )
        fresh_store.catalog_conn.execute(
            "UPDATE exercises SET equipment = 'dumbbell' WHERE id = '289'"
        )

    day = CustomDayPlan(
        day_order=1,
        day_name="Suggested signature substitutes",
        target_slots=["flat_press", "horizontal_row", "calf"],
        warmup_family="upper",
    )
    context = program_generator.DayGenerationContext(
        equipment_access=HOME_GYM,
        limitations=NO_LIMITATIONS,
        rep_preference="balanced",
        recovery_cut=False,
        experience_level="intermediate",
    )
    generated = program_generator.assemble_deterministic_day(
        day, context, set(), ledger=fresh_store.ledger
    )
    flat_press = next(
        exercise for exercise in generated.exercises if exercise.slot_key == "flat_press"
    )

    assert flat_press.exercise_id == "25"
    assert [item.exercise_id for item in flat_press.suggested_substitutes] == [
        "289",
        signature_ids[0],
    ]
    assert hidden_id not in {
        item.exercise_id
        for exercise in generated.exercises
        for item in exercise.suggested_substitutes
    }
    assert all(
        item.exercise_id != exercise.exercise_id
        for exercise in generated.exercises
        for item in exercise.suggested_substitutes
    )


def test_name_pattern_fallback_skips_curated_signature_mismatches(
    fresh_store, seed_exercise_curation
):
    _seed_flat_press_fixture(
        fresh_store,
        seed_exercise_curation,
        {
            "361:signature": ("Shoulder Flexion", "Front Delts"),
            "361:mismatch": ("Shoulder Flexion", "Front Delts"),
        },
    )

    program = _generate_program(
        fresh_store, _profile(BODYWEIGHT_ONLY, "male", 3), "Full Body"
    )
    flat_press_exercises = [
        exercise
        for day in program.days
        for exercise in day.exercises
        if exercise.slot_key == "flat_press"
    ]
    candidates = fetch_slot_candidates(
        "flat_press", BODYWEIGHT_ONLY, limit=100, ledger=fresh_store.ledger
    )

    assert "361:uncurated" in {str(candidate["id"]) for candidate in candidates}
    assert "361:uncurated" not in {
        exercise.exercise_id for day in program.days for exercise in day.exercises
    }
    assert not {"361:signature", "361:mismatch"} & {
        exercise.exercise_id for exercise in flat_press_exercises
    }


def test_replace_signature_rank_precedes_slot_equipment_preference(
    fresh_store, seed_exercise_curation
):
    rows = [
        ("361:rank-0", "synthetic glute movement exact", "glutes", "glutes", "resistance band", None),
        ("361:rank-1", "synthetic glute movement action", "glutes", "glutes", "dumbbell", None),
        ("361:rank-2", "synthetic glute movement muscle", "glutes", "glutes", "dumbbell", None),
        ("361:rank-3", "synthetic glute movement alternate pair", "glutes", "glutes", "dumbbell", None),
    ]
    _insert_exercises(fresh_store, rows)
    curation = {
        "361:rank-0": {
            "primary_action": "Hip Extension",
            "primary_muscle": "Glutes",
        },
        "361:rank-1": {
            "primary_action": "Hip Extension",
            "primary_muscle": "Abductors",
        },
        "361:rank-2": {
            "primary_action": "Hip Abduction",
            "primary_muscle": "Glutes",
        },
        "361:rank-3": {
            "primary_action": "Hip Abduction",
            "primary_muscle": "Abductors",
        },
    }
    seed_exercise_curation(fresh_store, curation)
    with fresh_store.catalog_conn:
        fresh_store.catalog_conn.executemany(
            "UPDATE exercises SET equipment = 'cable' WHERE id = ?",
            [(staple_id,) for staple_id in SLOT_STAPLES["glute_iso"]],
        )

    candidates = fetch_slot_candidates(
        "glute_iso", HOME_GYM, limit=100, ledger=fresh_store.ledger
    )
    matching_ids = [
        str(candidate["id"])
        for candidate in candidates
        if str(candidate["id"]).startswith("361:rank-")
    ]
    assert matching_ids == [
        "361:rank-0", "361:rank-1", "361:rank-2", "361:rank-3"
    ]

    program = _generate_program(fresh_store, _profile(HOME_GYM, "female", 5))
    glute_iso = next(
        exercise
        for day in program.days
        for exercise in day.exercises
        if exercise.slot_key == "glute_iso"
    )

    assert glute_iso.exercise_id == "361:rank-0"


def test_empty_curation_programs_match_coach_pattern_snapshot(
    fresh_store, seed_exercise_curation
):
    """Empty curation keeps current coach-pattern output deterministic."""
    seed_exercise_curation(fresh_store, {})
    snapshot_path = (
        Path(__file__).parent
        / "fixtures"
        / "program_generation_empty_curation_coach_patterns.json.gz"
    )
    with gzip.open(snapshot_path, "rt", encoding="utf-8") as snapshot_file:
        expected = json.load(snapshot_file)

    for equipment_access in (COMMERCIAL_GYM, HOME_GYM, BODYWEIGHT_ONLY):
        for frequency in (1, 3, 5):
            scenario = f"{equipment_access}|{frequency}|None"
            program = _generate_program(
                fresh_store,
                _profile(equipment_access, "male", frequency),
                "Full Body",
            )
            assert _without_program_week_fields(program.model_dump(mode="json")) == expected[scenario], scenario

    limitations = "lower back tightness"
    scenario = f"{COMMERCIAL_GYM}|3|{limitations}"
    program = _generate_program(
        fresh_store,
        _profile(COMMERCIAL_GYM, "male", 3, limitations),
        "Full Body",
        user_suffix="back_limit",
    )
    assert _without_program_week_fields(program.model_dump(mode="json")) == expected[scenario], scenario


def _without_program_week_fields(program: dict) -> dict:
    """Drops the Program week structure (#330), which postdates this snapshot."""
    program = {key: value for key, value in program.items() if key != "weeks"}
    program["days"] = [
        {key: value for key, value in day.items() if key != "week_order"}
        for day in program["days"]
    ]
    return program


def test_partially_curated_name_matches_keep_uncurated_ordering(
    fresh_store, seed_exercise_curation
):
    rows = [
        ("361:partial-action", "bodyweight flat press partial action", "chest", "pectorals", "body weight", None),
        ("361:partial-muscle", "bodyweight flat press partial muscle", "chest", "pectorals", "body weight", None),
        ("361:full-match", "bodyweight flat press full match", "chest", "pectorals", "body weight", None),
        ("361:uncurated-rank", "dumbbell chest press pattern match", "chest", "pectorals", "dumbbell", None),
    ]
    _insert_exercises(fresh_store, rows)
    seed_exercise_curation(
        fresh_store,
        {
            "361:partial-action": {"primary_action": "Shoulder Horizontal Adduction"},
            "361:partial-muscle": {"primary_muscle": "Chest"},
            "361:full-match": {
                "primary_action": "Shoulder Horizontal Adduction",
                "primary_muscle": "Chest",
            },
        },
    )

    candidates = fetch_slot_candidates(
        "flat_press", HOME_GYM, limit=100, ledger=fresh_store.ledger
    )
    by_id = {str(candidate["id"]): candidate for candidate in candidates}
    candidate_positions = {
        exercise_id: candidates.index(candidate)
        for exercise_id, candidate in by_id.items()
        if exercise_id.startswith("361:")
    }
    assert candidate_positions["361:full-match"] < candidate_positions["361:uncurated-rank"]
    assert candidate_positions["361:uncurated-rank"] < candidate_positions["361:partial-action"]
    assert candidate_positions["361:uncurated-rank"] < candidate_positions["361:partial-muscle"]


def test_hidden_curated_signature_match_is_never_prescribed(
    fresh_store, seed_exercise_curation
):
    hidden_id = "361:hidden-signature"
    _insert_exercises(
        fresh_store,
        [(hidden_id, "hidden signature movement", "chest", "pectorals", "body weight", None)],
    )
    seed_exercise_curation(
        fresh_store,
        {
            hidden_id: {
                "primary_action": "Shoulder Horizontal Adduction",
                "primary_muscle": "Chest",
                "hidden": True,
            }
        },
    )

    candidates = fetch_slot_candidates(
        "flat_press", BODYWEIGHT_ONLY, limit=100, ledger=fresh_store.ledger
    )
    program = _generate_program(
        fresh_store, _profile(BODYWEIGHT_ONLY, "male", 3), "Full Body"
    )
    prescribed_ids = {
        exercise.exercise_id
        for day in program.days
        for exercise in day.exercises
    }

    assert hidden_id not in {str(candidate["id"]) for candidate in candidates}
    assert hidden_id not in prescribed_ids


def test_generation_with_curated_rows_is_repeatable(fresh_store, seed_exercise_curation):
    _insert_exercises(
        fresh_store,
        [("361:repeatable", "curated press variant", "chest", "pectorals", "body weight", None)],
    )
    seed_exercise_curation(
        fresh_store,
        {
            "361:repeatable": {
                "primary_action": "Shoulder Horizontal Adduction",
                "primary_muscle": "Chest",
            }
        },
    )

    profile = _profile(BODYWEIGHT_ONLY, "male", 3)
    first = _generate_program(fresh_store, profile, "Full Body")
    second = _generate_program(fresh_store, profile, "Full Body")

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_limitation_guard_counts_used_staples_and_ignores_equipment_only(
    fresh_store,
):
    with fresh_store.catalog_conn:
        fresh_store.catalog_conn.execute(
            "UPDATE exercises SET name = 'barbell hinge fixture' WHERE id = '85'"
        )

    limitation_context = program_generator.DayGenerationContext(
        equipment_access=COMMERCIAL_GYM,
        limitations="lower back tightness",
        rep_preference="balanced",
        recovery_cut=False,
        experience_level="intermediate",
    )
    limited_candidates = fetch_slot_candidates(
        "ham_hinge",
        COMMERCIAL_GYM,
        limitation_context.limitations,
        limit=100,
        ledger=fresh_store.ledger,
    )
    limited_staple_ids = {
        str(candidate["id"])
        for candidate in limited_candidates
        if str(candidate["id"]) in SLOT_STAPLES["ham_hinge"]
    }

    assert limited_staple_ids == {"85"}
    assert not program_generator._limitation_removed_staples(
        limited_candidates,
        "ham_hinge",
        limitation_context,
        set(),
        ledger=fresh_store.ledger,
    )
    assert program_generator._limitation_removed_staples(
        limited_candidates,
        "ham_hinge",
        limitation_context,
        {"85"},
        ledger=fresh_store.ledger,
    )

    day = CustomDayPlan(
        day_order=1,
        day_name="Used hinge Staple",
        target_slots=["ham_hinge", "calf", "chest_fly"],
        warmup_family="lower",
    )
    generated = program_generator.assemble_deterministic_day(
        day, limitation_context, {"85"}, ledger=fresh_store.ledger
    )
    assert any(
        exercise.slot_key == "ham_curl" and exercise.exercise_id == "599"
        for exercise in generated.exercises
    )
    assert not any(exercise.slot_key == "ham_hinge" for exercise in generated.exercises)

    equipment_only_context = program_generator.DayGenerationContext(
        equipment_access=BODYWEIGHT_ONLY,
        limitations=NO_LIMITATIONS,
        rep_preference="balanced",
        recovery_cut=False,
        experience_level="intermediate",
    )
    equipment_only_candidates = fetch_slot_candidates(
        "ham_hinge",
        BODYWEIGHT_ONLY,
        equipment_only_context.limitations,
        limit=100,
        ledger=fresh_store.ledger,
    )
    assert not program_generator._limitation_removed_staples(
        equipment_only_candidates,
        "ham_hinge",
        equipment_only_context,
        set(),
        ledger=fresh_store.ledger,
    )


def test_explosive_signature_matches_are_never_prescribed(fresh_store, seed_exercise_curation):
    safe_id = "361:safe-hinge"
    push_press_id = "361:push-press-hinge"
    olympic_rows = (
        ("361:olympic-clean", "Synthetic Hang Clean"),
        ("361:olympic-snatch", "Synthetic Snatch Pull"),
        ("361:olympic-jerk", "Synthetic Push Jerk"),
        ("361:olympic-high-pull", "Synthetic High Pull"),
        ("361:olympic-clean-pull", "Synthetic Clean Pull"),
        ("361:olympic-hang-pull", "Synthetic Hang Pull"),
    )
    explosive_bodyweight_rows = tuple(
        (f"361:explosive-{term.replace(' ', '-')}", f"Synthetic {term.title()} Hinge")
        for term in (
            "clap",
            "plyo",
            "plyometric",
            "jump",
            "broad jump",
            "depth",
            "bound",
            "drop",
            "explosive",
        )
    )
    _insert_exercises(
        fresh_store,
        [
            (exercise_id, name, "hamstrings", "hamstrings", "dumbbell", None)
            for exercise_id, name in olympic_rows
        ]
        + [
            (exercise_id, name, "hamstrings", "hamstrings", "body weight", None)
            for exercise_id, name in explosive_bodyweight_rows
        ]
        + [
            (safe_id, "Synthetic Hip Hinge", "hamstrings", "hamstrings", "dumbbell", None),
            (push_press_id, "Synthetic Push Press", "hamstrings", "hamstrings", "dumbbell", None),
        ],
    )
    curation = {
        exercise_id: {
            "primary_action": "Hip Extension",
            "primary_muscle": "Hamstrings",
        }
        for exercise_id, _ in (*olympic_rows, *explosive_bodyweight_rows)
    }
    curation.update(
        {
            safe_id: {
                "primary_action": "Hip Extension",
                "primary_muscle": "Hamstrings",
            },
            push_press_id: {
                "primary_action": "Hip Extension",
                "primary_muscle": "Hamstrings",
            },
        }
    )
    seed_exercise_curation(
        fresh_store,
        curation,
    )
    with fresh_store.catalog_conn:
        fresh_store.catalog_conn.executemany(
            "UPDATE exercises SET equipment = 'cable' WHERE id = ?",
            [(staple_id,) for staple_id in SLOT_STAPLES["ham_hinge"]],
        )

    candidates = fetch_slot_candidates(
        "ham_hinge", HOME_GYM, limit=100, ledger=fresh_store.ledger
    )
    program = _generate_program(
        fresh_store, _profile(HOME_GYM, "male", 3), "Full Body"
    )
    prescribed_hinges = [
        exercise
        for day in program.days
        for exercise in day.exercises
        if exercise.slot_key == "ham_hinge"
    ]

    assert safe_id in {str(candidate["id"]) for candidate in candidates}
    assert push_press_id in {str(candidate["id"]) for candidate in candidates}
    olympic_ids = {exercise_id for exercise_id, _ in olympic_rows}
    explosive_bodyweight_ids = {
        exercise_id for exercise_id, _ in explosive_bodyweight_rows
    }
    candidate_ids = {str(candidate["id"]) for candidate in candidates}
    assert olympic_ids.isdisjoint(candidate_ids)
    assert explosive_bodyweight_ids.isdisjoint(candidate_ids)
    assert prescribed_hinges
    assert all(
        exercise.exercise_id not in olympic_ids
        for exercise in prescribed_hinges
    )
