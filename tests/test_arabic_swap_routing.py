import json

import pytest

from langchain_core.messages import HumanMessage, ToolMessage

from agent import assistant_graph
from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema
from agent.assistant_graph import stream_assistant_turn
from tests.fakes.chat_model import ScriptedChatModel, ToolCallsTurn

ARABIC_SWAP_CLARIFICATION = "أنهي تمرين عايز تغيّره؟"
COACHING_REPLY = "خد راحة كفاية حسب إحساسك، وخلّي مجهودك مناسب لحالتك."


def _seed_program(store, *, duplicate_bench=False):
    ledger = store.ledger
    ledger.upsert_player_profile({"weekly_frequency": 3, "equipment_access": "Commercial gym"})
    names = ["barbell bench press", "barbell squat", "barbell row"]
    if duplicate_bench:
        names.append("dumbbell bench press")
    exercises = []
    for name in names:
        matches = store.find_exercises_by_name(name, limit=1)
        assert matches
        entry = store.get_exercise_library_entry(str(matches[0]["id"]))
        exercises.append(
            ProgramExerciseSchema(
                exercise_id=str(entry["id"]),
                exercise_name=entry["name"],
                target_reps_min=6,
                target_reps_max=10,
            )
        )
    program = GeneratedProgramSchema(
        program_name="Arabic swap test program",
        split_type="Full Body",
        weekly_frequency=3,
        days=[ProgramDaySchema(day_name="Full A", day_order=1, exercises=exercises)],
    )
    ledger.save_training_program(program.model_dump())
    return ledger.get_active_program()


def _turn(message):
    return {
        "messages": [HumanMessage(content=message)],
        "trainee_id": "arabic_swap_test",
        "player_account_id": None,
        "coach_tone": "Direct and pragmatic",
        "custom_instructions": "",
        "telemetry_context": "",
        "intent": None,
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None,
    }


def _tool_call(name, args=None):
    return ToolCallsTurn(calls=[{"name": name, "args": args or {}, "id": "selected-tool"}])


def _substitution_call(source, target=None, day_name=None):
    args = {"source_exercise": source, "target_exercise": target}
    if day_name is not None:
        args["day_name"] = day_name
    return _tool_call("substitute_exercise", args)


def _tool_results(model, name):
    return [
        json.loads(message.content)
        for call in model.calls
        for message in call["messages"]
        if isinstance(message, ToolMessage) and message.name == name
    ]


def test_standard_arabic_swap_resolves_model_selected_natural_names(fresh_store, monkeypatch):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([_substitution_call("Barbell Bench Press", "Dumbbell Bench Press")])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("استبدل تمرين Barbell Bench Press بتمرين Dumbbell Bench Press.")

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["selected_tools"] == ["substitute_exercise"]
    assert "substitute_exercise" in model.calls[0]["tools"]
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Bench Press (Dumbbell)" in names
    assert "Bench Press (Barbell)" not in names


def test_egyptian_bench_request_resolves_single_program_match(fresh_store, monkeypatch):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([_substitution_call("Bench Press", "Dumbbell Bench Press")])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("بدّل لي البنش بالدامبل.")

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["selected_tools"] == ["substitute_exercise"]
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Bench Press (Dumbbell)" in names
    assert "Bench Press (Barbell)" not in names


def test_egyptian_incline_request_resolves_library_style_target(fresh_store, monkeypatch):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([
        _substitution_call("Bench Press (Barbell)", "Incline Bench Press (Barbell)")
    ])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("عايز أبدّل البنش بضغط مائل بالبار.")

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["selected_tools"] == ["substitute_exercise"]
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Incline Bench Press (Barbell)" in names
    assert "Bench Press (Barbell)" not in names


def test_leg_press_target_matches_the_english_named_target_path(fresh_store, monkeypatch):
    from agent.assistant_graph import exercise_substitution_node

    before = _seed_program(fresh_store)
    original_names = {
        exercise.exercise_name
        for day in before.days
        for exercise in day.exercises
    }
    english_state = _turn("swap Back Squat (Barbell) for Leg Press")
    english_state["intent"] = "exercise_substitution"
    english_state["intent_metadata"] = {
        "mode": "direct_swap",
        "source_exercise": "Back Squat (Barbell)",
        "target_exercise": "Leg Press",
    }
    exercise_substitution_node(
        english_state,
        {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}},
    )
    english_program = fresh_store.ledger.get_active_program()
    english_target = next(
        exercise.exercise_name
        for exercise in english_program.days[0].exercises
        if exercise.exercise_name not in original_names
    )

    before = _seed_program(fresh_store)
    original_names = {
        exercise.exercise_name
        for day in before.days
        for exercise in day.exercises
    }
    model = ScriptedChatModel([_substitution_call("Back Squat (Barbell)", "Leg Press")])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    arabic_state = _turn("بدّل السكوات بالليج برس.")
    list(stream_assistant_turn(arabic_state, ledger=fresh_store.ledger, store=fresh_store))
    arabic_program = fresh_store.ledger.get_active_program()
    arabic_target = next(
        exercise.exercise_name
        for exercise in arabic_program.days[0].exercises
        if exercise.exercise_name not in original_names
    )

    assert english_target == arabic_target
    assert english_target == "45° Leg Press (Plate-Loaded)"
    assert arabic_state["selected_tools"] == ["substitute_exercise"]
    assert arabic_state["program_updated"] is True


def test_arabic_target_clarifies_without_mutation(fresh_store, monkeypatch):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([_substitution_call("Bench Press (Barbell)", "دامبل")])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("بدّل لي البنش بالدامبل.")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["selected_tools"] == ["substitute_exercise"]
    assert state["program_updated"] is False
    assert after.version == before.version
    assert "Bench Press (Barbell)" in names
    assert response == ARABIC_SWAP_CLARIFICATION


def test_ar_mixed_03_suggestion_never_executes_scripted_swap(fresh_store, monkeypatch):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([_substitution_call("Back Squat (Barbell)", "Goblet Squat")])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("الـ squat مش مريح، can you suggest a safer alternative?")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["selected_tools"] == ["substitute_exercise"]
    assert state["program_updated"] is False
    assert after.version == before.version
    assert names == [
        exercise.exercise_name for exercise in before.days[0].exercises
    ]
    assert "45° Leg Press (Plate-Loaded)" not in names
    assert response == assistant_graph.AUTHORIZATION_RESPONSE


def test_ar_mixed_03_mismatched_name_hit_clarifies_without_mutation(fresh_store, monkeypatch):
    before = _seed_program(fresh_store)
    leg_press = fresh_store.find_exercises_by_name("Leg Press", limit=1)[0]
    original_search = fresh_store.find_exercises_by_name

    def name_search(name, *args, **kwargs):
        if name == "Goblet Squat":
            return [leg_press]
        return original_search(name, *args, **kwargs)

    monkeypatch.setattr(fresh_store, "find_unique_exercise_id_by_exact_name", lambda _name: None)
    monkeypatch.setattr(fresh_store, "find_exercises_by_name", name_search)
    model = ScriptedChatModel([_substitution_call("Back Squat (Barbell)", "Goblet Squat")])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("بدّل السكوات ب Goblet Squat.")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    assert state["selected_tools"] == ["substitute_exercise"]
    assert state["program_updated"] is False
    assert after.version == before.version
    assert "45° Leg Press (Plate-Loaded)" not in {exercise.exercise_name for exercise in after.days[0].exercises}
    assert response == ARABIC_SWAP_CLARIFICATION


def test_arabic_swap_with_weight_question_executes_the_selected_operation(
    fresh_store, monkeypatch
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([_substitution_call("Bench Press (Barbell)", "Dumbbell Bench Press")])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("بدّل لي البنش بالدامبل. وقولّي أزوّد الوزن إمتى؟")

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["selected_tools"] == ["substitute_exercise"]
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert names.count("Bench Press (Dumbbell)") == 1
    assert "Bench Press (Barbell)" not in names


def test_preferred_name_request_is_written_by_the_selected_tool(
    fresh_store, monkeypatch
):
    _seed_program(fresh_store)
    model = ScriptedChatModel([_tool_call("preferred_name")])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("ناديني سلمى")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    assert state["selected_tools"] == ["preferred_name"]
    assert fresh_store.ledger.get_assistant_memory()["preferred_name"] == "سلمى"
    assert response == "تمام، هناديك سلمى."


def test_ambiguous_source_clarifies_without_mutation(fresh_store, monkeypatch):
    before = _seed_program(fresh_store, duplicate_bench=True)
    model = ScriptedChatModel([_substitution_call("Bench Press", "Incline Bench Press")])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("بدّل لي البنش")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    assert state["selected_tools"] == ["substitute_exercise"]
    assert state["program_updated"] is False
    assert after.version == before.version
    assert response == ARABIC_SWAP_CLARIFICATION


@pytest.mark.parametrize(
    "message",
    [
        "أريح قد إيه بين المجموعات؟",
        "أتمرن النهارده ولا أريح؟ رجلي مرهقة من تمرين امبارح.",
        "سؤال تاني عن النادي.",
    ],
)
def test_arabic_coaching_questions_get_normal_coaching_answer(
    fresh_store, monkeypatch, message
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([COACHING_REPLY])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn(message)

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    assert state["program_updated"] is False
    assert not state.get("selected_tools")
    assert after.version == before.version
    assert response == COACHING_REPLY


def test_composite_swap_request_executes_only_the_selected_operation(
    fresh_store, monkeypatch
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([_substitution_call("Barbell Bench Press", "Dumbbell Bench Press")])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("بدّل البنش بالدامبل وقولّي عملت إيه في السكوات")

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["selected_tools"] == ["substitute_exercise"]
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Bench Press (Dumbbell)" in names
    assert "Back Squat (Barbell)" in names


def test_unresolved_swap_target_clarifies_without_mutation(fresh_store, monkeypatch):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([_substitution_call("Barbell Bench Press", "Imaginary Press")])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("عايز أبدّل البنش بتمرين تاني")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    assert state["selected_tools"] == ["substitute_exercise"]
    assert state["program_updated"] is False
    assert after.version == before.version
    assert response == ARABIC_SWAP_CLARIFICATION


def test_english_swap_with_arabic_politeness_is_authorized_by_selected_operation(
    fresh_store, monkeypatch
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([_substitution_call("Back Squat (Barbell)", "Leg Press")])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("swap Back Squat (Barbell) for Leg Press يا كابتن")

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["selected_tools"] == ["substitute_exercise"]
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "45° Leg Press (Plate-Loaded)" in names


@pytest.mark.parametrize(
    ("message", "expected_franco"),
    [
        ("ركبتي بتوجعني جامد وأنا بعمل القرفصاء.", False),
        ("3ayez a3raf eh a7san setup lel bench press w el sets ad eh?", True),
    ],
)
def test_arabic_clinical_and_franco_messages_are_intercepted_before_swap_routing(
    fresh_store, monkeypatch, message, expected_franco
):
    model = ScriptedChatModel()
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn(message)

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    assert state["intent"] == "clinical_intercept"
    assert state["intent_metadata"].get("franco", False) is expected_franco
    assert response


@pytest.mark.parametrize(
    ("message", "exercise_name", "expected_exercise"),
    [
        ("عملت كام تكرار في آخر تمرين للقرفصاء؟", "Back Squat (Barbell)", "Back Squat (Barbell)"),
        ("آخر مرة لعبت ضغط صدر بالبار، رفعت كام؟", "Bench Press (Barbell)", "Bench Press (Barbell)"),
        ("ما الوزن الذي سجلته في تمرين squat خلال آخر جلسة؟", "Squat", "Back Squat (Barbell)"),
    ],
)
def test_model_selected_history_tool_resolves_arabic_exercise_names(
    fresh_store, monkeypatch, message, exercise_name, expected_exercise
):
    program = _seed_program(fresh_store)
    program_exercise_names = {
        exercise.exercise_name
        for day in program.days
        for exercise in day.exercises
    }
    model = ScriptedChatModel([
        _tool_call("get_exercise_history", {
            "exercise_name": exercise_name,
            "scope": "last_occurrence",
        }),
        "البيانات المسجلة للتمرين موجودة في السياق.",
    ])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn(message)

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    assert state["selected_tools"] == ["get_exercise_history"]
    assert state["program_updated"] is False
    assert response == "البيانات المسجلة للتمرين موجودة في السياق."
    [result] = _tool_results(model, "get_exercise_history")
    assert result["status"] == "ok"
    assert result["exercise"] == expected_exercise
    assert result["exercise"] in program_exercise_names


def test_arabic_train_or_rest_advice_does_not_mutate_program(
    fresh_store, monkeypatch
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([COACHING_REPLY])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("أتمرن النهارده ولا أريح؟ رجلي مرهقة من تمرين امبارح.")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    assert not state.get("selected_tools")
    assert state["program_updated"] is False
    assert fresh_store.ledger.get_active_program().version == before.version
    assert response == COACHING_REPLY
