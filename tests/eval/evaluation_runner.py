"""Shared CLI and JSON report workflow for feature Evaluation runners."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from service.evaluation_report_gate import EvaluationReportConfig, evaluate_gate


@dataclass(frozen=True)
class EvaluationRunnerConfig:
    title: str
    description: str
    suite_name: str
    dataset_path: Path
    dataset_label: str
    privacy_suite: str
    report_config: EvaluationReportConfig
    context_version: str
    ensure_ascii: bool
    no_privacy_help: str
    check_title: str | None = None
    check_report_help: str = "Re-check an existing report without loading any model."


def load_cases(dataset_path: Path, dataset_label: str) -> list[dict[str, Any]]:
    cases = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{dataset_label} eval dataset must be a non-empty list: {dataset_path}")
    return cases


def run_privacy_suite(privacy_suite: str, base_dir: Path) -> bool:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", privacy_suite],
        cwd=str(base_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def build_report(
    results: list[dict[str, Any]],
    *,
    mode: str,
    privacy_pass: bool,
    dataset_path: Path,
    config: EvaluationRunnerConfig,
) -> dict[str, Any]:
    model_id, backend = config.report_config.model_identity()
    threshold = len(load_cases(dataset_path, config.dataset_label))
    evaluation_ok, reasons, stats = evaluate_gate(
        results,
        threshold,
        strict=config.report_config.strict,
    )
    report = {
        "report_version": config.report_config.report_version,
        "suite": config.suite_name,
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": Path(dataset_path).name,
        "prompt_hash": config.report_config.prompt_hash(),
        "context_version": config.context_version,
        "model": model_id,
        "backend": backend,
        "gates": {
            "privacy": {"pass": bool(privacy_pass), "suite": config.privacy_suite},
            "evaluation": {
                "pass": bool(evaluation_ok),
                "total": stats["total"],
                "passed": stats["passed"],
                "threshold": threshold,
            },
        },
        "run": stats,
        "reasons": reasons,
        "runs": results,
    }
    report["pass"] = bool(privacy_pass and evaluation_ok)
    return report


def write_report(path: Path, report: dict[str, Any], *, ensure_ascii: bool) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=ensure_ascii), encoding="utf-8")
    return path


def check_report(
    report_path: Path,
    validator: Callable[[Any], tuple[bool, list[str]]],
    *,
    strict: bool,
) -> tuple[bool, list[str]]:
    path = Path(report_path)
    if not path.is_file():
        return False, [f"report not found: {path}"]
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return False, [f"report is not valid JSON: {exc}"]
    except OSError as exc:
        if strict:
            return False, [f"report is not valid JSON: {exc}"]
        raise
    return validator(report)


def run_main(
    argv: list[str] | None,
    *,
    config: EvaluationRunnerConfig,
    base_dir: Path,
    run_cases: Callable[[list[dict[str, Any]], bool, Path], list[dict[str, Any]]],
    validator: Callable[[Any], tuple[bool, list[str]]],
) -> int:
    parser = argparse.ArgumentParser(description=config.description)
    parser.add_argument("--dataset", type=Path, default=config.dataset_path, help="Fixture cases JSON.")
    parser.add_argument("--mock", action="store_true", help="Plumbing run against the in-repo mock model.")
    parser.add_argument("--write-report", type=Path, default=None, help="Write the enablement report JSON here.")
    parser.add_argument("--no-privacy", action="store_true", help=config.no_privacy_help)
    parser.add_argument("--check-report", type=Path, default=None, help=config.check_report_help)
    args = parser.parse_args(argv)

    if args.check_report is not None:
        ok, reasons = check_report(args.check_report, validator, strict=config.report_config.strict)
        print(f"{config.check_title or config.title} eval report: {'PASSED' if ok else 'FAILED'}")
        for reason in reasons:
            print(f"  x {reason}", file=sys.stderr)
        return 0 if ok else 1

    cases = load_cases(args.dataset, config.dataset_label)
    mode = "mock" if args.mock else "live"
    print(f"{config.title} evaluation: {len(cases)} cases ({mode} mode)")
    results = run_cases(cases, args.mock, args.dataset)
    gate_ok, reasons, stats = evaluate_gate(
        results,
        len(cases),
        strict=config.report_config.strict,
    )
    for result in results:
        mark = "pass" if result["passed"] else "FAIL"
        print(f"  [{mark}] {result['case_id']}")
    print(f"evaluation gate: {stats['passed']}/{stats['total']} passed")
    for reason in reasons:
        print(f"  x {reason}", file=sys.stderr)

    if args.write_report is not None:
        privacy_pass = False
        if args.no_privacy:
            print("privacy gate: skipped (recorded as failed)", file=sys.stderr)
        else:
            print(f"running {config.privacy_suite} ...")
            privacy_pass = run_privacy_suite(config.privacy_suite, base_dir)
            print(f"privacy gate: {'passed' if privacy_pass else 'failed'}")
        report = build_report(
            results,
            mode=mode,
            privacy_pass=privacy_pass,
            dataset_path=args.dataset,
            config=config,
        )
        write_report(args.write_report, report, ensure_ascii=config.ensure_ascii)
        print(f"report written: {args.write_report} (pass={report['pass']})")
        if not args.mock and not report["pass"]:
            return 1
        return 0

    if args.mock:
        return 0 if len(results) == len(cases) else 1
    return 0 if gate_ok else 1
