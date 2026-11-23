"""#757: an identical model tool call reuses this turn's context pre-read."""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.assistant_graph import _split_preread_tool_calls


def _turn_with_preread():
    preread_call = {"name": "get_player_nutrition", "args": {"day": "today"}, "id": "context-1", "type": "tool_call"}
    return [
        HumanMessage(content="what are my targets today?"),
        AIMessage(content="", tool_calls=[preread_call]),
        ToolMessage(content='{"status": "ok"}', tool_call_id="context-1", name="get_player_nutrition"),
    ]


def test_identical_call_reuses_the_preread_under_its_own_id():
    call = {"name": "get_player_nutrition", "args": {"day": "today"}, "id": "call-7", "type": "tool_call"}

    reused, remaining = _split_preread_tool_calls(_turn_with_preread(), [call])

    assert remaining == []
    assert reused["call-7"].content == '{"status": "ok"}'
    assert reused["call-7"].tool_call_id == "call-7"


def test_different_arguments_or_tool_still_run():
    other_day = {"name": "get_player_nutrition", "args": {"day": "yesterday"}, "id": "a", "type": "tool_call"}
    other_tool = {"name": "get_player_food_log", "args": {"day": "today"}, "id": "b", "type": "tool_call"}

    reused, remaining = _split_preread_tool_calls(_turn_with_preread(), [other_day, other_tool])

    assert reused == {}
    assert remaining == [other_day, other_tool]


def test_an_earlier_model_call_is_not_treated_as_a_preread():
    model_call = {"name": "get_player_nutrition", "args": {}, "id": "call-1", "type": "tool_call"}
    messages = [
        HumanMessage(content="targets?"),
        AIMessage(content="", tool_calls=[model_call]),
        ToolMessage(content='{"status": "ok"}', tool_call_id="call-1", name="get_player_nutrition"),
    ]
    again = {**model_call, "id": "call-2"}

    reused, remaining = _split_preread_tool_calls(messages, [again])

    assert reused == {} and remaining == [again]
