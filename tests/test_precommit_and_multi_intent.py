# tests/test_precommit_and_multi_intent.py
from __future__ import annotations

import random
import shutil
import threading
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
composite_intent_node = _real_handler("composite_intent_node")
exercise_substitution_node = _real_handler("exercise_substitution_node")
program_mutation_node = _real_handler("program_mutation_node")
stream_assistant_turn = _real_handler("stream_assistant_turn")


@pytest.fixture
def db_fixture(tmp_path, monkeypatch):
    from agent import assistant_graph, program_generator, program_rules
    from database.database_manager import DEFAULT_CATALOG_PATH, DatabaseManager

    catalog_path = tmp_path / "catalog.db"
    shutil.copyfile(DEFAULT_CATALOG_PATH, catalog_path)
    monkeypatch.setattr(DatabaseManager, "_instance", None)
    monkeypatch.setattr(DatabaseManager, "_local", threading.local())
    db = DatabaseManager(
        catalog_path=catalog_path,
        users_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        active_user="default",
    )
    try:
        for module in (assistant_graph, program_generator, program_rules):
            monkeypatch.setattr(module, "db", db)
        profile = {
            "gender": "male",
            "proportions": "balanced",
            "experience": "intermediate",
            "equipment": "commercial_gym",
            "target_frequency": 4,
            "primary_goal": "hypertrophy",
            "coach_tone": "Direct, grounded, and pragmatic",
        }
        db.upsert_user_profile(profile)
        random.seed(11)
        program_generator.generate_program_pipeline(user_split_override=None, frequency_override=4)
        yield db
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def test_inquisitive_mutation_guard(db_fixture):
    """Verifies that hypothetical/inquisitive questions do not wipe or mutate the routine."""
    active_before = db_fixture.get_active_program()
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
        res = router_node(state)
        # Must NOT be classified as program_mutation
        assert res.get("intent") != "program_mutation", f"Query '{query}' was incorrectly classified as program_mutation"

        # Defense-in-depth: Even if passed to program_mutation_node directly, it should reject
        mutation_res = program_mutation_node(state)
        assert mutation_res["program_updated"] is False
        assert "explicit directive" in mutation_res["response_content"].lower()

    # Verify database program was completely untouched
    active_after = db_fixture.get_active_program()
    assert active_after.program_name == active_before.program_name
    assert active_after.weekly_frequency == active_before.weekly_frequency


def test_invalid_exercise_swap_guard(db_fixture):
    """Verifies that non-exercises (e.g. 'pizza') are rejected by vector distance <= 0.32 guard without DB mutation."""
    active_before = db_fixture.get_active_program()
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

    res = exercise_substitution_node(state)
    assert res["program_updated"] is False
    assert "could not find a biomechanically suitable match" in res["response_content"].lower()

    # Check database program slot is still the original exercise
    active_after = db_fixture.get_active_program()
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

    res = exercise_substitution_node(state)
    assert res["program_updated"] is False
    assert "could not identify" in res["response_content"].lower()
    assert "active movements:" in res["response_content"].lower()


def test_composite_intent_history_and_swap(db_fixture):
    """Verifies compound query combining exercise history and exercise substitution."""
    active_prog = db_fixture.get_active_program()
    press_slots = [ex for day in active_prog.days for ex in day.exercises if "press" in ex.exercise_name.lower()]
    assert press_slots, "seeded program composition must contain a press slot for this composite swap"
    first_ex = press_slots[0]

    import uuid
    from datetime import datetime, UTC

    now = datetime.now(UTC).isoformat()
    session_id = str(uuid.uuid4())
    db_fixture.log_workout_session(
        session_id=session_id,
        session_date="2026-09-15",
        split_name="Upper",
        started_at=now,
        completed_at=now,
    )
    db_fixture.log_workout_set(
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

    route_res = router_node(state)
    assert route_res["intent"] == "composite_intent"
    sub_intents = route_res["intent_metadata"]["sub_intents"]
    assert len(sub_intents) == 2
    assert sub_intents[0]["intent"] == "exercise_history"
    assert sub_intents[1]["intent"] == "exercise_substitution"

    state.update(route_res)
    comp_res = composite_intent_node(state)

    assert comp_res["program_updated"] is True
    assert "---" in comp_res["response_content"]
    assert "last logged session" in comp_res["response_content"].lower()
    assert "routine slot updated" in comp_res["response_content"].lower()


def test_composite_intent_multiple_swaps(db_fixture):
    """Verifies two exercise substitutions processed together in one prompt."""
    active_prog = db_fixture.get_active_program()
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

    route_res = router_node(state)
    assert route_res["intent"] == "composite_intent"
    sub_intents = route_res["intent_metadata"]["sub_intents"]
    assert len(sub_intents) == 2
    assert all(s["intent"] == "exercise_substitution" for s in sub_intents)


def test_composite_intent_banned_and_history(db_fixture):
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

    route_res = router_node(state)
    assert route_res["intent"] == "composite_intent"
    state.update(route_res)
    comp_res = composite_intent_node(state)

    assert "VETO: Behind-the-neck" in comp_res["response_content"]
    assert "---" in comp_res["response_content"]


def test_composite_streaming_turn(db_fixture):
    """Verifies stream_assistant_turn successfully streams composite_intent output."""
    query = "Can I do behind-the-neck press and how did I do on bench press?"
    state: dict = {
        "messages": [HumanMessage(content=query)],
        "trainee_id": "default",
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": None,
    }

    chunks = list(stream_assistant_turn(state))
    full_output = "".join(chunks)
    assert "VETO: Behind-the-neck" in full_output
    assert "---" in full_output
    assert state.get("intent") == "composite_intent"


def _isolated_turn(graph, query, mode):
    request = {"messages": [HumanMessage(content=query)], "telemetry_context": "Recorded session.", "intent_metadata": {}}
    if mode == "graph":
        result = graph.assistant_graph.invoke(request)
        return result["response_content"], result
    display = "".join(graph.stream_assistant_turn(request))
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
    graph.llm.invoke.assert_not_called()
    graph.generate_program_pipeline.assert_not_called()
    graph.db.swap_program_exercise.assert_not_called()
    graph.db.clear_chat_history.assert_not_called()


@pytest.mark.parametrize("mode", ["graph", "stream"])
@pytest.mark.parametrize("clinical_clause", ["my arm feels strange", "I felt sharp pain in my shoulder"])
def test_isolated_clinical_subintent_dominates_entire_turn(graph, mode, clinical_clause):
    graph.evaluate_clinical_semantic_guard.side_effect = lambda text, **kwargs: (text.strip(" .?!") == clinical_clause, 0.91)
    query = f"switch routine to 3 days; swap bench press for incline press; {clinical_clause}; how many reps for curls?"
    display, result = _isolated_turn(graph, query, mode)
    assert display == graph.finalize_coach_output(graph.CLINICAL_SAFEGUARD_RESPONSE)
    assert result["program_updated"] is False
    graph.llm.invoke.assert_not_called()
    graph.generate_program_pipeline.assert_not_called()
    graph.db.swap_program_exercise.assert_not_called()
    graph.db.clear_chat_history.assert_not_called()
    graph.db.set_assistant_memory.assert_not_called()


@pytest.mark.parametrize("explicit_clinical_intent", [True, False])
def test_isolated_direct_composite_preflights_before_mutations(graph, explicit_clinical_intent):
    clinical = "my arm feels strange"
    graph.evaluate_clinical_semantic_guard.side_effect = lambda text, **kwargs: (text == clinical, 0.92)
    request = {"messages": [HumanMessage(content="process these requests")], "intent_metadata": {"sub_intents": [
        {"intent": "program_mutation", "query": "switch routine to 3 days"},
        {"intent": "exercise_substitution", "query": "swap bench press for incline press"},
        {"intent": "clinical_intercept" if explicit_clinical_intent else "coaching_qa", "query": clinical},
    ]}}
    result = graph.composite_intent_node(request)
    assert result["response_content"] == graph.CLINICAL_SAFEGUARD_RESPONSE
    assert result["program_updated"] is False
    graph.llm.invoke.assert_not_called()
    graph.generate_program_pipeline.assert_not_called()
    graph.db.swap_program_exercise.assert_not_called()
    graph.db.clear_chat_history.assert_not_called()


@pytest.mark.parametrize("mode", ["graph", "stream"])
def test_isolated_veto_preserves_unrelated_question_and_context(graph, mode):
    query = "Should I do upright rows? How many reps should I use for squats?"
    display, result = _isolated_turn(graph, query, mode)
    assert "VETO:" in display and "Use controlled reps." in display
    assert "---" in display
    payload = graph.llm.invoke.call_args.args[0]
    text = "\n".join(message.content for message in payload)
    assert query in text
    assert "VETO:" in text
    assert payload[-1].content == "How many reps should I use for squats"
    assert result["program_updated"] is False


def test_isolated_dependent_clause_keeps_original_and_preceding_response(graph):
    request = {"messages": [HumanMessage(content="show me exercises for chest; should I use the second one?")], "intent_metadata": {"sub_intents": [
        {"intent": "catalog_search", "query": "show me exercises for chest"},
        {"intent": "coaching_qa", "query": "should I use the second one?"},
    ]}}
    graph.catalog_search_node = MagicMock(return_value=graph._response("1. Bench press\n2. Cable fly"))
    graph.composite_intent_node(request)
    text = "\n".join(message.content for message in graph.llm.invoke.call_args.args[0])
    assert request["messages"][0].content in text
    assert "2. Cable fly" in text
    assert "should I use the second one?" in text
    assert len(request["messages"]) == 1


def test_isolated_two_independent_mutations_still_execute(graph):
    query = "switch routine to 3 days; swap bench press for incline press"
    request = {"messages": [HumanMessage(content=query)], "intent_metadata": {}}
    request.update(graph.router_node(request))
    assert request["intent"] == "composite_intent"
    graph.program_mutation_node = MagicMock(return_value=graph._response("Routine rebuilt.", True))
    graph.exercise_substitution_node = MagicMock(return_value=graph._response("Movement replaced.", True))
    result = graph.composite_intent_node(request)
    assert result["program_updated"] is True
    assert "Routine rebuilt." in result["response_content"]
    assert "Movement replaced." in result["response_content"]
    graph.program_mutation_node.assert_called_once()
    graph.exercise_substitution_node.assert_called_once()
