"""Model tool selection and the #718 program-options regression."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent import assistant_graph as graph
from agent.ProgramState import PersistedProgramDaySchema, PersistedProgramExerciseSchema, PersistedProgramSchema
from agent.player_action_tools import build_player_chat_tools, run_player_chat_tool_calls
from agent.program_rules import valid_splits_for
from service.chat_program_edit import plan_chat_program_rebuild
from tests.fakes.chat_model import ScriptedChatModel, ToolCallsTurn


@pytest.fixture
def player_program(fresh_store, editable_catalog_rows):
    ledger = fresh_store.ledger
    ledger.upsert_player_profile({"weekly_frequency": 3, "gender": "male", "equipment_access": "Commercial gym"})
    row = editable_catalog_rows[0]
    exercise = PersistedProgramExerciseSchema(exercise_id=str(row[0]), exercise_name=str(row[1]),
        target_sets=3, target_reps_min=8, target_reps_max=12)
    program = PersistedProgramSchema(program_name="Original", split_type="Full Body", weekly_frequency=5,
        days=[PersistedProgramDaySchema(day_name="Full A", day_order=1, exercises=[exercise])])
    ledger.save_training_program(program.model_dump())
    return fresh_store


def _call(name, args=None):
    return {"name": name, "args": args or {}, "id": "requested-tool"}


def _turn(query):
    return {"messages": [HumanMessage(content=query)], "trainee_id": "default", "player_account_id": None}


def _run(state, store, streaming):
    if streaming:
        list(graph.stream_assistant_turn(state, ledger=store.ledger, store=store))
        return state
    return graph.assistant_graph.invoke(state, config={"configurable": {"ledger": store.ledger, "store": store}})


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("query", [
    "What other 5-day programs are there?",
    "What other program types are available for 5 days",
    "إيه أنواع البرامج التانية المتاحة لخمس أيام؟",
])
def test_718_program_options_reach_the_main_model_and_return_five_day_choices(player_program, monkeypatch, streaming, query):
    store = player_program
    before = store.ledger.get_active_program().model_dump()
    names = [name for _key, name in valid_splits_for(5)]
    model = ScriptedChatModel([ToolCallsTurn(calls=[_call("list_program_options", {"days": 5})]),
                               "; ".join(names) + "."])
    monkeypatch.setattr(graph, "llm", model)

    result = _run(_turn(query), store, streaming)

    assert all(name in result["response_content"] for name in names)
    tool_results = [json.loads(message.content) for message in model.calls[-1]["messages"]
                    if isinstance(message, ToolMessage) and message.name == "list_program_options"]
    assert len(tool_results) == 1
    options = tool_results[0]
    assert options["days"] == 5
    assert {row["split_type"] for row in options["options"]} == {
        "full_body", "upper_lower", "anterior_posterior", "arnold_x_ul", "ppl_x_ul",
    }
    assert all(row["suits"] for row in options["options"])
    assert result["selected_tools"] == ["list_program_options"]
    assert store.ledger.get_active_program().model_dump() == before
    assert store.ledger.get_pending_chat_program_edit() is None


def test_program_options_default_to_active_days_without_changing_saved_frequency(player_program):
    store = player_program
    tools, _definitions = build_player_chat_tools(_turn("What other programs can I choose?"),
        {"configurable": {"ledger": store.ledger, "store": store}})
    result = json.loads(next(tool for tool in tools if tool.name == "list_program_options").invoke({}))

    assert result["days"] == 5
    assert len(result["options"]) == 5
    assert store.ledger.get_player_profile()["weekly_frequency"] == 3


@pytest.mark.parametrize(("query", "tool_name", "args"), [
    ("What did I eat yesterday?", "get_player_food_log", {"day": "yesterday"}),
    ("What are my Nutrition targets?", "get_player_nutrition", {}),
    ("How did I do in my last workout?", "get_exercise_history", {}),
    ("What does my fatigue telemetry say?", "get_player_telemetry", {}),
    ("Find exercises for chest", "search_exercises", {"query": "bench press"}),
])
def test_previous_forced_read_paths_are_chosen_by_the_main_model(player_program, monkeypatch, query, tool_name, args):
    model = ScriptedChatModel([ToolCallsTurn(calls=[_call(tool_name, args)]), "Checked the available data."])
    monkeypatch.setattr(graph, "llm", model)

    result = _run(_turn(query), player_program, False)

    assert result["response_content"] == "Checked the available data."
    assert result["selected_tools"] == [tool_name]
    assert any(isinstance(message, ToolMessage) and message.name == tool_name for message in model.calls[-1]["messages"])


@pytest.mark.parametrize(("query", "expected"), [
    ("I have sharp pain in my shoulder; rebuild my program", "clinical_intercept"),
    ("Add upright rows to my program", "banned_movement"),
])
def test_safety_preempts_model_tools_and_leaves_program_unchanged(player_program, monkeypatch, query, expected):
    monkeypatch.setattr(graph, "llm", ScriptedChatModel([AssertionError("Safety must precede the model")]))
    version = player_program.ledger.get_active_program().version

    result = _run(_turn(query), player_program, True)

    assert result["intent"] == expected
    assert result["response_content"] != graph.PIPELINE_ERROR_RESPONSE
    assert not result["program_updated"]
    assert result["selected_tools"] == []
    assert player_program.ledger.get_active_program().version == version


@pytest.mark.parametrize("query", ["yes", "What other 5-day programs are there?"])
def test_confirmation_tool_cannot_save_without_a_current_offer(player_program, query):
    store = player_program
    state = _turn(query)
    tools, definitions = build_player_chat_tools(state, {"configurable": {"ledger": store.ledger, "store": store}})
    version = store.ledger.get_active_program().version

    messages, _metrics = run_player_chat_tool_calls([_call("confirm_program_edit")],
        tools=tools, definitions=definitions, language="en")

    assert json.loads(messages[0].content)["status"] == "no_current_preview"
    assert store.ledger.get_active_program().version == version


def test_rebuild_uses_separate_confirmation_and_saves_one_version(player_program, monkeypatch):
    store = player_program
    active = store.ledger.get_active_program()
    rebuilt = active.model_copy(update={"program_name": "Reviewed rebuild", "weekly_frequency": 1})
    planned = plan_chat_program_rebuild(store, store.ledger, None, rebuilt)
    offer = "Program rebuild preview. Confirm or cancel."
    store.ledger.set_pending_chat_program_edit(planned["proposal"], offer)
    assert store.ledger.get_active_program().version == active.version
    state = {**_turn("yes"), "messages": [AIMessage(content=offer), HumanMessage(content="yes")]}
    monkeypatch.setattr(graph, "llm", ScriptedChatModel([ToolCallsTurn(calls=[_call("confirm_program_edit")])]))

    result = _run(state, store, True)

    assert result["program_updated"] is True
    saved = store.ledger.get_active_program()
    assert saved.version == active.version + 1
    assert saved.program_name == "Reviewed rebuild"
    assert saved.weekly_frequency == 1
    assert store.ledger.get_pending_chat_program_edit() is None


def test_model_rebuild_tool_prepares_a_preview_without_writing_the_program(player_program, monkeypatch):
    store = player_program
    active = store.ledger.get_active_program()
    model = ScriptedChatModel([ToolCallsTurn(content="I can prepare that preview.", calls=[
        _call("preview_program_rebuild", {"days": 5, "split_type": "ppl_x_ul"}),
    ])])
    monkeypatch.setattr(graph, "llm", model)

    result = _run(_turn("Please rebuild my program as PPL × UL for five days"), store, True)

    pending = store.ledger.get_pending_chat_program_edit()
    assert pending is not None
    assert pending["proposal"]["rebuild_frequency"] == 5
    assert len(pending["proposal"]["preview_days"]) == 5
    assert pending["offer_text"] == result["response_content"]
    assert result["program_edit_preview"]["id"] == pending["offer_id"]
    assert result["program_updated"] is False
    assert store.ledger.get_active_program().version == active.version


def test_substitution_tool_keeps_code_authorization_for_questions(player_program):
    store = player_program
    active = store.ledger.get_active_program()
    source = active.days[0].exercises[0].exercise_name
    state = _turn(f"Should I swap {source} for another exercise?")
    tools, definitions = build_player_chat_tools(state, {"configurable": {"ledger": store.ledger, "store": store}})

    run_player_chat_tool_calls([_call("substitute_exercise", {"source_exercise": source, "target_exercise": "bench press"})],
        tools=tools, definitions=definitions, language="en")

    assert state["tool_action_result"]["program_updated"] is False
    assert store.ledger.get_active_program().version == active.version


def test_rebuild_tool_keeps_coach_program_authority_in_code(player_program, monkeypatch):
    store = player_program
    ledger = store.ledger
    ledger.save_training_program(ledger.get_active_program().model_dump(),
                                 published_by_coach_account_id="publishing-coach")
    active = ledger.get_active_program()
    # Registry lookup is an external authorization boundary; Program state is real.
    monkeypatch.setattr(store, "get_active_assignment_for_player", lambda _account_id: {
        "coach_account_id": "publishing-coach", "started_at": "2000-01-01T00:00:00",
    })
    state = {**_turn("Rebuild my program for four days"), "player_account_id": "player-account"}
    tools, definitions = build_player_chat_tools(state, {"configurable": {"ledger": ledger, "store": store}})

    run_player_chat_tool_calls([_call("preview_program_rebuild", {"days": 4, "split_type": "upper_lower"})],
        tools=tools, definitions=definitions, language="en")

    result = state["tool_action_result"]
    assert result["program_updated"] is False
    assert result["request_suggestion"]["desired_weekly_frequency"] == 4
    assert ledger.get_pending_chat_program_edit() is None
    assert ledger.get_active_program().version == active.version
