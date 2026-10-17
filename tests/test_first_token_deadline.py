"""Focused tests for the bounded first-model-chunk retry."""

from __future__ import annotations

import asyncio
import queue
import time

from langchain_core.messages import AIMessageChunk
import pytest

from agent import assistant_graph
from tests.eval import run_player_chat_measurement as measurement


class _AsyncScriptedStream:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = 0

    def bind_tools(self, _tools, **_kwargs):
        return self

    async def astream(self, _messages, **_kwargs):
        index = self.calls
        self.calls += 1
        delay, content, trailing_error = self.turns[index]
        if delay is None:
            await asyncio.Event().wait()
        elif delay:
            await asyncio.sleep(delay)
        yield AIMessageChunk(content=content)
        if trailing_error is not None:
            await asyncio.sleep(trailing_error[0])
            raise trailing_error[1]


def test_first_token_deadline_retries_and_probe_records_both_provider_attempts(monkeypatch):
    monkeypatch.setenv("LLM_FIRST_TOKEN_TIMEOUT", "0.03")
    monkeypatch.setenv("LLM_FIRST_TOKEN_MAX_ATTEMPTS", "2")
    model = _AsyncScriptedStream([(None, "discarded", None), (0.02, "second answer", None)])
    probe = measurement.FirstChunkProbe(model, time.perf_counter)
    started = time.perf_counter()

    chunks = list(assistant_graph._stream_model_with_first_token_deadline(probe, []))
    elapsed = time.perf_counter() - started

    assert "".join(str(chunk.content) for chunk in chunks) == "second answer"
    assert model.calls == 2
    assert 0.045 <= elapsed < 0.5
    assert len(probe.samples) == 2
    attempts = measurement._model_attempts(probe, 0)
    assert attempts[0]["first_token_deadline_exceeded"] is True
    assert attempts[0]["retried_after_deadline"] is True
    assert attempts[0]["first_model_chunk_seconds"] is None
    assert attempts[1]["first_token_deadline_exceeded"] is False
    assert attempts[1]["first_model_chunk_seconds"] is not None
    assert measurement._first_token_deadline_retries(probe, 0) == 1


def test_empty_metadata_chunk_does_not_bypass_first_token_deadline(monkeypatch):
    monkeypatch.setenv("LLM_FIRST_TOKEN_TIMEOUT", "0.03")
    monkeypatch.setenv("LLM_FIRST_TOKEN_MAX_ATTEMPTS", "2")

    class EmptyThenStallModel:
        calls = 0

        async def astream(self, _messages, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                yield AIMessageChunk(content="")
                await asyncio.Event().wait()
            yield AIMessageChunk(content="recovered answer")

    model = EmptyThenStallModel()
    probe = measurement.FirstChunkProbe(model, time.perf_counter)
    chunks = list(assistant_graph._stream_model_with_first_token_deadline(probe, []))

    assert "".join(str(chunk.content) for chunk in chunks) == "recovered answer"
    assert model.calls == 2
    assert len(probe.samples) == 2
    assert probe.samples[0].first_chunk_at is None
    assert probe.samples[0].first_token_deadline_exceeded is True


def test_empty_stream_is_not_a_first_token_deadline(monkeypatch):
    monkeypatch.setenv("LLM_FIRST_TOKEN_TIMEOUT", "0.03")
    monkeypatch.setenv("LLM_FIRST_TOKEN_MAX_ATTEMPTS", "3")

    class EmptyStreamModel:
        calls = 0

        async def astream(self, _messages, **_kwargs):
            self.calls += 1
            if self.calls:
                return
            yield AIMessageChunk(content="unreachable")

    model = EmptyStreamModel()
    probe = measurement.FirstChunkProbe(model, time.perf_counter)

    assert list(assistant_graph._stream_model_with_first_token_deadline(probe, [])) == []
    assert model.calls == 1
    assert len(probe.samples) == 1
    assert probe.samples[0].first_token_deadline_exceeded is False
    output = assistant_graph._PlayerStreamOutput([])
    assert list(assistant_graph._stream_player_answer([], output)) == [
        assistant_graph.EMPTY_RESPONSE_FALLBACK
    ]


def test_cancelled_producer_releases_consumer_waiting_for_stream_event():
    async def run():
        entered = asyncio.Event()

        class WaitingModel:
            async def astream(self, _messages, **_kwargs):
                entered.set()
                await asyncio.Event().wait()
                yield AIMessageChunk(content="unreachable")

        channel = queue.Queue(maxsize=2)
        producer = asyncio.create_task(
            assistant_graph._produce_player_stream(
                WaitingModel(), [], assistant_graph._FirstTokenStreamSettings(30, 1), channel
            )
        )
        await entered.wait()
        consumer = asyncio.create_task(asyncio.to_thread(channel.get))
        await asyncio.sleep(0.01)

        producer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await producer
        event = await asyncio.wait_for(consumer, timeout=0.5)
        assert event == ("cancelled", None)

    asyncio.run(run())


def test_outer_cancellation_during_attempt_cleanup_is_not_swallowed():
    class CancelOuterWhileAwaitingAttempt:
        def cancel(self):
            pass

        def __await__(self):
            async def cancel_current_task():
                asyncio.current_task().cancel()
                await asyncio.sleep(0)

            return cancel_current_task().__await__()

    asyncio.run(
        _assert_first_token_cleanup_propagates_cancellation(
            CancelOuterWhileAwaitingAttempt()
        )
    )


async def _assert_first_token_cleanup_propagates_cancellation(pending):
    with pytest.raises(asyncio.CancelledError):
        await assistant_graph._raise_first_token_deadline(
            object(), pending, 1.0, []
        )


def test_stream_timeout_after_first_chunk_does_not_retry(monkeypatch):
    monkeypatch.setenv("LLM_FIRST_TOKEN_TIMEOUT", "0.03")
    monkeypatch.setenv("LLM_FIRST_TOKEN_MAX_ATTEMPTS", "3")
    model = _AsyncScriptedStream(
        [(0, "first chunk", (0.01, TimeoutError("later chunk stalled"))), (0, "duplicate", None)]
    )
    stream = assistant_graph._stream_model_with_first_token_deadline(model, [])

    assert next(stream).content == "first chunk"
    with pytest.raises(TimeoutError, match="later chunk stalled"):
        next(stream)
    assert model.calls == 1


def test_last_deadline_attempt_raises_provider_failure(monkeypatch):
    monkeypatch.setenv("LLM_FIRST_TOKEN_TIMEOUT", "0.01")
    monkeypatch.setenv("LLM_FIRST_TOKEN_MAX_ATTEMPTS", "2")
    model = _AsyncScriptedStream([(None, "unused", None), (None, "unused", None)])

    with pytest.raises(assistant_graph._FirstTokenDeadlineTimeout):
        list(assistant_graph._stream_model_with_first_token_deadline(model, []))

    assert model.calls == 2


def test_first_token_attempt_configuration_has_safe_defaults_and_bounds(monkeypatch):
    from utils import model_downloader

    monkeypatch.delenv("LLM_FIRST_TOKEN_TIMEOUT", raising=False)
    monkeypatch.delenv("LLM_FIRST_TOKEN_MAX_ATTEMPTS", raising=False)
    assert model_downloader.first_token_timeout_seconds() == 6.0
    assert model_downloader.first_token_max_attempts() == 2

    monkeypatch.setenv("LLM_FIRST_TOKEN_TIMEOUT", "nan")
    monkeypatch.setenv("LLM_FIRST_TOKEN_MAX_ATTEMPTS", "8")
    assert model_downloader.first_token_timeout_seconds() == 6.0
    assert model_downloader.first_token_max_attempts() == 2
