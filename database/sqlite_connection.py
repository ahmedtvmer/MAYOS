"""SQLite connections opened by the API."""

import re
import sqlite3
from collections.abc import Callable
from functools import lru_cache
from os import PathLike
from time import perf_counter
from typing import Literal

from utils.env_flags import env_flag

SQLITE_BUSY_TIMEOUT_MS = 5000
LITESTREAM_ENV = "MAYOS_LITESTREAM"
StoreKind = Literal["catalog", "ledger"]
QueryRecorder = Callable[[StoreKind, str, float], None]
_query_recorder: QueryRecorder | None = None
_SQL_TOKENS = re.compile(
    r"--[^\n]*(?:\n|$)|/\*.*?\*/|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|"
    r"`(?:``|[^`])*`|\[[^\]]*\]|[A-Za-z_]+|[();=]",
    re.DOTALL,
)


def set_query_recorder(recorder: QueryRecorder | None) -> None:
    """Install an in-memory recorder receiving only kind, operation and milliseconds.

    The API owns this process-wide hook. Scripts leave it unset. All recorder
    and clock failures are discarded without logging SQL or affecting SQLite.
    """
    global _query_recorder
    _query_recorder = recorder


@lru_cache(maxsize=1024)
def _operation(sql: str) -> str:
    # Skip comments, quoted text and CTE bodies; RETURNING does not make a write a read.
    depth = 0
    for match in _SQL_TOKENS.finditer(sql):
        token = match.group()
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif depth == 0 and token[0].isalpha():
            keyword = token.upper()
            if keyword in {"WITH", "RECURSIVE"}:
                continue
            if keyword in {"SELECT", "VALUES", "EXPLAIN"}:
                return "read"
            if keyword in {"COMMIT", "END"}:
                return "commit"
            if keyword == "PRAGMA":
                return _pragma_operation(sql, match.end())
            if keyword in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER",
                           "BEGIN", "ROLLBACK", "SAVEPOINT", "RELEASE", "ATTACH", "DETACH", "VACUUM", "REINDEX", "ANALYZE"}:
                return "write"
    return "write"


def _pragma_operation(sql: str, offset: int) -> str:
    tokens = [match.group().upper() for match in _SQL_TOKENS.finditer(sql, offset)]
    if "=" in tokens or any(token in {"OPTIMIZE", "WAL_CHECKPOINT", "INCREMENTAL_VACUUM"} for token in tokens):
        return "write"
    # SQLite also accepts PRAGMA name(value) for settings, unlike table_info(table).
    settings = {"JOURNAL_MODE", "SYNCHRONOUS", "FOREIGN_KEYS", "BUSY_TIMEOUT", "WAL_AUTOCHECKPOINT",
                "USER_VERSION", "APPLICATION_ID", "CACHE_SIZE", "MMAP_SIZE", "LOCKING_MODE"}
    return "write" if "(" in tokens and settings.intersection(tokens) else "read"


def _timed(connection, sql, call, *args):
    recorder = _query_recorder
    if recorder is None:
        return call(*args)
    started = None
    try:
        started = perf_counter()
    except Exception:
        pass  # Run SQLite outside the exception handler to preserve error chaining.
    if started is None:
        return call(*args)
    try:
        return call(*args)
    finally:
        try:
            elapsed_ms = (perf_counter() - started) * 1000
            recorder(connection.store_kind, _operation(sql) if sql is not None else "commit", elapsed_ms)
        except Exception:
            pass  # Observation must never replace the query's result or exception.


class TimedCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=(), /):
        return _timed(self.connection, sql, super().execute, sql, parameters)

    def executemany(self, sql, seq_of_parameters, /):
        return _timed(self.connection, sql, super().executemany, sql, seq_of_parameters)

    def executescript(self, sql_script, /):
        # Scripts are one write call, including any SQLite implicit pre-script commit.
        return _timed(self.connection, "CREATE", super().executescript, sql_script)


@lru_cache(maxsize=32)
def _cursor_type(factory: type[sqlite3.Cursor]) -> type[sqlite3.Cursor]:
    if issubclass(factory, TimedCursor):
        return factory
    if factory is sqlite3.Cursor:
        return TimedCursor
    return type("Timed" + factory.__name__, (TimedCursor, factory), {})


class TimedConnection(sqlite3.Connection):
    store_kind: StoreKind = "catalog"

    def cursor(self, factory=TimedCursor):
        if factory is not TimedCursor and isinstance(factory, type) and issubclass(factory, sqlite3.Cursor):
            factory = _cursor_type(factory)
        return super().cursor(factory)

    def execute(self, sql, parameters=(), /):
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql, seq_of_parameters, /):
        return self.cursor().executemany(sql, seq_of_parameters)

    def executescript(self, sql_script, /):
        return self.cursor().executescript(sql_script)

    def commit(self):
        return _timed(self, None, super().commit)

    def __exit__(self, exc_type, exc_value, traceback, /):
        if exc_type is None and self.in_transaction:
            return _timed(self, None, super().__exit__, exc_type, exc_value, traceback)
        return super().__exit__(exc_type, exc_value, traceback)


def connect_api_sqlite(database: str | PathLike[str], *, store_kind: StoreKind = "catalog") -> sqlite3.Connection:
    """Open a writer; shared metadata defaults to catalog for existing callers."""
    if store_kind not in ("catalog", "ledger"):
        raise ValueError("store_kind must be catalog or ledger")
    connection = sqlite3.connect(database, check_same_thread=False, factory=TimedConnection)
    connection.store_kind = store_kind
    connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};")
    if env_flag(LITESTREAM_ENV):
        connection.execute("PRAGMA wal_autocheckpoint = 0;")
    return connection
