"""Onboarding intake steps over the onboarding graph."""

from __future__ import annotations

import threading
from typing import Any

from langchain_core.messages import HumanMessage
from service.keyed_locks import KeyedLocks

_ONBOARDING_LOCKS = KeyedLocks()


def _onboarding_lock(ledger_id: str) -> threading.Lock:
    """Get process-local coordination; production uses one Uvicorn worker for SQLite."""
    return _ONBOARDING_LOCKS.get(ledger_id)


def _graph_config(db: Any, ledger: Any) -> dict[str, Any]:
    """Carries the explicit ledger/store on the LangGraph run config (ADR 041)."""
    return {"configurable": {"ledger": ledger, "store": db}}


def start_onboarding(
    db: Any, ledger_id: str, player_account_id: str | None = None, ledger: Any | None = None
) -> dict[str, Any]:
    from agent.onboarding_graph import onboarding_graph
    from service._base import ledger_scope
    from svc.llm import InferenceScope, run_inference_sync

    clean_id = db._sanitize_username(ledger_id)
    with ledger_scope(db, ledger, clean_id) as handle:
        state = {"messages": [], "trainee_id": clean_id, "intake_step": 1, "is_complete": False, "profile_data": None}
        return run_inference_sync(
            onboarding_graph.invoke,
            state,
            config=_graph_config(db, handle),
            scope=InferenceScope(
                account_id=player_account_id, role="player", purpose="onboarding", store=db
            ),
        )


def answer_intake(
    db: Any,
    ledger_id: str,
    state: dict[str, Any],
    user_input: str,
    player_account_id: str | None = None,
    ledger: Any | None = None,
) -> dict[str, Any]:
    from agent.onboarding_graph import onboarding_graph
    from service._base import ledger_scope
    from svc.llm import InferenceScope, run_inference_sync

    clean_id = db._sanitize_username(ledger_id)
    with ledger_scope(db, ledger, clean_id) as handle:
        state["messages"].append(HumanMessage(content=user_input))
        state["trainee_id"] = clean_id
        output = run_inference_sync(
            onboarding_graph.invoke,
            state,
            config=_graph_config(db, handle),
            scope=InferenceScope(
                account_id=player_account_id, role="player", purpose="onboarding", store=db
            ),
        )
        state.update(output)
        return state


def _record_welcome_message_once(ledger: Any, message: str) -> None:
    welcome_message = f"Welcome! {message}"
    if any(
        chat_message["role"] == "assistant" and chat_message["content"] == welcome_message
        for chat_message in ledger.get_chat_history()
    ):
        return
    ledger.add_chat_message("assistant", welcome_message)


def _resolve_onboarding_program(db: Any, ledger: Any, player_account_id: str | None) -> tuple[Any, str]:
    from agent.program_generator import generate_program_pipeline
    from service.programs import COACH_CONTROLLED_ERROR, ensure_active_program, player_controls_program

    program = ensure_active_program(db, ledger.ledger_id, player_account_id=player_account_id, ledger=ledger)
    if program is None and player_controls_program(db, ledger, player_account_id):
        program = generate_program_pipeline(ledger=ledger)[0]

    program_message = (
        COACH_CONTROLLED_ERROR
        if program is None
        else f"I have calibrated your active routine: **{program.program_name}** "
        f"({program.weekly_frequency} days/week). Inspect your split in **Program & Dashboard**, "
        "log your work in **Active Workout Logger**, or query me here."
    )
    _record_welcome_message_once(ledger, program_message)
    return program, program_message


def complete_onboarding(
    db: Any,
    ledger_id: str,
    state: dict[str, Any],
    player_account_id: str | None = None,
    ledger: Any | None = None,
) -> dict[str, Any]:
    from svc.llm import InferenceScope, run_inference_sync

    from service._base import ledger_scope

    with ledger_scope(db, ledger, ledger_id) as ledger:
        # Keep duplicate completions out of the inference gate while they wait here.
        with _onboarding_lock(ledger.ledger_id):
            program, program_message = run_inference_sync(
                _resolve_onboarding_program,
                db,
                ledger,
                player_account_id,
                scope=InferenceScope(
                    account_id=player_account_id, role="player", purpose="onboarding_complete", store=db
                ),
            )
        if program is None:
            return {"program": None, "state": state, "program_message": program_message}
        return {"program": program, "state": state}
