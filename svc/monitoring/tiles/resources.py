"""Resource snapshots from the API's proc view and the catalog filesystem."""

from __future__ import annotations

import math
import shutil
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from svc.monitoring.measurements import HourlyMeasurements
from svc.monitoring.presentation import trend
from svc.monitoring.runtime import MonitoringView

# The same policy drives warning colours and their explanations. Load is per CPU.
RESOURCE_WARNING_THRESHOLDS = {
    "cpu_percent": 85.0,
    "memory_percent": 85.0,
    "disk_percent": 85.0,
    "load_1": 1.0,
    "load_5": 1.0,
    "load_15": 1.0,
    "process_rss_mib": 512.0,
}
RESOURCE_LABELS = {
    "cpu_percent": ("Server CPU", "%"),
    "memory_percent": ("Server memory used", "%"),
    "load_1": ("Server load, 1 minute", ""),
    "load_5": ("Server load, 5 minutes", ""),
    "load_15": ("Server load, 15 minutes", ""),
    "disk_percent": ("Data volume used", "%"),
    "process_rss_mib": ("API process resident memory", " MiB"),
}
READ_ERRORS = (OSError, UnicodeError, ValueError, KeyError, IndexError)


def _kib_fields(path: Path, names: tuple[str, ...]) -> dict[str, int]:
    fields = {}
    for line in path.read_text(encoding="ascii").splitlines():
        name, _, raw = line.partition(":")
        if name in names:
            amount, unit = raw.split()
            if unit != "kB" or int(amount) < 0:
                raise ValueError("invalid proc memory field")
            fields[name] = int(amount)
    return {name: fields[name] for name in names}


def _cpu_counters(path: Path) -> tuple[int, int, int]:
    lines = path.read_text(encoding="ascii").splitlines()
    label, *raw = lines[0].split()
    ticks = [int(counter) for counter in raw[:8]]
    if label != "cpu" or len(ticks) < 4 or any(counter < 0 for counter in ticks):
        raise ValueError("invalid proc CPU counters")
    # Guest time is already included in user/nice; do not add fields 9 and 10.
    idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
    count = sum(line.split()[0][3:].isdigit() for line in lines if line.startswith("cpu"))
    if not count:
        raise ValueError("missing proc CPU count")
    return sum(ticks), idle, count


def _hourly_means(view: MonitoringView, metric: str) -> list[float | None]:
    grouped: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for row in view.rows:
        if row["metric"] == metric:
            grouped[row["hour_utc"]][0] += row["total"]
            grouped[row["hour_utc"]][1] += row["count"]
    means = []
    for index in range(view.hours):
        total, count = grouped[(view.first_hour + timedelta(hours=index)).isoformat()]
        means.append(total / count if count else None)
    return means


def _resource_trend(view: MonitoringView, metric: str) -> str:
    label, unit = RESOURCE_LABELS[metric]
    means = _hourly_means(view, metric)
    if not any(mean is not None for mean in means):
        return '<p>No trend samples in this window.</p>'
    cells = " ".join("unavailable" if mean is None else f"{mean:.2f}{unit}" for mean in means)
    return (
        trend([mean if mean is not None else 0 for mean in means],
              f"{label}: hourly means{unit}; missing hours plotted at zero, not measured zero")
        + f'<details><summary>Hourly means, oldest to newest (UTC)</summary><p>{cells}</p></details>'
    )


class ResourcesProvider:
    key = "resources"

    def __init__(self, data_volume: Callable[[], Path | None], *, proc_root: Path = Path("/proc")) -> None:
        self.measurements = HourlyMeasurements()
        self.proc_root = Path(proc_root)
        self._data_volume = data_volume
        self._previous_cpu: tuple[int, int] | None = None
        self.current: dict[str, float] = {}
        self.unavailable: list[str] = []
        self.sampled_at: datetime | None = None

    def _sample_cpu(self) -> dict[str, float]:
        total, idle, count = _cpu_counters(self.proc_root / "stat")
        readings = {"cpu_count": float(count)}
        previous = self._previous_cpu
        self._previous_cpu = total, idle
        # First sample, reset counters, and unchanged counters cannot give a rate.
        if previous is not None:
            elapsed, resting = total - previous[0], idle - previous[1]
            if elapsed > 0 and 0 <= resting <= elapsed:
                readings["cpu_percent"] = 100 * (elapsed - resting) / elapsed
        return readings

    def _sample_memory(self) -> dict[str, float]:
        memory = _kib_fields(self.proc_root / "meminfo", ("MemTotal", "MemAvailable"))
        total, available = memory["MemTotal"], memory["MemAvailable"]
        if total <= 0 or available > total:
            raise ValueError("invalid proc memory totals")
        return {"memory_percent": 100 * (total - available) / total}

    def _sample_load(self) -> dict[str, float]:
        readings = self.proc_root.joinpath("loadavg").read_text(encoding="ascii").split()
        loads = {f"load_{minutes}": float(readings[index]) for index, minutes in enumerate((1, 5, 15))}
        if any(not math.isfinite(load) or load < 0 for load in loads.values()):
            raise ValueError("invalid proc load averages")
        return loads

    def _sample_process(self) -> dict[str, float]:
        memory = _kib_fields(self.proc_root / "self" / "status", ("VmRSS",))
        return {"process_rss_mib": memory["VmRSS"] / 1024}

    def _sample_proc(self) -> None:
        for label, reader in (("CPU", self._sample_cpu), ("Memory", self._sample_memory),
                              ("Load", self._sample_load), ("API memory", self._sample_process)):
            try:
                self.current.update(reader())
            except READ_ERRORS:
                self.unavailable.append(label)
                if label == "CPU":
                    self._previous_cpu = None

    def sample(self) -> None:
        self.current = {}
        self.unavailable = []
        self.sampled_at = datetime.now(UTC)
        volume = self._data_volume()
        if volume is None:
            self.unavailable.append("Data volume not initialized")
            self._previous_cpu = None
            return
        self._sample_proc()
        self._sample_disk(volume)
        # Percentages fit the 0..100 range. Exact sums/counts, not latency bucket
        # estimates, supply gauge means; MiB and load use those exact totals too.
        for metric, reading in self.current.items():
            self.measurements.observe(metric, reading, {}, at=self.sampled_at)

    def _sample_disk(self, volume: Path) -> None:
        try:
            usage = shutil.disk_usage(volume)
            if usage.total <= 0:
                raise ValueError("invalid filesystem capacity")
            self.current["disk_percent"] = 100 * usage.used / usage.total
        except (OSError, ValueError):
            self.unavailable.append("Data volume")

    def _metric_panel(self, view: MonitoringView, metric: str) -> str:
        label, unit = RESOURCE_LABELS[metric]
        reading = self.current.get(metric)
        threshold = RESOURCE_WARNING_THRESHOLDS[metric]
        if metric.startswith("load_"):
            threshold *= self.current.get("cpu_count", 0)
        warning = ' monitoring-warning' if reading is not None and threshold and reading > threshold else ''
        shown = f"{reading:.2f}{unit}" if reading is not None else "Unavailable"
        if metric == "cpu_percent" and "cpu_count" in self.current and reading is None:
            shown = "Waiting for two CPU readings"
        policy = f"Warning above {threshold:g}{unit}." if threshold else "Load warning unavailable without CPU count."
        if metric.startswith("load_") and threshold:
            policy += f' {RESOURCE_WARNING_THRESHOLDS[metric]:g} per CPU.'
        return (
            f'<section class="health-panel monitoring-tile{warning}"><h3>{label}</h3>'
            f'<p class="monitoring-rate{warning}">{shown}</p><p>{policy}</p>'
            + _resource_trend(view, metric) + '</section>'
        )

    def render(self, view: MonitoringView) -> str:
        status = "No samples yet."
        if self.sampled_at is not None:
            age = (view.now - self.sampled_at).total_seconds()
            status = f"Last sampled {self.sampled_at.isoformat()} (UTC)."
            if age > 180:
                status += " Current readings are stale (over 3 minutes old)."
        if self.unavailable:
            status += " Unavailable: " + ", ".join(self.unavailable) + "."
        return (
            '<section class="health-panel"><h2>Server resources</h2>'
            '<p>Sampled about once a minute off the request path. Current values are the latest sample; '
            'trends are hourly means. CPU is busy time between readings; idle includes I/O wait. '
            'Memory used is MemTotal minus MemAvailable. Load is runnable or uninterruptible tasks.</p>'
            '<p>Server CPU, memory and load use the whole-server view exposed by /proc inside the API; '
            'they are not container quota readings. Verify that view against the host on deployment. '
            'Disk covers the filesystem containing the catalog, not just MAYOS files. '
            'API memory is this API process RSS, not all container processes. '
            'Other containers, such as Litestream, wait for the #616 watcher.</p>'
            f'<p>{status}</p><div class="monitoring-grid">'
            + "".join(self._metric_panel(view, metric) for metric in RESOURCE_LABELS)
            + '</div></section>'
        )


def create_provider(app: Any) -> ResourcesProvider:
    # Discovery precedes lifespan initialization of the app-owned catalog.
    def data_volume() -> Path | None:
        database = getattr(app.state, "db", None)
        return Path(database.catalog_path).parent if database is not None else None

    return ResourcesProvider(data_volume)
