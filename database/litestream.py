"""Replica key layout shared by deletion cleanup and disaster restore."""

import os
import re
from pathlib import PurePosixPath

DEFAULT_LITESTREAM_R2_PREFIX = "litestream"
LITESTREAM_R2_PREFIX_ENV = "LITESTREAM_R2_PREFIX"
LEDGER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def litestream_r2_prefix(prefix: str | None = None) -> str:
    """Return a canonical dedicated R2 prefix, defaulting to ``litestream``."""
    raw_prefix = prefix if prefix is not None else os.getenv(LITESTREAM_R2_PREFIX_ENV, "")
    normalized = str(raw_prefix).strip().rstrip("/") or DEFAULT_LITESTREAM_R2_PREFIX
    path = PurePosixPath(normalized)
    if (
        "\\" in normalized
        or path.is_absolute()
        or path.as_posix() != normalized
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise ValueError("Litestream R2 prefix must be a relative object-storage path.")
    return path.as_posix()


def litestream_replica_path(relative_database_path: str | PurePosixPath, prefix: str | None = None) -> str:
    """Map a data-root-relative SQLite path to its per-database R2 prefix."""
    relative = str(relative_database_path)
    path = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or path.is_absolute()
        or path.as_posix() != relative
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise ValueError("Database path must be a canonical relative POSIX path.")
    return f"{litestream_r2_prefix(prefix)}/{path.as_posix()}"


def litestream_ledger_replica_path(ledger_id: str, prefix: str | None = None) -> str:
    """Return the exact watched-directory replica path for one ledger id."""
    if not LEDGER_ID_RE.fullmatch(str(ledger_id)):
        raise ValueError("Ledger id must be canonical before resolving its Litestream replica.")
    return litestream_replica_path(PurePosixPath("users") / f"{ledger_id}.db", prefix)
