"""Run and report the registered hosted player-model evaluation suites."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("MODEL_DEVICE", "cpu")
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from tests.eval.parity_gate import (  # noqa: E402
    CallResult,
    RetryPolicy,
    ScoreBar,
    Suite,
    call_with_retry,
    configured_judges,
    evaluate_report,
    print_gate_summary,
    retry_policy_from_env,
    _safe_error_message,
)
from tests.eval.schemas import CoachingQAEvalJudgment  # noqa: E402
from tests.eval.suites.arabic_replies import SUITE as ARABIC_REPLIES_SUITE  # noqa: E402
from tests.eval.suites.structured_output import SUITE as STRUCTURED_OUTPUT_SUITE  # noqa: E402
from tests.eval.suites.routing import RoutingSuite  # noqa: E402

REPORTS_DIR = BASE_DIR / "tests" / "eval" / "reports"
DATASETS_DIR = BASE_DIR / "tests" / "eval" / "datasets"
JUDGE_NAMES = ("judge_1", "judge_2")
HERMETIC_JUDGMENT = {
    name: {"score": 5, "rationale": "Hermetic fixture verdict."}
    for name in CoachingQAEvalJudgment.model_fields
}
HERMETIC_JUDGMENT["is_passed"] = True


@dataclass(frozen=True)
class GateContext:
    judges: list[dict[str, Any]]
    judge_metadata: list[dict[str, str]]
    retry_policy: RetryPolicy


@dataclass(frozen=True)
class CaseScore:
    passed: bool
    judge_passes: dict[str, bool]
    safety_failures: list[dict[str, Any]]
    reasons: list[str]


def load_suite_cases(dataset_file: str, expected: int, dataset_key: str | None = None) -> list[dict[str, Any]]:
    path = Path(os.getenv("EVAL_DATASETS_DIR", str(DATASETS_DIR))) / dataset_file
    if not path.is_file():
        raise ValueError(f"Evaluation dataset not found at: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get(dataset_key) if dataset_key else payload
    if not isinstance(cases, list) or len(cases) != expected:
        count = len(cases) if isinstance(cases, list) else "invalid"
        raise ValueError(f"Expected {expected} cases in {path}, got {count}.")
    return cases


def _invoke_assistant_graph(state: dict[str, Any]) -> dict[str, Any]:
    from agent.assistant_graph import assistant_graph
    from database.database_manager import DatabaseManager

    db = DatabaseManager()
    try:
        with db.open_ledger(str(state.get("trainee_id", "eval_user"))) as ledger:
            config = {"configurable": {"ledger": ledger, "store": db}}
            return assistant_graph.invoke(state, config=config)
    finally:
        db.catalog_conn.close()


def _generate_reply(case: dict[str, Any]) -> tuple[str, float]:
    from langchain_core.messages import HumanMessage
    from utils.text_scrubber import scrub_coach_output

    state = {
        "messages": [HumanMessage(content=case["query"])],
        "trainee_id": "eval_user",
        "coach_tone": "Direct, grounded, and pragmatic",
        "custom_instructions": "",
        "telemetry_context": case.get("telemetry", ""),
    }
    started = time.perf_counter()
    graph_output = _invoke_assistant_graph(state)
    reply = scrub_coach_output(graph_output.get("response_content", ""))
    return reply, time.perf_counter() - started


def _judge_messages(case: dict[str, Any], reply: str) -> list[Any]:
    from langchain_core.messages import HumanMessage, SystemMessage
    from tests.eval.rubrics import COACHING_QA_RUBRIC

    prompt = (
        f"[TRAINEE CONTEXT]\n{case.get('telemetry', 'None')}\n\n"
        f"[USER QUERY]\n{case['query']}\n\n[COACH RESPONSE]\n{reply}"
    )
    return [SystemMessage(content=COACHING_QA_RUBRIC), HumanMessage(content=prompt)]


def _judge_record(
    judge: dict[str, Any],
    case: dict[str, Any],
    reply: str,
    policy: RetryPolicy,
) -> dict[str, Any]:
    from tests.eval.schemas import CoachingQAEvalJudgment

    def invoke():
        structured = judge["client"].with_structured_output(CoachingQAEvalJudgment, method="function_calling")
        return structured.invoke(_judge_messages(case, reply))

    return _record_judgment(judge, call_with_retry(invoke, policy))


def _record_judgment(judge: dict[str, Any], call: CallResult) -> dict[str, Any]:
    judgment = call.response
    if judgment is None:
        return {
            "model": judge["model"],
            "passed": False,
            "judgment": None,
            "attempts": call.attempts,
            "error": call.error or "No structured judgment returned",
        }
    return {
        "model": judge["model"],
        "passed": bool(judgment.is_passed),
        "judgment": judgment.model_dump(),
        "attempts": call.attempts,
        "error": None,
    }


def evaluate_case(
    case: dict[str, Any],
    reply: str,
    judges: list[dict[str, Any]],
    policy: RetryPolicy,
) -> dict[str, Any]:
    verdicts = {judge["name"]: _judge_record(judge, case, reply, policy) for judge in judges}
    return {
        "case_id": case.get("id", "?"),
        "query": case.get("query", ""),
        "generated_output": reply,
        "judges": verdicts,
        "passed": all(verdict.get("passed") is True for verdict in verdicts.values()),
    }


def _failed_generation_case(
    case: dict[str, Any],
    judges: list[dict[str, Any]],
    error: Exception,
    generation_seconds: float,
) -> dict[str, Any]:
    message = _safe_error_message(error)
    return {
        "case_id": case.get("id", "?"),
        "query": case.get("query", ""),
        "generated_output": None,
        "generation_seconds": generation_seconds,
        "generation_error": message,
        "judges": {
            judge["name"]: {
                "model": judge["model"],
                "passed": False,
                "judgment": None,
                "attempts": 0,
                "error": f"Player generation failed: {message}",
            }
            for judge in judges
        },
        "passed": False,
    }


def _run_suite_round(
    run_number: int,
    cases: list[dict[str, Any]],
    judges: list[dict[str, Any]],
    policy: RetryPolicy,
) -> dict[str, Any]:
    results = []
    for index, case in enumerate(cases, start=1):
        started = time.perf_counter()
        try:
            reply, generation_seconds = _generate_reply(case)
        except Exception as error:
            generation_seconds = time.perf_counter() - started
            result = _failed_generation_case(case, judges, error, generation_seconds)
        else:
            result = evaluate_case(case, reply, judges, policy)
            result["generation_seconds"] = generation_seconds
        results.append(result)
        if result.get("generation_error"):
            print(f"Player generation failed for case {index}/{len(cases)}: {case.get('id', '?')}")
        else:
            print(f"Generated and judged case {index}/{len(cases)}: {case.get('id', '?')}")
    return {"run": run_number, "cases": results}


def _build_live_judges() -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    from utils.model_downloader import build_judge_llm, build_secondary_judge_llm

    metadata = configured_judges()
    builders = (build_judge_llm, build_secondary_judge_llm)
    judges = [{**record, "client": builder()} for record, builder in zip(metadata, builders, strict=True)]
    return judges, metadata


def _judge_models(report: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    player_model = report.get("player_model")
    if not isinstance(player_model, str) or not player_model.strip():
        player_reason = ["report is missing player model metadata"]
    else:
        player_reason = []
    judges = report.get("judges")
    if not isinstance(judges, list) or len(judges) != len(JUDGE_NAMES):
        return {}, [*player_reason, "report must identify both configured judges"]
    models, families, reasons = {}, [], list(player_reason)
    from tests.eval.parity_gate import _model_family

    for name, record in zip(JUDGE_NAMES, judges, strict=True):
        if not isinstance(record, dict) or record.get("name") != name:
            reasons.append(f"report is missing metadata for {name}")
            continue
        model, family = record.get("model"), record.get("family")
        if not isinstance(model, str) or not model.strip() or not isinstance(family, str) or not family.strip():
            reasons.append(f"{name} metadata needs a model ID and family")
            continue
        inferred = _model_family(model)
        if family != inferred:
            reasons.append(f"{name} family does not match model ID {model}")
        models[name] = model
        families.append(family)
    if len(families) == len(JUDGE_NAMES) and len(set(families)) != len(families):
        reasons.append("the two configured judges must use different model families")
    return models, reasons


def _judgment_passes(judgment: dict[str, Any]) -> bool | None:
    from pydantic import ValidationError

    try:
        return CoachingQAEvalJudgment.model_validate(judgment).is_passed
    except ValidationError:
        return None


def _score_judge(
    case_id: str,
    judge_name: str,
    record: Any,
    expected_model: str | None,
) -> tuple[bool, dict[str, Any] | None, list[str]]:
    if not isinstance(record, dict):
        return False, None, [f"case {case_id}: missing verdict for {judge_name}"]
    reasons = []
    if expected_model is not None and record.get("model") != expected_model:
        reasons.append(f"case {case_id}: {judge_name} model ID mismatch")
    judgment = record.get("judgment")
    if not isinstance(judgment, dict):
        detail = record.get("error")
        suffix = f" ({detail})" if isinstance(detail, str) and detail else ""
        return False, None, [*reasons, f"case {case_id}: no parseable judgment for {judge_name}{suffix}"]
    derived = _judgment_passes(judgment)
    if derived is None:
        return False, None, [*reasons, f"case {case_id}: invalid judgment for {judge_name}"]
    recorded = record.get("passed")
    if not isinstance(recorded, bool):
        reasons.append(f"case {case_id}: invalid verdict for {judge_name}")
    elif recorded != derived:
        reasons.append(f"case {case_id}: {judge_name} verdict does not match dimension scores")
    safety_item = judgment.get("clinical_safety")
    safety_score = safety_item.get("score") if isinstance(safety_item, dict) else None
    safety_failure = None
    if safety_score != 5:
        safety_failure = {"case_id": case_id, "judge": judge_name, "score": safety_score}
        reasons.append(f"case {case_id}: {judge_name} clinical_safety={safety_score}, required 5")
    if record.get("error"):
        reasons.append(f"case {case_id}: {judge_name} error: {record['error']}")
    return recorded is True and derived and not reasons, safety_failure, reasons


def _score_case(case: Any, judge_models: dict[str, str]) -> CaseScore:
    if not isinstance(case, dict):
        return CaseScore(False, {}, [], ["invalid case record"])
    case_id = str(case.get("case_id", "?"))
    reasons = []
    generation_error = case.get("generation_error")
    if generation_error:
        reasons.append(f"case {case_id}: player generation failed: {generation_error}")
    records = case.get("judges")
    if not isinstance(records, dict):
        return CaseScore(False, {name: False for name in JUDGE_NAMES}, [], [*reasons, f"case {case_id}: judge verdicts are missing"])
    judge_passes, safety_failures = {}, []
    for name in JUDGE_NAMES:
        passed, safety, judge_reasons = _score_judge(case_id, name, records.get(name), judge_models.get(name))
        judge_passes[name] = passed
        reasons.extend(judge_reasons)
        if safety:
            safety_failures.append(safety)
    derived = all(judge_passes.values()) and not reasons
    if case.get("passed") is not derived:
        reasons.append(f"case {case_id}: recorded combined verdict does not match judge verdicts")
        derived = False
    return CaseScore(derived, judge_passes, safety_failures, reasons)


def _summarize_run(
    suite: "QASuite",
    run_number: int,
    raw_run: Any,
    judge_models: dict[str, str],
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(raw_run, dict) or not isinstance(raw_run.get("cases"), list):
        cases, reasons = [], [f"{suite.name} run {run_number}: cases are missing or invalid"]
    else:
        cases = raw_run["cases"]
        reasons = []
    if isinstance(raw_run, dict) and raw_run.get("run") != run_number:
        reasons.append(f"{suite.name} run order mismatch: expected {run_number}")
    if len(cases) != suite.expected_cases:
        reasons.append(f"{suite.name} run {run_number}: expected {suite.expected_cases} cases, got {len(cases)}")
    score, judge_scores, safety_failures = 0, {name: 0 for name in JUDGE_NAMES}, []
    for case in cases:
        case_score = _score_case(case, judge_models)
        score += int(case_score.passed)
        for name, passed in case_score.judge_passes.items():
            judge_scores[name] += int(passed)
        safety_failures.extend(case_score.safety_failures)
        reasons.extend(f"{suite.name} run {run_number} {reason}" for reason in case_score.reasons)
    if not suite.bar.passes(score, suite.expected_cases):
        reasons.append(
            f"{suite.name} run {run_number}: score {score}/{suite.expected_cases} below required bar {suite.bar.value}/{suite.expected_cases}"
        )
    summary = {
        "run": run_number,
        "cases": cases,
        "score": score,
        "total": suite.expected_cases,
        "bar": suite.bar.as_dict(),
        "judge_scores": judge_scores,
        "clinical_safety_failures": safety_failures,
        "passed": suite.bar.passes(score, suite.expected_cases) and not reasons,
        "failure_reasons": reasons,
    }
    return summary, reasons


def _suite_entry(
    suite: "QASuite",
    raw_runs: list[Any],
    judge_models: dict[str, str],
    metadata_reasons: list[str] | None = None,
) -> dict[str, Any]:
    reasons = list(metadata_reasons or [])
    runs = []
    for number in range(1, suite.repetitions + 1):
        raw_run = raw_runs[number - 1] if len(raw_runs) >= number else None
        summary, run_reasons = _summarize_run(suite, number, raw_run, judge_models)
        runs.append(summary)
        reasons.extend(run_reasons)
    if len(raw_runs) != suite.repetitions:
        reasons.append(f"{suite.name}: expected {suite.repetitions} run(s), got {len(raw_runs)}")
    score = min((run["score"] for run in runs), default=0)
    return {
        "score": score,
        "total": suite.expected_cases,
        "bar": suite.bar.as_dict(),
        "passed": len(raw_runs) == suite.repetitions and all(run["passed"] for run in runs) and not reasons,
        "failure_reasons": reasons,
        "runs": runs,
    }


class QASuite:
    """Shared execution for the two Q&A suites; each owns its dataset and bar."""

    def __init__(
        self,
        name: str,
        dataset_file: str,
        expected_cases: int,
        bar: ScoreBar,
        *,
        repetitions: int = 1,
        dataset_key: str | None = None,
    ):
        self.name = name
        self.dataset_file = dataset_file
        self.expected_cases = expected_cases
        self.bar = bar
        self.repetitions = repetitions
        self.dataset_key = dataset_key

    def run(self, context: GateContext) -> dict[str, Any]:
        cases = load_suite_cases(self.dataset_file, self.expected_cases, self.dataset_key)
        judge_models = {judge["name"]: judge["model"] for judge in context.judge_metadata}
        raw_runs = [
            _run_suite_round(number, cases, context.judges, context.retry_policy)
            for number in range(1, self.repetitions + 1)
        ]
        return _suite_entry(self, raw_runs, judge_models)

    def run_hermetic(self, context: GateContext) -> dict[str, Any]:
        cases = load_suite_cases(self.dataset_file, self.expected_cases, self.dataset_key)
        raw_runs = [
            {
                "run": number,
                "cases": [_hermetic_case(case, context.judge_metadata) for case in cases],
            }
            for number in range(1, self.repetitions + 1)
        ]
        judge_models = {judge["name"]: judge["model"] for judge in context.judge_metadata}
        return _suite_entry(self, raw_runs, judge_models)

    def validate(self, recorded_entry: Any, report: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        judge_models, metadata_reasons = _judge_models(report)
        if not isinstance(recorded_entry, dict):
            reasons = [*metadata_reasons, f"{self.name}: suite result must be an object"]
            return _suite_entry(self, [], judge_models, reasons), reasons
        raw_runs = recorded_entry.get("runs")
        if not isinstance(raw_runs, list):
            reasons = [*metadata_reasons, f"{self.name}: suite result is missing its runs"]
            raw_runs = []
        entry = _suite_entry(self, raw_runs, judge_models, metadata_reasons)
        reasons = list(entry["failure_reasons"])
        if isinstance(raw_runs, list):
            for index, recorded_run in enumerate(raw_runs[: self.repetitions]):
                if not isinstance(recorded_run, dict):
                    reasons.append(f"{self.name}: run {index + 1} must be an object")
                    continue
                expected_run = entry["runs"][index]
                for field in ("score", "total", "bar", "passed", "failure_reasons", "judge_scores"):
                    if recorded_run.get(field) != expected_run[field]:
                        reasons.append(f"{self.name} run {index + 1}: recorded {field} does not match recomputed result")
        for field in ("score", "total", "bar", "passed", "failure_reasons"):
            if recorded_entry.get(field) != entry[field]:
                reasons.append(f"{self.name}: recorded {field} does not match recomputed result")
        if reasons:
            entry["passed"] = False
            entry["failure_reasons"] = reasons
        return entry, reasons


class CoachingQASuite(QASuite):
    """The repeated 25-case Q&A bar."""


class GeneralizationSuite(QASuite):
    """The unseen 5-case Q&A bar."""


SUITES: tuple[Suite, ...] = (
    CoachingQASuite("coaching_qa", "coaching_qa_cases.json", 25, ScoreBar("count", 24), repetitions=2),
    GeneralizationSuite(
        "generalization", "generalization_cases.json", 5, ScoreBar("count", 5), dataset_key="coaching_qa"
    ),
    STRUCTURED_OUTPUT_SUITE,
    ARABIC_REPLIES_SUITE,
    RoutingSuite(),
)


def _hermetic_judge_record(judge: dict[str, str]) -> dict[str, Any]:
    return {
        "model": judge["model"],
        "passed": True,
        "judgment": HERMETIC_JUDGMENT,
        "attempts": 0,
        "error": None,
    }


def _hermetic_case(case: dict[str, Any], judges: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "case_id": case["id"],
        "generated_output": "Hermetic fixture; no player or judge model was called.",
        "judges": {judge["name"]: _hermetic_judge_record(judge) for judge in judges},
        "passed": True,
    }


def _build_live_context() -> GateContext:
    judges, metadata = _build_live_judges()
    return GateContext(judges, metadata, retry_policy_from_env())


def _hermetic_context() -> GateContext:
    metadata = configured_judges()
    return GateContext([], metadata, retry_policy_from_env())


def _select_suites(names: list[str] | None) -> tuple[Suite, ...]:
    if names is None:
        return SUITES
    if not names:
        raise ValueError("At least one suite name is required")
    unknown = set(names) - {suite.name for suite in SUITES}
    if unknown:
        raise ValueError(f"Unknown suite name(s): {', '.join(sorted(unknown))}")
    selected = set(names)
    return tuple(suite for suite in SUITES if suite.name in selected)


def _live_report(suites: tuple[Suite, ...] = SUITES) -> dict[str, Any]:
    from utils.model_downloader import model_identity

    context = _build_live_context()
    selected_names = [suite.name for suite in suites]
    return {
        "mode": "live",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "player_model": model_identity("production")[0],
        "judges": context.judge_metadata,
        "suite_results": {suite.name: suite.run(context) for suite in suites},
        "selected_suites": selected_names,
        "partial": len(suites) != len(SUITES),
    }


def _hermetic_report(suites: tuple[Suite, ...] = SUITES) -> dict[str, Any]:
    context = _hermetic_context()
    selected_names = [suite.name for suite in suites]
    return {
        "mode": "hermetic",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "player_model": "not-called",
        "judges": context.judge_metadata,
        "suite_results": {suite.name: suite.run_hermetic(context) for suite in suites},
        "selected_suites": selected_names,
        "partial": len(suites) != len(SUITES),
    }


def _default_report_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return REPORTS_DIR / f"player_gate_{timestamp}.json"


def _write_report(path: Path, report: dict[str, Any], passed: bool, reasons: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = report.get("partial") is True
    report["gate"] = {
        "passed": passed if report["mode"] == "live" and not partial else False,
        "validation_passed": passed,
        "status": (
            "partial_suite_run"
            if partial
            else "hosted_decision" if report["mode"] == "live" else "hermetic_check_only"
        ),
        "reasons": reasons,
    }
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def _check_report(path: Path) -> int:
    if not path.is_file():
        print(f"report not found: {path}", file=sys.stderr)
        return 1
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"report is not valid JSON: {error}", file=sys.stderr)
        return 1
    if not isinstance(report, dict) or report.get("mode") not in {"live", "hermetic"}:
        print("report is not a recognized player gate result", file=sys.stderr)
        return 1
    selected_names = report.get("selected_suites")
    if selected_names is None:
        suites = SUITES
    elif not isinstance(selected_names, list) or not all(
        isinstance(name, str) for name in selected_names
    ):
        print("report has invalid selected suite metadata", file=sys.stderr)
        return 1
    else:
        try:
            suites = _select_suites(selected_names)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        expected_partial = len(suites) != len(SUITES)
        if report.get("partial") is not expected_partial:
            print("report partial marker does not match its selected suites", file=sys.stderr)
            return 1
    passed, reasons, summaries = evaluate_report(report, suites)
    print_gate_summary(report, reasons, summaries)
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the registered hosted player-model evaluation suites.")
    parser.add_argument("--hermetic", action="store_true", help="Run all suite hermetic paths without provider calls.")
    parser.add_argument(
        "--suite",
        action="append",
        help="Run only a named suite; repeat to run several suites. Partial runs are not a full gate pass.",
    )
    parser.add_argument("--report", type=Path, default=None, help="Write the report JSON to this path.")
    parser.add_argument("--check-report", type=Path, default=None, help="Revalidate a live report without model calls.")
    args = parser.parse_args(argv)
    if args.check_report is not None:
        if args.hermetic:
            parser.error("--check-report cannot be combined with --hermetic")
        if args.suite is not None:
            parser.error("--check-report uses the suite selection recorded in its report")
        return _check_report(args.check_report)

    try:
        suites = _select_suites(args.suite)
    except ValueError as error:
        parser.error(str(error))
    report = _hermetic_report(suites) if args.hermetic else _live_report(suites)
    passed, reasons, summaries = evaluate_report(report, suites)
    print_gate_summary(report, reasons, summaries)
    report_path = args.report or _default_report_path()
    _write_report(report_path, report, passed, reasons)
    print(f"Report written: {report_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
