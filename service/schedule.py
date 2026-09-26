"""Expected training schedule and prospective pauses (ticket #30, ADR 029).

The player owns the weekdays they expect to train and their timezone, plus any
future pause. Schedule edits append a new effective-dated version in the ledger
and never rewrite an earlier one, so attendance for a past date resolves against
the schedule that was effective then. A pause is prospective (starts today or
later), lasts at most 14 days, carries no reason, and is surfaced to the assigned
coach through the existing assignment gate with a best-effort in-app notice.

The schedule is deliberately separate from the program's weekly frequency and
ordered training days: setting it never generates, rebuilds, or reorders a program.
"""

import logging
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

MAX_PAUSE_DAYS = 14
PAUSE_NOTICE_KIND = "training_pause"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def local_today(current: dict[str, Any] | None) -> date:
    """The player's local date from their current schedule timezone, or UTC when unset.

    "Today" is the player's day, not the server's UTC day: a player west of UTC can
    still start a pause on their local today after the server has rolled over.
    """
    timezone = current["timezone"] if current else "UTC"
    return datetime.now(ZoneInfo(timezone)).date()


def _parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD).")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD).") from None


def _validate_weekdays(raw: Any) -> list[int]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("Pick at least one expected training weekday.")
    weekdays: list[int] = []
    for day in raw:
        if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 7:
            raise ValueError("Expected training weekdays must be integers from 1 (Mon) to 7 (Sun).")
        weekdays.append(day)
    if len(set(weekdays)) != len(weekdays):
        raise ValueError("Expected training weekdays must be unique.")
    return sorted(weekdays)


def _validate_timezone(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("A timezone is required.")
    try:
        ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Unknown timezone: {raw}.") from None
    return raw


def get_schedule(db: Any, trainee_id: str) -> dict[str, Any]:
    """The current schedule, every version, and today's active pauses."""
    current = db.get_current_training_schedule(trainee_id)
    today = local_today(current).isoformat()
    return {
        "current": current,
        "versions": db.list_training_schedules(trainee_id),
        "pauses": db.get_active_training_pauses(trainee_id, today),
    }


def set_schedule(db: Any, trainee_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validates and appends a new schedule version; the program is never touched."""
    weekdays = _validate_weekdays(payload.get("weekdays"))
    timezone = _validate_timezone(payload.get("timezone"))
    effective_from = payload.get("effective_from") or _now_iso()[:10]
    _parse_date(effective_from, "effective_from")
    version = db.append_training_schedule(
        trainee_id, weekdays, timezone, effective_from, _now_iso()
    )
    return {"version": version, "current": db.get_current_training_schedule(trainee_id)}


def schedule_pause(
    db: Any,
    trainee_id: str,
    payload: dict[str, Any],
    player_account_id: str | None,
    now_iso: str,
) -> dict[str, Any]:
    """Validates and stores a prospective pause, then best-effort notifies the coach.

    "Today" uses the player's schedule timezone (falling back to UTC before a
    schedule exists), not the server's UTC clock passed in ``now_iso``, so a player
    west of UTC is not rejected for starting on their own local today. ``now_iso``
    is still the pause's ``created_at``.
    """
    starts_on = _parse_date(payload.get("starts_on"), "starts_on")
    ends_on = _parse_date(payload.get("ends_on"), "ends_on")
    today = local_today(db.get_current_training_schedule(trainee_id))
    if starts_on < today:
        raise ValueError("A pause must start today or later.")
    if ends_on < starts_on:
        raise ValueError("A pause must end on or after it starts.")
    if (ends_on - starts_on).days + 1 > MAX_PAUSE_DAYS:
        raise ValueError(f"A pause can last at most {MAX_PAUSE_DAYS} days.")

    pause = db.schedule_training_pause(
        trainee_id, starts_on.isoformat(), ends_on.isoformat(), now_iso
    )
    notice_sent = _notify_coach(db, player_account_id, now_iso)
    return {"pause": pause, "notice_sent": notice_sent}


def get_pauses(db: Any, trainee_id: str) -> list[dict[str, Any]]:
    return db.list_training_pauses(trainee_id)


def _notify_coach(db: Any, player_account_id: str | None, now_iso: str) -> bool:
    """Best-effort coach in-app notice; a notice failure never fails the pause.

    With no active assignment there is no coach to notify, so the pause is still
    written and ``False`` is returned.
    """
    if not player_account_id:
        return False
    assignment = db.get_active_assignment_for_player(player_account_id)
    if assignment is None:
        return False
    account = db.get_account(player_account_id)
    username = account["username"] if account else "A player"
    try:
        db.create_assignment_notice(
            assignment["coach_account_id"],
            assignment["assignment_id"],
            PAUSE_NOTICE_KIND,
            f"{username} scheduled a training pause.",
            now_iso,
        )
    except Exception:
        logger.exception("Coach training-pause notice raised unexpectedly")
        return False
    return True
