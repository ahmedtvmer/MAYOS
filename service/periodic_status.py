"""Process-local status for the alert sweep and daily backup loops."""

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

ALERT_SWEEP_JOB = "Alert sweep"
DAILY_BACKUP_JOB = "Daily backup"

_JOB_INTERVALS = {
    ALERT_SWEEP_JOB: ("MAYOS_ALERT_SWEEP_INTERVAL_SECONDS", 3600.0),
    DAILY_BACKUP_JOB: ("MAYOS_DAILY_BACKUP_INTERVAL_SECONDS", 3600.0),
}
_PROCESS_STARTED_AT = datetime.now(UTC)


@dataclass(frozen=True)
class PeriodicRun:
    finished_at: datetime
    interval_seconds: float
    ok: bool
    error_class: str | None


_runs: dict[str, PeriodicRun] = {}


def record_run(job: str, interval_seconds: float, ok: bool, error_class: str | None) -> None:
    """Stores a completed run and the interval the loop used."""
    _runs[job] = PeriodicRun(datetime.now(UTC), interval_seconds, ok, error_class)


def get(job: str) -> PeriodicRun | None:
    """Returns the latest completed run for ``job``, if any."""
    return _runs.get(job)


def reset() -> None:
    """Clears recorded runs while preserving the process start time."""
    _runs.clear()


def process_started_at() -> datetime:
    """Returns when this process first loaded the status module."""
    return _PROCESS_STARTED_AT


def configured_interval_seconds(job: str) -> float:
    """Returns the configured loop interval, falling back to its default."""
    name, default = _JOB_INTERVALS[job]
    raw = os.getenv(name, str(default))
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using the default.", name, raw)
        return default


__all__ = [
    "ALERT_SWEEP_JOB",
    "DAILY_BACKUP_JOB",
    "PeriodicRun",
    "configured_interval_seconds",
    "get",
    "process_started_at",
    "record_run",
    "reset",
]
