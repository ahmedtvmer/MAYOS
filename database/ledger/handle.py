"""Explicit ledger handle (ADR 041, phase B of #79).

A :class:`TrainingLedger` owns exactly one SQLite connection for one
``ledger_id``. It composes the ledger mixins unchanged, so their bodies keep
reading ``self.conn`` and the ledger transaction helpers; on the handle those
refer to its own connection rather than the facade's thread-local mount.

Callers obtain a handle from :meth:`database.database_manager.DatabaseManager.open_ledger`
*after* the registry/assignment gate has passed, and use it as a context manager
so the connection closes on exit::

    with db.open_ledger(ledger_id) as ledger:
        ledger.get_player_profile()

Registry and exercise-library methods stay on the app store; only ledger
methods live on the handle.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from database.ledger.auth import LedgerAuthMixin
from database.ledger.checkpoint_reviews import LedgerCheckpointReviewsMixin
from database.ledger.chat import LedgerChatMixin
from database.ledger.debriefs import LedgerDebriefsMixin
from database.ledger.onboarding import LedgerOnboardingMixin
from database.ledger.profile import LedgerProfileMixin
from database.ledger.schedule import LedgerScheduleMixin
from database.ledger.training_program import LedgerTrainingProgramMixin
from database.ledger.workouts import LedgerWorkoutsMixin


class TrainingLedger(
    LedgerAuthMixin,
    LedgerTrainingProgramMixin,
    LedgerWorkoutsMixin,
    LedgerCheckpointReviewsMixin,
    LedgerScheduleMixin,
    LedgerProfileMixin,
    LedgerOnboardingMixin,
    LedgerChatMixin,
    LedgerDebriefsMixin,
):
    """One player's ledger: a single connection plus the ledger operations on it."""

    def __init__(self, conn: sqlite3.Connection, ledger_id: str, backups_dir: Path):
        self._conn: sqlite3.Connection | None = conn
        # Ledger mixins read ``self.ledger_id`` and ``self.backups_dir``; keep
        # them wired to this handle's own ledger.
        self.ledger_id = ledger_id
        self.backups_dir = Path(backups_dir)
        # Transaction depth is per-handle and per-thread, mirroring the facade.
        self._local = threading.local()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError(f"Ledger '{self.ledger_id}' handle is closed.")
        return self._conn

    # Ledger transactions: re-entrant, on this handle's connection (ADR 020/033).
    @contextmanager
    def ledger_transaction(self) -> Iterator[None]:
        """Runs a group of ledger writes atomically.

        Re-entrant: nested calls join the outermost transaction. On error the
        whole group is rolled back and the exception re-raised.
        """
        conn = self.conn
        depth = getattr(self._local, "ledger_tx_depth", 0)
        self._local.ledger_tx_depth = depth + 1
        outermost = depth == 0
        original_isolation = conn.isolation_level
        if outermost:
            conn.isolation_level = None
            conn.execute("BEGIN")
            # Reserve this ledger's writer slot without locking attached catalog.
            conn.execute("UPDATE main.user_profile SET id = id WHERE 0")
        try:
            yield
        except Exception:
            if outermost:
                conn.execute("ROLLBACK")
            raise
        else:
            if outermost:
                conn.execute("COMMIT")
        finally:
            self._local.ledger_tx_depth = depth
            if outermost:
                conn.isolation_level = original_isolation

    def _commit_ledger(self) -> None:
        """Commits a standalone ledger write, or defers to the active transaction."""
        if getattr(self._local, "ledger_tx_depth", 0) == 0:
            self.conn.commit()

    def commit_ledger(self) -> None:
        """Public seam for ledger writers outside the database package."""
        self._commit_ledger()

    def close(self) -> None:
        """Commits and closes this handle's connection; idempotent."""
        conn = self._conn
        self._conn = None
        if conn is None:
            return
        try:
            conn.commit()
        except Exception:
            pass
        conn.close()

    def __enter__(self) -> "TrainingLedger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
