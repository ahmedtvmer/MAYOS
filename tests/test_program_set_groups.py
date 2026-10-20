from pydantic import ValidationError
import pytest

from agent.ProgramState import ProgramExerciseSchema
from database.migration_manager import MIGRATION_REGISTRY
import sqlite3


def test_program_exercise_accepts_ordered_set_groups_and_backoff_load():
    exercise = ProgramExerciseSchema.model_validate({
        "exercise_id": "bench", "exercise_name": "Bench Press",
        "target_sets": 3, "target_reps_min": 6, "target_reps_max": 8,
        "set_groups": [
            {"sets": 3, "reps_min": 6, "reps_max": 8, "target_rir": 2},
            {"sets": 2, "reps_min": 10, "reps_max": 12, "target_rir": 1,
             "load": {"kind": "pct_of_first_group", "value": 80}, "amrap_last_set": True},
        ],
    })

    assert [group.sets for group in exercise.set_groups] == [3, 2]
    assert exercise.set_groups[1].load.kind == "pct_of_first_group"
    assert exercise.working_sets == 5


def test_explicit_single_group_is_source_of_truth_for_flat_mirrors():
    exercise = ProgramExerciseSchema.model_validate({
        "exercise_id": "bench", "exercise_name": "Bench Press",
        "target_sets": 4, "target_reps_min": 4, "target_reps_max": 4,
        "target_rpe": 9,
        "set_groups": [{"sets": 2, "reps_min": 6, "reps_max": 8,
                        "target_rir": 1, "amrap_last_set": True}],
    })

    assert (exercise.target_sets, exercise.target_reps_min, exercise.target_reps_max) == (2, 6, 8)
    assert exercise.target_rpe == 9
    assert exercise.set_groups[0].amrap_last_set is True


def test_first_group_percentage_is_rejected_on_first_group():
    with pytest.raises(ValidationError):
        ProgramExerciseSchema.model_validate({
            "exercise_id": "bench", "exercise_name": "Bench Press",
            "target_sets": 1, "target_reps_min": 6, "target_reps_max": 8,
            "set_groups": [{"sets": 1, "reps_min": 6, "reps_max": 8,
                            "target_rir": 2,
                            "load": {"kind": "pct_of_first_group", "value": 80}}],
        })


def test_ledger_v35_adds_nullable_set_groups_storage_without_rewriting_legacy_rows():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE program_exercises (id TEXT, target_sets INTEGER)")
    connection.execute("INSERT INTO program_exercises VALUES ('old', 3)")

    MIGRATION_REGISTRY[34](connection)

    columns = {row[1] for row in connection.execute("PRAGMA table_info(program_exercises)")}
    assert "set_groups_json" in columns
    assert connection.execute("SELECT set_groups_json FROM program_exercises").fetchone()[0] is None
