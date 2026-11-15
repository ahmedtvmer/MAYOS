"""#718: bound every provider request, including schemas and repeated history."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.player_action_tools import build_player_chat_tools, select_player_chat_tools
from agent.player_prompt import PromptBudgetError, build_player_chat_prompt
from agent.player_turn_budget import (
    PLAYER_TURN_ESTIMATED_INPUT_TOKEN_LIMIT,
    PLAYER_TURN_INPUT_TOKEN_LIMIT,
    PlayerTurnInputBudget,
    provider_tool_schemas,
)


@pytest.mark.parametrize("component", ["system", "history", "schema", "arguments", "result"])
def test_718_oversized_request_component_is_refused(component):
    oversized = "ع" * PLAYER_TURN_INPUT_TOKEN_LIMIT
    messages = [SystemMessage(content=oversized if component == "system" else "Coach safely."),
                HumanMessage(content=oversized if component == "history" else "Show my last workout.")]
    schemas = [{"type": "function", "function": {"name": "read", "description": oversized,
                "parameters": {"type": "object", "properties": {}}}}] if component == "schema" else []
    if component in {"arguments", "result"}:
        messages.extend([AIMessage(content="", tool_calls=[{"name": "read", "id": "read-1",
            "args": {"query": oversized if component == "arguments" else "bench"}}]),
            ToolMessage(content=oversized if component == "result" else "{}", tool_call_id="read-1")])

    with pytest.raises(PromptBudgetError):
        PlayerTurnInputBudget().admit(messages, schemas)
    with pytest.raises(PromptBudgetError):
        PlayerTurnInputBudget().prepare_request(messages, schemas)


def test_718_individually_small_rounds_cannot_exceed_the_turn_budget():
    budget = PlayerTurnInputBudget()
    messages = [SystemMessage(content="Coach safely."), HumanMessage(content="a" * 4_000)]
    budget.admit(messages)
    for _round in range(30):
        try:
            budget.admit(messages)
        except PromptBudgetError:
            break
    else:
        pytest.fail("Repeated provider rounds escaped the turn input budget")

    assert budget.consumed <= PLAYER_TURN_INPUT_TOKEN_LIMIT


def test_718_transport_retry_reservation_cannot_escape_the_turn_ceiling():
    messages = [HumanMessage(content="a" * 4_000)]
    budget = PlayerTurnInputBudget()
    with pytest.raises(PromptBudgetError):
        budget.admit(messages, attempts=30)


@pytest.mark.parametrize("query", [
    "What do you know about my profile?", "قولّي يا سلمى", "كشفت على ركبتي",
    "عايز أكبر صدري", "نفسي أكبر دراعاتي", "put side delts on leg days",
])
def test_718_all_read_tool_schemas_fit_repeated_turn_estimate(fresh_store, query):
    state = {"messages": [HumanMessage(content=query)]}
    config = {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}}
    tools, _definitions = build_player_chat_tools(state, config)
    messages = build_player_chat_prompt(state)
    budget = PlayerTurnInputBudget()
    selected_tools = select_player_chat_tools(tools, messages, budget)
    read_names = {
        "list_program_options", "get_player_profile", "get_active_program",
        "get_program_rationale", "get_player_weight_trend", "get_player_nutrition",
        "get_player_food_log", "get_assistant_preferences", "search_chat_history",
        "get_exercise_history", "get_player_telemetry", "search_exercises",
    }
    assert read_names <= {tool.name for tool in selected_tools}
    # #718: phrase matching must not hide an operation when the catalog fits.
    assert {tool.name for tool in selected_tools} == {tool.name for tool in tools}
    assert budget == PlayerTurnInputBudget()

    schemas = provider_tool_schemas(selected_tools)
    budget.admit(messages, schemas)
    budget.admit(messages, schemas)

    assert 0 < budget.estimated_consumed <= PLAYER_TURN_ESTIMATED_INPUT_TOKEN_LIMIT
    assert budget.consumed <= PLAYER_TURN_INPUT_TOKEN_LIMIT


@pytest.mark.parametrize("ceiling", ["estimated", "escaped_bytes"])
def test_718_turn_pressure_keeps_all_reads_and_room_for_final_answer(fresh_store, ceiling):
    state = {"messages": [HumanMessage(content="قولّي يا سلمى")]}
    config = {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}}
    tools, _definitions = build_player_chat_tools(state, config)
    read_names = {
        "list_program_options", "get_player_profile", "get_active_program",
        "get_program_rationale", "get_player_weight_trend", "get_player_nutrition",
        "get_player_food_log", "get_assistant_preferences", "search_chat_history",
        "get_exercise_history", "get_player_telemetry", "search_exercises",
    }
    reads = [tool for tool in tools if tool.name in read_names]
    messages = build_player_chat_prompt(state)
    required = PlayerTurnInputBudget()
    required.admit(messages, provider_tool_schemas(reads))
    required.admit(messages)
    budget = PlayerTurnInputBudget(
        consumed=PLAYER_TURN_INPUT_TOKEN_LIMIT - required.consumed if ceiling == "escaped_bytes" else 0,
        estimated_consumed=(PLAYER_TURN_ESTIMATED_INPUT_TOKEN_LIMIT - required.estimated_consumed
                            if ceiling == "estimated" else 0),
    )
    before = (budget.consumed, budget.estimated_consumed)

    selected = select_player_chat_tools(tools, messages, budget)

    assert {tool.name for tool in selected} == read_names
    assert (budget.consumed, budget.estimated_consumed) == before
    budget.admit(messages, provider_tool_schemas(selected))
    budget.admit(messages)
    assert budget.consumed <= PLAYER_TURN_INPUT_TOKEN_LIMIT
    assert budget.estimated_consumed <= PLAYER_TURN_ESTIMATED_INPUT_TOKEN_LIMIT


def test_718_schema_pressure_trims_old_exchanges_but_preserves_current_tool_pairs():
    system = SystemMessage(content="Coach safely.")
    current = [HumanMessage(content="Show my last workout."),
               AIMessage(content="", tool_calls=[{"name": "read", "id": "read-1", "args": {}}]),
               ToolMessage(content="100 kg for 8 reps", tool_call_id="read-1")]
    messages = [system, HumanMessage(content="old question"), AIMessage(content="a" * 32_000), *current]
    schemas = [{"type": "function", "function": {"name": "read", "description": "a" * 12_000,
                "parameters": {"type": "object", "properties": {}}}}]
    with pytest.raises(PromptBudgetError):
        PlayerTurnInputBudget().admit(messages, schemas)

    budget = PlayerTurnInputBudget()
    prepared = budget.prepare_request(messages, schemas)

    assert prepared == [system, *current]
    assert len(messages) == 6
    assert 0 < budget.consumed <= PLAYER_TURN_INPUT_TOKEN_LIMIT
