import pytest
from pydantic import BaseModel

from langchain_core.messages import HumanMessage
from tests.fakes.chat_model import ScriptedChatModel, ToolCallsTurn


class Review(BaseModel):
    summary: str
    count: int


def test_scripted_model_records_tool_calls_and_stream_chunks():
    model = ScriptedChatModel(
        [
            ToolCallsTurn(
                calls=[
                    {"name": "search_exercises", "args": {"query": "hamstrings"}, "id": "call_1"},
                    {"name": "get_program", "args": {}, "id": "call_2"},
                ]
            ),
            "Here are two options.",
        ],
    )
    tools = [
        {"name": "search_exercises", "description": "Search the Exercise library."},
        {"name": "get_program", "description": "Read the current Training program."},
    ]
    prompt = [HumanMessage(content="Suggest a hamstring exercise.")]

    call = model.bind_tools(tools).invoke(prompt)
    chunks = list(model.stream(prompt))

    assert [tool_call["name"] for tool_call in call.tool_calls] == ["search_exercises", "get_program"]
    assert "".join(chunk.content for chunk in chunks) == "Here are two options."
    assert model.calls[0]["messages"] == tuple(prompt)
    assert model.calls[0]["tools"] == ("search_exercises", "get_program")
    assert model.calls[0]["bound_tools"] == tuple(tools)
    assert model.calls[1]["mode"] == "stream"


def test_scripted_model_returns_structured_output():
    model = ScriptedChatModel([{"summary": "Steady progress", "count": 3}])
    prompt = [HumanMessage(content="Summarize the recent sessions.")]

    result = model.with_structured_output(Review).invoke(prompt)

    assert result == Review(summary="Steady progress", count=3)
    assert model.calls[0]["mode"] == "structured"
    assert model.calls[0]["kwargs"]["schema"] == "Review"


def test_scripted_model_fails_when_script_is_exhausted():
    model = ScriptedChatModel()

    with pytest.raises(AssertionError, match="no turn for invoke call #1"):
        model.invoke("A prompt")


@pytest.mark.parametrize("raw", ["not JSON", "[]"])
def test_scripted_model_rejects_invalid_structured_output(raw):
    model = ScriptedChatModel([raw])

    with pytest.raises(ValueError, match="Scripted response"):
        model.with_structured_output(Review).invoke("A prompt")
