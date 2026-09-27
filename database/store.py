"""Ambient access to the app-owned store (ADR 041, phase A of #79).

The application builds exactly one :class:`~database.database_manager.DatabaseManager`
at lifespan startup and hands it to every request through ``svc.dependencies.get_db``.
Agent and service modules no longer construct their own store. Entry points that
already receive the store pass it explicitly; the few call sites with no caller to
inject from (the model-metering callback, request admission, direct graph node
calls) read the active store set here.

Tests set a fresh store per test through the same seam, so no ``DatabaseManager``
singleton or ``_instance`` reset is needed, and ``get_store`` never silently
constructs one.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

_active_store: ContextVar[Any | None] = ContextVar("mayos_active_store", default=None)


def set_store(store: Any) -> Token:
    """Makes ``store`` the active store for the current context and returns the reset token."""
    return _active_store.set(store)


def reset_store(token: Token) -> None:
    """Restores the active store that was in place before the matching :func:`set_store`."""
    _active_store.reset(token)


def get_store() -> Any:
    """Return the active store, refusing to invent one when none is set."""
    store = _active_store.get()
    if store is None:
        raise RuntimeError(
            "No active DatabaseManager store is set. The app sets one at startup; "
            "tests and scripts must set a fresh store per test/run."
        )
    return store
