"""Expected training schedule and prospective pauses (ticket #30, ADR 029).

The player owns the weekdays they expect to train and their timezone, plus any
future pause. Schedule edits append a new effective-dated version in the ledger
and never rewrite an earlier one, so attendance for a past date resolves against
the schedule that was effective then. A pause is prospective (starts today or
later), lasts at most 14 days, carries no reason, and is surfaced to the assigned
coach through the existing assignment gate with a best-effort in-app notice.

The schedule is deliberately separate from the program's weekly frequency and
ordered training days: setting it never generates, rebuilds, or reorders a program.

"Today" is always the player's local day, derived from their schedule timezone:
this module is the single place that computes it.
"""

import logging
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from service._base import ledger_scope

logger = logging.getLogger(__name__)

MAX_PAUSE_DAYS = 14
PAUSE_NOTICE_KIND = "training_pause"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def timezone_for_versions(versions: list[dict[str, Any]], fallback_timezone: str = "UTC") -> str:
    """The timezone of the most recently created schedule version, else the fallback.

    Pure and DB-free so attendance evaluation can resolve the player's local day
    without mounting a ledger (this is the single ADR 029 definition of "today").
    """
    if not versions:
        return fallback_timezone
    latest = max(
        versions,
        key=lambda version: (
            version.get("created_at", ""),
            version.get("effective_from", ""),
            version.get("schedule_id", ""),
        ),
    )
    return latest["timezone"]


def local_date_in(now: datetime, timezone: str) -> date:
    """The local date of ``now`` in ``timezone`` (the one place "today" is derived)."""
    return now.astimezone(ZoneInfo(timezone)).date()


def latest_schedule_timezone(db: Any, ledger_id: str, ledger: Any | None = None) -> str | None:
    """The timezone of the most recently created schedule version, if any.

    Public so other services (e.g. performed-date correction) resolve a legacy
    session's local day the same way "today" is derived (ADR 029).
    """
    with ledger_scope(db, ledger, ledger_id) as ledger:
        versions = ledger.list_training_schedules(ledger_id)
    if not versions:
        return None
    return timezone_for_versions(versions)


def local_today(db: Any, ledger_id: str, fallback_timezone: str = "UTC", ledger: Any | None = None) -> date:
    """The player's local date from their latest schedule timezone, else the fallback.

    "Today" is the player's day, not the server's UTC day: a player ahead of UTC
    rolls into tomorrow first, and a player behind UTC still has their own today.
    """
    timezone = latest_schedule_timezone(db, ledger_id, ledger=ledger) or fallback_timezone
    return local_date_in(datetime.now(UTC), timezone)


def current_schedule(
    db: Any, ledger_id: str, fallback_timezone: str = "UTC", ledger: Any | None = None
) -> tuple[dict[str, Any] | None, date]:
    """The schedule effective on the player's local today, plus that local date."""
    with ledger_scope(db, ledger, ledger_id) as ledger:
        today = local_today(db, ledger_id, fallback_timezone=fallback_timezone, ledger=ledger)
        return ledger.get_schedule_effective_on(ledger_id, today.isoformat()), today


def parse_iso_date(value: Any, field: str) -> date:
    """A strict ``YYYY-MM-DD`` date; basic ISO forms (``20260901``) are refused."""
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD).")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD).") from None
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD).")
    return parsed


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


def get_schedule(db: Any, ledger_id: str, ledger: Any | None = None) -> dict[str, Any]:
    """The current schedule, every version, and today's active/upcoming pauses."""
    with ledger_scope(db, ledger, ledger_id) as ledger:
        current, today = current_schedule(db, ledger_id, ledger=ledger)
        return {
            "current": current,
            "versions": ledger.list_training_schedules(ledger_id),
            "pauses": ledger.list_active_or_upcoming_training_pauses(ledger_id, today.isoformat()),
        }


def set_schedule(
    db: Any, ledger_id: str, payload: dict[str, Any], ledger: Any | None = None
) -> dict[str, Any]:
    """Validates and appends a new schedule version; the program is never touched.

    ``effective_from`` may not be earlier than the player's local today, so a new
    version can never change what an already-past date expected. It defaults to
    the player's local today.
    """
    weekdays = _validate_weekdays(payload.get("weekdays"))
    timezone = _validate_timezone(payload.get("timezone"))
    with ledger_scope(db, ledger, ledger_id) as ledger:
        today = local_today(db, ledger_id, fallback_timezone=timezone, ledger=ledger)
        raw_effective_from = payload.get("effective_from")
        if raw_effective_from:
            effective_from = parse_iso_date(raw_effective_from, "effective_from")
            if effective_from < today:
                raise ValueError("A schedule cannot take effect in the past.")
        else:
            effective_from = today
        version = ledger.append_training_schedule(
            ledger_id, weekdays, timezone, effective_from.isoformat(), _now_iso()
        )
        current = ledger.get_schedule_effective_on(ledger_id, today.isoformat())
        return {"version": version, "current": current}


def schedule_pause(
    db: Any,
    ledger_id: str,
    payload: dict[str, Any],
    player_account_id: str | None,
    ledger: Any | None = None,
) -> dict[str, Any]:
    """Validates and stores a prospective pause, then best-effort notifies the coach.

    "Today" uses the player's local schedule timezone (falling back to UTC before
    a schedule exists), not the server's UTC clock, so a player west of UTC is not
    rejected for starting on their own local today.
    """
    now_iso = _now_iso()
    starts_on = parse_iso_date(payload.get("starts_on"), "starts_on")
    ends_on = parse_iso_date(payload.get("ends_on"), "ends_on")
    with ledger_scope(db, ledger, ledger_id) as ledger:
        _, today = current_schedule(db, ledger_id, ledger=ledger)
        if starts_on < today:
            raise ValueError("A pause must start today or later.")
        if ends_on < starts_on:
            raise ValueError("A pause must end on or after it starts.")
        if (ends_on - starts_on).days + 1 > MAX_PAUSE_DAYS:
            raise ValueError(f"A pause can last at most {MAX_PAUSE_DAYS} days.")

        pause = ledger.schedule_training_pause(
            ledger_id, starts_on.isoformat(), ends_on.isoformat(), now_iso
        )
    notice_sent = _notify_coach(db, player_account_id, starts_on, ends_on, now_iso)
    return {"pause": pause, "notice_sent": notice_sent}


def get_pauses(db: Any, ledger_id: str, ledger: Any | None = None) -> list[dict[str, Any]]:
    """Every pause the player has scheduled, newest first."""
    with ledger_scope(db, ledger, ledger_id) as ledger:
        return ledger.list_training_pauses(ledger_id)


def _notify_coach(
    db: Any,
    player_account_id: str | None,
    starts_on: date,
    ends_on: date,
    now_iso: str,
) -> bool:
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
            f"{username} scheduled a training pause from {starts_on.isoformat()} to {ends_on.isoformat()}.",
            now_iso,
        )
    except Exception:
        logger.exception("Coach training-pause notice raised unexpectedly")
        return False
    return True
