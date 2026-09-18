import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from agent.program_generator import generate_program_pipeline
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)
db = DatabaseManager()


def run_test():
    logger.info("--- Starting Phase 2 Program Generation ---")

    # 1. Mount isolated test ledger and seed baseline profile
    test_user = "test_generator_trainee"
    db.switch_user(test_user)
    db.upsert_user_profile(
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
    program, table_view = generate_program_pipeline()

    # 3. Assertions
    assert program is not None, "Failed: Program generation returned None."
    assert len(program.days) == 4, f"Expected 4 training days, got {len(program.days)}"
    assert db.get_active_program() is not None, "Failed: Program not persisted to SQLite."

    logger.info("\n" + "=" * 50)
    logger.info(table_view)
    logger.info("=" * 50)
    logger.info("\nPhase 2 Program Generation & Database Persistence Verified.")


import pytest
from unittest.mock import MagicMock

from pydantic import ValidationError

from agent import program_generator
from agent.ProgramState import GeneratedProgramSchema, ProgramSchema
from agent.UserState import UserProfileSchema


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
    database.get_user_profile.return_value = {"weekly_frequency": frequency if source == "profile" else 4}
    split = MagicMock()
    monkeypatch.setattr(program_generator, "db", database)
    monkeypatch.setattr(program_generator, "resolve_split", split)
    kwargs = {"frequency_override": frequency} if source == "override" else {}
    with pytest.raises(ValueError, match="1 to 5"):
        generate_program_pipeline(**kwargs)
    assert database.method_calls == [("get_user_profile", (), {})]
    split.assert_not_called()


@pytest.mark.parametrize("frequency", ["0", "6", "7", "14", "zero", "six", "twelve", "twenty-one", "one hundred"])
def test_invalid_text_frequency_not_hidden_by_valid_override(monkeypatch, frequency):
    database = MagicMock()
    database.get_user_profile.return_value = {"weekly_frequency": 4}
    monkeypatch.setattr(program_generator, "db", database)
    with pytest.raises(ValueError, match="1 to 5"):
        generate_program_pipeline(user_split_override=f"switch routine to {frequency} days", frequency_override=3)
    assert database.method_calls == [("get_user_profile", (), {})]


@pytest.mark.parametrize("schema", [UserProfileSchema, ProgramSchema, GeneratedProgramSchema])
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


if __name__ == "__main__":
    run_test()
