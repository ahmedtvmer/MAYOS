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


def test_program_edit_records_trim_reorder_removal_and_keeps_reasons(fresh_store):
    db = fresh_store
    ledger = db.ledger
    rows = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 4").fetchall()
    exercises = [PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]), target_sets=3, target_reps_min=8, target_reps_max=12) for row in rows]
    day = PersistedProgramDaySchema(day_name="Edit", day_order=1, exercises=exercises)
    rationale = {"split": {"code": "split.frequency_default", "params": {}}, "day_order": {"code": "day_order.template", "params": {}}, "days": [{"day_order": 1, "exercises": [
        {"position": i + 1, "exercise_id": str(row[0]), "rationale": {"selection": {"code": f"selection.generator_{i}"}}} for i, row in enumerate(rows)
    ]}]}
    program = PersistedProgramSchema(program_name="Edit", split_type="Full Body", weekly_frequency=1, days=[day], program_rationale=rationale)
    ledger.save_training_program(program.model_dump())
    active = ledger.get_active_program()
    result = edit_active_program_day(db, ledger, ProgramEdit(day_name="Edit", expected_active_version=active.version,
        exercises=[ProgramEditExercise(0, str(rows[0][0]), 3), ProgramEditExercise(2, str(rows[2][0]), 2), ProgramEditExercise(3, str(rows[3][0]), 3)],
        player_account_id=TEST_PLAYER_ID, actor=ProgramAnalyticsActor(TEST_PLAYER_ID, "player"), day_order=1))
    assert result["version"] == 2
    saved = ledger.get_active_program().program_rationale["days"][0]
    by_id = {entry["exercise_id"]: entry for entry in saved["exercises"]}
    assert by_id[str(rows[2][0])]["rationale"]["selection"]["code"] == "selection.generator_2"
    assert by_id[str(rows[2][0])]["changes"][0]["code"] == "change.program_edit_trimmed"
    assert by_id[str(rows[2][0])]["changes"][0]["params"] == {"from_sets": 3, "to_sets": 2}
    assert by_id[str(rows[0][0])]["rationale"]["selection"]["code"] == "selection.generator_0"
    assert by_id[str(rows[0][0])].get("changes", []) == []
    assert by_id[str(rows[3][0])]["changes"][0]["code"] == "change.program_edit_reordered"
    assert saved["removed"][0]["exercise_id"] == str(rows[1][0])
    assert saved["removed"][0]["code"] == "change.program_edit_removed"


def test_program_edit_adds_visible_library_exercise_and_raises_sets(fresh_store):
    db = fresh_store
    ledger = db.ledger
    rows = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 3").fetchall()
    ids = [str(row[0]) for row in rows]
    day = PersistedProgramDaySchema(day_name="Edit", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=ids[0], exercise_name=str(rows[0][1]), target_sets=2, target_reps_min=8, target_reps_max=12),
    ])
    ledger.save_training_program(PersistedProgramSchema(program_name="Edit", split_type="Full Body", weekly_frequency=1, days=[day]).model_dump())
    active = ledger.get_active_program()
    candidate = db.get_exercise_library_entry(ids[1])
    if candidate and candidate["equipment"].lower() in {"body weight", "band"}:
        candidate = db.find_exercises_by_name("dumbbell", limit=1)[0]
    edit = ProgramEdit(day_name="Edit", expected_active_version=active.version,
        exercises=[ProgramEditExercise(0, ids[0], 4), ProgramEditExercise(-1, candidate["id"], 2)],
        player_account_id=TEST_PLAYER_ID, actor=ProgramAnalyticsActor(TEST_PLAYER_ID, "player"), day_order=1, preview=True)
    preview = edit_active_program_day(db, ledger, edit)
    assert preview["version"] == active.version
    assert "volume_warnings" in preview
    assert ledger.get_active_program().version == active.version
    result = edit_active_program_day(db, ledger, ProgramEdit(**{**edit.__dict__, "preview": False}))
    assert "code" not in result
    saved = ledger.get_active_program().days[0].exercises
    assert [exercise.exercise_id for exercise in saved] == [ids[0], candidate["id"]]
    assert saved[0].target_sets == 4
    rationale = ledger.get_active_program().program_rationale
    added = rationale["days"][0]["exercises"][-1]
    assert added["changes"][0]["code"] == "change.program_edit_added"
    assert added["changes"][0]["params"]["exercise_id"] == candidate["id"]
    assert added["changes"][0]["params"]["by"] == "player"
    assert added["changes"][0]["at"]


def test_program_edit_set_limit_applies_to_total_groups(fresh_store):
    db = fresh_store
    ledger = db.ledger
    row = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 1").fetchone()
    exercise = PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]),
        target_sets=1, target_reps_min=8, target_reps_max=12,
        set_groups=[{"sets": 1, "reps_min": 8, "reps_max": 12, "target_rir": 2}, {"sets": 2, "reps_min": 8, "reps_max": 12, "target_rir": 2}])
    day = PersistedProgramDaySchema(day_name="Edit", day_order=1, exercises=[exercise])
    ledger.save_training_program(PersistedProgramSchema(program_name="Edit", split_type="Full Body", weekly_frequency=1, days=[day]).model_dump())
    active = ledger.get_active_program()
    result = edit_active_program_day(db, ledger, ProgramEdit(day_name="Edit", expected_active_version=active.version,
        exercises=[ProgramEditExercise(0, str(row[0]), 4)], player_account_id=TEST_PLAYER_ID,
        actor=ProgramAnalyticsActor(TEST_PLAYER_ID, "player"), day_order=1))
    assert "code" not in result
    saved = ledger.get_active_program().days[0].exercises[0]
    assert sum(group.sets for group in saved.set_groups) == 4
    assert saved.set_groups[0].sets == 2
    assert saved.set_groups[1].sets == 2


def test_program_edit_rejects_total_below_backoff_sets_plus_one(fresh_store):
    db = fresh_store
    ledger = db.ledger
    row = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 1").fetchone()
    exercise = PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]),
        target_sets=1, target_reps_min=8, target_reps_max=12,
        set_groups=[{"sets": 1, "reps_min": 8, "reps_max": 12, "target_rir": 2},
                    {"sets": 3, "reps_min": 8, "reps_max": 12, "target_rir": 2}])
    day = PersistedProgramDaySchema(day_name="Edit", day_order=1, exercises=[exercise])
    ledger.save_training_program(PersistedProgramSchema(program_name="Edit", split_type="Full Body", weekly_frequency=1, days=[day]).model_dump())
    active = ledger.get_active_program()

    response = edit_active_program_day(db, ledger, ProgramEdit(day_name="Edit", expected_active_version=active.version,
        exercises=[ProgramEditExercise(0, str(row[0]), 3)], player_account_id=TEST_PLAYER_ID,
        actor=ProgramAnalyticsActor(TEST_PLAYER_ID, "player"), day_order=1))

    assert response["code"] == "invalid_set_count"


def test_program_edit_total_cap_does_not_turn_backoffs_into_seven_sets(fresh_store):
    db = fresh_store
    ledger = db.ledger
    rows = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 2").fetchall()
    grouped = PersistedProgramExerciseSchema(exercise_id=str(rows[0][0]), exercise_name=str(rows[0][1]),
        target_sets=1, target_reps_min=8, target_reps_max=12,
        set_groups=[{"sets": 1, "reps_min": 8, "reps_max": 12, "target_rir": 2},
                    {"sets": 3, "reps_min": 8, "reps_max": 12, "target_rir": 2}])
    other = PersistedProgramExerciseSchema(exercise_id=str(rows[1][0]), exercise_name=str(rows[1][1]),
        target_sets=2, target_reps_min=8, target_reps_max=12)
    day = PersistedProgramDaySchema(day_name="Edit", day_order=1, exercises=[grouped, other])
    ledger.save_training_program(PersistedProgramSchema(program_name="Edit", split_type="Full Body", weekly_frequency=1, days=[day]).model_dump())
    active = ledger.get_active_program()

    response = edit_active_program_day(db, ledger, ProgramEdit(day_name="Edit", expected_active_version=active.version,
        exercises=[ProgramEditExercise(0, str(rows[0][0]), 4)], player_account_id=TEST_PLAYER_ID,
        actor=ProgramAnalyticsActor(TEST_PLAYER_ID, "player"), day_order=1))

    assert "code" not in response
    saved = ledger.get_active_program().days[0].exercises[0]
    assert [group.sets for group in saved.set_groups] == [1, 3]
    assert sum(group.sets for group in saved.set_groups) == 4


def test_program_edit_keeps_existing_five_set_exercise_when_removing_another(fresh_store):
    db = fresh_store
    ledger = db.ledger
    rows = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 2").fetchall()
    grouped = PersistedProgramExerciseSchema(exercise_id=str(rows[0][0]), exercise_name=str(rows[0][1]),
        target_sets=3, target_reps_min=8, target_reps_max=12,
        set_groups=[{"sets": 3, "reps_min": 8, "reps_max": 12, "target_rir": 2},
                    {"sets": 2, "reps_min": 8, "reps_max": 12, "target_rir": 2}])
    other = PersistedProgramExerciseSchema(exercise_id=str(rows[1][0]), exercise_name=str(rows[1][1]), target_sets=2,
        target_reps_min=8, target_reps_max=12)
    day = PersistedProgramDaySchema(day_name="Edit", day_order=1, exercises=[grouped, other])
    ledger.save_training_program(PersistedProgramSchema(program_name="Edit", split_type="Full Body", weekly_frequency=1, days=[day]).model_dump())
    active = ledger.get_active_program()

    response = edit_active_program_day(db, ledger, ProgramEdit(day_name="Edit", expected_active_version=active.version,
        exercises=[ProgramEditExercise(0, str(rows[0][0]), 5)], player_account_id=TEST_PLAYER_ID,
        actor=ProgramAnalyticsActor(TEST_PLAYER_ID, "player"), day_order=1))

    assert "code" not in response
    saved = ledger.get_active_program().days[0].exercises
    assert len(saved) == 1
    assert [group.sets for group in saved[0].set_groups] == [3, 2]


def test_program_edit_can_lower_existing_five_sets_but_not_raise_to_six(fresh_store):
    db = fresh_store
    ledger = db.ledger
    row = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 1").fetchone()
    grouped = PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]), target_sets=3,
        target_reps_min=8, target_reps_max=12,
        set_groups=[{"sets": 3, "reps_min": 8, "reps_max": 12, "target_rir": 2},
                    {"sets": 2, "reps_min": 8, "reps_max": 12, "target_rir": 2}])
    day = PersistedProgramDaySchema(day_name="Edit", day_order=1, exercises=[grouped])
    ledger.save_training_program(PersistedProgramSchema(program_name="Edit", split_type="Full Body", weekly_frequency=1, days=[day]).model_dump())
    active = ledger.get_active_program()

    rejected = edit_active_program_day(db, ledger, ProgramEdit(day_name="Edit", expected_active_version=active.version,
        exercises=[ProgramEditExercise(0, str(row[0]), 6)], player_account_id=TEST_PLAYER_ID,
        actor=ProgramAnalyticsActor(TEST_PLAYER_ID, "player"), day_order=1))
    assert rejected["code"] == "invalid_set_count"

    lowered = edit_active_program_day(db, ledger, ProgramEdit(day_name="Edit", expected_active_version=active.version,
        exercises=[ProgramEditExercise(0, str(row[0]), 4)], player_account_id=TEST_PLAYER_ID,
        actor=ProgramAnalyticsActor(TEST_PLAYER_ID, "player"), day_order=1))
    assert "code" not in lowered
    saved = ledger.get_active_program().days[0].exercises[0]
    assert [group.sets for group in saved.set_groups] == [2, 2]


def test_program_edit_added_rationale_records_computed_prescription(fresh_store, editable_catalog_rows):
    db = fresh_store
    ledger = db.ledger
    rows = editable_catalog_rows[:2]
    day = PersistedProgramDaySchema(day_name="Edit", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(rows[0][0]), exercise_name=str(rows[0][1]), target_sets=2, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Edit", split_type="Full Body", weekly_frequency=1, days=[day]).model_dump())
    active = ledger.get_active_program()
    edit_active_program_day(db, ledger, ProgramEdit(day_name="Edit", expected_active_version=active.version,
        exercises=[ProgramEditExercise(0, str(rows[0][0]), 2), ProgramEditExercise(-1, str(rows[1][0]), 2)],
        player_account_id=TEST_PLAYER_ID, actor=ProgramAnalyticsActor(TEST_PLAYER_ID, "player"), preview=False))
    added = ledger.get_active_program().program_rationale["days"][0]["exercises"][-1]
    prescription = added["changes"][0]["params"]["prescription"]
    assert {key: reason["code"] for key, reason in prescription.items()} == {
        "sets": "sets.player_edit", "reps": "reps.rep_preference",
        "rir": "rir.experience_level", "rest": "rest.movement_class",
        "warmup": "warmup.template",
    }
    assert prescription["reps"]["params"]["rep_preference"] == "balanced"
    assert prescription["rir"]["params"]["experience_level"] == "beginner"


def test_program_edit_resolves_rationale_day_without_day_order(fresh_store, editable_catalog_rows):
    db = fresh_store
    ledger = db.ledger
    rows = editable_catalog_rows
    first = PersistedProgramDaySchema(day_name="A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(rows[0][0]), exercise_name=str(rows[0][1]), target_sets=2, target_reps_min=8, target_reps_max=12)])
    second = PersistedProgramDaySchema(day_name="B", day_order=2, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(rows[1][0]), exercise_name=str(rows[1][1]), target_sets=2, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Edit", split_type="Full Body", weekly_frequency=2, days=[first, second]).model_dump())
    active = ledger.get_active_program()
    edit_active_program_day(db, ledger, ProgramEdit(day_name="B", expected_active_version=active.version,
        exercises=[ProgramEditExercise(0, str(rows[1][0]), 3), ProgramEditExercise(-1, str(rows[2][0]), 2)],
        player_account_id=TEST_PLAYER_ID, actor=ProgramAnalyticsActor(TEST_PLAYER_ID, "player")))
    rationale_day = next(day for day in ledger.get_active_program().program_rationale["days"] if day["day_order"] == 2)
    changes_by_id = {entry["exercise_id"]: [change["code"] for change in entry.get("changes", [])]
                     for entry in rationale_day["exercises"]}
    assert "change.program_edit_raised" in changes_by_id[str(rows[1][0])]
    assert "change.program_edit_added" in changes_by_id[str(rows[2][0])]


def test_program_edit_warning_uses_unchanged_edited_week(fresh_store, monkeypatch):
    db = fresh_store
    ledger = db.ledger
    rows = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 5").fetchall()
    first_day = PersistedProgramDaySchema(day_name="Full A", day_order=1, week_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(rows[0][0]), exercise_name=str(rows[0][1]), target_sets=2, target_reps_min=8, target_reps_max=12)])
    second_day = PersistedProgramDaySchema(day_name="Full A", day_order=1, week_order=2, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]), target_sets=3, target_reps_min=8, target_reps_max=12)
        for row in rows[1:]])
    ledger.save_training_program(PersistedProgramSchema(program_name="Two-week plan", split_type="Full Body", weekly_frequency=1,
        days=[first_day, second_day], weeks=[
            PersistedProgramWeekSchema(week_name="Base", week_order=1, days=[first_day]),
            PersistedProgramWeekSchema(week_name="Build", week_order=2, days=[second_day]),
        ]).model_dump())
    monkeypatch.setattr(ledger, "volume_review_exercise_targets", lambda ids: {exercise_id: "Biceps" for exercise_id in ids})
    monkeypatch.setattr(
        ledger,
        "volume_review_exercise_credits",
        lambda ids: {
            exercise_id: {
                "biceps": {"credit": 1.0, "is_primary": True, "source": "default"}
            }
            for exercise_id in ids
        },
    )
    active = ledger.get_active_program()

    response = edit_active_program_day(db, ledger, ProgramEdit(day_name="Full A", expected_active_version=active.version,
        exercises=[ProgramEditExercise(index, str(row[0]), 3) for index, row in enumerate(rows[1:])],
        player_account_id=TEST_PLAYER_ID, actor=ProgramAnalyticsActor(TEST_PLAYER_ID, "player"), week_order=2, day_order=1))

    assert response["volume_warnings"] == [{"muscle": "biceps", "weekly_sets": 12, "ceiling": 8}]


def test_program_edit_rejects_more_than_ten_exercises(fresh_store):
    db = fresh_store
    ledger = db.ledger
    rows = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 12").fetchall()
    day = PersistedProgramDaySchema(day_name="Edit", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]), target_sets=2, target_reps_min=8, target_reps_max=12) for row in rows[:1]
    ])
    ledger.save_training_program(PersistedProgramSchema(program_name="Edit", split_type="Full Body", weekly_frequency=1, days=[day]).model_dump())
    active = ledger.get_active_program()
    result = edit_active_program_day(db, ledger, ProgramEdit(day_name="Edit", expected_active_version=active.version,
        exercises=[ProgramEditExercise(-1, str(row[0]), 2) for row in rows[:11]],
        player_account_id=TEST_PLAYER_ID, actor=ProgramAnalyticsActor(TEST_PLAYER_ID, "player"), day_order=1))
    assert result["code"] == "day_limit"
