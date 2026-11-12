"""Bounded hourly histograms; callers supply only fixed, non-personal dimensions."""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

LATENCY_BUCKETS_MS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 120000)


def percentile_estimate(buckets: dict[str, int], quantile: float) -> float | None:
    """Return the first enclosing upper bound; overflow is infinity, empty is None."""
    if not 0 < quantile <= 1:
        raise ValueError("quantile must be in (0, 1]")
    rank = math.ceil(sum(buckets.values()) * quantile)
    if not rank:
        return None
    cumulative = 0
    for bound in LATENCY_BUCKETS_MS:
        cumulative += buckets.get(str(bound), 0)
        if cumulative >= rank:
            return float(bound)
    return math.inf


class HourlyMeasurements:
    """Cumulative process totals, with dirty snapshots retried after write failure.

    Dimension values must come from bounded vocabularies, never user input.
    There is no I/O here. Retention covers the page window by default; delayed
    client reports retain 30 days so an upload does not lose older dirty hours.
    """

    def __init__(self, *, retention_days: int = 7) -> None:
        self._lock = Lock()
        self._retention_days = retention_days
        self._rows: dict[tuple, dict[str, Any]] = {}
        self._dirty: set[tuple] = set()
        self._last_pruned_hour: datetime | None = None

    @staticmethod
    def _key(row: dict[str, Any]) -> tuple:
        return row["hour_utc"], row["metric"], tuple(sorted(row["dimensions"].items()))

    def observe(self, metric: str, value: float, dimensions: dict[str, str], *, at: datetime | None = None) -> None:
        if not math.isfinite(value) or value < 0:
            raise ValueError("measurement must be finite and non-negative")
        hour = (at or datetime.now(UTC)).astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        sample = {"hour_utc": hour.isoformat(), "metric": metric, "dimensions": dict(dimensions)}
        key = self._key(sample)
        with self._lock:
            row = self._rows.setdefault(key, {**sample, "count": 0, "total": 0.0, "buckets": {}})
            row["count"] += 1
            row["total"] += value
            bound = next((str(bound) for bound in LATENCY_BUCKETS_MS if value <= bound), "+Inf")
            row["buckets"][bound] = row["buckets"].get(bound, 0) + 1
            self._dirty.add(key)
            if self._last_pruned_hour is None or hour > self._last_pruned_hour:
                self._prune(hour)
                self._last_pruned_hour = hour

    def _prune(self, hour: datetime) -> None:
        cutoff = (hour - timedelta(days=self._retention_days)).isoformat()
        for key in tuple(self._rows):
            if key[0] < cutoff:
                del self._rows[key]
                self._dirty.discard(key)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(self._rows.values()))

    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = deepcopy([self._rows[key] for key in self._dirty])
            self._dirty.clear()
            return rows

    def retry(self, rows: list[dict[str, Any]]) -> None:
        with self._lock:
            self._dirty.update(self._key(row) for row in rows if self._key(row) in self._rows)
