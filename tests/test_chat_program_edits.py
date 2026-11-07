from datetime import UTC, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from agent.ProgramState import PersistedProgramDaySchema, PersistedProgramExerciseSchema, PersistedProgramSchema
from service.program_analytics import ProgramAnalyticsActor
from service.program_edit import ProgramEdit, ProgramEditExercise, edit_active_program_days
from service.chat_program_edit import plan_chat_program_edit, resolve_chat_program_edit
from langchain_core.messages import AIMessage, HumanMessage
from agent.assistant_graph import stream_assistant_turn


def test_pending_chat_program_edit_round_trips_offer_and_expires(fresh_store):
    ledger = fresh_store.ledger
    proposal = {
        "expected_version": 3,
        "days": [{"day_name": "Leg A", "exercises": [{"exercise_id": "e1", "target_sets": 2}]}],
        "optional": ["forearms"],
    }

    ledger.set_pending_chat_program_edit(proposal, "Preview text")
    pending = ledger.get_pending_chat_program_edit()

    assert pending["proposal"] == proposal
    assert pending["offer_text"] == "Preview text"
    ledger.conn.execute(
        "UPDATE assistant_goal_weak_point_pending SET created_at = ? WHERE id = 1",
        ((datetime.now(UTC) - timedelta(minutes=31)).isoformat(),),
    )
    ledger._commit_ledger()
    assert ledger.get_pending_chat_program_edit() is None

    ledger.set_pending_chat_program_edit(proposal, "Preview text")
    ledger.clear_chat_history()
    assert ledger.get_pending_chat_program_edit() is None


def test_chat_edit_preview_and_multi_day_confirmation_create_one_version(fresh_store, editable_catalog_rows):
    db = fresh_store
    ledger = db.ledger
    rows = editable_catalog_rows
    ids = [str(row[0]) for row in rows]
    days = [
        PersistedProgramDaySchema(day_name=f"Leg {index}", day_order=index,
            exercises=[PersistedProgramExerciseSchema(exercise_id=ids[index - 1],
                exercise_name=str(rows[index - 1][1]), target_sets=3,
                target_reps_min=8, target_reps_max=12)])
        for index in (1, 2)
    ]
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=2, days=days).model_dump())
    active = ledger.get_active_program()
    actor = ProgramAnalyticsActor("00000000-0000-4000-8000-000000000001", "player")
    edits = [
        ProgramEdit(day_name=f"Leg {index}", expected_active_version=active.version,
            exercises=[ProgramEditExercise(0, ids[index - 1], 3),
                       ProgramEditExercise(-1, ids[2], 2)],
            player_account_id="00000000-0000-4000-8000-000000000001", actor=actor, day_order=index,
            preview=True, via="chat")
        for index in (1, 2)
    ]
    preview = edit_active_program_days(db, ledger, edits)
    assert ledger.get_active_program().version == active.version
    assert len(preview["days"]) == 2
    with patch("service.program_edit.capture_program_edited"):
        committed = edit_active_program_days(db, ledger, [
            ProgramEdit(**{**edit.__dict__, "preview": False}) for edit in edits
        ])

    assert committed["version"] == active.version + 1
    rationale = ledger.get_active_program().program_rationale["days"]
    additions = [entry for day in rationale for entry in day.get("exercises", [])
                 if any(change.get("code") == "change.program_edit_added"
                        for change in entry.get("changes", []))]
    assert len(additions) == 2
    assert all(addition["changes"][0]["params"]["via"] == "chat" for addition in additions)


def test_muscle_selection_is_deterministic_and_forearms_stay_optional(fresh_store):
    db = fresh_store
    ledger = db.ledger
    rows = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 2").fetchall()
    base = [PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]),
        target_sets=3, target_reps_min=8, target_reps_max=12) for row in rows]
    days = [PersistedProgramDaySchema(day_name=f"Leg {name}", day_order=order, exercises=[base[order - 1]])
            for order, name in enumerate(("A", "B"), 1)]
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=2, days=days).model_dump())
    query = "rebuild my program and augment leg days with bi, tri and side delt, maybe forearms"

    first = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001", query)
    second = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001", query)

    assert "proposal" in first, first
    assert first["proposal"]["optional"][0]["muscle"] == "forearms"
    assert first["proposal"]["days"] == second["proposal"]["days"]
    assert all(len(day["exercises"]) == 4 for day in first["proposal"]["days"])


def test_cancelled_chat_edit_leaves_program_unchanged(fresh_store):
    db = fresh_store
    ledger = db.ledger
    row = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 1").fetchone()
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]),
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())
    active = ledger.get_active_program()
    proposal = {"expected_version": active.version, "days": [], "optional": []}
    preview_id = ledger.set_pending_chat_program_edit(proposal, "offer")

    cancelled = resolve_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        preview_id, confirm=False)
    assert cancelled["cancelled"] is True
    assert ledger.get_active_program().version == active.version


def test_stale_chat_edit_is_rejected_without_changing_program(fresh_store):
    db = fresh_store
    ledger = db.ledger
    row = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 1").fetchone()
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]),
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())
    active = ledger.get_active_program()
    proposal = {"expected_version": active.version, "days": [], "optional": []}
    preview_id = ledger.set_pending_chat_program_edit(proposal, "offer")
    ledger.save_training_program(ledger.get_active_program().model_dump())
    stale = resolve_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        preview_id, confirm=True)
    assert stale["error"] == "program_changed"
    assert ledger.get_pending_chat_program_edit() is None


def test_compound_on_opposite_region_returns_short_refusal(fresh_store):
    db = fresh_store
    ledger = db.ledger
    row = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 1").fetchone()
    day = PersistedProgramDaySchema(day_name="Upper A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]),
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Upper Lower",
        weekly_frequency=1, days=[day]).model_dump())

    result = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        "put barbell squat on upper day")

    assert result["error"] == "opposite_region_compound"
    assert "compound" in result["message"].casefold()


def test_opposite_region_checks_equipment_filtered_selected_exercise(fresh_store):
    db = fresh_store
    ledger = db.ledger
    squat = db.find_exercises_by_name("barbell squat", limit=1)[0]
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(squat["id"]), exercise_name=squat["name"],
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())
    ledger.upsert_player_profile({"equipment_access": "Commercial gym"})

    result = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        "add shoulder to leg days")

    assert result["error"] == "opposite_region_compound"


def test_named_exercise_addition_builds_program_edit_preview(fresh_store):
    db = fresh_store
    ledger = db.ledger
    squat = db.catalog_conn.execute(
        "SELECT id, name FROM exercises WHERE LOWER(name) LIKE '%squat%' ORDER BY id LIMIT 1"
    ).fetchone()
    extension = db.find_exercises_by_name("leg extension", limit=10)[0]
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(squat[0]), exercise_name=str(squat[1]),
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())

    planned = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        "add leg extension to leg days")

    assert "proposal" in planned, planned
    assert any(item["exercise_id"] == str(extension["id"]) and item["target_sets"] == 2
               for item in planned["proposal"]["days"][0]["exercises"]), planned


def test_named_exercise_removal_builds_program_edit_preview(fresh_store):
    db = fresh_store
    ledger = db.ledger
    squat = db.find_exercises_by_name("barbell squat", limit=10)[0]
    bench = db.find_exercises_by_name("bench press", limit=10)[0]
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(squat["id"]), exercise_name=squat["name"],
            target_sets=3, target_reps_min=8, target_reps_max=12),
        PersistedProgramExerciseSchema(exercise_id=str(bench["id"]), exercise_name=bench["name"],
            target_sets=3, target_reps_min=8, target_reps_max=12),
    ])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())

    planned = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        "remove barbell squat from leg days")

    assert "proposal" in planned, planned
    exercises = planned["proposal"]["days"][0]["exercises"]
    assert all(item["exercise_id"] != str(squat["id"]) for item in exercises)
    assert any(item["exercise_id"] == str(bench["id"]) for item in exercises)


def test_named_exercise_set_change_builds_program_edit_preview(fresh_store):
    db = fresh_store
    ledger = db.ledger
    squat = db.find_exercises_by_name("barbell squat", limit=10)[0]
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(squat["id"]), exercise_name=squat["name"],
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())

    planned = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        "change barbell squat to 4 sets on leg days")

    assert "proposal" in planned, planned
    assert planned["proposal"]["days"][0]["exercises"] == [
        {"source_index": 0, "exercise_id": str(squat["id"]), "target_sets": 4}
    ]


def test_muscle_removal_and_set_change_edit_existing_items(fresh_store):
    db = fresh_store
    ledger = db.ledger
    curl = db.find_exercises_by_name("biceps curl", limit=1)[0]
    squat = db.find_exercises_by_name("barbell squat", limit=1)[0]
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(curl["id"]), exercise_name=curl["name"],
            target_sets=2, target_reps_min=8, target_reps_max=12),
        PersistedProgramExerciseSchema(exercise_id=str(squat["id"]), exercise_name=squat["name"],
            target_sets=2, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())

    removed = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        "remove biceps from leg days")
    changed = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        "change biceps to 4 sets on leg days")

    assert "proposal" in removed, removed
    assert len(removed["proposal"]["days"][0]["exercises"]) == 1
    assert removed["proposal"]["days"][0]["exercises"][0]["exercise_id"] == str(squat["id"])
    assert "proposal" in changed, changed
    assert changed["proposal"]["days"][0]["exercises"][0]["target_sets"] == 4


def test_missing_removal_does_not_create_preview(fresh_store):
    db = fresh_store
    ledger = db.ledger
    squat = db.find_exercises_by_name("barbell squat", limit=1)[0]
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(squat["id"]), exercise_name=squat["name"],
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())
    before = ledger.get_active_program().version

    result = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        "remove leg extension from leg days")

    assert result["error"] == "exercise_not_on_day"
    assert ledger.get_active_program().version == before


def test_composite_keeps_program_preview_bound_to_combined_reply(fresh_store, monkeypatch):
    from agent.assistant_graph import composite_intent_node
    from tests.fakes.chat_model import ScriptedChatModel

    db = fresh_store
    ledger = db.ledger
    squat = db.find_exercises_by_name("barbell squat", limit=1)[0]
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(squat["id"]), exercise_name=squat["name"],
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())
    monkeypatch.setattr("agent.assistant_graph.llm", ScriptedChatModel([
        "Progress by adding a rep when you can."
    ]))
    state = {"messages": [HumanMessage(content="Add biceps to leg days and how should I progress?")],
        "player_account_id": "00000000-0000-4000-8000-000000000001", "display_language": "en",
        "intent_metadata": {"raw_query": "Add biceps to leg days and how should I progress?",
            "sub_intents": [
                {"intent": "program_edit", "query": "Add biceps to leg days"},
                {"intent": "program_edit", "query": "add triceps to leg days"},
                {"intent": "coaching_qa", "query": "how should I progress?"},
            ]}}

    result = composite_intent_node(state, {"configurable": {"ledger": ledger, "store": db}})

    assert result.get("program_edit_preview")
    assert len(result["program_edit_preview"]["days"][0]["exercises"]) == 3
    pending = ledger.get_pending_chat_program_edit()
    assert pending["offer_text"] == result["response_content"]


def test_batch_noop_does_not_publish_a_version(fresh_store):
    db = fresh_store
    ledger = db.ledger
    squat = db.find_exercises_by_name("barbell squat", limit=1)[0]
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(squat["id"]), exercise_name=squat["name"],
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())
    active = ledger.get_active_program()
    edit = ProgramEdit(day_name="Leg A", expected_active_version=active.version,
        exercises=[ProgramEditExercise(0, str(squat["id"]), 3)],
        player_account_id="00000000-0000-4000-8000-000000000001",
        actor=ProgramAnalyticsActor("00000000-0000-4000-8000-000000000001", "player"),
        week_order=1, day_order=1, preview=False, via="chat")

    result = edit_active_program_days(db, ledger, [edit])

    assert result["version"] == active.version
    assert ledger.get_active_program().version == active.version


def test_concurrent_confirmations_publish_exactly_one_version(fresh_store):
    db = fresh_store
    ledger = db.ledger
    squat = db.find_exercises_by_name("barbell squat", limit=1)[0]
    curl = db.find_exercises_by_name("barbell curl", limit=1)[0]
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(squat["id"]), exercise_name=squat["name"],
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())
    active = ledger.get_active_program()
    proposal = {"expected_version": active.version, "days": [{"day_name": "Leg A",
        "day_order": 1, "week_order": 1, "exercises": [
            {"source_index": 0, "exercise_id": str(squat["id"]), "target_sets": 3},
            {"source_index": -1, "exercise_id": str(curl["id"]), "target_sets": 2}]}],
        "optional": []}
    preview_id = ledger.set_pending_chat_program_edit(proposal, "offer")
    account_id = "00000000-0000-4000-8000-000000000001"
    handles = [db.open_ledger(ledger.ledger_id), db.open_ledger(ledger.ledger_id)]

    def confirm(handle):
        try:
            return resolve_chat_program_edit(db, handle, account_id, preview_id, confirm=True)
        finally:
            handle.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, handles))

    assert sum("error" not in result for result in results) == 1
    with db.open_ledger(ledger.ledger_id) as verification_ledger:
        assert verification_ledger.get_active_program().version == active.version + 1


def test_chat_history_restores_only_the_live_program_edit_preview(fresh_store):
    from service.chat import get_history

    db = fresh_store
    ledger = db.ledger
    squat = db.find_exercises_by_name("barbell squat", limit=1)[0]
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(squat["id"]), exercise_name=squat["name"],
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())
    offer = "Program edit preview. Confirm or cancel."
    proposal = {"expected_version": ledger.get_active_program().version, "days": [],
        "preview_days": [{"day_name": "Leg A", "week_order": 1, "exercises": []}],
        "warnings": [], "optional": []}
    preview_id = ledger.set_pending_chat_program_edit(proposal, offer)
    ledger.add_chat_message("assistant", offer)

    history = get_history(db, ledger.ledger_id, ledger)

    assert history[-1]["program_edit_preview"]["id"] == preview_id
    ledger.clear_pending_chat_program_edit()
    assert "program_edit_preview" not in get_history(db, ledger.ledger_id, ledger)[-1]


def test_preview_uses_week_and_day_identity_and_group_prescriptions(fresh_store):
    from agent.ProgramState import PersistedProgramWeekSchema

    db = fresh_store
    ledger = db.ledger
    squat = db.find_exercises_by_name("barbell squat", limit=1)[0]
    bench = db.find_exercises_by_name("bench press", limit=1)[0]
    first = PersistedProgramDaySchema(day_name="Leg A", day_order=1, week_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(squat["id"]), exercise_name=squat["name"],
            target_sets=4, target_reps_min=8, target_reps_max=12,
            set_groups=[{"sets": 2, "reps_min": 8, "reps_max": 12, "target_rir": 2},
                {"sets": 2, "reps_min": 12, "reps_max": 15, "target_rir": 3}])])
    second = PersistedProgramDaySchema(day_name="Leg A", day_order=1, week_order=2, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(bench["id"]), exercise_name=bench["name"],
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[first, second], weeks=[
            PersistedProgramWeekSchema(week_name="Week 1", week_order=1, days=[first]),
            PersistedProgramWeekSchema(week_name="Week 2", week_order=2, days=[second]),
        ]).model_dump())

    planned = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        "add biceps to leg days")

    assert "proposal" in planned, planned
    preview = planned["proposal"]["preview_days"][0]
    assert preview["week_order"] == 1
    assert preview["exercises"][0]["name"] == squat["name"]
    assert preview["exercises"][0]["sets"] == 4
    assert preview["exercises"][0]["set_groups"] == [
        {"sets": 2, "reps_min": 8, "reps_max": 12, "rir": 2.0,
         "load": None, "amrap_last_set": False},
        {"sets": 2, "reps_min": 12, "reps_max": 15, "rir": 3.0,
         "load": None, "amrap_last_set": False},
    ]


def test_move_respects_named_source_occurrence(fresh_store):
    db = fresh_store
    ledger = db.ledger
    raises = db.catalog_conn.execute(
        "SELECT id, name FROM exercises WHERE LOWER(name) LIKE '%lateral raise%' ORDER BY id LIMIT 2"
    ).fetchall()
    bench = db.find_exercises_by_name("bench press", limit=1)[0]
    squat = db.find_exercises_by_name("barbell squat", limit=1)[0]
    def exercise(row):
        return PersistedProgramExerciseSchema(exercise_id=str(row["id"]),
            exercise_name=row["name"], target_sets=3, target_reps_min=8, target_reps_max=12)
    days = [
        PersistedProgramDaySchema(day_name="Upper A", day_order=1, exercises=[exercise(bench), exercise({"id": raises[0][0], "name": raises[0][1]})]),
        PersistedProgramDaySchema(day_name="Upper B", day_order=2, exercises=[exercise(bench), exercise({"id": raises[1][0], "name": raises[1][1]})]),
        PersistedProgramDaySchema(day_name="Leg A", day_order=3, exercises=[exercise(squat)]),
    ]
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Upper Lower",
        weekly_frequency=3, days=days).model_dump())

    planned = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        "move lateral raises from Upper B to leg days")

    assert "proposal" in planned, planned
    assert any(day["day_name"] == "Upper B" and
        all(item["exercise_id"] != str(raises[1][0]) for item in day["exercises"])
        for day in planned["proposal"]["days"])
    result = resolve_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        ledger.set_pending_chat_program_edit(planned["proposal"], "preview"), confirm=True)
    assert "error" not in result, result
    active = ledger.get_active_program()
    upper_a = next(day for day in active.days if day.day_name == "Upper A")
    upper_b = next(day for day in active.days if day.day_name == "Upper B")
    lower = next(day for day in active.days if day.day_name == "Leg A")
    assert str(raises[0][0]) in {item.exercise_id for item in upper_a.exercises}
    assert str(raises[1][0]) not in {item.exercise_id for item in upper_b.exercises}
    assert str(raises[1][0]) in {item.exercise_id for item in lower.exercises}


def test_moving_lateral_raises_moves_them_off_the_upper_day(fresh_store):
    db = fresh_store
    ledger = db.ledger
    rows = db.catalog_conn.execute(
        "SELECT id, name FROM exercises WHERE LOWER(name) LIKE '%lateral raise%' ORDER BY id LIMIT 2"
    ).fetchall()
    assert rows
    squat = db.catalog_conn.execute(
        "SELECT id, name FROM exercises WHERE LOWER(name) LIKE '%squat%' ORDER BY id LIMIT 1"
    ).fetchone()
    bench = db.catalog_conn.execute(
        "SELECT id, name FROM exercises WHERE LOWER(name) LIKE '%bench press%' ORDER BY id LIMIT 1"
    ).fetchone()
    upper = PersistedProgramDaySchema(day_name="Upper A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(bench[0]), exercise_name=str(bench[1]),
            target_sets=3, target_reps_min=8, target_reps_max=12),
        PersistedProgramExerciseSchema(exercise_id=str(rows[0][0]), exercise_name=str(rows[0][1]),
            target_sets=3, target_reps_min=8, target_reps_max=12),
    ])
    lower = PersistedProgramDaySchema(day_name="Leg A", day_order=2, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(squat[0]), exercise_name=str(squat[1]),
            target_sets=3, target_reps_min=8, target_reps_max=12),
    ])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Upper Lower",
        weekly_frequency=2, days=[upper, lower]).model_dump())

    planned = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        "move lateral raises to leg days")

    assert "proposal" in planned, planned
    assert any(not exercise["exercise_id"] == str(rows[0][0])
               for exercise in planned["proposal"]["days"][0]["exercises"])
    result = resolve_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        ledger.set_pending_chat_program_edit(planned["proposal"], "preview"), confirm=True)
    assert "error" not in result, result
    active = ledger.get_active_program()
    upper_day = next(day for day in active.days if day.day_name == "Upper A")
    lower_day = next(day for day in active.days if day.day_name == "Leg A")
    assert str(rows[0][0]) not in {exercise.exercise_id for exercise in upper_day.exercises}
    assert any(exercise.exercise_id == str(rows[0][0]) for exercise in lower_day.exercises)


@pytest.mark.parametrize(("query", "expected_reply"), [
    ("add biceps to leg days",
     "Your assigned coach controls your program. You can review and send a request to your coach."),
    ("ضيف باي على أيام الرجل من فضلك",
     "يتولى مدربك المعيّن التحكم في برنامجك التدريبي. يمكنك مراجعة طلب وإرساله إلى مدربك."),
])
def test_coach_controlled_chat_edit_offers_program_request(fresh_store, query, expected_reply):
    from agent.assistant_graph import program_edit_chat_node
    state = {"messages": [HumanMessage(content=query)],
        "player_account_id": "00000000-0000-4000-8000-000000000001",
        "display_language": "en", "intent_metadata": {}}
    program = PersistedProgramSchema(program_name="Plan", split_type="Upper Lower",
        weekly_frequency=1, created_at="2026-10-27T00:00:00+00:00",
        published_by_coach_account_id="coach", days=[PersistedProgramDaySchema(day_name="Leg A",
            day_order=1, exercises=[
                PersistedProgramExerciseSchema(exercise_id="squat", exercise_name="Squat",
                    target_sets=3, target_reps_min=8, target_reps_max=12),
                PersistedProgramExerciseSchema(exercise_id="curl", exercise_name="Curl",
                    target_sets=3, target_reps_min=8, target_reps_max=12),
                PersistedProgramExerciseSchema(exercise_id="row", exercise_name="Row",
                    target_sets=3, target_reps_min=8, target_reps_max=12),
            ])])
    ledger = SimpleNamespace(get_active_program=lambda: program)
    store = SimpleNamespace(
        get_active_assignment_for_player=lambda _account: {
            "coach_account_id": "coach", "started_at": "2026-10-26T00:00:00+00:00"
        }
    )
    result = program_edit_chat_node(state, {"configurable": {"ledger": ledger, "store": store}})

    assert result["program_updated"] is False
    assert result["request_suggestion"]["kind"] == "split_change"
    assert result["response_content"] == expected_reply


def test_unrelated_yes_cannot_confirm_pending_chat_preview(fresh_store):
    from agent.assistant_graph import router_node

    db = fresh_store
    ledger = db.ledger
    row = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 1").fetchone()
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]),
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())
    proposal = {"expected_version": ledger.get_active_program().version, "days": [], "optional": []}
    ledger.set_pending_chat_program_edit(proposal, "Confirm this Program edit?")
    state = {"messages": [AIMessage(content="Unrelated prior reply"), HumanMessage(content="yes")],
        "player_account_id": "00000000-0000-4000-8000-000000000001", "display_language": "en"}

    result = router_node(state, {"configurable": {"ledger": ledger, "store": db}})

    assert result["intent"] != "program_edit_confirmation"
    assert ledger.get_pending_chat_program_edit() is None


def test_yes_after_its_own_preview_routes_to_confirmation(fresh_store):
    from agent.assistant_graph import router_node

    db = fresh_store
    ledger = db.ledger
    row = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 1").fetchone()
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]),
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())
    proposal = {"expected_version": ledger.get_active_program().version, "days": [], "optional": []}
    offer = "Program edit preview. Confirm or cancel."
    ledger.set_pending_chat_program_edit(proposal, offer)
    state = {"messages": [AIMessage(content=offer), HumanMessage(content="yes")],
        "player_account_id": "00000000-0000-4000-8000-000000000001", "display_language": "en"}

    result = router_node(state, {"configurable": {"ledger": ledger, "store": db}})

    assert result["intent"] == "program_edit_confirmation"


def test_include_forearms_confirms_and_selects_optional_exercise(fresh_store):
    from agent.assistant_graph import router_node

    db = fresh_store
    ledger = db.ledger
    row = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 1").fetchone()
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]),
            target_sets=3, target_reps_min=8, target_reps_max=12)])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Full Body",
        weekly_frequency=1, days=[day]).model_dump())
    proposal = {"expected_version": ledger.get_active_program().version, "days": [],
        "optional": [{"muscle": "forearms", "exercise_id": "wrist-1"}]}
    offer = "Program edit preview"
    ledger.set_pending_chat_program_edit(proposal, offer)
    state = {"messages": [AIMessage(content=offer), HumanMessage(content="yes, include forearms")],
        "player_account_id": "00000000-0000-4000-8000-000000000001", "display_language": "en"}

    result = router_node(state, {"configurable": {"ledger": ledger, "store": db}})

    assert result["intent"] == "program_edit_confirmation"
    assert result["intent_metadata"]["include_optional"] == ["wrist-1"]


@pytest.mark.parametrize("reply", ["Do not include forearms", "Should I include forearms?",
    "yes, but should I include forearms?"])
def test_ambiguous_or_negated_optional_reply_does_not_confirm(fresh_store, reply):
    from agent.assistant_graph import router_node

    db = fresh_store
    ledger = db.ledger
    offer = "Program edit preview. Confirm or cancel."
    ledger.set_pending_chat_program_edit({"expected_version": 1, "days": [], "optional": [
        {"muscle": "forearms", "exercise_id": "wrist-1"}]}, offer)
    state = {"messages": [AIMessage(content=offer), HumanMessage(content=reply)],
        "player_account_id": "00000000-0000-4000-8000-000000000001", "display_language": "en"}

    result = router_node(state, {"configurable": {"ledger": ledger, "store": db}})

    assert result["intent"] != "program_edit_confirmation"
    assert ledger.get_pending_chat_program_edit() is not None


def test_production_chat_requests_preview_then_confirm_one_version(fresh_store):
    from service.chat import build_turn_state

    db = fresh_store
    ledger = db.ledger
    account_id = "00000000-0000-4000-8000-000000000001"
    rows = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 4").fetchall()
    exercises = [PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]),
        target_sets=3, target_reps_min=8, target_reps_max=12) for row in rows]
    days = [
        PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[exercises[0]]),
        PersistedProgramDaySchema(day_name="Leg B", day_order=2, exercises=[exercises[1]]),
    ]
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Lower",
        weekly_frequency=2, days=days).model_dump())
    ledger.upsert_player_profile({"gender": "male", "age": 30, "height_cm": 175,
        "weight_kg": 80, "equipment_access": "Commercial gym", "injuries_or_limitations": "None",
        "weekly_frequency": 4, "training_age_years": 3, "rep_preference": "balanced"})
    # These four requests reproduce the 2026-10-27 production routing failure.
    cases = [
        "rebuild my program and augment leg days with bi, tri and side delt, maybe forearms",
        "add biceps and triceps to my leg days",
        "put side delts on leg days",
        "move lateral raises to leg days",
        "add biceps to leg days, don't rebuild my program",
    ]
    for query in cases:
        rows = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 4").fetchall()
        fresh_days = [PersistedProgramDaySchema(day_name=f"Leg {name}", day_order=index,
            exercises=[PersistedProgramExerciseSchema(exercise_id=str(rows[index - 1][0]),
                exercise_name=str(rows[index - 1][1]), target_sets=3,
                target_reps_min=8, target_reps_max=12)])
            for index, name in enumerate(("A", "B"), 1)]
        ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Lower",
            weekly_frequency=2, days=fresh_days).model_dump())
        before = ledger.get_active_program().version
        state = build_turn_state("player", [HumanMessage(content=query)], player_account_id=account_id)
        list(stream_assistant_turn(state, ledger=ledger, store=db))
        preview = state.get("program_edit_preview")
        assert preview and preview["days"], state.get("response_content")
        if "don't rebuild" in query:
            assert "Rebuild" not in state["response_content"]
        pending_version = ledger.get_active_program().version
        assert pending_version == before
        optional_ids = [item["exercise_id"] for item in preview.get("optional", [])]
        next_state = build_turn_state("player", [
            AIMessage(content=state["response_content"]), HumanMessage(content="yes")
        ], player_account_id=account_id)
        list(stream_assistant_turn(next_state, ledger=ledger, store=db))
        assert next_state["program_updated"] is True, (query, next_state.get("response_content"))
        assert ledger.get_active_program().version == pending_version + 1
        all_ids = {str(item.exercise_id) for day in ledger.get_active_program().days for item in day.exercises}
        assert not set(optional_ids).intersection(all_ids)


def test_cancelled_rebuild_preview_keeps_original_program_version(fresh_store):
    from service.chat import build_turn_state

    db = fresh_store
    ledger = db.ledger
    account_id = "00000000-0000-4000-8000-000000000001"
    rows = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 2").fetchall()
    days = [PersistedProgramDaySchema(day_name=f"Leg {label}", day_order=index, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(rows[index - 1][0]),
            exercise_name=str(rows[index - 1][1]), target_sets=3,
            target_reps_min=8, target_reps_max=12)])
        for index, label in enumerate(("A", "B"), 1)]
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Lower",
        weekly_frequency=2, days=days).model_dump())
    ledger.upsert_player_profile({"gender": "male", "age": 30, "height_cm": 175,
        "weight_kg": 80, "equipment_access": "Commercial gym", "injuries_or_limitations": "None",
        "weekly_frequency": 4, "training_age_years": 3, "rep_preference": "balanced"})
    before = ledger.get_active_program().version
    query = "rebuild my program and add biceps to leg days"
    preview_state = build_turn_state("player", [HumanMessage(content=query)], player_account_id=account_id)
    list(stream_assistant_turn(preview_state, ledger=ledger, store=db))
    assert preview_state.get("program_edit_preview")
    assert ledger.get_active_program().version == before
    decline_state = build_turn_state("player", [
        AIMessage(content=preview_state["response_content"]), HumanMessage(content="no")
    ], player_account_id=account_id)

    list(stream_assistant_turn(decline_state, ledger=ledger, store=db))

    assert decline_state["program_updated"] is False
    assert ledger.get_active_program().version == before


def test_egyptian_arabic_program_edit_previews_and_confirms(fresh_store):
    from service.chat import build_turn_state

    db = fresh_store
    ledger = db.ledger
    account_id = "00000000-0000-4000-8000-000000000001"
    rows = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 2").fetchall()
    days = [PersistedProgramDaySchema(day_name=f"Leg {name}", day_order=index,
        exercises=[PersistedProgramExerciseSchema(exercise_id=str(rows[index - 1][0]),
            exercise_name=str(rows[index - 1][1]), target_sets=3, target_reps_min=8,
            target_reps_max=12)])
        for index, name in enumerate(("A", "B"), 1)]
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Lower",
        weekly_frequency=2, days=days).model_dump())
    state = build_turn_state("player", [HumanMessage(content="حط باي وتراي وكتف جانبي على أيام الرجل")],
        player_account_id=account_id)
    state["display_language"] = "ar"

    list(stream_assistant_turn(state, ledger=ledger, store=db))

    assert state["program_edit_preview"]["days"]
    followup = build_turn_state("player", [AIMessage(content=state["response_content"]),
        HumanMessage(content="أيوه")], player_account_id=account_id)
    followup["display_language"] = "ar"
    list(stream_assistant_turn(followup, ledger=ledger, store=db))
    assert followup["program_updated"] is True


@pytest.mark.parametrize("query", [
    "rebuild my program; add biceps to leg days",
    "rebuild my program and add biceps to leg days",
    "rebuild my program then add biceps to leg days",
    "add biceps to leg days and rebuild my program",
    "add biceps to leg days, then rebuild my program",
    "جدّد برنامجي؛ وحط باي على أيام الرجل",
])
def test_all_rebuild_edit_clause_orders_are_preview_only(fresh_store, query):
    from service.chat import build_turn_state

    db, ledger = fresh_store, fresh_store.ledger
    account_id = "00000000-0000-4000-8000-000000000001"
    rows = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 2").fetchall()
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Lower",
        weekly_frequency=2, days=[PersistedProgramDaySchema(day_name=f"Leg {i}", day_order=i,
            exercises=[PersistedProgramExerciseSchema(exercise_id=str(rows[i-1][0]),
                exercise_name=str(rows[i-1][1]), target_sets=3, target_reps_min=8,
                target_reps_max=12)]) for i in (1, 2)]).model_dump())
    ledger.upsert_player_profile({"gender": "male", "age": 30, "height_cm": 175,
        "weight_kg": 80, "equipment_access": "Commercial gym", "injuries_or_limitations": "None",
        "weekly_frequency": 4, "training_age_years": 3, "rep_preference": "balanced"})
    before = ledger.get_active_program().version
    state = build_turn_state("player", [HumanMessage(content=query)], player_account_id=account_id)
    list(stream_assistant_turn(state, ledger=ledger, store=db))
    assert state.get("program_edit_preview"), state.get("response_content")
    assert ledger.get_active_program().version == before
    answer = "أيوه" if "جدّد" in query else "yes"
    confirmation = build_turn_state("player", [AIMessage(content=state["response_content"]),
        HumanMessage(content=answer)], player_account_id=account_id)
    list(stream_assistant_turn(confirmation, ledger=ledger, store=db))
    assert confirmation["program_updated"] is True
    assert ledger.get_active_program().version == before + 1


@pytest.mark.parametrize("query", [
    "my knee hurts; rebuild my program and add biceps to leg days",
    "ركبتي بتوجعني؛ جدّد برنامجي وحط باي على أيام الرجل",
])
def test_clinical_clause_records_injury_before_rebuild_edit(fresh_store, query):
    from service.chat import build_turn_state

    db, ledger = fresh_store, fresh_store.ledger
    account_id = "00000000-0000-4000-8000-000000000001"
    row = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 1").fetchone()
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Lower",
        weekly_frequency=1, days=[PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
            PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]), target_sets=3,
                target_reps_min=8, target_reps_max=12)])]).model_dump())
    ledger.upsert_player_profile({"gender": "male", "age": 30, "height_cm": 175, "weight_kg": 80,
        "equipment_access": "Commercial gym", "injuries_or_limitations": "None", "weekly_frequency": 4,
        "training_age_years": 3, "rep_preference": "balanced"})
    before = ledger.get_active_program().version
    state = build_turn_state("player", [HumanMessage(content=query)], player_account_id=account_id)
    list(stream_assistant_turn(state, ledger=ledger, store=db))
    assert state["intent"] == "clinical_intercept"
    assert state.get("program_edit_preview") is None
    assert ledger.get_active_program().version == before
    assert any(record["body_area"] == "knee" for record in ledger.list_injury_records())


@pytest.mark.parametrize("reply", ["no", "cancel", "لا", "لأ", "مش عايز"])
def test_plain_decline_resolves_pending_program_edit(fresh_store, reply):
    from agent.assistant_graph import router_node

    db, ledger = fresh_store, fresh_store.ledger
    offer = "Program edit preview. Confirm or cancel."
    ledger.set_pending_chat_program_edit({"expected_version": 1, "days": [], "optional": []}, offer)
    state = {"messages": [AIMessage(content=offer), HumanMessage(content=reply)],
        "player_account_id": "00000000-0000-4000-8000-000000000001", "display_language": "en"}
    result = router_node(state, {"configurable": {"ledger": ledger, "store": db}})
    assert result["intent"] == "program_edit_confirmation"
    assert result["intent_metadata"]["confirm"] is False


def test_plain_no_cancels_offer_with_explicit_reply(fresh_store):
    from service.chat import build_turn_state

    db, ledger = fresh_store, fresh_store.ledger
    offer = "Program edit preview. Confirm or cancel."
    ledger.set_pending_chat_program_edit({"expected_version": 1, "days": [], "optional": []}, offer)
    state = build_turn_state("player", [AIMessage(content=offer), HumanMessage(content="no")],
        player_account_id="00000000-0000-4000-8000-000000000001")
    list(stream_assistant_turn(state, ledger=ledger, store=db))
    assert "cancelled" in state["response_content"].casefold()
    assert ledger.get_pending_chat_program_edit() is None


def test_named_triceps_exercise_removal_does_not_expand_to_muscle(fresh_store):
    db, ledger = fresh_store, fresh_store.ledger
    rows = db.catalog_conn.execute("SELECT id, name FROM exercises WHERE lower(name) LIKE '%triceps%' ORDER BY name LIMIT 2").fetchall()
    assert len(rows) >= 2
    extra = db.catalog_conn.execute("SELECT id, name FROM exercises WHERE id NOT IN (?, ?) ORDER BY id LIMIT 1",
        (rows[0][0], rows[1][0])).fetchone()
    day = PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
        PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]), target_sets=3,
            target_reps_min=8, target_reps_max=12)
        for row in [*rows, extra]])
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Lower",
        weekly_frequency=1, days=[day]).model_dump())
    planned = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        f"remove {rows[0][1]} from leg days")
    assert "error" not in planned
    retained = planned["proposal"]["days"][0]["exercises"]
    assert [item["exercise_id"] for item in retained] == [str(rows[1][0]), str(extra[0])]
    changed = plan_chat_program_edit(db, ledger, "00000000-0000-4000-8000-000000000001",
        f"change {rows[0][1]} to 4 sets on leg days")
    assert "error" not in changed
    prescriptions = {item["exercise_id"]: item["target_sets"]
        for item in changed["proposal"]["days"][0]["exercises"]}
    assert prescriptions[str(rows[0][0])] == 4
    assert prescriptions[str(rows[1][0])] == 3


def test_player_writer_transaction_does_not_reserve_catalog_writer(fresh_store):
    db, ledger = fresh_store, fresh_store.ledger
    row = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 1").fetchone()
    import threading

    started = threading.Event()
    finished = threading.Event()
    def catalog_write():
        started.set()
        db.catalog_conn.execute("UPDATE exercises SET name = name WHERE id = ?", (row[0],))
        db.catalog_conn.commit()
        finished.set()

    with ledger.ledger_transaction(immediate=True):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(catalog_write)
            assert started.wait(1)
            assert finished.wait(2), "player writer lock blocked the shared catalog"
            future.result()


def test_rebuild_preview_with_optional_item_includes_all_days(fresh_store):
    from service.chat import build_turn_state

    db, ledger = fresh_store, fresh_store.ledger
    account_id = "00000000-0000-4000-8000-000000000001"
    rows = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 2").fetchall()
    ledger.save_training_program(PersistedProgramSchema(program_name="Old", split_type="Lower",
        weekly_frequency=1, days=[PersistedProgramDaySchema(day_name="Leg A", day_order=1,
            exercises=[PersistedProgramExerciseSchema(exercise_id=str(rows[0][0]), exercise_name=str(rows[0][1]),
                target_sets=3, target_reps_min=8, target_reps_max=12)])]).model_dump())
    ledger.upsert_player_profile({"gender": "male", "age": 30, "height_cm": 175, "weight_kg": 80,
        "equipment_access": "Commercial gym", "injuries_or_limitations": "None", "weekly_frequency": 4,
        "training_age_years": 3, "rep_preference": "balanced"})
    state = build_turn_state("player", [HumanMessage(content="rebuild my program and add biceps to leg days, maybe forearms")],
        player_account_id=account_id)
    list(stream_assistant_turn(state, ledger=ledger, store=db))
    preview = state["program_edit_preview"]
    assert len(preview["days"]) >= 4
    assert any(exercise["requested_edit"] for day in preview["days"] for exercise in day["exercises"])
    assert preview["optional"]


def test_profile_change_stales_chat_preview_and_preserves_exact_plan(fresh_store):
    db, ledger = fresh_store, fresh_store.ledger
    account_id = "00000000-0000-4000-8000-000000000001"
    row = db.find_exercises_by_name("barbell squat", limit=1)[0]
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Lower",
        weekly_frequency=1, days=[PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
            PersistedProgramExerciseSchema(exercise_id=str(row["id"]), exercise_name=row["name"],
                target_sets=3, target_reps_min=8, target_reps_max=12)])]).model_dump())
    ledger.upsert_player_profile({"gender": "male", "age": 30, "height_cm": 175, "weight_kg": 80,
        "equipment_access": "Commercial gym", "injuries_or_limitations": "None", "weekly_frequency": 1,
        "training_age_years": 3, "rep_preference": "balanced"})
    planned = plan_chat_program_edit(db, ledger, account_id, "add biceps to leg days")
    assert "error" not in planned
    previewed = planned["proposal"]["days"][0]["exercises"][-1]["prescription"]
    preview_id = ledger.set_pending_chat_program_edit(planned["proposal"], "preview")
    before = ledger.get_active_program().version
    ledger.upsert_player_profile({"training_age_years": 0})
    from service.chat import build_turn_state
    stale_state = build_turn_state("player", [AIMessage(content="preview"), HumanMessage(content="yes")],
        player_account_id=account_id)
    list(stream_assistant_turn(stale_state, ledger=ledger, store=db))
    assert stale_state.get("program_edit_preview")
    assert stale_state["program_edit_preview"]["id"] != preview_id
    assert ledger.get_active_program().version == before
    assert "fresh" in stale_state["response_content"].lower() or "preview" in stale_state["response_content"].lower()
    assert previewed["target_reps_min"] is not None

    refreshed = plan_chat_program_edit(db, ledger, account_id, "add triceps to leg days")
    assert "error" not in refreshed
    added = refreshed["proposal"]["days"][0]["exercises"][-1]
    prescription = added["prescription"]
    preview_id = ledger.set_pending_chat_program_edit(refreshed["proposal"], "fresh preview")
    saved = resolve_chat_program_edit(db, ledger, account_id, preview_id, confirm=True)
    assert "error" not in saved
    committed = next(item for day in ledger.get_active_program().days for item in day.exercises
        if str(item.exercise_id) == added["exercise_id"])
    assert committed.target_reps_min == prescription["target_reps_min"]
    assert committed.target_reps_max == prescription["target_reps_max"]
    assert committed.target_rpe == prescription["target_rpe"]
    assert committed.rest_seconds == prescription["rest_seconds"]


def test_rebuild_no_op_edit_still_saves_against_persisted_program(fresh_store):
    from agent.assistant_graph import _build_chat_rebuild_preview
    from agent.ProgramState import program_exercise_working_sets
    from service.chat_program_edit import _is_lower_day

    db, ledger = fresh_store, fresh_store.ledger
    account_id = "00000000-0000-4000-8000-000000000001"
    old_row = db.catalog_conn.execute("SELECT id, name FROM exercises ORDER BY id LIMIT 1").fetchone()
    ledger.save_training_program(PersistedProgramSchema(program_name="Old", split_type="Lower",
        weekly_frequency=1, days=[PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
            PersistedProgramExerciseSchema(exercise_id=str(old_row[0]), exercise_name=str(old_row[1]),
                target_sets=3, target_reps_min=8, target_reps_max=12)])]).model_dump())
    ledger.upsert_player_profile({"gender": "male", "age": 30, "height_cm": 175, "weight_kg": 80,
        "equipment_access": "Commercial gym", "injuries_or_limitations": "None", "weekly_frequency": 1,
        "training_age_years": 3, "rep_preference": "balanced"})
    candidate = _build_chat_rebuild_preview("rebuild my program for 4 days", ledger)
    lower_day = next(day for day in candidate.days if _is_lower_day(db, day.model_dump()))
    exercise = lower_day.exercises[0]
    target_sets = program_exercise_working_sets(exercise.model_dump())
    query = f"rebuild my program for 4 days and change {exercise.exercise_name} to {target_sets} sets on leg days"
    regenerated = _build_chat_rebuild_preview(query, ledger)
    planned = plan_chat_program_edit(db, ledger, account_id, query, base_program=regenerated)
    assert "error" not in planned
    preview_id = ledger.set_pending_chat_program_edit(planned["proposal"], "rebuild preview")
    before = ledger.get_active_program().version
    result = resolve_chat_program_edit(db, ledger, account_id, preview_id, confirm=True)
    assert "error" not in result
    assert ledger.get_active_program().version == before + 1
    assert ledger.get_active_program().weekly_frequency == 4


@pytest.mark.parametrize(("language", "reply", "expected"), [
    ("en", "yes", "already matches"),
    ("ar", "أيوه", "مطابق"),
])
def test_unchanged_chat_confirm_says_nothing_changed(fresh_store, language, reply, expected):
    from service.chat import build_turn_state

    db, ledger = fresh_store, fresh_store.ledger
    account_id = "00000000-0000-4000-8000-000000000001"
    squat = db.find_exercises_by_name("barbell squat", limit=1)[0]
    ledger.save_training_program(PersistedProgramSchema(program_name="Plan", split_type="Lower",
        weekly_frequency=1, days=[PersistedProgramDaySchema(day_name="Leg A", day_order=1, exercises=[
            PersistedProgramExerciseSchema(exercise_id=str(squat["id"]), exercise_name=squat["name"],
                target_sets=3, target_reps_min=8, target_reps_max=12)])]).model_dump())
    active = ledger.get_active_program()
    proposal = {"expected_version": active.version, "profile_fingerprint": None, "days": [{
        "day_name": "Leg A", "day_order": 1, "week_order": 1, "exercises": [
            {"source_index": 0, "exercise_id": str(squat["id"]), "target_sets": 3}]}], "optional": []}
    offer = "Program edit preview. Confirm or cancel."
    ledger.set_pending_chat_program_edit(proposal, offer)
    state = build_turn_state("player", [AIMessage(content=offer), HumanMessage(content=reply)],
        player_account_id=account_id)
    state["display_language"] = language
    before = active.version
    list(stream_assistant_turn(state, ledger=ledger, store=db))
    assert state["program_updated"] is False
    assert expected in state["response_content"].casefold()
    assert ledger.get_active_program().version == before
