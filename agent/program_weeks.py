"""Shared pure ordering and position rules for Training program weeks."""

from dataclasses import dataclass
from typing import Any, Iterable

from pydantic import BaseModel


@dataclass(frozen=True)
class ProgramPosition:
    current_week: int
    week_count: int
    next_day_order: int


def default_week_name(week_order: int) -> str:
    return f"Week {week_order}"


def normalize_program_weeks(program: Any) -> list[dict[str, Any]]:
    """Return ordered plain week/day dictionaries, synthesizing one week for flat programs."""
    program_data = program.model_dump() if isinstance(program, BaseModel) else dict(program)
    raw_weeks = program_data.get("weeks") or [
        {"week_name": default_week_name(1), "week_order": 1, "days": program_data.get("days", [])}
    ]
    if len(raw_weeks) == 1 and program_data.get("days"):
        raw_weeks = [{**raw_weeks[0], "days": program_data["days"]}]
    weeks = [
        _normalize_week(raw_week, week_index)
        for week_index, raw_week in enumerate(raw_weeks, start=1)
    ]
    return sorted(weeks, key=lambda week: week["week_order"])


def _normalize_week(raw_week: Any, week_index: int) -> dict[str, Any]:
    week = raw_week.model_dump() if isinstance(raw_week, BaseModel) else dict(raw_week)
    week_order = int(week.get("week_order", week_index))
    days = []
    for day_index, raw_day in enumerate(week.get("days", []), start=1):
        day = raw_day.model_dump() if isinstance(raw_day, BaseModel) else dict(raw_day)
        day.setdefault("day_order", day_index)
        day["week_order"] = week_order
        days.append(day)
    days.sort(key=lambda day: int(day["day_order"]))
    return {
        **week,
        "week_name": str(week.get("week_name") or default_week_name(week_order)),
        "week_order": week_order,
        "days": days,
    }


def find_program_day(
    weeks: list[dict[str, Any]],
    week_order: int,
    *,
    day_order: int | None = None,
    day_name: str | None = None,
) -> dict[str, Any] | None:
    """Find a day inside one week, preferring its stable order over its name."""
    week = next((item for item in weeks if item["week_order"] == week_order), None)
    if week is None:
        return None
    if day_order is not None:
        day = next(
            (item for item in week["days"] if item["day_order"] == day_order),
            None,
        )
        if day is not None:
            return day
    if day_name is not None:
        return next(
            (item for item in week["days"] if item["day_name"] == day_name),
            None,
        )
    return None


def flatten_program_days(weeks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a flat day list from normalized weeks."""
    return [day for week in weeks for day in week["days"]]


def clamp_program_position(
    weeks: list[dict[str, Any]], week_order: int, day_order: int
) -> tuple[int, int]:
    """Keep a cursor on the closest existing week/day after a program edit."""
    if not weeks:
        return 1, 1
    available_weeks = [week["week_order"] for week in weeks]
    clamped_week = min(available_weeks, key=lambda value: (abs(value - week_order), value))
    days = weeks[available_weeks.index(clamped_week)]["days"]
    if not days:
        return clamped_week, 1
    available_days = [day["day_order"] for day in days]
    clamped_day = min(available_days, key=lambda value: (abs(value - day_order), value))
    return clamped_week, clamped_day


def progress_for_program(
    program: Any,
    completed_days: Iterable[tuple[int, int]],
    *,
    start_position: tuple[int, int] = (1, 1),
    latest_day_order: int | None = None,
) -> ProgramPosition:
    """Derive a version cursor from its structure and committed week/day pairs."""
    weeks = normalize_program_weeks(program)
    if not weeks:
        return ProgramPosition(current_week=1, week_count=1, next_day_order=1)

    current_position = _first_unfinished_position(
        weeks, set(completed_days), start_position
    )
    if current_position is not None:
        return current_position
    return _repeat_final_week(weeks[-1], latest_day_order, len(weeks))


def _first_unfinished_position(
    weeks: list[dict[str, Any]],
    completed_days: set[tuple[int, int]],
    start_position: tuple[int, int],
) -> ProgramPosition | None:
    start_week, start_day = start_position
    for week in weeks:
        week_order = week["week_order"]
        if week_order < start_week:
            continue
        for day in week["days"]:
            day_order = day["day_order"]
            if week_order == start_week and day_order < start_day:
                continue
            if (week_order, day_order) not in completed_days:
                return ProgramPosition(
                    current_week=week_order,
                    week_count=len(weeks),
                    next_day_order=day_order,
                )
    return None


def _repeat_final_week(
    last_week: dict[str, Any],
    latest_day_order: int | None,
    week_count: int,
) -> ProgramPosition:
    day_orders = [day["day_order"] for day in last_week["days"]]
    if not day_orders:
        next_day_order = 1
    elif latest_day_order not in day_orders:
        next_day_order = day_orders[0]
    else:
        next_day_order = day_orders[(day_orders.index(latest_day_order) + 1) % len(day_orders)]
    return ProgramPosition(
        current_week=last_week["week_order"],
        week_count=week_count,
        next_day_order=next_day_order,
    )
