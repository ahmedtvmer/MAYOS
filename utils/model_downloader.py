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
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import BaseModel

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


class MockSafeChatLlamaCpp(SafeChatLlamaCpp):
    """Testing double that satisfies CI requirements without loading GGUF binaries."""

    def __init__(self, **kwargs: Any) -> None:
        attrs = {
            "max_tokens": 200,
            "temperature": 0.0,
            "n_ctx": 2048,
            "n_batch": 512,
            "streaming": True,
            "verbose": False,
            "model_path": "mock.gguf",
        }
        for k, v in attrs.items():
            object.__setattr__(self, k, v)

    def invoke(self, *args: Any, **kwargs: Any) -> AIMessage:
        return AIMessage(
            content="Execute Romanian deadlifts first to bias hamstring lengthened tension under high axial load."
        )

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

        # Match exercise IDs with your active catalog (e.g. "1" for mock fixture)
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
            },
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
            },
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
            },
        ]
        
        class MockSplitDay:
            day_order = 1
            day_name = "Day 1"
            target_body_parts = ["chest", "back"]
            exercises = sample_exercises

        class MockPlan:
            split_name = "Custom 3-Day Split"
            days = [MockSplitDay(), MockSplitDay(), MockSplitDay()]
            day_order = 1
            day_name = "Full Body"
            target_body_parts = ["chest", "back", "legs"]
            exercises = sample_exercises

        def _handler(*h_args: Any, **h_kwargs: Any) -> Any:
            if isinstance(schema, type) and issubclass(schema, BaseModel):
                try:
                    payload = {
                        "split_name": "Custom 3-Day Split",
                        "days": [
                            {
                                "day_order": 1,
                                "day_name": "Upper",
                                "target_body_parts": ["chest"],
                                "exercises": sample_exercises,
                            },
                            {
                                "day_order": 2,
                                "day_name": "Lower",
                                "target_body_parts": ["quads"],
                                "exercises": sample_exercises,
                            },
                            {
                                "day_order": 3,
                                "day_name": "Arms",
                                "target_body_parts": ["biceps"],
                                "exercises": sample_exercises,
                            },
                        ],
                        "day_order": 1,
                        "day_name": "Full Body",
                        "target_body_parts": ["chest", "back", "legs"],
                        "exercises": sample_exercises,
                    }
                    return schema.model_validate(payload)
                except Exception:
                    return MockPlan()
            return MockPlan()

        runnable.invoke.side_effect = _handler
        return runnable

_llm_instance = None


def get_llm() -> Any:
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance

    is_testing = os.getenv("CI") == "true" or "pytest" in sys.modules or os.getenv("TESTING") == "1"
    model_candidate = Path(
        os.getenv("MODEL_PATH", Path(os.getenv("MODEL_DIR", DEFAULT_MODEL_DIR)) / DEFAULT_MODEL_FILENAME)
    )

    if is_testing and not model_candidate.is_file():
        _llm_instance = MockSafeChatLlamaCpp()
        return _llm_instance

    resolved_path = get_or_download_model_path()
    physical_cores = max(1, multiprocessing.cpu_count() // 2)

    n_gpu_layers = int(os.getenv("N_GPU_LAYERS", "-1"))

    _llm_instance = SafeChatLlamaCpp(
        model_path=resolved_path,
        temperature=0.0,
        n_ctx=2048,
        n_batch=512,
        n_gpu_layers=n_gpu_layers,
        n_threads=physical_cores,
        n_threads_batch=physical_cores,
        max_tokens=200,
        streaming=True,
        verbose=False,
    )
    return _llm_instance


class _LazyLLMProxy:
    def __getattr__(self, name: str) -> Any:
        return getattr(get_llm(), name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return get_llm()(*args, **kwargs)

    def __repr__(self) -> str:
        return repr(get_llm())


llm = _LazyLLMProxy()
