"""Missed expected-day alerts and catalog-side attendance summaries (ADR 030, ticket #31).

A coach is alerted when an assigned player misses two consecutive expected
training days. Evaluation is deterministic and idempotent: it opens the player's
ledger (the sweep may; roster reads may not), runs the pure attendance evaluation
(``service.attendance``), and then:

* creates one ``new`` alert for a qualifying streak and a best-effort coach
  in-app notice (the notice is only written when the alert is first created);
* extends the same alert's ``details`` (``last_missed_date``/``missed_count``)
  while the streak continues;
* auto-resolves any open alert whose streak is no longer the current one; and
* updates the catalog-side roster summary so roster reads never open a ledger.

The catalog alert is keyed by ``(assignment, kind, dedupe_key)`` where the
missed-day dedupe key is the streak's start date, so a retry or a concurrent
sweep cannot duplicate it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from service._base import bind_user
from service.attendance import AttendanceEvaluation, evaluate_attendance
from service.coach_notices import notify_coach, player_display_name
from service.schedule import local_date_in, timezone_for_versions

logger = logging.getLogger(__name__)

MISSED_DAY_KIND = "missed_expected_days"
STREAK_ALERT_THRESHOLD = 2
ALERT_STATES = ("new", "acknowledged", "resolved")
DEFAULT_ALERT_STATES = ("new", "acknowledged")

__all__ = [
    "ALERT_STATES",
    "DEFAULT_ALERT_STATES",
    "MISSED_DAY_KIND",
    "acknowledge_alert",
    "evaluate_assignment",
    "evaluate_for_ledger",
    "list_alerts",
    "present_alert",
    "resolve_alert",
]


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


def _window_start(started_at: Any, versions: list[dict[str, Any]], timezone: str) -> date:
    """The assignment's local start date, never before the first schedule version.

    Expectations cannot predate the first schedule the player ever wrote, so a
    long-running assignment does not retroactively flag days before any schedule
    existed.
    """
    first_effective = min(date.fromisoformat(str(version["effective_from"])) for version in versions)
    started = _parse_instant(started_at)
    if started is None:
        return first_effective
    return max(local_date_in(started, timezone), first_effective)


def _notify_coach(db: Any, assignment: dict[str, Any], evaluation: AttendanceEvaluation, now_iso: str) -> bool:
    """Best-effort coach in-app notice; carries the missed date range, no training detail."""
    return notify_coach(
        db,
        assignment,
        MISSED_DAY_KIND,
        (
            f"{player_display_name(db, assignment)} missed {evaluation.trailing_streak_length}"
            f" expected training days ({evaluation.trailing_streak_start.isoformat()} to"
            f" {evaluation.trailing_streak_last.isoformat()}). Review the alert in your roster."
        ),
        now_iso,
    )


def evaluate_assignment(db: Any, assignment: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Evaluates one assignment and applies alert/transition/roster-summary effects.

    Safe to run repeatedly with the same data: the second run creates no notice
    and changes no alert. One player's failure is the caller's to catch.
    """
    now = now or datetime.now(UTC)
    now_iso = now.isoformat()
    assignment_id = assignment["assignment_id"]
    coach_account_id = assignment["coach_account_id"]
    player_account_id = assignment["player_account_id"]

    account = db.get_account(player_account_id)
    if not db.is_live_account(account):
        return {"evaluated": False, "skipped": True, "alerts_created": 0, "alerts_resolved": 0, "streak": 0}

    ledger_id = account["ledger_id"]
    if not db.user_exists(ledger_id):
        logger.warning(
            "Skipping missed-day evaluation for account %s; no ledger exists.", player_account_id
        )
        return {"evaluated": False, "skipped": True, "alerts_created": 0, "alerts_resolved": 0, "streak": 0}

    bind_user(db, ledger_id)
    versions = db.list_training_schedules(ledger_id)
    if not versions:
        db.upsert_roster_attendance(assignment_id, 0, now_iso)
        return {"evaluated": True, "skipped": False, "alerts_created": 0, "alerts_resolved": 0, "streak": 0}

    pauses = db.list_training_pauses(ledger_id)
    performed = db.list_performed_dates()
    timezone = timezone_for_versions(versions)
    evaluation = evaluate_attendance(
        versions=versions,
        pauses=pauses,
        performed_dates=performed,
        window_start=_window_start(assignment.get("started_at"), versions, timezone),
        now=now,
    )

    streak = evaluation.trailing_streak_length
    created = 0
    if streak >= STREAK_ALERT_THRESHOLD:
        streak_start = evaluation.trailing_streak_start.isoformat()
        details = {
            "streak_start_date": streak_start,
            "last_missed_date": evaluation.trailing_streak_last.isoformat(),
            "missed_count": streak,
        }
        inserted = db.insert_coach_alert(
            uuid.uuid4().hex,
            assignment_id,
            coach_account_id,
            player_account_id,
            MISSED_DAY_KIND,
            streak_start,
            details,
            now_iso,
        )
        if inserted["created"]:
            created = 1
            _notify_coach(db, assignment, evaluation, now_iso)
        else:
            db.update_coach_alert_details(inserted["alert"]["alert_id"], details)
        resolved = db.resolve_open_coach_alerts_for_assignment(
            assignment_id, now_iso, MISSED_DAY_KIND, except_dedupe_key=streak_start
        )
    else:
        resolved = db.resolve_open_coach_alerts_for_assignment(
            assignment_id, now_iso, MISSED_DAY_KIND
        )

    db.upsert_roster_attendance(assignment_id, streak, now_iso, timezone=evaluation.timezone)
    return {
        "evaluated": True,
        "skipped": False,
        "alerts_created": created,
        "alerts_resolved": resolved,
        "streak": streak,
        "missed_days": [day.isoformat() for day in evaluation.missed_days],
    }


def evaluate_for_ledger(db: Any, account_id: str, now: datetime | None = None) -> dict[str, Any] | None:
    """Best-effort evaluation for a player account; ``None`` with no active assignment.

    Always unbinds the player's ledger afterwards so a shared worker thread does
    not keep it mounted (ADR 030).
    """
    if not account_id:
        return None
    try:
        assignment = db.get_active_assignment_for_player(account_id)
        if assignment is None:
            return None
        return evaluate_assignment(db, assignment, now=now)
    finally:
        db.unmount_user()


def present_alert(alert: dict[str, Any]) -> dict[str, Any]:
    """Flatten kind-specific ``details`` beside the common fields for the response.

    The single presentation point for the alert API shape (ADR 031); the database
    row keeps the fields nested under ``details``.
    """
    presented = {key: value for key, value in alert.items() if key != "details"}
    details = alert.get("details")
    if isinstance(details, dict):
        for key, value in details.items():
            presented.setdefault(str(key), value)
    return presented


def list_alerts(db: Any, coach_account_id: str, states: tuple[str, ...]) -> list[dict[str, Any]]:
    """Catalog-only alert list for the coach's active assignments, newest-first.

    Unknown states are dropped; an empty selection lists nothing.
    """
    allowed = tuple(state for state in states if state in ALERT_STATES)
    return [present_alert(alert) for alert in db.list_coach_alerts(coach_account_id, allowed)]


def _active_alert(db: Any, coach_account_id: str, alert_id: Any) -> dict[str, Any] | None:
    """The alert only when it belongs to the coach and its assignment is still active."""
    if not isinstance(alert_id, str) or not alert_id:
        return None
    alert = db.get_coach_alert(alert_id)
    if alert is None or alert["coach_account_id"] != str(coach_account_id):
        return None
    if db.get_active_assignment_for_coach(coach_account_id, alert["assignment_id"]) is None:
        return None
    return _with_player_username(db, alert)


def _with_player_username(db: Any, alert: dict[str, Any]) -> dict[str, Any]:
    account = db.get_account(alert["player_account_id"])
    alert["player_username"] = account["username"] if account else "former player"
    return present_alert(alert)


def acknowledge_alert(db: Any, coach_account_id: str, alert_id: Any) -> dict[str, Any] | None:
    """Acknowledges an alert (``new`` → ``acknowledged``); already acknowledged is idempotent.

    A resolved alert stays resolved. ``None`` is the generic denial for an
    unknown, foreign, or ended assignment, with no ledger mounted.
    """
    if _active_alert(db, coach_account_id, alert_id) is None:
        return None
    result = db.acknowledge_coach_alert(
        str(alert_id), coach_account_id, datetime.now(UTC).isoformat()
    )
    return _with_player_username(db, result) if result else None


def resolve_alert(db: Any, coach_account_id: str, alert_id: Any) -> dict[str, Any] | None:
    """Resolves an alert as the coach; already resolved is idempotent, denial is ``None``."""
    if _active_alert(db, coach_account_id, alert_id) is None:
        return None
    result = db.resolve_coach_alert(
        str(alert_id), coach_account_id, datetime.now(UTC).isoformat(), "coach"
    )
    return _with_player_username(db, result) if result else None
