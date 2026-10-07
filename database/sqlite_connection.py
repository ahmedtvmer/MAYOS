"""SQLite connections opened by the API."""

import sqlite3
from os import PathLike

from utils.env_flags import env_flag

SQLITE_BUSY_TIMEOUT_MS = 5000
LITESTREAM_ENV = "MAYOS_LITESTREAM"


def connect_api_sqlite(database: str | PathLike[str]) -> sqlite3.Connection:
    """Open an API writer connection with optional Litestream checkpointing."""
    connection = sqlite3.connect(database, check_same_thread=False)
    connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};")
    if env_flag(LITESTREAM_ENV):
        connection.execute("PRAGMA wal_autocheckpoint = 0;")
    return connection
