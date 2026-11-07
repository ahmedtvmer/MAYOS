"""Disposable metrics history, deliberately outside the instrumented DB seam."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

RETENTION_DAYS = 30
_SCHEMA = """
CREATE TABLE IF NOT EXISTS hourly_metrics (
    process_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    hour_utc TEXT NOT NULL,
    metric TEXT NOT NULL,
    dimensions TEXT NOT NULL,
    count INTEGER NOT NULL,
    total REAL NOT NULL,
    buckets TEXT NOT NULL,
    PRIMARY KEY (process_id, provider, hour_utc, metric, dimensions)
);
CREATE INDEX IF NOT EXISTS hourly_metrics_hour ON hourly_metrics(hour_utc);
"""


class MetricsStore:
    def __init__(self, catalog_path: Path) -> None:
        self.path = Path(catalog_path).parent / "monitoring.db"

    def write(self, process_id: str, provider: str, rows: list[dict[str, Any]], now: datetime) -> None:
        # Each operation owns its connection and transaction, with no ATTACH,
        # ledger access, replication or connect_api_sqlite instrumentation.
        with closing(sqlite3.connect(self.path, timeout=1)) as connection:
            connection.executescript(_SCHEMA)
            with connection:
                connection.executemany(
                    """INSERT INTO hourly_metrics VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(process_id, provider, hour_utc, metric, dimensions)
                    DO UPDATE SET count=excluded.count, total=excluded.total, buckets=excluded.buckets""",
                    [self._values(process_id, provider, row) for row in rows],
                )
                connection.execute(
                    "DELETE FROM hourly_metrics WHERE hour_utc < ?",
                    ((now - timedelta(days=RETENTION_DAYS)).isoformat(),),
                )

    @staticmethod
    def _values(process_id: str, provider: str, row: dict[str, Any]) -> tuple:
        return (process_id, provider, row["hour_utc"], row["metric"],
                json.dumps(row["dimensions"], sort_keys=True), row["count"], row["total"],
                json.dumps(row["buckets"]))

    def history(self, process_id: str, cutoff: datetime) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path, timeout=1)) as connection:
            rows = connection.execute(
                """SELECT provider, hour_utc, metric, dimensions, count, total, buckets
                FROM hourly_metrics WHERE process_id != ? AND hour_utc >= ?""",
                (process_id, cutoff.isoformat()),
            ).fetchall()
        return [dict(provider=provider, hour_utc=hour, metric=metric, dimensions=json.loads(dimensions),
                     count=count, total=total, buckets=json.loads(buckets))
                for provider, hour, metric, dimensions, count, total, buckets in rows]
