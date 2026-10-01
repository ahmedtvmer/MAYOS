"""Shared validation and enablement for live evaluation reports."""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from utils.env_flags import env_flag


@dataclass(frozen=True)
class GateStatus:
    """The feature flag as configured, its effective state, and the reason."""

    requested: bool
    enabled: bool
    reason: str


@dataclass(frozen=True)
class EvaluationReportConfig:
    """Feature-specific identity used by the common Evaluation report gate."""

    enabled_flag: str
    report_env_var: str
    model_identity: Callable[[], tuple[str, str]]
    prompt_hash: Callable[[], str]
    report_version: int
    suite_name: str
    model_label: str
    startup_label: str
    missing_report_reason: str
    evaluation_gate_name: str
    strict: bool = False


# The path + file identity + configured model key is intentionally shared by
# both features. The cached context marker prevents one feature's verdict from
# being reused for a different suite if both point at the same file.
_report_cache: dict[tuple[str, int, int, str, str], tuple[tuple[Any, ...], tuple[bool, str]]] = {}
_report_cache_lock = threading.Lock()
_REPORT_CACHE_LIMIT = 8


def evaluate_gate(
    results: list[dict[str, Any]], expected: int | None = None, *, strict: bool = False
) -> tuple[bool, list[str], dict[str, Any]]:
    """Single definition of the evaluation verdict for runners and validation.

    The runner records this verdict and report validation re-derives it from
    the recorded runs, so the recorded gate cannot disagree with its evidence.
    """
    reasons: list[str] = []
    expected = len(results) if expected is None else expected
    stats: dict[str, Any] = {"total": len(results), "passed": 0, "expected": expected, "failed_cases": []}
    if expected and len(results) != expected:
        reasons.append(f"incomplete run: {len(results)} of {expected} cases")
    for result in results:
        if strict and isinstance(result, dict) and result.get("passed") is True:
            stats["passed"] += 1
            continue
        if not strict and result.get("passed"):
            stats["passed"] += 1
            continue
        case_id = result.get("case_id") if isinstance(result, dict) else None
        checks = result.get("checks") if isinstance(result, dict) else None
        if strict:
            failed = [
                name
                for name, check in (checks.items() if isinstance(checks, dict) else [])
                if not isinstance(check, dict) or check.get("passed") is not True
            ]
        else:
            failed = [name for name, check in (result.get("checks") or {}).items() if not check.get("passed")]
        stats["failed_cases"].append({"case_id": case_id, "checks": failed})
        reasons.append(f"case {case_id}: failed {', '.join(failed) or 'unknown check'}")
    if expected and stats["passed"] < expected:
        reasons.append(f"score {stats['passed']}/{stats['total']} below required {expected}/{expected}")
    return not reasons, reasons, stats


def validate_report(report: Any, config: EvaluationReportConfig) -> tuple[bool, list[str]]:
    """Validates provenance and re-derives a report's verdict from its runs."""
    if not isinstance(report, dict):
        return False, ["report is not a JSON object"]

    reasons: list[str] = []
    version = report.get("report_version")
    if (config.strict and isinstance(version, bool)) or version != config.report_version:
        reasons.append(f"report_version must be {config.report_version}")
    if report.get("mode") != "live":
        reasons.append("report was not produced by a live (non-mock) run")

    model_id, backend = config.model_identity()
    if report.get("model") != model_id:
        reasons.append(
            f"report model {report.get('model')!r} does not match the configured {config.model_label} model {model_id!r}"
        )
    if report.get("backend") != backend:
        reasons.append(f"report backend {report.get('backend')!r} does not match the configured backend {backend!r}")
    if report.get("prompt_hash") != config.prompt_hash():
        reasons.append("evaluation report is for a different prompt version (prompt_hash mismatch)")

    gates = report.get("gates")
    if not isinstance(gates, dict):
        reasons.append("evaluation report has no gates object")
        if config.strict and report.get("pass") is not True:
            reasons.append("evaluation report does not record pass=true")
        return False, reasons
    privacy = gates.get("privacy")
    if not isinstance(privacy, dict) or privacy.get("pass") is not True:
        reasons.append("privacy suite gate is not recorded as passed")
    evaluation = gates.get("evaluation")
    if not isinstance(evaluation, dict):
        reasons.append(f"{config.evaluation_gate_name} is not recorded")
        if config.strict and report.get("pass") is not True:
            reasons.append("evaluation report does not record pass=true")
        return False, reasons

    runs = report.get("runs")
    if not isinstance(runs, list) or not runs:
        reasons.append("report has no recorded runs to re-check")
        if config.strict and report.get("pass") is not True:
            reasons.append("evaluation report does not record pass=true")
        return False, reasons
    if config.strict and any(not isinstance(run, dict) for run in runs):
        reasons.append("report contains an invalid evaluation run")
        if report.get("pass") is not True:
            reasons.append("evaluation report does not record pass=true")
        return False, reasons

    threshold = evaluation.get("threshold")
    invalid_boolean = config.strict and isinstance(threshold, bool)
    if not isinstance(threshold, int) or invalid_boolean or threshold < 1:
        reasons.append("evaluation gate has no usable threshold")
        threshold = len(runs)
    derived_ok, derived_reasons, _stats = evaluate_gate(
        runs,
        threshold,
        strict=config.strict,
    )
    reasons.extend(derived_reasons)
    if evaluation.get("pass") is not derived_ok:
        reasons.append("recorded evaluation gate disagrees with the recorded runs")
    if report.get("pass") is not True:
        reasons.append("evaluation report does not record pass=true")
    return not reasons, reasons


def validate_report_file(
    path: str,
    validator: Callable[[Any], tuple[bool, list[str]]],
) -> tuple[bool, str]:
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"evaluation report is unreadable: {exc}"
    ok, reasons = validator(report)
    return (True, "ok") if ok else (False, "; ".join(reasons))


def report_passes(
    path: str,
    config: EvaluationReportConfig,
    validator_file: Callable[[str], tuple[bool, str]],
) -> tuple[bool, str]:
    """Uses one cached verdict per path, file identity, model, and backend.

    The prompt hash is code-derived and stable for the process, so it is
    checked when parsing a report and deliberately stays out of the cache-hit
    path. Suite and version distinguish feature contexts that share a path.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return False, f"evaluation report not found at {path}"
    model_id, backend = config.model_identity()
    key = (path, stat.st_mtime_ns, stat.st_size, model_id, backend)
    context = (config.suite_name, config.report_version)
    with _report_cache_lock:
        cached = _report_cache.get(key)
    if cached is not None and cached[0] == context:
        return cached[1]
    verdict = validator_file(path)
    with _report_cache_lock:
        if len(_report_cache) >= _REPORT_CACHE_LIMIT:
            _report_cache.clear()
        _report_cache[key] = (context, verdict)
    return verdict


def resolve_enable_gate(
    config: EvaluationReportConfig,
    validator_file: Callable[[str], tuple[bool, str]],
) -> GateStatus:
    # A flag-off deployment never reads or stats the report file.
    if not env_flag(config.enabled_flag, False):
        return GateStatus(False, False, f"{config.enabled_flag} is off.")
    report_path = os.getenv(config.report_env_var, "").strip()
    if not report_path:
        return GateStatus(True, False, config.missing_report_reason)
    ok, reason = report_passes(report_path, config, validator_file)
    if not ok:
        return GateStatus(True, False, reason)
    return GateStatus(True, True, "flag on and report accepted")


def log_enable_gate_at_startup(
    config: EvaluationReportConfig,
    resolve: Callable[[], GateStatus],
    feature_logger: logging.Logger,
) -> GateStatus:
    status = resolve()
    if status.requested and not status.enabled:
        feature_logger.error("%s requested but refused; the feature stays off: %s", config.startup_label, status.reason)
    return status
