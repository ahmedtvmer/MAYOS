"""Discover independent tile modules and isolate all monitoring failures."""

from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

from svc.monitoring.measurements import HourlyMeasurements
from svc.monitoring.store import MetricsStore

logger = logging.getLogger(__name__)
FLUSH_INTERVAL_SECONDS = 60
WINDOWS = {1: "1 hour", 24: "24 hours", 168: "7 days"}


@dataclass(frozen=True)
class MonitoringView:
    hours: int
    now: datetime
    rows: list[dict[str, Any]]

    @property
    def first_hour(self) -> datetime:
        return self.now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=self.hours - 1)


class MonitoringProvider(Protocol):
    """A tile module exports create_provider(app), returning this interface.

    Add the file under svc.monitoring.tiles; discovery needs no registry edit.
    recorders can use measurements.observe() from their existing timing seam.
    sample() runs once a minute in a worker thread for periodic resources or
    cached read-only outside-service reads. render() receives only its own rows.
    Keep all dimension vocabularies bounded and free of personal data.
    """

    key: str
    measurements: HourlyMeasurements

    def sample(self) -> None: ...
    def render(self, view: MonitoringView) -> str: ...


class Monitoring:
    def __init__(self, app: Any) -> None:
        self.process_id = uuid4().hex
        self.store: MetricsStore | None = None
        self.providers: list[MonitoringProvider] = []
        self._io_lock = Lock()
        self._discover(app)

    def _discover(self, app: Any) -> None:
        from svc.monitoring import tiles

        for module in pkgutil.iter_modules(tiles.__path__, tiles.__name__ + "."):
            if module.name.rsplit(".", 1)[-1].startswith("_"):
                continue
            try:
                provider = importlib.import_module(module.name).create_provider(app)
                if any(existing.key == provider.key for existing in self.providers):
                    raise ValueError("duplicate monitoring provider")
                self.providers.append(provider)
            except Exception:
                logger.exception("Monitoring provider could not load: %s", module.name)

    def flush(self) -> None:
        with self._io_lock:
            for provider in self.providers:
                self._flush_provider(provider)

    def _flush_provider(self, provider: MonitoringProvider) -> None:
        pending = []
        try:
            provider.sample()
        except Exception:
            logger.exception("Monitoring measurement failed: %s", provider.key)
        if self.store is None:
            return
        try:
            pending = provider.measurements.pending()
            self.store.write(self.process_id, provider.key, pending, datetime.now(UTC))
        except Exception:
            provider.measurements.retry(pending)
            logger.exception("Monitoring write failed: %s", provider.key)

    def render(self, hours: int) -> str:
        now = datetime.now(UTC)
        cutoff = MonitoringView(hours, now, []).first_hour
        with self._io_lock:
            rows, notice = self._history(cutoff)
            panels = []
            for provider in self.providers:
                try:
                    own = [row for row in rows if row["provider"] == provider.key]
                    own += provider.measurements.snapshot()
                    own = [row for row in own if cutoff.isoformat() <= row["hour_utc"] <= now.isoformat()]
                    panels.append(provider.render(MonitoringView(hours, now, own)))
                except Exception:
                    logger.exception("Monitoring tile failed: %s", provider.key)
                    panels.append('<section class="health-panel"><h2>Measurement unavailable</h2></section>')
        return notice + "".join(panels)

    def _history(self, cutoff: datetime) -> tuple[list[dict[str, Any]], str]:
        if self.store is None:
            return [], '<p>History storage unavailable; showing current process measurements.</p>'
        try:
            return self.store.history(self.process_id, cutoff), ""
        except Exception:
            logger.exception("Monitoring history read failed")
            return [], '<p>History unavailable; showing current process measurements.</p>'


async def flush_loop(monitoring: Monitoring) -> None:
    while True:
        await asyncio.to_thread(monitoring.flush)
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
