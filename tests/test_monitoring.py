"""Monitoring histogram boundaries and real, disposable SQLite persistence."""

import math
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from svc.monitoring.measurements import HourlyMeasurements, LATENCY_BUCKETS_MS, percentile_estimate
from svc.monitoring.runtime import Monitoring, MonitoringView
from svc.monitoring.store import MetricsStore
from svc.monitoring.tiles.api import ApiProvider, ERROR_WARNING_THRESHOLDS
from svc.request_metrics import RequestMetrics


def _monitoring():
    app = SimpleNamespace(state=SimpleNamespace(request_metrics=RequestMetrics()))
    return app.state.request_metrics, Monitoring(app)


@pytest.mark.parametrize("bound", LATENCY_BUCKETS_MS)
def test_bucket_edge_is_inclusive_and_next_sample_uses_next_bucket(bound):
    measurements = HourlyMeasurements()
    measurements.observe("latency", bound, {})
    measurements.observe("latency", bound + 0.01, {})
    buckets = measurements.snapshot()[0]["buckets"]
    following = next((value for value in LATENCY_BUCKETS_MS if value > bound), math.inf)
    assert percentile_estimate(buckets, 0.5) == bound
    assert percentile_estimate(buckets, 0.95) == following
    assert percentile_estimate(buckets, 0.99) == following


@pytest.mark.parametrize(
    ("buckets", "quantile", "expected"),
    [({}, 0.99, None), ({"5": 50, "10": 45, "25": 4, "+Inf": 1}, 0.5, 5),
     ({"5": 50, "10": 45, "25": 4, "+Inf": 1}, 0.95, 10),
     ({"5": 50, "10": 45, "25": 4, "+Inf": 1}, 0.99, 25), ({"+Inf": 1}, 0.99, math.inf)],
)
def test_percentile_rank_including_empty_and_overflow(buckets, quantile, expected):
    assert percentile_estimate(buckets, quantile) == expected


def test_restart_keeps_history_and_repeated_flush_does_not_double_count(tmp_path):
    metrics, monitoring = _monitoring()
    monitoring.store = MetricsStore(tmp_path / "catalog.db")
    metrics.record("/safe/{id}", "GET", 200, 12)
    monitoring.flush()
    metrics.record("/safe/{id}", "GET", 200, 24)
    monitoring.flush()
    monitoring.flush()

    restarted_metrics, restarted = _monitoring()
    restarted.store = MetricsStore(tmp_path / "catalog.db")
    restarted_metrics.record("/safe/{id}", "GET", 500, 6001)
    restarted.flush()
    rows = restarted.store.history("another-process", datetime.now(UTC) - timedelta(days=1))
    assert sum(row["count"] for row in rows) == 3
    assert sum(sum(row["buckets"].values()) for row in rows) == 3
    page = restarted.render(24)
    assert "3 requests" in page
    assert "~10000 ms" in page
    assert "monitoring-warning" in page


def test_pruning_retains_boundary_and_removes_only_expired_hours(tmp_path):
    now = datetime(2026, 11, 7, 12, tzinfo=UTC)
    store = MetricsStore(tmp_path / "catalog.db")
    for days in (31, 30, 29):
        measurements = HourlyMeasurements()
        at = now - timedelta(days=days)
        measurements.observe("requests", 5, {"route": "/safe"}, at=at)
        store.write(f"process-{days}", "api", measurements.pending(), at)
    store.write("current", "api", [], now)
    rows = store.history("current", now - timedelta(days=40))
    assert sorted(row["hour_utc"] for row in rows) == [
        (now - timedelta(days=30)).isoformat(), (now - timedelta(days=29)).isoformat(),
    ]


def test_failed_write_retries_newest_cumulative_total(tmp_path):
    metrics, monitoring = _monitoring()
    store = MetricsStore(tmp_path / "missing" / "catalog.db")
    monitoring.store = store
    metrics.record("/safe", "GET", 200, 10)
    monitoring.flush()  # Parent does not exist: a real SQLite write failure.
    metrics.record("/safe", "GET", 200, 30)
    assert "2 requests" in monitoring.render(1)
    store.path.parent.mkdir()
    monitoring.flush()
    rows = store.history("after-restart", datetime.now(UTC) - timedelta(hours=1))
    assert sum(row["count"] for row in rows) == 2
    assert sum(row["total"] for row in rows) == 40


def test_observations_during_a_flush_remain_pending(tmp_path):
    measurements = HourlyMeasurements()
    measurements.observe("requests", 10, {})
    first = measurements.pending()
    measurements.observe("requests", 20, {})
    store = MetricsStore(tmp_path / "catalog.db")
    store.write("process", "api", first, datetime.now(UTC))
    store.write("process", "api", measurements.pending(), datetime.now(UTC))
    rows = store.history("restart", datetime.now(UTC) - timedelta(hours=1))
    assert len(rows) == 1
    assert rows[0]["count"] == 2
    assert rows[0]["total"] == 30


def test_unflushed_snapshots_cannot_mutate_recorded_buckets():
    measurements = HourlyMeasurements()
    measurements.observe("requests", 10, {})
    snapshot = measurements.snapshot()
    snapshot[0]["buckets"]["10"] = 999
    assert measurements.snapshot()[0]["buckets"] == {"10": 1}


def test_streaming_and_probes_do_not_dominate_api_percentiles_or_errors():
    metrics = RequestMetrics()
    metrics.record("/fast", "GET", 200, 5)
    metrics.record("/chat/messages", "POST", 500, 90000)
    metrics.record("/coach/assignments/{assignment_id}/assistant", "POST", 200, 60000)
    metrics.record("/healthz", "GET", 500, 120000)
    metrics.record("/readyz", "GET", 400, 120000)
    rows = metrics.measurements.snapshot()
    html = ApiProvider(metrics).render(MonitoringView(24, datetime.now(UTC), rows))
    api_latency = html.split("API response time</h2>", 1)[1].split("</section>", 1)[0]
    assert api_latency.count("~5 ms") == 6  # Overall plus the single slowest route.
    assert "~120000 ms" not in api_latency
    errors = html.split("Error rate</h2>", 1)[1].split("</section>", 1)[0]
    api_errors, streaming_errors = errors.split("<h3>Streaming chat</h3>")
    assert "1 requests" in api_errors and "5xx: 0.00%" in api_errors
    assert "monitoring-warning" not in api_errors
    assert "2 requests" in streaming_errors and "5xx: 50.00%" in streaming_errors
    assert "monitoring-warning" in streaming_errors


@pytest.mark.parametrize("status", (400, 500))
def test_error_warning_begins_above_central_threshold(status):
    status_class = f"{status // 100}xx"
    threshold = ERROR_WARNING_THRESHOLDS[status_class]
    metrics = RequestMetrics()
    for index in range(100):
        metrics.record("/safe", "GET", status if index < round(100 * threshold) else 200, 5)
    provider = ApiProvider(metrics)
    at_boundary = provider.render(MonitoringView(1, datetime.now(UTC), metrics.measurements.snapshot()))
    assert "monitoring-warning" not in at_boundary
    metrics.record("/safe", "GET", status, 5)
    above = provider.render(MonitoringView(1, datetime.now(UTC), metrics.measurements.snapshot()))
    assert "monitoring-warning" in above


@pytest.mark.parametrize(("hours", "expected"), ((1, 1), (24, 2), (168, 3)))
def test_windows_filter_live_and_persisted_hourly_totals(tmp_path, monkeypatch, hours, expected):
    instant = datetime(2026, 11, 7, 12, 30, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr("svc.monitoring.runtime.datetime", Clock)
    metrics, monitoring = _monitoring()
    monitoring.store = MetricsStore(tmp_path / "catalog.db")
    for offset in (200, 48, 2):
        at = instant - timedelta(hours=offset)
        measurements = HourlyMeasurements()
        measurements.observe("requests", 5, {"route": "/old", "method": "GET", "traffic": "api", "status_class": "2xx"}, at=at)
        monitoring.store.write(f"previous-{offset}", "api", measurements.pending(), instant)
    metrics.record("/live", "GET", 200, 5, instant)
    assert f"<p>{expected} requests</p>" in monitoring.render(hours)


def test_a_failed_provider_leaves_other_tiles_and_persistence_available(tmp_path):
    class FailedProvider:
        key = "failed"

        def __init__(self):
            self.measurements = HourlyMeasurements()

        def sample(self):
            raise OSError("resource unavailable")

        def render(self, view):
            raise OSError("cached resource unavailable")

    metrics, monitoring = _monitoring()
    monitoring.providers.insert(0, FailedProvider())
    monitoring.store = MetricsStore(tmp_path / "catalog.db")
    metrics.record("/safe", "GET", 200, 5)
    monitoring.flush()
    page = monitoring.render(24)
    assert "Measurement unavailable" in page
    assert "API response time" in page and "1 requests" in page
    assert sum(row["count"] for row in monitoring.store.history("restart", datetime.now(UTC) - timedelta(days=1))) == 1


def test_independent_tile_file_is_discovered_sampled_persisted_and_rendered(tmp_path, monkeypatch):
    from svc.monitoring import tiles

    module = tmp_path / "example_tile.py"
    module.write_text(
        'from svc.monitoring.measurements import HourlyMeasurements\n'
        'class Provider:\n'
        '    key = "example"\n'
        '    def __init__(self): self.measurements = HourlyMeasurements()\n'
        '    def sample(self): self.measurements.observe("sample", 12, {"store_kind": "catalog"})\n'
        '    def render(self, view): return "<p>Example: " + str(sum(row["count"] for row in view.rows)) + "</p>"\n'
        'def create_provider(app): return Provider()\n', encoding="utf-8",
    )
    monkeypatch.setattr(tiles, "__path__", [str(tmp_path)])
    _, monitoring = _monitoring()
    monitoring.store = MetricsStore(tmp_path / "catalog.db")
    monitoring.flush()
    assert "<p>Example: 1</p>" in monitoring.render(1)
    rows = monitoring.store.history("restart", datetime.now(UTC) - timedelta(hours=1))
    assert len(rows) == 1 and rows[0]["metric"] == "sample"
    assert rows[0]["dimensions"] == {"store_kind": "catalog"}
