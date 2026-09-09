# utils/model_downloader.py
import multiprocessing
import os
from pathlib import Path
from typing import Any, Iterator, List, Optional

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
            local_dir_use_symlinks=False
        )
        print("✅ Download complete.")

    return str(target_file)


class SafeChatLlamaCpp(ChatLlamaCpp):
    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
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


physical_cores = max(1, multiprocessing.cpu_count() // 2)

llm = SafeChatLlamaCpp(
    model_path=get_or_download_model_path(),
    temperature=0.0,
    n_ctx=2048,
    n_batch=512,
    n_threads=physical_cores,
    n_threads_batch=physical_cores,
    max_tokens=200,
    streaming=True,
    verbose=False
)