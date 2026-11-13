# tests/test_precommit_and_multi_intent.py
from __future__ import annotations

import random
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage

from tests.test_context_management import graph as graph

if TYPE_CHECKING:
    from agent.assistant_graph import AssistantState


def _real_handler(name):
    def invoke(*args, **kwargs):
        from agent import assistant_graph

        return getattr(assistant_graph, name)(*args, **kwargs)
    return invoke


router_node = _real_handler("router_node")
exercise_substitution_node = _real_handler("exercise_substitution_node")
program_mutation_node = _real_handler("program_mutation_node")
stream_assistant_turn = _real_handler("stream_assistant_turn")


@pytest.fixture
def db_fixture(fresh_store, monkeypatch):
    from agent import program_generator
    db = fresh_store
    try:
        profile = {
            "gender": "male",
            "proportions": "balanced",
            "experience": "intermediate",
            "equipment": "commercial_gym",
            "target_frequency": 4,
            "primary_goal": "hypertrophy",
            "coach_tone": "Direct, grounded, and pragmatic",
        }
        db.ledger.upsert_player_profile(profile)
        random.seed(11)
        program_generator.generate_program_pipeline(user_split_override=None, frequency_override=4, ledger=db.ledger)
        yield db
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def test_inquisitive_mutation_guard(db_fixture):
    """Verifies that hypothetical/inquisitive questions do not wipe or mutate the routine."""
    active_before = db_fixture.ledger.get_active_program()
    assert active_before is not None

    inquisitive_queries = [
        "Should I change my routine if I feel fatigued?",
        "Can I switch my program to 3 days if work is busy?",
        "What if I update my split to 5 days?",
        "Why does my routine have 4 days a week?",
    ]

    for query in inquisitive_queries:
        state: AssistantState = {
            "messages": [HumanMessage(content=query)],
            "trainee_id": "default",
            "coach_tone": "Direct",
            "custom_instructions": "",
            "telemetry_context": None,
            "intent": None,
            "intent_metadata": {},
            "active_intents": None,
            "program_updated": False,
            "response_content": None,
        }
        res = router_node(state, {"configurable": {"ledger": db_fixture.ledger, "store": db_fixture}})
        # Must NOT be classified as program_mutation
        assert res.get("intent") != "program_mutation", f"Query '{query}' was incorrectly classified as program_mutation"

        # Defense-in-depth: Even if passed to program_mutation_node directly, it should reject
        mutation_res = program_mutation_node(state, {"configurable": {"ledger": db_fixture.ledger, "store": db_fixture}})
        assert mutation_res["program_updated"] is False
        assert "explicit directive" in mutation_res["response_content"].lower()

    # Verify database program was completely untouched
    active_after = db_fixture.ledger.get_active_program()
    assert active_after.program_name == active_before.program_name
    assert active_after.weekly_frequency == active_before.weekly_frequency


def test_invalid_exercise_swap_guard(db_fixture):
    """Verifies that non-exercises (e.g. 'pizza') are rejected by vector distance <= 0.32 guard without DB mutation."""
    active_before = db_fixture.ledger.get_active_program()
    first_day = active_before.days[0]
    target_ex = first_day.exercises[0]

    state: AssistantState = {
        "messages": [HumanMessage(content=f"swap {target_ex.exercise_name} for pizza")],
        "trainee_id": "default",
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": None,
        "intent": "exercise_substitution",
        "intent_metadata": {
            "mode": "direct_swap",
            "source_exercise": target_ex.exercise_name,
            "target_exercise": "pizza",
        },
        "active_intents": None,
        "program_updated": False,
        "response_content": None,
    }

    res = exercise_substitution_node(state, {"configurable": {"ledger": db_fixture.ledger, "store": db_fixture}})
    assert res["program_updated"] is False
    assert "could not find a biomechanically suitable match" in res["response_content"].lower()

    # Check database program slot is still the original exercise
    active_after = db_fixture.ledger.get_active_program()
    reloaded_ex = active_after.days[0].exercises[0]
    assert reloaded_ex.exercise_name == target_ex.exercise_name


def test_fuzzy_threshold_elevation(db_fixture):
    """Verifies that SequenceMatcher ratio < 0.70 rejects random movement names cleanly."""
    state: AssistantState = {
        "messages": [HumanMessage(content="swap flying pterodactyl for cable fly")],
        "trainee_id": "default",
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": None,
        "intent": "exercise_substitution",
        "intent_metadata": {
            "mode": "direct_swap",
            "source_exercise": "flying pterodactyl",
            "target_exercise": "cable fly",
        },
        "active_intents": None,
        "program_updated": False,
        "response_content": None,
    }

    res = exercise_substitution_node(state, {"configurable": {"ledger": db_fixture.ledger, "store": db_fixture}})
    assert res["program_updated"] is False
    assert "could not identify" in res["response_content"].lower()
    assert "active movements:" in res["response_content"].lower()


def test_multiple_selected_tools_read_history_and_apply_a_swap(db_fixture):
    """Verifies compound query combining exercise history and exercise substitution."""
    active_prog = db_fixture.ledger.get_active_program()
    press_slots = [ex for day in active_prog.days for ex in day.exercises if "press" in ex.exercise_name.lower()]
    assert press_slots, "seeded program composition must contain a press slot for this composite swap"
    first_ex = press_slots[0]

    import uuid
    from datetime import datetime, UTC

    now = datetime.now(UTC).isoformat()
    session_id = str(uuid.uuid4())
    db_fixture.ledger.log_workout_session(
        session_id=session_id,
        session_date="2026-09-15",
        split_name="Upper",
        started_at=now,
        completed_at=now,
    )
    db_fixture.ledger.log_workout_set(
        set_id=str(uuid.uuid4()),
        session_id=session_id,
        exercise_id=str(first_ex.exercise_id),
        set_index=1,
        weight_kg=100.0,
        reps=8,
        rpe=8.5,
    )

    query = f"How did I do on {first_ex.exercise_name} and swap {first_ex.exercise_name} for dumbbell press"
    state: AssistantState = {
        "messages": [HumanMessage(content=query)],
        "trainee_id": "default",
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": None,
        "intent": None,
        "intent_metadata": {},
        "active_intents": None,
        "program_updated": False,
        "response_content": None,
    }

    from agent.player_action_tools import build_player_chat_tools, run_player_chat_tool_calls
    import json

    tools, definitions = build_player_chat_tools(state, {"configurable": {
        "ledger": db_fixture.ledger, "store": db_fixture,
    }})
    messages, _metrics = run_player_chat_tool_calls([
        {"name": "get_exercise_history", "args": {"exercise_name": first_ex.exercise_name}, "id": "history"},
        {"name": "substitute_exercise", "args": {"source_exercise": first_ex.exercise_name,
            "target_exercise": "dumbbell press"}, "id": "swap"},
    ], tools=tools, definitions=definitions, language="en")

    assert "100" in messages[0].content
    assert json.loads(messages[1].content)["program_updated"] is True
    assert state["tool_action_result"]["program_updated"] is True

def test_multiple_swap_text_passes_through_the_safety_gate(db_fixture):
    """Non-safety requests stay intact for the model to handle with selected tools."""
    active_prog = db_fixture.ledger.get_active_program()
    ex1 = active_prog.days[0].exercises[0]
    ex2 = active_prog.days[0].exercises[1]

    query = f"swap {ex1.exercise_name} for cable fly and swap {ex2.exercise_name} for push up"
    state: AssistantState = {
        "messages": [HumanMessage(content=query)],
        "trainee_id": "default",
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": None,
        "intent": None,
        "intent_metadata": {},
        "active_intents": None,
        "program_updated": False,
        "response_content": None,
    }

    route = router_node(state, {"configurable": {"ledger": db_fixture.ledger, "store": db_fixture}})
    assert route["intent"] == "coaching_qa"
    assert state["messages"][-1].content == query

def test_banned_movement_preempts_history_question(db_fixture):
    """Verifies a query with banned movement and exercise history."""
    query = "Can I do behind-the-neck press and how did I do on squats?"
    state: AssistantState = {
        "messages": [HumanMessage(content=query)],
        "trainee_id": "default",
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": None,
        "intent": None,
        "intent_metadata": {},
        "active_intents": None,
        "program_updated": False,
        "response_content": None,
    }

    route = router_node(state, {"configurable": {"ledger": db_fixture.ledger, "store": db_fixture}})
    assert route["intent"] == "banned_movement"
    chunks = list(stream_assistant_turn(state, ledger=db_fixture.ledger, store=db_fixture))
    assert "VETO: Behind-the-neck" in "".join(chunks)
    assert state["program_updated"] is False

def test_streaming_banned_movement_preempts_history_question(db_fixture):
    """The safety gate vetoes a banned movement before the model sees the turn."""
    query = "Can I do behind-the-neck press and how did I do on bench press?"
    state: dict = {
        "messages": [HumanMessage(content=query)],
        "trainee_id": "default",
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": None,
    }

    chunks = list(stream_assistant_turn(state, ledger=db_fixture.ledger, store=db_fixture))
    full_output = "".join(chunks)
    assert "VETO: Behind-the-neck" in full_output
    assert state.get("intent") == "banned_movement"


def _isolated_turn(graph, query, mode):
    request = {"messages": [HumanMessage(content=query)], "telemetry_context": "Recorded session.", "intent_metadata": {}}
    if mode == "graph":
        result = graph.assistant_graph.invoke(request, config={"configurable": {"ledger": graph.db, "store": graph.db}})
        return result["response_content"], result
    display = "".join(graph.stream_assistant_turn(request, ledger=graph.db, store=graph.db))
    assert display == request["response_content"] == request["messages"][-1].content
    return display, request


@pytest.mark.parametrize("mode", ["graph", "stream"])
def test_isolated_gen_qa_04_coherent_veto(graph, mode):
    query = "My gym partner told me to do heavy close-grip barbell upright rows to blow up my side delts. Should I add them?"
    display, result = _isolated_turn(graph, query, mode)
    assert display.count("VETO:") == 1
    assert "upright rows" in display
    assert "cable lateral raises" in display
    assert "---" not in display
    assert result["program_updated"] is False
    assert graph.llm.calls == []
    graph.generate_program_pipeline.assert_not_called()
    graph.db.save_training_program.assert_not_called()
    graph.db.clear_chat_history.assert_not_called()


@pytest.mark.parametrize("mode", ["graph", "stream"])
@pytest.mark.parametrize("clinical_clause", ["my arm feels strange", "I felt sharp pain in my shoulder"])
def test_isolated_clinical_subintent_dominates_entire_turn(graph, mode, clinical_clause):
    graph.evaluate_clinical_semantic_guard.side_effect = lambda text, **kwargs: (text.strip(" .?!") == clinical_clause, 0.91)
    query = f"switch routine to 3 days; swap bench press for incline press; {clinical_clause}; how many reps for curls?"
    display, result = _isolated_turn(graph, query, mode)
    assert display == graph.finalize_coach_output(graph.CLINICAL_SAFEGUARD_RESPONSE)
    assert result["program_updated"] is False
    assert graph.llm.calls == []
    graph.generate_program_pipeline.assert_not_called()
    graph.db.save_training_program.assert_not_called()
    graph.db.clear_chat_history.assert_not_called()
    graph.db.set_assistant_memory.assert_not_called()


def test_safety_gate_preflights_the_whole_request_before_model_actions(graph):
    clinical = "my arm feels strange"
    graph.evaluate_clinical_semantic_guard.side_effect = lambda text, **kwargs: (text == clinical, 0.92)
    query = f"switch routine to 3 days; swap bench press for incline press; {clinical}"
    display, result = _isolated_turn(graph, query, "stream")
    assert display == graph.CLINICAL_SAFEGUARD_RESPONSE
    assert result["program_updated"] is False
    assert graph.llm.calls == []
    graph.db.save_training_program.assert_not_called()

@pytest.mark.parametrize("mode", ["graph", "stream"])
def test_isolated_veto_preempts_the_entire_turn(graph, mode):
    query = "Should I do upright rows? How many reps should I use for squats?"
    display, result = _isolated_turn(graph, query, mode)
    assert "VETO:" in display
    assert result["program_updated"] is False
    assert graph.llm.calls == []

def test_non_safety_compound_requests_are_handed_to_the_model_intact(graph):
    query = "show me exercises for chest; should I use the second one?"
    request = {"messages": [HumanMessage(content=query)], "intent_metadata": {}}
    route = graph.router_node(request, {"configurable": {"ledger": graph.db, "store": graph.db}})
    assert route["intent"] == "coaching_qa"
    assert request["messages"][-1].content == query
