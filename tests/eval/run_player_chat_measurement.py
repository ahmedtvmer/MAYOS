"""Measure the live player-chat streaming path: user wait, visible latency, cache, cost.

Streams a synthetic five-turn player session through the real
``agent.assistant_graph.stream_assistant_turn`` generator — the same generator
the SSE ``POST /chat/messages`` route consumes — and records, per *attempt*:

* seconds from starting the attempt to the first visible text chunk,
* seconds to the first model chunk and the pre-stream code time before it,
* input, output and cached input tokens, cached input share and USD cost.

Accounting rules (ADR 038 metering; see ``utils.model_metering``):

* Every attempt of a logical turn is retained, including failed and retried
  ones, with its own elapsed time, retry backoff, error and recorded usage. A
  failed attempt is never overwritten by the eventual successful attempt.
* Latency is reported two ways: the *end-to-end user wait* (every attempt plus
  its retry backoff until the successful answer's first visible text, i.e. what
  the player experiences) and the *successful-attempt visible latency* (the
  eventual answer attempt's own first-visible latency, which includes graph and
  output work and is not a pure provider/model-stream TTFT; the first model
  chunk time is recorded separately). A failed attempt's pipeline error
  placeholder is not counted as a first token.
* Usage totals are the sum of every *known* usage row across all attempts,
  including the known rows of a ``partial`` attempt (some sub-call recorded, the
  errored call did not). Only the unreported remainder of a failed attempt is
  unknown and excluded (``unknown`` = nothing recorded); usage is never assumed
  to be zero. The known token and cost totals are labelled a lower bound when
  any usage is unreported. A recorded-token cache share is not a lower bound:
  it is only the fraction among the tokens that were reported, and the overall
  share is unknown while usage is incomplete.

Retry policy — kept explicit and distinct from production:

* This harness builds the model with ``build_player_llm(timeout=..., max_retries=0)``
  and may retry a logical turn up to ``max_turn_attempts`` times, only for a
  transient provider-busy (HTTP 429/overloaded) or timeout failure, with a fixed
  backoff. All of those attempts are recorded.
* Production player chat (``utils.model_downloader.get_llm``) relies on the
  OpenAI SDK's own retries (``LLM_MAX_RETRIES`` default 1, request timeout 60 s,
  stream-chunk timeout 30 s). Those SDK retries happen inside one call and are
  invisible to, and uncounted by, this harness.

The report is truthful measurement evidence, never a release gate: it records
whether the 2.0-second median target was met without changing the provider,
model or prompt order. It is written as a paired, run-versioned JSON and
Markdown file naming the provider, model, endpoint, base commit and sample
counts; every request is bounded by ``--timeout`` and a ``--max-seconds``
wall-clock budget stops the run instead of sweeping forever.

The metering summary reuses
``tests.eval.run_player_memory_sweep.summarize_usage`` and the live model is the
configured hosted player model built by ``utils.model_downloader``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(BASE_DIR))

from langchain_core.messages import HumanMessage  # noqa: E402

from agent.assistant_graph import stream_assistant_turn  # noqa: E402
from agent.prompts import DEFAULT_ASSISTANT_STYLE  # noqa: E402
from service.chat import build_turn_state  # noqa: E402
from tests.eval.run_player_memory_sweep import summarize_usage  # noqa: E402
from utils.model_metering import scoped_usage_recorder  # noqa: E402
from utils.text_scrubber import PIPELINE_ERROR_RESPONSE  # noqa: E402

#: Synthetic player identity; no real account or training ledger is touched.
SYNTHETIC_PLAYER_ID = "ttft_probe_player"

#: Five synthetic English free-form coaching turns (unreviewed; no fixed replies).
PLAYER_SESSION_QUESTIONS = (
    "How should I adjust my training if I feel tired this week?",
    "What should I focus on during a warm-up before heavy squats?",
    "How much protein do I need on the days I do not train?",
    "My bench press feels stuck; what could help?",
    "How do I know when to increase the weight on a lift?",
)

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_SECONDS = 300.0
DEFAULT_TURN_ATTEMPTS = 1
LIVE_TURN_ATTEMPTS = 3
LIVE_RETRY_BACKOFF_SECONDS = 3.0
TTFT_TARGET_SECONDS = 2.0

#: Documented so a reader can tell the probe's retry policy from production's.
MEASUREMENT_RETRY_POLICY = (
    "Measurement harness: model built with build_player_llm(timeout=..., max_retries=0); "
    "up to max_turn_attempts (live: 3) per logical turn, retrying only a transient provider-busy "
    "(HTTP 429/overloaded) or timeout failure with a fixed backoff; every attempt is recorded."
)
PRODUCTION_RETRY_POLICY = (
    "Production player chat (utils.model_downloader.get_llm): OpenAI SDK retries inside one call "
    "(LLM_MAX_RETRIES default 1, request timeout 60 s, stream-chunk timeout 30 s). Those SDK retries "
    "are invisible to and uncounted by this harness."
)
ACCOUNTING_NOTE = (
    "Every attempt of a logical turn is retained with its elapsed time, retry backoff, error and known "
    "usage. Latency is split into the end-to-end user wait (all attempts + backoff) and the successful "
    "attempt's visible latency (its own first-visible text, not a pure provider/model-stream TTFT). "
    "Usage totals sum every known row, including the known rows of partial attempts; only the "
    "unreported remainder of a failed attempt is unknown and excluded (never counted as zero), so the "
    "known token and cost sums are a lower bound when any usage is unreported. A recorded-token cache "
    "share is not a lower bound: it is the fraction among reported tokens, and the overall share is "
    "unknown while usage is incomplete."
)

#: Committed #265 provider-smoke baseline (direct prompt stream, 2026-10-11) and
#: the #192 player-session measurement (2026-10-12), quoted for comparison only.
BASELINE_NOTES = (
    "#265 provider smoke (2026-10-11, direct `build_player_chat_prompt` stream, n=5 per category): "
    "median model TTFT 1.29-2.45 s with p90 outliers 32-63 s.",
    "#192 player session (2026-10-12, median time to first token): 9.52 s on master and 9.17 s with a "
    "stable-prefix prompt order, provider-slow window; cached share was already nonzero in 256/512-token blocks.",
)


@dataclass(frozen=True)
class FirstChunkSample:
    """One streamed model call: when it started and when its first output arrived.

    ``first_chunk_at`` is ``None`` when the call failed before producing any
    model output, so a failure is never mistaken for a fast first chunk.
    """

    started: float
    first_chunk_at: float | None


@dataclass
class AttemptMeasurement:
    """One attempt at one logical turn; failed and retried attempts are retained."""

    turn: int
    attempt: int
    status: str
    elapsed_seconds: float
    retry_backoff_seconds: float = 0.0
    first_visible_text_seconds: float | None = None
    first_model_chunk_seconds: float | None = None
    pre_stream_seconds: float | None = None
    intent: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cached_input_share: float | None = None
    cost_usd: float | None = None
    model_calls: int = 0
    estimated_calls: int = 0
    usage_reported: bool = False
    usage_unknown: bool = False
    timed_out: bool = False
    reply_chars: int = 0
    error: str = ""

    @property
    def usage_state(self) -> str:
        """``reported`` | ``estimated`` | ``partial`` | ``unknown`` | ``none``."""
        if self.usage_unknown:
            return "unknown"
        if self.status == "error" and self.usage_reported:
            return "partial"
        if self.estimated_calls:
            return "estimated"
        if self.usage_reported:
            return "reported"
        return "none"


@dataclass
class TurnMeasurement:
    """One logical turn: the ordered list of every attempt that ran for it."""

    turn: int
    query: str
    status: str
    intent: str | None = None
    attempts: list[AttemptMeasurement] = field(default_factory=list)


@dataclass
class PlayerSessionMeasurement:
    turns: list[TurnMeasurement] = field(default_factory=list)
    stopped_early: bool = False
    provider: str = ""
    model: str = ""
    api_base: str = ""


def _chunk_has_output(chunk: Any) -> bool:
    if getattr(chunk, "tool_call_chunks", None):
        return True
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return bool(content)
    if isinstance(content, list):
        return any(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
    return bool(content)


class FirstChunkProbe:
    """Wraps a chat model to record the first streamed output time of each call.

    Mirrors the ``StreamingInvokeAdapter`` seam from the memory sweep, but keeps
    the real ``stream`` interface the player path uses instead of an ``invoke``
    adapter, so first model chunk and first visible text are measured separately.
    """

    def __init__(
        self,
        model: Any,
        clock: Callable[[], float],
        samples: list[FirstChunkSample] | None = None,
        errors: list[Exception] | None = None,
    ) -> None:
        self._model = model
        self._clock = clock
        self.samples: list[FirstChunkSample] = samples if samples is not None else []
        self.errors: list[Exception] = errors if errors is not None else []

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FirstChunkProbe":
        return FirstChunkProbe(
            self._model.bind_tools(tools, **kwargs), self._clock, self.samples, self.errors
        )

    def stream(self, messages: Any, *args: Any, **kwargs: Any):
        started = self._clock()
        first_chunk_at: float | None = None
        try:
            for chunk in self._model.stream(messages, *args, **kwargs):
                if first_chunk_at is None and _chunk_has_output(chunk):
                    first_chunk_at = self._clock()
                yield chunk
        except Exception as error:  # noqa: BLE001 - recorded for the failed-sample report
            self.errors.append(error)
            raise
        finally:
            self.samples.append(FirstChunkSample(started, first_chunk_at))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._model, name)


def _is_timeout_error(error: Exception) -> bool:
    name = type(error).__name__.lower()
    return "timeout" in name or "timed out" in str(error).lower()


def _usage_fields(usage_events: list[dict[str, Any]]) -> dict[str, Any]:
    """The known usage of one attempt from its captured metering rows."""
    usage = summarize_usage(list(usage_events), 1)
    reported = usage["metered_player_calls"] > 0
    return {
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cached_input_tokens": usage["cached_input_tokens"],
        "cached_input_share": usage["cached_input_share"],
        "cost_usd": usage["cost_usd"],
        "model_calls": usage["metered_player_calls"],
        "estimated_calls": usage["estimated_calls"],
        "usage_reported": reported,
    }


def _measure_attempt(
    turn_index: int,
    attempt_number: int,
    query: str,
    history: list[Any],
    *,
    ledger: Any,
    store: Any,
    probe: FirstChunkProbe,
    clock: Callable[[], float],
    retry_backoff_seconds: float,
) -> tuple[AttemptMeasurement, list[Any]]:
    tail = [*history, HumanMessage(content=query)]
    state = build_turn_state(SYNTHETIC_PLAYER_ID, tail, coach_tone=DEFAULT_ASSISTANT_STYLE)
    usage_events: list[dict[str, Any]] = []
    sample_start = len(probe.samples)
    error_start = len(probe.errors)
    attempt_started = clock()
    first_visible: float | None = None
    try:
        with scoped_usage_recorder(lambda **row: usage_events.append(row)):
            for _piece in stream_assistant_turn(state, ledger=ledger, store=store):
                if first_visible is None:
                    first_visible = clock() - attempt_started
    except Exception as error:  # noqa: BLE001 - failures outside the generator become failed samples
        return _failed_attempt(
            turn_index,
            attempt_number,
            probe,
            sample_start,
            error_start,
            attempt_started,
            clock,
            usage_events,
            error,
            retry_backoff_seconds,
        )
    return _completed_attempt(
        turn_index,
        attempt_number,
        state,
        probe,
        sample_start,
        error_start,
        attempt_started,
        first_visible,
        clock,
        usage_events,
        retry_backoff_seconds,
    )


def _failed_attempt(
    turn_index: int,
    attempt_number: int,
    probe: FirstChunkProbe,
    sample_start: int,
    error_start: int,
    attempt_started: float,
    clock: Callable[[], float],
    usage_events: list[dict[str, Any]],
    error: Exception,
    retry_backoff_seconds: float,
) -> tuple[AttemptMeasurement, list[Any]]:
    elapsed = max(0.0, clock() - attempt_started)
    fields = _usage_fields(usage_events)
    attempt = AttemptMeasurement(
        turn=turn_index,
        attempt=attempt_number,
        status="error",
        elapsed_seconds=elapsed,
        retry_backoff_seconds=retry_backoff_seconds,
        first_model_chunk_seconds=_first_model_chunk(probe, sample_start, attempt_started),
        pre_stream_seconds=_pre_stream(probe, sample_start, attempt_started),
        timed_out=_is_timeout_error(error),
        error=f"{type(error).__name__}: {error}",
        usage_unknown=not fields["usage_reported"],
        **fields,
    )
    return attempt, []


def _completed_attempt(
    turn_index: int,
    attempt_number: int,
    state: dict[str, Any],
    probe: FirstChunkProbe,
    sample_start: int,
    error_start: int,
    attempt_started: float,
    first_visible: float | None,
    clock: Callable[[], float],
    usage_events: list[dict[str, Any]],
    retry_backoff_seconds: float,
) -> tuple[AttemptMeasurement, list[Any]]:
    elapsed = max(0.0, clock() - attempt_started)
    fields = _usage_fields(usage_events)
    reply = str(state.get("response_content") or "")
    turn_errors = probe.errors[error_start:]
    status = _turn_status(reply, fields["model_calls"], turn_errors)
    first_model_chunk = _first_model_chunk(probe, sample_start, attempt_started)
    # On a failure with no model output the generator yields the pipeline error
    # placeholder; that text is not a model first token and must not be timed as one.
    if status == "error" and first_model_chunk is None:
        first_visible = None
    attempt = AttemptMeasurement(
        turn=turn_index,
        attempt=attempt_number,
        status=status,
        elapsed_seconds=elapsed,
        retry_backoff_seconds=retry_backoff_seconds,
        first_visible_text_seconds=first_visible,
        first_model_chunk_seconds=first_model_chunk,
        pre_stream_seconds=_pre_stream(probe, sample_start, attempt_started),
        intent=state.get("intent"),
        timed_out=any(_is_timeout_error(error) for error in turn_errors),
        reply_chars=len(reply),
        error="; ".join(f"{type(error).__name__}: {error}" for error in turn_errors),
        usage_unknown=status == "error" and not fields["usage_reported"],
        **fields,
    )
    return attempt, list(state.get("messages", []))


def _turn_status(reply: str, model_calls: int, turn_errors: list[Exception]) -> str:
    if turn_errors or PIPELINE_ERROR_RESPONSE in reply:
        return "error"
    return "ok" if model_calls else "deterministic"


def _first_model_chunk(probe: FirstChunkProbe, sample_start: int, attempt_started: float) -> float | None:
    samples = probe.samples[sample_start:]
    if not samples or samples[0].first_chunk_at is None:
        return None
    return max(0.0, samples[0].first_chunk_at - attempt_started)


def _pre_stream(probe: FirstChunkProbe, sample_start: int, attempt_started: float) -> float | None:
    samples = probe.samples[sample_start:]
    return max(0.0, samples[0].started - attempt_started) if samples else None


def run_player_session(
    model: Any,
    *,
    ledger: Any,
    store: Any,
    questions: tuple[str, ...] = PLAYER_SESSION_QUESTIONS,
    clock: Callable[[], float] = time.perf_counter,
    max_seconds: float | None = DEFAULT_MAX_SECONDS,
    max_turn_attempts: int = DEFAULT_TURN_ATTEMPTS,
    retry_backoff_seconds: float = 0.0,
) -> PlayerSessionMeasurement:
    """Streams one synthetic session and returns per-attempt evidence.

    ``max_turn_attempts`` allows a bounded retry of a turn that fails for a
    transient provider-busy reason (429/overload) or a timeout. Every attempt is
    retained; a successful retry does not erase the failed attempt's time, usage
    or error.
    """
    from agent import assistant_graph

    probe = FirstChunkProbe(model, clock)
    original_llm = assistant_graph.llm
    assistant_graph.llm = probe
    session = PlayerSessionMeasurement(model=str(getattr(model, "model_name", "") or ""))
    started = clock()
    history: list[Any] = []
    try:
        for index, query in enumerate(questions, start=1):
            if max_seconds is not None and (clock() - started) > max_seconds:
                session.stopped_early = True
                session.turns.append(
                    TurnMeasurement(index, query, "skipped")
                )
                continue
            turn, new_history = _run_turn(
                index,
                query,
                history,
                ledger=ledger,
                store=store,
                probe=probe,
                clock=clock,
                max_turn_attempts=max_turn_attempts,
                retry_backoff_seconds=retry_backoff_seconds,
                started=started,
                max_seconds=max_seconds,
            )
            history = new_history
            session.turns.append(turn)
    finally:
        assistant_graph.llm = original_llm
    return session


def _run_turn(
    index: int,
    query: str,
    history: list[Any],
    *,
    ledger: Any,
    store: Any,
    probe: FirstChunkProbe,
    clock: Callable[[], float],
    max_turn_attempts: int,
    retry_backoff_seconds: float,
    started: float,
    max_seconds: float | None,
) -> tuple[TurnMeasurement, list[Any]]:
    attempts: list[AttemptMeasurement] = []
    new_history = history
    limit = max(1, max_turn_attempts)
    for attempt_number in range(1, limit + 1):
        backoff = 0.0
        if attempt_number > 1:
            if max_seconds is not None and (clock() - started) > max_seconds:
                break
            time.sleep(retry_backoff_seconds)
            backoff = retry_backoff_seconds
        attempt, new_history = _measure_attempt(
            index,
            attempt_number,
            query,
            history,
            ledger=ledger,
            store=store,
            probe=probe,
            clock=clock,
            retry_backoff_seconds=backoff,
        )
        attempts.append(attempt)
        if not _is_transient_failure(attempt):
            break
    status = attempts[-1].status if attempts else "error"
    intent = next((a.intent for a in reversed(attempts) if a.intent), None)
    return TurnMeasurement(turn=index, query=query, status=status, intent=intent, attempts=attempts), new_history


def _is_transient_failure(attempt: AttemptMeasurement) -> bool:
    """A provider-busy or timeout failure a bounded retry may recover."""
    if attempt.status != "error":
        return False
    if attempt.timed_out:
        return True
    message = attempt.error.lower()
    return any(marker in message for marker in ("429", "overload", "busy", "rate limit"))


def _turn_end_to_end_seconds(turn: TurnMeasurement) -> float:
    """Total wall time the player waited: every attempt plus its retry backoff."""
    return sum(attempt.retry_backoff_seconds + attempt.elapsed_seconds for attempt in turn.attempts)


def _turn_end_to_end_first_visible_text_seconds(turn: TurnMeasurement) -> float | None:
    """Seconds until the player sees the *successful* answer's first text.

    Counts every earlier failed attempt and its backoff, but not an error
    placeholder: a failed attempt is not a first token.
    """
    offset = 0.0
    for attempt in turn.attempts:
        offset += attempt.retry_backoff_seconds
        if attempt.status == "ok":
            if attempt.first_visible_text_seconds is None:
                return None
            return offset + attempt.first_visible_text_seconds
        offset += attempt.elapsed_seconds
    return None


def _successful_attempt(turn: TurnMeasurement) -> AttemptMeasurement | None:
    for attempt in reversed(turn.attempts):
        if attempt.status == "ok":
            return attempt
    return None


def _successful_attempt_visible_latency(turn: TurnMeasurement) -> float | None:
    """The successful attempt's own first-visible-text latency.

    This is *visible* latency (graph + output work included), not a pure
    provider/model-stream TTFT; the first model chunk time is recorded separately
    as ``first_model_chunk_seconds``.
    """
    attempt = _successful_attempt(turn)
    return attempt.first_visible_text_seconds if attempt is not None else None


def _turn_known_usage(turn: TurnMeasurement) -> dict[str, Any]:
    usage = _aggregate_attempts(turn.attempts)
    usage["first_model_chunk_seconds"] = (
        _successful_attempt(turn).first_model_chunk_seconds if _successful_attempt(turn) else None
    )
    usage["pre_stream_seconds"] = (
        _successful_attempt(turn).pre_stream_seconds if _successful_attempt(turn) else None
    )
    return usage


def _aggregate_attempts(attempts: list[AttemptMeasurement]) -> dict[str, Any]:
    known_input = sum(attempt.input_tokens for attempt in attempts)
    known_cached = sum(attempt.cached_input_tokens for attempt in attempts)
    known_output = sum(attempt.output_tokens for attempt in attempts)
    known_cost = sum(attempt.cost_usd or 0.0 for attempt in attempts)
    unreported = sum(attempt.usage_state == "unknown" for attempt in attempts)
    partial = sum(attempt.usage_state == "partial" for attempt in attempts)
    estimated = sum(attempt.usage_state == "estimated" for attempt in attempts)
    return {
        "known_input_tokens": known_input,
        "known_cached_input_tokens": known_cached,
        "known_output_tokens": known_output,
        "known_cost_usd": known_cost,
        "model_calls": sum(attempt.model_calls for attempt in attempts),
        "estimated_calls": sum(attempt.estimated_calls for attempt in attempts),
        "unreported_attempts": unreported,
        "partial_attempts": partial,
        "estimated_attempts": estimated,
        "usage_complete": unreported == 0 and partial == 0,
    }


def summarize_session(session: PlayerSessionMeasurement) -> dict[str, Any]:
    """Aggregates latency, cache and cost over every attempt, without losing failures."""
    turns = session.turns
    measured = [turn for turn in turns if turn.status == "ok"]
    attempts = [attempt for turn in turns for attempt in turn.attempts]

    end_to_end = [
        value
        for value in (_turn_end_to_end_first_visible_text_seconds(turn) for turn in measured)
        if value is not None
    ]
    successful_visible_latency = [
        value
        for value in (_successful_attempt_visible_latency(turn) for turn in measured)
        if value is not None
    ]
    model_chunks = [
        attempt.first_model_chunk_seconds
        for turn in measured
        if (attempt := _successful_attempt(turn)) is not None and attempt.first_model_chunk_seconds is not None
    ]
    pre_stream = [
        attempt.pre_stream_seconds
        for turn in measured
        if (attempt := _successful_attempt(turn)) is not None and attempt.pre_stream_seconds is not None
    ]

    overall = _aggregate_attempts(attempts)
    from_turn_2 = _aggregate_attempts([attempt for turn in turns if turn.turn >= 2 for attempt in turn.attempts])
    from_turn_2_input = from_turn_2["known_input_tokens"]
    from_turn_2_cached = from_turn_2["known_cached_input_tokens"]
    turn_2 = _aggregate_attempts([attempt for turn in turns if turn.turn == 2 for attempt in turn.attempts])

    median_end_to_end = statistics.median(end_to_end) if end_to_end else None
    median_successful_visible_latency = (
        statistics.median(successful_visible_latency) if successful_visible_latency else None
    )
    return {
        "turns_total": len(turns),
        "turns_measured": len(measured),
        "turns_deterministic": sum(turn.status == "deterministic" for turn in turns),
        "turns_failed": sum(turn.status == "error" for turn in turns),
        "turns_skipped": sum(turn.status == "skipped" for turn in turns),
        "attempts_total": len(attempts),
        "attempts_failed": sum(attempt.status == "error" for attempt in attempts),
        "attempts_timed_out": sum(attempt.timed_out for attempt in attempts),
        "attempts_unreported_usage": overall["unreported_attempts"],
        "attempts_partial_usage": overall["partial_attempts"],
        "model_stream_samples": overall["model_calls"],
        "stopped_early": session.stopped_early,
        "median_end_to_end_first_visible_text_seconds": median_end_to_end,
        "median_successful_attempt_visible_latency_seconds": median_successful_visible_latency,
        "median_first_model_chunk_seconds": statistics.median(model_chunks) if model_chunks else None,
        "median_pre_stream_seconds": statistics.median(pre_stream) if pre_stream else None,
        "first_visible_text_samples": len(end_to_end),
        "known_input_tokens": overall["known_input_tokens"],
        "known_cached_input_tokens": overall["known_cached_input_tokens"],
        "known_output_tokens": overall["known_output_tokens"],
        "known_cost_usd": overall["known_cost_usd"],
        "known_cost_per_turn_usd": overall["known_cost_usd"] / len(turns) if turns else None,
        "usage_complete": overall["usage_complete"],
        "from_turn_2_input_tokens": from_turn_2_input,
        "from_turn_2_cached_input_tokens": from_turn_2_cached,
        "cached_input_share_from_turn_2": (
            from_turn_2_cached / from_turn_2_input if from_turn_2_input else None
        ),
        "from_turn_2_usage_complete": from_turn_2["usage_complete"],
        "turn_2_input_tokens": turn_2["known_input_tokens"],
        "turn_2_cached_input_tokens": turn_2["known_cached_input_tokens"],
        "turn_2_usage_complete": turn_2["usage_complete"],
        "median_first_visible_text_within_2_seconds": (
            median_end_to_end <= TTFT_TARGET_SECONDS if median_end_to_end is not None else None
        ),
        "median_successful_attempt_visible_latency_within_2_seconds": (
            median_successful_visible_latency <= TTFT_TARGET_SECONDS
            if median_successful_visible_latency is not None
            else None
        ),
    }


def _provider_name(api_base: str) -> str:
    host = urlparse(api_base).hostname or api_base
    return "DeepInfra" if host.lower().endswith("deepinfra.com") else host


def _base_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=BASE_DIR, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _attempt_to_dict(attempt: AttemptMeasurement) -> dict[str, Any]:
    row = dict(attempt.__dict__)
    row["usage_state"] = attempt.usage_state
    return row


def _turn_to_dict(turn: TurnMeasurement) -> dict[str, Any]:
    return {
        "turn": turn.turn,
        "query": turn.query,
        "status": turn.status,
        "intent": turn.intent,
        "attempts": len(turn.attempts),
        "end_to_end_seconds": _turn_end_to_end_seconds(turn),
        "end_to_end_first_visible_text_seconds": _turn_end_to_end_first_visible_text_seconds(turn),
        "successful_attempt_visible_latency_seconds": _successful_attempt_visible_latency(turn),
        "known_usage": _turn_known_usage(turn),
        "attempt_rows": [_attempt_to_dict(attempt) for attempt in turn.attempts],
    }


def _acceptance_criteria(aggregate: dict[str, Any]) -> dict[str, Any]:
    """The issue's carried-over criteria, marked honestly from this run.

    The cache/session criterion is only ``MET`` when a full five-turn session
    succeeded *and* logical turn 2 recorded nonzero cached input tokens. Later
    turns may miss; the aggregate turn-2-onward share is reported for context but
    cannot by itself certify the criterion, because later reuse with zero turn-2
    reuse is not evidence of reuse *from turn 2*. Unknown turn-2 cache evidence
    (unreported/partial usage) is not demonstrated and never yields ``MET``.
    """
    median_wait = aggregate["median_end_to_end_first_visible_text_seconds"]
    if median_wait is None:
        latency_status = "UNKNOWN"
    elif median_wait <= TTFT_TARGET_SECONDS:
        latency_status = "MET"
    else:
        latency_status = "UNMET"

    required_turns = len(PLAYER_SESSION_QUESTIONS)
    full_session = (
        aggregate["turns_measured"] == required_turns and aggregate["turns_failed"] == 0
    )
    turn_2_cached = aggregate["turn_2_cached_input_tokens"]
    turn_2_reuse = turn_2_cached is not None and turn_2_cached > 0
    return {
        "median_visible_latency_within_target": {
            "target_seconds": TTFT_TARGET_SECONDS,
            "median_end_to_end_first_visible_text_seconds": median_wait,
            "status": latency_status,
        },
        "nonzero_cached_share_from_turn_2_full_session": {
            "required_turns": required_turns,
            "turns_measured": aggregate["turns_measured"],
            "turn_2_input_tokens": aggregate["turn_2_input_tokens"],
            "turn_2_cached_input_tokens": turn_2_cached,
            "turn_2_usage_complete": aggregate["turn_2_usage_complete"],
            "aggregate_cached_input_share_from_turn_2": aggregate["cached_input_share_from_turn_2"],
            "status": "MET" if (full_session and turn_2_reuse) else "PARTIAL / NOT DEMONSTRATED",
        },
    }


def build_report(
    session: PlayerSessionMeasurement,
    *,
    provider: str,
    model: str,
    api_base: str,
    timeout_seconds: float,
    max_seconds: float,
    measured_at: str | None = None,
) -> dict[str, Any]:
    """The machine-readable report: metadata, per-attempt rows and aggregates."""
    aggregate = summarize_session(session)
    return {
        "report_version": 2,
        "generated_at": measured_at or datetime.now(UTC).isoformat(),
        "mode": "live",
        "path": "assistant_graph.stream_assistant_turn (SSE chat route generator)",
        "provider": provider,
        "model": model,
        "api_base": api_base,
        "base_commit": _base_commit(),
        "request_timeout_seconds": timeout_seconds,
        "max_seconds": max_seconds,
        "ttft_target_seconds": TTFT_TARGET_SECONDS,
        "ttft_definition": (
            "End-to-end user wait = seconds from starting a logical turn to the successful answer's "
            "first visible text, including every earlier failed attempt and its retry backoff (an error "
            "placeholder is not counted). Successful-attempt visible latency = that answer attempt's own "
            "first-visible latency, which includes graph/output work and is not a pure provider/model-"
            "stream TTFT; the first model chunk time is recorded separately."
        ),
        "accounting": ACCOUNTING_NOTE,
        "retry_policy": {"measurement": MEASUREMENT_RETRY_POLICY, "production": PRODUCTION_RETRY_POLICY},
        "questions": list(PLAYER_SESSION_QUESTIONS),
        "baseline_comparison": list(BASELINE_NOTES),
        "acceptance_criteria": _acceptance_criteria(aggregate),
        "aggregate": aggregate,
        "turns": [_turn_to_dict(turn) for turn in session.turns],
    }


def _format_seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f} s"


def _format_cost(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.6f}"


def _format_share(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _usage_label(usage: dict[str, Any]) -> str:
    if usage["unreported_attempts"] or usage["partial_attempts"] or usage["estimated_attempts"]:
        parts = []
        if usage["partial_attempts"]:
            parts.append(f"{usage['partial_attempts']} partial (known rows included)")
        if usage["estimated_attempts"]:
            parts.append(f"{usage['estimated_attempts']} estimated")
        if usage["unreported_attempts"]:
            parts.append(f"{usage['unreported_attempts']} unknown (no usage recorded)")
        return "lower bound: " + ", ".join(parts)
    return "reported"


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    aggregate = report["aggregate"]
    lines = [
        "# Player chat streaming measurement",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Report version: `{report['report_version']}` (per-attempt retention; the historical "
        f"version-1 reports are final-attempt-only and kept in `reports/player-chat-measurement/`)",
        f"- Streamed path: {report['path']}",
        f"- Provider: {report['provider']}",
        f"- Model: `{report['model']}`",
        f"- Endpoint: `{report['api_base']}`",
        f"- Base commit: `{report['base_commit']}`",
        f"- Request timeout: `{report['request_timeout_seconds']:.1f}s`; wall-clock budget: "
        f"`{report['max_seconds']:.1f}s`",
        f"- Turns: {aggregate['turns_measured']} measured / {aggregate['turns_failed']} failed / "
        f"{aggregate['turns_skipped']} skipped of {aggregate['turns_total']}; attempts: "
        f"{aggregate['attempts_total']} total, {aggregate['attempts_failed']} failed, "
        f"{aggregate['attempts_timed_out']} timed out; model stream calls: "
        f"{aggregate['model_stream_samples']}",
        "",
        "## Accounting",
        "",
        f"- {report['accounting']}",
        f"- Measurement retry policy: {report['retry_policy']['measurement']}",
        f"- Production retry policy: {report['retry_policy']['production']}",
        "",
        "## Per-turn summary",
        "",
        "| Turn | Intent | Status | Attempts | End-to-end first text (user wait) | "
        "Successful-attempt visible latency | Known cost | Usage |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for turn in report["turns"]:
        lines.append(
            f"| {turn['turn']} | {turn.get('intent') or '-'} | {turn['status']} | {turn['attempts']} | "
            f"{_format_seconds(turn['end_to_end_first_visible_text_seconds'])} | "
            f"{_format_seconds(turn['successful_attempt_visible_latency_seconds'])} | "
            f"{_format_cost(turn['known_usage']['known_cost_usd'])} | {_usage_label(turn['known_usage'])} |"
        )

    lines += [
        "",
        "## Per-attempt detail",
        "",
        "| Turn | Attempt | Status | Backoff | Elapsed | First visible | First model chunk | "
        "Pre-stream | Input | Cached | Output | Cached share | Cost | Usage | Error |",
        "| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for turn in report["turns"]:
        for attempt in turn["attempt_rows"]:
            lines.append(
                f"| {attempt['turn']} | {attempt['attempt']} | {attempt['status']} | "
                f"{_format_seconds(attempt['retry_backoff_seconds'])} | "
                f"{_format_seconds(attempt['elapsed_seconds'])} | "
                f"{_format_seconds(attempt['first_visible_text_seconds'])} | "
                f"{_format_seconds(attempt['first_model_chunk_seconds'])} | "
                f"{_format_seconds(attempt['pre_stream_seconds'])} | {attempt['input_tokens']} | "
                f"{attempt['cached_input_tokens']} | {attempt['output_tokens']} | "
                f"{_format_share(attempt['cached_input_share'])} | {_format_cost(attempt['cost_usd'])} | "
                f"{attempt['usage_state']} | {_cell(attempt['error']) or '-'} |"
            )

    within = aggregate["median_first_visible_text_within_2_seconds"]
    within_visible = aggregate["median_successful_attempt_visible_latency_within_2_seconds"]
    target = report["ttft_target_seconds"]
    acceptance = report["acceptance_criteria"]
    latency_criterion = acceptance["median_visible_latency_within_target"]
    cache_criterion = acceptance["nonzero_cached_share_from_turn_2_full_session"]
    lines += [
        "",
        "## Aggregate",
        "",
        f"- Median user-visible first text (end-to-end, all attempts + backoff): "
        f"**{_format_seconds(aggregate['median_end_to_end_first_visible_text_seconds'])}** "
        f"(n={aggregate['first_visible_text_samples']})",
        f"- Median successful-attempt visible latency: "
        f"**{_format_seconds(aggregate['median_successful_attempt_visible_latency_seconds'])}**",
        f"- Median first model chunk: {_format_seconds(aggregate['median_first_model_chunk_seconds'])}",
        f"- Median pre-stream code time: {_format_seconds(aggregate['median_pre_stream_seconds'])}",
        f"- Cached input share from turn 2: **{_format_share(aggregate['cached_input_share_from_turn_2'])}** "
        f"({aggregate['from_turn_2_cached_input_tokens']}/{aggregate['from_turn_2_input_tokens']} input "
        f"tokens from turn 2 onward; share among recorded tokens"
        + ("" if aggregate["from_turn_2_usage_complete"] else "; overall share unknown — some usage unreported")
        + ")",
        f"- Known cost across all attempts: **{_format_cost(aggregate['known_cost_usd'])}** "
        f"({_format_cost(aggregate['known_cost_per_turn_usd'])} per turn; known rows from "
        f"{aggregate['attempts_partial_usage']} partial attempt(s) included; lower bound — "
        f"{aggregate['attempts_unreported_usage']} attempt(s) with unreported usage unknown; "
        f"complete: {aggregate['usage_complete']})",
        f"- Median user-visible first text within {target:.1f}s: "
        f"**{_mark(within)}**",
        f"- Median successful-attempt visible latency within {target:.1f}s: **{_mark(within_visible)}**",
        "",
        "## Acceptance criteria",
        "",
        f"- Median time to first visible text ≤ {target:.1f}s: **{latency_criterion['status']}** "
        f"(median {_format_seconds(latency_criterion['median_end_to_end_first_visible_text_seconds'])})",
        f"- Nonzero recorded cache reuse on logical turn 2 in a full "
        f"{cache_criterion['required_turns']}-turn session: **{cache_criterion['status']}** "
        f"({cache_criterion['turns_measured']}/{cache_criterion['required_turns']} turns measured; "
        f"turn 2 recorded {cache_criterion['turn_2_cached_input_tokens']}/"
        f"{cache_criterion['turn_2_input_tokens']} cached/input tokens, usage complete: "
        f"{cache_criterion['turn_2_usage_complete']}; aggregate share from turn 2 onward "
        f"{_format_share(cache_criterion['aggregate_cached_input_share_from_turn_2'])})",
        "",
        "## Baseline comparison",
        "",
    ]
    lines.extend(f"- {note}" for note in report["baseline_comparison"])
    lines.append("")
    return "\n".join(lines)


def _mark(value: bool | None) -> str:
    if value is None:
        return "UNKNOWN (no measured turns)"
    return "MET" if value else "UNMET"


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)


def _build_store() -> Any:
    """A throwaway store that seeds from the configured catalog when one exists."""
    from database.database_manager import DEFAULT_CATALOG_PATH, DatabaseManager

    tmp = Path(tempfile.mkdtemp(prefix="player-chat-measurement-"))
    catalog_path = tmp / "catalog.db"
    try:
        if DEFAULT_CATALOG_PATH.is_file():
            shutil.copyfile(DEFAULT_CATALOG_PATH, catalog_path)
    except OSError:
        pass
    return DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp / "users",
        backups_dir=tmp / "backups",
    )


def run_live_measurement(
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Builds the configured hosted player model and measures one synthetic session."""
    from utils.model_downloader import DEFAULT_CLOUD_API_BASE, build_player_llm

    api_base = os.getenv("LLM_API_BASE", "").strip() or DEFAULT_CLOUD_API_BASE
    model = build_player_llm(timeout=timeout, max_retries=0)
    store = _build_store()
    try:
        with store.open_ledger(SYNTHETIC_PLAYER_ID) as ledger:
            session = run_player_session(
                model,
                ledger=ledger,
                store=store,
                clock=clock,
                max_seconds=max_seconds,
                max_turn_attempts=LIVE_TURN_ATTEMPTS,
                retry_backoff_seconds=LIVE_RETRY_BACKOFF_SECONDS,
            )
    finally:
        store.catalog_conn.close()
    return build_report(
        session,
        provider=_provider_name(api_base),
        model=str(getattr(model, "model_name", "") or ""),
        api_base=api_base,
        timeout_seconds=timeout,
        max_seconds=max_seconds,
    )


def _report_paths(output_dir: Path) -> tuple[Path, Path]:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = output_dir / f"player_chat_measurement_{timestamp}"
    return basename.with_suffix(".json"), basename.with_suffix(".md")


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure the live player chat streaming path.")
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="Per-request timeout in seconds."
    )
    parser.add_argument(
        "--max-seconds", type=float, default=DEFAULT_MAX_SECONDS, help="Wall-clock budget for the whole session."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BASE_DIR / "reports" / "player-chat-measurement",
        help="Directory for the paired JSON and Markdown report.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    if args.timeout <= 0 or args.max_seconds <= 0:
        print("--timeout and --max-seconds must be positive.", file=sys.stderr)
        return 2
    if not os.getenv("LLM_API_KEY", "").strip():
        print("LLM_API_KEY not set; live player chat cannot be measured.", file=sys.stderr)
        return 2
    report = run_live_measurement(timeout=args.timeout, max_seconds=args.max_seconds)
    json_path, markdown_path = _report_paths(args.output_dir)
    json_path.write_text(render_json(report), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report))
    print(f"Reports: {json_path} and {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
