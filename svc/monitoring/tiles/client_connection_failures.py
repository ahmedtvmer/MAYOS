"""Client connection-failure counts by hour, type, platform, and window."""

import html
from collections import defaultdict
from datetime import timedelta
from typing import Any

from svc.connection_failures import ConnectionFailureMetrics
from svc.monitoring.presentation import trend
from svc.monitoring.runtime import MonitoringView

_FAILURE_TYPES = (
    ("dns", "DNS"),
    ("connect_timeout", "Connect timeout"),
    ("receive_timeout", "Receive timeout"),
    ("connection_reset", "Connection reset"),
    ("other", "Other"),
)
_PLATFORMS = (("web", "Web"), ("android", "Android"))


def _hourly_details(hours: list[str], counts: list[int]) -> str:
    entries = "".join(
        f'<li><time datetime="{hour}">{hour[:10]} {hour[11:16]} UTC</time>: {count:,}</li>'
        for hour, count in zip(hours, counts) if count
    )
    if not entries:
        return '<p>No failures in this window.</p>'
    return '<details><summary>Hourly totals</summary><ul>' + entries + '</ul></details>'


class ClientConnectionFailureProvider:
    key = "client_connection_failures"

    def __init__(self, metrics: ConnectionFailureMetrics) -> None:
        self.measurements = metrics.measurements

    def sample(self) -> None:
        pass

    def render(self, view: MonitoringView) -> str:
        counts: dict[tuple[str, str, str], int] = defaultdict(int)
        for row in view.rows:
            dimensions = row["dimensions"]
            counts[
                row["hour_utc"],
                dimensions["failure_type"],
                dimensions["platform"],
            ] += row["count"]
        rows = [self._table_row(view, counts, failure, platform)
                for failure in _FAILURE_TYPES for platform in _PLATFORMS]
        return (
            '<section class="health-panel monitoring-tile" id="client-connection-failures">'
            '<h2>Client connection failures</h2>'
            '<p>Failures without an HTTP response, counted by UTC hour, type, and platform. '
            'Route templates are retained; account ids, request bodies, and query strings are not.</p>'
            '<div class="table-scroll"><table><thead><tr><th>Type</th><th>Platform</th>'
            '<th>Failures</th><th>Hourly counts</th></tr></thead><tbody>'
            + "".join(rows)
            + "</tbody></table></div></section>"
        )

    @staticmethod
    def _table_row(
        view: MonitoringView,
        counts: dict[tuple[str, str, str], int],
        failure: tuple[str, str],
        platform: tuple[str, str],
    ) -> str:
        failure_key, failure_label = failure
        platform_key, platform_label = platform
        hours = [
            (view.first_hour + timedelta(hours=index)).isoformat()
            for index in range(view.hours)
        ]
        hourly = [counts.get((hour, failure_key, platform_key), 0) for hour in hours]
        total = sum(hourly)
        chart = trend(
            hourly,
            f"{failure_label} on {platform_label}, hourly failures; empty hours shown as zero",
        )
        return (
            f"<tr><td>{html.escape(failure_label)}</td>"
            f"<td>{html.escape(platform_label)}</td><td>{total:,}</td>"
            f"<td>{chart}{_hourly_details(hours, hourly)}</td></tr>"
        )


def create_provider(app: Any) -> ClientConnectionFailureProvider:
    return ClientConnectionFailureProvider(app.state.connection_failure_metrics)
