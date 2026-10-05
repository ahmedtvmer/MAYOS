"""Hosted chat model configuration and lifecycle."""

import gc
import logging
import math
import os
import threading
from typing import Any

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

CLOUD_MODEL_REGISTRY = {
    "production": {
        "model_env": "LLM_MODEL",
        "default_model": "deepseek-ai/DeepSeek-V4-Flash",
        "max_tokens_env": "LLM_MAX_TOKENS",
        "default_max_tokens": 200,
        "streaming": True,
    },
    "judge": {
        "model_env": "JUDGE_MODEL",
        "default_model": "Qwen/Qwen3.5-27B",
        "max_tokens_env": "JUDGE_MAX_TOKENS",
        "default_max_tokens": 700,
        "streaming": False,
    },
    "coach": {
        "model_env": "COACH_MODEL",
        "default_model": "deepseek-ai/DeepSeek-V4-Flash",
        "max_tokens_env": "COACH_MAX_TOKENS",
        "default_max_tokens": 512,
        "streaming": True,
    },
}

DEFAULT_CLOUD_API_BASE = "https://api.deepinfra.com/v1/openai"
DEFAULT_CLOUD_REQUEST_TIMEOUT = 60.0
DEFAULT_CLOUD_MAX_RETRIES = 1
DEFAULT_CLOUD_STREAM_CHUNK_TIMEOUT = 30.0


class SafeChatOpenAI(ChatOpenAI):
    """Hosted chat model with the standard LangChain chat interface."""


_llm_instance: Any = None
_judge_llm_instance: Any = None
_coach_llm_instance: Any = None
_model_build_lock = threading.Lock()


def _cloud_api_key() -> str:
    return os.getenv("LLM_API_KEY", "").strip()


def _cloud_api_base() -> str:
    return os.getenv("LLM_API_BASE", DEFAULT_CLOUD_API_BASE).strip() or DEFAULT_CLOUD_API_BASE


def _cloud_model_id(model_type: str) -> str:
    config = CLOUD_MODEL_REGISTRY[model_type]
    return os.getenv(config["model_env"], config["default_model"]).strip()


def configured_model_ids() -> frozenset[str]:
    return frozenset(_cloud_model_id(role) for role in CLOUD_MODEL_REGISTRY)


def model_identity(model_type: str = "production") -> tuple[str, str]:
    """Returns the configured hosted model id and provider family."""
    if model_type not in CLOUD_MODEL_REGISTRY:
        raise ValueError(f"Unknown model_type '{model_type}'. Choose from {list(CLOUD_MODEL_REGISTRY)}")
    return _cloud_model_id(model_type), "openai"


def _metering_callbacks(model_id: str) -> list[Any]:
    try:
        from utils.model_metering import MeteringCallback

        return [MeteringCallback(model_id)]
    except Exception:  # Metering must never prevent model construction.
        logger.exception("Model metering callback unavailable; building the model unmetered.")
        return []


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


def _non_negative_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _parse_extra_body(raw_extra_body: str, env_name: str) -> dict[str, Any]:
    import json

    try:
        parsed = json.loads(raw_extra_body)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{env_name} must be a JSON object.")
    return parsed


def _extra_body(model_type: str) -> dict[str, Any] | None:
    setting = {
        "production": ("LLM_EXTRA_BODY", None),
        "judge": ("JUDGE_EXTRA_BODY", {"chat_template_kwargs": {"enable_thinking": False}}),
        "coach": ("COACH_EXTRA_BODY", None),
    }[model_type]
    name, default = setting
    raw_body = os.getenv(name, "").strip()
    if raw_body:
        return _parse_extra_body(raw_body, name) or None
    if model_type == "judge" and os.getenv("LLM_ENABLE_THINKING", "").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    return default


def _build_cloud_llm(model_type: str) -> SafeChatOpenAI:
    if model_type not in CLOUD_MODEL_REGISTRY:
        raise ValueError(f"Unknown model_type '{model_type}'. Choose from {list(CLOUD_MODEL_REGISTRY)}")
    api_key = _cloud_api_key()
    if not api_key:
        raise RuntimeError("LLM_API_KEY is required to build a hosted chat model.")

    config = CLOUD_MODEL_REGISTRY[model_type]
    model_id = _cloud_model_id(model_type)
    return SafeChatOpenAI(
        model=model_id,
        api_key=api_key,
        base_url=_cloud_api_base(),
        temperature=_float_env("LLM_TEMPERATURE", 0.0),
        max_tokens=_int_env(config["max_tokens_env"], config["default_max_tokens"]),
        streaming=bool(config["streaming"]),
        extra_body=_extra_body(model_type),
        stream_usage=True,
        callbacks=_metering_callbacks(model_id),
        timeout=_positive_float_env("LLM_REQUEST_TIMEOUT", DEFAULT_CLOUD_REQUEST_TIMEOUT),
        max_retries=_non_negative_int_env("LLM_MAX_RETRIES", DEFAULT_CLOUD_MAX_RETRIES),
        stream_chunk_timeout=_positive_float_env("LLM_STREAM_CHUNK_TIMEOUT", DEFAULT_CLOUD_STREAM_CHUNK_TIMEOUT),
    )


def _get_model(role: str) -> Any:
    global _llm_instance, _judge_llm_instance, _coach_llm_instance
    instance_name = {"production": "_llm_instance", "judge": "_judge_llm_instance", "coach": "_coach_llm_instance"}[role]
    instance = globals()[instance_name]
    if instance is not None:
        return instance
    with _model_build_lock:
        instance = globals()[instance_name]
        if instance is None:
            instance = _build_cloud_llm(role)
            globals()[instance_name] = instance
        return instance


def get_llm() -> Any:
    return _get_model("production")


def get_judge_llm() -> Any:
    return _get_model("judge")


def get_coach_llm() -> Any:
    return _get_model("coach")


def _unload_model(instance_name: str) -> None:
    globals()[instance_name] = None
    gc.collect()


def unload_llm() -> None:
    _unload_model("_llm_instance")


def unload_judge_llm() -> None:
    _unload_model("_judge_llm_instance")


def unload_coach_llm() -> None:
    _unload_model("_coach_llm_instance")


class _LazyModelProxy:
    def __init__(self, getter: Any, role: str, loaded_name: str) -> None:
        self._getter = getter
        self._role = role
        self._loaded_name = loaded_name

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return getattr(self._getter(), name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._getter()(*args, **kwargs)

    def __repr__(self) -> str:
        loaded = globals()[self._loaded_name] is not None
        return f"<lazy {self._role} chat model loaded={loaded}>"


llm = _LazyModelProxy(get_llm, "player", "_llm_instance")
judge_llm = _LazyModelProxy(get_judge_llm, "judge", "_judge_llm_instance")
coach_llm = _LazyModelProxy(get_coach_llm, "coach", "_coach_llm_instance")


__all__ = [
    "CLOUD_MODEL_REGISTRY",
    "DEFAULT_CLOUD_API_BASE",
    "SafeChatOpenAI",
    "coach_llm",
    "configured_model_ids",
    "get_coach_llm",
    "get_judge_llm",
    "get_llm",
    "judge_llm",
    "llm",
    "model_identity",
    "unload_coach_llm",
    "unload_judge_llm",
    "unload_llm",
]
