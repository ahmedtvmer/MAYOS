"""Coach alerts for the final Program week (ticket #332, ADR 073 amendment)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from agent.program_weeks import final_week_is_complete, normalize_program_weeks
from service import coach_analytics

logger = logging.getLogger(__name__)

FINAL_WEEK_STARTED_KIND = "program_final_week_started"
FINAL_WEEK_COMPLETED_KIND = "program_final_week_completed"
FINAL_WEEK_ALERT_KINDS = (FINAL_WEEK_STARTED_KIND, FINAL_WEEK_COMPLETED_KIND)


@dataclass(frozen=True)
class FinalWeekState:
    details: dict[str, Any]
    has_started: bool
    is_complete: bool


def evaluate_for_player(
    db: Any, player_account_id: str, now: datetime | None = None
) -> dict[str, int]:
    """Create version-deduplicated alerts from the Player's active Program state.

    This runs after a workout commits. It reads the Player's ledger only after
    resolving the active Assignment and never affects the workout result.
    """
    assignment = db.get_active_assignment_for_player(player_account_id)
    if assignment is None:
        return {"alerts_created": 0}
    state = _current_final_week_state(db, assignment)
    if state is None:
        return {"alerts_created": 0}
    return _create_due_alerts(db, assignment, state, now)


def _current_final_week_state(
    db: Any, assignment: dict[str, Any]
) -> FinalWeekState | None:
    account = db.get_account(assignment["player_account_id"])
    if not db.is_live_account(account) or not db.ledger_exists(account["ledger_id"]):
        return None
    with db.open_ledger(account["ledger_id"]) as ledger:
        program = ledger.get_active_program()
        if not _is_coach_multiweek_program(program, assignment["coach_account_id"]):
            return None
        return _final_week_state(ledger, program)


def _is_coach_multiweek_program(program: Any, coach_account_id: str) -> bool:
    if program is None or program.version is None:
        return False
    if program.published_by_coach_account_id != coach_account_id:
        return False
    return len(normalize_program_weeks(program)) > 1


def _final_week_state(ledger: Any, program: Any) -> FinalWeekState:
    final_week = normalize_program_weeks(program)[-1]
    version = int(program.version)
    completed_days = ledger.completed_program_days(version)
    return FinalWeekState(
        details={
            "program_version": version,
            "program_name": program.program_name,
            "final_week_order": int(final_week["week_order"]),
            "final_week_name": str(final_week["week_name"]),
        },
        has_started=(
            ledger.get_program_position(program).current_week
            == int(final_week["week_order"])
        ),
        is_complete=final_week_is_complete(program, completed_days),
    )


def _create_due_alerts(
    db: Any, assignment: dict[str, Any], state: FinalWeekState, now: datetime | None
) -> dict[str, int]:
    now_iso = (now or datetime.now(UTC)).isoformat()
    created = 0
    if state.has_started:
        created += _create_alert(
            db, assignment, FINAL_WEEK_STARTED_KIND, state.details, now_iso
        )
    if state.is_complete:
        created += _create_alert(
            db, assignment, FINAL_WEEK_COMPLETED_KIND, state.details, now_iso
        )
    return {"alerts_created": created}


def _create_alert(
    db: Any,
    assignment: dict[str, Any],
    kind: str,
    details: dict[str, Any],
    created_at: str,
) -> int:
    try:
        inserted = coach_analytics.create_coach_alert(
            db, _alert_draft(assignment, kind, details, created_at)
        )
    except Exception:
        logger.exception("Could not create final Program week Coach alert.")
        return 0
    return int(bool(inserted.get("created")))


def _alert_draft(
    assignment: dict[str, Any],
    kind: str,
    details: dict[str, Any],
    created_at: str,
) -> coach_analytics.CoachAlertDraft:
    return coach_analytics.CoachAlertDraft(
        alert_id=uuid.uuid4().hex,
        assignment_id=str(assignment["assignment_id"]),
        coach_account_id=str(assignment["coach_account_id"]),
        player_account_id=str(assignment["player_account_id"]),
        alert_kind=kind,
        dedupe_key=str(details["program_version"]),
        details=details,
        created_at=created_at,
    )


def resolve_for_publish(
    db: Any, assignment_id: str, now: datetime | None = None
) -> None:
    """Resolve open final-week alerts when a new Coach version is published."""
    now_iso = (now or datetime.now(UTC)).isoformat()
    for kind in FINAL_WEEK_ALERT_KINDS:
        try:
            db.resolve_open_coach_alerts_for_assignment(assignment_id, now_iso, kind)
        except Exception:
            logger.exception("Could not resolve a final Program week alert on publish.")
