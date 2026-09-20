"""Blueprint-level guarantees: slot resolution, weekly coverage, Arabic schema and export."""

import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from agent import program_generator
from agent.program_blueprints import (
    ANTERIOR_POSTERIOR_DAYS,
    ARNOLD_DAYS,
    ARNOLD_X_UL_DAYS,
    FAT_LOSS_CARDIO_NOTE,
    FB_DAYS,
    FEMALE_FB_DAYS,
    MAX_RECOVERY_CUTS_PER_DAY,
    PPL_DAYS,
    SLOT_SPECS,
    SPLIT_DAY_POOLS,
    UL_DAYS,
    WARMUP_FAMILIES,
    WARMUP_SPECS,
    is_fat_loss_goal,
    is_poor_recovery,
    match_split_keyword,
)
from agent.program_rules import fetch_slot_candidates, fetch_warmup_candidates, get_split_plan, resolve_split
from database.database_manager import DatabaseManager
from utils.exporter import export_program_to_excel

db = DatabaseManager()

ALL_BLUEPRINTS = FB_DAYS + FEMALE_FB_DAYS + UL_DAYS + ARNOLD_DAYS + ARNOLD_X_UL_DAYS + ANTERIOR_POSTERIOR_DAYS + PPL_DAYS


@pytest.mark.parametrize("blueprint", ALL_BLUEPRINTS, ids=lambda b: b.name)
def test_every_blueprint_slot_resolves_to_a_catalog_exercise(blueprint):
    for slot_key in blueprint.slots:
        spec = SLOT_SPECS.get(slot_key)
        assert spec is not None, f"Unknown slot '{slot_key}' in {blueprint.name}"
        candidates = fetch_slot_candidates(slot_key, "commercial gym", "None", limit=4)
        assert candidates, f"Slot '{slot_key}' ({blueprint.name}) resolved no catalog exercises"


@pytest.mark.parametrize("warmup_key", list(WARMUP_SPECS))
def test_every_warmup_spec_resolves(warmup_key):
    candidates = fetch_warmup_candidates(warmup_key, "commercial gym", "None", limit=2)
    assert candidates, f"Warm-up '{warmup_key}' resolved no catalog exercises"


def test_all_slot_keys_are_referenced_by_a_blueprint():
    referenced = {slot for blueprint in ALL_BLUEPRINTS for slot in blueprint.slots}
    assert referenced == set(SLOT_SPECS), f"Unused slots: {set(SLOT_SPECS) - referenced}"


def test_warmup_families_reference_known_specs():
    for family in WARMUP_FAMILIES:
        for key in WARMUP_FAMILIES[family]:
            assert key in WARMUP_SPECS


def _generate(
    gender,
    frequency,
    preference=None,
    goal="hypertrophy",
    long_term_goal="progressive overload",
    recovery="normal",
    limitations="None",
):
    suffix = (preference or "default").replace(" ", "_").replace("/", "_")
    tags = "".join(
        f"_{value.replace(' ', '_').replace(',', '')}"
        for value in (goal, recovery if recovery != "normal" else "", limitations if limitations != "None" else "")
        if value
    )
    user = f"test_blueprint_{gender}_{frequency}{tags}_{suffix}"
    db.switch_user(user)
    db.upsert_user_profile(
        {
            "gender": gender,
            "proportions": "balanced",
            "age": 28,
            "weight_kg": 80.0,
            "height_cm": 175.0,
            "rep_preference": "balanced",
            "current_goal": goal,
            "long_term_goal": long_term_goal,
            "weekly_frequency": frequency,
            "training_age_years": 3.0,
            "equipment_access": "commercial gym",
            "injuries_or_limitations": limitations,
            "stress_and_sleep": recovery,
        }
    )
    return program_generator.generate_program_pipeline(user_split_override=preference)[0]


@pytest.mark.parametrize("gender,frequency", [("male", 1), ("male", 3), ("male", 4), ("male", 5), ("female", 3)])
def test_generated_programs_have_belghamdi_day_sizes(gender, frequency):
    program = _generate(gender, frequency)
    assert len(program.days) == frequency
    minimum = 8 if gender == "female" or frequency != 5 else 6
    for day in program.days:
        assert len(day.exercises) >= minimum, f"{day.day_name} only has {len(day.exercises)} exercises"
        assert 2 <= len(day.warmup_exercises) <= 3, f"{day.day_name} warm-up block is missing"


@pytest.mark.parametrize("gender,frequency", [("male", 3), ("male", 4), ("female", 3)])
def test_weekly_muscle_coverage_guarantees(gender, frequency):
    program = _generate(gender, frequency)
    slots = {exercise.slot_key for day in program.days for exercise in day.exercises}
    for required in ["incline_press", "flat_press", "vertical_pull", "horizontal_row", "side_delts", "rear_delts", "calf", "adductors", "abs"]:
        assert required in slots, f"Weekly coverage missing '{required}': {sorted(slots)}"
    arm_slots = {"biceps_preacher", "biceps_alt"}
    triceps_slots = {"triceps_pushdown", "triceps_overhead"}
    assert len(arm_slots & slots) >= 2, f"Biceps direct work missing: {sorted(slots)}"
    assert len(triceps_slots & slots) >= 2, f"Triceps direct work missing: {sorted(slots)}"
    assert {"forearm_wrist", "forearm_reverse"} & slots, "Forearm work missing"
    assert "shrug" in slots, "Shrug (Kelso nearest-match) work missing"


@pytest.mark.parametrize("gender,frequency", [("male", 3), ("female", 3)])
def test_incline_and_front_pulldown_reach_programs(gender, frequency):
    program = _generate(gender, frequency)
    names = {exercise.exercise_name.lower() for day in program.days for exercise in day.exercises}
    assert any("incline" in name and ("press" in name or "bench" in name) for name in names), names
    assert any(("pulldown" in name or "pull-up" in name or "pull up" in name) for name in names), names


def test_no_duplicate_exercises_within_a_day():
    program = _generate("male", 4)
    for day in program.days:
        ids = [exercise.exercise_id for exercise in day.exercises]
        assert len(ids) == len(set(ids)), f"Duplicate exercise inside {day.day_name}"


def test_program_output_is_english_only_with_catalog_steps():
    program = _generate("male", 4)
    assert program.instructions == ""
    for day in program.days:
        for exercise in day.exercises:
            assert exercise.notes, f"Missing catalog execution steps on {exercise.exercise_name}"
            assert not any("\u0600" <= char <= "\u06ff" for char in exercise.notes)
            assert exercise.notes != "-"


def test_prescriptions_follow_reference_scheme():
    program = _generate("male", 4)
    for day in program.days:
        for exercise in day.exercises:
            assert 0 <= exercise.warmup_sets <= 4
            assert 1 <= exercise.target_sets <= 4
            assert exercise.target_reps_min >= 4
            assert exercise.target_reps_max <= 30
            assert exercise.rest_seconds >= 120
            if exercise.slot_key in {"quad_compound", "ham_hinge", "horizontal_row"}:
                assert exercise.rest_seconds >= 240, "Heavy compounds need 4+ minute rests"
            if exercise.slot_key in {"quad_compound", "ham_hinge", "horizontal_row", "incline_press", "flat_press"}:
                assert exercise.warmup_sets >= 1, "Heavy compounds need a ramp-up set"


def test_day_working_set_totals_match_reference_profiles():
    """Guardrails for the 22-sets-per-day regression: sessions stay in sample ranges."""
    expected_ranges = {
        ("male", 3): (12, 16),
        ("male", 4): (12, 17),
        ("male", 5): (10, 15),
        ("female", 3): (12, 17),
    }
    for (gender, frequency), (low, high) in expected_ranges.items():
        program = _generate(gender, frequency)
        totals = [sum(exercise.target_sets for exercise in day.exercises) for day in program.days]
        for total, day in zip(totals, program.days, strict=True):
            assert low <= total <= high, f"{gender} {frequency}d {day.day_name}: {total} working sets"
        weekly = sum(totals)
        assert weekly <= 70, f"{gender} {frequency}d weekly working sets too high: {weekly}"


def test_full_body_days_use_minimal_profiles():
    program = _generate("male", 3)
    for day in program.days:
        plan = next(plan_day for plan_day in get_split_plan("full_body", 3, "male").days if plan_day.day_name == day.day_name)
        double_slots = set(plan.double_slots)
        for exercise in day.exercises:
            if exercise.slot_key == "calf":
                assert exercise.target_sets == 2
            elif exercise.slot_key in double_slots:
                assert exercise.target_sets == 2
            else:
                assert exercise.target_sets == 1, f"{day.day_name}/{exercise.slot_key} should carry 1 set"


def test_anterior_posterior_split_preset_exists():
    plan = get_split_plan("anterior_posterior", 4, "male")
    assert plan is not None
    names = [day.day_name for day in plan.days]
    assert names == ["Anterior", "Posterior", "Anterior 2", "Posterior 2"]
    assert all(day.target_slots for day in plan.days)
    assert plan.days[0].warmup_family == "upper"
    assert plan.days[1].warmup_family == "upper"


def test_arnold_split_preset_matches_sample_shape():
    plan = get_split_plan("arnold", 3, "male")
    assert plan is not None
    counts = [len(day.target_slots) for day in plan.days]
    assert counts == [7, 7, 7]
    assert [day.day_name for day in plan.days] == ["Chest & Back", "Shoulders & Arms", "Legs"]


def test_arnold_x_ul_matches_belghamdi_day_sizes():
    plan = get_split_plan("arnold_x_ul", 5, "male")
    assert plan is not None
    assert [len(day.target_slots) for day in plan.days] == [7, 7, 6, 7, 6]


def test_arnold_keyword_routes_to_hybrid_at_high_frequency():
    plan_5 = get_split_plan("arnold", 5, "male")
    assert plan_5.split_name == "Arnold x Upper/Lower"
    assert [day.day_name for day in plan_5.days] == ["Chest & Back", "Shoulders & Arms", "Lower A", "Upper", "Lower B"]
    assert [len(day.target_slots) for day in plan_5.days] == [7, 7, 6, 7, 6]

    plan_4 = get_split_plan("arnold", 4, "male")
    assert plan_4.split_name == "Arnold x Upper/Lower (4-Day)"
    assert [day.day_name for day in plan_4.days] == ["Chest & Back", "Shoulders & Arms", "Lower A", "Upper"]

    plan_3 = get_split_plan("arnold", 3, "male")
    assert [day.day_name for day in plan_3.days] == ["Chest & Back", "Shoulders & Arms", "Legs"]


def test_anterior_posterior_five_day_has_unique_day_names():
    plan = get_split_plan("anterior_posterior", 5, "male")
    assert plan is not None
    names = [day.day_name for day in plan.days]
    assert names == ["Anterior", "Posterior", "Anterior 2", "Posterior 2", "Anterior 3"]
    assert len(names) == len(set(names))
    assert all(len(day.target_slots) >= 6 for day in plan.days)


def test_keyword_matching_is_not_hijacked_by_body_part_phrases():
    assert match_split_keyword("I have lower back pain, keep the program easy") is None
    assert match_split_keyword("focus on upper chest please") is None
    assert match_split_keyword("posterior chain focus with more back volume") is None
    assert match_split_keyword("give me an upper lower split") == "upper_lower"
    assert match_split_keyword("I want Upper, Lower, and an isolated Arms & Shoulders day") == "upper_lower"
    assert match_split_keyword("push/pull/legs") == "ppl"
    assert match_split_keyword("PPL") == "ppl"
    assert match_split_keyword("fullbody please") == "full_body"
    assert match_split_keyword("total body") == "full_body"
    assert match_split_keyword("anterior posterior") == "anterior_posterior"
    assert match_split_keyword("arnold style") == "arnold"


def test_unsupported_keyword_frequency_falls_back_to_default():
    assert resolve_split(1, "arnold split").split_name == resolve_split(1).split_name
    assert resolve_split(1, "ppl").split_name == resolve_split(1).split_name
    assert resolve_split(1, "upper lower").split_name == resolve_split(1).split_name


def test_resolve_split_routes_preferences_deterministically():
    assert resolve_split(3, "give me an arnold split").split_name.startswith("Arnold")
    assert "Anterior" in resolve_split(2, "anterior posterior").split_name
    assert resolve_split(3, "I want upper lower").split_name.startswith("Upper / Lower")
    assert resolve_split(3, "push pull legs").split_name.startswith("Push / Pull / Legs")


def test_schema_round_trip_persists_warmups_and_slots():
    program = _generate("male", 3)
    loaded = db.get_active_program()
    assert loaded is not None
    assert loaded.instructions == program.instructions
    for generated_day, stored_day in zip(program.days, loaded.days, strict=True):
        assert len(stored_day.exercises) == len(generated_day.exercises)
        assert len(stored_day.warmup_exercises) == len(generated_day.warmup_exercises)
        for generated_ex, stored_ex in zip(generated_day.exercises, stored_day.exercises, strict=True):
            assert stored_ex.slot_key == generated_ex.slot_key
            assert stored_ex.warmup_sets == generated_ex.warmup_sets
            assert stored_ex.notes == generated_ex.notes


def test_excel_export_uses_english_sheet_layout():
    program = _generate("male", 3)
    payload = export_program_to_excel(program)
    assert payload[:2] == b"PK"
    import io

    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(payload))
    assert workbook.sheetnames[0].startswith("Day 1")
    day_sheet = workbook[workbook.sheetnames[0]]
    headers = [cell.value for cell in day_sheet[1]]
    assert headers[:7] == ["Day", "Exercise", "Warm-up Sets", "Working Sets", "Reps", "RPE", "Rest"]


def test_excel_export_renders_cardio_once():
    program = _generate("male", 4)
    assert any(day.cardio for day in program.days), "UL blueprint should include cardio notes"
    payload = export_program_to_excel(program)
    import io

    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(payload))
    for day, sheet_name in zip(program.days, workbook.sheetnames, strict=True):
        sheet = workbook[sheet_name]
        cardio_rows = sum(
            1
            for row in sheet.iter_rows(min_row=2, values_only=True)
            if day.cardio and row[1] == day.cardio
        )
        expected = 1 if day.cardio else 0
        assert cardio_rows == expected, f"{day.day_name}: expected {expected} cardio row(s), got {cardio_rows}"


def test_split_day_pools_cover_all_defined_days():
    for split_type, pool in SPLIT_DAY_POOLS.items():
        for day in pool:
            assert day.slots, f"{split_type}/{day.name} has no slots"
            assert all(slot in SLOT_SPECS for slot in day.slots)


def test_is_fat_loss_goal_patterns():
    assert is_fat_loss_goal("fat loss")
    assert is_fat_loss_goal("Losing weight")
    assert is_fat_loss_goal("lose weight for summer")
    assert is_fat_loss_goal("lose some weight")
    assert is_fat_loss_goal("losing a bit of weight")
    assert is_fat_loss_goal("weight loss")
    assert is_fat_loss_goal("cutting phase")
    assert is_fat_loss_goal("cut")
    assert is_fat_loss_goal("get lean")
    assert is_fat_loss_goal("shredding")
    assert is_fat_loss_goal("burn fat")
    assert is_fat_loss_goal("burning body fat")
    assert is_fat_loss_goal("reduce my body fat")
    assert is_fat_loss_goal("drop some fat")
    assert is_fat_loss_goal("lower body fat percentage")
    assert is_fat_loss_goal("fat reduction")
    assert is_fat_loss_goal("slim down")
    assert is_fat_loss_goal("slimming down")
    assert is_fat_loss_goal("get more defined")
    assert is_fat_loss_goal("look defined")
    assert is_fat_loss_goal("recomp")
    assert is_fat_loss_goal("recomposition")
    assert is_fat_loss_goal("tone up")
    assert is_fat_loss_goal("get toned")
    assert is_fat_loss_goal("toning")
    assert is_fat_loss_goal(None, "reach 12% body fat and lose weight")
    assert not is_fat_loss_goal("hypertrophy")
    assert not is_fat_loss_goal("bulking")
    assert not is_fat_loss_goal("muscle gain")
    assert not is_fat_loss_goal("gain weight")
    assert not is_fat_loss_goal("strength")
    assert not is_fat_loss_goal("progressive overload")
    assert not is_fat_loss_goal("get healthy")
    assert not is_fat_loss_goal("build more defined arms")
    assert not is_fat_loss_goal("well-defined shoulders")
    assert not is_fat_loss_goal("a ton of muscle")
    assert not is_fat_loss_goal(None, None)


@pytest.mark.parametrize("gender,frequency", [("male", 3), ("female", 3)])
def test_fat_loss_goal_adds_cardio_finisher_to_every_day(gender, frequency):
    program = _generate(gender, frequency, goal="fat loss")
    for day in program.days:
        assert day.cardio == FAT_LOSS_CARDIO_NOTE, day.day_name
        assert "Fat-loss finisher" in (day.cardio or "")
    loaded = db.get_active_program()
    assert loaded is not None
    assert [day.cardio for day in loaded.days] == [FAT_LOSS_CARDIO_NOTE] * len(program.days)


def test_other_goals_keep_default_cardio():
    for goal in ("hypertrophy", "bulking", "strength"):
        program = _generate("male", 4, goal=goal)
        for day in program.days:
            assert day.cardio and day.cardio.startswith("Light cardio:"), f"{goal}/{day.day_name}: {day.cardio}"
    full_body = _generate("male", 3, goal="bulking")
    assert all(day.cardio is None for day in full_body.days)


def test_goal_changes_only_the_cardio_layer():
    fat_loss = _generate("male", 4, goal="fat loss")
    hypertrophy = _generate("male", 4, goal="hypertrophy")
    assert [day.day_name for day in fat_loss.days] == [day.day_name for day in hypertrophy.days]
    for fl_day, hy_day in zip(fat_loss.days, hypertrophy.days, strict=True):
        fl_shape = [
            (ex.slot_key, ex.target_sets, ex.warmup_sets, ex.target_reps_min, ex.target_reps_max, ex.rest_seconds)
            for ex in fl_day.exercises
        ]
        hy_shape = [
            (ex.slot_key, ex.target_sets, ex.warmup_sets, ex.target_reps_min, ex.target_reps_max, ex.rest_seconds)
            for ex in hy_day.exercises
        ]
        assert fl_shape == hy_shape, f"Lifting program changed for {fl_day.day_name}"
        assert fl_day.cardio == FAT_LOSS_CARDIO_NOTE
        assert hy_day.cardio != FAT_LOSS_CARDIO_NOTE


def test_is_poor_recovery_patterns():
    assert is_poor_recovery("high stress, 5 hours sleep")
    assert is_poor_recovery("poor sleep")
    assert is_poor_recovery("I get 4 hours most nights")
    assert is_poor_recovery("insomnia lately")
    assert is_poor_recovery("sleep deprivation")
    assert is_poor_recovery("stressed")
    assert is_poor_recovery("lots of stress at work")
    assert not is_poor_recovery("good sleep, 8 hours, low stress")
    assert not is_poor_recovery("normal")
    assert not is_poor_recovery("7 hours sleep, low stress")
    assert not is_poor_recovery("well rested")
    assert not is_poor_recovery(None)


def test_poor_recovery_cuts_escalated_sets_only():
    normal = _generate("male", 4)
    poor = _generate("male", 4, recovery="high stress, 5 hours sleep")
    compound_slots = {
        "quad_compound",
        "ham_hinge",
        "horizontal_row",
        "upper_back_pull",
        "flat_press",
        "incline_press",
        "vertical_pull",
        "shoulder_press",
        "glute_thrust",
    }
    for n_day, p_day in zip(normal.days, poor.days, strict=True):
        assert [e.slot_key for e in n_day.exercises] == [e.slot_key for e in p_day.exercises]
        cuts = 0
        for n_ex, p_ex in zip(n_day.exercises, p_day.exercises, strict=True):
            if n_ex.target_sets != p_ex.target_sets:
                assert p_ex.target_sets == 1, f"{p_day.day_name}/{p_ex.slot_key} dropped below 1 set"
                cuts += 1
            if n_ex.slot_key in compound_slots or n_ex.slot_key == "calf":
                assert p_ex.target_sets == n_ex.target_sets, f"{p_day.day_name}/{p_ex.slot_key} lost a set"
        assert cuts <= MAX_RECOVERY_CUTS_PER_DAY, f"{p_day.day_name} cut {cuts} sets"
    normal_weekly = sum(e.target_sets for d in normal.days for e in d.exercises)
    poor_weekly = sum(e.target_sets for d in poor.days for e in d.exercises)
    reduction = (normal_weekly - poor_weekly) / normal_weekly
    assert 0.10 <= reduction <= 0.18, f"Recovery cut {reduction:.0%} outside the designed dose"


def test_recovery_cut_composes_with_fat_loss_goal():
    program = _generate("male", 4, goal="fat loss", recovery="poor sleep")
    normal_weekly = sum(
        e.target_sets for d in _generate("male", 4).days for e in d.exercises
    )
    weekly = sum(e.target_sets for d in program.days for e in d.exercises)
    assert weekly < normal_weekly
    for day in program.days:
        assert day.cardio == FAT_LOSS_CARDIO_NOTE


def test_back_limitation_substitutes_hamstring_alternative():
    program = _generate("male", 4, limitations="lower back tightness")
    names = [e.exercise_name.lower() for d in program.days for e in d.exercises]
    assert not any("deadlift" in name or "good morning" in name for name in names)
    for day in program.days:
        assert len(day.exercises) >= 10, f"{day.day_name} shrank to {len(day.exercises)} exercises"
    lower2 = next(d for d in program.days if d.day_name == "Lower 2")
    ham_curls = [e for e in lower2.exercises if e.slot_key == "ham_curl"]
    assert len(ham_curls) >= 2, "ham_hinge fallback did not add a second leg-curl variant"

    full_body = _generate("male", 3, limitations="lower back tightness")
    for day in full_body.days:
        assert len(day.exercises) == 11, f"{day.day_name} lost an exercise to the back rule"


def test_mobility_limitations_leave_program_unchanged():
    baseline = _generate("male", 4)
    mobility = _generate("male", 4, limitations="shoulder lack of flexibility, lower body stiffness")
    for b_day, m_day in zip(baseline.days, mobility.days, strict=True):
        b_shape = [
            (ex.slot_key, ex.target_sets, ex.warmup_sets, ex.target_reps_min, ex.target_reps_max, ex.rest_seconds)
            for ex in b_day.exercises
        ]
        m_shape = [
            (ex.slot_key, ex.target_sets, ex.warmup_sets, ex.target_reps_min, ex.target_reps_max, ex.rest_seconds)
            for ex in m_day.exercises
        ]
        assert b_shape == m_shape, f"Mobility limitation changed the lifting plan for {b_day.day_name}"
