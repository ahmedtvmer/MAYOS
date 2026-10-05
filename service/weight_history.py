"""Dated Player weight facts stored in the Training ledger."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import math
from typing import Any

from service._base import ledger_scope
from service.schedule import local_date_in, timezone_for_versions
from service.weight_limits import MAX_WEIGHT_KG, MIN_WEIGHT_KG


@dataclass(frozen=True)
class WeightTrendPoint:
    """One date-only weight measurement."""

    date: date
    weight_kg: float


@dataclass(frozen=True)
class WeightTrend:
    """Ascending dated points and the change between the window endpoints."""

    points: tuple[WeightTrendPoint, ...]
    change_kg: float | None


@dataclass(frozen=True)
class WeightTrendQuery:
    """Window requested from one Player's Training ledger."""

    ledger_id: str
    weeks: int
    as_of: date | None = None


def player_local_date(ledger: Any, ledger_id: str, now: datetime | None = None) -> date:
    """Resolves a UTC instant to the Player's current schedule timezone day."""
    instant = now or datetime.now(UTC)
    versions = ledger.list_training_schedules(ledger_id)
    return local_date_in(instant, timezone_for_versions(versions, "UTC"))


def record_weight(
    ledger: Any,
    ledger_id: str,
    weight_kg: float,
    *,
    now: datetime | None = None,
) -> WeightTrendPoint:
    """Replaces the Player's local-day entry and updates the latest profile value."""
    if isinstance(weight_kg, bool) or not isinstance(weight_kg, (int, float)):
        raise ValueError("Weight must be a number.")
    weight = float(weight_kg)
    if not math.isfinite(weight) or not MIN_WEIGHT_KG <= weight <= MAX_WEIGHT_KG:
        raise ValueError(f"Weight must be between {MIN_WEIGHT_KG} and {MAX_WEIGHT_KG} kg.")
    day = player_local_date(ledger, ledger_id, now)
    profile = ledger.get_player_profile()
    if profile is None:
        raise ValueError("No profile yet; complete onboarding.")
    ledger.upsert_player_profile_with_weight_history(
        {**profile, "weight_kg": weight}, day.isoformat()
    )
    return WeightTrendPoint(date=day, weight_kg=weight)


def get_weight_trend(
    db: Any,
    query: WeightTrendQuery,
    ledger: Any | None = None,
) -> WeightTrend:
    """Returns entries in the inclusive last-N-weeks window, oldest first."""
    with ledger_scope(db, ledger, query.ledger_id) as handle:
        if isinstance(query.weeks, bool) or not isinstance(query.weeks, int) or not 1 <= query.weeks <= 52:
            raise ValueError("Weeks must be between 1 and 52.")
        end_date = query.as_of or player_local_date(handle, query.ledger_id)
        start_date = end_date - timedelta(weeks=query.weeks)
        rows = handle.list_weight_history(start_date.isoformat(), end_date.isoformat())

    points = tuple(
        WeightTrendPoint(date=date.fromisoformat(row["entry_date"]), weight_kg=row["weight_kg"])
        for row in rows
    )
    change = points[-1].weight_kg - points[0].weight_kg if len(points) >= 2 else None
    return WeightTrend(points=points, change_kg=change)
