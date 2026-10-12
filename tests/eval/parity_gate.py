"""Model-free gate plumbing shared by independently implemented suites.

Each suite owns ``run(context)``, ``run_hermetic(context)``, and
``validate(recorded_entry, report)``. Its result can use any score/total and a
count or percentage bar, and may include suite-specific evidence such as
``unauthorized_actions``, ``clinical_misses`` or ``unreviewed_count``. A suite
validator can fail for its own reasons even when its score clears the bar.

For example, a deterministic form suite can implement ``run(context)`` and
``run_hermetic(context)`` by checking local fixtures. It may return
``{"score": 9, "total": 10, "bar": {"kind": "percent", "value": 90},
"passed": False, "failure_reasons": ["1 case is unreviewed"],
"unreviewed_count": 1}``. Its ``validate(record, report)`` recomputes the
score and review status from those fixtures. Registering it in
``tests.eval.run_evaluation.SUITES`` makes live and hermetic execution plus
report re-validation require it without changing this gate module.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol


@dataclass(frozen=True)
class ScoreBar:
    """A pass threshold expressed as a raw count or a percentage of total."""

    kind: Literal["count", "percent"]
    value: int | float

    def __post_init__(self) -> None:
        if self.kind not in {"count", "percent"}:
            raise ValueError(f"Unknown score-bar kind: {self.kind}")
        if not math.isfinite(self.value) or self.value < 0:
            raise ValueError("Score-bar value must be a finite non-negative number.")
        if self.kind == "percent" and self.value > 100:
            raise ValueError("Percentage score bars cannot exceed 100.")

    def passes(self, score: float, total: float) -> bool:
        if self.kind == "count":
            return score >= self.value
        return total > 0 and (score / total) * 100 >= self.value

    def as_dict(self) -> dict[str, int | float | str]:
        return {"kind": self.kind, "value": self.value}


class Suite(Protocol):
    """An evaluation unit that owns execution and validation of its result."""

    name: str

    def run(self, context: Any) -> dict[str, Any]: ...

    def run_hermetic(self, context: Any) -> dict[str, Any]: ...

    def validate(self, recorded_entry: Any, report: dict[str, Any]) -> tuple[dict[str, Any], list[str]]: ...


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 8.0


@dataclass(frozen=True)
class CallResult:
    response: Any = None
    attempts: int = 0
    error: str | None = None


def configured_judges(environ: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Read judge ids and defaults from the shared hosted-model registry."""
    from utils.model_downloader import CLOUD_MODEL_REGISTRY, JUDGE_MODEL_ROLES

    settings = os.environ if environ is None else environ
    model_ids = [
        settings.get(CLOUD_MODEL_REGISTRY[role]["model_env"], CLOUD_MODEL_REGISTRY[role]["default_model"]).strip()
        for role in JUDGE_MODEL_ROLES
    ]
    judges = [
        {"name": f"judge_{index}", "model": model, "family": _model_family(model)}
        for index, model in enumerate(model_ids, start=1)
    ]
    if any(not judge["model"] for judge in judges):
        raise ValueError("Both configured judge model IDs must be non-empty.")
    if judges[0]["model"] == judges[1]["model"] or judges[0]["family"] == judges[1]["family"]:
        raise ValueError("The two configured judges must use different model families.")
    return judges


def _model_family(model_id: str) -> str:
    normalized = model_id.casefold()
    for family in ("qwen", "glm", "deepseek", "llama", "claude", "gpt"):
        if family in normalized:
            return family
    return model_id.split("/", maxsplit=1)[0].casefold()


def _env_float(settings: dict[str, str], name: str, default: float) -> float:
    try:
        parsed = float(settings.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) and parsed >= 0 else default


def retry_policy_from_env(environ: dict[str, str] | None = None) -> RetryPolicy:
    settings = os.environ if environ is None else environ
    try:
        attempts = max(1, int(settings.get("EVAL_JUDGE_MAX_ATTEMPTS", "4")))
    except (TypeError, ValueError):
        attempts = 4
    base = _env_float(settings, "EVAL_JUDGE_RETRY_BASE_SECONDS", 1.0)
    maximum = _env_float(settings, "EVAL_JUDGE_RETRY_MAX_SECONDS", 8.0)
    return RetryPolicy(attempts, base, max(base, maximum))


def _status_code(error: Exception) -> int | None:
    for source in (error, getattr(error, "response", None)):
        code = getattr(source, "status_code", None)
        if isinstance(code, int):
            return code
    return None


def _transient_error(error: Exception) -> bool:
    status = _status_code(error)
    if status == 429 or (status is not None and 500 <= status <= 599):
        return True
    try:
        import httpx
        from openai import APIConnectionError, APITimeoutError
    except ImportError:
        return isinstance(error, (TimeoutError, ConnectionError))
    return isinstance(
        error,
        (APITimeoutError, APIConnectionError, httpx.TimeoutException, httpx.NetworkError, TimeoutError, ConnectionError),
    )


def _structured_parse_error(error: Exception) -> bool:
    try:
        from langchain_core.exceptions import OutputParserException
        from pydantic import ValidationError
    except ImportError:
        return isinstance(error, json.JSONDecodeError)
    return isinstance(error, (OutputParserException, ValidationError, json.JSONDecodeError))


def _safe_error_message(error: Exception, limit: int = 500) -> str:
    message = str(error) or type(error).__name__
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    message = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", message)
    message = re.sub(r"\b(?:sk|hf)_[A-Za-z0-9_-]{8,}\b", "[REDACTED]", message)
    return message[:limit]


def call_with_retry(
    operation: Callable[[], Any],
    policy: RetryPolicy,
    sleeper: Callable[[float], None] = time.sleep,
) -> CallResult:
    """Retries transient transport failures and one structured parse failure."""
    attempts, transient_retries, parse_retried = 0, 0, False
    while True:
        attempts += 1
        try:
            return CallResult(response=operation(), attempts=attempts)
        except Exception as error:
            if _structured_parse_error(error) and not parse_retried:
                parse_retried = True
                continue
            if _transient_error(error) and transient_retries < policy.max_attempts - 1:
                delay = min(policy.base_delay_seconds * 2**transient_retries, policy.max_delay_seconds)
                transient_retries += 1
                sleeper(delay)
                continue
            return CallResult(attempts=attempts, error=_safe_error_message(error))


def evaluate_report(
    report: Any,
    suites: tuple[Suite, ...] | list[Suite],
) -> tuple[bool, list[str], list[dict[str, Any]]]:
    """Requires every registered suite and delegates validation to each suite."""
    if not isinstance(report, dict) or not isinstance(report.get("suite_results"), dict):
        return False, ["report has no 'suite_results' object"], []
    results = report["suite_results"]
    names = [suite.name for suite in suites]
    reasons = []
    if len(names) != len(set(names)):
        return False, ["registered suite names must be unique"], []
    if set(results) != set(names):
        missing = sorted(set(names) - set(results))
        extra = sorted(set(results) - set(names))
        if missing:
            reasons.append(f"report is missing registered suite(s): {', '.join(missing)}")
        if extra:
            reasons.append(f"report has unregistered suite(s): {', '.join(extra)}")
    summaries = []
    for suite in suites:
        if suite.name not in results:
            continue
        try:
            summary, suite_reasons = suite.validate(results[suite.name], report)
        except Exception as error:
            summary, suite_reasons = {}, [f"{suite.name}: report validation failed ({type(error).__name__})"]
        if not isinstance(summary, dict) or not isinstance(suite_reasons, list):
            summary, suite_reasons = {}, [f"{suite.name}: validator returned an invalid result"]
        summaries.append({"name": suite.name, **summary})
        reasons.extend(str(reason) for reason in suite_reasons)
        if summary.get("passed") is not True and not suite_reasons:
            reasons.append(f"{suite.name}: suite validator did not pass")
    return not reasons, reasons, summaries


def print_gate_summary(
    report: dict[str, Any],
    reasons: list[str],
    summaries: list[dict[str, Any]],
) -> None:
    judges = report.get("judges")
    if isinstance(judges, list):
        specs = [
            f"{judge.get('name', '?')}={judge.get('model', '?')} ({judge.get('family', '?')})"
            for judge in judges
            if isinstance(judge, dict)
        ]
        if specs:
            print(f"Judges: {'; '.join(specs)}")
    for suite in summaries:
        measures = suite.get("measures")
        if isinstance(measures, list):
            for measure in measures:
                if isinstance(measure, dict):
                    _print_result_line(f"{suite['name']} {measure.get('name', 'measure')}", measure)
        _print_suite_summary(suite)
    if report.get("mode") == "hermetic":
        print("PLAYER MODEL GATE: NOT RUN (hermetic validation only)")
    else:
        print(f"PLAYER MODEL GATE: {'PASSED' if not reasons else 'FAILED'}")
    for reason in reasons:
        print(f"  x {reason}", file=sys.stderr)


def _print_suite_summary(suite: dict[str, Any]) -> None:
    runs = suite.get("runs")
    if isinstance(runs, list) and runs:
        for run in runs:
            _print_result_line(f"{suite['name']} run {run.get('run', '?')}", run)
        _print_result_line(f"{suite['name']} suite", suite)
    else:
        _print_result_line(suite["name"], suite)


def _print_result_line(name: str, result: dict[str, Any]) -> None:
    score, total, bar = result.get("score", "?"), result.get("total", "?"), result.get("bar", {})
    if isinstance(bar, dict) and bar.get("kind") == "percent":
        bar_label = f"≥{bar.get('value', '?')}%"
    elif isinstance(bar, dict):
        bar_label = f"≥{bar.get('value', '?')}/{total}"
    else:
        bar_label = str(bar)
    judge_scores = result.get("judge_scores", {})
    judge_labels = "; ".join(
        f"{label}={value}/{total}" for label, value in judge_scores.items()
    ) if isinstance(judge_scores, dict) else ""
    status = result.get("status")
    if status == "unreviewed":
        verdict = "UNREVIEWED; observed score not counted"
    else:
        verdict = "PASS" if result.get("passed") is True else "FAIL"
    detail = f"; {judge_labels}" if judge_labels else ""
    print(f"{name}: {score}/{total} (bar {bar_label}){detail}; {verdict}")
