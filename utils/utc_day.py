"""Shared UTC calendar-day boundaries for durable daily usage windows."""

from datetime import UTC, datetime, timedelta


def utc_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Returns the current UTC day start and the next UTC midnight."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def utc_day_start_iso(now: datetime | None = None) -> str:
    """Returns the current UTC day start as an ISO string."""
    return utc_day_bounds(now)[0].isoformat()
