"""API latency and errors, separate from streaming chat and probe traffic."""

import html
import math
from collections import defaultdict
from datetime import timedelta
from typing import Any

from svc.monitoring.measurements import LATENCY_BUCKETS_MS, percentile_estimate
from svc.monitoring.presentation import trend
from svc.monitoring.runtime import MonitoringView

# Shares are fractions of requests. Copy and warning state use this one policy.
ERROR_WARNING_THRESHOLDS = {"5xx": 0.01, "4xx": 0.10}


def _buckets(rows: list[dict[str, Any]]) -> dict[str, int]:
    combined: dict[str, int] = defaultdict(int)
    for row in rows:
        for bound, count in row["buckets"].items():
            combined[bound] += count
    return dict(combined)


def _latency(value: float | None) -> str:
    if value is None:
        return "No samples"
    if math.isinf(value):
        return f'&gt;{LATENCY_BUCKETS_MS[-1] / 1000:g} s'
    return f"~{value:g} ms"


def _percentile_cells(rows: list[dict[str, Any]]) -> str:
    buckets = _buckets(rows)
    return "".join(f"<td>{_latency(percentile_estimate(buckets, quantile))}</td>" for quantile in (0.5, 0.95, 0.99))


def _hourly_rows(view: MonitoringView, rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[row["hour_utc"]].append(row)
    return [grouped[(view.first_hour + timedelta(hours=index)).isoformat()] for index in range(view.hours)]


def _latency_tile(view: MonitoringView, traffic: str, label: str) -> str:
    rows = [row for row in view.rows if row["dimensions"]["traffic"] == traffic]
    routes: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        routes[row["dimensions"]["method"], row["dimensions"]["route"]].append(row)
    slowest = sorted(routes.items(), key=lambda item: percentile_estimate(_buckets(item[1]), 0.95) or 0, reverse=True)[:5]
    route_rows = "".join(
        f'<tr><td>{html.escape(method)} {html.escape(route)}</td>{_percentile_cells(group)}</tr>'
        for (method, route), group in slowest
    )
    values = [min(percentile_estimate(_buckets(group), 0.95) or 0, LATENCY_BUCKETS_MS[-1])
              for group in _hourly_rows(view, rows)]
    return (
        f'<section class="health-panel monitoring-tile"><h2>{label} response time</h2>'
        '<p>p50, p95 and p99 are estimates: the enclosing latency bucket upper bound. '
        'Slowest routes are ranked by estimated p95. Overflow is shown as a lower bound.</p>'
        + trend(values, f"{label} hourly estimated p95; empty hours shown as zero; "
                       f"overflow capped at {LATENCY_BUCKETS_MS[-1] / 1000:g} s")
        + '<div class="table-scroll"><table><thead><tr><th>Route</th><th>p50 estimate</th>'
        '<th>p95 estimate</th><th>p99 estimate</th></tr></thead><tbody><tr><th>Overall</th>'
        + _percentile_cells(rows) + '</tr>' + route_rows + '</tbody></table></div></section>'
    )


def _share(rows: list[dict[str, Any]], status: str) -> float:
    total = sum(row["count"] for row in rows)
    errors = sum(row["count"] for row in rows if row["dimensions"]["status_class"] == status)
    return errors / total if total else 0


def _error_tile(view: MonitoringView) -> str:
    rows = [row for row in view.rows if row["dimensions"]["traffic"] != "system"]
    panels = []
    for traffic, label in (("api", "API"), ("streaming", "Streaming chat")):
        group = [row for row in rows if row["dimensions"]["traffic"] == traffic]
        panels.append(f'<h3>{label}</h3><p>{sum(row["count"] for row in group):,} requests</p>')
        for status, threshold in ERROR_WARNING_THRESHOLDS.items():
            share = _share(group, status)
            warning = ' monitoring-warning' if share > threshold else ''
            value = f"{share:.2%}" if group else "No samples"
            panels.append(f'<p class="monitoring-rate{warning}">{status}: {value} '
                          f'(warning above {threshold:.0%})</p>')
            panels.append(trend([100 * _share(hour, status) for hour in _hourly_rows(view, group)],
                                f"{label} {status} hourly share, percent; empty hours shown as zero"))
    return '<section class="health-panel monitoring-tile"><h2>Error rate</h2>' + "".join(panels) + '</section>'


def _raw_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<tr><td>No requests recorded yet.</td></tr>'
    return "".join(
        '<tr>' + (f'<td>{html.escape(row["hour_utc"])}</td>' if "hour_utc" in row else '')
        + f'<td>{html.escape(row["traffic"])}</td><td>{html.escape(row["method"])}</td>'
        + f'<td>{html.escape(row["route"])}</td><td>{html.escape(row["status_class"])}</td>'
        + f'<td>{row["count"]:,}</td><td>{html.escape(str(row["latency_buckets"]))}</td></tr>'
        for row in rows
    )


def _raw_tables(snapshot: dict[str, Any], view: MonitoringView) -> str:
    headers = '<th>Traffic</th><th>Method</th><th>Route template</th><th>Status</th><th>Requests</th><th>Latency buckets (ms)</th>'
    hourly = [{"hour_utc": row["hour_utc"], **row["dimensions"], "count": row["count"],
               "latency_buckets": row["buckets"]} for row in view.rows]
    return (
        '<section class="health-panel usage-panel" id="api-request-metrics" data-api-request-metrics>'
        '<h2>API requests and latency</h2>'
        f'<p>{html.escape(snapshot["persistence"])} Latency buckets count requests in the first matching upper bound.</p>'
        '<h3>Since process start</h3><div class="table-scroll"><table class="usage-table"><thead><tr>'
        + headers + '</tr></thead><tbody>' + _raw_rows(snapshot["since_start"])
        + '</tbody></table></div><h3>Hourly, selected window (UTC)</h3>'
        '<div class="table-scroll"><table class="usage-table"><thead><tr><th>Hour UTC</th>'
        + headers + '</tr></thead><tbody>' + _raw_rows(hourly) + '</tbody></table></div></section>'
    )


class ApiProvider:
    key = "api"

    def __init__(self, metrics: Any) -> None:
        self.metrics = metrics
        self.measurements = metrics.measurements

    def sample(self) -> None:
        pass  # Requests observe their own completion; no periodic sampling needed.

    def render(self, view: MonitoringView) -> str:
        return (
            '<div class="monitoring-grid">'
            + _latency_tile(view, "api", "API")
            + _latency_tile(view, "streaming", "Streaming chat")
            + _error_tile(view) + '</div>'
            + '<p>Streaming chat includes player and coach assistant routes, timed through stream completion. '
            'Probe traffic (/healthz and /readyz) appears only in the raw tables. '
            'Error rates use HTTP response status; errors sent inside an already-started stream do not change it.</p>'
            + _raw_tables(self.metrics.snapshot(), view)
        )


def create_provider(app: Any) -> ApiProvider:
    return ApiProvider(app.state.request_metrics)
