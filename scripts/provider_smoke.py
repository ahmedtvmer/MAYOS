"""Smoke-check the hosted player model and measure its prompt streaming.

Run the general provider check with ``python scripts/provider_smoke.py``.
Use ``--baseline`` for synthetic player-chat TTFT measurements, ``--tool-calls``
for streamed single/parallel tool calls, or both together. Measurement modes
write paired, run-versioned Markdown and JSON reports with ``--report`` as an
optional filename prefix. ``--timeout`` applies to every live request.

Exit codes: ``0`` on a live pass, ``1`` on a failed live check, and ``2`` when
the check could not run because ``LLM_API_KEY`` is not configured. A ``not run`` status is deliberately nonzero so
it can never be mistaken for a passed release gate; the orchestrator runs the
live gate once the user supplies the key. The API key is never printed, logged,
or written to the report; both the text and JSON renderings are redacted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any, Callable
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from dotenv import load_dotenv  # noqa: E402
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from agent.player_prompt import build_player_chat_prompt  # noqa: E402
from utils.model_metering import UsageContext, set_recorder, usage_context  # noqa: E402

load_dotenv()  # read the untracked .env (key is never printed)

from utils.model_downloader import (  # noqa: E402
    CLOUD_MODEL_REGISTRY,
    DEFAULT_CLOUD_API_BASE,
)

PRODUCTION = CLOUD_MODEL_REGISTRY["production"]
TOOL_PROMPT = "What is the weather in Berlin? Use the get_weather tool to find out."
STREAM_PROMPT = "Reply with the single word: ready"
DEEPSEEK_PLAYER = PRODUCTION["default_model"]
DEFAULT_BASELINE_REPEATS = 5
MAX_BASELINE_REPEATS = 5
DEFAULT_MEASUREMENT_TIMEOUT = 60.0
BASELINE_RETRY_LIMIT = 1
BASELINE_REPORT_HEADER = [
    "## TTFT baseline", "",
    "TTFT uses messages built with `agent.player_prompt.build_player_chat_prompt` and synthetic player context. "
    "P90 uses nearest-rank percentile; timed-out and retried samples are excluded and reported separately.", "",
    "| Path category | Language | n | Median TTFT | P90 TTFT | Timeouts | Retries | Status |",
    "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
]


@dataclass(frozen=True)
class BaselinePrompt:
    category: str
    language: str
    text: str


BASELINE_PROMPTS = (
    BaselinePrompt("profile", "en", "What details do you have about my training profile?"),
    BaselinePrompt("profile", "ar", "إيه المعلومات الموجودة عندك عن ملفي التدريبي؟"),
    BaselinePrompt("history", "en", "What have I logged for my Bench Press recently?"),
    BaselinePrompt("history", "ar", "إيه اللي سجلته في تمرين Bench Press مؤخرًا؟"),
    BaselinePrompt("last_session", "en", "How did my latest workout compare with the one before it?"),
    BaselinePrompt("last_session", "ar", "حصتي التدريبية الأخيرة كانت أحسن من اللي قبلها إزاي؟"),
    BaselinePrompt("free_form_coaching", "en", "How should I adjust my training if I feel tired this week?"),
    BaselinePrompt("free_form_coaching", "ar", "أعدّل تدريبي إزاي لو حاسس بإرهاق الأسبوع ده؟"),
)


SYNTHETIC_PLAYER = {
    "profile": "Training age: 3 years; goal: build strength; equipment: full gym.",
    "recent_history": "Bench Press: 75 kg x 5 on 2026-10-07; 77.5 kg x 5 on 2026-10-09.",
    "last_session": "Latest Bench Press: 77.5 kg x 5; previous: 75 kg x 5; improved by 2.5 kg.",
}


class StructuredSmokeResult(BaseModel):
    result: str = Field(description="The requested short result.")


class WeatherInput(BaseModel):
    city: str = Field(description="City to look up.")


class ProfileInput(BaseModel):
    field: str = Field(description="The profile field to read.")


class LastSessionInput(BaseModel):
    exercise: str = Field(description="An exercise name.")


@tool(args_schema=WeatherInput)
def get_weather(city: str) -> str:
    """Returns the current weather for a city."""
    return f"Sunny in {city}."


@tool(args_schema=ProfileInput)
def get_profile(field: str) -> str:
    """Reads a fixed, synthetic training profile field for this smoke check."""
    return f"{field}: build strength."


@tool(args_schema=LastSessionInput)
def get_last_session(exercise: str) -> str:
    """Reads a fixed, synthetic last-session result for this smoke check."""
    return f"{exercise}: 80 kg for 5 reps."


READ_ONLY_TOOLS = {"get_profile": get_profile, "get_last_session": get_last_session}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class BaselineCategory:
    category: str
    language: str
    sample_count: int
    median_seconds: float | None
    p90_seconds: float | None
    timeout_count: int = 0
    retry_count: int = 0


@dataclass
class BaselineAttempt:
    attempt: int
    duration_seconds: float
    ttft_seconds: float | None
    timed_out: bool
    error: str = ""


@dataclass
class BaselineSample:
    category: str
    language: str
    repeat: int
    ttft_seconds: float | None
    timed_out: bool
    retried: bool
    status: str
    attempts: list[BaselineAttempt] = field(default_factory=list)
    error: str = ""


@dataclass
class BaselineMeasurements:
    categories: list[BaselineCategory] = field(default_factory=list)
    samples: list[BaselineSample] = field(default_factory=list)


@dataclass
class ToolCallCheck:
    name: str
    passed: bool
    tool_names: list[str]
    tool_deltas: int
    final_text_chunks: int
    final_chars: int
    summary: str


@dataclass(frozen=True)
class ToolCallCase:
    name: str
    prompt: str
    expected_names: list[str]


TOOL_CALL_CASES = (
    ToolCallCase(
        "single",
        "Use get_profile once to answer. Call it with field='goal', then summarize the result in one sentence.",
        ["get_profile"],
    ),
    ToolCallCase(
        "parallel",
        "Call get_profile(field='goal') and get_last_session(exercise='Bench Press') in parallel in one round. "
        "After both results arrive, answer in one short sentence.",
        ["get_profile", "get_last_session"],
    ),
)

@dataclass
class StreamedToolRound:
    chunks: list[Any] = field(default_factory=list)
    assistant_chunk: AIMessageChunk | None = None
    error: str = ""


@dataclass
class ToolRoundSummary:
    chunk_count: int
    tool_deltas: int
    tool_names: list[str]
    malformed: int
    finish_reason: str
    content_chars: int
    error: str
    calls: list[dict[str, Any]] = field(default_factory=list)
    non_chunk_tool_response: bool = False


@dataclass
class FinalAnswerSummary:
    text_chunks: int = 0
    chars: int = 0
    tool_deltas: int = 0
    error: str = ""


@dataclass
class SmokeReport:
    status: str  # "pass" | "fail" | "not_run"
    reason: str = ""
    checks: list[Check] = field(default_factory=list)
    model: str = ""
    base_url: str = ""
    measured_at: str = ""
    baseline: list[BaselineCategory] = field(default_factory=list)
    baseline_samples: list[BaselineSample] = field(default_factory=list)
    tool_calls: list[ToolCallCheck] = field(default_factory=list)
    timeout_seconds: float = DEFAULT_MEASUREMENT_TIMEOUT
    baseline_repeats: int = DEFAULT_BASELINE_REPEATS
    git_commit_sha: str = ""
    measured_code_sha256: str = ""
    run_id: str = ""
    report_markdown_path: str = ""
    report_json_path: str = ""
    metering_rows: int = 0


@dataclass(frozen=True)
class SmokeConfiguration:
    api_key: str
    model: str
    api_base: str


# ---------------------------------------------------------------------------
# Configuration (read-only; the key is only ever used as a header value)
# ---------------------------------------------------------------------------


def configured_model() -> str:
    return os.getenv("LLM_MODEL", "").strip() or PRODUCTION["default_model"]


def configured_api_base() -> str:
    return os.getenv("LLM_API_BASE", "").strip() or DEFAULT_CLOUD_API_BASE


def configured_api_key() -> str:
    return os.getenv("LLM_API_KEY", "").strip()


def _redact(text: Any, secret: str) -> str:
    rendered = str(text)
    return rendered.replace(secret, "***REDACTED***") if secret else rendered


def _thinking_disabled(extra_body: Any) -> bool:
    """True when the effective body disables thinking at either documented shape."""
    if not isinstance(extra_body, dict):
        return False
    if extra_body.get("enable_thinking") is False:
        return True
    nested = extra_body.get("chat_template_kwargs")
    return isinstance(nested, dict) and nested.get("enable_thinking") is False


def _request_body_configured(model: str, extra_body: Any) -> bool:
    """The hosted player has no default body; legacy Qwen defaults to thinking off."""
    if os.getenv("LLM_EXTRA_BODY", "").strip():
        return isinstance(extra_body, dict)
    if model == DEEPSEEK_PLAYER:
        return extra_body is None
    if os.getenv("LLM_ENABLE_THINKING", "").strip().lower() in {"1", "true", "yes", "on"}:
        return extra_body is None
    return _thinking_disabled(extra_body)


def _reasoning_content(payload: dict[str, Any]) -> str:
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    return str(message.get("reasoning_content") or "")


def _tool_names(calls: Any) -> list[str]:
    names = []
    for call in calls or []:
        name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
        if name:
            names.append(str(name))
    return names


def _default_requester(api_base: str, api_key: str) -> Callable[[dict[str, Any], float], dict[str, Any]]:
    """Raw chat-completions probe so the exact request body and reasoning fields are visible."""

    import httpx

    def request(payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        response = httpx.post(
            f"{api_base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    return request


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _operator_usage_context(purpose: str, store: Any = None):
    """Keeps smoke calls outside player allowance and labels them as operator usage."""
    return usage_context(UsageContext(account_id=None, role="operator", purpose=purpose, store=store))


class SmokeUsageStore:
    """Temporary SQLite model_usage sink for operator smoke calls."""

    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute(
            "CREATE TABLE model_usage (id TEXT PRIMARY KEY, account_id TEXT, turn_id TEXT, role TEXT NOT NULL, "
            "model TEXT NOT NULL, purpose TEXT, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, "
            "estimated INTEGER NOT NULL, cost_usd REAL NOT NULL, created_at TEXT NOT NULL)"
        )

    def record_model_usage(self, **row: Any) -> None:
        self.connection.execute(
            "INSERT INTO model_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex, row.get("account_id"), row.get("turn_id"), row.get("role"),
                row.get("model"), row.get("purpose"), row.get("input_tokens", 0),
                row.get("output_tokens", 0), int(bool(row.get("estimated"))), row.get("cost_usd", 0.0),
                datetime.now(UTC).isoformat(),
            ),
        )
        self.connection.commit()

    def count_operator_rows(self) -> int:
        return int(self.connection.execute(
            "SELECT COUNT(*) FROM model_usage WHERE account_id IS NULL AND role = 'operator'"
        ).fetchone()[0])

    def close(self) -> None:
        self.connection.close()


def _register_operator_metering(store: SmokeUsageStore) -> None:
    from utils.logger import MyosLogger

    # Service imports initialize the app logger, whose default path is outside the worktree.
    MyosLogger(log_file=str(Path(tempfile.gettempdir()) / f"provider-smoke-{uuid.uuid4().hex}.log"))
    from service.model_metering import record_model_usage

    set_recorder(record_model_usage)


def _chunk_text(chunk: Any) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in {None, "text"}
        )
    return ""


def _nearest_rank_p90(samples: list[float]) -> float | None:
    if not samples:
        return None
    return sorted(samples)[max(0, math.ceil(0.9 * len(samples)) - 1)]


def _synthetic_prompt_state(prompt: BaselinePrompt) -> dict[str, Any]:
    context = SYNTHETIC_PLAYER["profile"]
    if prompt.category in {"history", "free_form_coaching"}:
        context += "\nRecent history: " + SYNTHETIC_PLAYER["recent_history"]
    if prompt.category == "last_session":
        context += "\nSession comparison: " + SYNTHETIC_PLAYER["last_session"]
    return {
        "messages": [
            HumanMessage(content="I train at a full gym."),
            AIMessage(content="I can use your supplied training context."),
            HumanMessage(content=prompt.text),
        ],
        "preferred_name": "Alex",
        "coach_tone": None,
        "custom_instructions": "",
        "telemetry_context": context,
        "synthetic_profile": SYNTHETIC_PLAYER["profile"],
        "synthetic_recent_history": SYNTHETIC_PLAYER["recent_history"],
        "synthetic_last_session": SYNTHETIC_PLAYER["last_session"],
    }


def _is_timeout_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    return "timeout" in name or "timed out" in str(exc).lower()


def _measure_prompt_attempt(
    chat_model: Any,
    messages: list[Any],
    clock: Callable[[], float],
    api_key: str,
) -> BaselineAttempt:
    started = clock()
    first_text_at: float | None = None
    try:
        for chunk in chat_model.stream(messages):
            if _chunk_text(chunk) and first_text_at is None:
                first_text_at = clock()
    except Exception as exc:  # noqa: BLE001 - provider failures become explicit failed samples
        elapsed = max(0.0, clock() - started)
        return BaselineAttempt(0, elapsed, None, _is_timeout_error(exc), f"{type(exc).__name__}: {_redact(exc, api_key)}")
    elapsed = max(0.0, clock() - started)
    if first_text_at is None:
        return BaselineAttempt(0, elapsed, None, False, "stream ended without text")
    return BaselineAttempt(0, elapsed, max(0.0, first_text_at - started), False)


def _prompt_attempts(
    chat_model: Any,
    messages: list[Any],
    clock: Callable[[], float],
    api_key: str,
) -> list[BaselineAttempt]:
    attempts = []
    for attempt_number in range(1, BASELINE_RETRY_LIMIT + 2):
        attempt = _measure_prompt_attempt(chat_model, messages, clock, api_key)
        attempt.attempt = attempt_number
        attempts.append(attempt)
        if attempt.ttft_seconds is not None or attempt_number > BASELINE_RETRY_LIMIT:
            break
    return attempts


def _measure_baseline_sample(
    chat_model: Any,
    prompt: BaselinePrompt,
    repeat: int,
    clock: Callable[[], float],
    api_key: str,
) -> BaselineSample:
    messages = build_player_chat_prompt(_synthetic_prompt_state(prompt))
    attempts = _prompt_attempts(chat_model, messages, clock, api_key)
    timed_out = any(attempt.timed_out for attempt in attempts)
    retried = len(attempts) > 1
    final = attempts[-1]
    status = (
        "timeout_retried" if timed_out and retried else "timeout" if timed_out
        else "retried" if retried else "ok" if final.ttft_seconds is not None else "error"
    )
    error = "; ".join(attempt.error for attempt in attempts if attempt.error)
    ttft = final.ttft_seconds if not retried and not timed_out else None
    return BaselineSample(prompt.category, prompt.language, repeat, ttft, timed_out, retried, status, attempts, error)


def _baseline_category_stats(samples: list[BaselineSample]) -> list[BaselineCategory]:
    grouped: dict[tuple[str, str], list[BaselineSample]] = {}
    for sample in samples:
        grouped.setdefault((sample.category, sample.language), []).append(sample)
    results = []
    for (category, language), group in grouped.items():
        values = [
            s.ttft_seconds for s in group
            if s.ttft_seconds is not None and not s.retried and not s.timed_out
        ]
        results.append(BaselineCategory(
            category, language, len(values), median(values) if values else None,
            _nearest_rank_p90(values), sum(s.timed_out for s in group), sum(s.retried for s in group),
        ))
    return results


def run_ttft_baseline(
    chat_model: Any,
    *,
    repeats: int = DEFAULT_BASELINE_REPEATS,
    api_key: str = "",
    store: Any = None,
    clock: Callable[[], float] = time.perf_counter,
) -> BaselineMeasurements:
    """Streams built player-chat prompts with synthetic ledger context and records each attempt."""
    if repeats < 1 or repeats > MAX_BASELINE_REPEATS:
        raise ValueError(f"repeats must be between 1 and {MAX_BASELINE_REPEATS}.")
    samples: list[BaselineSample] = []
    with _operator_usage_context("provider_smoke_ttft", store):
        for repeat in range(1, repeats + 1):
            for prompt in BASELINE_PROMPTS:
                samples.append(_measure_baseline_sample(chat_model, prompt, repeat, clock, api_key))
    return BaselineMeasurements(_baseline_category_stats(samples), samples)


def _tool_result(call: dict[str, Any]) -> str:
    name = str(call.get("name") or "")
    args = call.get("args")
    if not isinstance(args, dict):
        raise ValueError(f"{name or 'unnamed tool'} arguments were not an object")
    tool = READ_ONLY_TOOLS.get(name)
    if tool is None:
        raise ValueError(f"unexpected tool name {name!r}")
    return str(tool.invoke(args))


def _stream_tool_round(bound_model: Any, messages: list[Any], api_key: str) -> StreamedToolRound:
    streamed = StreamedToolRound()
    try:
        for chunk in bound_model.stream(messages):
            streamed.chunks.append(chunk)
            if isinstance(chunk, AIMessageChunk):
                previous = streamed.assistant_chunk
                streamed.assistant_chunk = chunk if previous is None else previous + chunk
    except Exception as exc:  # noqa: BLE001 - report provider failure with the partial response summary
        streamed.error = f"{type(exc).__name__}: {_redact(exc, api_key)}"
    return streamed


def _tool_delta_count(streamed: StreamedToolRound) -> int:
    return sum(len(getattr(chunk, "tool_call_chunks", None) or []) for chunk in streamed.chunks)


def _parsed_tool_calls(streamed: StreamedToolRound) -> list[dict[str, Any]]:
    chunk_calls = getattr(streamed.assistant_chunk, "tool_calls", None) or []
    if chunk_calls:
        return list(chunk_calls)
    for chunk in streamed.chunks:
        if getattr(chunk, "tool_calls", None):
            return list(chunk.tool_calls)
    return []


def _malformed_tool_count(streamed: StreamedToolRound, calls: list[dict[str, Any]]) -> int:
    invalid_calls = list(getattr(streamed.assistant_chunk, "invalid_tool_calls", None) or [])
    invalid_indexes = sum(
        not isinstance(delta.get("index"), int)
        for chunk in streamed.chunks
        for delta in (getattr(chunk, "tool_call_chunks", None) or [])
        if isinstance(delta, dict)
    )
    invalid_fields = sum(
        not call.get("name") or not call.get("id") or not isinstance(call.get("args"), dict) for call in calls
    )
    return len(invalid_calls) + invalid_indexes + invalid_fields


def _summarize_tool_round(streamed: StreamedToolRound) -> ToolRoundSummary:
    calls = _parsed_tool_calls(streamed)
    finish_reason = ""
    for chunk in streamed.chunks:
        metadata = getattr(chunk, "response_metadata", None) or {}
        finish_reason = str(metadata.get("finish_reason") or finish_reason)
    return ToolRoundSummary(
        chunk_count=len(streamed.chunks),
        tool_deltas=_tool_delta_count(streamed),
        tool_names=[str(call.get("name") or "") for call in calls],
        malformed=_malformed_tool_count(streamed, calls),
        finish_reason=finish_reason or "unknown",
        content_chars=sum(len(_chunk_text(chunk)) for chunk in streamed.chunks),
        error=streamed.error,
        calls=calls,
        non_chunk_tool_response=any(
            not isinstance(chunk, AIMessageChunk) and getattr(chunk, "tool_calls", None)
            for chunk in streamed.chunks
        ),
    )


def _render_tool_round_summary(summary: ToolRoundSummary) -> str:
    rendered = (
        f"raw response summary: chunks={summary.chunk_count}, tool_deltas={summary.tool_deltas}, "
        f"tool_names={summary.tool_names}, malformed={summary.malformed}, "
        f"finish_reason={summary.finish_reason}, content_chars={summary.content_chars}"
    )
    return f"{rendered}, error={summary.error}" if summary.error else rendered


def _tool_round_failure(case: ToolCallCase, summary: ToolRoundSummary) -> ToolCallCheck | None:
    failure = _tool_round_failure_reason(case, summary)
    if not failure:
        return None
    return ToolCallCheck(
        case.name,
        False,
        summary.tool_names,
        summary.tool_deltas,
        0,
        0,
        f"{_render_tool_round_summary(summary)}; {failure}.",
    )


def _tool_round_failure_reason(case: ToolCallCase, summary: ToolRoundSummary) -> str:
    if summary.non_chunk_tool_response or (summary.calls and not summary.tool_deltas):
        return "tool calls were not streamed"
    elif summary.malformed:
        return "malformed tool-call deltas"
    elif summary.error or not summary.tool_deltas or not summary.calls:
        return "tool calls were missing from the stream"
    elif sorted(summary.tool_names) != sorted(case.expected_names) or len(summary.calls) != len(case.expected_names):
        return f"expected tool calls {case.expected_names}"
    elif summary.tool_deltas < len(summary.calls):
        return "not every tool call had a streamed delta"
    return ""


def _tool_messages(streamed: StreamedToolRound, summary: ToolRoundSummary) -> list[ToolMessage]:
    if streamed.assistant_chunk is None:
        raise ValueError("streamed assistant tool-call message was missing")
    return [ToolMessage(content=_tool_result(call), tool_call_id=str(call["id"])) for call in summary.calls]


def _collect_final_answer(bound_model: Any, messages: list[Any], api_key: str) -> FinalAnswerSummary:
    collected = FinalAnswerSummary()
    try:
        for chunk in bound_model.stream(messages):
            if isinstance(chunk, AIMessageChunk):
                text = _chunk_text(chunk)
                collected.text_chunks += 1 if text else 0
                collected.chars += len(text)
                collected.tool_deltas += len(chunk.tool_call_chunks or [])
            else:
                collected.chars += len(_chunk_text(chunk))
    except Exception as exc:  # noqa: BLE001 - preserve partial stream details in the failed check
        collected.error = f"{type(exc).__name__}: {_redact(exc, api_key)}"
    return collected


def _final_answer_check(case: ToolCallCase, summary: ToolRoundSummary, final: FinalAnswerSummary) -> ToolCallCheck:
    passed = not final.error and final.text_chunks >= 2 and final.chars > 0 and not final.tool_deltas
    detail = f"{_render_tool_round_summary(summary)}; final answer chunks={final.text_chunks}, chars={final.chars}"
    if final.error:
        detail += f", error={final.error}"
    if final.tool_deltas:
        detail += f"; final stream requested more tools (deltas={final.tool_deltas})"
    if final.text_chunks < 2:
        detail += "; final answer did not stream in multiple text chunks"
    return ToolCallCheck(case.name, passed, summary.tool_names, summary.tool_deltas, final.text_chunks, final.chars, detail)


def _run_tool_case(bound_model: Any, case: ToolCallCase, api_key: str) -> ToolCallCheck:
    messages = [HumanMessage(content=case.prompt)]
    streamed = _stream_tool_round(bound_model, messages, api_key)
    summary = _summarize_tool_round(streamed)
    failure = _tool_round_failure(case, summary)
    if failure:
        return failure
    tool_messages = _tool_messages(streamed, summary)
    assistant_message = AIMessage(
        content=streamed.assistant_chunk.content,
        tool_calls=summary.calls,
        additional_kwargs=streamed.assistant_chunk.additional_kwargs,
        response_metadata=streamed.assistant_chunk.response_metadata,
    )
    final = _collect_final_answer(bound_model, [*messages, assistant_message, *tool_messages], api_key)
    return _final_answer_check(case, summary, final)


def run_tool_call_check(chat_model: Any, *, api_key: str = "", store: Any = None) -> list[ToolCallCheck]:
    """Checks one streamed tool call and a parallel two-tool round, then streamed answers."""
    with _operator_usage_context("provider_smoke_tool_calls", store):
        try:
            bound = chat_model.bind_tools([get_profile, get_last_session])
        except Exception as exc:  # noqa: BLE001 - unsupported provider binding is a reportable failure
            summary = f"raw response summary: bind_tools failed: {type(exc).__name__}: {_redact(exc, api_key)}"
            return [ToolCallCheck(case.name, False, [], 0, 0, 0, summary) for case in TOOL_CALL_CASES]
        return [_run_tool_case(bound, case, api_key) for case in TOOL_CALL_CASES]


def run_smoke(
    chat_model: Any,
    *,
    expected_model: str,
    api_base: str,
    api_key: str = "",
    requester: Callable[[dict[str, Any], float], dict[str, Any]] | None = None,
    timeout: float = 30.0,
) -> SmokeReport:
    """Runs the four checks against ``chat_model`` (and an optional raw probe)."""
    checks: list[Check] = []
    actual_model = str(getattr(chat_model, "model_name", "") or "")
    checks.append(
        Check("model_id", actual_model == expected_model, f"configured={expected_model!r} built={actual_model!r}")
    )

    extra_body = getattr(chat_model, "extra_body", None)
    checks.append(
        Check(
            "request_body_config",
            _request_body_configured(expected_model, extra_body),
            f"extra_body={extra_body!r}",
        )
    )

    try:
        chunk_count = 0
        streamed = []
        for chunk in chat_model.stream(STREAM_PROMPT):
            chunk_count += 1
            streamed.append(str(getattr(chunk, "content", "")))
        text = "".join(streamed).strip()
        checks.append(
            Check("streaming", chunk_count > 0 and bool(text), f"chunks={chunk_count} chars={len(text)}")
        )
    except Exception as exc:  # noqa: BLE001 - reported, never re-raised with a key
        checks.append(Check("streaming", False, f"stream raised {type(exc).__name__}: {_redact(exc, api_key)}"))

    try:
        structured = chat_model.with_structured_output(StructuredSmokeResult).invoke(
            "Return the word ready in the result field."
        )
        valid = isinstance(structured, StructuredSmokeResult) and bool(structured.result.strip())
        checks.append(Check("structured_output", valid, f"parsed={type(structured).__name__}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(
            Check("structured_output", False, f"invoke raised {type(exc).__name__}: {_redact(exc, api_key)}")
        )

    try:
        bound = chat_model.bind_tools([get_weather])
        response = bound.invoke(TOOL_PROMPT)
        names = _tool_names(getattr(response, "tool_calls", None))
        checks.append(Check("tool_calls", "get_weather" in names, f"tool_calls={names}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("tool_calls", False, f"invoke raised {type(exc).__name__}: {_redact(exc, api_key)}"))

    if requester is not None:
        probe_payload: dict[str, Any] = {
            "model": expected_model,
            "messages": [{"role": "user", "content": STREAM_PROMPT}],
            "max_tokens": PRODUCTION["default_max_tokens"],
            "temperature": 0.0,
        }
        if isinstance(extra_body, dict):
            probe_payload.update(extra_body)
        try:
            payload = requester(probe_payload, timeout)
            echoed = str(payload.get("model", "") or "")
            checks.append(
                Check(
                    "provider_model_echo",
                    echoed == expected_model or echoed.startswith(expected_model),
                    f"provider echoed {echoed!r}",
                )
            )
            reasoning = _reasoning_content(payload)
            checks.append(
                Check(
                    "non_reasoning_response",
                    reasoning == "",
                    "no reasoning_content" if reasoning == "" else f"reasoning_content={len(reasoning)} chars",
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                Check("provider_probe", False, f"raw request failed {type(exc).__name__}: {_redact(exc, api_key)}")
            )

    status = "pass" if all(check.passed for check in checks) else "fail"
    return SmokeReport(status=status, checks=checks, model=actual_model, base_url=api_base)


def _format_measurement(value_seconds: float | None = None, *, passed: bool | None = None) -> str:
    if passed is not None:
        return "PASS" if passed else "FAIL"
    return "n/a" if value_seconds is None else f"{value_seconds * 1000:.1f} ms"


def _render_text_baseline(report: SmokeReport, api_key: str) -> list[str]:
    lines = []
    for row in report.baseline:
        lines.append(
            f"  [{_format_measurement(passed=row.sample_count > 0)}] ttft {row.category}/{row.language}: "
            f"n={row.sample_count}, median={_format_measurement(row.median_seconds)}, "
            f"p90={_format_measurement(row.p90_seconds)}, timeouts={row.timeout_count}, retries={row.retry_count}"
        )
    for sample in report.baseline_samples:
        if sample.status != "ok":
            lines.append(
                f"    sample {sample.category}/{sample.language} repeat={sample.repeat}: {sample.status}, "
                f"timed_out={sample.timed_out}, retried={sample.retried}, error={_redact(sample.error, api_key)}"
            )
    return lines


def _render_text_tool_calls(report: SmokeReport, api_key: str) -> list[str]:
    return [
        f"  [{_format_measurement(passed=check.passed)}] tool_calls_{check.name}: {_redact(check.summary, api_key)}"
        for check in report.tool_calls
    ]


def render_report(report: SmokeReport, api_key: str = "") -> str:
    lines = [f"provider smoke: {report.status}"]
    if report.model:
        lines.append(f"  model: {report.model}")
    if report.base_url:
        lines.append(f"  base_url: {report.base_url}")
    if report.measured_at:
        lines.append(f"  measured_at: {report.measured_at}")
    if report.reason:
        lines.append(f"  reason: {_redact(report.reason, api_key)}")
    for check in report.checks:
        lines.append(f"  [{_format_measurement(passed=check.passed)}] {check.name}: {_redact(check.detail, api_key)}")
    lines.extend(_render_text_baseline(report, api_key))
    lines.extend(_render_text_tool_calls(report, api_key))
    return _redact("\n".join(lines), api_key)


def _baseline_json(report: SmokeReport) -> list[dict[str, Any]]:
    return [
        {
            "category": row.category,
            "language": row.language,
            "n": row.sample_count,
            "median_seconds": row.median_seconds,
            "p90_seconds": row.p90_seconds,
            "timeout_count": row.timeout_count,
            "retry_count": row.retry_count,
        }
        for row in report.baseline
    ]


def _attempt_json(attempt: BaselineAttempt, api_key: str) -> dict[str, Any]:
    return {
        "attempt": attempt.attempt,
        "duration_seconds": attempt.duration_seconds,
        "ttft_seconds": attempt.ttft_seconds,
        "timed_out": attempt.timed_out,
        "error": _redact(attempt.error, api_key),
    }


def _sample_json(sample: BaselineSample, api_key: str) -> dict[str, Any]:
    return {
        "category": sample.category,
        "language": sample.language,
        "repeat": sample.repeat,
        "ttft_seconds": sample.ttft_seconds,
        "timed_out": sample.timed_out,
        "retried": sample.retried,
        "status": sample.status,
        "error": _redact(sample.error, api_key),
        "attempts": [_attempt_json(attempt, api_key) for attempt in sample.attempts],
    }


def _samples_json(report: SmokeReport, api_key: str) -> list[dict[str, Any]]:
    return [_sample_json(sample, api_key) for sample in report.baseline_samples]


def _check_json(check: Check, api_key: str) -> dict[str, Any]:
    return {"name": check.name, "passed": check.passed, "detail": _redact(check.detail, api_key)}


def _tool_call_json(check: ToolCallCheck, api_key: str) -> dict[str, Any]:
    return {
        "name": check.name,
        "passed": check.passed,
        "tool_names": check.tool_names,
        "tool_deltas": check.tool_deltas,
        "final_text_chunks": check.final_text_chunks,
        "final_chars": check.final_chars,
        "summary": _redact(check.summary, api_key),
    }


def _report_metadata_json(report: SmokeReport, api_key: str) -> dict[str, Any]:
    return {
        "status": report.status,
        "reason": _redact(report.reason, api_key),
        "model": report.model,
        "base_url": report.base_url,
        "measured_at": report.measured_at,
        "timeout_seconds": report.timeout_seconds,
        "baseline_repeats": report.baseline_repeats,
        "git_commit_sha": report.git_commit_sha,
        "measured_code_sha256": report.measured_code_sha256,
        "run_id": report.run_id,
        "report_paths": {"markdown": report.report_markdown_path, "json": report.report_json_path},
        "metering": {"rows": report.metering_rows, "account_id": None, "role": "operator"},
    }


def render_json(report: SmokeReport, api_key: str = "") -> str:
    """JSON rendering with the same redaction as the text report."""
    payload = {
        **_report_metadata_json(report, api_key),
        "checks": [_check_json(check, api_key) for check in report.checks],
        "baseline": _baseline_json(report),
        "baseline_samples": _samples_json(report, api_key),
        "tool_calls": [_tool_call_json(check, api_key) for check in report.tool_calls],
    }
    return _redact(json.dumps(payload), api_key)


def _provider_name(api_base: str) -> str:
    host = urlparse(api_base).hostname or api_base
    return "DeepInfra" if host.lower().endswith("deepinfra.com") else host


def _baseline_row_markdown(row: BaselineCategory) -> str:
    return (
        f"| {row.category} | {row.language} | {row.sample_count} | "
        f"{_format_measurement(row.median_seconds)} | {_format_measurement(row.p90_seconds)} | "
        f"{row.timeout_count} | {row.retry_count} | {_format_measurement(passed=row.sample_count > 0)} |"
    )


def _exceptional_sample_lines(report: SmokeReport) -> list[str]:
    exceptional = [sample for sample in report.baseline_samples if sample.status != "ok"]
    if not exceptional:
        return []
    return ["", "Timed out or failed samples (excluded from TTFT):"] + [
        f"- {sample.category}/{sample.language} repeat {sample.repeat}: status={sample.status}, "
        f"timed_out={str(sample.timed_out).lower()}, retried={str(sample.retried).lower()}, "
        f"attempts={len(sample.attempts)}, error=`{sample.error}`"
        for sample in exceptional
    ]


def _baseline_report_section(report: SmokeReport) -> list[str]:
    lines = BASELINE_REPORT_HEADER.copy()
    lines.extend(_baseline_row_markdown(row) for row in report.baseline)
    lines.extend(_exceptional_sample_lines(report))
    if not report.baseline:
        lines.append("| Not run | — | 0 | n/a | n/a | 0 | 0 | NOT RUN |")
    return lines


def _tool_call_report_section(report: SmokeReport) -> list[str]:
    lines = ["## Streaming tool-call check", ""]
    if any(not check.passed for check in report.tool_calls):
        lines.extend(["**STOP: the hosted tool-call check failed. Later tool-calling tickets must stop.**", ""])
    lines.extend([
        "| Case | Status | Tool names | Streamed tool deltas | Final text chunks | Summary |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ])
    for check in report.tool_calls:
        summary = check.summary.replace("|", "\\|")
        lines.append(
            f"| {check.name} | {_format_measurement(passed=check.passed)} | "
            f"{', '.join(check.tool_names) or 'none'} | {check.tool_deltas} | {check.final_text_chunks} | {summary} |"
        )
    if not report.tool_calls:
        lines.append("| Not run | NOT RUN | — | 0 | 0 | — |")
    return lines


def _baseline_comment_stats(report: SmokeReport) -> str:
    return "; ".join(
        f"{row.category}/{row.language}: median {_format_measurement(row.median_seconds)}, "
        f"p90 {_format_measurement(row.p90_seconds)}, n={row.sample_count}"
        for row in report.baseline
    ) or "TTFT baseline not run"


def _tool_comment_stats(report: SmokeReport) -> str:
    return "; ".join(
        f"{check.name} {_format_measurement(passed=check.passed)} "
        f"(tool deltas={check.tool_deltas}, final chunks={check.final_text_chunks})"
        for check in report.tool_calls
    ) or "tool-call check not run"


def _issue_264_comment(report: SmokeReport, provider: str) -> str:
    if any(not check.passed for check in report.tool_calls):
        return (
            f"STOP for follow-on tool work: #265 found that {report.model} on {provider} ({report.base_url}) "
            f"did not pass streamed tool calls. Raw summaries are in {report.report_markdown_path}; "
            "later tool-calling tickets should stop pending investigation."
        )
    stats = _baseline_comment_stats(report)
    timeouts = sum(sample.timed_out for sample in report.baseline_samples)
    retries = sum(sample.retried for sample in report.baseline_samples)
    return (
        f"#265 measurement {report.status.upper()} ({report.measured_at} UTC): {report.model} on {provider} "
        f"({report.base_url}). TTFT: {stats}. Timeouts={timeouts}; retried samples={retries} (excluded from TTFT). "
        f"Tool calls: {_tool_comment_stats(report)}. Reports: {report.report_markdown_path} and "
        f"{report.report_json_path}. "
        f"Metering rows={report.metering_rows}, account_id=NULL, role=operator."
    )


def render_versioned_report(report: SmokeReport) -> str:
    """Renders the measurement report and ready-to-post #264 comment."""
    provider = _provider_name(report.base_url)
    day = report.measured_at[:10] if report.measured_at else "not measured"
    metadata = [
        f"# Provider smoke report — {day}", "", f"- Result: **{report.status.upper()}**",
        f"- Model: `{report.model or 'unknown'}`", f"- Provider: {provider}",
        f"- Endpoint: `{report.base_url or 'unknown'}`", f"- Measured at: `{report.measured_at or 'not measured'}` (UTC)",
        f"- Timeout: `{report.timeout_seconds:.1f}s`; repeats per language/category: `{report.baseline_repeats}`",
        f"- Measured code: git HEAD `{report.git_commit_sha or 'unknown'}`, source SHA-256 `{report.measured_code_sha256 or 'unknown'}`",
        f"- Run ID: `{report.run_id or 'unknown'}`",
        f"- Metering: `{report.metering_rows}` rows via registered service recorder in a temporary store; `account_id=NULL`, `role=operator`.",
        f"- Machine report: `{report.report_json_path or 'not written'}`", "",
    ]
    sections = _baseline_report_section(report) + [""] + _tool_call_report_section(report)
    comment = ["", "## Comment for #264", "", _issue_264_comment(report, provider), ""]
    return "\n".join(metadata + sections + comment)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _add_baseline_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--baseline", action="store_true", help="Measure synthetic player-chat TTFT prompts in English and Arabic.")
    parser.add_argument("--repeats", type=int, default=DEFAULT_BASELINE_REPEATS, help="Repeats per prompt and language (1-5).")
    parser.add_argument("--report", type=Path, help="Filename prefix for the paired versioned Markdown and JSON reports.")


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live hosted player-model smoke check.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_MEASUREMENT_TIMEOUT, help="Per-request timeout in seconds for every mode.")
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    parser.add_argument(
        "--tool-calls",
        action="store_true",
        help="Check single and parallel tool calls while streaming, then check streamed final answers.",
    )
    _add_baseline_arguments(parser)
    return parser


def _measurement_report(args: Any, config: SmokeConfiguration, store: SmokeUsageStore) -> SmokeReport:
    measured_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    report = SmokeReport(
        "not_run", model=config.model, base_url=config.api_base, measured_at=measured_at,
        timeout_seconds=args.timeout, baseline_repeats=args.repeats, run_id=uuid.uuid4().hex[:8],
    )
    try:
        chat_model = _build_smoke_model(args.timeout)
    except Exception as exc:  # noqa: BLE001 - construction failures become an explicit report failure
        report.status = "fail"
        report.reason = f"model build failed: {_redact(exc, config.api_key)}"
        return report
    return _execute_measurements(report, chat_model, args, config.api_key, store)


def _build_smoke_model(timeout: float) -> Any:
    """Builds every live smoke model through one uncached, metered constructor."""
    from utils.model_downloader import build_player_llm

    return build_player_llm(timeout=timeout, max_retries=0)


def _measured_code_metadata() -> tuple[str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=BASE_DIR, check=True, capture_output=True, text=True
    ).stdout.strip()
    digest = hashlib.sha256()
    for path in (BASE_DIR / "scripts/provider_smoke.py", BASE_DIR / "agent/player_prompt.py", BASE_DIR / "utils/model_downloader.py"):
        digest.update(path.relative_to(BASE_DIR).as_posix().encode())
        digest.update(path.read_bytes())
    return commit, digest.hexdigest()


def _execute_measurements(
    report: SmokeReport, chat_model: Any, args: Any, api_key: str, store: SmokeUsageStore
) -> SmokeReport:
    report.model = str(getattr(chat_model, "model_name", "") or report.model)
    report.reason = ""
    report.git_commit_sha, report.measured_code_sha256 = _measured_code_metadata()
    if args.baseline:
        baseline = run_ttft_baseline(chat_model, repeats=args.repeats, api_key=api_key, store=store)
        report.baseline = baseline.categories
        report.baseline_samples = baseline.samples
    if args.tool_calls:
        report.tool_calls = run_tool_call_check(chat_model, api_key=api_key, store=store)
    report.metering_rows = store.count_operator_rows()
    failed = any(not baseline.sample_count for baseline in report.baseline)
    report.status = "fail" if failed or any(not check.passed for check in report.tool_calls) else "pass"
    return report


def _measurement_destinations(args: Any, report: SmokeReport) -> tuple[Path, Path]:
    prefix = args.report or (BASE_DIR / "reports" / "provider-smoke" / "provider-smoke")
    prefix = prefix.with_suffix("") if prefix.suffix.lower() in {".md", ".json"} else prefix
    timestamp = report.measured_at.replace(":", "").replace("-", "")
    stem = f"{prefix.name}-{timestamp}-{report.run_id}"
    return prefix.parent / f"{stem}.md", prefix.parent / f"{stem}.json"


def _display_report_path(path: Path) -> str:
    try:
        return path.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return str(path)


def _write_measurement_reports(args: Any, report: SmokeReport, api_key: str) -> int:
    markdown_path, json_path = _measurement_destinations(args, report)
    report.report_markdown_path = _display_report_path(markdown_path)
    report.report_json_path = _display_report_path(json_path)
    if markdown_path.exists() or json_path.exists():
        raise FileExistsError(f"Refusing to overwrite an existing provider-smoke report: {markdown_path.stem}")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_versioned_report(report), encoding="utf-8")
    json_path.write_text(render_json(report, api_key), encoding="utf-8")
    print(render_json(report, api_key) if args.json else render_report(report, api_key))
    print(f"versioned reports: {markdown_path} and {json_path}")
    return _exit_code(report.status)


def _run_measurement_mode(args: Any, config: SmokeConfiguration) -> int:
    if not config.api_key:
        report = SmokeReport("not_run", "LLM_API_KEY not set", model=config.model, base_url=config.api_base)
        print(render_report(report))
        return 2
    store = SmokeUsageStore()
    _register_operator_metering(store)
    try:
        report = _measurement_report(args, config, store)
    finally:
        report.metering_rows = store.count_operator_rows()
        store.close()
        set_recorder(None)
    return _write_measurement_reports(args, report, config.api_key)


def _legacy_report(args: Any, config: SmokeConfiguration) -> SmokeReport:
    if not config.api_key:
        return SmokeReport("not_run", "LLM_API_KEY not set", model=config.model, base_url=config.api_base)
    try:
        chat_model = _build_smoke_model(args.timeout)
    except Exception as exc:  # noqa: BLE001 - construction failures become an explicit report failure
        reason = f"model build failed: {_redact(exc, config.api_key)}"
        return SmokeReport("fail", reason, model=config.model, base_url=config.api_base)
    return run_smoke(
        chat_model,
        expected_model=config.model,
        api_base=config.api_base,
        api_key=config.api_key,
        requester=_default_requester(config.api_base, config.api_key),
        timeout=args.timeout,
    )


def _exit_code(status: str) -> int:
    return {"pass": 0, "fail": 1, "not_run": 2}[status]


def main(argv: list[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(argv)
    config = SmokeConfiguration(configured_api_key(), configured_model(), configured_api_base())
    if (args.baseline or args.tool_calls) and not 1 <= args.repeats <= MAX_BASELINE_REPEATS:
        parser.error(f"--repeats must be between 1 and {MAX_BASELINE_REPEATS}.")
    if args.report and not (args.baseline or args.tool_calls):
        parser.error("--report requires --baseline or --tool-calls.")
    if args.timeout <= 0:
        parser.error("--timeout must be a positive number of seconds.")
    if args.baseline or args.tool_calls:
        return _run_measurement_mode(args, config)
    report = _legacy_report(args, config)
    print(render_json(report, config.api_key) if args.json else render_report(report, config.api_key))
    return _exit_code(report.status)


if __name__ == "__main__":
    raise SystemExit(main())
