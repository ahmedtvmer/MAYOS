from datetime import date, datetime, timedelta, timezone

import pytest

from agent.ProgramState import (
    PersistedProgramDaySchema,
    PersistedProgramExerciseSchema,
    PersistedProgramSchema,
    ProgramSetGroupSchema,
)
from service.volume_review import accept_review, dismiss_review, evaluate_review, list_pending, review_facts
from service.workouts import commit_session


def _seed_review(fresh_store, trend: str, *, weekly_frequency: int = 1):
    db = fresh_store
    ledger = db.ledger
    muscle_row = db.catalog_conn.execute(
        "SELECT exercise_id, primary_muscle FROM exercise_curated_fields "
        "WHERE primary_muscle IS NOT NULL ORDER BY exercise_id LIMIT 1"
    ).fetchone()
    exercise_id, muscle = str(muscle_row[0]), str(muscle_row[1])
    exercise_row = db.catalog_conn.execute(
        "SELECT name FROM exercises WHERE id = ?", (exercise_id,)
    ).fetchone()
    now = date.today()
    started = now - timedelta(weeks=5)
    exercise = PersistedProgramExerciseSchema(
        exercise_id=exercise_id,
        exercise_name=str(exercise_row[0]),
        target_sets=5 if trend == "regressing" else 2,
        target_reps_min=8,
        target_reps_max=12,
    )
    day = PersistedProgramDaySchema(day_name="Full A", day_order=1, exercises=[exercise])
    program = PersistedProgramSchema(
        program_name="Review test",
        split_type="Full Body",
        weekly_frequency=weekly_frequency,
        days=[day],
        created_at=started.isoformat(),
    )
    ledger.save_training_program(program.model_dump())
    active = ledger.get_active_program()
    active.created_at = program.created_at
    values = {
        "progressing": [(40, 8), (42, 8), (46, 8), (50, 8)],
        "stalled": [(40, 8)] * 4,
        "regressing": [(50, 8), (48, 8), (44, 8), (40, 8)],
    }[trend]
    for index, (weight, reps) in enumerate(values):
        session_date = started + timedelta(days=7 * index + 1)
        session_id = f"review-{trend}-{index}"
        stamp = datetime.combine(session_date, datetime.min.time(), tzinfo=timezone.utc).isoformat()
        ledger.log_workout_session(
            session_id,
            session_date.isoformat(),
            "Full A",
            stamp,
            stamp,
            readiness_score=1 if trend == "regressing" else 4,
            program_version=active.version,
        )
        # The exaggerated warm-up must never affect the progression assessment.
        ledger.log_workout_set(f"warm-{index}", session_id, exercise_id, 0, 200, 10, 10, 1)
        ledger.log_workout_set(f"work-{index}", session_id, exercise_id, 1, weight, reps, 8, 0)
    return ledger, active, {"training_age_years": 3, "weekly_frequency": weekly_frequency}, now, muscle


def test_volume_review_counts_sets_across_groups(fresh_store):
    ledger, program, profile, today, muscle = _seed_review(fresh_store, "progressing")
    exercise = program.days[0].exercises[0]
    exercise.set_groups = [
        ProgramSetGroupSchema(sets=3, reps_min=8, reps_max=12, target_rir=2),
        ProgramSetGroupSchema(sets=2, reps_min=10, reps_max=12, target_rir=1),
    ]

    result = review_facts(ledger, program, profile, today)

    row = next(item for item in result["muscles"] if item["muscle"] == muscle)
    assert row["weekly_sets"] == 5


def test_grouped_volume_reduction_keeps_backoffs_and_places_remaining_cut(fresh_store):
    db = fresh_store
    ledger, program, profile, today, muscle = _seed_review(db, "regressing")
    grouped = program.days[0].exercises[0]
    grouped.set_groups = [
        ProgramSetGroupSchema(sets=1, reps_min=5, reps_max=5, target_rir=1),
        ProgramSetGroupSchema(sets=3, reps_min=8, reps_max=8, target_rir=2),
    ]
    second_id, second_name = db.catalog_conn.execute(
        "SELECT e.id, e.name FROM exercise_curated_fields f "
        "JOIN exercises e ON e.id = f.exercise_id "
        "WHERE f.primary_muscle = ? AND e.id != ? ORDER BY e.id LIMIT 1",
        (muscle, grouped.exercise_id),
    ).fetchone()
    simple = PersistedProgramExerciseSchema(
        exercise_id=str(second_id), exercise_name=str(second_name), target_sets=3,
        target_reps_min=8, target_reps_max=8,
    )
    program.days[0].exercises = [simple, grouped]

    result = review_facts(ledger, program, profile, today)

    row = next(item for item in result["muscles"] if item["muscle"] == muscle)
    assert row["set_delta"] == -2
    assert row["edits"] == [{
        "week_order": 1, "day_order": 1, "day_name": "Full A",
        "exercise_id": str(second_id), "target_sets": 1,
    }]


@pytest.mark.parametrize(
    ("trend", "frequency", "verdict", "delta"),
    [
        ("progressing", 1, "progressing", 0),
        ("stalled", 1, "stalled", 1),
        ("regressing", 1, "under_recovered", -1),
        ("stalled", 2, "low_adherence", 0),
    ],
)
def test_seeded_working_set_histories_produce_volume_verdicts(
    fresh_store, trend, frequency, verdict, delta
):
    ledger, program, profile, today, muscle = _seed_review(
        fresh_store, trend, weekly_frequency=frequency
    )
    result = review_facts(ledger, program, profile, today)
    assert result["eligible"] is True
    assert result["muscles"], result
    row = next(item for item in result["muscles"] if item["muscle"] == muscle)
    assert row["verdict"] == verdict
    assert row["set_delta"] == delta
    if verdict == "low_adherence":
        assert "Consistency comes first" in row["reason"]
    if delta < 0:
        assert row["weekly_sets"] + delta >= 4


def test_beginner_ceiling_caps_stalled_volume(fresh_store):
    ledger, program, profile, today, muscle = _seed_review(fresh_store, "stalled")
    profile["training_age_years"] = 1
    program.days[0].exercises[0].set_groups[0].sets = 9
    result = review_facts(ledger, program, profile, today)
    row = next((item for item in result["muscles"] if item["muscle"] == muscle), None)
    assert row is None or row["set_delta"] == 0


@pytest.mark.parametrize(
    ("trend", "sets", "verdict"),
    [("stalled", 8, "at_ceiling"), ("regressing", 4, "at_floor")],
)
def test_volume_limits_have_distinct_no_change_verdicts(fresh_store, trend, sets, verdict):
    ledger, program, profile, today, muscle = _seed_review(fresh_store, trend)
    program.days[0].exercises[0].set_groups[0].sets = sets
    if trend == "stalled":
        profile["training_age_years"] = 1

    result = review_facts(ledger, program, profile, today)

    row = next(item for item in result["muscles"] if item["muscle"] == muscle)
    assert row["verdict"] == verdict
    assert row["set_delta"] == 0
    assert row["edits"] == []


def test_beginner_ceiling_allows_only_the_last_set_up_to_eight(fresh_store):
    db = fresh_store
    ledger, program, profile, today, muscle = _seed_review(db, "stalled")
    other_id, other_name = db.catalog_conn.execute(
        "SELECT e.id, e.name FROM exercise_curated_fields f "
        "JOIN exercises e ON e.id = f.exercise_id "
        "WHERE f.primary_muscle = ? AND e.id != ? ORDER BY e.id LIMIT 1",
        (muscle, program.days[0].exercises[0].exercise_id),
    ).fetchone()
    program.days[0].exercises[0].set_groups[0].sets = 2
    program.days.append(PersistedProgramDaySchema(
        day_name="Full B", day_order=2,
        exercises=[PersistedProgramExerciseSchema(
            exercise_id=str(other_id), exercise_name=str(other_name), target_sets=5,
            target_reps_min=8, target_reps_max=12,
        )],
    ))
    profile["training_age_years"] = 1
    result = review_facts(ledger, program, profile, today)
    row = next(item for item in result["muscles"] if item["muscle"] == muscle)
    assert row["weekly_sets"] == 7
    assert row["set_delta"] == 1
    assert row["weekly_sets"] + row["set_delta"] == 8


def test_multiweek_review_counts_and_edits_only_current_week(fresh_store):
    ledger, program, profile, today, muscle = _seed_review(fresh_store, "regressing")
    program_data = program.model_dump()
    first_day = program_data["days"][0]
    third_day = {**first_day, "week_order": 2, "day_name": "Week 2 A"}
    program_data["weeks"] = [
        {"week_name": "Week 1", "week_order": 1, "days": [first_day]},
        {"week_name": "Week 2", "week_order": 2, "days": [third_day]},
    ]
    ledger.save_training_program(program_data)
    active = ledger.get_active_program()
    active.created_at = program.created_at
    for index in range(4):
        session_date = date.fromisoformat(program.created_at[:10]) + timedelta(days=7 * index + 1)
        stamp = datetime.combine(session_date, datetime.min.time(), tzinfo=timezone.utc).isoformat()
        session_id = f"multiweek-{index}"
        ledger.log_workout_session(
            session_id, session_date.isoformat(), "Full A", stamp, stamp,
            program_version=active.version,
        )
        ledger.log_workout_set(
            f"multiweek-set-{index}", session_id,
            str(program.days[0].exercises[0].exercise_id), 1,
            [50, 48, 44, 40][index], 8, 8, 0,
        )
    result = review_facts(ledger, active, profile, today)
    assert result["muscles"], result
    row = next(item for item in result["muscles"] if item["muscle"] == muscle)
    assert row["weekly_sets"] == 5
    assert {edit["week_order"] for edit in row["edits"]} == {1}


@pytest.mark.parametrize("slot_key", ["flat_press", None])
def test_placement_adds_existing_set_before_second_staple(fresh_store, slot_key):
    db = fresh_store
    ledger = db.ledger
    staple_id, second_id = "576", "25"
    target = db.catalog_conn.execute(
        "SELECT a.primary_muscle, e.name FROM exercise_curated_fields a "
        "JOIN exercises e ON e.id = a.exercise_id WHERE a.exercise_id = ?",
        (staple_id,),
    ).fetchone()
    next_target = db.catalog_conn.execute(
        "SELECT primary_muscle FROM exercise_curated_fields WHERE exercise_id = ?",
        (second_id,),
    ).fetchone()
    assert target is not None
    assert next_target is not None
    assert target[0] == next_target[0]
    unrelated = db.catalog_conn.execute(
        "SELECT id, name FROM exercises WHERE id NOT IN (?, ?) ORDER BY id LIMIT 1",
        (staple_id, second_id),
    ).fetchone()
    now = date.today()
    started = now - timedelta(weeks=5)
    primary = PersistedProgramExerciseSchema(
        exercise_id=staple_id,
        exercise_name=str(target[1]),
        target_sets=2,
        target_reps_min=8,
        target_reps_max=12,
        slot_key=slot_key,
    )
    other = PersistedProgramExerciseSchema(
        exercise_id=str(unrelated[0]),
        exercise_name=str(unrelated[1]),
        target_sets=1,
        target_reps_min=8,
        target_reps_max=12,
    )
    days = [
        PersistedProgramDaySchema(day_name="Press", day_order=1, exercises=[primary]),
        PersistedProgramDaySchema(day_name="Other", day_order=2, exercises=[other]),
    ]
    program = PersistedProgramSchema(
        program_name="Placement test",
        split_type="Full Body",
        weekly_frequency=2,
        days=days,
        created_at=started.isoformat(),
    )
    ledger.save_training_program(program.model_dump())
    active = ledger.get_active_program()
    active.created_at = program.created_at
    for index in range(8):
        session_date = started + timedelta(days=4 * index + 1)
        session_id = f"placement-{index}"
        stamp = datetime.combine(session_date, datetime.min.time(), tzinfo=timezone.utc).isoformat()
        ledger.log_workout_session(
            session_id,
            session_date.isoformat(),
            "Press",
            stamp,
            stamp,
            program_version=active.version,
        )
        ledger.log_workout_set(
            f"placement-set-{index}", session_id, staple_id, 1, 40, 8, 8, 0
        )
    facts = review_facts(
        ledger,
        active,
        {"training_age_years": 3, "weekly_frequency": 2},
        now,
    )
    chest = next(item for item in facts["muscles"] if item["muscle"] == target[0])
    assert chest["edits"][0]["target_sets"] == 3
    assert chest["edits"][1]["add_exercise"]["exercise_id"] == second_id
    assert chest["edits"][1]["day_order"] == 2


def test_removals_start_with_last_exercise_and_keep_four_weekly_sets(fresh_store):
    db = fresh_store
    ledger = db.ledger
    first_id, second_id = "576", "25"
    rows = db.catalog_conn.execute(
        "SELECT e.id, e.name, f.primary_muscle FROM exercises e "
        "JOIN exercise_curated_fields f ON f.exercise_id = e.id WHERE e.id IN (?, ?)",
        (first_id, second_id),
    ).fetchall()
    assert len(rows) == 2 and rows[0][2] == rows[1][2]
    by_id = {str(row[0]): str(row[1]) for row in rows}
    started = date.today() - timedelta(weeks=5)
    days = [
        PersistedProgramDaySchema(
            day_name=f"Day {index}", day_order=index,
            exercises=[PersistedProgramExerciseSchema(
                exercise_id=exercise_id, exercise_name=by_id[exercise_id], target_sets=sets,
                target_reps_min=8, target_reps_max=12,
            )],
        )
        for index, exercise_id, sets in [(1, first_id, 3), (2, second_id, 2)]
    ]
    program = PersistedProgramSchema(
        program_name="Removal order", split_type="Full Body", weekly_frequency=2,
        days=days, created_at=started.isoformat(),
    )
    ledger.save_training_program(program.model_dump())
    active = ledger.get_active_program()
    active.created_at = program.created_at
    days = (1, 3, 5, 8, 27, 29, 31, 34)
    weights = (50, 50, 50, 50, 40, 40, 40, 40)
    for index, (session_day, weight) in enumerate(zip(days, weights)):
        session_date = started + timedelta(days=session_day)
        stamp = datetime.combine(session_date, datetime.min.time(), tzinfo=timezone.utc).isoformat()
        session_id = f"removal-{index}"
        ledger.log_workout_session(session_id, session_date.isoformat(), "Day 1", stamp, stamp, program_version=active.version)
        ledger.log_workout_set(f"removal-set-{index}", session_id, first_id, 1, weight, 8, 8, 0)
    result = review_facts(ledger, active, {"training_age_years": 3}, date.today())
    chest = next(item for item in result["muscles"] if item["muscle"] == rows[0][2])
    assert chest["set_delta"] == -1
    assert chest["edits"][0]["exercise_id"] == second_id
    assert chest["edits"][0]["target_sets"] == 1
    assert chest["weekly_sets"] + chest["set_delta"] == 4


def test_trend_waits_when_exercises_do_not_overlap_between_halves(fresh_store):
    db = fresh_store
    ledger = db.ledger
    first_id, second_id = "576", "25"
    rows = db.catalog_conn.execute(
        "SELECT e.id, e.name, f.primary_muscle FROM exercises e "
        "JOIN exercise_curated_fields f ON f.exercise_id = e.id WHERE e.id IN (?, ?)",
        (first_id, second_id),
    ).fetchall()
    by_id = {str(row[0]): str(row[1]) for row in rows}
    started = date.today() - timedelta(weeks=5)
    exercises = [
        PersistedProgramExerciseSchema(
            exercise_id=exercise_id, exercise_name=by_id[exercise_id], target_sets=2,
            target_reps_min=8, target_reps_max=12,
        )
        for exercise_id in (first_id, second_id)
    ]
    program = PersistedProgramSchema(
        program_name="Exercise trend", split_type="Full Body", weekly_frequency=1,
        days=[PersistedProgramDaySchema(day_name="Full A", day_order=1, exercises=exercises)],
        created_at=started.isoformat(),
    )
    ledger.save_training_program(program.model_dump())
    active = ledger.get_active_program()
    active.created_at = program.created_at
    for index, (session_day, exercise_id) in enumerate(zip((1, 8, 29, 34), (first_id, first_id, second_id, second_id))):
        session_date = started + timedelta(days=session_day)
        stamp = datetime.combine(session_date, datetime.min.time(), tzinfo=timezone.utc).isoformat()
        session_id = f"split-trend-{index}"
        ledger.log_workout_session(session_id, session_date.isoformat(), "Full A", stamp, stamp, program_version=active.version)
        ledger.log_workout_set(f"split-trend-set-{index}", session_id, exercise_id, 1, 40, 8, 8, 0)
    result = review_facts(ledger, active, {"weekly_frequency": 1}, date.today())
    assert result["eligible"] is False
    assert result["muscles"] == []


def test_insufficient_exposure_waits_a_week(fresh_store):
    db = fresh_store
    ledger = db.ledger
    exercise_id = str(db.catalog_conn.execute("SELECT id FROM exercises ORDER BY id LIMIT 1").fetchone()[0])
    exercise = PersistedProgramExerciseSchema(
        exercise_id=exercise_id,
        exercise_name="Test",
        target_sets=2,
        target_reps_min=8,
        target_reps_max=12,
    )
    day = PersistedProgramDaySchema(day_name="Full A", day_order=1, exercises=[exercise])
    program = PersistedProgramSchema(
        program_name="New", split_type="Full Body", weekly_frequency=3,
        days=[day], created_at=(date.today() - timedelta(weeks=5)).isoformat(),
    )
    ledger.save_training_program(program.model_dump())
    active = ledger.get_active_program()
    active.created_at = program.created_at
    started = date.fromisoformat(program.created_at)
    for index in range(3):
        session_date = started + timedelta(days=7 * index + 1)
        stamp = datetime.combine(session_date, datetime.min.time(), tzinfo=timezone.utc).isoformat()
        ledger.log_workout_session(
            f"few-exposures-{index}", session_date.isoformat(), "Full A", stamp, stamp,
            program_version=active.version,
        )
        ledger.log_workout_set(
            f"few-exposures-set-{index}", f"few-exposures-{index}", exercise_id, 1, 40, 8, 8, 0,
        )

    result = review_facts(ledger, active, {"weekly_frequency": 3}, date.today())
    assert result["eligible"] is False
    assert result["next_eligible_date"] == (date.today() + timedelta(weeks=1)).isoformat()
    assert evaluate_review(ledger, active, {"weekly_frequency": 3}, date.today()) is None
    assert evaluate_review(ledger, active, {"weekly_frequency": 3}, date.today() + timedelta(days=3)) is None


@pytest.mark.parametrize("signal", ["low_readiness", "overshoot"])
def test_flat_performance_with_recovery_strain_reduces_volume(fresh_store, signal):
    ledger, program, profile, today, muscle = _seed_review(fresh_store, "stalled")
    program.days[0].exercises[0].set_groups[0].sets = 5
    if signal == "low_readiness":
        ledger.conn.execute("UPDATE workout_sessions SET readiness_score = 1")
    else:
        ledger.conn.execute("UPDATE workout_sets SET rpe = 9.8 WHERE is_warmup = 0")
    result = review_facts(ledger, program, profile, today)
    row = next(item for item in result["muscles"] if item["muscle"] == muscle)
    assert row["verdict"] == "under_recovered"
    assert row["set_delta"] < 0
    assert row["weekly_sets"] + row["set_delta"] >= 4
    assert row["edits"][0]["target_sets"] == 4


def test_bodyweight_progression_uses_reps_at_zero_load(fresh_store):
    ledger, program, profile, today, muscle = _seed_review(fresh_store, "progressing")
    for index in range(4):
        ledger.conn.execute(
            "UPDATE workout_sets SET weight_kg = 0, reps = ? WHERE id = ?",
            (8 + index, f"work-{index}"),
        )
    result = review_facts(ledger, program, profile, today)
    row = next(item for item in result["muscles"] if item["muscle"] == muscle)
    assert row["verdict"] == "progressing"


def test_program_frequency_controls_adherence_denominator(fresh_store):
    ledger, program, profile, today, muscle = _seed_review(fresh_store, "stalled")
    profile["weekly_frequency"] = 3
    result = review_facts(ledger, program, profile, today)
    row = next(item for item in result["muscles"] if item["muscle"] == muscle)
    assert row["verdict"] == "stalled"


def test_informational_review_has_no_program_change_to_accept(fresh_store):
    ledger, program, profile, today, _ = _seed_review(fresh_store, "progressing")
    review = evaluate_review(ledger, program, profile, today)
    assert review is not None
    assert review["status"] == "informational"
    assert evaluate_review(ledger, program, profile, today + timedelta(days=1)) is None
    with pytest.raises(ValueError, match="review_not_pending"):
        accept_review(fresh_store, ledger, "player-one", review["review_id"])
    assert ledger.get_active_program().version == program.version


def test_only_latest_informational_review_is_listed_for_a_program_version(fresh_store):
    ledger, program, profile, today, _ = _seed_review(fresh_store, "progressing")
    first = evaluate_review(ledger, program, profile, today)
    second = evaluate_review(ledger, program, profile, today + timedelta(days=7))

    assert first is not None and first["status"] == "informational"
    assert second is not None and second["status"] == "informational"
    listed = list_pending(ledger, int(program.version))
    assert [review["review_id"] for review in listed] == [second["review_id"]]


def test_pending_review_blocks_another_review_for_same_version(fresh_store):
    ledger, program, profile, today, _ = _seed_review(fresh_store, "stalled")
    review = evaluate_review(ledger, program, profile, today)
    assert review is not None and review["status"] == "pending"
    assert evaluate_review(ledger, program, profile, today + timedelta(days=1)) is None


def test_workout_commit_triggers_volume_review(fresh_store):
    ledger, program, _, today, _ = _seed_review(fresh_store, "stalled")
    exercise = program.days[0].exercises[0]
    outcome = commit_session(
        fresh_store,
        "player-one",
        program.days[0],
        readiness=4,
        session_notes="",
        sets_by_exercise=[{
            "exercise": exercise,
            "sets": [{"weight_kg": 40, "reps": 8, "rpe": 8}],
            "previous_perf": [],
        }],
        today_date=today.isoformat(),
        now_iso=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).isoformat(),
        ledger=ledger,
    )
    reviews = list_pending(ledger, int(program.version))
    assert outcome.created is True
    assert reviews and reviews[0]["status"] == "pending"


def test_accept_creates_a_new_version_and_resets_the_window(fresh_store):
    ledger, program, profile, today, _ = _seed_review(fresh_store, "stalled")
    review = evaluate_review(ledger, program, profile, today)
    assert review is not None
    replay = evaluate_review(ledger, program, profile, today)
    assert replay["review_id"] == review["review_id"]
    assert ledger.get_active_program().version == program.version
    accepted = accept_review(fresh_store, ledger, "player-one", review["review_id"])
    updated = ledger.get_active_program()
    assert accepted["status"] == "accepted"
    assert updated.version == program.version + 1
    assert updated.created_at[:10] == today.isoformat()
    assert updated.days[0].exercises[0].target_sets == 3

    after_change = review_facts(ledger, updated, profile, today + timedelta(days=14))
    assert after_change["eligible"] is False
    assert after_change["next_eligible_date"] == (today + timedelta(days=21)).isoformat()


def test_dismiss_records_choice(fresh_store):
    ledger, program, profile, today, _ = _seed_review(fresh_store, "stalled")
    review = evaluate_review(ledger, program, profile, today)
    assert review is not None
    dismissed = dismiss_review(fresh_store, ledger, "player-one", review["review_id"])
    assert dismissed["status"] == "dismissed"


def test_stale_volume_review_is_refused(fresh_store):
    ledger, program, profile, today, _ = _seed_review(fresh_store, "stalled")
    review = evaluate_review(ledger, program, profile, today)
    assert review is not None
    ledger.save_training_program(program.model_dump())
    with pytest.raises(ValueError, match="program_changed"):
        accept_review(fresh_store, ledger, "player-one", review["review_id"])
