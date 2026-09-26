"""Coach drill-down reads of an assigned player's training history (ticket #25).

Every read is gated by the catalog before the player's ledger is mounted: the
assignment must belong to the authenticated coach and be active (ADR 014/015/025).
An unknown, revoked, or other coach's assignment is denied with one generic error,
so its existence is never revealed. Player-assistant chats are never read here.
"""

from typing import Any

from service import dashboard as dashboard_service
from service._base import bind_user

DENIED_ERROR = "No active assignment."
DEFAULT_RECENT_SESSIONS = 10


def _bind_assigned_player(
    db: Any, coach_account_id: str, assignment_id: Any
) -> dict[str, Any] | None:
    """Resolves an active assignment owned by this coach, then mounts its ledger.

    The catalog gate runs first; ``bind_user`` is never reached unless the
    assignment belongs to this coach and is active. ``None`` covers unknown,
    ended, and other-coach assignments alike so callers deny them identically.
    """
    if not isinstance(assignment_id, str) or not assignment_id:
        return None
    assignment = db.get_active_assignment_for_coach(coach_account_id, assignment_id)
    if assignment is None:
        return None
    player = db.get_account(assignment["player_account_id"])
    if not db.is_live_account(player):
        return None
    bind_user(db, player["ledger_id"])
    return {"assignment": assignment, "player": player}


def _recent_sessions(db: Any, limit: int) -> list[dict[str, Any]]:
    """Newest-first working-set summaries grouped from the ledger session log."""
    sessions: dict[str, dict[str, Any]] = {}
    for row in db.get_session_log():
        summary = sessions.get(row["session_id"])
        if summary is None:
            summary = {
                "session_id": row["session_id"],
                "session_date": row["session_date"],
                "split_name": row["split_name"],
                "readiness_score": row["readiness_score"],
                "sets_count": 0,
                "total_volume_kg": 0.0,
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
    context = _bind_assigned_player(db, coach_account_id, assignment_id)
    if context is None:
        return None
    ledger_id = context["player"]["ledger_id"]
    return {
        "player_username": context["player"]["username"],
        "started_at": context["assignment"]["started_at"],
        "status": context["assignment"]["status"],
        "volume": dashboard_service.volume_attribution(db, ledger_id, days_lookback=days_lookback),
        "latest_session": db.get_latest_session_summary(),
        "recent_sessions": _recent_sessions(db, DEFAULT_RECENT_SESSIONS),
    }


def player_personal_records(
    db: Any, coach_account_id: str, assignment_id: Any, limit: int = 20
) -> list[dict[str, Any]] | None:
    """The assigned player's most recent personal records, newest-first."""
    context = _bind_assigned_player(db, coach_account_id, assignment_id)
    if context is None:
        return None
    return dashboard_service.recent_personal_records(
        db, context["player"]["ledger_id"], limit=limit
    )


def player_exercises(db: Any, coach_account_id: str, assignment_id: Any) -> list[dict[str, str]] | None:
    """The distinct exercises the assigned player has logged."""
    context = _bind_assigned_player(db, coach_account_id, assignment_id)
    if context is None:
        return None
    return dashboard_service.logged_exercises(db, context["player"]["ledger_id"])


def player_exercise_history(
    db: Any, coach_account_id: str, assignment_id: Any, exercise_id: str
) -> dict[str, Any] | None:
    """Progression history, latest caption, and records for one logged exercise."""
    context = _bind_assigned_player(db, coach_account_id, assignment_id)
    if context is None:
        return None
    ledger_id = context["player"]["ledger_id"]
    history = dashboard_service.exercise_history(db, ledger_id, exercise_id)
    return {
        "history": history,
        "caption": dashboard_service.latest_record_caption(history),
        "records": dashboard_service.exercise_records(db, ledger_id, exercise_id),
    }
