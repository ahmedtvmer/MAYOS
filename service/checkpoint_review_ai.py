"""Model-written wording for Checkpoint reviews (ADR 016/038/049/052)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from database.registry.model_usage import ALLOWANCE_EXEMPT_PURPOSE
from utils.env_flags import env_flag

logger = logging.getLogger(__name__)

CONTEXT_VERSION = "checkpoint-review-v1"
REPORT_VERSION = 1
MAX_OUTPUT_TOKENS = 200

# TODO(#135): revisit the Arabic dialect. Kept out of the prompt text, which is
# hashed into every recorded evaluation report.
SYSTEM_PROMPT = """Write a brief assessment for the player in 2–4 short sentences.
Use only the supplied facts and rating parts; never calculate, infer, restate labels as scores, or invent numbers.
Give no medical advice, and reply in the requested language: English or Modern Standard Arabic.
Keep the answer within 200 tokens."""

FACT_FIELDS = (
    ("workouts_in_period", "Workouts in this period"),
    ("weeks_met", "Weeks that met the training target"),
    ("weeks_counted", "Weeks with enough data"),
    ("personal_records", "Personal records in this period"),
    ("regressed_exercises", "Exercises with regression"),
    ("volume_first_half", "Working volume in first half (kg)"),
    ("volume_second_half", "Working volume in second half (kg)"),
)
RATING_PARTS = ("Consistency", "Progression", "Volume trend")

CANONICAL_FIXTURE: dict[str, Any] = {
    "facts": {
        "workouts_in_period": 10,
        "weeks_met": 4,
        "weeks_counted": 5,
        "personal_records": 2,
        "regressed_exercises": 1,
        "volume_first_half": 4200.0,
        "volume_second_half": 4500.0,
    },
    "rating": [
        {"part": "Consistency", "label": "Steady"},
        {"part": "Progression", "label": "Strong"},
        {"part": "Volume trend", "label": "Rising"},
    ],
    "language": "en",
}


@dataclass(frozen=True)
class GateStatus:
    requested: bool
    enabled: bool
    reason: str


@dataclass(frozen=True)
class ReviewGenerationRequest:
    db: Any
    account_id: str
    facts: dict[str, Any]
    rating: list[dict[str, Any]]
    language: str


def format_number(value: Any) -> str:
    """Formats every review figure the same way in prompts and evaluation."""
    if value is None:
        return "n/a"
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.1f}".rstrip("0").rstrip(".")


def _language_name(language: str) -> str:
    return "Arabic (Modern Standard Arabic)" if language == "ar" else "English"


def render_review(facts: dict[str, Any], rating: list[dict[str, Any]], language: str) -> str:
    """Projects only stored facts and rating parts into the model's input."""
    lines = ["[CHECKPOINT REVIEW FACTS]", f"Requested language: {_language_name(language)}"]
    for key, label in FACT_FIELDS:
        if key in facts:
            lines.append(f"{label}: {format_number(facts[key])}")
    lines.append("Rating parts:")
    allowed_parts = set(RATING_PARTS)
    for item in rating:
        if item.get("part") in allowed_parts and isinstance(item.get("label"), str):
            lines.append(f"{item['part']}: {item['label']}")
    return "\n".join(lines)


def build_messages(facts: dict[str, Any], rating: list[dict[str, Any]], language: str) -> list[Any]:
    from langchain_core.messages import SystemMessage

    rendered = render_review(facts, rating, language)
    return [SystemMessage(content=f"{SYSTEM_PROMPT}\n\n{rendered}")]


def canonical_messages_text() -> str:
    rendered = []
    for language in ("en", "ar"):
        fixture = {**CANONICAL_FIXTURE, "language": language}
        rendered.extend(
            f"{type(message).__name__}: {getattr(message, 'content', message)}"
            for message in build_messages(**fixture)
        )
    return "\n".join(rendered)


def prompt_version_hash() -> str:
    payload = f"{CONTEXT_VERSION}\n{SYSTEM_PROMPT}\n{canonical_messages_text()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def checkpoint_review_model_identity() -> tuple[str, str]:
    """Returns the hosted player model identity (`production` in this factory)."""
    from utils import model_downloader

    return model_downloader.model_identity("production")


def bind_review_model(model: Any, *, backend: str | None = None) -> Any:
    """Bounds review output and disables cloud thinking for this call only."""
    if backend is None:
        backend = checkpoint_review_model_identity()[1]
    params: dict[str, Any] = {"max_tokens": MAX_OUTPUT_TOKENS}
    if backend == "openai":
        params["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    return model.bind(**params)


def evaluate_gate(
    results: list[dict[str, Any]], expected: int | None = None
) -> tuple[bool, list[str], dict[str, Any]]:
    reasons: list[str] = []
    expected = len(results) if expected is None else expected
    stats: dict[str, Any] = {"total": len(results), "passed": 0, "expected": expected, "failed_cases": []}
    if expected and len(results) != expected:
        reasons.append(f"incomplete run: {len(results)} of {expected} cases")
    for result in results:
        if isinstance(result, dict) and result.get("passed") is True:
            stats["passed"] += 1
            continue
        failure, reason = _failed_case(result)
        stats["failed_cases"].append(failure)
        reasons.append(reason)
    if expected and stats["passed"] < expected:
        reasons.append(f"score {stats['passed']}/{stats['total']} below required {expected}/{expected}")
    return not reasons, reasons, stats


def _failed_case(case_run: Any) -> tuple[dict[str, Any], str]:
    case_id = case_run.get("case_id") if isinstance(case_run, dict) else None
    checks = case_run.get("checks") if isinstance(case_run, dict) else None
    failed = [
        name
        for name, check in (checks.items() if isinstance(checks, dict) else [])
        if not isinstance(check, dict) or check.get("passed") is not True
    ]
    return {"case_id": case_id, "checks": failed}, f"case {case_id}: failed {', '.join(failed) or 'unknown check'}"


def _report_identity_reasons(report: dict[str, Any]) -> list[str]:
    reasons = []
    version = report.get("report_version")
    if isinstance(version, bool) or version != REPORT_VERSION:
        reasons.append(f"report_version must be {REPORT_VERSION}")
    if report.get("mode") != "live":
        reasons.append("report was not produced by a live (non-mock) run")
    model_id, backend = checkpoint_review_model_identity()
    if report.get("model") != model_id:
        reasons.append(f"report model {report.get('model')!r} does not match the configured player model {model_id!r}")
    if report.get("backend") != backend:
        reasons.append(f"report backend {report.get('backend')!r} does not match the configured backend {backend!r}")
    if report.get("prompt_hash") != prompt_version_hash():
        reasons.append("evaluation report is for a different prompt version (prompt_hash mismatch)")
    return reasons


def _report_runs_error(runs: Any) -> str | None:
    if not isinstance(runs, list) or not runs:
        return "report has no recorded runs to re-check"
    if any(not isinstance(run, dict) for run in runs):
        return "report contains an invalid evaluation run"
    return None


def _report_gate_inputs(report: dict[str, Any]) -> tuple[list[str], dict[str, Any] | None, list[Any] | None]:
    gates = report.get("gates")
    if not isinstance(gates, dict):
        return ["evaluation report has no gates object"], None, None
    privacy, evaluation = gates.get("privacy"), gates.get("evaluation")
    reasons = [] if isinstance(privacy, dict) and privacy.get("pass") is True else [
        "privacy suite gate is not recorded as passed"
    ]
    if not isinstance(evaluation, dict):
        reasons.append("checkpoint review evaluation gate is not recorded")
        return reasons, None, None
    runs = report.get("runs")
    runs_error = _report_runs_error(runs)
    if runs_error is not None:
        reasons.append(runs_error)
        return reasons, evaluation, None
    return reasons, evaluation, runs


def _evaluation_verdict_reasons(evaluation: dict[str, Any], runs: list[Any]) -> list[str]:
    reasons = []
    threshold = evaluation.get("threshold")
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
        reasons.append("evaluation gate has no usable threshold")
        threshold = len(runs)
    derived_ok, derived_reasons, _stats = evaluate_gate(runs, threshold)
    reasons.extend(derived_reasons)
    if evaluation.get("pass") is not derived_ok:
        reasons.append("recorded evaluation gate disagrees with the recorded runs")
    return reasons


def validate_report(report: Any) -> tuple[bool, list[str]]:
    """Validates the same report format written by the evaluation runner."""
    if not isinstance(report, dict):
        return False, ["report is not a JSON object"]
    reasons = _report_identity_reasons(report)
    gate_reasons, evaluation, runs = _report_gate_inputs(report)
    reasons.extend(gate_reasons)
    if evaluation is not None and runs is not None:
        reasons.extend(_evaluation_verdict_reasons(evaluation, runs))
    if report.get("pass") is not True:
        reasons.append("evaluation report does not record pass=true")
    return not reasons, reasons


def _validate_report_file(path: str) -> tuple[bool, str]:
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"evaluation report is unreadable: {exc}"
    ok, reasons = validate_report(report)
    return (True, "ok") if ok else (False, "; ".join(reasons))


_report_cache: dict[tuple[str, int, int, str, str], tuple[bool, str]] = {}
_report_cache_lock = threading.Lock()
_REPORT_CACHE_LIMIT = 8


def _report_passes(path: str) -> tuple[bool, str]:
    try:
        stat = os.stat(path)
    except OSError:
        return False, f"evaluation report not found at {path}"
    model_id, backend = checkpoint_review_model_identity()
    key = (path, stat.st_mtime_ns, stat.st_size, model_id, backend)
    with _report_cache_lock:
        cached = _report_cache.get(key)
    if cached is not None:
        return cached
    verdict = _validate_report_file(path)
    with _report_cache_lock:
        if len(_report_cache) >= _REPORT_CACHE_LIMIT:
            _report_cache.clear()
        _report_cache[key] = verdict
    return verdict


def _flag_on() -> bool:
    return env_flag("CHECKPOINT_REVIEW_AI_ENABLED", False)


def resolve_enable_gate() -> GateStatus:
    if not _flag_on():
        return GateStatus(False, False, "CHECKPOINT_REVIEW_AI_ENABLED is off.")
    report_path = os.getenv("CHECKPOINT_REVIEW_EVAL_REPORT", "").strip()
    if not report_path:
        return GateStatus(True, False, "CHECKPOINT_REVIEW_EVAL_REPORT is not set; a live passing report is required.")
    ok, reason = _report_passes(report_path)
    if not ok:
        return GateStatus(True, False, reason)
    return GateStatus(True, True, "flag on and report accepted")


def log_enable_gate_at_startup() -> GateStatus:
    status = resolve_enable_gate()
    if status.requested and not status.enabled:
        logger.error("Checkpoint review AI requested but refused; the feature stays off: %s", status.reason)
    return status


def checkpoint_review_ai_enabled() -> bool:
    return resolve_enable_gate().enabled


def extract_text(reply: Any) -> str:
    from utils.text_scrubber import EMPTY_RESPONSE_FALLBACK, finalize_coach_output

    content = getattr(reply, "content", reply)
    finalized = finalize_coach_output("" if content is None else str(content))
    return "" if finalized == EMPTY_RESPONSE_FALLBACK else finalized


def _invoke_player_model(messages: list[Any]) -> str:
    from utils.model_downloader import get_llm

    return extract_text(bind_review_model(get_llm()).invoke(messages))


def generate_review_text(request: ReviewGenerationRequest) -> str:
    """Runs the metered player model without consuming the account's allowance."""
    from svc.llm import InferenceScope, run_inference_sync

    messages = build_messages(request.facts, request.rating, request.language)
    return run_inference_sync(
        _invoke_player_model,
        messages,
        scope=InferenceScope(
            account_id=request.account_id,
            role="player",
            purpose=ALLOWANCE_EXEMPT_PURPOSE,
            admit=False,
            store=request.db,
        ),
    )


__all__ = [
    "CANONICAL_FIXTURE",
    "CONTEXT_VERSION",
    "MAX_OUTPUT_TOKENS",
    "REPORT_VERSION",
    "ReviewGenerationRequest",
    "SYSTEM_PROMPT",
    "GateStatus",
    "bind_review_model",
    "build_messages",
    "canonical_messages_text",
    "checkpoint_review_ai_enabled",
    "checkpoint_review_model_identity",
    "evaluate_gate",
    "extract_text",
    "format_number",
    "generate_review_text",
    "log_enable_gate_at_startup",
    "prompt_version_hash",
    "render_review",
    "resolve_enable_gate",
    "validate_report",
]
