"""Real SQLite coverage for the database timing seam and its private aggregates."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
import sqlite_vec

from database import sqlite_connection
from database.sqlite_connection import connect_api_sqlite, set_query_recorder
from svc.monitoring.runtime import MonitoringView
from svc.monitoring.store import MetricsStore
from svc.monitoring.tiles.database import DatabaseProvider, create_provider


@pytest.fixture(autouse=True)
def isolated_recorder(monkeypatch):
    monkeypatch.setattr(sqlite_connection, "_query_recorder", None)


@pytest.mark.parametrize("store_kind", ("catalog", "ledger"))
@pytest.mark.parametrize("target", ("connection", "cursor"))
@pytest.mark.parametrize("method", ("execute", "executemany", "executescript"))
def test_sqlite_entry_points_record_one_call_without_retaining_private_inputs(
    tmp_path, monkeypatch, caplog, store_kind, target, method,
):
    private_id = "ledger-private-636"
    path = tmp_path / f"{private_id}.db"
    with closing(connect_api_sqlite(path, store_kind=store_kind)) as connection:
        connection.execute("CREATE TABLE private_records (private_payload TEXT)")
        provider = create_provider(None)
        ticks = count()
        monkeypatch.setattr(sqlite_connection, "perf_counter", lambda: next(ticks) / 1000)
        caller = connection if target == "connection" else connection.cursor()
        sql = "INSERT INTO private_records VALUES (?)"
        if method == "execute":
            caller.execute(sql, (private_id,))
        elif method == "executemany":
            caller.executemany(sql, [(private_id,), (private_id,)])
        else:
            caller.executescript(f"INSERT INTO private_records VALUES ('{private_id}');")

        rows = provider.measurements.snapshot()
        assert len(rows) == 1
        assert rows[0]["dimensions"] == {"store_kind": store_kind, "operation": "write"}
        assert rows[0]["count"] == 1
        assert rows[0]["total"] == pytest.approx(1)
        assert rows[0]["buckets"] == {"5": 1}
        serialized = json.dumps(rows)
        for private_fragment in (private_id, str(path), "INSERT", "private_records", "private_payload"):
            assert private_fragment not in serialized
            assert private_fragment not in caplog.text
        set_query_recorder(None)
        expected = 2 if method == "executemany" else 1
        assert connection.execute("SELECT count(*) FROM private_records").fetchone()[0] == expected


@pytest.mark.parametrize(
    ("sql", "operation"),
    [
        ("SELECT 1", "read"),
        ("-- INSERT private\n/* UPDATE private */ SELECT 1", "read"),
        ("WITH source AS (SELECT 'UPDATE private') SELECT * FROM source", "read"),
        ('WITH "INSERT"(n) AS (SELECT 1), other AS (SELECT 2) SELECT * FROM "INSERT"', "read"),
        ("WITH source AS (SELECT 1) INSERT INTO records SELECT * FROM source RETURNING n", "write"),
        ("EXPLAIN INSERT INTO records VALUES (1)", "read"),
        ("PRAGMA table_info(records)", "read"),
        ("PRAGMA user_version = 1", "write"),
        ("PRAGMA user_version(1)", "write"),
        ("COMMIT", "commit"),
    ],
)
def test_statement_operation_uses_the_outer_command(sql, operation):
    with closing(connect_api_sqlite(":memory:")) as connection:
        connection.execute("CREATE TABLE records (n)")
        connection.execute("BEGIN")
        provider = create_provider(None)
        connection.execute(sql).fetchall()
        rows = provider.measurements.snapshot()
        assert len(rows) == 1
        assert rows[0]["dimensions"]["operation"] == operation


def test_shortcut_cursors_remain_timed_and_fetching_is_not_a_call():
    with closing(connect_api_sqlite(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        provider = create_provider(None)
        cursor = connection.execute("SELECT 1 AS n UNION ALL SELECT 2")
        assert cursor.fetchone()["n"] == 1
        assert [row["n"] for row in cursor] == [2]
        assert cursor.execute("SELECT 3 AS n").fetchall()[0]["n"] == 3
        rows = provider.measurements.snapshot()
        assert len(rows) == 1
        assert rows[0]["dimensions"] == {"store_kind": "catalog", "operation": "read"}
        assert rows[0]["count"] == 2


def test_explicit_cursor_factories_keep_their_behavior_and_are_timed():
    class CustomCursor(sqlite3.Cursor):
        def execute(self, sql, parameters=(), /):
            self.executed = True
            return super().execute(sql, parameters)

    with closing(connect_api_sqlite(":memory:")) as connection:
        provider = create_provider(None)
        assert connection.cursor(factory=sqlite3.Cursor).execute("SELECT 1").fetchone() == (1,)
        cursor = connection.cursor(factory=CustomCursor)
        assert isinstance(cursor, CustomCursor)
        assert cursor.execute("SELECT 2").fetchone() == (2,)
        assert cursor.executed
        assert provider.measurements.snapshot()[0]["count"] == 2


def test_failed_queries_are_counted_without_replacing_the_original_exception(caplog):
    with closing(connect_api_sqlite(":memory:")) as connection:
        provider = create_provider(None)
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            connection.execute("SELECT * FROM private_missing_table")
        rows = provider.measurements.snapshot()
        assert rows[0]["dimensions"]["operation"] == "read"
        assert rows[0]["count"] == 1
        assert "private_missing_table" not in json.dumps(rows) + caplog.text


def test_manager_catalog_ledger_and_deletion_connections_supply_fixed_labels(fresh_store):
    provider = create_provider(None)
    fresh_store.catalog_conn.execute("SELECT 1").fetchone()
    fresh_store.deletions_conn.execute("SELECT 1").fetchone()
    with fresh_store.open_ledger("private-ledger-636") as ledger:
        ledger.conn.execute("SELECT 1").fetchone()
    rows = provider.measurements.snapshot()
    assert {row["dimensions"]["store_kind"] for row in rows} == {"catalog", "ledger"}
    assert all(set(row["dimensions"]) == {"store_kind", "operation"} for row in rows)
    assert "private-ledger-636" not in json.dumps(rows)


def test_explicit_and_context_commits_are_each_counted_once_and_rollbacks_are_not():
    with closing(connect_api_sqlite(":memory:")) as connection:
        connection.execute("CREATE TABLE records (n)")
        provider = create_provider(None)
        connection.execute("INSERT INTO records VALUES (1)")
        connection.commit()
        with connection:
            connection.execute("INSERT INTO records VALUES (2)")
        with pytest.raises(RuntimeError, match="abort transaction"), connection:
            connection.execute("INSERT INTO records VALUES (3)")
            raise RuntimeError("abort transaction")
        counts = {row["dimensions"]["operation"]: row["count"] for row in provider.measurements.snapshot()}
        assert counts == {"write": 3, "commit": 2}
        assert connection.execute("SELECT n FROM records ORDER BY n").fetchall() == [(1,), (2,)]


@pytest.mark.parametrize("failure", ("recorder", "clock_start", "clock_end"))
def test_timing_failure_preserves_results_commits_and_original_sqlite_errors(monkeypatch, failure):
    with closing(connect_api_sqlite(":memory:")) as connection:
        provider = create_provider(None)

        def broken_recorder(*_args):
            raise RuntimeError("recorder unavailable")

        def broken_clock():
            raise RuntimeError("clock unavailable")

        if failure == "recorder":
            set_query_recorder(broken_recorder)
        elif failure == "clock_start":
            monkeypatch.setattr(sqlite_connection, "perf_counter", broken_clock)
        else:
            ticks = count()

            def failing_end_clock():
                if next(ticks) % 2:
                    raise RuntimeError("clock unavailable")
                return 0

            monkeypatch.setattr(sqlite_connection, "perf_counter", failing_end_clock)
        connection.execute("CREATE TABLE records (n UNIQUE)")
        with connection:
            connection.executemany("INSERT INTO records VALUES (?)", [(1,), (2,)])
        connection.commit()
        assert connection.execute("SELECT n FROM records ORDER BY n").fetchall() == [(1,), (2,)]
        with pytest.raises(sqlite3.IntegrityError) as error:
            connection.execute("INSERT INTO records VALUES (1)")
        assert error.value.__context__ is None
        assert provider.measurements.snapshot() == []


def test_disabled_recorder_never_reads_the_clock_and_extensions_still_load(monkeypatch):
    def unexpected_clock():
        pytest.fail("disabled instrumentation must not read the clock")

    monkeypatch.setattr(sqlite_connection, "perf_counter", unexpected_clock)
    with closing(connect_api_sqlite(":memory:")) as connection:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
        assert connection.execute("SELECT vec_version()").fetchone()[0]
        connection.executescript("CREATE TABLE records (n); INSERT INTO records VALUES (1);")
        connection.commit()
        assert connection.cursor().execute("SELECT n FROM records").fetchall() == [(1,)]


def test_database_tile_round_trips_history_without_instrumenting_metrics_io(tmp_path):
    provider = create_provider(None)
    provider.record("catalog", "read", 5)
    provider.record("catalog", "write", 12)
    provider.record("ledger", "commit", 120001)
    now = datetime.now(UTC)
    store = MetricsStore(tmp_path / "catalog.db")
    store.write("before-restart", provider.key, provider.measurements.pending(), now)
    persisted = store.history("after-restart", now - timedelta(hours=1))
    assert sum(row["count"] for row in provider.measurements.snapshot()) == 3
    assert sum(row["count"] for row in persisted) == 3
    assert all(set(row["dimensions"]) == {"store_kind", "operation"} for row in persisted)
    page = DatabaseProvider().render(MonitoringView(1, now, persisted))
    assert "Database query duration" in page
    assert '<th>catalog</th><td>All operations</td><td>2</td><td>~5 ms</td><td>~25 ms</td><td>~25 ms</td>' in page
    assert '<th>ledger</th><td>All operations</td><td>1</td>' in page
    assert "&gt;120000 ms" in page
    assert "No samples" in page
    assert "Fetching rows" in page and "metrics store is not measured" in page
