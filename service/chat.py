"""Dialogue-history helpers and assistant-turn entry points."""

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from agent.chat_markers import chat_message_kind
from service._base import ledger_scope


def get_history(db: Any, trainee_id: str, ledger: Any | None = None) -> list[dict[str, Any]]:
    with ledger_scope(db, ledger, trainee_id) as ledger:
        history = ledger.get_chat_history()
        # Label the session-commit pointer as a debrief so the client renders it
        # distinctly without re-deriving the wording (ADR 036).
        for message in history:
            message["kind"] = chat_message_kind(
                str(message.get("role", "")), str(message.get("content", ""))
            )
        return history


def add_user_message(db: Any, trainee_id: str, content: str, ledger: Any | None = None) -> None:
    with ledger_scope(db, ledger, trainee_id) as ledger:
        ledger.add_chat_message("user", content)


def prepare_user_turn(db: Any, content: str, ledger: Any) -> list[dict[str, Any]]:
    """Persists a user turn idempotently and returns the full history to run against.

    A turn persists the user message *before* the model runs, so a failed turn
    leaves it unanswered in the ledger. Retrying that exact message must not
    insert a second user row: when the most recent stored message is a ``user``
    message with identical content and no assistant reply follows it, the turn
    runs against the existing history instead. Reusing the stored row also
    means the retried turn sees the same tail context as the original attempt.
    """
    history = ledger.get_chat_history()
    if history and history[-1]["role"] == "user" and history[-1]["content"] == content:
        return history
    ledger.add_chat_message("user", content)
    return history + [{"role": "user", "content": content}]


def clear_history(db: Any, trainee_id: str, ledger: Any | None = None) -> None:
    with ledger_scope(db, ledger, trainee_id) as ledger:
        ledger.clear_chat_history()


def build_tail_messages(records: list[dict[str, Any]]) -> list:
    tail = []
    for record in records:
        if record["role"] == "user":
            tail.append(HumanMessage(content=record["content"]))
        elif record["role"] == "assistant":
            tail.append(AIMessage(content=record["content"]))
    return tail


def build_turn_state(
    trainee_id: str,
    tail_messages: list,
    coach_tone: str = "Direct, grounded, and pragmatic",
    custom_instructions: str = "",
    player_account_id: str | None = None,
) -> dict[str, Any]:
    return {
        "messages": tail_messages,
        "trainee_id": trainee_id,
        "player_account_id": player_account_id,
        "coach_tone": coach_tone,
        "custom_instructions": custom_instructions,
        "telemetry_context": None,
        "intent": None,
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None,
    }


def persist_assistant_message(ledger: Any, response: str | None) -> None:
    if response:
        ledger.add_chat_message("assistant", response)
