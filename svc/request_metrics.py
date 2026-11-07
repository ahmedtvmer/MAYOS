"""Low-cardinality, privacy-safe request counters (ADR 072/097)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from svc.monitoring.measurements import HourlyMeasurements, LATENCY_BUCKETS_MS

logger = logging.getLogger(__name__)
_SYSTEM_TEMPLATES = frozenset({"/healthz", "/readyz"})
_STREAMING_TEMPLATES = frozenset({"/chat/messages", "/coach/assignments/{assignment_id}/assistant"})
_HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})


class RequestMetrics:
    """Process-local aggregates keyed only by route template and safe dimensions."""

    def __init__(self) -> None:
        self.started_at = datetime.now(UTC)
        self._lock = Lock()
        self._since_start: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self.measurements = HourlyMeasurements()

    @staticmethod
    def _new_count() -> dict[str, Any]:
        return {"count": 0, "latency_buckets": {str(bound): 0 for bound in LATENCY_BUCKETS_MS} | {"+Inf": 0}}

    @staticmethod
    def _bucket(count: dict[str, Any], elapsed_ms: float) -> None:
        for bound in LATENCY_BUCKETS_MS:
            if elapsed_ms <= bound:
                count["latency_buckets"][str(bound)] += 1
                return
        count["latency_buckets"]["+Inf"] += 1

    def record(self, route: str, method: str, status: int, elapsed_ms: float, at: datetime | None = None) -> None:
        if not route.startswith("/"):
            route = "<unmatched>"
        traffic = "system" if route in _SYSTEM_TEMPLATES else "streaming" if route in _STREAMING_TEMPLATES else "api"
        status_class = f"{status // 100}xx"
        safe_method = method if method in _HTTP_METHODS else "OTHER"
        key = (traffic, route, safe_method, status_class)
        instant = at or datetime.now(UTC)
        with self._lock:
            self._add(self._since_start, key, elapsed_ms)
            self.measurements.observe(
                "requests", elapsed_ms,
                {"traffic": traffic, "route": route, "method": safe_method, "status_class": status_class}, at=instant,
            )

    def _add(self, target: dict, key: tuple, elapsed_ms: float) -> None:
        count = target.setdefault(key, self._new_count())
        count["count"] += 1
        self._bucket(count, elapsed_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "persistence": "Hourly totals persist for 30 days; flushed about once a minute. Since-start totals reset on restart.",
                "started_at": self.started_at.isoformat(),
                "since_start": self._serialize(self._since_start),
                "hourly_last_7_days": [
                    {"hour_utc": row["hour_utc"], **row["dimensions"], "count": row["count"],
                     "latency_buckets": row["buckets"]}
                    for row in self.measurements.snapshot()
                ],
            }

    @staticmethod
    def _serialize(source: dict) -> list[dict[str, Any]]:
        rows = []
        for key, value in sorted(source.items(), key=lambda item: tuple(str(part) for part in item[0])):
            traffic, route, method, status_class = key
            rows.append({"traffic": traffic, "route": route, "method": method,
                         "status_class": status_class, "count": value["count"],
                         "latency_buckets": dict(value["latency_buckets"])})
        return rows

    def log_summary(self) -> None:
        rows = self.snapshot()["since_start"]
        api_requests = sum(row["count"] for row in rows if row["traffic"] != "system")
        system_requests = sum(row["count"] for row in rows if row["traffic"] == "system")
        logger.info(
            "API request metrics summary since process start: api=%s system=%s route_groups=%s",
            api_requests,
            system_requests,
            len(rows),
        )


class RequestMetricsMiddleware:
    """Pure ASGI middleware that observes only response status and route template."""

    def __init__(self, app: Any, metrics: RequestMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def capture(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            # Monitoring must never replace a response or the application's error.
            try:
                route_obj = scope.get("route")
                route = getattr(route_obj, "path", "<unmatched>")
                self.metrics.record(
                    route,
                    scope.get("method", "UNKNOWN"),
                    status,
                    (time.perf_counter() - started) * 1000,
                )
            except Exception:
                logger.exception("Request measurement failed")


async def summary_loop(metrics: RequestMetrics) -> None:
    """Emit at most one compact summary per UTC hour."""
    while True:
        now = datetime.now(UTC)
        delay = max(1, 3600 - (now.minute * 60 + now.second))
        await asyncio.sleep(delay)
        try:
            metrics.log_summary()
        except Exception:
            logger.exception("Request metrics summary failed")
