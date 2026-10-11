"""Deterministic first-program creation and onboarding analytics."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from database.ledger.onboarding import OnboardingAnalyticsStart

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


def _prefilled_fields_count(answers: dict[str, dict[str, Any]]) -> int:
    return sum(1 for answer in answers.values() if answer["prefilled"])


def record_onboarding_completion(
    ledger: Any,
    answers: dict[str, dict[str, Any]],
) -> OnboardingCompletionAnalytics | None:
    """Persists the one-time completion fact and returns safe event properties."""
    try:
        started_at = ledger.get_onboarding_analytics_started_at()
        if started_at is None:
            return None
        duration_seconds = _onboarding_duration_seconds(started_at)
        if duration_seconds is None:
            return None
        prefilled_fields_count = _prefilled_fields_count(answers)
        first_completion = ledger.mark_onboarding_analytics_completed(datetime.now(UTC).isoformat())
    except sqlite3.Error:
        logger.exception("Could not persist onboarding analytics completion; onboarding continues.")
        return None
    return OnboardingCompletionAnalytics(duration_seconds, prefilled_fields_count, first_completion)


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
        emit_analytics=False,
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
    player_account_id: str | None = None,
    ledger: Any | None = None,
) -> dict[str, Any]:
    from service._base import ledger_scope

    with ledger_scope(db, ledger, ledger_id) as ledger:
        program, program_message, program_generated = _resolve_onboarding_program(
            db, ledger, player_account_id
        )
        if program is None:
            return {
                "program": None,
                "program_message": program_message,
                "program_generated": False,
            }
        return {"program": program, "program_generated": program_generated}
