"""Network-free scripted LangChain chat model used by tests.

Turns are strings or ``AIMessage`` instances for text, Pydantic models or
mappings for structured payloads, ``ToolCallsTurn`` for bound tool responses,
``StructuredValue`` for an explicit prevalidated structured result, or
``StreamErrorTurn`` for partial failures. Text streaming is chunked centrally
by ``chunk_size``.
"""

import json
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field, PrivateAttr


@dataclass(frozen=True)
class ToolCallsTurn:
    """One assistant turn containing one or more parallel tool calls."""

    calls: Sequence[dict[str, Any]]
    content: str = ""


@dataclass(frozen=True)
class StreamErrorTurn:
    """Text emitted before a scripted streaming failure."""

    content: str
    error: BaseException


@dataclass(frozen=True)
class StructuredValue:
    """Inject an already typed structured value to test downstream validation."""

    value: Any


class ScriptedChatModel(BaseChatModel):
    """BaseChatModel fake that records model payloads and consumes scripted turns."""

    chunk_size: int = 12
    max_tokens: int = 200
    model_name: str = "deepseek-ai/DeepSeek-V4-Flash"
    extra_body: dict[str, Any] | None = None
    usage_metadata: dict[str, int] | None = None
    emit_usage: bool = True
    finish_reason: str | None = None
    default_turn: Any = None
    _turns: deque[Any] = PrivateAttr(default_factory=deque)
    _streamed_chunk_count: int = PrivateAttr(default=0)
    calls: list[dict[str, Any]] = Field(default_factory=list)

    def __init__(self, turns: Iterable[Any] = (), **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._turns = deque(turns)
        self.calls = []

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self._llm_type}

    @property
    def streamed_chunk_count(self) -> int:
        return self._streamed_chunk_count

    def reset(self, turns: Iterable[Any] = (), *, default_turn: Any = None) -> None:
        self._turns = deque(turns)
        self.calls.clear()
        self._streamed_chunk_count = 0
        self.default_turn = default_turn

    def script(self, *turns: Any) -> None:
        self._turns.extend(turns)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        schema = kwargs.pop("structured_schema", None)
        mode = "structured" if schema is not None else "invoke"
        if schema is not None:
            kwargs["schema"] = _schema_name(schema)
            kwargs["structured_schema"] = schema
        response = self._next_response(
            messages,
            mode=mode,
            stop=stop,
            **kwargs,
        )
        return ChatResult(generations=[ChatGeneration(message=response)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ):
        self._streamed_chunk_count = 0
        turn = self._next_turn(messages, mode="stream", stop=stop, **kwargs)
        if isinstance(turn, StreamErrorTurn):
            yield from self._text_chunks(turn.content)
            raise turn.error
        response = self._with_metadata(_as_response(turn))
        if response.tool_calls:
            chunks = [
                {
                    "name": call["name"],
                    "args": json.dumps(call["args"]),
                    "id": call["id"],
                    "index": index,
                    "type": "tool_call_chunk",
                }
                for index, call in enumerate(response.tool_calls)
            ]
            self._streamed_chunk_count += 1
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=chunks))
            return
        content = response.content if isinstance(response.content, str) else ""
        yield from self._text_chunks(content)
        if self.emit_usage and response.usage_metadata is not None:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    usage_metadata=response.usage_metadata,
                    response_metadata=response.response_metadata,
                )
            )
        elif response.response_metadata:
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", response_metadata=response.response_metadata)
            )

    def _text_chunks(self, content: str):
        for start in range(0, len(content), max(1, self.chunk_size)):
            self._streamed_chunk_count += 1
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=content[start : start + max(1, self.chunk_size)])
            )

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: str | None = None, **kwargs: Any):
        bound_tools = tuple(tools)
        tool_names = tuple(_tool_name(tool) for tool in bound_tools)
        return RunnableLambda(
            lambda prompt, **call_kwargs: self._next_response(
                _as_messages(prompt),
                mode="tools",
                tools=tool_names,
                bound_tools=bound_tools,
                tool_choice=tool_choice,
                **{**kwargs, **call_kwargs},
            )
        )

    def with_structured_output(self, schema: Any, *, include_raw: bool = False, **kwargs: Any):
        return RunnableLambda(
            lambda prompt, **call_kwargs: self._structured_response(
                self.invoke(
                    _as_messages(prompt),
                    structured_schema=schema,
                    **{**kwargs, **call_kwargs},
                ),
                schema=schema,
                include_raw=include_raw,
            )
        )

    def _structured_response(
        self,
        response: AIMessage,
        *,
        schema: Any,
        include_raw: bool,
    ) -> Any:
        parsed = _parse_structured(response, schema)
        if include_raw:
            return {"raw": response, "parsed": parsed, "parsing_error": None}
        return parsed

    def _next_response(
        self,
        messages: list[BaseMessage],
        *,
        mode: str,
        tools: tuple[str, ...] = (),
        bound_tools: tuple[Any, ...] = (),
        **kwargs: Any,
    ) -> AIMessage:
        turn = self._next_turn(
            messages,
            mode=mode,
            tools=tools,
            bound_tools=bound_tools,
            **kwargs,
        )
        response = self._with_metadata(_as_response(turn))
        return response

    def _with_metadata(self, response: AIMessage) -> AIMessage:
        if self.usage_metadata is not None and self.emit_usage and response.usage_metadata is None:
            response.usage_metadata = self.usage_metadata
        if self.finish_reason and not response.response_metadata.get("finish_reason"):
            response.response_metadata["finish_reason"] = self.finish_reason
        return response

    def _next_turn(self, messages: list[BaseMessage], *, mode: str, **kwargs: Any) -> Any:
        self.calls.append(
            {
                "messages": tuple(messages),
                "mode": mode,
                "tools": kwargs.get("tools", ()),
                "bound_tools": kwargs.get("bound_tools", ()),
                "kwargs": {key: value for key, value in kwargs.items() if key not in {"tools", "bound_tools"}},
            }
        )
        if self._turns:
            turn = self._turns.popleft()
        elif self.default_turn is not None:
            turn = self.default_turn
        else:
            raise AssertionError(f"Scripted chat model has no turn for {mode} call #{len(self.calls)}")
        if isinstance(turn, BaseException):
            raise turn
        return turn


def _as_messages(prompt: Any) -> list[BaseMessage]:
    if isinstance(prompt, str):
        return [HumanMessage(content=prompt)]
    if hasattr(prompt, "to_messages"):
        return list(prompt.to_messages())
    return list(prompt)


def _as_response(turn: Any) -> AIMessage:
    if isinstance(turn, AIMessage):
        return turn
    if isinstance(turn, ToolCallsTurn):
        return AIMessage(content=turn.content, tool_calls=list(turn.calls))
    if isinstance(turn, StructuredValue):
        return AIMessage(content="", additional_kwargs={"scripted_structured_value": turn.value})
    if isinstance(turn, str):
        return AIMessage(content=turn)
    if isinstance(turn, BaseModel):
        return AIMessage(content=turn.model_dump_json())
    if isinstance(turn, dict):
        return AIMessage(content=json.dumps(turn))
    raise TypeError(f"Unsupported scripted chat turn: {type(turn).__name__}")


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name", ""))
    return str(getattr(tool, "name", getattr(tool, "__name__", type(tool).__name__)))


def _schema_name(schema: Any) -> str:
    return getattr(schema, "__name__", str(schema))


def _parse_structured(response: AIMessage, schema: Any) -> Any:
    if "scripted_structured_value" in response.additional_kwargs:
        return response.additional_kwargs["scripted_structured_value"]
    content = response.content
    if isinstance(content, str):
        try:
            payload = json.loads(content)
        except ValueError as error:
            raise ValueError(
                f"Scripted response for {_schema_name(schema)} must contain valid JSON: {error}"
            ) from error
    else:
        payload = content
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        if isinstance(payload, schema):
            return payload
        try:
            return schema.model_validate(payload)
        except Exception as error:
            raise ValueError(
                f"Scripted response does not match structured schema {_schema_name(schema)}: {error}"
            ) from error
    return payload
