"""Run the #248 Arabic coach evaluation without changing the Coach AI gate."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(BASE_DIR))

from tests.eval import arabic_coach_evaluation as evaluation  # noqa: E402


def _mock_model(cases: list[dict[str, Any]]):
    from tests.fakes.chat_model import ScriptedChatModel

    return ScriptedChatModel(
        turns=[evaluation.mock_answer(case) for case in cases],
        model_name="arabic-coach-eval-plumbing-mock",
    )


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    templates_fixture = evaluation.load_templates()
    facts_fixture = evaluation.load_facts()
    cases = evaluation.expand_cases(templates_fixture, facts_fixture)
    mode = "mock" if arguments.mock else "live"
    print(
        f"Arabic coach evaluation: {templates_fixture['base_template_count']} base templates, "
        f"{len(cases)} runs ({mode})"
    )
    runs, report = _run_evaluation(cases, mode, facts_fixture)
    _print_runs(runs)
    _print_report_summary(runs, report)
    if arguments.write_report:
        _write_report(arguments.write_report, report, mode)
    return _exit_code(report)


def _parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the synthetic Arabic coach-question evaluation.")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--mock", action="store_true", help="Run deterministic scripted plumbing answers only.")
    modes.add_argument("--live", action="store_true", help="Call the configured hosted coach model.")
    parser.add_argument("--write-report", type=Path, help="Write a per-case JSON report to this path.")
    args = parser.parse_args(argv)
    if args.live and args.write_report is None:
        parser.error("--live requires --write-report so the live result is recorded.")
    return args


def _run_evaluation(
    cases: list[dict[str, Any]],
    mode: str,
    facts_fixture: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        model = _evaluation_model(cases, mode)
        runs = evaluation.run_suite(cases, model=model, mode=mode, facts_fixture=facts_fixture)
        report = evaluation.build_report(runs, mode=mode, facts_fixture=facts_fixture)
    except Exception as exc:
        return _runner_error_report(exc, mode, facts_fixture)
    return runs, report


def _evaluation_model(cases: list[dict[str, Any]], mode: str) -> Any:
    if mode == "mock":
        return _mock_model(cases)
    from utils.model_downloader import get_coach_llm

    return get_coach_llm()


def _runner_error_report(
    error: Exception, mode: str, facts_fixture: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report = evaluation.build_report([], mode=mode, fatal_error=error, facts_fixture=facts_fixture)
    print(f"runner error: {type(error).__name__}", file=sys.stderr)
    return [], report


def _print_runs(runs: list[dict[str, Any]]) -> None:
    for run in runs:
        status = run.get("status", "completed")
        mark = "pass" if run.get("passed") else ("runner_error" if status == "runner_error" else "FAIL")
        print(f"  [{mark}] {run['run_id']}")


def _print_report_summary(runs: list[dict[str, Any]], report: dict[str, Any]) -> None:
    print(
        "run status: {status}; scored {passed}/{total}; evaluation_pass={evaluation_pass}".format(
            status=report["run_status"],
            passed=sum(bool(run.get("passed")) for run in runs),
            total=len(runs),
            evaluation_pass=report["evaluation_pass"],
        )
    )


def _write_report(path: Path, report: dict[str, Any], mode: str) -> None:
    written = evaluation.write_report(path, report, ensure_ascii=False)
    print(f"report written: {written} (mode={mode}, production_gate_eligible=false)")


def _exit_code(report: dict[str, Any]) -> int:
    if report["run_status"] == "runner_error":
        return 2
    return 0 if report["evaluation_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
