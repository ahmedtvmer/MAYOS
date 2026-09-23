"""Dialogue-history helpers and assistant-turn entry points."""

from typing import Any, Generator

from langchain_core.messages import AIMessage, HumanMessage


def get_history(db: Any, trainee_id: str) -> list[dict[str, Any]]:
    from service._base import bind_user

    bind_user(db, trainee_id)
    return db.get_chat_history()


def add_user_message(db: Any, trainee_id: str, content: str) -> None:
    from service._base import bind_user

    bind_user(db, trainee_id)
    db.add_chat_message("user", content)


def clear_history(db: Any, trainee_id: str) -> None:
    from service._base import bind_user

    bind_user(db, trainee_id)
    db.clear_chat_history()


def build_tail_messages(records: list[dict[str, Any]]) -> list:
    tail = []
    for record in records:
        if record["role"] == "user":
            tail.append(HumanMessage(content=record["content"]))
        elif record["role"] == "assistant":
            tail.append(AIMessage(content=record["content"]))
    return tail


def build_turn_state(
    db: Any,
    trainee_id: str,
    tail_messages: list,
    coach_tone: str = "Direct, grounded, and pragmatic",
    custom_instructions: str = "",
) -> dict[str, Any]:
    return {
        "messages": tail_messages,
        "trainee_id": trainee_id,
        "coach_tone": coach_tone,
        "custom_instructions": custom_instructions,
        "telemetry_context": None,
        "intent": None,
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None,
    }


def stream_turn(state: dict[str, Any]) -> Generator[str, None, None]:
    from agent.assistant_graph import stream_assistant_turn
    from svc.llm import bound_stream

    yield from bound_stream(stream_assistant_turn, state)


def persist_assistant_message(db: Any, response: str | None) -> None:
    if response:
        db.add_chat_message("assistant", response)
