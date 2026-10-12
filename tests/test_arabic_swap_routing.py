import pytest
from langchain_core.messages import HumanMessage

from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema
from agent.assistant_graph import stream_assistant_turn
from tests.fakes.chat_model import ScriptedChatModel

ARABIC_SWAP_CLARIFICATION = "أنهي تمرين عايز تغيّره؟"
ARABIC_ONE_AT_A_TIME_NOTE = "هبدّل التمرين ده الأول، وبعدها قولي تحب أساعدك في إيه كمان؟"


def _seed_program(store):
    ledger = store.ledger
    ledger.upsert_player_profile({"weekly_frequency": 3, "equipment_access": "Commercial gym"})
    exercises = []
    for name in ("barbell bench press", "barbell squat", "barbell row"):
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


@pytest.mark.parametrize(
    "message",
    [
        "عايز أبدّل البنش بالدامبل",
        "أريد استبدال تمرين Bench Press (Barbell) بـ Bench Press (Dumbbell)",
        "بدّل الـ bench press بـ dumbbell bench press",
    ],
)
def test_arabic_swap_requests_replace_the_validated_program_exercise(
    fresh_store, monkeypatch, message
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel(
        [
            {
                "intent": "exercise_substitution",
                "source_exercise": "Bench Press (Barbell)",
                "target_exercise": "Bench Press (Dumbbell)",
            }
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn(message)

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["intent"] == "exercise_substitution"
    assert state["program_updated"] is True
    assert after.version == before.version + 1
    assert "Bench Press (Dumbbell)" in names
    assert "Bench Press (Barbell)" not in names


def test_arabic_dominant_mixed_swap_routes_through_arabic_classifier(
    fresh_store, monkeypatch
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel(
        [
            {
                "intent": "exercise_substitution",
                "source_exercise": "Bench Press (Barbell)",
                "target_exercise": "Bench Press (Dumbbell)",
            }
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("بدّل لي الـ barbell bench press بـ dumbbell bench press.")

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    assert state["intent"] == "exercise_substitution"
    assert state["program_updated"] is True
    assert after.version == before.version + 1


def test_english_swap_with_arabic_politeness_keeps_the_english_route(monkeypatch):
    from agent.assistant_graph import router_node

    model = ScriptedChatModel()
    monkeypatch.setattr("agent.assistant_graph.llm", model)

    routed = router_node(
        {"messages": [HumanMessage(content="swap bench press for dumbbell press يا كابتن")]}
    )

    assert routed["intent"] == "exercise_substitution"
    assert "arabic_data_validated" not in routed["intent_metadata"]


@pytest.mark.parametrize(
    "classification",
    [
        {"intent": "exercise_substitution", "source_exercise": "Bench Press (Barbell)"},
        {
            "intent": "exercise_substitution",
            "source_exercise": "Bench Press (Barbell)",
            "target_exercise": "Imaginary Press",
        },
    ],
)
def test_arabic_swap_without_one_valid_source_and_target_clarifies_without_mutation(
    fresh_store, monkeypatch, classification
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([classification])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("عايز أبدّل البنش")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    assert state["intent"] == "arabic_swap_clarification"
    assert state["program_updated"] is False
    assert after.version == before.version
    assert response == ARABIC_SWAP_CLARIFICATION


def test_arabic_composite_swap_runs_once_and_prompts_for_the_next_request(
    fresh_store, monkeypatch
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel(
        [
            {
                "intent": "exercise_substitution",
                "source_exercise": "Bench Press (Barbell)",
                "target_exercise": "Bench Press (Dumbbell)",
                "has_additional_request": True,
            }
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("بدّل البنش بالدامبل وقولّي عملت إيه في السكوات")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    names = [exercise.exercise_name for exercise in after.days[0].exercises]
    assert state["intent"] == "composite_intent"
    assert after.version == before.version + 1
    assert state["program_updated"] is True
    assert "Bench Press (Dumbbell)" in names
    assert "Back Squat (Barbell)" in names
    assert ARABIC_ONE_AT_A_TIME_NOTE in response


@pytest.mark.parametrize(
    "classification",
    [
        {
            "intent": "exercise_substitution",
            "source_exercise": "البنش",
            "target_exercise": "Bench Press (Dumbbell)",
        },
        {
            "intent": "exercise_substitution",
            "source_exercise": "Bench Press (Barbell)",
            "target_exercise": "الدامبل",
        },
    ],
)
def test_arabic_classifier_must_return_exact_library_names(
    fresh_store, monkeypatch, classification
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel([classification])
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("عايز أبدّل البنش بالدامبل")

    response = "".join(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    assert state["intent"] == "arabic_swap_clarification"
    assert state["program_updated"] is False
    assert after.version == before.version
    assert response == ARABIC_SWAP_CLARIFICATION


def test_arabic_program_intent_stays_in_coaching_until_its_routing_ticket(
    fresh_store, monkeypatch
):
    before = _seed_program(fresh_store)
    model = ScriptedChatModel(
        [
            {"intent": "program_mutation", "target_frequency": 4},
            "ممكن نتكلم عن التغيير ده؟",
        ]
    )
    monkeypatch.setattr("agent.assistant_graph.llm", model)
    state = _turn("عايز أغيّر الـ program لـ 4 days per week")

    list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))

    after = fresh_store.ledger.get_active_program()
    assert state["intent"] == "coaching_qa"
    assert state["program_updated"] is False
    assert after.version == before.version


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
