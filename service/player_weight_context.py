"""Pure renderer for the Player assistant's weight facts."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from service.weight_history import WeightTrend

_WEIGHT_CONTEXT_RELEVANCE = re.compile(
    r"\b(?:weight|bodyweight|kg|target|lose|gain|progress)\b|"
    r"وزن|وزني|كيلو|هدف|تخسيس|نزلت|زودت|تقدم",
    re.IGNORECASE,
)


def is_weight_context_relevant(query: str) -> bool:
    """Whether the Player asked about bodyweight or progress this turn."""
    return _WEIGHT_CONTEXT_RELEVANCE.search(query) is not None


def render_player_weight_context(
    trend: WeightTrend,
    target_weight_kg: float | None,
    *,
    as_of: date | None = None,
) -> str:
    """Renders date-stamped weight facts and Python-computed comparisons."""
    if not trend.points:
        history = "not available"
        change = "not available"
        latest_distance = "not available"
        fortnight_change = "not available"
        direction = "not available"
    else:
        history = ", ".join(
            f"{point.date.isoformat()}: {point.weight_kg:g} kg"
            for point in trend.points
        )
        change = _signed_kg(trend.change_kg) if trend.change_kg is not None else "not available"
        latest = trend.points[-1]
        latest_distance = (
            _signed_kg(latest.weight_kg - target_weight_kg)
            if target_weight_kg is not None
            else "not available"
        )
        today = as_of or datetime.now(UTC).date()
        window = tuple(point for point in trend.points if point.date >= today - timedelta(days=13))
        if len(window) < 2:
            fortnight_change = "not available"
            direction = "not available"
        else:
            first, current = window[0], window[-1]
            delta = current.weight_kg - first.weight_kg
            fortnight_change = _signed_kg(delta)
            if target_weight_kg is None:
                direction = "not available"
            else:
                start_distance = abs(first.weight_kg - target_weight_kg)
                end_distance = abs(current.weight_kg - target_weight_kg)
                direction = (
                    "toward target"
                    if end_distance < start_distance
                    else "away from target"
                    if end_distance > start_distance
                    else "unchanged"
                )

    target = f"{target_weight_kg:g} kg" if target_weight_kg is not None else "not available"
    return "\n".join(
        (
            "[PLAYER WEIGHT CONTEXT]",
            f"8-week dated points (oldest to newest): {history}",
            f"8-week change (latest minus earliest): {change}",
            f"Target weight: {target}",
            f"Latest weight minus target: {latest_distance}",
            f"14-day change (latest minus earliest): {fortnight_change}",
            f"14-day movement relative to target: {direction}",
        )
    )


def _signed_kg(value: float) -> str:
    return f"{value:+g} kg"
