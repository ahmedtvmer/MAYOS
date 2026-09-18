from unittest.mock import MagicMock

from langchain_community.chat_models import ChatLlamaCpp
from llama_cpp import LlamaRAMCache

from utils import model_downloader


def test_production_attaches_bounded_cache_without_inference(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr(model_downloader, "_llm_instance", None)
    monkeypatch.setattr(model_downloader, "SafeChatLlamaCpp", constructor)
    monkeypatch.setattr(model_downloader.Path, "is_file", lambda self: True)
    monkeypatch.setattr(model_downloader, "get_or_download_model_path", lambda kind: "mock.gguf")
    model = model_downloader.get_llm(n_gpu_layers=0)
    assert model is constructor.return_value
    kwargs = constructor.call_args.kwargs
    assert "cache_prompt" not in kwargs
    assert "n_threads_batch" not in ChatLlamaCpp.model_fields
    assert kwargs["n_gpu_layers"] == 0
    assert kwargs["model_kwargs"] == {"offload_kqv": False, "op_offload": False}
    model.client.set_cache.assert_called_once()
    cache = model.client.set_cache.call_args.args[0]
    assert isinstance(cache, LlamaRAMCache)
    assert cache.capacity_bytes == 256 * 1024 * 1024
    assert model_downloader.get_llm() is model
    constructor.assert_called_once()
    model.invoke.assert_not_called()
    model.stream.assert_not_called()


def test_cpu_offload_flags_omitted_for_gpu_layers(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr(model_downloader, "_llm_instance", None)
    monkeypatch.setattr(model_downloader, "SafeChatLlamaCpp", constructor)
    monkeypatch.setattr(model_downloader.Path, "is_file", lambda self: True)
    monkeypatch.setattr(model_downloader, "get_or_download_model_path", lambda kind: "mock.gguf")
    model_downloader.get_llm(n_gpu_layers=8)
    assert constructor.call_args.kwargs["model_kwargs"] == {}


def test_context_failure_on_gpu_retries_on_cpu(monkeypatch):
    constructor = MagicMock(side_effect=[ValueError("Failed to create llama_context"), "cpu-instance"])
    monkeypatch.setattr(model_downloader, "_judge_llm_instance", None)
    monkeypatch.setattr(model_downloader, "ChatLlamaCpp", constructor)
    monkeypatch.setattr(model_downloader, "get_or_download_model_path", lambda kind: "mock.gguf")
    model = model_downloader.get_judge_llm(n_gpu_layers=4)
    assert model == "cpu-instance"
    first, retry = constructor.call_args_list
    assert first.kwargs["n_gpu_layers"] == 4
    assert retry.kwargs["n_gpu_layers"] == 0
    assert retry.kwargs["model_kwargs"] == {"offload_kqv": False, "op_offload": False}


def test_unrelated_failure_is_not_swallowed(monkeypatch):
    constructor = MagicMock(side_effect=ValueError("Corrupt GGUF header"))
    monkeypatch.setattr(model_downloader, "_judge_llm_instance", None)
    monkeypatch.setattr(model_downloader, "ChatLlamaCpp", constructor)
    monkeypatch.setattr(model_downloader, "get_or_download_model_path", lambda kind: "mock.gguf")
    import pytest

    with pytest.raises(ValueError, match="Corrupt GGUF header"):
        model_downloader.get_judge_llm(n_gpu_layers=4)
