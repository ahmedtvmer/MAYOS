"""Shared helpers for the service layer."""

from contextvars import ContextVar
from typing import Any

#: Request-scoped trainee identity. Survives asyncio thread-hops where
#: ``threading.local`` does not; every service entry point sets it via
#: :func:`bind_user`. Route layers must derive it from a verified JWT.
current_trainee: ContextVar[str | None] = ContextVar("mayos_trainee", default=None)


def bind_user(db: Any, trainee_id: str) -> str:
    """Mounts the trainee ledger on the calling thread; returns sanitized id."""
    clean_id = db._sanitize_username(trainee_id)
    current_trainee.set(clean_id)
    if db.active_user != clean_id:
        db.switch_user(clean_id)
    return clean_id
