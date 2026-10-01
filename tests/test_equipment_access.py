"""Equipment access free-text mapping and ledger migration (#228)."""

import json
import sqlite3
from contextlib import closing

import pytest

from database.migration_manager import apply_lazy_migrations, get_ledger_schema_version
from service.intake import validate_answer
from utils.equipment_access import (
    BODYWEIGHT_ONLY,
    COMMERCIAL_GYM,
    EQUIPMENT_ACCESS_VALUES,
    HOME_GYM,
    equipment_access_allows,
    equipment_access_filter,
    map_equipment_access,
)


_GENERATION_SPLITS = [
    ("default", None, "male", range(1, 6)),
    ("PPL", "PPL", "male", range(2, 6)),
    ("Arnold", "Arnold", "male", range(2, 6)),
    ("Upper / Lower", "upper lower", "male", range(2, 6)),
    ("Anterior / Posterior", "anterior posterior", "male", range(2, 6)),
    ("Full Body", "full body", "male", range(1, 6)),
    ("female default", None, "female", range(1, 6)),
    ("female Upper / Lower", "upper lower", "female", range(2, 6)),
    ("female Full Body", "full body", "female", range(1, 6)),
]


@pytest.mark.parametrize("access", EQUIPMENT_ACCESS_VALUES)
@pytest.mark.parametrize(
    "split_name,split_override,gender,frequency",
    [
        (name, override, gender, frequency)
        for name, override, gender, frequencies in _GENERATION_SPLITS
        for frequency in frequencies
    ],
)
def test_generated_program_working_sets_fit_equipment_access(
    fresh_store, access, split_name, split_override, gender, frequency
):
    from agent.program_generator import generate_program_pipeline

    fresh_store.ledger.upsert_player_profile({
        "gender": gender, "proportions": "balanced", "age": 30,
        "weight_kg": 80, "height_cm": 180, "rep_preference": "balanced",
        "current_goal": "hypertrophy", "long_term_goal": "strength",
        "weekly_frequency": frequency, "training_age_years": 3,
        "equipment_access": access, "injuries_or_limitations": "None",
        "stress_and_sleep": "normal",
    })

    program, _ = generate_program_pipeline(
        ledger=fresh_store.ledger,
        user_split_override=split_override,
        frequency_override=frequency,
    )

    free_weights = {"barbell", "dumbbell", "ez barbell", "olympic barbell", "kettlebell", "trap bar"}
    bands = {"band", "resistance band"}
    bodyweight = {"body weight", "bodyweight"}
    expected = (
        free_weights | bands | bodyweight | {"weighted"} if access == HOME_GYM
        else bodyweight if access == BODYWEIGHT_ONLY
        else None
    )
    for day in program.days:
        assert day.exercises
        for exercise in day.exercises:
            entry = fresh_store.get_exercise_library_entry(exercise.exercise_id)
            category = entry["equipment"].casefold()
            if expected is None:
                assert category not in bands | bodyweight | {"weighted"}
            else:
                assert category in expected


@pytest.mark.parametrize(
    "access,allowed",
    [
        (COMMERCIAL_GYM, {"barbell"}),
        (HOME_GYM, {"barbell", "body weight", "band", "weighted"}),
        (BODYWEIGHT_ONLY, {"body weight"}),
    ],
)
def test_weighted_exercise_equipment_matches_equipment_access(access, allowed):
    assert {equipment for equipment in ("barbell", "body weight", "band", "weighted")
            if equipment_access_allows(access, equipment)} == allowed


def test_equipment_access_filter_names_its_list_mode():
    commercial_filter = equipment_access_filter(COMMERCIAL_GYM)
    home_filter = equipment_access_filter(HOME_GYM)

    assert commercial_filter.allow_list is False
    assert "weighted" in commercial_filter.equipment_values
    assert home_filter.allow_list is True
    assert "weighted" in home_filter.equipment_values


def test_commercial_gym_warmup_movements_keep_bodyweight_options(fresh_store):
    from agent.program_generator import generate_program_pipeline

    fresh_store.ledger.upsert_player_profile({
        "gender": "male", "proportions": "balanced", "age": 30,
        "weight_kg": 80, "height_cm": 180, "rep_preference": "balanced",
        "current_goal": "hypertrophy", "long_term_goal": "strength",
        "weekly_frequency": 3, "training_age_years": 3,
        "equipment_access": COMMERCIAL_GYM, "injuries_or_limitations": "None",
        "stress_and_sleep": "normal",
    })

    program, _ = generate_program_pipeline(ledger=fresh_store.ledger)

    assert all(day.warmup_exercises for day in program.days)
    warmup_categories = {
        fresh_store.get_exercise_library_entry(movement.exercise_id)["equipment"].casefold()
        for day in program.days
        for movement in day.warmup_exercises
    }
    assert warmup_categories & {"body weight", "band", "resistance band"}


@pytest.mark.parametrize(
    ("free_text", "expected"),
    [
        ("a big gym", COMMERCIAL_GYM),
        ("commercial gym", COMMERCIAL_GYM),
        ("my gym", COMMERCIAL_GYM),
        ("the gym", COMMERCIAL_GYM),
        ("commercial gym near my home", COMMERCIAL_GYM),
        ("my garage", HOME_GYM),
        ("home gym", HOME_GYM),
        ("no gym, just dumbbells at home", HOME_GYM),
        ("dumbbells and a bench", HOME_GYM),
        ("bands only", HOME_GYM),
        ("I workout at home with nothing", BODYWEIGHT_ONLY),
        ("hotel room, no equipment", BODYWEIGHT_ONLY),
        ("no equipment", BODYWEIGHT_ONLY),
        ("nothing", BODYWEIGHT_ONLY),
        ("bodyweight only", BODYWEIGHT_ONLY),
        ("unmapped training place", COMMERCIAL_GYM),
    ],
)
def test_equipment_access_mapping(free_text, expected):
    assert map_equipment_access(free_text) == expected
    assert validate_answer("equipment_access", free_text) == expected


@pytest.mark.parametrize(
    ("legacy_value", "expected"),
    [
        ("a big gym", COMMERCIAL_GYM),
        ("commercial gym", COMMERCIAL_GYM),
        ("my garage", HOME_GYM),
        ("hotel room, no equipment", BODYWEIGHT_ONLY),
        ("unmapped legacy value", COMMERCIAL_GYM),
    ],
)
def test_v16_migration_maps_legacy_profiles_and_intake(legacy_value, expected, tmp_path):
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute(
            "CREATE TABLE user_profile (id INTEGER PRIMARY KEY, equipment_access TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE intake_answers (field TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO user_profile VALUES (1, ?)", (legacy_value,))
        conn.execute(
            "INSERT INTO intake_answers VALUES ('equipment_access', ?)",
            (json.dumps(legacy_value),),
        )
        conn.execute("PRAGMA user_version = 16")
        conn.commit()

        apply_lazy_migrations(
            conn,
            username="equipment-access-test",
            ledgers_dir=tmp_path / "ledgers",
            backups_dir=tmp_path / "backups",
            target_version=17,
        )

        profile_access = conn.execute(
            "SELECT equipment_access FROM user_profile"
        ).fetchone()[0]
        intake_access = conn.execute("SELECT value FROM intake_answers").fetchone()[0]
        assert profile_access == expected
        assert json.loads(intake_access) == expected
        assert get_ledger_schema_version(conn) == 17
        with pytest.raises(sqlite3.IntegrityError, match="Invalid Equipment access"):
            conn.execute("UPDATE user_profile SET equipment_access = 'fourth option'")
