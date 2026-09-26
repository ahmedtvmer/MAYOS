"""Low-level model usage metering hook (ADR 038).

A LangChain callback handler is attached to every model the downloader builds,
so each model call — ``invoke``, ``with_structured_output``, and ``stream`` —
meters itself without touching the call sites. The handler reads the current
account/role/purpose from a :class:`~contextvars.ContextVar` that the inference
entry points (``svc.llm``) set around the whole user turn; a call made with no
context (startup, eval scripts) is recorded unattributed rather than dropped.

This module stays dependency-light: it never imports the database or service
layers. The usage sink is registered once at startup by ``svc.app``
(``set_recorder(service.model_metering.record_model_usage)``); until then it is
a no-op that logs once at DEBUG. Every failure is swallowed so metering can
never break inference.
"""

import contextvars
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)

#: Characters-per-token heuristic used only when a provider returns no usage
#: metadata; the row is flagged ``estimated`` so the report can distinguish it.
_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class UsageContext:
    """The immutable account + role + purpose an inference is attributed to."""

    account_id: str | None
    role: str
    purpose: str | None


_usage_context: contextvars.ContextVar[UsageContext | None] = contextvars.ContextVar(
    "mayos_usage_context", default=None
)


def current_usage_context() -> UsageContext:
    """The active usage context, or an unattributed one when none is set."""
    return _usage_context.get() or UsageContext(account_id=None, role="unknown", purpose=None)


@contextmanager
def usage_context(
    account_id: str | None, role: str = "unknown", purpose: str | None = None
) -> Iterator[None]:
    """Sets the usage context for the duration of the block (per thread/task)."""
    token = _usage_context.set(UsageContext(account_id=account_id, role=role or "unknown", purpose=purpose))
    try:
        yield
    finally:
        _usage_context.reset(token)


def estimate_tokens_from_text(text: str) -> int:
    """Fallback token count (chars/4); 0 for empty text."""
    return max(0, len(text) // _CHARS_PER_TOKEN)


def _extract_usage(response: Any, prompt_chars: int) -> tuple[int, int, bool]:
    """Returns ``(input_tokens, output_tokens, estimated)`` from an ``LLMResult``.

    Prefers provider ``usage_metadata`` then ``llm_output`` token usage; a
    missing side falls back to the documented chars/4 estimate and flags the
    whole call as estimated.
    """
    input_tokens: int | None = None
    output_tokens: int | None = None
    produced_text: list[str] = []

    for generation_group in getattr(response, "generations", None) or []:
        for generation in generation_group:
            message = getattr(generation, "message", None)
            usage = getattr(message, "usage_metadata", None) if message is not None else None
            if usage:
                if usage.get("input_tokens") is not None:
                    input_tokens = int(usage["input_tokens"])
                if usage.get("output_tokens") is not None:
                    output_tokens = int(usage["output_tokens"])
            produced_text.append(str(getattr(generation, "text", "") or ""))

    llm_output = getattr(response, "llm_output", None) or {}
    token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
    if input_tokens is None:
        value = token_usage.get("prompt_tokens", token_usage.get("input_tokens"))
        if value is not None:
            input_tokens = int(value)
    if output_tokens is None:
        value = token_usage.get("completion_tokens", token_usage.get("output_tokens"))
        if value is not None:
            output_tokens = int(value)

    estimated = input_tokens is None or output_tokens is None
    if input_tokens is None:
        input_tokens = max(0, prompt_chars // _CHARS_PER_TOKEN)
    if output_tokens is None:
        output_tokens = estimate_tokens_from_text("".join(produced_text))
    return input_tokens, output_tokens, estimated


#: The sink that persists a recorded call. Registered once at startup by
#: ``svc.app`` (or explicitly by tests); the unregistered default is a no-op so
#: this module never imports the service layer.
_recorder: Callable[..., None] | None = None
_no_op_logged = False


def set_recorder(recorder: Callable[..., None] | None) -> None:
    """Registers the usage sink; ``None`` restores the no-op default."""
    global _recorder
    _recorder = recorder


def _no_op_recorder(**kwargs: Any) -> None:
    global _no_op_logged
    if not _no_op_logged:
        _no_op_logged = True
        logger.debug("No model usage recorder registered; metering records nothing.")


def record_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    estimated: bool,
    context: UsageContext | None = None,
) -> None:
    """Persists one metered call; never raises (metering must not break inference)."""
    try:
        active = context or current_usage_context()
        (_recorder or _no_op_recorder)(
            account_id=active.account_id,
            role=active.role,
            purpose=active.purpose,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated=estimated,
        )
    except Exception:  # pragma: no cover - defensive; logging only
        logger.exception("Model usage metering failed; inference continues.")


class MeteringCallback(BaseCallbackHandler):
    """Records one usage row per model call for the model it is attached to."""

    def __init__(self, model: str) -> None:
        super().__init__()
        self.model = model
        self._prompt_chars: dict[Any, int] = {}

    @staticmethod
    def _chars_from_messages(messages: Any) -> int:
        total = 0
        try:
            for group in messages or []:
                for message in group or []:
                    total += len(str(getattr(message, "content", "") or ""))
        except Exception:  # pragma: no cover - defensive
            return total
        return total

    def on_chat_model_start(self, serialized: Any, messages: Any, *, run_id: Any, **kwargs: Any) -> None:
        self._prompt_chars[run_id] = self._chars_from_messages(messages)

    def on_llm_start(self, serialized: Any, prompts: Any, *, run_id: Any, **kwargs: Any) -> None:
        self._prompt_chars[run_id] = sum(len(str(prompt or "")) for prompt in (prompts or []))

    def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
        prompt_chars = self._prompt_chars.pop(run_id, 0)
        try:
            input_tokens, output_tokens, estimated = _extract_usage(response, prompt_chars)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Could not extract model usage; skipping row.")
            return
        record_usage(self.model, input_tokens, output_tokens, estimated)

    def on_llm_error(self, error: Any, *, run_id: Any, **kwargs: Any) -> None:
        self._prompt_chars.pop(run_id, None)


__all__ = [
    "MeteringCallback",
    "UsageContext",
    "current_usage_context",
    "estimate_tokens_from_text",
    "record_usage",
    "set_recorder",
    "usage_context",
]
