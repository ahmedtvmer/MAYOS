# tests/eval/run_evaluation.py
import os

os.environ["N_GPU_LAYERS"] = "0"
os.environ["EMBEDDING_DEVICE"] = "cpu"

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from agent.assistant_graph import build_prompt_payload
from agent.debrief import generate_session_debrief
from tests.eval.rubrics import COACHING_QA_RUBRIC, DEBRIEF_RUBRIC
from tests.eval.schemas import CoachingQAEvalJudgment, DebriefEvalJudgment
from utils.model_downloader import get_judge_llm, llm
from utils.text_scrubber import scrub_coach_output
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)

REPORTS_DIR = BASE_DIR / "tests" / "eval" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

T = TypeVar("T", bound=BaseModel)


def safe_invoke_judge(judge: Any, system_prompt: str, user_payload: str, schema: type[T]) -> T | None:
    """Attempts structured invocation with graceful exception handling."""
    structured_judge = judge.with_structured_output(schema)
    try:
        return structured_judge.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_payload),
        ])
    except Exception as exc:
        logger.error(f"  ⚠️ Judgment Parsing Error: {exc}")
        return None


def evaluate_qa(judge: Any, dataset_path: Path):
    with open(dataset_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    results = []
    logger.info(f"\n⚡ Evaluating Coaching Q&A ({len(cases)} cases)...")
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
        payload = build_prompt_payload(state)
        raw_output = llm.invoke(payload).content
        cleaned_output = scrub_coach_output(raw_output)
        gen_time = time.perf_counter() - t0

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
        logger.info(f"[{status_tag}] Case {case['id']} ({gen_time:.2f}s)")

        if judgment and not judgment.is_passed:
            logger.warning(
                f"  Safety: {judgment.clinical_safety.score} | "
                f"Grounded: {judgment.groundedness.score} | "
                f"Budget: {judgment.structural_budget.score}"
            )
            logger.warning(f"  Rationale: {judgment.clinical_safety.rationale or judgment.groundedness.rationale}")

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


def evaluate_debrief(judge: Any, dataset_path: Path):
    with open(dataset_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    results = []
    logger.info(f"\n⚡ Evaluating Post-Workout Debriefs ({len(cases)} cases)...")
    logger.info("-" * 75)

    for case in cases:
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
        logger.info(f"[{status_tag}] Case {case['id']} ({gen_time:.2f}s)")

        if judgment and not judgment.is_passed:
            logger.warning(
                f"  Deload: {judgment.deload_compliance.score} | "
                f"Metrics: {judgment.metric_alignment.score}"
            )

        results.append({
            "case_id": case["id"],
            "generated_output": output,
            "judgment": judgment.model_dump() if judgment else None,
            "passed": passed,
            "gen_time_s": gen_time,
            "error": None if judgment else "Schema extraction failed",
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="Myos LLM-as-a-Judge Offline Evaluation Suite")
    parser.add_argument("--target", choices=["qa", "debrief", "all"], default="all")
    parser.add_argument("--gpu-layers", type=int, default=10)
    args = parser.parse_args()

    judge = get_judge_llm(n_gpu_layers=args.gpu_layers)
    report_payload = {"timestamp": datetime.now().isoformat(), "runs": {}}

    if args.target in ("qa", "all"):
        qa_data = BASE_DIR / "tests" / "eval" / "datasets" / "coaching_qa_cases.json"
        qa_results = evaluate_qa(judge, qa_data)
        qa_pass = (sum(1 for r in qa_results if r["passed"]) / len(qa_results)) * 100
        logger.info(f"\n📊 Coaching Q&A Pass Rate: {qa_pass:.1f}% ({sum(1 for r in qa_results if r['passed'])}/{len(qa_results)})")
        report_payload["runs"]["coaching_qa"] = qa_results

    if args.target in ("debrief", "all"):
        debrief_data = BASE_DIR / "tests" / "eval" / "datasets" / "debrief_cases.json"
        debrief_results = evaluate_debrief(judge, debrief_data)
        debrief_pass = (sum(1 for r in debrief_results if r["passed"]) / len(debrief_results)) * 100
        logger.info(f"\n📊 Debrief Pass Rate: {debrief_pass:.1f}% ({sum(1 for r in debrief_results if r['passed'])}/{len(debrief_results)})")
        report_payload["runs"]["debrief"] = debrief_results

    out_file = REPORTS_DIR / f"eval_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_file.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    logger.info(f"\n📁 Benchmark artifact written to: {out_file}")


if __name__ == "__main__":
    main()