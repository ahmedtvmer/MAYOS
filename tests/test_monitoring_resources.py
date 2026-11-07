"""Resource sampling from fixture proc files; no reads of the machine's proc view."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from svc.monitoring.runtime import MonitoringView
from svc.monitoring.store import MetricsStore
from svc.monitoring.tiles.resources import RESOURCE_WARNING_THRESHOLDS, ResourcesProvider, create_provider

INITIAL_STAT = (
    "cpu 100 20 30 800 50 10 5 5 100 20\n"
    "cpu0 50 10 15 400 25 5 2 3 50 10\n"
    "cpu1 50 10 15 400 25 5 3 2 50 10\n"
    "intr 1000\n"
)
NEXT_STAT = (
    "cpu 140 20 40 830 60 10 10 10 120 20\n"
    "cpu0 70 10 20 415 30 5 5 5 60 10\n"
    "cpu1 70 10 20 415 30 5 5 5 60 10\n"
)


@pytest.fixture
def proc_root(tmp_path):
    root = tmp_path / "fixture-proc"
    root.joinpath("self").mkdir(parents=True)
    root.joinpath("stat").write_text(INITIAL_STAT, encoding="ascii")
    root.joinpath("meminfo").write_text(
        "MemTotal: 8192000 kB\nMemFree: 512000 kB\nMemAvailable: 2048000 kB\n", encoding="ascii",
    )
    root.joinpath("loadavg").write_text("1.25 2.50 3.75 2/123 456\n", encoding="ascii")
    root.joinpath("self", "status").write_text(
        "Name:\tapi\nVmSize:\t1048576 kB\nVmRSS:\t262144 kB\n", encoding="ascii",
    )
    return root


@pytest.fixture
def resources(proc_root, tmp_path, monkeypatch):
    volume = tmp_path / "catalog-volume"
    volume.mkdir()

    def disk_usage(path):
        if path != volume:
            raise OSError("not the catalog volume")
        return SimpleNamespace(total=1000, used=600, free=400)

    monkeypatch.setattr("svc.monitoring.tiles.resources.shutil.disk_usage", disk_usage)
    return ResourcesProvider(lambda: volume, proc_root=proc_root)


def _page(provider, *, hours=1, at=None, rows=None):
    return provider.render(MonitoringView(
        hours, at or datetime.now(UTC), provider.measurements.snapshot() if rows is None else rows,
    ))


def test_fixture_samples_use_cpu_deltas_available_memory_and_process_rss(resources, proc_root):
    resources.sample()
    assert "cpu_percent" not in resources.current
    assert "Waiting for two CPU readings" in _page(resources)
    proc_root.joinpath("stat").write_text(NEXT_STAT, encoding="ascii")
    resources.sample()

    assert resources.current == pytest.approx({
        "cpu_count": 2, "cpu_percent": 60, "memory_percent": 75, "disk_percent": 60,
        "load_1": 1.25, "load_5": 2.50, "load_15": 3.75, "process_rss_mib": 256,
    })
    rows = {row["metric"]: row for row in resources.measurements.snapshot()}
    assert rows["cpu_percent"]["count"] == 1
    assert rows["memory_percent"]["count"] == 2
    page = _page(resources)
    assert "60.00%" in page and "256.00 MiB" in page
    assert "#616 watcher" in page and "Litestream" in page


@pytest.mark.parametrize(
    ("missing", "metrics"),
    [("stat", ("cpu_percent", "cpu_count")), ("meminfo", ("memory_percent",)),
     ("loadavg", ("load_1", "load_5", "load_15")), ("self/status", ("process_rss_mib",))],
)
def test_missing_proc_file_clears_current_reading_and_recovers(resources, proc_root, missing, metrics):
    resources.sample()
    path = proc_root / missing
    original = path.read_text(encoding="ascii")
    path.unlink()
    resources.sample()
    assert all(metric not in resources.current for metric in metrics)
    assert resources.unavailable
    assert "Unavailable" in _page(resources)
    assert resources.current["disk_percent"] == 60

    path.write_text(original, encoding="ascii")
    resources.sample()
    assert not resources.unavailable
    assert all(metric in resources.current for metric in metrics if metric != "cpu_percent")


def test_platform_without_proc_keeps_disk_and_renders_unavailable(resources, tmp_path):
    resources.proc_root = tmp_path / "no-proc-on-this-platform"
    resources.sample()
    assert resources.current == {"disk_percent": 60}
    assert set(resources.unavailable) == {"CPU", "Memory", "Load", "API memory"}
    assert "Unavailable" in _page(resources)
    assert "Data volume used" in _page(resources)


@pytest.mark.parametrize(
    ("name", "contents", "metric"),
    [("stat", "cpu invalid\n", "cpu_percent"),
     ("meminfo", "MemTotal: 0 kB\nMemAvailable: 1 kB\n", "memory_percent"),
     ("loadavg", "nan 0 1\n", "load_1"),
     ("self/status", "VmRSS: -1 kB\n", "process_rss_mib")],
)
def test_malformed_proc_reading_is_unavailable_without_breaking_other_samples(
    resources, proc_root, name, contents, metric,
):
    proc_root.joinpath(name).write_text(contents, encoding="ascii")
    resources.sample()
    assert metric not in resources.current
    assert resources.unavailable
    assert resources.current["disk_percent"] == 60
    assert "Unavailable" in _page(resources)


@pytest.mark.parametrize("stat", [INITIAL_STAT, INITIAL_STAT.replace("100 20 30 800", "1 0 0 0")])
def test_unchanged_or_reset_cpu_counters_never_report_a_false_rate(resources, proc_root, stat):
    resources.sample()
    proc_root.joinpath("stat").write_text(stat, encoding="ascii")
    resources.sample()
    assert "cpu_percent" not in resources.current
    proc_root.joinpath("stat").write_text(NEXT_STAT, encoding="ascii")
    resources.sample()
    assert 0 <= resources.current["cpu_percent"] <= 100


def test_disk_failure_does_not_discard_proc_samples(resources, monkeypatch):
    def unavailable_disk(_path):
        raise OSError("volume unavailable")

    monkeypatch.setattr("svc.monitoring.tiles.resources.shutil.disk_usage", unavailable_disk)
    resources.sample()
    assert "disk_percent" not in resources.current
    assert resources.current["memory_percent"] == 75
    assert resources.unavailable == ["Data volume"]


def test_render_reads_cached_values_only_and_marks_stale_samples(resources, proc_root, monkeypatch):
    resources.sample()
    sampled_at = resources.sampled_at
    for path in (proc_root / "stat", proc_root / "meminfo", proc_root / "loadavg", proc_root / "self/status"):
        path.unlink()

    def unexpected_disk(_path):
        raise AssertionError("render attempted filesystem sampling")

    monkeypatch.setattr("svc.monitoring.tiles.resources.shutil.disk_usage", unexpected_disk)
    page = _page(resources, at=sampled_at + timedelta(minutes=4))
    assert "75.00%" in page and "256.00 MiB" in page
    assert "stale" in page


def test_factory_resolves_catalog_volume_after_lifespan_initialization(proc_root, tmp_path, monkeypatch):
    app = SimpleNamespace(state=SimpleNamespace(db=None))
    provider = create_provider(app)
    provider.proc_root = proc_root
    provider.sample()
    assert provider.measurements.snapshot() == []
    app.state.db = SimpleNamespace(catalog_path=tmp_path / "catalog.db")

    def disk_usage(path):
        return SimpleNamespace(total=100, used=45 if path == tmp_path else 99)

    monkeypatch.setattr("svc.monitoring.tiles.resources.shutil.disk_usage", disk_usage)
    provider.sample()
    assert provider.current["disk_percent"] == 45
    assert provider.current["memory_percent"] == 75


@pytest.mark.parametrize("metric", RESOURCE_WARNING_THRESHOLDS)
def test_warning_colour_begins_above_the_displayed_threshold(resources, metric):
    threshold = RESOURCE_WARNING_THRESHOLDS[metric] * (2 if metric.startswith("load_") else 1)
    resources.current = {"cpu_count": 2, metric: threshold}
    assert "monitoring-warning" not in _page(resources)
    resources.current[metric] = threshold + 0.01
    assert "monitoring-warning" in _page(resources)


def test_hourly_trends_keep_exact_gauge_means_across_persistence_and_restart(
    resources, proc_root, tmp_path, monkeypatch,
):
    instant = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr("svc.monitoring.tiles.resources.datetime", Clock)
    resources.sample()  # 75%, not the enclosing latency bucket of 100.
    proc_root.joinpath("meminfo").write_text(
        "MemTotal: 8192000 kB\nMemAvailable: 1024000 kB\n", encoding="ascii",
    )
    instant += timedelta(minutes=1)
    resources.sample()  # 87.5%; hourly mean is 81.25%.
    store = MetricsStore(tmp_path / "catalog.db")
    store.write("previous", "resources", resources.measurements.pending(), instant)
    instant += timedelta(hours=1)
    proc_root.joinpath("meminfo").write_text(
        "MemTotal: 8192000 kB\nMemAvailable: 4096000 kB\n", encoding="ascii",
    )
    resources.sample()
    store.write("previous", "resources", resources.measurements.pending(), instant)
    rows = store.history("restarted", instant - timedelta(hours=24))
    memory = sorted((row for row in rows if row["metric"] == "memory_percent"), key=lambda row: row["hour_utc"])
    assert [(row["count"], row["total"]) for row in memory] == [(2, 162.5), (1, 50)]
    restarted = ResourcesProvider(lambda: tmp_path, proc_root=proc_root)
    page = _page(restarted, hours=24, at=instant, rows=rows)
    assert "81.25% 50.00%" in page
    assert "No samples yet" in page  # History must not masquerade as a current sample.
    assert "missing hours plotted at zero" in page
