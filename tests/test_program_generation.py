import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from agent.program_generator import generate_program_pipeline
from database.database_manager import DatabaseManager
from utils.logger import MayosLogger

logger = MayosLogger().get_logger(__name__)


def run_test():
    logger.info("--- Starting Phase 2 Program Generation ---")

    # 1. Open an isolated test ledger and seed baseline profile
    db = DatabaseManager()
    test_user = "test_generator_trainee"
    with db.open_ledger(test_user) as ledger:
        ledger.upsert_player_profile(
            {
                "gender": "male",
                "proportions": "balanced",
                "age": 22,
                "weight_kg": 80.0,
                "height_cm": 180.0,
                "rep_preference": "balanced",
                "current_goal": "hypertrophy",
                "long_term_goal": "progressive overload",
                "weekly_frequency": 4,
                "training_age_years": 3.0,
                "equipment_access": "commercial gym",
                "injuries_or_limitations": "None",
                "stress_and_sleep": "normal",
            }
        )

        # 2. Execute program synthesis
        program, table_view = generate_program_pipeline(ledger=ledger)

        # 3. Assertions
        assert program is not None, "Failed: Program generation returned None."
        assert len(program.days) == 4, f"Expected 4 training days, got {len(program.days)}"
        assert ledger.get_active_program() is not None, "Failed: Program not persisted to SQLite."

    logger.info("\n" + "=" * 50)
    logger.info(table_view)
    logger.info("=" * 50)
    logger.info("\nPhase 2 Program Generation & Database Persistence Verified.")


import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from pydantic import ValidationError

from agent import program_generator
from agent import program_rules
from agent.program_cardio import (
    CoachCardioOptions,
    apply_program_cardio,
    build_cardio_note,
    is_leg_day,
    select_cardio_day_indices,
)
from agent.ProgramState import (
    CustomDayPlan,
    GeneratedProgramSchema,
    PersistedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
    ProgramSchema,
)
from agent.program_order import main_muscles_for_slot, shares_main_muscle
from agent.UserState import PlayerProfileSchema


@pytest.mark.parametrize("experience,test_rir,compound_rir,isolation_rir", [
    ("beginner", 3, 2, 1), ("intermediate", 2, 1, 0), ("advanced", 2, 1, 0),
])
@pytest.mark.parametrize("slot", ["quad_compound", "flat_press", "side_delts", "calf", "abs"])
@pytest.mark.parametrize("set_count", [1, 2, 3, 4])
def test_generated_exercise_groups_follow_test_set_rule(
    experience, test_rir, compound_rir, isolation_rir, slot, set_count,
):
    from agent.program_blueprints import SLOT_SPECS
    from agent.program_rationale import ExerciseRationaleOptions, exercise_rationale

    spec = SLOT_SPECS[slot]
    prescription = program_generator.ExercisePrescription(
        movement_slot=slot, spec=spec, working_sets=set_count,
        rep_preference="balanced", experience_level=experience,
    )
    candidate = {"id": "example", "name": "Example Exercise"}
    exercise = program_generator._build_program_exercise(candidate, prescription)
    working_rir = compound_rir if "compound" in spec.archetype else isolation_rir
    expected = [(1, working_rir)] if set_count == 1 else [(1, test_rir), (set_count - 1, working_rir)]
    assert [(group.sets, group.target_rir) for group in exercise.set_groups] == expected
    assert exercise.working_sets == set_count
    assert exercise.target_sets == expected[0][0]
    assert exercise.target_rpe == 10 - expected[0][1]
    assert all((group.reps_min, group.reps_max) == spec.reps for group in exercise.set_groups)
    reason = exercise_rationale(candidate, prescription, ExerciseRationaleOptions(experience_level=experience))
    assert reason["prescription"]["rir"] == {
        "code": "rir.test_set_rule",
        "params": {
            "experience_level": experience, "target_rir": working_rir,
            "test_set_rir": test_rir, "test_set_count": int(set_count > 1),
            "test_set_counts_toward_weekly_sets": True,
        },
    }


@pytest.mark.parametrize("text,expected", [
    ("switch to 0 days", 0), ("six days", 6), ("seven-day split", 7),
    ("12 days", 12), ("zero days", 0), ("twenty-one days", 21),
    ("one hundred days", 100), ("minus one day", -1), ("-1 days", -1),
    ("3d/wk", 3), ("five days", 5), ("1x per week", 1),
    ("3 times a week", 3), ("new routine", None),
])
def test_frequency_extraction_preserves_unsupported_requests(text, expected):
    assert program_generator.extract_frequency_from_text(text) == expected


@pytest.mark.parametrize("frequency", [0, 6, 7, 12, -1, True, 2.5, "0", "99"])
@pytest.mark.parametrize("source", ["override", "profile"])
def test_invalid_frequency_rejected_before_program_writes(monkeypatch, frequency, source):
    database = MagicMock()
    database.get_player_profile.return_value = {"weekly_frequency": frequency if source == "profile" else 4}
    split = MagicMock()
    monkeypatch.setattr(program_generator, "resolve_split", split)
    kwargs = {"frequency_override": frequency} if source == "override" else {}
    with pytest.raises(ValueError, match="1 to 5"):
        generate_program_pipeline(ledger=database, **kwargs)
    assert database.method_calls == [("get_player_profile", (), {})]
    split.assert_not_called()


@pytest.mark.parametrize("frequency", ["0", "6", "7", "14", "zero", "six", "twelve", "twenty-one", "one hundred"])
def test_invalid_text_frequency_not_hidden_by_valid_override(monkeypatch, frequency):
    database = MagicMock()
    database.get_player_profile.return_value = {"weekly_frequency": 4}
    with pytest.raises(ValueError, match="1 to 5"):
        generate_program_pipeline(
            user_split_override=f"switch routine to {frequency} days", frequency_override=3, ledger=database
        )
    assert database.method_calls == [("get_player_profile", (), {})]


def test_coach_generation_can_build_a_draft_without_writing_program_or_profile(monkeypatch):
    profile = {
        "gender": "male",
        "weekly_frequency": 4,
        "rep_preference": "balanced",
        "equipment_access": "commercial gym",
        "injuries_or_limitations": "None",
        "stress_and_sleep": "normal",
        "training_age_years": 3,
        "current_goal": "Hypertrophy",
    }
    ledger = MagicMock()
    ledger.get_player_profile.return_value = profile.copy()
    split = type("Split", (), {})()
    split.split_name = "Full Body"
    split.days = [
        CustomDayPlan(day_order=order, day_name=f"Full {order}", target_slots=[])
        for order in (1, 2)
    ]
    monkeypatch.setattr(program_generator, "resolve_split", lambda **_kwargs: split)

    def build_day(day, *_args, **_kwargs):
        return ProgramDaySchema(
            day_name=day.day_name,
            day_order=day.day_order,
            exercises=[
                ProgramExerciseSchema(
                    exercise_id=exercise_id,
                    exercise_name=name,
                    target_reps_min=6,
                    target_reps_max=8,
                )
                for exercise_id, name in (("sq", "Squat"), ("bp", "Bench"), ("row", "Row"))
            ],
        )

    monkeypatch.setattr(program_generator, "assemble_program_day", lambda day, *_args, **_kwargs: (build_day(day), []))

    generated, _ = program_generator.generate_program_draft_pipeline(
        program_generator.ProgramGenerationRequest(
            frequency_override=2,
        ),
        ledger=ledger,
    )

    assert generated.weekly_frequency == 2
    ledger.update_player_frequency.assert_not_called()
    ledger.save_training_program.assert_not_called()
    assert ledger.get_player_profile.return_value == profile


def test_generated_program_draft_carries_structured_rationale(monkeypatch):
    profile = {
        "gender": "male", "weekly_frequency": 2, "rep_preference": "balanced",
        "equipment_access": "commercial gym", "injuries_or_limitations": "None",
        "stress_and_sleep": "normal", "training_age_years": 3,
        "current_goal": "Hypertrophy",
    }
    split = type("Split", (), {"split_name": "Full Body", "days": [
        CustomDayPlan(day_order=1, day_name="Full 1", target_slots=[]),
        CustomDayPlan(day_order=2, day_name="Full 2", target_slots=[]),
    ]})()
    monkeypatch.setattr(program_generator, "resolve_split", lambda **_kwargs: split)
    monkeypatch.setattr(program_generator, "_assemble_deterministic_day_with_rationale", lambda day, *_args, **_kwargs: (ProgramDaySchema(
        day_name=day.day_name, day_order=day.day_order,
        exercises=[
            ProgramExerciseSchema(
                exercise_id=f"ex-{index}", exercise_name="Squat", target_reps_min=8,
                target_reps_max=12,
            )
            for index in range(3)
        ],
    ), [{"position": index, "exercise_id": f"ex-{index}", "rationale": {"selection": {"code": "selection.staple"}, "position": {"code": "position.heavy_compound"}, "prescription": {"sets": {"code": "sets.coach_dose"}}}} for index in range(1, 4)]))
    generated, _ = program_generator.generate_program_draft_pipeline(
        program_generator.ProgramGenerationRequest(frequency_override=2),
        ledger=MagicMock(), profile=profile,
    )

    rationale = generated.model_dump().get("program_rationale")
    assert rationale["split"]["code"] == "split.frequency_default"
    assert rationale["day_order"]["code"] == "day_order.template"
    assert rationale["days"][0]["exercises"][0]["rationale"]["prescription"]["sets"]["code"] == "sets.coach_dose"


def _order_test_program_day(
    monkeypatch,
    slots,
    *,
    family="upper",
    experience="intermediate",
    equipment_by_slot=None,
):
    equipment_by_slot = equipment_by_slot or {}

    def candidates_for_slot(slot_key, *_args, **_kwargs):
        return [
            {
                "id": f"test-{slot_key}",
                "name": f"Test {slot_key}",
                "equipment": equipment_by_slot.get(slot_key, "Cable"),
                "_candidate_source": program_rules.SLOT_CANDIDATE_SIGNATURE,
            }
        ], False

    monkeypatch.setattr(program_generator, "_fetch_generation_candidates", candidates_for_slot)
    monkeypatch.setattr(program_generator, "build_warmup_block", lambda *_args, **_kwargs: [])
    day_plan = CustomDayPlan(
        day_order=1,
        day_name="Ordering test",
        target_slots=slots,
        warmup_family=family,
        family=family,
    )
    context = program_generator.DayGenerationContext(
        equipment_access="Commercial gym",
        limitations="None",
        rep_preference="balanced",
        recovery_cut=False,
        experience_level=experience,
    )
    day, exercise_reasons = program_generator.assemble_program_day(
        day_plan, context, set(), ledger=object()
    )
    program = GeneratedProgramSchema(
        program_name="Ordering test",
        split_type="custom",
        weekly_frequency=1,
        days=[day],
        program_rationale={
            "days": [{"day_order": 1, "exercises": exercise_reasons}],
        },
    )
    training_age = {"beginner": 0.5, "intermediate": 3.0, "advanced": 6.0}[experience]
    program_generator._order_generated_program(
        program, {1: family}, {"training_age_years": training_age}
    )
    return program.days[0], program.program_rationale["days"][0]["exercises"]


def test_generator_pre_exhausts_lats_and_chest_before_later_compounds(monkeypatch):
    day, rationale = _order_test_program_day(
        monkeypatch,
        ["horizontal_row", "pullover", "vertical_pull", "chest_fly", "flat_press", "incline_press"],
    )

    assert [exercise.slot_key for exercise in day.exercises] == [
        "horizontal_row", "pullover", "vertical_pull", "chest_fly", "flat_press", "incline_press",
    ]
    reasons = {entry["exercise_id"]: entry["rationale"]["position"] for entry in rationale}
    for slot in ("pullover", "chest_fly"):
        position = reasons[f"test-{slot}"]
        assert position["code"] == "position.pre_exhaust"
        assert "small isolation exercise" in position["params"]["reason_en"]
        assert "5–15% less load" in position["params"]["reason_en"]
        assert "تمرين العزل" in position["params"]["reason_ar"]
        assert "٥–١٥٪" in position["params"]["reason_ar"]
    assert reasons["test-horizontal_row"]["code"] == "position.main_progressed_lift"


def test_main_lift_precedes_its_owner_group_muscle_and_rear_delts_stay_separate(monkeypatch):
    day, rationale = _order_test_program_day(
        monkeypatch,
        ["side_delts", "shoulder_press", "rear_delts", "flat_press"],
    )

    assert [exercise.slot_key for exercise in day.exercises][:2] == ["shoulder_press", "side_delts"]
    assert main_muscles_for_slot("side_delts") == main_muscles_for_slot("shoulder_press")
    assert not shares_main_muscle("rear_delts", "horizontal_row")
    reasons = {entry["exercise_id"]: entry["rationale"]["position"] for entry in rationale}
    assert reasons["test-shoulder_press"]["code"] == "position.main_progressed_lift"
    assert reasons["test-shoulder_press"]["params"]["reason_ar"]


def test_beginner_keeps_compounds_ahead_of_isolations(monkeypatch):
    day, rationale = _order_test_program_day(
        monkeypatch,
        ["chest_fly", "flat_press", "horizontal_row", "pullover"],
        family="full",
        experience="beginner",
    )

    assert [exercise.slot_key for exercise in day.exercises] == [
        "flat_press", "horizontal_row", "chest_fly", "pullover",
    ]
    positions = [entry["rationale"]["position"]["code"] for entry in rationale]
    assert "position.pre_exhaust" not in positions
    assert positions[:2] == ["position.main_progressed_lift", "position.beginner_compound_first"]


def test_crowded_upper_day_can_keep_template_order_without_pre_exhaust(monkeypatch):
    day, rationale = _order_test_program_day(
        monkeypatch,
        [
            "horizontal_row", "flat_press", "incline_press", "chest_fly",
            "vertical_pull", "side_delts", "rear_delts", "shrug",
        ],
    )

    slots = [exercise.slot_key for exercise in day.exercises]
    assert slots.index("chest_fly") > slots.index("flat_press")
    assert slots.index("chest_fly") > slots.index("incline_press")
    assert all(entry["rationale"]["position"]["code"] != "position.pre_exhaust" for entry in rationale)


@pytest.mark.parametrize("press_slot", ["flat_press", "incline_press"])
def test_stabilizer_isolation_follows_barbell_bench(monkeypatch, press_slot):
    day, rationale = _order_test_program_day(
        monkeypatch,
        ["triceps_pushdown", press_slot, "horizontal_row"],
        equipment_by_slot={press_slot: "Barbell"},
    )

    slots = [exercise.slot_key for exercise in day.exercises]
    assert slots.index(press_slot) < slots.index("triceps_pushdown")
    position = next(
        entry["rationale"]["position"]
        for entry in rationale
        if entry["exercise_id"] == "test-triceps_pushdown"
    )
    assert position["code"] == "position.stabilizer_safety"
    assert position["params"]["reason_en"]
    assert position["params"]["reason_ar"]


def test_pre_exhaust_caps_sets_and_effort(monkeypatch):
    original_slot_sets = program_generator.slot_working_sets

    def three_set_fly(slot_key, *args, **kwargs):
        return 3 if slot_key == "chest_fly" else original_slot_sets(slot_key, *args, **kwargs)

    monkeypatch.setattr(program_generator, "slot_working_sets", three_set_fly)
    day, rationale = _order_test_program_day(
        monkeypatch,
        ["horizontal_row", "chest_fly", "flat_press"],
        family="arms",
    )

    fly = next(exercise for exercise in day.exercises if exercise.slot_key == "chest_fly")
    assert fly.working_sets == 2
    assert all(1 <= group.target_rir <= 3 for group in fly.set_groups)
    fly_rationale = next(
        entry["rationale"] for entry in rationale if entry["exercise_id"] == "test-chest_fly"
    )
    assert fly_rationale["prescription"]["sets"]["params"]["count"] == 2
    assert fly_rationale["prescription"]["rir"]["params"]["target_rir"] == 2


def test_structured_fat_loss_cardio_keeps_its_program_rationale():
    from agent.ProgramState import CardioPrescriptionSchema
    from agent.program_blueprints import (
        FAT_LOSS_CARDIO_BODYWEIGHT_NOTE,
        FAT_LOSS_CARDIO_NOTE,
    )
    from agent.program_rationale import CARDIO_FAT_LOSS_FINISHER, _day_rationale

    for prescription in (FAT_LOSS_CARDIO_NOTE, FAT_LOSS_CARDIO_BODYWEIGHT_NOTE):
        day = SimpleNamespace(
            cardio=CardioPrescriptionSchema.model_validate(prescription),
            warmup_exercises=[],
            day_order=1,
        )
        assert _day_rationale(day, None)["cardio"]["code"] == CARDIO_FAT_LOSS_FINISHER


def test_retired_glute_split_id_uses_frequency_default_for_new_requests(fresh_store):
    generated, _ = program_generator.generate_program_draft_pipeline(
        program_generator.ProgramGenerationRequest(
            frequency_override=4,
            split_id_override="female_full_body",
        ),
        ledger=fresh_store.ledger,
        profile={
            "gender": "female",
            "weekly_frequency": 4,
            "equipment_access": "commercial gym",
            "injuries_or_limitations": "None",
            "rep_preference": "balanced",
            "training_age_years": 3.0,
            "stress_and_sleep": "normal",
        },
    )

    assert generated.split_type == program_rules.get_default_split(4).split_name


@pytest.mark.parametrize("frequency", [2, 3, 4, 5])
def test_coach_cardio_days_are_evenly_spread_and_intervals_prefer_non_leg_days(frequency):
    for split_id, _ in program_rules.valid_splits_for(frequency):
        split = program_rules.resolve_split(frequency, split_id)
        for cardio_days in range(1, frequency + 1):
            selected = select_cardio_day_indices(split.days, cardio_days, "steady")
            expected = tuple(
                int((index + 0.5) * frequency / cardio_days)
                for index in range(cardio_days)
            )
            assert selected == expected

            intervals = select_cardio_day_indices(split.days, cardio_days, "intervals")
            non_leg_days = {
                index
                for index, day in enumerate(split.days)
                if not is_leg_day(day)
            }
            assert len(intervals) == cardio_days
            assert len(set(intervals) & non_leg_days) == min(cardio_days, len(non_leg_days))
            interval_gaps = [
                right - left for left, right in zip(intervals, intervals[1:])
            ]
            assert max(interval_gaps, default=0) - min(interval_gaps, default=0) <= 1


def test_coach_cardio_notes_use_fixed_wording_and_custom_text_verbatim():
    assert build_cardio_note(CoachCardioOptions(1, 20, "steady")) == (
        "Steady cardio: 20 min at an easy, conversational pace."
    )
    assert build_cardio_note(CoachCardioOptions(1, 20, "intervals")) == (
        "Intervals: 20 min, 30 s hard / 90 s easy."
    )
    assert build_cardio_note(CoachCardioOptions(1, 30, "steady", display_language="ar")) == (
        "تمارين لياقة مستمرة: 30 دقيقة بوتيرة مريحة تسمح بالمحادثة."
    )
    assert build_cardio_note(CoachCardioOptions(1, 30, "intervals", display_language="ar")) == (
        "تمارين متقطعة: 30 دقيقة؛ 30 ثانية بشدة عالية / 90 ثانية بوتيرة سهلة."
    )
    custom = "Bike as tolerated  \n"
    assert build_cardio_note(CoachCardioOptions(1, 20, "custom", custom_note=custom)) == custom


def test_coach_cardio_overrides_fat_loss_automatic_note_and_none_clears_it():
    profile = {
        "gender": "male",
        "weekly_frequency": 3,
        "current_goal": "fat loss",
        "training_age_years": 3.0,
        "equipment_access": "commercial gym",
        "injuries_or_limitations": "None",
        "stress_and_sleep": "normal",
    }
    split = program_rules.resolve_split(3, "upper_lower")
    exercises = [
        ProgramExerciseSchema(
            exercise_id=exercise_id,
            exercise_name=exercise_name,
            target_reps_min=6,
            target_reps_max=8,
        )
        for exercise_id, exercise_name in (("sq", "Squat"), ("bp", "Bench"), ("row", "Row"))
    ]
    program_days = [
        ProgramDaySchema(
            day_name=day.day_name,
            day_order=day.day_order,
            exercises=[exercise.model_copy() for exercise in exercises],
        )
        for day in split.days
    ]

    apply_program_cardio(
        program_days, split.days, profile, CoachCardioOptions(1, 25, "steady")
    )

    cardio_days = [day for day in program_days if day.cardio]
    assert len(cardio_days) == 1
    assert cardio_days[0].cardio == "Steady cardio: 25 min at an easy, conversational pace."
    assert sum(day.cardio is not None for day in program_days) == 1

    apply_program_cardio(
        program_days, split.days, profile, CoachCardioOptions(0, 25, "none")
    )
    assert all(day.cardio is None for day in program_days)


def test_fat_loss_finisher_is_structured_treadmill_for_either_goal_field():
    exercises = [ProgramExerciseSchema(exercise_id=f"x{i}", exercise_name="Squat", target_reps_min=6, target_reps_max=8) for i in range(3)]
    days = [ProgramDaySchema(day_name="Upper", day_order=i, exercises=exercises) for i in range(1, 3)]
    split_days = [CustomDayPlan(day_order=i, day_name="Upper") for i in range(1, 3)]
    apply_program_cardio(days, split_days, {"current_goal": "hypertrophy", "long_term_goal": "fat loss"}, None)
    assert days[0].cardio.model_dump() == {
        "machine": "treadmill", "minutes": 25, "minutes_max": None,
        "speed_kmh": 5.0, "incline_pct": 10.0, "level": None,
        "watts": None, "distance_m": None,
    }


def test_fat_loss_cardio_avoids_incline_modalities_for_knee_restrictions():
    exercises = [ProgramExerciseSchema(exercise_id=f"c{i}", exercise_name="Row", target_reps_min=6, target_reps_max=8) for i in range(3)]
    days = [ProgramDaySchema(day_name="Upper", day_order=1, exercises=exercises)]
    split_days = [CustomDayPlan(day_order=1, day_name="Upper")]
    adjustments = apply_program_cardio(days, split_days, {
        "current_goal": "fat loss", "movement_restrictions": ["Knee flexion"]
    }, None)
    assert days[0].cardio.machine == "outdoor_walk_run"
    assert days[0].cardio.incline_pct is None
    assert adjustments == [{"restriction": "Knee flexion", "reason": "incline_modality_removed"}]


def test_cardio_restriction_adjustment_is_recorded_in_generated_rationale(fresh_store):
    from agent.program_generator import ProgramGenerationRequest, generate_program_draft_pipeline

    profile = {
        "gender": "male", "weekly_frequency": 3, "rep_preference": "balanced",
        "equipment_access": "Commercial gym", "injuries_or_limitations": "None",
        "stress_and_sleep": "normal", "training_age_years": 3,
        "current_goal": "fat loss", "movement_restrictions": ["Knee flexion"],
    }
    program = generate_program_draft_pipeline(
        ProgramGenerationRequest(user_split_override="ppl", frequency_override=3),
        ledger=fresh_store.ledger,
        profile=profile,
    )[0]
    assert all(day.cardio.machine == "outdoor_walk_run" for day in program.days)
    assert all(
        day["cardio_restriction"] == [
            {"restriction": "Knee flexion", "reason": "incline_modality_removed"}
        ]
        for day in program.program_rationale["days"]
    )


def test_program_day_schema_accepts_legacy_cardio_and_structured_prescription():
    exercises = [ProgramExerciseSchema(exercise_id=f"x{i}", exercise_name="Squat", target_reps_min=6, target_reps_max=8) for i in range(3)]
    legacy = ProgramDaySchema(day_name="A", day_order=1, exercises=exercises, cardio="Easy treadmill walk")
    structured = ProgramDaySchema(day_name="A", day_order=1, exercises=exercises, cardio={"machine": "bike", "minutes": 30, "level": 4})
    assert legacy.cardio == "Easy treadmill walk"
    assert structured.cardio.machine == "bike"


@pytest.mark.parametrize("schema", [PlayerProfileSchema, ProgramSchema, GeneratedProgramSchema])
@pytest.mark.parametrize("frequency", [0, 6, 7, 12, -1])
def test_frequency_schema_bounds(schema, frequency):
    data = {
        "weekly_frequency": frequency, "program_name": "Test", "split_type": "custom", "days": [],
        "proportions": "balanced", "age": 30, "weight_kg": 80, "height_cm": 180,
        "current_goal": "strength", "long_term_goal": "health", "training_age_years": 2,
        "equipment_access": "gym", "stress_and_sleep": "normal",
    }
    with pytest.raises(ValidationError) as error:
        schema.model_validate(data)
    assert any(e["loc"] == ("weekly_frequency",) for e in error.value.errors())
    field = schema.model_json_schema()["properties"]["weekly_frequency"]
    assert field["minimum"] == 1
    assert field["maximum"] == 5


def _program_output(exercise_count=3, working_sets=2):
    return {
        "program_name": "Generated",
        "split_type": "custom",
        "weekly_frequency": 1,
        "days": [
            {
                "day_name": "Day 1",
                "day_order": 1,
                "exercises": [
                    {
                        "exercise_id": f"exercise-{index}",
                        "exercise_name": f"Exercise {index}",
                        "target_sets": working_sets,
                        "target_reps_min": 8,
                        "target_reps_max": 12,
                    }
                    for index in range(exercise_count)
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "program",
    [_program_output(working_sets=5), _program_output(exercise_count=2)],
)
def test_generated_program_output_keeps_blueprint_set_and_day_guards(program):
    with pytest.raises(ValidationError):
        GeneratedProgramSchema.model_validate(program)


def test_persisted_program_schema_accepts_coach_authored_prescription():
    program = PersistedProgramSchema.model_validate(_program_output(exercise_count=1, working_sets=5))

    assert len(program.days[0].exercises) == 1
    assert program.days[0].exercises[0].target_sets == 5


if __name__ == "__main__":
    run_test()


def test_machine_suffix_never_reads_as_a_chin_up_cue():
    from agent.program_generator import MECHANIC_CUES, get_biomechanical_cue

    assert get_biomechanical_cue("Squat (Smith Machine)", "intermediate") == MECHANIC_CUES["compound_lower"]
    assert get_biomechanical_cue("Assisted Chin-Up (Machine)", "intermediate") == MECHANIC_CUES["compound_pull"]
