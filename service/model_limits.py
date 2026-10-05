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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Literal, NoReturn

from service.analytics import ClientContext, UNKNOWN_CLIENT

logger = logging.getLogger(__name__)

#: Trial defaults: generous enough for real use, low enough to cap runaway spend.
DEFAULT_REQUESTS_PER_MINUTE = 20
DEFAULT_DAILY_TOKEN_LIMIT = 200_000

_WINDOW_SECONDS = 60.0

REQUEST_LIMIT_DETAIL = "Too many AI requests. Please wait a minute and try again."
DAILY_TOKEN_LIMIT_DETAIL = "You have reached your daily AI usage limit. Please try again tomorrow."


@dataclass(frozen=True)
class ModelAdmissionContext:
    role: str
    client: ClientContext
    background_tasks: Any | None = None
    defer_limit_hit: Callable[[str], None] | None = None


@dataclass(frozen=True)
class ModelLimitContext:
    kind: Literal["rate", "daily_tokens"]
    account_id: str
    role: str
    hit_id: str | None
    store: Any
    client: ClientContext


class ModelLimitExceeded(Exception):
    """Raised before any model call when an account is over its limit."""

    def __init__(
        self,
        detail: str,
        kind: Literal["rate", "daily_tokens"],
        context: ModelLimitContext | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.kind = kind
        self.context = context


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
_limit_hit_prune_lock = threading.Lock()
_limit_hit_pruned_day: str | None = None
#: The account that already claimed a request slot in this context, so a step
#: that calls the entry point more than once still counts as one request. Keyed
#: by account id (not a bare flag) so a different account in the same context is
#: still admitted.
_admitted: ContextVar[str | None] = ContextVar("mayos_model_admitted", default=None)


def reset_model_limits() -> None:
    """Clears in-process admission and retention state, plus the current context's admit flag."""
    global _limit_hit_pruned_day
    with _lock:
        _request_window.clear()
    with _limit_hit_prune_lock:
        _limit_hit_pruned_day = None
    _admitted.set(None)


def _check_request_window(account_id: str, now: float) -> int:
    """Drops expired timestamps and returns the current in-window request count."""
    window = _request_window.setdefault(account_id, deque())
    while window and now - window[0] >= _WINDOW_SECONDS:
        window.popleft()
    return len(window)


def record_model_limit_hit(db: Any, account_id: str, kind: Literal["rate", "daily_tokens"]) -> str | None:
    """Best-effort refusal telemetry; a catalog outage must preserve the 429."""
    try:
        hit_id = db.record_model_limit_hit(account_id, kind)
    except Exception:
        logger.exception("Failed to record %s model-limit hit for account %s", kind, account_id)
        return None
    _prune_limit_hits_once_daily(db)
    return str(hit_id)


def _prune_limit_hits_once_daily(db: Any) -> None:
    """Claims one daily retention sweep, then prunes outside the admission lock."""
    global _limit_hit_pruned_day
    day = datetime.now(UTC).date().isoformat()
    with _limit_hit_prune_lock:
        if _limit_hit_pruned_day == day:
            return
        _limit_hit_pruned_day = day
    cutoff = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    try:
        db._prune_model_limit_hits(cutoff)
    except Exception:
        logger.exception("Failed to prune old model-limit hits")
def release_admission(token: Token[str | None] | None) -> None:
    """Releases a guard token returned by :func:`admit_model_request` (scope exit)."""
    if token is not None:
        _admitted.reset(token)


def admit_model_request(
    account_id: str | None,
    *,
    guard: bool = True,
    db: Any = None,
    context: ModelAdmissionContext | None = None,
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
    if _admission_is_skipped(account_id, guard, db):
        return None
    refusal = _check_admission_window(account_id, db)
    if refusal is not None:
        _raise_model_limit(account_id, db, context, refusal)
    return _admitted.set(account_id) if guard else None


def _admission_is_skipped(account_id: str | None, guard: bool, db: Any) -> bool:
    if not account_id:
        return True
    if db is None:
        raise RuntimeError(
            f"Account {account_id!r} admission has no store for the daily token check; "
            "refusing to skip the limit (ADR 041)."
        )
    if guard and _admitted.get() == account_id:
        return True
    return False


def _check_admission_window(
    account_id: str, db: Any
) -> tuple[Literal["rate", "daily_tokens"], str] | None:
    request_limit = request_limit_per_minute()
    token_limit = daily_token_limit()
    refusal: tuple[Literal["rate", "daily_tokens"], str] | None = None
    with _lock:
        now = time.monotonic()
        in_window = _check_request_window(account_id, now)
        if request_limit > 0 and in_window >= request_limit:
            refusal = ("rate", REQUEST_LIMIT_DETAIL)
        elif token_limit > 0:
            used = db.sum_model_tokens_for_account(account_id, utc_day_start_iso())
            if used >= token_limit:
                refusal = ("daily_tokens", DAILY_TOKEN_LIMIT_DETAIL)
        if refusal is None:
            _request_window.setdefault(account_id, deque()).append(now)
    return refusal


def _raise_model_limit(
    account_id: str,
    db: Any,
    context: ModelAdmissionContext | None,
    refusal: tuple[Literal["rate", "daily_tokens"], str],
) -> NoReturn:
    kind, detail = refusal
    deferred = context.defer_limit_hit if context is not None else None
    hit_id = None if deferred is not None else record_model_limit_hit(db, account_id, kind)
    if deferred is not None:
        deferred(kind)
    role = context.role if context is not None else "unknown"
    client = context.client if context is not None else UNKNOWN_CLIENT
    payload = ModelLimitContext(
        kind=kind,
        account_id=account_id,
        role=role,
        hit_id=hit_id,
        store=db,
        client=client,
    )
    if hit_id is not None:
        try:
            from service.ai_usage_analytics import AILimitContext, capture_ai_request_limited

            limit_context = AILimitContext(
                account_id=account_id,
                role=role,
                limit=kind,
                hit_id=hit_id,
                store=db,
                client=client,
            )
            if context is not None and context.background_tasks is not None:
                context.background_tasks.add_task(capture_ai_request_limited, limit_context)
            else:
                capture_ai_request_limited(limit_context)
        except Exception:
            logger.exception("Failed to capture model-limit refusal for account %s", account_id)
    raise ModelLimitExceeded(
        detail,
        kind,
        payload,
    )


__all__ = [
    "DAILY_TOKEN_LIMIT_DETAIL",
    "DEFAULT_DAILY_TOKEN_LIMIT",
    "DEFAULT_REQUESTS_PER_MINUTE",
    "ModelLimitExceeded",
    "ModelAdmissionContext",
    "ModelLimitContext",
    "REQUEST_LIMIT_DETAIL",
    "admit_model_request",
    "daily_token_limit",
    "record_model_limit_hit",
    "release_admission",
    "request_limit_per_minute",
    "reset_model_limits",
    "utc_day_start_iso",
]
