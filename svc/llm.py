"""Gateway to the inference backends.

Local ``llama-cpp-python`` is not thread-safe, so every inference runs under
``_INFERENCE_LOCK``. Cloud (OpenAI-compatible) endpoints are thread-safe: the
lock is skipped and ``LLM_MAX_CONCURRENT`` (default 1) bounds overlap instead.

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
"""

import asyncio
import contextlib
import os
import threading
from typing import Any, Callable, Iterator

_INFERENCE_LOCK = threading.Lock()


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

    if not model_downloader.uses_cloud_backend():
        # Local mode aliases the production model, which owns the instance.
        return model_downloader._llm_instance is not None
    return model_downloader._coach_llm_instance is not None


async def warmup_llm() -> None:
    """Preloads the production model on a worker thread. Judge stays lazy."""
    from utils.model_downloader import get_llm

    await asyncio.to_thread(get_llm)


def _uses_serial_lock() -> bool:
    """True only for the thread-unsafe local llama.cpp backend."""
    from utils.model_downloader import uses_cloud_backend

    return not uses_cloud_backend()


@contextlib.contextmanager
def inference_slot(timeout: float = 30.0) -> Iterator[None]:
    """Sync gate for a blocking graph call: one ``LLM_MAX_CONCURRENT`` slot.

    Raises ``TimeoutError`` when the gate stays full for ``timeout`` seconds.
    The thread-unsafe local backend additionally holds ``_INFERENCE_LOCK`` for
    the whole slot; cloud calls skip it.
    """
    gate = _inference_gate()
    if not gate.acquire(timeout=timeout):
        raise TimeoutError("Inference queue is full; retry shortly.")
    try:
        if _uses_serial_lock():
            with _INFERENCE_LOCK:
                yield
        else:
            yield
    finally:
        gate.release()


def run_inference_sync(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Runs a blocking ``llm.*`` callable under the shared inference gate."""
    with inference_slot():
        return fn(*args, **kwargs)


def bound_stream(stream_factory: Callable[..., Iterator[Any]], *args: Any, **kwargs: Any) -> Iterator[Any]:
    """Yields from a sync generator while holding one inference slot.

    The slot spans the whole stream so concurrent chat turns are bounded by
    ``LLM_MAX_CONCURRENT`` (and serialized for the local backend) instead of
    only buffering whole responses.
    """
    with inference_slot():
        yield from stream_factory(*args, **kwargs)


async def run_inference(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Runs a blocking ``llm.*`` callable; raises ``TimeoutError`` on overload."""
    try:
        await asyncio.wait_for(_SEMAPHORE.acquire(), timeout=30.0)
    except asyncio.TimeoutError:
        raise TimeoutError("Inference queue is full; retry shortly.") from None
    try:
        if _uses_serial_lock():
            return await asyncio.to_thread(_locked_call, fn, args, kwargs)
        return await asyncio.to_thread(fn, *args, **kwargs)
    finally:
        _SEMAPHORE.release()


def _locked_call(fn: Callable[..., Any], args: tuple, kwargs: dict) -> Any:
    with _INFERENCE_LOCK:
        return fn(*args, **kwargs)


def unload_all() -> None:
    from utils.model_downloader import unload_coach_llm, unload_judge_llm, unload_llm

    with _INFERENCE_LOCK:
        unload_llm()
        unload_judge_llm()
        unload_coach_llm()
