"""Bounded recount of roster stall length (CONTEXT.md "Stalling", #203)."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Four times the stall-alert threshold of eight gives a useful trend window
# while limiting every commit hook to a small roster recount.
STALL_LOOKBACK_SESSIONS = 32


def _session_order(session: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(session.get("session_date") or ""),
        str(session.get("started_at") or ""),
        int(session.get("session_order") or 0),
    )


def stall_length(sessions: list[dict[str, Any]], program_version: int, exercise_ids: set[str]) -> int:
    """Recount consecutive sessions from canonical ADR 042 ``new_prs`` commit results."""
    ordered = sorted(sessions, key=_session_order)
    current_version_sessions = [
        session for session in ordered if session.get("program_version") == program_version
    ]
    if not current_version_sessions:
        return 0
    first_program_session = current_version_sessions[0]
    first_order = _session_order(first_program_session)
    latest_record_session = None
    for session in ordered:
        response = session.get("commit_response")
        if not response:
            continue
        try:
            events = json.loads(response).get("new_prs", [])
        except (TypeError, ValueError):
            events = []
        if any(
            isinstance(event, dict) and str(event.get("exercise_id")) in exercise_ids
            for event in events
        ):
            latest_record_session = session
    if latest_record_session is not None and _session_order(latest_record_session) >= first_order:
        reset_order = _session_order(latest_record_session)
        return sum(1 for session in ordered if _session_order(session) > reset_order)
    return sum(1 for session in ordered if _session_order(session) >= first_order)


def stall_window_start(sessions: list[dict[str, Any]], program_version: int, exercise_ids: set[str]) -> str | None:
    """Date of the first session in the current consecutive no-record run."""
    ordered = sorted(sessions, key=_session_order)
    current = [session for session in ordered if session.get("program_version") == program_version]
    if not current:
        return None
    first = current[0]
    latest_record = None
    for session in ordered:
        response = session.get("commit_response")
        if not response:
            continue
        try:
            events = json.loads(response).get("new_prs", [])
        except (TypeError, ValueError):
            events = []
        if any(isinstance(event, dict) and str(event.get("exercise_id")) in exercise_ids for event in events):
            latest_record = session
    start_order = _session_order(latest_record) if latest_record and _session_order(latest_record) >= _session_order(first) else _session_order(first)
    run = [session for session in ordered if _session_order(session) > start_order]
    if start_order == _session_order(first):
        run.insert(0, first)
    return str(run[0].get("session_date")) if run else None


def evaluate_assignment_facts(db: Any, assignment: dict[str, Any]) -> tuple[int, str | None]:
    """Recount one assignment's stall length and write it to the catalog summary."""
    account = db.get_account(assignment["player_account_id"])
    if not db.is_live_account(account):
        return 0, None
    if not db.ledger_exists(account["ledger_id"]):
        logger.warning("Skipping stall-length recount for account %s; no ledger exists.", assignment["player_account_id"])
        return 0, None
    with db.open_ledger(account["ledger_id"]) as ledger:
        program = ledger.get_active_program()
        if program is None or program.version is None:
            length, window_start = 0, None
        else:
            exercise_ids = sorted(
                {
                    str(exercise.exercise_id)
                    for day in program.days
                    for exercise in day.exercises
                    if exercise.exercise_id
                }
            )
            sessions = ledger.stall_recount_facts(STALL_LOOKBACK_SESSIONS)
            length = stall_length(sessions, int(program.version), set(exercise_ids))
            window_start = stall_window_start(sessions, int(program.version), set(exercise_ids))
    db.upsert_roster_attendance(assignment["assignment_id"], stall_length=length)
    return length, window_start


def evaluate_assignment(db: Any, assignment: dict[str, Any]) -> int:
    """Recount one assignment's stall length and write it to the catalog summary."""
    return evaluate_assignment_facts(db, assignment)[0]


def evaluate_for_ledger(db: Any, account_id: str) -> int | None:
    """Best-effort hook entry point; returns ``None`` without an active assignment."""
    assignment = db.get_active_assignment_for_player(account_id) if account_id else None
    return evaluate_assignment(db, assignment) if assignment else None
