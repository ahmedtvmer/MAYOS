"""Coach drill-down reads of an assigned player's training history (ticket #25).

Every read is gated by the catalog before the player's ledger is opened: the
assignment must belong to the authenticated coach and be active (ADR 014/015/025).
An unknown, revoked, or other coach's assignment is denied with one generic error,
so its existence is never revealed. Player-assistant chats are never read here.
"""

from typing import Any

from service import dashboard as dashboard_service
from service.assignments import (  # noqa: F401  (DENIED_ERROR re-exported for routers)
    DENIED_ERROR,
    authorized_player_ledger,
)
from service.schedule import current_schedule
from service.workouts import is_historical_program

DEFAULT_RECENT_SESSIONS = 10


def _schedule_and_pauses(db: Any, ledger: Any, ledger_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The player's current expected schedule and their upcoming/active pauses.

    Only the underlying ledger rows are read; the caller has already passed the
    assignment gate, so no new authorization is introduced here.
    """
    current, today = current_schedule(db, ledger_id, ledger=ledger)
    schedule = None
    if current is not None:
        schedule = {"weekdays": current["weekdays"], "timezone": current["timezone"]}
    pauses = [
        {"starts_on": pause["starts_on"], "ends_on": pause["ends_on"]}
        for pause in ledger.list_active_or_upcoming_training_pauses(ledger_id, today.isoformat())
    ]
    return schedule, pauses


def _recent_sessions(ledger: Any, limit: int) -> list[dict[str, Any]]:
    """Newest-first working-set summaries grouped from the ledger session log."""
    divergences_by_session = ledger.list_divergences_by_session()
    version_by_session = ledger.get_session_program_versions()
    audit_by_session = ledger.get_session_audit_metadata()
    sessions: dict[str, dict[str, Any]] = {}
    for row in ledger.get_session_log():
        summary = sessions.get(row["session_id"])
        if summary is None:
            version_info = version_by_session.get(row["session_id"], {})
            audit = audit_by_session.get(row["session_id"], {})
            summary = {
                "session_id": row["session_id"],
                "session_date": row["session_date"],
                "split_name": row["split_name"],
                "readiness_score": row["readiness_score"],
                "program_version": version_info.get("program_version"),
                "active_program_version_at_sync": version_info.get("active_program_version_at_sync"),
                "is_historical_program": is_historical_program(
                    version_info.get("program_version"),
                    version_info.get("active_program_version_at_sync"),
                ),
                "uploaded_at": audit.get("uploaded_at"),
                "edited_at": audit.get("edited_at"),
                "corrections": audit.get("corrections", []),
                "sets_count": 0,
                "total_volume_kg": 0.0,
                "divergences": divergences_by_session.get(row["session_id"], []),
            }
            sessions[row["session_id"]] = summary
        if not row["is_warmup"]:
            summary["sets_count"] += 1
            summary["total_volume_kg"] += float(row["weight_kg"]) * int(row["reps"])
    ordered = list(sessions.values())
    ordered.reverse()
    return ordered[: max(1, limit)]


def player_summary(
    db: Any, coach_account_id: str, assignment_id: Any, days_lookback: int = 7
) -> dict[str, Any] | None:
    """Identity, volume, latest session, and recent sessions for an assigned player."""
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        ledger_id = context["player"]["ledger_id"]
        schedule, pauses = _schedule_and_pauses(db, ledger, ledger_id)
        latest_session = ledger.get_latest_session_summary()
        if latest_session is not None:
            latest_session["is_historical_program"] = is_historical_program(
                latest_session.get("program_version"),
                latest_session.get("active_program_version_at_sync"),
            )
        return {
            "player_username": context["player"]["username"],
            "started_at": context["assignment"]["started_at"],
            "status": context["assignment"]["status"],
            "volume": dashboard_service.volume_attribution(
                db, ledger_id, days_lookback=days_lookback, ledger=ledger
            ),
            "latest_session": latest_session,
            "recent_sessions": _recent_sessions(ledger, DEFAULT_RECENT_SESSIONS),
            "schedule": schedule,
            "pauses": pauses,
        }


def player_personal_records(
    db: Any, coach_account_id: str, assignment_id: Any, limit: int = 20
) -> list[dict[str, Any]] | None:
    """The assigned player's most recent personal records, newest-first."""
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        return dashboard_service.recent_personal_records(
            db, context["player"]["ledger_id"], limit=limit, ledger=ledger
        )


def player_exercises(db: Any, coach_account_id: str, assignment_id: Any) -> list[dict[str, str]] | None:
    """The distinct exercises the assigned player has logged."""
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        return dashboard_service.logged_exercises(db, context["player"]["ledger_id"], ledger=ledger)


def player_exercise_history(
    db: Any, coach_account_id: str, assignment_id: Any, exercise_id: str
) -> dict[str, Any] | None:
    """Progression history, latest caption, and records for one logged exercise."""
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        ledger_id = context["player"]["ledger_id"]
        history = dashboard_service.exercise_history(db, ledger_id, exercise_id, ledger=ledger)
        return {
            "history": history,
            "caption": dashboard_service.latest_record_caption(history),
            "records": dashboard_service.exercise_records(db, ledger_id, exercise_id, ledger=ledger),
        }
