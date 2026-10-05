"""Gateway to the hosted inference service.

``LLM_MAX_CONCURRENT`` (default 1) bounds overlapping inference calls.

There are two entry surfaces because callers live in two worlds:

* ``run_inference`` — async callers on the event loop (the asyncio ``_SEMAPHORE``
  bounds overlap and the blocking call runs on a worker thread).
* ``inference_slot`` / ``run_inference_sync`` / ``bound_stream`` — the blocking
  sync graph paths used by the chat and onboarding endpoints, which already run
  on worker threads. They share a thread-safe gate (``_GATE``) sized by
  ``LLM_MAX_CONCURRENT``. ``bound_stream`` holds one slot for the whole streamed
  turn so streaming is bounded too, not just buffered calls.

Both surfaces honor ``LLM_MAX_CONCURRENT`` and fail fast (``TimeoutError``)
instead of piling requests up.

Every entry point also carries the caller's immutable account plus role,
purpose, and an admission flag bundled as an :class:`InferenceScope` (ADR 038).
Admission (the per-account model rate limit) and the usage context run before
the gate is taken, so no model call or stream can start while an account is over
its limit; the context attributes each metered model call to the account for the
whole turn. ``admit=False`` is for a route that already pre-admitted (the
streamed chat route, so it can refuse with a plain HTTP 429 before the stream
starts).
"""

import asyncio
import contextlib
import logging
import os
import threading
import time
import uuid
from contextvars import Token
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from service.analytics import ClientContext, UNKNOWN_CLIENT
from utils.model_metering import UsageContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InferenceScope:
    """The immutable attribution and admission input for inference calls.

    ``admit`` controls whether the entry point also enforces the per-account
    request/daily-token limit (``False`` for a route that already admitted).
    ``store`` is the app-owned :class:`~database.database_manager.DatabaseManager`
    used to admit the request and persist usage; it travels with the scope so no
    ambient/thread-local store lookup is needed (ADR 041).
    """

    account_id: str | None = None
    role: str = "unknown"
    purpose: str | None = None
    admit: bool = True
    store: Any = None
    client: ClientContext = UNKNOWN_CLIENT


@dataclass
class InferenceTurnState:
    """Mutable outcome and timing for one user turn, separate from attribution."""

    scope: InferenceScope
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    outcome: str = "ok"
    finish_reason: str | None = None
    latency_ms: int = 0
    _emitted: bool = field(default=False, init=False, repr=False)
    _completion_suppressed: bool = field(default=False, init=False, repr=False)
    _ready: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _emit_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _usage_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _pending_limit_hits: list[str] = field(default_factory=list, init=False, repr=False)
    _has_usage: bool = field(default=False, init=False, repr=False)
    background_tasks: Any = field(default=None, repr=False)

    def record_finish_reason(self, reason: str) -> None:
        self.finish_reason = reason

    def record_inference(self, outcome: str, latency_ms: int) -> None:
        if outcome != "ok":
            self.outcome = outcome
        self.latency_ms = min(self.latency_ms + max(0, latency_ms), 31_557_600)

    def mark_interrupted(self) -> None:
        self.outcome = "interrupted"

    def mark_error(self) -> None:
        if self.outcome == "ok":
            self.outcome = "error"

    def record_usage(self, model: str, input_tokens: int, output_tokens: int, estimated: bool) -> None:
        with self._usage_lock:
            self._has_usage = True

    @property
    def has_usage(self) -> bool:
        with self._usage_lock:
            return self._has_usage

    def defer_limit_hit(self, kind: str) -> None:
        with self._usage_lock:
            self._pending_limit_hits.append(kind)

    def flush_limit_hits(self) -> None:
        with self._usage_lock:
            pending, self._pending_limit_hits = self._pending_limit_hits, []
        if not self.scope.account_id or self.scope.store is None:
            return
        from service.ai_usage_analytics import AILimitContext, capture_ai_request_limited
        from service.model_limits import record_model_limit_hit

        for kind in pending:
            hit_id = record_model_limit_hit(self.scope.store, self.scope.account_id, kind)
            if hit_id is None:
                continue
            context = AILimitContext(
                account_id=self.scope.account_id,
                role=self.scope.role,
                limit=kind,
                hit_id=hit_id,
                store=self.scope.store,
                client=self.scope.client,
            )
            if self.background_tasks is not None:
                self.background_tasks.add_task(capture_ai_request_limited, context)
            else:
                capture_ai_request_limited(context)

    def suppress_completion(self) -> None:
        self._completion_suppressed = True

    def emit(self) -> None:
        self._ready.wait()
        with self._emit_lock:
            if self._emitted:
                return
            self._emitted = True
        if self._completion_suppressed:
            return
        try:
            from service.ai_usage_analytics import AIRequestContext, capture_ai_request_completed

            capture_ai_request_completed(
                AIRequestContext(
                    account_id=self.scope.account_id,
                    turn_id=self.turn_id,
                    role=self.scope.role,
                    purpose=self.scope.purpose,
                    store=self.scope.store,
                    client=self.scope.client,
                    latency_ms=self.latency_ms,
                    outcome=self.outcome,
                    finish_reason=self.finish_reason,
                )
            )
        except Exception:
            logger.exception("Could not emit AI usage analytics; inference result is unchanged.")

    def emit_after(self, ready_event: threading.Event) -> None:
        ready_event.wait()
        self.emit()


def register_ai_analytics_background_tasks(request: Any, background_tasks: Any) -> None:
    """Keeps deferred inference capture attached when an endpoint raises."""
    request.state.ai_analytics_background_tasks = background_tasks


@contextlib.contextmanager
def inference_turn(
    scope: InferenceScope,
    *,
    background_tasks: Any = None,
    state: InferenceTurnState | None = None,
    wait_for: threading.Event | None = None,
) -> Iterator[InferenceTurnState]:
    """Wraps inference and its caller-owned write, then emits one metered event.

    HTTP callers pass FastAPI background tasks so reads and capture happen after
    the response. Streaming callers may provide a pre-registered ``state`` and
    a completion event that the response background waits for.
    """
    turn = state or InferenceTurnState(scope)
    if background_tasks is not None:
        turn.background_tasks = background_tasks
    from utils.model_metering import UsageContext, usage_context

    turn_context = UsageContext(
        account_id=scope.account_id,
        role=scope.role,
        purpose=scope.purpose,
        store=scope.store,
        turn_id=turn.turn_id,
        turn_state=turn,
        on_finish_reason=turn.record_finish_reason,
        on_usage=turn.record_usage,
        on_limit_hit=turn.defer_limit_hit,
        background_tasks=turn.background_tasks,
    )
    try:
        with usage_context(turn_context):
            yield turn
    except BaseException as exc:
        from service.model_limits import ModelLimitExceeded

        if isinstance(exc, ModelLimitExceeded):
            if turn.has_usage:
                turn.mark_error()
            else:
                turn.suppress_completion()
        elif isinstance(exc, (asyncio.CancelledError, GeneratorExit, InterruptedError)):
            turn.mark_interrupted()
        else:
            turn.mark_error()
        raise
    finally:
        turn.flush_limit_hits()
        turn._ready.set()
        if wait_for is None:
            if background_tasks is not None:
                background_tasks.add_task(turn.emit)
            else:
                try:
                    turn.emit()
                except Exception:
                    logger.exception("Could not emit AI usage analytics; inference result is unchanged.")


def _max_concurrent() -> int:
    try:
        value = int(os.getenv("LLM_MAX_CONCURRENT", "1"))
    except (TypeError, ValueError):
        return 1
    return value if value >= 1 else 1


_SEMAPHORE = asyncio.Semaphore(_max_concurrent())

#: Thread-safe gate for the blocking graph paths. ``LLM_MAX_CONCURRENT`` is read
#: once, when the gate is first used, and never retuned mid-flight: replacing the
#: semaphore while requests still hold slots would let more work run than the cap.
#: ``reset_inference_gate`` exists for tests to re-read the value between runs.
_GATE_LOCK = threading.Lock()
_GATE: threading.Semaphore | None = None


def _inference_gate() -> threading.Semaphore:
    global _GATE
    with _GATE_LOCK:
        if _GATE is None:
            _GATE = threading.Semaphore(_max_concurrent())
        return _GATE


def reset_inference_gate() -> None:
    """Drops the cached gate so the next use re-reads ``LLM_MAX_CONCURRENT``.

    Only safe when no inference holds a slot; intended for tests and startup.
    """
    global _GATE
    with _GATE_LOCK:
        _GATE = None


def is_llm_loaded() -> bool:
    from utils import model_downloader

    return model_downloader._llm_instance is not None


def is_judge_loaded() -> bool:
    from utils import model_downloader

    return model_downloader._judge_llm_instance is not None


def is_coach_loaded() -> bool:
    from utils import model_downloader

    return model_downloader._coach_llm_instance is not None


async def warmup_llm() -> None:
    """Preloads the hosted player model on a worker thread. Judge stays lazy."""
    from utils.model_downloader import get_llm

    await asyncio.to_thread(get_llm)


@contextlib.contextmanager
def _usage_scope(scope: InferenceScope) -> Iterator[None]:
    """Admits one per-account request (unless disabled) and sets the usage context.

    Admission runs first, so an over-limit account is refused before any model
    call, stream, or gate acquisition. The guard token is released when the
    scope exits, so a later turn in the same thread/context is enforced again.
    The context stays set for the whole block, so every model call the turn makes
    is metered to the same account/role.
    """
    from service.model_limits import release_admission
    from utils.model_metering import usage_context
    from utils.model_metering import current_usage_context

    active_context = current_usage_context()
    turn = active_context.turn_state
    token = _admit_scope(scope, turn)
    turn_id = active_context.turn_id if turn is not None else None
    try:
        with _track_inference_scope(turn):
            with usage_context(_metering_context(scope, turn, turn_id)):
                yield
    finally:
        release_admission(token)


def _admit_scope(scope: InferenceScope, turn: InferenceTurnState | None) -> Token[str | None] | None:
    from service.model_limits import ModelAdmissionContext, admit_model_request

    if not scope.admit:
        return None
    context = ModelAdmissionContext(
        role=scope.role,
        client=scope.client,
        background_tasks=turn.background_tasks if turn is not None else None,
        defer_limit_hit=turn.defer_limit_hit if turn is not None else None,
    )
    return admit_model_request(scope.account_id, db=scope.store, context=context)


def _metering_context(
    scope: InferenceScope,
    turn: InferenceTurnState | None,
    turn_id: str | None,
) -> UsageContext:
    return UsageContext(
        account_id=scope.account_id,
        role=scope.role,
        purpose=scope.purpose,
        store=scope.store,
        turn_id=turn_id,
        turn_state=turn,
        on_finish_reason=turn.record_finish_reason if turn is not None else None,
        on_usage=turn.record_usage if turn is not None else None,
        on_limit_hit=turn.defer_limit_hit if turn is not None else None,
        background_tasks=turn.background_tasks if turn is not None else None,
    )


@contextlib.contextmanager
def _track_inference_scope(turn: InferenceTurnState | None) -> Iterator[None]:
    started = time.perf_counter()
    outcome = "ok"
    try:
        yield
    except BaseException as exc:
        interrupted = (asyncio.CancelledError, GeneratorExit, InterruptedError)
        outcome = "interrupted" if isinstance(exc, interrupted) else "error"
        raise
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if turn is not None:
            turn.record_inference(outcome, elapsed_ms)


@contextlib.contextmanager
def inference_slot(timeout: float = 30.0, *, scope: InferenceScope | None = None) -> Iterator[None]:
    """Sync gate for a blocking graph call: one ``LLM_MAX_CONCURRENT`` slot.

    Raises ``TimeoutError`` when the gate stays full for ``timeout`` seconds and
    ``ModelLimitExceeded`` when the account is over its model limit. The
    slot bounds the complete model operation.
    """
    with _usage_scope(scope or InferenceScope()):
        gate = _inference_gate()
        if not gate.acquire(timeout=timeout):
            raise TimeoutError("Inference queue is full; retry shortly.")
        try:
            yield
        finally:
            gate.release()


def run_inference_sync(
    fn: Callable[..., Any], *args: Any, scope: InferenceScope | None = None, **kwargs: Any
) -> Any:
    """Runs a blocking ``llm.*`` callable under the shared inference gate."""
    with inference_slot(scope=scope):
        return fn(*args, **kwargs)


def bound_stream(
    stream_factory: Callable[..., Iterator[Any]],
    *args: Any,
    scope: InferenceScope | None = None,
    **kwargs: Any,
) -> Iterator[Any]:
    """Yields from a sync generator while holding one inference slot.

    The slot spans the whole stream so concurrent chat turns are bounded by
    ``LLM_MAX_CONCURRENT`` instead of only buffering whole responses.
    """
    with inference_slot(scope=scope):
        generator = stream_factory(*args, **kwargs)
        try:
            yield from generator
        finally:
            # The slot must cover the whole stream, not just the first chunk:
            # close the underlying generator inside the held slot so a
            # disconnect/abort cannot leave the graph running ungated.
            generator.close()


async def run_inference(
    fn: Callable[..., Any], *args: Any, scope: InferenceScope | None = None, **kwargs: Any
) -> Any:
    """Runs a blocking ``llm.*`` callable; raises ``TimeoutError`` on overload."""
    with _usage_scope(scope or InferenceScope()):
        try:
            await asyncio.wait_for(_SEMAPHORE.acquire(), timeout=30.0)
        except asyncio.TimeoutError:
            raise TimeoutError("Inference queue is full; retry shortly.") from None
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        finally:
            _SEMAPHORE.release()


def unload_all() -> None:
    from utils.model_downloader import unload_coach_llm, unload_judge_llm, unload_llm

    unload_llm()
    unload_judge_llm()
    unload_coach_llm()
