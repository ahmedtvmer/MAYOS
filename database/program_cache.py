"""Revision-backed process cache for loaded active programs."""

from __future__ import annotations

import copy
import os
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from utils.logger import MayosLogger

logger = MayosLogger().get_logger(__name__)
_lock = threading.RLock()
_entries: OrderedDict[str, tuple[tuple[str, int, str, int], Any]] = OrderedDict()
_metrics = {"hits": 0, "misses": 0, "rebuild_seconds": 0.0, "last_report": 0.0}


class ReadOnlyList(list):
    def _immutable(self, *args, **kwargs):
        raise TypeError("Cached program data is read-only.")

    __setitem__ = __delitem__ = __iadd__ = __imul__ = append = clear = extend = insert = pop = remove = reverse = sort = _immutable

    def __deepcopy__(self, memo=None):
        memo = {} if memo is None else memo
        return copy.deepcopy(list(self), memo)


class ReadOnlyDict(dict):
    def _immutable(self, *args, **kwargs):
        raise TypeError("Cached program data is read-only.")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable
    __ior__ = _immutable

    def __deepcopy__(self, memo=None):
        memo = {} if memo is None else memo
        return copy.deepcopy(dict(self), memo)


def _freeze_value(value):
    if isinstance(value, list):
        return ReadOnlyList(_freeze_value(item) for item in value)
    if isinstance(value, dict):
        return ReadOnlyDict({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, Mapping):
        return ReadOnlyDict({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    if hasattr(value, "model_dump"):
        for name, nested in tuple(value.__dict__.items()):
            frozen = _freeze_value(nested)
            if frozen is not nested:
                object.__setattr__(value, name, frozen)
        object.__setattr__(value, "_program_cache_readonly", True)
        return value
    return value


def _freeze_program(program):
    """Return a read-only view before exposing a freshly loaded model."""
    return _freeze_value(program)


def _report_metrics(now: float) -> None:
    if now - _metrics["last_report"] >= 60:
        logger.info(
            "Active program cache metrics; hits=%d misses=%d total_rebuild_seconds=%.6f",
            _metrics["hits"], _metrics["misses"], _metrics["rebuild_seconds"],
        )
        _metrics["hits"] = 0
        _metrics["misses"] = 0
        _metrics["rebuild_seconds"] = 0.0
        _metrics["last_report"] = now


def ensure_revision_schema(conn, schema: str, tables: tuple[str, ...]) -> None:
    """Create a revision row and triggers in main or an attached schema."""
    prefix = f"{schema}." if schema else ""
    conn.execute(f"CREATE TABLE IF NOT EXISTS {prefix}program_revision (id INTEGER PRIMARY KEY CHECK(id=1), generation TEXT NOT NULL, counter INTEGER NOT NULL DEFAULT 0)")
    conn.execute(f"INSERT OR IGNORE INTO {prefix}program_revision(id, generation, counter) VALUES (1, ?, 0)", (secrets.token_hex(16),))
    for table in tables:
        for operation in ("INSERT", "UPDATE", "DELETE"):
            trigger = f"program_revision_{table}_{operation.lower()}"
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS {prefix}{trigger} AFTER {operation} ON {prefix}{table} "
                f"BEGIN UPDATE program_revision SET counter=counter+1 WHERE id=1; END"
            )


def rotate_revision(conn, schema: str = "main") -> None:
    prefix = f"{schema}." if schema else ""
    conn.execute(
        f"UPDATE {prefix}program_revision SET generation=?, counter=0 WHERE id=1",
        (secrets.token_hex(16),),
    )


def active_program(ledger, loader):
    """Return a cached active program when both database revisions match."""
    disabled = os.getenv("MAYOS_PROGRAM_CACHE", "1").strip().lower() in {"0", "false", "off", "no"}
    if disabled:
        return loader()
    limit = max(1, int(os.getenv("MAYOS_PROGRAM_CACHE_SIZE", "1000")))
    revision, in_transaction = ledger.active_program_cache_state()
    with _lock:
        entry = _entries.get(ledger.ledger_id)
        if entry is not None and entry[0] == revision:
            _entries.move_to_end(ledger.ledger_id)
            _metrics["hits"] += 1
            now = time.monotonic()
            _report_metrics(now)
            logger.debug("Active program cache hit")
            return entry[1]
        if entry is not None:
            _entries.pop(ledger.ledger_id, None)
    started = time.perf_counter()
    loaded = loader()
    elapsed = time.perf_counter() - started
    result = _freeze_program(loaded)
    with _lock:
        _metrics["misses"] += 1
        _metrics["rebuild_seconds"] += elapsed
        now = time.monotonic()
        if not in_transaction:
            current = _entries.get(ledger.ledger_id)
            # Concurrent loads can finish out of order; never replace a
            # newer cached revision with an older one.
            if current is None or current[0] == revision:
                _entries[ledger.ledger_id] = (revision, result)
                _entries.move_to_end(ledger.ledger_id)
            while len(_entries) > limit:
                _entries.popitem(last=False)
        _report_metrics(now)
        logger.debug("Active program cache miss; rebuild_seconds=%.6f", elapsed)
        return result


def evict(ledger_id: str) -> None:
    with _lock:
        _entries.pop(str(ledger_id), None)
