"""Weekly streak and Checkpoint progress for a player's training history."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from service._base import ledger_scope
from service.attendance import is_expected_day
from service.schedule import local_date_in, timezone_for_versions

CHECKPOINTS = (10, 25, 50, 100)


@dataclass(frozen=True)
class TrainingStatus:
    weekly_streak: int
    week_start: date
    week_done: int
    week_target: int
    mayos_workouts: int
    next_checkpoint: int
    workouts_to_next: int

    def as_dict(self) -> dict[str, Any]:
        """The stable API and commit-response representation."""
        values = asdict(self)
        values["week_start"] = self.week_start.isoformat()
        return values


@dataclass(frozen=True)
class TrainingStatusFacts:
    """Plain schedule and workout facts used by the pure calculation."""

    versions: list[dict[str, Any]]
    pauses: list[dict[str, Any]]
    performed_dates: list[Any]
    weekly_frequency: int
    local_today: date
    mayos_workouts: int


def saturday_week_start(day: date) -> date:
    """The Saturday that starts ``day``'s Saturday-to-Friday week."""
    return day - timedelta(days=(day.weekday() - 5) % 7)


def mayos_workout_count(committed_workouts: int, imported_workouts: int = 0) -> int:
    """Committed workouts completed in MAYOS, excluding imported history."""
    return max(0, int(committed_workouts) - max(0, int(imported_workouts)))


def next_checkpoint_for(mayos_workouts: int) -> int:
    """The smallest Checkpoint number greater than ``mayos_workouts``."""
    count = max(0, int(mayos_workouts))
    for checkpoint in CHECKPOINTS:
        if count < checkpoint:
            return checkpoint
    return (count // 100 + 1) * 100


def is_checkpoint(number: int) -> bool:
    return number in CHECKPOINTS or (number > 100 and number % 100 == 0)


def previous_checkpoint(number: int) -> int | None:
    previous = [checkpoint for checkpoint in CHECKPOINTS if checkpoint < number]
    if number > 100:
        previous.append(number - 100)
    return max(previous, default=None)


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _week_target(week_start: date, facts: TrainingStatusFacts) -> int:
    return weekly_target_for(
        week_start, facts.versions, facts.pauses, facts.weekly_frequency
    )


def weekly_target_for(
    week_start: date,
    versions: list[dict[str, Any]],
    pauses: list[dict[str, Any]],
    weekly_frequency: int,
) -> int:
    if not versions:
        return max(0, int(weekly_frequency))
    target = 0
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        if is_expected_day(versions, pauses, day):
            target += 1
    return target


def _week_done(week_start: date, performed_dates: list[date]) -> int:
    return sum(week_start <= day < week_start + timedelta(days=7) for day in performed_dates)


def _past_week_streak(facts: TrainingStatusFacts, performed_dates: list[date]) -> int:
    if not performed_dates:
        return 0
    first_week = saturday_week_start(performed_dates[0])
    week = saturday_week_start(facts.local_today) - timedelta(days=7)
    streak = 0
    while week >= first_week:
        target = _week_target(week, facts)
        if target > 0:
            if _week_done(week, performed_dates) < target:
                break
            streak += 1
        week -= timedelta(days=7)
    return streak


def compute_training_status(facts: TrainingStatusFacts) -> TrainingStatus:
    """Computes the player's Weekly streak and next Checkpoint from plain facts."""
    performed_dates = sorted(_as_date(value) for value in facts.performed_dates)
    current_week = saturday_week_start(facts.local_today)
    week_done = _week_done(current_week, performed_dates)
    week_target = _week_target(current_week, facts)
    streak = _past_week_streak(facts, performed_dates)
    if week_target > 0 and week_done >= week_target:
        streak += 1

    count = max(0, int(facts.mayos_workouts))
    checkpoint = next_checkpoint_for(count)
    return TrainingStatus(
        weekly_streak=streak,
        week_start=current_week,
        week_done=week_done,
        week_target=week_target,
        mayos_workouts=count,
        next_checkpoint=checkpoint,
        workouts_to_next=checkpoint - count,
    )


def imported_workout_count(db: Any, account_id: str | None) -> int:
    """Reads imported workout history before any ledger write transaction."""
    if not account_id:
        return 0
    with db.catalog_locked() as conn:
        row = conn.execute(
            "SELECT counts_json FROM account_imports WHERE account_id = ?"
            " ORDER BY imported_at DESC, rowid DESC LIMIT 1",
            (str(account_id),),
        ).fetchone()
    if row is None:
        return 0
    try:
        counts = json.loads(row[0])
        if not isinstance(counts, dict):
            return 0
        value = counts.get("workout_sessions", 0)
        return max(0, int(value)) if not isinstance(value, bool) else 0
    except (KeyError, TypeError, ValueError):
        return 0


def get_training_status(
    db: Any,
    ledger_id: str,
    account_id: str | None = None,
    ledger: Any | None = None,
    imported_workouts: int | None = None,
) -> TrainingStatus:
    """Loads ledger and import facts, then computes status without writing."""
    if imported_workouts is None:
        imported_workouts = imported_workout_count(db, account_id)
    with ledger_scope(db, ledger, ledger_id) as open_ledger:
        return _status_for_ledger(open_ledger, ledger_id, imported_workouts)


def _status_for_ledger(
    ledger: Any,
    ledger_id: str,
    imported_workouts: int,
) -> TrainingStatus:
    versions = ledger.list_training_schedules(ledger_id)
    performed_dates = ledger.list_performed_dates()
    program = ledger.get_active_program()
    timezone = timezone_for_versions(versions, "UTC")
    facts = TrainingStatusFacts(
        versions=versions,
        pauses=ledger.list_training_pauses(ledger_id),
        performed_dates=performed_dates,
        weekly_frequency=int(program.weekly_frequency) if program is not None else 0,
        local_today=local_date_in(datetime.now(UTC), timezone),
        mayos_workouts=mayos_workout_count(
            len(performed_dates), imported_workouts
        ),
    )
    return compute_training_status(facts)
