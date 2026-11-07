"""SQLite call durations, grouped only by fixed store kinds and operations."""

import math
from collections import defaultdict
from typing import Any

from database.sqlite_connection import StoreKind, set_query_recorder
from svc.monitoring.measurements import HourlyMeasurements, LATENCY_BUCKETS_MS, percentile_estimate
from svc.monitoring.runtime import MonitoringView

STORE_KINDS = ("catalog", "ledger")
OPERATIONS = ("read", "write", "commit")


def _percentile_cells(rows: list[dict[str, Any]]) -> str:
    buckets: dict[str, int] = defaultdict(int)
    for row in rows:
        for bound, count in row["buckets"].items():
            buckets[bound] += count
    cells = []
    for quantile in (0.5, 0.95, 0.99):
        estimate = percentile_estimate(buckets, quantile)
        if estimate is None:
            label = "No samples"
        elif math.isinf(estimate):
            label = f"&gt;{LATENCY_BUCKETS_MS[-1]:g} ms"
        else:
            label = f"~{estimate:g} ms"
        cells.append(f"<td>{label}</td>")
    return "".join(cells)


def _table_row(store_kind: str, operation: str, rows: list[dict[str, Any]]) -> str:
    return (f'<tr><th>{store_kind}</th><td>{operation}</td><td>{sum(row["count"] for row in rows):,}</td>'
            + _percentile_cells(rows) + '</tr>')


class DatabaseProvider:
    key = "database"

    def __init__(self) -> None:
        self.measurements = HourlyMeasurements()

    def record(self, store_kind: StoreKind, operation: str, elapsed_ms: float) -> None:
        if store_kind in STORE_KINDS and operation in OPERATIONS:
            self.measurements.observe("query_duration", elapsed_ms, {"store_kind": store_kind, "operation": operation})

    def sample(self) -> None:
        pass  # SQLite calls record their own completion without I/O.

    def render(self, view: MonitoringView) -> str:
        table_rows = []
        for store_kind in STORE_KINDS:
            rows = [row for row in view.rows if row["dimensions"]["store_kind"] == store_kind]
            table_rows.append(_table_row(store_kind, "All operations", rows))
            for operation in OPERATIONS:
                group = [row for row in rows if row["dimensions"]["operation"] == operation]
                table_rows.append(_table_row(store_kind, operation, group))
        return (
            '<section class="health-panel monitoring-tile" id="database-query-duration">'
            '<h2>Database query duration</h2>'
            '<p>p50, p95 and p99 are estimates: the enclosing latency bucket upper bound. '
            'Overflow is shown as a lower bound. Counts are calls, including failed calls, not rows. '
            'Catalog includes the shared deletion journal; ledger includes catalog reads through attached views.</p>'
            '<p>Times cover execute, executemany, executescript and commit, including cursor calls and '
            'successful transaction context exits. Each batch counts once; each script counts as one write '
            '(including any implicit pre-script commit). Fetching rows, row conversion after execute, '
            'connection opening, rollback(), backup and extension loading are not counted. '
            'The separate metrics store is not measured. No SQL, parameters or ledger ids are retained.</p>'
            '<div class="table-scroll"><table><thead><tr><th>Store kind</th><th>Operation</th><th>Calls</th>'
            '<th>p50 estimate</th><th>p95 estimate</th><th>p99 estimate</th></tr></thead><tbody>'
            + "".join(table_rows) + '</tbody></table></div></section>'
        )


def create_provider(app: Any) -> DatabaseProvider:
    provider = DatabaseProvider()
    set_query_recorder(provider.record)
    return provider
