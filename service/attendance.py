"""Pure attendance evaluation for missed expected training days (ticket #31, ADR 030).

This module has no database access: it takes the player's effective-dated
schedule versions, their pauses, the local dates they actually performed a
workout on, the evaluation window start, and the current instant, and returns a
deterministic evaluation. The service layer (``service.missed_day_alerts``) only
supplies ledger rows and persists the resulting transitions.

Rules (ADR 030):

* An *expected day* is a local date in the window whose ISO weekday is in the
  schedule version effective on that date and that no pause covers.
* A day is *due* once local now reaches the start of the local date two days
  later (the end of the day plus a 24 hour local grace period).
* Iterating workouts oldest-first, each workout satisfies at most one expected
  day: the earliest not-yet-satisfied expected day ``e`` with
  ``e <= performed_date <= e + 1``. Each expected day is satisfied by at most one
  workout and leftover workouts satisfy nothing.
* A *missed expected day* is due and unsatisfied. The trailing run of missed due
  expected days is measured over the sequence of expected days; non-expected and
  paused days are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from service.schedule import local_date_in, timezone_for_versions

__all__ = [
    "AttendanceEvaluation",
    "evaluate_attendance",
    "is_expected_day",
    "pause_covers",
    "version_effective_on",
]


@dataclass(frozen=True)
class AttendanceEvaluation:
    """The deterministic attendance facts for one player's window."""

    timezone: str
    local_today: date
    window_start: date
    expected_days: tuple[date, ...]
    satisfied_days: tuple[date, ...]
    missed_days: tuple[date, ...]
    trailing_streak_start: date | None
    trailing_streak_last: date | None
    trailing_streak_length: int


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def version_effective_on(versions: list[dict[str, Any]], on_date: date) -> dict[str, Any] | None:
    """The latest schedule version with ``effective_from <= on_date``, matching the ledger order.

    Ties on ``effective_from`` fall to the later ``created_at`` and then the later
    appended row, mirroring ``get_schedule_effective_on``.
    """
    chosen: dict[str, Any] | None = None
    chosen_key: tuple[date, str, int] | None = None
    for index, version in enumerate(versions):
        effective = _as_date(version["effective_from"])
        if effective > on_date:
            continue
        key = (effective, str(version.get("created_at", "")), index)
        if chosen_key is None or key >= chosen_key:
            chosen = version
            chosen_key = key
    return chosen


def pause_covers(pauses: list[dict[str, Any]], day: date) -> bool:
    """Whether any Schedule pause covers ``day``."""
    for pause in pauses:
        if _as_date(pause["starts_on"]) <= day <= _as_date(pause["ends_on"]):
            return True
    return False


def is_expected_day(
    versions: list[dict[str, Any]], pauses: list[dict[str, Any]], day: date
) -> bool:
    """Whether ``day`` is expected under its effective schedule and pauses."""
    version = version_effective_on(versions, day)
    return (
        version is not None
        and day.isoweekday() in set(version["weekdays"])
        and not pause_covers(pauses, day)
    )


def evaluate_attendance(
    *,
    versions: list[dict[str, Any]],
    pauses: list[dict[str, Any]],
    performed_dates: list[Any],
    window_start: Any,
    now: datetime,
    fallback_timezone: str = "UTC",
) -> AttendanceEvaluation:
    """Evaluates due/satisfied/missed expected days for one player over the window.

    ``window_start`` is the player's local date of the assignment start, already
    floored to the first schedule version's ``effective_from`` by the caller.
    """
    timezone = timezone_for_versions(versions, fallback_timezone)
    local_today = local_date_in(now, timezone)
    window_start = _as_date(window_start)
    performed = sorted(_as_date(value) for value in performed_dates)

    expected: list[date] = []
    day = window_start
    while day <= local_today:
        if is_expected_day(versions, pauses, day):
            expected.append(day)
        day += timedelta(days=1)

    satisfied: set[date] = set()
    for performed_date in performed:
        for expected_day in expected:
            if expected_day in satisfied:
                continue
            if expected_day <= performed_date <= expected_day + timedelta(days=1):
                satisfied.add(expected_day)
                break

    missed: list[date] = []
    due_days: set[date] = set()
    for expected_day in expected:
        if expected_day + timedelta(days=2) <= local_today:
            due_days.add(expected_day)
            if expected_day not in satisfied:
                missed.append(expected_day)

    # A satisfied expected day breaks the trailing missed run whether or not it
    # is due yet; an unsatisfied day not yet due is neither missed nor breaking
    # (ADR 030).
    trailing: list[date] = []
    for expected_day in reversed(expected):
        if expected_day in satisfied:
            break
        if expected_day not in due_days:
            continue
        trailing.append(expected_day)
    trailing.reverse()

    return AttendanceEvaluation(
        timezone=timezone,
        local_today=local_today,
        window_start=window_start,
        expected_days=tuple(expected),
        satisfied_days=tuple(sorted(satisfied)),
        missed_days=tuple(missed),
        trailing_streak_start=trailing[0] if trailing else None,
        trailing_streak_last=trailing[-1] if trailing else None,
        trailing_streak_length=len(trailing),
    )
