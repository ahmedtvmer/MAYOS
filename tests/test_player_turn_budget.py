"""#718: bound every provider request, including schemas and repeated history."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.player_prompt import PromptBudgetError
from agent.player_turn_budget import PLAYER_TURN_INPUT_TOKEN_LIMIT, PlayerTurnInputBudget


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
