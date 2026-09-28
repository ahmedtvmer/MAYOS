# tests/eval/run_coach_evaluation.py
"""Coach assistant evaluation runner and enablement report (issue #45, ADR 049).

Two gates decide whether ``COACH_AI_ENABLED`` may turn the feature on:

1. **Privacy** — ``tests/test_coach_ai_privacy.py`` (hermetic, mock LLM).
2. **Evaluation** — this runner, which builds the *production* prompt for each
   fixture case (``service.coach_ai.render_context`` + ``build_messages``),
   asks the coach model, and scores the answer with the deterministic rubric in
   ``tests/eval/coach_rubric.py``.

``--write-report PATH`` runs both gates and records the JSON the service checks
at startup (``COACH_AI_EVAL_REPORT``): ``pass``, the current ``prompt_hash``,
the configured coach ``model``/``backend``, and both gate results. The service
re-derives the verdict from the recorded runs with the *same*
``service.coach_ai.evaluate_gate`` this runner uses, so the report and the gate
can never disagree. ``--check-report PATH`` re-checks an existing report
without loading any model (it calls the same shared validator);
``--mock`` is a plumbing run against the in-repo mock model and is what pytest
exercises; the real-model run is what the owner records.

Usage::

    python tests/eval/run_coach_evaluation.py --check-report reports/coach_ai_eval.json
    python tests/eval/run_coach_evaluation.py --mock
    python tests/eval/run_coach_evaluation.py --write-report reports/coach_ai_eval.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from service.coach_ai import (  # noqa: E402  (path bootstrap first, mirrors run_evaluation.py)
    CONTEXT_VERSION,
    REPORT_VERSION,
    build_messages,
    coach_model_identity,
    evaluate_gate,
    extract_answer,
    prompt_version_hash,
    render_context,
    validate_report,
)
from tests.eval.coach_rubric import evaluate_case  # noqa: E402

DEFAULT_DATASET = Path(__file__).resolve().parent / "datasets" / "coach_assistant_cases.json"
PRIVACY_SUITE = "tests/test_coach_ai_privacy.py"


def load_cases(dataset_path: Path = DEFAULT_DATASET) -> list[dict[str, Any]]:
    cases = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"coach eval dataset must be a non-empty list: {dataset_path}")
    return cases


def _prompt_text(messages: list[Any]) -> str:
    return "\n".join(str(getattr(message, "content", message)) for message in messages)


def run_suite(
    cases: list[dict[str, Any]] | None = None,
    *,
    model: Any = None,
    dataset_path: Path = DEFAULT_DATASET,
) -> list[dict[str, Any]]:
    """Builds the production prompt per case, asks the model, and rubrics the answer."""
    if cases is None:
        cases = load_cases(dataset_path)
    if model is None:
        from utils.model_downloader import get_coach_llm

        model = get_coach_llm()

    results: list[dict[str, Any]] = []
    for case in cases:
        context_text = render_context(case.get("facts") or {})
        messages = build_messages(
            context_text, str(case.get("question", "")), list(case.get("history") or [])
        )
        # Production applies the same extraction/finalization to the reply (ADR 049).
        answer = extract_answer(model.invoke(messages))
        result = evaluate_case(case, context_text, answer, prompt_text=_prompt_text(messages))
        result["context"] = context_text
        results.append(result)
    return results


def run_privacy_suite(base_dir: Path = BASE_DIR) -> bool:
    """Runs the hermetic privacy suite in a subprocess; records its verdict."""
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
    """Assembles the enablement report: provenance, both gates, and the runs."""
    model_id, backend = coach_model_identity()
    threshold = len(load_cases(dataset_path))
    evaluation_ok, reasons, stats = evaluate_gate(results, threshold)
    report = {
        "report_version": REPORT_VERSION,
        "suite": "coach_assistant",
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(Path(dataset_path).name),
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
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def check_report(report_path: Path) -> tuple[bool, list[str]]:
    """Re-checks a produced report without loading any model.

    Delegates to the service's shared validator, so ``--check-report`` and the
    startup gate accept and reject exactly the same reports.
    """
    path = Path(report_path)
    if not path.is_file():
        return False, [f"report not found: {path}"]
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return False, [f"report is not valid JSON: {exc}"]
    return validate_report(report)


def _mock_model():
    from utils.model_downloader import MockSafeChatLlamaCpp

    return MockSafeChatLlamaCpp()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coach assistant evaluation + enablement report (issue #45)")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Fixture cases JSON.")
    parser.add_argument("--mock", action="store_true", help="Plumbing run against the in-repo mock model.")
    parser.add_argument("--write-report", type=Path, default=None, help="Write the enablement report JSON here.")
    parser.add_argument(
        "--no-privacy",
        action="store_true",
        help="Do not run the privacy suite; records the privacy gate as failed.",
    )
    parser.add_argument(
        "--check-report",
        type=Path,
        default=None,
        help="Re-check an existing report without loading any model.",
    )
    args = parser.parse_args(argv)

    if args.check_report is not None:
        ok, reasons = check_report(args.check_report)
        print(f"coach eval report: {'PASSED' if ok else 'FAILED'}")
        for reason in reasons:
            print(f"  x {reason}", file=sys.stderr)
        return 0 if ok else 1

    cases = load_cases(args.dataset)
    mode = "mock" if args.mock else "live"
    print(f"coach assistant evaluation: {len(cases)} cases ({mode} mode)")
    results = run_suite(cases, model=_mock_model() if args.mock else None, dataset_path=args.dataset)
    gate_ok, reasons, stats = evaluate_gate(results, len(cases))
    for case in results:
        mark = "pass" if case["passed"] else "FAIL"
        print(f"  [{mark}] {case['case_id']}")
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

    # A mock run is a plumbing check: structure is the verdict, not the gate.
    if args.mock:
        return 0 if len(results) == len(cases) else 1
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
