"""Checkpoint review evaluation and live enablement report (issue #222)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(BASE_DIR))

from service.checkpoint_review_ai import (  # noqa: E402
    CONTEXT_VERSION,
    REPORT_VERSION,
    bind_review_model,
    build_messages,
    checkpoint_review_model_identity,
    evaluate_gate,
    extract_text,
    prompt_version_hash,
    validate_report,
)
from tests.eval.checkpoint_review_rubric import evaluate_case  # noqa: E402

DEFAULT_DATASET = Path(__file__).resolve().parent / "datasets" / "checkpoint_review_cases.json"
PRIVACY_SUITE = "tests/test_checkpoint_review_ai_privacy.py"


def load_cases(dataset_path: Path = DEFAULT_DATASET) -> list[dict[str, Any]]:
    cases = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"checkpoint review eval dataset must be a non-empty list: {dataset_path}")
    return cases


def _prompt_text(messages: list[Any]) -> str:
    return "\n".join(str(getattr(message, "content", message)) for message in messages)


def run_suite(
    cases: list[dict[str, Any]] | None = None,
    *,
    model: Any = None,
    model_backend: str | None = None,
    dataset_path: Path = DEFAULT_DATASET,
) -> list[dict[str, Any]]:
    if cases is None:
        cases = load_cases(dataset_path)
    if model is None:
        from utils.model_downloader import get_llm

        model = get_llm()
    bound_model = bind_review_model(model, backend=model_backend)
    results: list[dict[str, Any]] = []
    for case in cases:
        messages = build_messages(case.get("facts") or {}, list(case.get("rating") or []), str(case.get("language", "en")))
        prompt = _prompt_text(messages)
        answer = extract_text(bound_model.invoke(messages))
        result = evaluate_case(case, prompt, answer)
        result["prompt"] = prompt
        results.append(result)
    return results


def run_privacy_suite(base_dir: Path = BASE_DIR) -> bool:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", PRIVACY_SUITE],
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
    dataset_path: Path = DEFAULT_DATASET,
) -> dict[str, Any]:
    model_id, backend = checkpoint_review_model_identity()
    threshold = len(load_cases(dataset_path))
    evaluation_ok, reasons, stats = evaluate_gate(results, threshold)
    report = {
        "report_version": REPORT_VERSION,
        "suite": "checkpoint_review",
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": Path(dataset_path).name,
        "prompt_hash": prompt_version_hash(),
        "context_version": CONTEXT_VERSION,
        "model": model_id,
        "backend": backend,
        "gates": {
            "privacy": {"pass": bool(privacy_pass), "suite": PRIVACY_SUITE},
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


def write_report(path: Path, report: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def check_report(report_path: Path) -> tuple[bool, list[str]]:
    path = Path(report_path)
    if not path.is_file():
        return False, [f"report not found: {path}"]
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, [f"report is not valid JSON: {exc}"]
    return validate_report(report)


def _mock_model():
    from utils.model_downloader import MockSafeChatLlamaCpp

    return MockSafeChatLlamaCpp()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Checkpoint review evaluation + enablement report (issue #222)")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Fixture cases JSON.")
    parser.add_argument("--mock", action="store_true", help="Plumbing run against the in-repo mock model.")
    parser.add_argument("--write-report", type=Path, default=None, help="Write the enablement report JSON here.")
    parser.add_argument("--no-privacy", action="store_true", help="Skip privacy suite and record the gate as failed.")
    parser.add_argument("--check-report", type=Path, default=None, help="Validate an existing report without loading a model.")
    args = parser.parse_args(argv)
    if args.check_report is not None:
        ok, reasons = check_report(args.check_report)
        print(f"checkpoint review eval report: {'PASSED' if ok else 'FAILED'}")
        for reason in reasons:
            print(f"  x {reason}", file=sys.stderr)
        return 0 if ok else 1

    cases = load_cases(args.dataset)
    mode = "mock" if args.mock else "live"
    print(f"checkpoint review evaluation: {len(cases)} cases ({mode} mode)")
    results = run_suite(
        cases,
        model=_mock_model() if args.mock else None,
        model_backend="local" if args.mock else None,
        dataset_path=args.dataset,
    )
    gate_ok, reasons, stats = evaluate_gate(results, len(cases))
    for result in results:
        print(f"  [{'pass' if result['passed'] else 'FAIL'}] {result['case_id']}")
    print(f"evaluation gate: {stats['passed']}/{stats['total']} passed")
    for reason in reasons:
        print(f"  x {reason}", file=sys.stderr)

    if args.write_report is not None:
        privacy_pass = False
        if args.no_privacy:
            print("privacy gate: skipped (recorded as failed)", file=sys.stderr)
        else:
            print(f"running {PRIVACY_SUITE} ...")
            privacy_pass = run_privacy_suite()
            print(f"privacy gate: {'passed' if privacy_pass else 'failed'}")
        report = build_report(results, mode=mode, privacy_pass=privacy_pass, dataset_path=args.dataset)
        write_report(args.write_report, report)
        print(f"report written: {args.write_report} (pass={report['pass']})")
        if not args.mock and not report["pass"]:
            return 1
        return 0
    if args.mock:
        return 0 if len(results) == len(cases) else 1
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
