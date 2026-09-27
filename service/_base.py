"""Shared helpers for the service layer."""

from contextlib import contextmanager
from typing import Any, Iterator


@contextmanager
def ledger_scope(db: Any, ledger: Any, ledger_id: str) -> Iterator[Any]:
    """Yields the explicit ledger handle, opening (and closing) one when absent.

    Route layers pass the request's :class:`~database.ledger.handle.TrainingLedger`.
    Direct callers (scripts, tests, internal helpers without a handle) get a fresh
    handle opened through the store's gate-then-mount path. Either way the
    connection is explicit and never read from thread-local "current ledger" state.
    """
    if ledger is not None:
        yield ledger
        return
    with db.open_ledger(ledger_id) as opened:
        yield opened
