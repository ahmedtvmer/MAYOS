"""Coach check-ins and follow-up-due alerts (ADR 031, ticket #32).

A check-in is an immutable catalog fact: the coach records the date, the contact
channel, and an optional short note. It is visible to the player for the life of
their account, including after the assignment ends, while the former coach's
access ends with the assignment because every coach read rides the ADR 025
assignment gate.

A weekly follow-up cadence runs off the most recent check-in: an assignment is
due once the player's local today reaches ``last check-in (or assignment start
local date) + FOLLOW_UP_CADENCE_DAYS``. The due date is the alert's dedupe key,
so a retry or a concurrent sweep cannot duplicate the alert. ``evaluate_follow_up``
is the single place that transitions follow-up alerts: it clears stale open
alerts and inserts the current one, so recording a check-in only writes the fact
and re-runs that evaluation.

Everything in this module is catalog-only: no player ledger is ever mounted. The
player's local day comes from the timezone the missed-day sweep caches on
``roster_attendance``, falling back to UTC. Until a timezone is cached, each
validation bound takes the most permissive local day on earth: the future-date
bound uses the latest local day (``Pacific/Kiritimati``, UTC+14) so a player
ahead of UTC is never rejected for dating their own today, while the assignment
start (lower) bound uses the earliest local day (``Etc/GMT+12``, UTC-12) so a
check-in dated on the assignment's real start day is never rejected as
predating it once UTC+14 has rolled into the next calendar day.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from service.coach_notices import notify_coach, player_display_name
from service.schedule import local_date_in

CHECK_IN_CHANNELS = (
    "in_app",
    "in_person",
    "phone",
    "video",
    "message",
    "email",
    "other",
)
MAX_CHECK_IN_NOTE_LENGTH = 500
FOLLOW_UP_KIND = "follow_up_due"
FOLLOW_UP_CADENCE_DAYS = 7

#: When the player's timezone is not cached yet, validate a check-in date against
#: the most permissive local day on each side rather than UTC. The upper bound
#: (future date) uses the latest local day on earth (UTC+14) so a player ahead of
#: UTC is never told their own today is in the future; the lower bound
#: (assignment start) uses the earliest local day on earth (UTC-12) so a check-in
#: dated on the assignment's real start day is never rejected as predating it
#: once UTC+14 has already rolled into the next calendar day.
MAX_LOCAL_TIMEZONE = "Pacific/Kiritimati"
MIN_LOCAL_TIMEZONE = "Etc/GMT+12"

__all__ = [
    "CHECK_IN_CHANNELS",
    "FOLLOW_UP_CADENCE_DAYS",
    "FOLLOW_UP_KIND",
    "MAX_CHECK_IN_NOTE_LENGTH",
    "MAX_LOCAL_TIMEZONE",
    "MIN_LOCAL_TIMEZONE",
    "create_check_in",
    "evaluate_follow_up",
    "list_coach_check_ins",
    "list_player_check_ins",
    "next_follow_up_on",
]


def _now() -> datetime:
    """The current instant; the single seam tests freeze to pin the wall clock."""
    return datetime.now(UTC)


def _parse_instant(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _parse_strict_date(value: Any, field: str = "checked_in_on") -> date:
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


def _normalize_note(note: Any) -> str | None:
    """Trim an optional note; an empty note is stored as ``NULL``."""
    if note is None:
        return None
    if not isinstance(note, str):
        raise ValueError("A check-in note must be text.")
    trimmed = note.strip()
    if not trimmed:
        return None
    if len(trimmed) > MAX_CHECK_IN_NOTE_LENGTH:
        raise ValueError(f"A check-in note can be at most {MAX_CHECK_IN_NOTE_LENGTH} characters.")
    return trimmed


def _assignment_start_local(assignment: dict[str, Any], timezone: str) -> date | None:
    started = _parse_instant(assignment.get("started_at"))
    if started is None:
        return None
    return local_date_in(started, timezone)


def next_follow_up_on(
    started_at: Any,
    latest_check_in_on: str | None,
    timezone: str,
) -> date | None:
    """The next follow-up due date: last check-in (or assignment start) + cadence.

    Pure and catalog-only. ``None`` only when neither a check-in nor a parseable
    assignment start exists.
    """
    if latest_check_in_on:
        base = _parse_strict_date(latest_check_in_on, "last check-in")
    else:
        started = _parse_instant(started_at)
        if started is None:
            return None
        base = local_date_in(started, timezone)
    return base + timedelta(days=FOLLOW_UP_CADENCE_DAYS)


def evaluate_follow_up(db: Any, assignment: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Reconciles the assignment's open follow-up alerts against the current due date.

    The single transition point for the follow-up kind:

    * open alerts whose dedupe key differs from the current due date are resolved
      with ``resolved_by='system'``;
    * when the follow-up is no longer due, every open follow-up alert is resolved;
    * when due, the alert for the current due date is inserted (insert-or-ignore,
      so an acknowledged or coach-resolved alert with the same key is left as-is
      and no duplicate appears).

    Catalog-only and idempotent: a repeated or concurrent sweep never duplicates
    an alert.
    """
    now = now or _now()
    now_iso = now.isoformat()
    assignment_id = assignment["assignment_id"]
    timezone = db.get_roster_timezone(assignment_id) or "UTC"
    local_today = local_date_in(now, timezone)
    latest = db.latest_check_in_on(assignment_id)
    due_on = next_follow_up_on(assignment.get("started_at"), latest, timezone)
    due_key = due_on.isoformat() if due_on else None
    is_due = due_on is not None and local_today >= due_on

    resolved = db.resolve_open_coach_alerts_for_assignment(
        assignment_id,
        now_iso,
        FOLLOW_UP_KIND,
        except_dedupe_key=due_key if is_due else None,
    )

    created = 0
    if is_due:
        inserted = db.insert_coach_alert(
            uuid.uuid4().hex,
            assignment_id,
            assignment["coach_account_id"],
            assignment["player_account_id"],
            FOLLOW_UP_KIND,
            due_key,
            {"due_on": due_key, "last_check_in_on": latest},
            now_iso,
        )
        if inserted["created"]:
            created = 1
            notify_coach(
                db,
                assignment,
                FOLLOW_UP_KIND,
                f"A follow-up with {player_display_name(db, assignment)} is due since"
                f" {due_key}. Review your roster.",
                now_iso,
            )
    return {
        "created": created,
        "resolved": resolved,
        "due_on": due_key,
        "last_check_in_on": latest,
    }


def _gate_coach(db: Any, coach_account_id: str, assignment_id: Any) -> dict[str, Any] | None:
    """The active assignment owned by this coach, or ``None`` for a generic denial.

    Unknown, ended, and other-coach assignments all return ``None`` (ADR 025).
    """
    if not isinstance(assignment_id, str) or not assignment_id:
        return None
    return db.get_active_assignment_for_coach(coach_account_id, assignment_id)


def create_check_in(
    db: Any,
    coach_account_id: str,
    assignment_id: Any,
    payload: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validates and records one check-in, then reconciles the follow-up alerts.

    Returns ``{"ok": False, "denied": True}`` for an unknown/ended/foreign
    assignment and ``{"ok": False, "error": ...}`` for a validation failure.
    """
    now = now or _now()
    now_iso = now.isoformat()
    assignment = _gate_coach(db, coach_account_id, assignment_id)
    if assignment is None:
        return {"ok": False, "denied": True, "error": "No active assignment."}

    channel = payload.get("channel")
    if channel not in CHECK_IN_CHANNELS:
        return {"ok": False, "error": "channel is not a recognized contact method."}
    try:
        checked_in_on = _parse_strict_date(payload.get("checked_in_on"))
        note = _normalize_note(payload.get("note"))
    except ValueError as error:
        return {"ok": False, "error": str(error)}

    # Until the timezone is cached, take the most permissive bound on each side:
    # the latest local day for the future check and the earliest local day for
    # the assignment-start check (ADR 031).
    cached_timezone = db.get_roster_timezone(assignment_id)
    upper_bound_timezone = cached_timezone or MAX_LOCAL_TIMEZONE
    lower_bound_timezone = cached_timezone or MIN_LOCAL_TIMEZONE
    local_today = local_date_in(now, upper_bound_timezone)
    if checked_in_on > local_today:
        return {"ok": False, "error": "A check-in cannot be dated in the future."}
    start_local = _assignment_start_local(assignment, lower_bound_timezone)
    if start_local is not None and checked_in_on < start_local:
        return {"ok": False, "error": "A check-in cannot predate the assignment."}

    record = db.create_check_in(
        uuid.uuid4().hex,
        assignment_id,
        coach_account_id,
        assignment["player_account_id"],
        checked_in_on.isoformat(),
        channel,
        note,
        now_iso,
    )
    follow_up = evaluate_follow_up(db, assignment, now=now)
    return {
        "ok": True,
        "check_in": record,
        "next_follow_up_on": follow_up["due_on"],
    }


def list_coach_check_ins(
    db: Any, coach_account_id: str, assignment_id: Any
) -> list[dict[str, Any]] | None:
    """The assignment's check-ins for its active coach, or ``None`` for a denial."""
    if _gate_coach(db, coach_account_id, assignment_id) is None:
        return None
    return db.list_assignment_check_ins(str(assignment_id))


def list_player_check_ins(db: Any, player_account_id: str) -> list[dict[str, Any]]:
    """Every check-in the authenticated player received, including ended assignments."""
    return db.list_player_check_ins(player_account_id)
