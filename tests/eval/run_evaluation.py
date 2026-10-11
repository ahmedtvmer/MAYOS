# tests/eval/run_evaluation.py
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

os.environ.setdefault("MODEL_DEVICE", "cpu")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

#: Lightweight modes must not import the model-heavy modules below. Short-circuit
#: here so `--check-report` (and a missing generalization dataset) stays instant.
if __name__ == "__main__" and "--check-report" in sys.argv:
    from tests.eval.parity_gate import _report_main

    sys.exit(_report_main(sys.argv[1:]))

if __name__ == "__main__" and "--generalize" in sys.argv:
    from tests.eval.parity_gate import generalization_dataset_path

    _gen_dataset = generalization_dataset_path()
    if not _gen_dataset.exists():
        print(f"Generalization dataset not found at: {_gen_dataset}", file=sys.stderr)
        sys.exit(1)

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from tests.eval.parity_gate import (
    GENERALIZATION_MODULE_COUNTS,
    GENERALIZATION_THRESHOLD,
    STANDARD_MODULE_COUNTS,
    STANDARD_THRESHOLD,
    datasets_dir,
    evaluate_parity_gate,
)
from tests.eval.rubrics import COACHING_QA_RUBRIC, DEBRIEF_RUBRIC
from tests.eval.schemas import (
    CoachingQAEvalJudgment,
    DebriefEvalJudgment,
)
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)

REPORTS_DIR = BASE_DIR / "tests" / "eval" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

T = TypeVar("T", bound=BaseModel)


def _eval_graph_config(db: Any, ledger: Any) -> dict[str, Any]:
    """Builds the explicit ``(ledger, store)`` LangGraph config production uses.

    Mirrors ``agent.assistant_graph.stream_assistant_turn`` (ADR 041): the graph
    reads no ambient store or thread-local ledger, so an eval opens its own handle.
    """
    return {"configurable": {"ledger": ledger, "store": db}}


def _invoke_assistant_graph(state: dict[str, Any]) -> dict[str, Any]:
    """Invokes the assistant graph under an opened ``(ledger, store)`` config."""
    from agent.assistant_graph import assistant_graph
    from database.database_manager import DatabaseManager

    db = DatabaseManager()
    try:
        with db.open_ledger(str(state.get("trainee_id", "eval_user"))) as ledger:
            return assistant_graph.invoke(state, config=_eval_graph_config(db, ledger))
    finally:
        db.catalog_conn.close()


def safe_invoke_judge(judge: Any, system_prompt: str, user_payload: str, schema: type[T]) -> T | None:
    structured_judge = judge.with_structured_output(schema, method="function_calling")
    try:
        return structured_judge.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_payload),
        ])
    except Exception as exc:
        logger.error(f"  ⚠️ Judgment Parsing Error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Phase 1: Candidate Generation (GPU: Qwen 2.5 3B)
# ---------------------------------------------------------------------------


def generate_qa_candidates(dataset_path: Path) -> list[dict[str, Any]]:
    from utils.text_scrubber import scrub_coach_output

    with open(dataset_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    candidates = []
    logger.info(f"\n⚡ [Phase 1: Generation] Coaching Q&A ({len(cases)} cases)...")
    logger.info("-" * 75)

    for case in cases:
        state = {
            "messages": [HumanMessage(content=case["query"])],
            "trainee_id": "eval_user",
            "coach_tone": "Direct, grounded, and pragmatic",
            "custom_instructions": "",
            "telemetry_context": case.get("telemetry", ""),
        }

        t0 = time.perf_counter()
        graph_output = _invoke_assistant_graph(state)
        raw_output = graph_output.get("response_content", "")
        cleaned_output = scrub_coach_output(raw_output)
        gen_time = time.perf_counter() - t0

        logger.info(f"  [Gen] Case {case['id']} ({gen_time:.2f}s)")
        candidates.append({
            "case": case,
            "generated_output": cleaned_output,
            "gen_time_s": gen_time,
        })

    return candidates


def generate_debrief_candidates(dataset_path: Path) -> list[dict[str, Any]]:
    from agent.debrief import generate_session_debrief

    with open(dataset_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    candidates = []
    logger.info(f"\n⚡ [Phase 1: Generation] Post-Workout Debriefs ({len(cases)} cases)...")
    logger.info("-" * 75)

    for case in cases:
        case_id = case.get("id") or case.get("case_id", "unknown")
        t0 = time.perf_counter()
        output = generate_session_debrief(
            split_name=case["split_name"],
            readiness=case["readiness"],
            session_notes=case.get("session_notes", ""),
            exercise_summaries=case["exercise_summaries"],
            profile={"coach_tone": "Direct, grounded, and pragmatic"},
            fatigue_info=case.get("fatigue_info"),
        )
        gen_time = time.perf_counter() - t0
        logger.info(f"  [Gen] Case {case_id} ({gen_time:.2f}s)")

        candidates.append({
            "case": case,
            "case_id": case_id,
            "generated_output": output,
            "gen_time_s": gen_time,
        })

    return candidates


def skip_onboarding_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserves onboarding case counts while the retired suite awaits #189."""
    reason = "removed by #188, cases deleted in #189"
    logger.info("Skipping %s onboarding eval cases: %s", len(cases), reason)
    return [
        {
            "case_id": case.get("id", case.get("case_id", "?")),
            "passed": False,
            "judgment": {"skipped": True},
            "skipped": True,
            "skip_reason": reason,
        }
        for case in cases
    ]


# ---------------------------------------------------------------------------
# Phase 2: Evaluation / Judgment
# ---------------------------------------------------------------------------


def judge_qa_candidates(judge: Any, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    logger.info(f"\n⚖️ [Phase 2: Judgment] Coaching Q&A ({len(candidates)} cases)...")
    logger.info("-" * 75)

    for item in candidates:
        case = item["case"]
        cleaned_output = item["generated_output"]
        gen_time = item["gen_time_s"]

        judge_input = (
            f"[TRAINEE CONTEXT]\n{case.get('telemetry', 'None')}\n\n"
            f"[USER QUERY]\n{case['query']}\n\n"
            f"[COACH RESPONSE]\n{cleaned_output}"
        )
        judgment = safe_invoke_judge(
            judge=judge,
            system_prompt=COACHING_QA_RUBRIC,
            user_payload=judge_input,
            schema=CoachingQAEvalJudgment,
        )

        passed = judgment.is_passed if judgment else False
        status_tag = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"[{status_tag}] Case {case['id']} (Gen: {gen_time:.2f}s)")

        if judgment and not judgment.is_passed:
            logger.warning(
                f"  Safety: {judgment.clinical_safety.score} | "
                f"Grounded: {judgment.groundedness.score} | "
                f"Budget: {judgment.structural_budget.score}"
            )
            logger.warning(f"  Rationale: {judgment.clinical_safety.rationale or judgment.structural_budget.rationale}")

        results.append({
            "case_id": case["id"],
            "query": case["query"],
            "generated_output": cleaned_output,
            "judgment": judgment.model_dump() if judgment else None,
            "passed": passed,
            "gen_time_s": gen_time,
            "error": None if judgment else "Schema extraction failed",
        })

    return results


def judge_debrief_candidates(judge: Any, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    logger.info(f"\n⚖️ [Phase 2: Judgment] Post-Workout Debriefs ({len(candidates)} cases)...")
    logger.info("-" * 75)

    for item in candidates:
        case = item["case"]
        case_id = item["case_id"]
        output = item["generated_output"]
        gen_time = item["gen_time_s"]

        judge_input = (
            f"[FATIGUE STATUS]\n{json.dumps(case.get('fatigue_info', {}))}\n\n"
            f"[EXERCISE SUMMARIES]\n{json.dumps(case['exercise_summaries'])}\n\n"
            f"[GENERATED DEBRIEF]\n{output}"
        )
        judgment = safe_invoke_judge(
            judge=judge,
            system_prompt=DEBRIEF_RUBRIC,
            user_payload=judge_input,
            schema=DebriefEvalJudgment,
        )

        passed = judgment.is_passed if judgment else False
        status_tag = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"[{status_tag}] Case {case_id} (Gen: {gen_time:.2f}s)")

        if judgment and not judgment.is_passed:
            logger.warning(
                f"  Deload: {judgment.deload_compliance.score} | "
                f"Metrics: {judgment.metric_alignment.score}"
            )

        results.append({
            "case_id": case_id,
            "split_name": case.get("split_name"),
            "generated_output": output,
            "judgment": judgment.model_dump() if judgment else None,
            "passed": passed,
            "gen_time_s": gen_time,
            "error": None if judgment else "Schema extraction failed",
        })

    return results


# ---------------------------------------------------------------------------
# Backward-Compatible Helper Functions
# ---------------------------------------------------------------------------


def evaluate_qa(judge: Any, dataset_path: Path) -> list[dict[str, Any]]:
    candidates = generate_qa_candidates(dataset_path)
    return judge_qa_candidates(judge, candidates)


def evaluate_debrief(judge: Any, dataset_path: Path) -> list[dict[str, Any]]:
    candidates = generate_debrief_candidates(dataset_path)
    return judge_debrief_candidates(judge, candidates)


# ---------------------------------------------------------------------------
# Hosted Evaluation Runner
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Myos hosted LLM evaluation suite")
    parser.add_argument("--target", choices=["qa", "debrief", "onboarding", "all"], default="all")
    parser.add_argument(
        "--generalize", action="store_true", help="Run 15 unseen generalization cases across all modules"
    )
    parser.add_argument(
        "--phase",
        choices=["all", "generate", "judge"],
        default="all",
        help="Evaluation phase to execute: 'generate', 'judge', or 'all'",
    )
    args = parser.parse_args()

    report_payload = {"timestamp": datetime.now().isoformat(), "runs": {}}
    eval_datasets = datasets_dir()

    cached_qa: list[dict[str, Any]] = []
    cached_debrief: list[dict[str, Any]] = []
    cached_onboarding: list[dict[str, Any]] = []

    if args.generalize:
        gen_file = eval_datasets / "generalization_cases.json"
        if not gen_file.exists():
            # Never report success when the gate cannot run.
            logger.error(f"Generalization dataset not found at: {gen_file}")
            sys.exit(1)

        with open(gen_file, "r", encoding="utf-8") as f:
            gen_data = json.load(f)
        cached_onboarding = skip_onboarding_cases(gen_data.get("onboarding", []))

        logger.info("\n" + "=" * 75)
        logger.info("🚀 RUNNING HOSTED GENERALIZATION EVALUATION (15 UNSEEN CASES)")
        logger.info("=" * 75)

        qa_tmp = eval_datasets / "_tmp_gen_qa.json"
        deb_tmp = eval_datasets / "_tmp_gen_deb.json"

        try:
            qa_tmp.write_text(json.dumps(gen_data.get("coaching_qa", [])), encoding="utf-8")
            deb_tmp.write_text(json.dumps(gen_data.get("debrief", [])), encoding="utf-8")

            # --- PHASE 1: GENERATION ---
            if args.phase in ("all", "generate"):
                cached_qa = generate_qa_candidates(qa_tmp)
                cached_debrief = generate_debrief_candidates(deb_tmp)

                logger.info("\nGeneration complete; starting hosted judge evaluation...")

            # --- PHASE 2: JUDGMENT ---
            if args.phase in ("all", "judge"):
                judge = None
                if cached_qa or cached_debrief:
                    from utils.model_downloader import get_judge_llm

                    judge = get_judge_llm()

                qa_results = judge_qa_candidates(judge, cached_qa)
                qa_pass = (sum(1 for r in qa_results if r["passed"]) / len(qa_results)) * 100 if qa_results else 0.0
                logger.info(
                    f"\n📊 Generalization QA Pass Rate: {qa_pass:.1f}% "
                    f"({sum(1 for r in qa_results if r['passed'])}/{len(qa_results)})"
                )
                report_payload["runs"]["coaching_qa"] = qa_results

                debrief_results = judge_debrief_candidates(judge, cached_debrief)
                debrief_pass = (
                    (sum(1 for r in debrief_results if r["passed"]) / len(debrief_results)) * 100
                    if debrief_results
                    else 0.0
                )
                logger.info(
                    f"\n📊 Generalization Debrief Pass Rate: {debrief_pass:.1f}% "
                    f"({sum(1 for r in debrief_results if r['passed'])}/{len(debrief_results)})"
                )
                report_payload["runs"]["debrief"] = debrief_results

                onboarding_results = cached_onboarding
                onboarding_pass = (
                    (sum(1 for r in onboarding_results if r["passed"]) / len(onboarding_results)) * 100
                    if onboarding_results
                    else 0.0
                )
                logger.info(
                    f"\n📊 Generalization Onboarding Pass Rate: {onboarding_pass:.1f}% "
                    f"({sum(1 for r in onboarding_results if r['passed'])}/{len(onboarding_results)})"
                )
                report_payload["runs"]["onboarding"] = onboarding_results

                total_cases = len(qa_results) + len(debrief_results) + len(onboarding_results)
                total_passed = (
                    sum(1 for r in qa_results if r["passed"])
                    + sum(1 for r in debrief_results if r["passed"])
                    + sum(1 for r in onboarding_results if r["passed"])
                )
                total_pct = (total_passed / total_cases * 100) if total_cases > 0 else 0.0
                logger.info("\n" + "=" * 75)
                logger.info(f"🎯 FINAL GENERALIZATION SCORE: {total_passed}/{total_cases} ({total_pct:.1f}%)")
                logger.info("=" * 75)


        finally:
            qa_tmp.unlink(missing_ok=True)
            deb_tmp.unlink(missing_ok=True)

    else:
        # Standard Evaluation Suite (65 cases)
        # --- PHASE 1: GENERATION ---
        if args.phase in ("all", "generate"):
            if args.target in ("qa", "all"):
                qa_data = eval_datasets / "coaching_qa_cases.json"
                cached_qa = generate_qa_candidates(qa_data)

            if args.target in ("debrief", "all"):
                debrief_data = eval_datasets / "debrief_cases.json"
                cached_debrief = generate_debrief_candidates(debrief_data)

            if args.target in ("onboarding", "all"):
                onboarding_data = eval_datasets / "onboarding_cases.json"
                with open(onboarding_data, "r", encoding="utf-8") as f:
                    cached_onboarding = skip_onboarding_cases(json.load(f))

            logger.info("\nGeneration complete; starting hosted judge evaluation...")

        # --- PHASE 2: JUDGMENT ---
        if args.phase in ("all", "judge"):
            judge = None
            if cached_qa or cached_debrief:
                from utils.model_downloader import get_judge_llm

                judge = get_judge_llm()

            if cached_qa:
                qa_results = judge_qa_candidates(judge, cached_qa)
                qa_pass = (sum(1 for r in qa_results if r["passed"]) / len(qa_results)) * 100 if qa_results else 0.0
                logger.info(
                    f"\n📊 Coaching Q&A Pass Rate: {qa_pass:.1f}% "
                    f"({sum(1 for r in qa_results if r['passed'])}/{len(qa_results)})"
                )
                report_payload["runs"]["coaching_qa"] = qa_results

            if cached_debrief:
                debrief_results = judge_debrief_candidates(judge, cached_debrief)
                debrief_pass = (
                    (sum(1 for r in debrief_results if r["passed"]) / len(debrief_results)) * 100
                    if debrief_results
                    else 0.0
                )
                logger.info(
                    f"\n📊 Debrief Pass Rate: {debrief_pass:.1f}% "
                    f"({sum(1 for r in debrief_results if r['passed'])}/{len(debrief_results)})"
                )
                report_payload["runs"]["debrief"] = debrief_results

            if cached_onboarding:
                onboarding_results = cached_onboarding
                onboarding_pass = (
                    (sum(1 for r in onboarding_results if r["passed"]) / len(onboarding_results)) * 100
                    if onboarding_results
                    else 0.0
                )
                logger.info(
                    f"\n📊 Onboarding Pass Rate: {onboarding_pass:.1f}% "
                    f"({sum(1 for r in onboarding_results if r['passed'])}/{len(onboarding_results)})"
                )
                report_payload["runs"]["onboarding"] = onboarding_results


    gate_ok = True
    if args.phase in ("all", "judge"):
        if args.generalize:
            expected_counts, threshold = GENERALIZATION_MODULE_COUNTS, GENERALIZATION_THRESHOLD
        elif args.target == "all":
            expected_counts, threshold = STANDARD_MODULE_COUNTS, STANDARD_THRESHOLD
        else:
            # A partial --target run is a development slice, not the parity gate.
            expected_counts, threshold = None, None
            logger.info("ℹ️ Parity gate not evaluated for partial --target '%s'.", args.target)

        if expected_counts is not None:
            gate_ok, reasons, stats = evaluate_parity_gate(
                report_payload.get("runs", {}), expected_counts, threshold
            )
            report_payload["gate"] = {
                "passed": gate_ok,
                "threshold": threshold,
                "expected": stats["expected"],
                "total_judged": stats["total"],
                "passed_cases": stats["passed"],
                "clinical_safety_failures": stats["clinical_safety_failures"],
                "unparseable": stats["unparseable"],
                "counts": stats["counts"],
                "reasons": reasons,
            }
            logger.info("\n" + "=" * 75)
            logger.info(
                f"🚦 PARITY GATE: {'PASSED' if gate_ok else 'FAILED'} "
                f"({stats['passed']}/{stats['expected']}, required {threshold}/{stats['expected']}); "
                f"clinical_safety failures={len(stats['clinical_safety_failures'])}"
            )
            for reason in reasons:
                logger.error(f"  ✗ {reason}")
            logger.info("=" * 75)

    if args.phase in ("all", "judge") and report_payload.get("runs"):
        prefix = "gen_" if args.generalize else ""
        out_file = REPORTS_DIR / f"{prefix}eval_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out_file.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
        logger.info(f"\n📁 Benchmark artifact written to: {out_file}")

    if not gate_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
