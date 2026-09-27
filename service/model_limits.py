"""Per-account model rate limits (ADR 038, AC2).

Enforced at the inference entry, keyed by the **immutable account id** — never
by client IP or bearer suffix — so two accounts behind one IP are independent
and one account across two IPs/tokens shares one limit. The request window is
in-process (single API writer); day-to-date tokens are read from the catalog so
they survive a restart.

A *request* is one admitted user turn: a chat turn that makes several model
calls, or an onboarding step, counts once for the request limit while every
call's tokens are metered (ADR 038). The streamed chat route admits before the
stream starts, so streaming cannot bypass the limit.

The daily token cap is a **soft cap**: it is checked at admission from tokens
already recorded, and a turn's tokens land when its calls end, so an in-flight
turn can overshoot by at most that one turn (ADR 038).
"""

import logging
import os
import threading
import time
from collections import deque
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

#: Trial defaults: generous enough for real use, low enough to cap runaway spend.
DEFAULT_REQUESTS_PER_MINUTE = 20
DEFAULT_DAILY_TOKEN_LIMIT = 200_000

_WINDOW_SECONDS = 60.0

REQUEST_LIMIT_DETAIL = "Too many AI requests. Please wait a minute and try again."
DAILY_TOKEN_LIMIT_DETAIL = "You have reached your daily AI usage limit. Please try again tomorrow."


class ModelLimitExceeded(Exception):
    """Raised before any model call when an account is over its limit."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def request_limit_per_minute() -> int:
    """Per-account requests/minute; ``0`` disables the request limit."""
    return _int_env("MODEL_RATE_LIMIT_REQUESTS", DEFAULT_REQUESTS_PER_MINUTE)


def daily_token_limit() -> int:
    """Per-account tokens/UTC-day; ``0`` disables the daily token limit."""
    return _int_env("MODEL_DAILY_TOKEN_LIMIT", DEFAULT_DAILY_TOKEN_LIMIT)


def utc_day_start_iso(now: datetime | None = None) -> str:
    """Start of the current UTC calendar day as an ISO string (comparable form)."""
    moment = now or datetime.now(UTC)
    return moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


_lock = threading.Lock()
_request_window: dict[str, deque[float]] = {}
#: The account that already claimed a request slot in this context, so a step
#: that calls the entry point more than once still counts as one request. Keyed
#: by account id (not a bare flag) so a different account in the same context is
#: still admitted.
_admitted: ContextVar[str | None] = ContextVar("mayos_model_admitted", default=None)


def reset_model_limits() -> None:
    """Clears the in-process request window and the current context's admit flag (tests)."""
    with _lock:
        _request_window.clear()
    _admitted.set(None)


def _check_request_window(account_id: str, now: float) -> int:
    """Drops expired timestamps and returns the current in-window request count."""
    window = _request_window.setdefault(account_id, deque())
    while window and now - window[0] >= _WINDOW_SECONDS:
        window.popleft()
    return len(window)


def release_admission(token: Token[str | None] | None) -> None:
    """Releases a guard token returned by :func:`admit_model_request` (scope exit)."""
    if token is not None:
        _admitted.reset(token)


def admit_model_request(
    account_id: str | None, *, guard: bool = True, db: Any = None
) -> Token[str | None] | None:
    """Checks and reserves one request for ``account_id``; raises :class:`ModelLimitExceeded`.

    Unattributed calls (``account_id is None``) are never limited. The window
    count, the day-to-date token check, and the append run in **one critical
    section**, so concurrent turns for one account cannot all pass at L-1.

    With ``guard=True`` a second call for the same account inside the same
    thread/turn is a no-op and returns ``None``; otherwise a token is returned
    for the caller to hand to :func:`release_admission` when the scope exits.

    ``db`` is the app-owned store used for the day-to-date token check; callers
    pass it explicitly (ADR 041). An attributed call (``account_id`` set) with
    no store raises rather than silently skipping the daily token ceiling;
    unattributed calls are never limited.
    """
    if not account_id:
        return None
    if db is None:
        raise RuntimeError(
            f"Account {account_id!r} admission has no store for the daily token check; "
            "refusing to skip the limit (ADR 041)."
        )
    if guard and _admitted.get() == account_id:
        return None

    request_limit = request_limit_per_minute()
    token_limit = daily_token_limit()
    with _lock:
        now = time.monotonic()
        in_window = _check_request_window(account_id, now)
        if request_limit > 0 and in_window >= request_limit:
            raise ModelLimitExceeded(REQUEST_LIMIT_DETAIL)
        if token_limit > 0:
            used = db.sum_model_tokens_for_account(account_id, utc_day_start_iso())
            if used >= token_limit:
                raise ModelLimitExceeded(DAILY_TOKEN_LIMIT_DETAIL)
        _request_window.setdefault(account_id, deque()).append(now)

    if guard:
        return _admitted.set(account_id)
    return None


__all__ = [
    "DAILY_TOKEN_LIMIT_DETAIL",
    "DEFAULT_DAILY_TOKEN_LIMIT",
    "DEFAULT_REQUESTS_PER_MINUTE",
    "ModelLimitExceeded",
    "REQUEST_LIMIT_DETAIL",
    "admit_model_request",
    "daily_token_limit",
    "release_admission",
    "request_limit_per_minute",
    "reset_model_limits",
    "utc_day_start_iso",
]
