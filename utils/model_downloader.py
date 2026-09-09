# utils/model_downloader.py
import multiprocessing
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from huggingface_hub import hf_hub_download
from langchain_community.chat_models import ChatLlamaCpp
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk

DEFAULT_MODEL_DIR = Path("models")
DEFAULT_MODEL_FILENAME = "qwen2.5-3b-instruct-q4_k_m.gguf"
REPO_ID = "Qwen/Qwen2.5-3B-Instruct-GGUF"


def get_or_download_model_path() -> str:
    env_path = os.getenv("MODEL_PATH")
    if env_path and Path(env_path).is_file():
        return env_path

    target_dir = Path(os.getenv("MODEL_DIR", DEFAULT_MODEL_DIR))
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / DEFAULT_MODEL_FILENAME

    if not target_file.is_file():
        print(f"⚡ Downloading {DEFAULT_MODEL_FILENAME} from {REPO_ID}...")
        hf_hub_download(
            repo_id=REPO_ID,
            filename=DEFAULT_MODEL_FILENAME,
            local_dir=str(target_dir),
        )
        print("✅ Download complete.")

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


_llm_instance = None


def get_llm() -> Any:
    """Lazily instantiate SafeChatLlamaCpp singleton."""
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance

    is_testing = os.getenv("CI") == "true" or "pytest" in sys.modules or os.getenv("TESTING") == "1"

    try:
        import llama_cpp  # noqa: F401
    except ImportError:
        if is_testing:
            _llm_instance = MagicMock(name="MockSafeChatLlamaCpp")
            return _llm_instance
        raise ImportError(
            "Could not import llama-cpp-python library. "
            "Please install it using `pip install llama-cpp-python`."
        )

    model_candidate = Path(
        os.getenv("MODEL_PATH", Path(os.getenv("MODEL_DIR", DEFAULT_MODEL_DIR)) / DEFAULT_MODEL_FILENAME)
    )

    # Prevent multi-gigabyte downloads during CI runs and unit tests
    if is_testing and not model_candidate.is_file():
        _llm_instance = MagicMock(name="MockSafeChatLlamaCpp")
        return _llm_instance

    resolved_path = get_or_download_model_path()
    physical_cores = max(1, multiprocessing.cpu_count() // 2)

    _llm_instance = SafeChatLlamaCpp(
        model_path=resolved_path,
        temperature=0.0,
        n_ctx=2048,
        n_batch=512,
        n_threads=physical_cores,
        n_threads_batch=physical_cores,
        max_tokens=200,
        streaming=True,
        verbose=False,
    )
    return _llm_instance


class _LazyLLMProxy:
    """Transparent proxy that defers model loading until an attribute or invocation occurs."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_llm(), name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return get_llm()(*args, **kwargs)

    def __or__(self, other: Any) -> Any:
        return get_llm().__or__(other)

    def __ror__(self, other: Any) -> Any:
        return get_llm().__ror__(other)

    def __bool__(self) -> bool:
        return True

    def __repr__(self) -> str:
        if _llm_instance is None:
            return "<LazyLLMProxy (uninitialized)>"
        return repr(_llm_instance)


llm = _LazyLLMProxy()