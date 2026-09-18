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


def test_concurrent_first_load_constructs_once(monkeypatch):
    import threading
    import time

    calls = []

    def slow_constructor(**kwargs):
        calls.append(1)
        time.sleep(0.2)
        instance = MagicMock()
        instance.client = MagicMock()
        return instance

    monkeypatch.setattr(model_downloader, "_llm_instance", None)
    monkeypatch.setattr(model_downloader, "SafeChatLlamaCpp", slow_constructor)
    monkeypatch.setattr(model_downloader.Path, "is_file", lambda self: True)
    monkeypatch.setattr(model_downloader, "get_or_download_model_path", lambda kind: "mock.gguf")
    results = []

    def load():
        results.append(model_downloader.get_llm(n_gpu_layers=0))

    threads = [threading.Thread(target=load) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(calls) == 1
    assert all(result is results[0] for result in results)


def test_inference_gateway_serializes_and_unloads(monkeypatch):
    import asyncio

    monkeypatch.setattr(model_downloader, "_llm_instance", object())
    monkeypatch.setattr(model_downloader, "_judge_llm_instance", object())
    from svc import llm as llm_gateway

    order = []

    async def main():
        async def job(tag):
            def work():
                order.append(f"start-{tag}")
                return tag

            return await llm_gateway.run_inference(work)

        return await asyncio.gather(job("a"), job("b"))

    assert sorted(asyncio.run(main())) == ["a", "b"]
    assert order == ["start-a", "start-b"]
    assert llm_gateway.is_llm_loaded() is True
    llm_gateway.unload_all()
    assert llm_gateway.is_llm_loaded() is False
    assert llm_gateway.is_judge_loaded() is False
