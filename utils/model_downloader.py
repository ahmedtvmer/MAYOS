"""Local GGUF resolution, download, and singleton lifecycle.

Public surface (stable):
``MODEL_REGISTRY``, ``get_or_download_model_path``, ``SafeChatLlamaCpp``,
``MockSafeChatLlamaCpp``, ``get_llm``, ``get_judge_llm``, ``unload_llm``,
``unload_judge_llm``, ``llm``, ``judge_llm``.
"""

import errno
import gc
import hashlib
import logging
import multiprocessing
import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from huggingface_hub import hf_hub_download
from langchain_community.chat_models import ChatLlamaCpp
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk
from pydantic import BaseModel

try:  # POSIX advisory locks; released by the OS if the holder process dies.
    import fcntl
except ImportError:  # pragma: no cover - Windows dev fallback
    fcntl = None

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_DIR = BASE_DIR / "models"

MODEL_REGISTRY = {
    "production": {
        "repo_id": "unsloth/Qwen3.5-4B-GGUF",
        "filename": "Qwen3.5-4B-Q4_K_M.gguf",
        "env_var": "MODEL_PATH",
        # Pin a revision / sha256 here when reproducibility is required;
        # None means "whatever the repo serves" (documented, not silent).
        "revision": os.getenv("MODEL_REVISION"),
        "sha256": os.getenv("MODEL_SHA256"),
    },
    "judge": {
        "repo_id": "unsloth/Qwen3.5-9B-GGUF",
        "filename": "Qwen3.5-9B-Q4_K_M.gguf",
        "env_var": "JUDGE_MODEL_PATH",
        "revision": os.getenv("JUDGE_MODEL_REVISION"),
        "sha256": os.getenv("JUDGE_MODEL_SHA256"),
    },
}

# ``TESTING=1`` is the only explicit mock switch. ``CI`` and a live pytest
# process are fallbacks: they mock only when the model file is genuinely
# absent, so a test run can never trigger a multi-GB download. Note that
# ``SKIP_LLM_LOAD`` is deliberately NOT a mock switch — it only skips eager
# boot warmup; the real model lazy-loads on first inference.
_MOCK_ENV_VARS = ("TESTING",)
_MOCK_FALLBACK_ENV_VARS = ("CI",)


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").lower() in {"1", "true", "yes"}


def _should_use_mock(model_type: str) -> bool:
    if any(_env_truthy(var) for var in _MOCK_ENV_VARS):
        return True
    fallback_context = "pytest" in sys.modules or any(_env_truthy(var) for var in _MOCK_FALLBACK_ENV_VARS)
    if not fallback_context:
        return False
    try:
        return not Path(resolve_model_path(model_type)).is_file()
    except ValueError:
        return True


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _thread_count() -> int:
    """Worker threads: explicit opt-in first, else half the cores, min 1.

    Honors OMP_NUM_THREADS so container CPU quotas are respected.
    """
    explicit = os.getenv("LLM_THREADS") or os.getenv("OMP_NUM_THREADS")
    if explicit:
        try:
            if int(explicit) >= 1:
                return int(explicit)
        except ValueError:
            pass
    return max(1, multiprocessing.cpu_count() // 2)


def resolve_model_path(model_type: str = "production") -> str:
    """Resolve the on-disk GGUF path for ``model_type`` without downloading."""
    if model_type not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model_type '{model_type}'. Choose from {list(MODEL_REGISTRY.keys())}")
    config = MODEL_REGISTRY[model_type]
    env_path = os.getenv(config["env_var"])
    if env_path and Path(env_path).is_file():
        return env_path
    target_dir = Path(os.getenv("MODEL_DIR", DEFAULT_MODEL_DIR))
    return str(target_dir / config["filename"])


@contextmanager
def _flock_guard(lock_path: Path, timeout_s: float, poll_s: float) -> Iterator[None]:
    """POSIX ``flock`` guard: a crashed holder can never wedge the next boot."""
    fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES):
                    raise
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Timed out waiting for model download lock: {lock_path}") from None
                time.sleep(poll_s)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


@contextmanager
def _lockfile_guard(lock_path: Path, timeout_s: float, poll_s: float) -> Iterator[None]:
    """Portable fallback: atomic O_EXCL lockfile (a stale file blocks until timeout)."""
    deadline = time.monotonic() + timeout_s
    fd = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() > deadline:
                raise TimeoutError(f"Timed out waiting for model download lock: {lock_path}")
            time.sleep(poll_s)
    try:
        yield
    finally:
        os.close(fd)
        try:
            lock_path.unlink()
        except OSError:
            pass


@contextmanager
def _file_lock(lock_path: Path, timeout_s: float = 600.0, poll_s: float = 0.25) -> Iterator[None]:
    """Cross-process download mutex.

    Serializes concurrent downloads across uvicorn workers/processes, which a
    ``threading.Lock`` cannot do. Uses ``flock`` where available so a killed
    process releases its lock; falls back to lockfile creation on Windows.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    guard = _flock_guard if fcntl is not None else _lockfile_guard
    with guard(lock_path, timeout_s, poll_s):
        yield


def _verify_checksum(path: Path, expected_sha256: str | None) -> None:
    if not expected_sha256:
        return
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest().lower() != expected_sha256.lower():
        raise ValueError(f"Checksum mismatch for {path.name}; refusing to load a corrupt model file.")


def get_or_download_model_path(model_type: str = "production") -> str:
    """Resolves local path or downloads the requested model from HF Hub.

    model_type: 'production' | 'judge'
    """
    if model_type not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model_type '{model_type}'. Choose from {list(MODEL_REGISTRY.keys())}")

    config = MODEL_REGISTRY[model_type]
    env_path = os.getenv(config["env_var"])
    if env_path and Path(env_path).is_file():
        return env_path

    target_dir = Path(os.getenv("MODEL_DIR", DEFAULT_MODEL_DIR))
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / config["filename"]

    if target_file.is_file():
        _verify_checksum(target_file, config.get("sha256"))
        return str(target_file)

    lock_path = target_dir / f"{config['filename']}.lock"
    with _file_lock(lock_path):
        # Re-check under the lock: another process may have finished first.
        if target_file.is_file():
            _verify_checksum(target_file, config.get("sha256"))
            return str(target_file)
        logger.info("Downloading %s from %s ...", config["filename"], config["repo_id"])
        try:
            hf_hub_download(
                repo_id=config["repo_id"],
                filename=config["filename"],
                revision=config.get("revision"),
                local_dir=str(target_dir),
            )
        except Exception:
            # Never leave a partial file behind: a half-written GGUF would
            # otherwise pass is_file() forever and fail late at load time.
            try:
                if target_file.is_file() and target_file.stat().st_size == 0:
                    target_file.unlink()
            except OSError:
                pass
            logger.exception("Model download failed for %s", config["filename"])
            raise
        if not target_file.is_file() or target_file.stat().st_size == 0:
            raise RuntimeError(f"Download reported success but {target_file} is missing or empty.")
        _verify_checksum(target_file, config.get("sha256"))
        logger.info("Download complete: %s", config["filename"])

    return str(target_file)


class SafeChatLlamaCpp(ChatLlamaCpp):
    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        seen_tool_indices = set()
        for chunk in super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
            tc_chunks = getattr(chunk.message, "tool_call_chunks", None)
            if tc_chunks:
                for tc in tc_chunks:
                    idx = tc.get("index", 0) if isinstance(tc, dict) else getattr(tc, "index", 0)
                    if idx in seen_tool_indices:
                        if isinstance(tc, dict):
                            tc["name"] = None
                        else:
                            tc.name = None
                    else:
                        seen_tool_indices.add(idx)
            yield chunk


class MockSafeChatLlamaCpp(SafeChatLlamaCpp):
    """Testing double that satisfies CI requirements without loading GGUF binaries."""

    def __init__(self, **kwargs: Any) -> None:
        attrs = {
            "max_tokens": 200,
            "temperature": 0.0,
            "n_ctx": 2048,
            "n_batch": 512,
            "streaming": True,
            "disable_streaming": False,
            "verbose": False,
            "model_path": "mock.gguf",
        }
        for k, v in attrs.items():
            object.__setattr__(self, k, v)

    def invoke(self, *args: Any, **kwargs: Any) -> AIMessage:
        return AIMessage(
            content="Execute Romanian deadlifts first to bias hamstring lengthened tension under high axial load."
        )

    async def ainvoke(self, *args: Any, **kwargs: Any) -> AIMessage:
        return self.invoke(*args, **kwargs)

    def _stream(
        self,
        messages: list[BaseMessage] | str,
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Word-level chunks on the internal layer, mirroring the real model."""
        text = str(self.invoke(messages, **kwargs).content)
        words = text.split(" ")
        for index, word in enumerate(words):
            piece = word + (" " if index < len(words) - 1 else "")
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))

    def stream(self, *args: Any, **kwargs: Any) -> Iterator[AIMessageChunk]:
        """Public layer yields message chunks, exactly like ``BaseChatModel.stream``.

        Callers consume ``chunk.content``; yielding ``ChatGenerationChunk`` here
        would surface reprs via their ``str(chunk)`` fallback.
        """
        for generation in self._stream(*args, **kwargs):
            yield generation.message

    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        from langchain_core.outputs import ChatResult

        return ChatResult(generations=[ChatGeneration(message=self.invoke(*args, **kwargs))])

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        bound = MagicMock()
        bound.invoke.return_value = AIMessage(
            content="",
            tool_calls=[{
                "name": "search_exercises",
                "args": {"query": "hamstrings barbell"},
                "id": "call_mock_1",
                "type": "tool_call",
            }],
        )
        return bound

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        runnable = MagicMock()
        sample_exercises = [
            {
                "id": "1",
                "exercise_id": "1",
                "name": "3/4 sit-up",
                "exercise_name": "3/4 sit-up",
                "body_part": "waist",
                "target": "abs",
                "target_muscle": "abs",
                "target_sets": 3,
                "target_reps_min": 8,
                "target_reps_max": 10,
                "target_rpe": 8.0,
                "rest_seconds": 90,
                "notes": "",
                "sets": 3,
                "reps": "8-10",
                "rpe": 8.0,
            }
        ]

        class MockPlan:
            split_name = "Custom 3-Day Split"
            days = []

        def _handler(*h_args: Any, **h_kwargs: Any) -> Any:
            if isinstance(schema, type) and issubclass(schema, BaseModel):
                try:
                    payload = {
                        "split_name": "Custom 3-Day Split",
                        "days": [
                            {"day_order": 1, "day_name": "Upper", "target_body_parts": ["chest"], "exercises": sample_exercises},
                            {"day_order": 2, "day_name": "Lower", "target_body_parts": ["quads"], "exercises": sample_exercises},
                            {"day_order": 3, "day_name": "Arms", "target_body_parts": ["biceps"], "exercises": sample_exercises},
                        ],
                    }
                    return schema.model_validate(payload)
                except Exception:
                    return MockPlan()
            return MockPlan()

        runnable.invoke.side_effect = _handler
        return runnable


_llm_instance = None
_judge_llm_instance = None
#: Serializes singleton construction within this process. NOTE: this cannot
#: stop concurrent *processes* (uvicorn workers) from each loading the GGUF;
#: run a single model-owning replica or warm up behind a file lock.
_load_lock = threading.Lock()

#: Substrings (lowercased) that mark a load failure as hardware/offload
#: related and therefore worth a single CPU retry. Anything else re-raises
#: immediately so config errors surface instead of being masked.
_RETRYABLE_LOAD_ERRORS = (
    "failed to create llama_context",
    "failed to load model from file",
    "failed to allocate",
    "out of memory",
    "cuda",
    "no device",
)


def _load_local_model(constructor, gpu_layers: int, **kwargs: Any) -> Any:
    cpu_options = {"offload_kqv": False, "op_offload": False}
    try:
        return constructor(
            **kwargs,
            n_gpu_layers=gpu_layers,
            model_kwargs=cpu_options if gpu_layers == 0 else {},
        )
    except Exception as exc:
        message = str(exc).lower()
        if gpu_layers == 0 or not any(marker in message for marker in _RETRYABLE_LOAD_ERRORS):
            raise
        logger.warning("GPU model initialization failed (%s); retrying once on CPU.", exc)
        gc.collect()
        return constructor(**kwargs, n_gpu_layers=0, model_kwargs=cpu_options)


def _common_llm_kwargs() -> dict[str, Any]:
    threads = _thread_count()
    return {
        "temperature": 0.0,
        "n_ctx": _int_env("LLM_N_CTX", 2048),
        "n_batch": _int_env("LLM_N_BATCH", 512),
        "n_threads": threads,
        "n_threads_batch": threads,
        "verbose": False,
    }


def _attach_prompt_cache(instance: Any) -> None:
    """Best-effort KV prompt cache; absence must never break inference."""
    try:
        from llama_cpp import LlamaRAMCache

        client = getattr(instance, "client", None)
        setter = getattr(client, "set_cache", None)
        if callable(setter):
            setter(LlamaRAMCache(capacity_bytes=_int_env("LLM_CACHE_BYTES", 256 * 1024 * 1024)))
    except Exception as exc:
        logger.debug("Prompt cache unavailable; continuing without it: %s", exc)


def _release_instance(instance: Any) -> None:
    if instance is None:
        return
    try:
        client = getattr(instance, "client", None)
        if client is not None:
            closer = getattr(client, "close", None)
            if callable(closer):
                closer()
            try:
                instance.client = None
            except Exception:
                pass
    except Exception:
        logger.debug("Error while releasing LLM client.", exc_info=True)
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
    except Exception:
        logger.debug("CUDA cache release failed.", exc_info=True)


def get_llm(n_gpu_layers: int | None = None) -> Any:
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance

    with _load_lock:
        if _llm_instance is not None:
            return _llm_instance

        if _should_use_mock("production"):
            _llm_instance = MockSafeChatLlamaCpp()
            return _llm_instance

        resolved = get_or_download_model_path("production")
        gpu_layers = n_gpu_layers if n_gpu_layers is not None else _int_env("N_GPU_LAYERS", -1)

        instance = _load_local_model(
            SafeChatLlamaCpp,
            gpu_layers,
            model_path=resolved,
            max_tokens=_int_env("LLM_MAX_TOKENS", 200),
            streaming=True,
            **_common_llm_kwargs(),
        )
        _attach_prompt_cache(instance)
        _llm_instance = instance
        return _llm_instance


def unload_llm() -> None:
    """Explicitly releases the production LLM client and reclaims CUDA VRAM."""
    global _llm_instance
    with _load_lock:
        instance, _llm_instance = _llm_instance, None
    _release_instance(instance)


def get_judge_llm(n_gpu_layers: int | None = None) -> Any:
    global _judge_llm_instance
    if _judge_llm_instance is not None:
        return _judge_llm_instance

    with _load_lock:
        if _judge_llm_instance is not None:
            return _judge_llm_instance

        if _should_use_mock("judge"):
            _judge_llm_instance = MockSafeChatLlamaCpp(streaming=False)
            return _judge_llm_instance

        resolved = get_or_download_model_path("judge")
        gpu_layers = n_gpu_layers if n_gpu_layers is not None else _int_env("JUDGE_N_GPU_LAYERS", 18)

        _judge_llm_instance = _load_local_model(
            SafeChatLlamaCpp,
            gpu_layers,
            model_path=resolved,
            max_tokens=_int_env("JUDGE_MAX_TOKENS", 280),
            streaming=False,
            **{**_common_llm_kwargs(), "n_ctx": _int_env("JUDGE_N_CTX", 4096)},
        )
        return _judge_llm_instance


def unload_judge_llm() -> None:
    """Explicitly releases the judge LLM client and reclaims CUDA VRAM."""
    global _judge_llm_instance
    with _load_lock:
        instance, _judge_llm_instance = _judge_llm_instance, None
    _release_instance(instance)


class _LazyLLMProxy:
    """Defers the 4B load until a real inference attribute is used.

    Dunder access (repr/copy/pickle/inspect) must NEVER trigger a load.
    """

    #: Attributes that are safe / expected without loading the model.
    _SAFE_ATTRS = frozenset({"model_path"})

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return getattr(get_llm(), name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return get_llm()(*args, **kwargs)

    def __repr__(self) -> str:
        loaded = _llm_instance is not None
        return f"<lazy production llm loaded={loaded}>"


class _LazyJudgeProxy:
    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return getattr(get_judge_llm(), name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return get_judge_llm()(*args, **kwargs)

    def __repr__(self) -> str:
        loaded = _judge_llm_instance is not None
        return f"<lazy judge llm loaded={loaded}>"


llm = _LazyLLMProxy()
judge_llm = _LazyJudgeProxy()


__all__ = [
    "BASE_DIR",
    "DEFAULT_MODEL_DIR",
    "MODEL_REGISTRY",
    "MockSafeChatLlamaCpp",
    "SafeChatLlamaCpp",
    "get_judge_llm",
    "get_llm",
    "get_or_download_model_path",
    "judge_llm",
    "llm",
    "resolve_model_path",
    "unload_judge_llm",
    "unload_llm",
]
