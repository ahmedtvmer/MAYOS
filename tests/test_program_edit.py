from agent.ProgramState import (
    PersistedProgramDaySchema,
    PersistedProgramExerciseSchema,
    PersistedProgramSchema,
    PersistedProgramWeekSchema,
)
from service.program_analytics import ProgramAnalyticsActor
from service.program_edit import (
    ProgramEdit,
    ProgramEditExercise,
    edit_active_program_day,
)

TEST_PLAYER_ID = "00000000-0000-4000-8000-000000000001"


def test_program_edit_targets_week_and_day_coordinates(fresh_store):
    db = fresh_store
    ledger = db.ledger
    catalog_exercises = db.catalog_conn.execute(
        "SELECT id, name FROM exercises ORDER BY id LIMIT 2"
    ).fetchall()
    first_id, first_name = str(catalog_exercises[0][0]), str(catalog_exercises[0][1])
    second_id, second_name = str(catalog_exercises[1][0]), str(catalog_exercises[1][1])
    first_exercise = PersistedProgramExerciseSchema(
        exercise_id=first_id,
        exercise_name=first_name,
        target_sets=3,
        target_reps_min=5,
        target_reps_max=8,
    )
    second_exercise = PersistedProgramExerciseSchema(
        exercise_id=second_id,
        exercise_name=second_name,
        target_sets=4,
        target_reps_min=5,
        target_reps_max=8,
    )
    first_day = PersistedProgramDaySchema(
        day_name="Full A",
        day_order=1,
        week_order=1,
        exercises=[first_exercise],
    )
    second_day = PersistedProgramDaySchema(
        day_name="Full A",
        day_order=1,
        week_order=2,
        exercises=[second_exercise],
    )
    ledger.save_training_program(
        PersistedProgramSchema(
            program_name="Two-week plan",
            split_type="Full Body",
            weekly_frequency=1,
            days=[first_day, second_day],
            weeks=[
                PersistedProgramWeekSchema(
                    week_name="Base", week_order=1, days=[first_day]
                ),
                PersistedProgramWeekSchema(
                    week_name="Build", week_order=2, days=[second_day]
                ),
            ],
        ).model_dump()
    )
    active = ledger.get_active_program()
    ledger.log_workout_session(
        "program-edit-cursor-seed",
        "2026-10-01",
        "Full A",
        "2026-10-01T10:00:00+00:00",
        "2026-10-01T11:00:00+00:00",
        program_version=active.version,
        program_week_order=1,
        program_day_order=1,
    )

    edit_active_program_day(
        db,
        ledger,
        ProgramEdit(
            day_name="Full A",
            expected_active_version=active.version,
            exercises=[ProgramEditExercise(0, second_id, 2)],
            player_account_id=TEST_PLAYER_ID,
            actor=ProgramAnalyticsActor(TEST_PLAYER_ID, "player"),
            week_order=2,
            day_order=1,
        ),
    )

    updated = ledger.get_active_program()
    assert updated.weeks[0].days[0].exercises[0].exercise_id == first_id
    assert updated.weeks[1].days[0].exercises[0].target_sets == 2
    position = ledger.get_program_position(updated)
    assert (position.current_week, position.next_day_order) == (2, 1)
