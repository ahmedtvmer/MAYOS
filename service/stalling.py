"""Bounded recount of roster stall length (CONTEXT.md "Stalling", #203)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# One bounded look-back keeps each commit hook's ledger scan predictable.
STALL_LOOKBACK_SESSIONS = 500


def _session_order(session: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(session.get("session_date") or ""),
        str(session.get("started_at") or ""),
        int(session.get("session_order") or 0),
    )


def stall_length(facts: dict[str, Any]) -> int:
    """Count recent committing sessions after the latest applicable reset point."""
    first_program_session = facts.get("first_program_session")
    if first_program_session is None:
        return 0
    anchor = _session_order(first_program_session)
    latest_record_session = facts.get("latest_record_session")
    if latest_record_session is not None:
        anchor = max(anchor, _session_order(latest_record_session))
    sessions = sorted(facts.get("sessions") or [], key=_session_order)
    return sum(1 for session in sessions if _session_order(session) > anchor)


def evaluate_assignment(db: Any, assignment: dict[str, Any], now: datetime | None = None) -> int:
    """Recount one assignment's stall length and write it to the catalog summary."""
    now_iso = (now or datetime.now(UTC)).isoformat()
    account = db.get_account(assignment["player_account_id"])
    if not db.is_live_account(account) or not db.ledger_exists(account["ledger_id"]):
        return 0
    with db.open_ledger(account["ledger_id"]) as ledger:
        program = ledger.get_active_program()
        if program is None or program.version is None:
            length = 0
        else:
            exercise_ids = sorted(
                {
                    str(exercise.exercise_id)
                    for day in program.days
                    for exercise in day.exercises
                    if exercise.exercise_id
                }
            )
            facts = ledger.stall_recount_facts(
                int(program.version), exercise_ids, STALL_LOOKBACK_SESSIONS
            )
            length = stall_length(facts)
    db.update_roster_stall_length(assignment["assignment_id"], length, now_iso)
    return length


def evaluate_for_ledger(db: Any, account_id: str, now: datetime | None = None) -> int | None:
    """Best-effort hook entry point; returns ``None`` without an active assignment."""
    assignment = db.get_active_assignment_for_player(account_id) if account_id else None
    return evaluate_assignment(db, assignment, now=now) if assignment else None


def evaluate_after_commit(db: Any, account_id: str) -> None:
    """Refresh the roster summary without allowing a recount failure to fail commit."""
    try:
        evaluate_for_ledger(db, account_id)
    except Exception:
        logger.exception("Stall-length recount raised unexpectedly after session commit")
