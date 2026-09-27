"""Shared helpers for the service layer."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

#: Request-scoped trainee identity. Survives asyncio thread-hops where
#: ``threading.local`` does not; every service entry point sets it via
#: :func:`bind_user`. Route layers must derive it from a verified JWT.
current_trainee: ContextVar[str | None] = ContextVar("mayos_trainee", default=None)


@contextmanager
def ledger_scope(db: Any, ledger: Any, ledger_id: str) -> Iterator[Any]:
    """Yields the explicit ledger handle, opening (and closing) one when absent.

    Phase B routes pass in the request's :class:`TrainingLedger`. Direct callers
    (scripts, tests, internal helpers without a handle) get a fresh handle opened
    through the store's gate-then-mount path. Either way the connection is
    explicit and never read from thread-local "current ledger" state.

    The store is published to the ambient context (ADR 041) so agent/graph code
    reached from these services can still resolve the same app-owned instance
    until Phase B2 passes the handle explicitly.
    """
    from database.store import get_store, set_store

    try:
        already_set = get_store()
    except RuntimeError:
        already_set = None
    token = None if already_set is db else set_store(db)
    try:
        if ledger is not None:
            yield ledger
            return
        with db.open_ledger(ledger_id) as opened:
            yield opened
    finally:
        if token is not None:
            from database.store import reset_store

            reset_store(token)


def bind_user(db: Any, trainee_id: str) -> str:
    """Mounts the trainee ledger on the calling thread; returns sanitized id."""
    from database.store import set_store

    # Every service entry point is handed the store; publishing it here lets the
    # agent graphs and the metering callback (which have no explicit store)
    # resolve the same app-owned instance on this thread/task (ADR 041).
    set_store(db)
    clean_id = db._sanitize_username(trainee_id)
    current_trainee.set(clean_id)
    if db.active_user != clean_id:  # Phase B2: thread-local compatibility mount for agent/
        db.switch_user(clean_id)  # Phase B2: thread-local compatibility mount for agent/
    return clean_id
