"""Fail-soft, non-personal inference measurements registered by the API."""

from __future__ import annotations

import logging
from collections.abc import Callable

from httpx import TimeoutException
from openai import APITimeoutError

from service.analytics import AI_USE_CASES
from utils.model_metering import current_usage_context

logger = logging.getLogger(__name__)
INFERENCE_PURPOSES = AI_USE_CASES | {"coach_roster_assistant"}
INFERENCE_OUTCOMES = frozenset({"ok", "error", "timeout", "interrupted", "truncated", "other"})
_recorder: Callable[[str, str, float, float | None], None] | None = None


def log_turn_exception(
    target: logging.Logger, message: str, error: BaseException, *, request_id: str | None = None,
) -> None:
    """Retain the traceback and correlation id without exception values or chains.

    SDK, validation and storage exceptions can embed private request data in
    their messages. A new exception keeps those values out of every formatter.
    """
    target.exception(
        "%s request_id=%s exception_type=%s", message,
        request_id or current_usage_context().turn_id or "unattributed",
        type(error).__name__,
        exc_info=(RuntimeError, RuntimeError("Exception details redacted"), error.__traceback__),
    )


def set_recorder(recorder: Callable[[str, str, float, float | None], None] | None) -> None:
    """Register the monitoring sink without importing the API layer."""
    global _recorder
    _recorder = recorder


def record_turn(purpose: str | None, outcome: str, latency_ms: float, ttft_ms: float | None) -> None:
    """Drop failed measurements; monitoring must never affect an answer."""
    try:
        if _recorder is not None:
            _recorder(
                purpose if purpose in INFERENCE_PURPOSES else "other",
                outcome if outcome in INFERENCE_OUTCOMES else "other",
                latency_ms,
                ttft_ms,
            )
    except Exception:
        logger.warning("Inference monitoring measurement failed; inference continues.")


def record_first_token(ttft_ms: float) -> None:
    """Keep the first model stream's existing timing, including tool-call chunks."""
    try:
        turn = current_usage_context().turn_state
        if turn is not None and turn.ttft_ms is None:
            turn.ttft_ms = ttft_ms
    except Exception:
        logger.warning("Inference first-token measurement failed; inference continues.")


def record_failure(error: BaseException) -> None:
    """Classify monitoring failures independently of the analytics outcome."""
    try:
        turn = current_usage_context().turn_state
        if turn is not None:
            timeout_types = (TimeoutError, TimeoutException, APITimeoutError)
            turn.monitoring_outcome = "timeout" if isinstance(error, timeout_types) else "error"
    except Exception:
        logger.warning("Inference failure measurement failed; inference continues.")
