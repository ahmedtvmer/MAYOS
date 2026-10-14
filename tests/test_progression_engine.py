# scripts/test_progression_engine.py
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from agent.progression_engine import calculate_e1rm, project_next_load
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)


def run_tests():
    logger.info("⚡ Starting Dynamic RPE Progression Engine Tests...\n")

    # 1. Test e1RM Formulation
    e1rm = calculate_e1rm(weight_kg=100.0, reps=8, rpe=8.0)
    # Effective reps = 8 + (10 - 8) = 10 -> 100 * (1 + 10/30) = 133.33 kg
    assert abs(e1rm - 133.33) < 0.1, f"e1RM mismatch: {e1rm}"
    logger.info(f"✅ e1RM Calculated: 100kg x 8 @ RPE 8.0 -> {e1rm:.2f}kg e1RM")

    # 2. Test Dynamic Projection Upward (Achieved top of bracket with low RPE)
    # Target was 8 reps @ RPE 8.5. User did 8 reps @ RPE 7.0 (reserve velocity left)
    proj_up = project_next_load(
        last_weight=100.0, last_reps=8, last_rpe=7.0, target_reps=8, target_rpe=8.5, equipment="barbell"
    )
    assert proj_up["delta_kg"] > 0, "Failed to project weight increase on low RPE."
    assert proj_up["projected_weight"] % 2.5 == 0, "Failed to snap to 2.5kg barbell increment."
    logger.info(
        f"✅ Dynamic Upscale: 100kg @ RPE 7.0 -> Next Target: {proj_up['projected_weight']}kg (+{proj_up['delta_kg']}kg)"
    )

    # 3. Test RPE Overshoot Deload / Step-Down
    # User was supposed to hit RPE 8.0 but hit RPE 10.0 (absolute failure)
    proj_down = project_next_load(
        last_weight=100.0, last_reps=6, last_rpe=10.0, target_reps=8, target_rpe=8.0, equipment="barbell"
    )
    assert proj_down["delta_kg"] <= 0, "Failed to protect player on RPE 10 overshoot."
    logger.info(
        f"✅ Overshoot Protection: 100kg @ RPE 10.0 -> Next Target: {proj_down['projected_weight']}kg ({proj_down['delta_kg']}kg)"
    )

    logger.info("\n🎉 Dynamic RPE Progression calculations verified successfully.")


import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from agent.ProgramState import (
    PersistedProgramDaySchema,
    PersistedProgramExerciseSchema,
    PersistedProgramSchema,
    PersistedProgramWeekSchema,
)
from agent.progression_engine import get_progression_signals


@pytest.mark.parametrize("days_ago,exposures,expected_baseline", [(None, 0, True), (0, 0, False), (0, 2, False), (90, 2, False)])
def test_progression_baseline_requires_empty_all_time_ledger(days_ago, exposures, expected_baseline):
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript("""
            ATTACH DATABASE ':memory:' AS catalog;
            CREATE TABLE catalog.exercises (id TEXT, name TEXT, equipment TEXT);
            CREATE TABLE catalog.coach_exercises (
                id TEXT, name TEXT, equipment TEXT, body_part TEXT
            );
            CREATE TABLE workout_sessions (
                id TEXT, session_date TEXT, program_week_order INTEGER, program_day_order INTEGER
            );
            CREATE TABLE workout_sets (
                session_id TEXT, exercise_id TEXT, weight_kg REAL, reps INTEGER,
                rpe REAL, set_index INTEGER, is_warmup INTEGER
            );
            INSERT INTO catalog.exercises VALUES ('squat', 'Barbell Squat', 'barbell');
        """)
        if days_ago is not None:
            for index in range(max(exposures, 1)):
                date = (datetime.now(UTC) - timedelta(days=days_ago + index)).date().isoformat()
                connection.execute(
                    "INSERT INTO workout_sessions VALUES (?, ?, NULL, NULL)",
                    (str(index), date),
                )
                if exposures:
                    connection.execute("INSERT INTO workout_sets VALUES (?, 'squat', 80, 8, 8.5, 1, 0)", (str(index),))
        database = SimpleNamespace(ledger_conn=connection, conn=connection, get_active_program=lambda: None)
        result = get_progression_signals(database)
        if expected_baseline:
            assert result == "Progression: Establishing baseline loads across routine."
        else:
            assert result == "Progression: No progression or stall signals in the last 30 days."
    finally:
        connection.close()


def test_progression_targets_follow_logged_week_when_current_week_advances(fresh_store):
    ledger = fresh_store.ledger
    exercise = fresh_store.catalog_conn.execute(
        "SELECT id, name FROM exercises ORDER BY id LIMIT 1"
    ).fetchone()
    exercise_id, exercise_name = str(exercise[0]), str(exercise[1])
    first_day = PersistedProgramDaySchema(
        day_name="A",
        day_order=1,
        week_order=1,
        exercises=[
            PersistedProgramExerciseSchema(
                exercise_id=exercise_id,
                exercise_name=exercise_name,
                target_reps_min=5,
                target_reps_max=8,
            )
        ],
    )
    first_week_second_day = first_day.model_copy(
        update={"day_name": "B", "day_order": 2}
    )
    second_week_day = first_day.model_copy(
        update={
            "week_order": 2,
            "exercises": [
                first_day.exercises[0].model_copy(
                    update={"target_reps_min": 10, "target_reps_max": 12}
                )
            ],
        }
    )
    program = PersistedProgramSchema(
        program_name="Rep ranges",
        split_type="custom",
        weekly_frequency=2,
        days=[first_day, first_week_second_day, second_week_day],
        weeks=[
            PersistedProgramWeekSchema(
                week_name="Week 1",
                week_order=1,
                days=[first_day, first_week_second_day],
            ),
            PersistedProgramWeekSchema(
                week_name="Week 2", week_order=2, days=[second_week_day]
            ),
        ],
    )
    ledger.save_training_program(program.model_dump())
    active_program = ledger.get_active_program()
    session_date = (datetime.now(UTC) - timedelta(days=3)).date()

    for index in range(2):
        date = session_date + timedelta(days=index)
        session_id = f"week-one-{index}"
        ledger.log_workout_session(
            session_id,
            date.isoformat(),
            "A",
            f"{date.isoformat()}T10:00:00+00:00",
            f"{date.isoformat()}T11:00:00+00:00",
            program_version=active_program.version,
            program_week_order=1,
            program_day_order=1,
        )
        ledger.log_workout_set(
            f"set-{index}", session_id, exercise_id, 1, 100 + index * 5, 8, 8.0
        )

    assert ledger.get_program_position(active_program).current_week == 1
    first_signal = get_progression_signals(ledger)
    ledger.log_workout_session(
        "finish-week-one",
        (session_date + timedelta(days=2)).isoformat(),
        "B",
        f"{session_date + timedelta(days=2)}T10:00:00+00:00",
        f"{session_date + timedelta(days=2)}T11:00:00+00:00",
        program_version=active_program.version,
        program_week_order=1,
        program_day_order=2,
    )

    assert ledger.get_program_position(active_program).current_week == 2
    second_signal = get_progression_signals(ledger)
    assert first_signal == second_signal
    assert "+2.5kg target" in first_signal


if __name__ == "__main__":
    run_tests()
