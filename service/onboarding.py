"""Onboarding intake steps over the onboarding graph."""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from database.ledger.onboarding import OnboardingAnalyticsStart
from langchain_core.messages import HumanMessage
from service import analytics
from service.keyed_locks import KeyedLocks

_ONBOARDING_LOCKS = KeyedLocks()
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OnboardingCompletionAnalytics:
    duration_seconds: int
    prefilled_fields_count: int
    first_completion: bool


def mark_onboarding_started(ledger: Any) -> OnboardingAnalyticsStart | None:
    """Persists the first committed onboarding write time for event timing."""
    try:
        return ledger.start_onboarding_analytics(datetime.now(UTC).isoformat())
    except sqlite3.Error:
        logger.exception("Could not persist onboarding analytics start time; onboarding continues.")
        return None


def _onboarding_duration_seconds(started_at: str) -> int | None:
    try:
        started = datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid onboarding start time for analytics.")
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - started.astimezone(UTC)).total_seconds()))


def _prefilled_fields_count(answers: dict[str, dict[str, Any]], legacy_state: dict[str, Any] | None) -> int:
    if answers:
        return sum(1 for answer in answers.values() if answer["prefilled"])
    from service.intake import legacy_prefill

    return len(legacy_prefill(legacy_state))


def record_onboarding_completion(
    ledger: Any,
    answers: dict[str, dict[str, Any]],
    legacy_state: dict[str, Any] | None = None,
) -> OnboardingCompletionAnalytics | None:
    """Persists the one-time completion fact and returns safe event properties."""
    try:
        started_at = ledger.get_onboarding_analytics_started_at()
        if started_at is None:
            return None
        duration_seconds = _onboarding_duration_seconds(started_at)
        if duration_seconds is None:
            return None
        prefilled_fields_count = _prefilled_fields_count(answers, legacy_state)
        first_completion = ledger.mark_onboarding_analytics_completed(datetime.now(UTC).isoformat())
    except sqlite3.Error:
        logger.exception("Could not persist onboarding analytics completion; onboarding continues.")
        return None
    return OnboardingCompletionAnalytics(duration_seconds, prefilled_fields_count, first_completion)


def _onboarding_lock(ledger_id: str) -> threading.Lock:
    """Get process-local coordination; production uses one Uvicorn worker for SQLite."""
    return _ONBOARDING_LOCKS.get(ledger_id)


def _graph_config(db: Any, ledger: Any) -> dict[str, Any]:
    """Carries the explicit ledger/store on the LangGraph run config (ADR 041)."""
    return {"configurable": {"ledger": ledger, "store": db}}


def start_onboarding(
    db: Any,
    ledger_id: str,
    player_account_id: str | None = None,
    ledger: Any | None = None,
    *,
    scope: Any | None = None,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> dict[str, Any]:
    from agent.onboarding_graph import onboarding_graph
    from service._base import ledger_scope
    from svc.llm import InferenceScope, run_inference_sync

    clean_id = db._sanitize_username(ledger_id)
    with ledger_scope(db, ledger, clean_id) as handle:
        state = {"messages": [], "trainee_id": clean_id, "intake_step": 1, "is_complete": False, "profile_data": None}
        inference_scope = scope or InferenceScope(
            account_id=player_account_id,
            role="player",
            purpose="onboarding",
            store=db,
            client=client,
        )
        return run_inference_sync(
            onboarding_graph.invoke,
            state,
            config=_graph_config(db, handle),
            scope=inference_scope,
        )


def answer_intake(
    db: Any,
    ledger_id: str,
    state: dict[str, Any],
    user_input: str,
    player_account_id: str | None = None,
    ledger: Any | None = None,
    *,
    scope: Any | None = None,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> dict[str, Any]:
    from agent.onboarding_graph import onboarding_graph
    from service._base import ledger_scope
    from svc.llm import InferenceScope, run_inference_sync

    clean_id = db._sanitize_username(ledger_id)
    with ledger_scope(db, ledger, clean_id) as handle:
        state["messages"].append(HumanMessage(content=user_input))
        state["trainee_id"] = clean_id
        inference_scope = scope or InferenceScope(
            account_id=player_account_id,
            role="player",
            purpose="onboarding",
            store=db,
            client=client,
        )
        output = run_inference_sync(
            onboarding_graph.invoke,
            state,
            config=_graph_config(db, handle),
            scope=inference_scope,
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


def _resolve_onboarding_program(
    db: Any,
    ledger: Any,
    player_account_id: str | None,
    client: analytics.ClientContext,
    emit_program_analytics: bool,
) -> tuple[Any, str, bool]:
    from agent.program_generator import generate_program_pipeline
    from service.programs import COACH_CONTROLLED_ERROR, ensure_active_program, player_controls_program

    had_program = ledger.get_active_program() is not None
    program = ensure_active_program(
        db,
        ledger.ledger_id,
        player_account_id=player_account_id,
        ledger=ledger,
        trigger="onboarding",
        emit_analytics=emit_program_analytics,
        client=client,
    )
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
    return program, program_message, not had_program and program is not None


def complete_onboarding(
    db: Any,
    ledger_id: str,
    state: dict[str, Any],
    player_account_id: str | None = None,
    ledger: Any | None = None,
    *,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
    emit_program_analytics: bool = True,
    scope: Any | None = None,
) -> dict[str, Any]:
    from svc.llm import InferenceScope, run_inference_sync

    from service._base import ledger_scope

    with ledger_scope(db, ledger, ledger_id) as ledger:
        # Keep duplicate completions out of the inference gate while they wait here.
        with _onboarding_lock(ledger.ledger_id):
            inference_scope = scope or InferenceScope(
                account_id=player_account_id,
                role="player",
                purpose="onboarding_complete",
                store=db,
                client=client,
            )
            program, program_message, program_generated = run_inference_sync(
                _resolve_onboarding_program,
                db,
                ledger,
                player_account_id,
                client,
                emit_program_analytics,
                scope=inference_scope,
            )
        if program is None:
            return {
                "program": None,
                "state": state,
                "program_message": program_message,
                "program_generated": False,
            }
        return {"program": program, "state": state, "program_generated": program_generated}
