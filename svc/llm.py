"""Serialized async gateway to the blocking llama-cpp models.

``llama-cpp-python`` is not thread-safe: every ``llm.*`` call runs under
``_INFERENCE_LOCK`` on a worker thread. ``_SEMAPHORE`` bounds concurrent
inference requests so overload fails fast instead of piling up.
"""

import asyncio
import threading
from typing import Any, Callable

_INFERENCE_LOCK = threading.Lock()
_SEMAPHORE = asyncio.Semaphore(1)


def is_llm_loaded() -> bool:
    from utils import model_downloader

    return model_downloader._llm_instance is not None


def is_judge_loaded() -> bool:
    from utils import model_downloader

    return model_downloader._judge_llm_instance is not None


async def warmup_llm() -> None:
    """Preloads the production model on a worker thread. Judge stays lazy."""
    from utils.model_downloader import get_llm

    await asyncio.to_thread(get_llm)


async def run_inference(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Runs a blocking ``llm.*`` callable serialized; raises ``TimeoutError`` on overload."""
    try:
        await asyncio.wait_for(_SEMAPHORE.acquire(), timeout=30.0)
    except asyncio.TimeoutError:
        raise TimeoutError("Inference queue is full; retry shortly.") from None
    try:
        return await asyncio.to_thread(_locked_call, fn, args, kwargs)
    finally:
        _SEMAPHORE.release()


def _locked_call(fn: Callable[..., Any], args: tuple, kwargs: dict) -> Any:
    with _INFERENCE_LOCK:
        return fn(*args, **kwargs)


def unload_all() -> None:
    from utils.model_downloader import unload_judge_llm, unload_llm

    with _INFERENCE_LOCK:
        unload_llm()
        unload_judge_llm()
