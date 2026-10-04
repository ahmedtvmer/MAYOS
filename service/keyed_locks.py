"""Process-local locks shared by service operations keyed to a ledger."""

from __future__ import annotations

import threading
import weakref
from collections.abc import Hashable


class KeyedLocks:
    """Keep weakly referenced locks for keys that currently have active users."""

    def __init__(self) -> None:
        self._locks: weakref.WeakValueDictionary[Hashable, threading.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._guard: threading.Lock = threading.Lock()

    def get(self, key: Hashable) -> threading.Lock:
        """Return a per-key lock; callers keep it referenced while acquiring it."""
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock
