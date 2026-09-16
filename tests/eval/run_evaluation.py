# tests/eval/run_evaluation.py
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

os.environ.setdefault("EMBEDDING_DEVICE", "cpu")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from agent.assistant_graph import assistant_graph
from agent.debrief import generate_session_debrief
from agent.onboarding_graph import onboarding_graph
from tests.eval.rubrics import COACHING_QA_RUBRIC, DEBRIEF_RUBRIC, ONBOARDING_RUBRIC
from tests.eval.schemas import (
    CoachingQAEvalJudgment,
    DebriefEvalJudgment,
    OnboardingExtractionJudgment,
)
from utils.logger import MyosLogger
from utils.model_downloader import (
    get_judge_llm,
    unload_judge_llm,
    unload_llm,
)
from utils.text_scrubber import scrub_coach_output

logger = MyosLogger().get_logger(__name__)

REPORTS_DIR = BASE_DIR / "tests" / "eval" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

T = TypeVar("T", bound=BaseModel)


def safe_invoke_judge(judge: Any, system_prompt: str, user_payload: str, schema: type[T]) -> T | None:
    structured_judge = judge.with_structured_output(schema)
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
        graph_output = assistant_graph.invoke(state)
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


def generate_onboarding_candidates(dataset_path: Path) -> list[dict[str, Any]]:
    with open(dataset_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    candidates = []
    logger.info(f"\n⚡ [Phase 1: Generation] Onboarding Intake Graph ({len(cases)} cases)...")
    logger.info("-" * 75)

    for case in cases:
        step = case["step"]
        initial_profile = {
            "proportions": "balanced",
            "gender": "male",
            "age": 25,
            "weight_kg": 80.0,
            "height_cm": 180.0,
        } if step > 1 else {}

        if step > 2:
            initial_profile.update({
                "current_goal": "Hypertrophy",
                "long_term_goal": "Longevity",
                "weekly_frequency": 4,
                "training_age_years": 2.0,
                "rep_preference": "balanced",
            })

        state = {
            "messages": [HumanMessage(content=case["user_input"])],
            "trainee_id": f"eval_user_{case['id']}",
            "intake_step": step,
            "is_complete": False,
            "profile_data": initial_profile,
        }

        t0 = time.perf_counter()
        result_state = onboarding_graph.invoke(state)
        gen_time = time.perf_counter() - t0

        new_step = result_state.get("intake_step", step)
        is_complete = result_state.get("is_complete", False)
        profile = result_state.get("profile_data", {})
        last_msg = result_state["messages"][-1].content if result_state.get("messages") else ""

        advanced = (new_step > step) or is_complete
        expected_adv = (case["expected_action"] == "advance")
        structural_pass = (advanced == expected_adv)

        if not advanced and case["expected_action"] == "reject":
            structural_pass = "invalid response" in last_msg.lower() or "please provide" in last_msg.lower()

        step_fields = {
            1: ["proportions", "gender", "age", "weight_kg", "height_cm"],
            2: ["current_goal", "long_term_goal", "weekly_frequency", "training_age_years", "rep_preference"],
            3: ["equipment_access", "injuries_or_limitations", "stress_and_sleep"],
        }[step]

        delta_profile = {k: v for k, v in profile.items() if k in step_fields}
        logger.info(f"  [Gen] Case {case['id']} ({gen_time:.2f}s) | Step {step} -> {new_step}")

        candidates.append({
            "case": case,
            "step": step,
            "user_input": case["user_input"],
            "expected_action": case["expected_action"],
            "advanced": advanced,
            "structural_pass": structural_pass,
            "delta_profile": delta_profile,
            "last_msg": last_msg,
            "profile": profile,
            "gen_time_s": gen_time,
        })

    return candidates


# ---------------------------------------------------------------------------
# Phase 2: Evaluation / Judgment (GPU/CPU: Qwen 2.5 9B)
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


def judge_onboarding_candidates(judge: Any, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    logger.info(f"\n⚖️ [Phase 2: Judgment] Onboarding Intake Graph ({len(candidates)} cases)...")
    logger.info("-" * 75)

    for item in candidates:
        case = item["case"]
        step = item["step"]
        advanced = item["advanced"]
        structural_pass = item["structural_pass"]
        delta_profile = item["delta_profile"]
        last_msg = item["last_msg"]
        profile = item["profile"]
        gen_time = item["gen_time_s"]
        expected_action = item["expected_action"]

        judge_input = (
            f"[STEP]: {step}\n"
            f"[TRAINEE INPUT]\n{item['user_input']}\n\n"
            f"[GRAPH ACTION]\n{'ADVANCED' if advanced else 'REJECTED'}\n\n"
            f"[BOT RESPONSE]\n{last_msg}\n\n"
            f"[EXTRACTED DELTA PROFILE]\n{json.dumps(delta_profile)}"
        )

        judgment = safe_invoke_judge(
            judge=judge,
            system_prompt=ONBOARDING_RUBRIC,
            user_payload=judge_input,
            schema=OnboardingExtractionJudgment,
        )

        if expected_action == "reject":
            judge_pass = judgment.off_topic_accuracy.passes(4) if judgment else True
            passed = structural_pass and judge_pass
        else:
            judge_pass = judgment.is_passed if judgment else False
            passed = structural_pass and judge_pass

        status_tag = "✅ PASS" if passed else "❌ FAIL"
        logger.info(
            f"[{status_tag}] Case {case['id']} (Gen: {gen_time:.2f}s) | "
            f"Expected: {expected_action} | Got: {'advance' if advanced else 'reject'}"
        )

        if not passed:
            if not structural_pass:
                logger.warning(f"  ❌ Transition Mismatch: Expected {expected_action}, but got advanced={advanced}")
                logger.warning(f"  Last Message: {last_msg[:90]}...")
            if judgment and not judge_pass:
                logger.warning(
                    f"  Extraction: {judgment.extraction_fidelity.score} | "
                    f"Off-Topic: {judgment.off_topic_accuracy.score}"
                )
                logger.warning(
                    f"  Rationale: {judgment.extraction_fidelity.rationale or judgment.off_topic_accuracy.rationale}"
                )

        results.append({
            "case_id": case["id"],
            "input": item["user_input"],
            "bot_response": last_msg,
            "extracted_profile": profile,
            "advanced": advanced,
            "structural_pass": structural_pass,
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


def evaluate_onboarding(judge: Any, dataset_path: Path) -> list[dict[str, Any]]:
    candidates = generate_onboarding_candidates(dataset_path)
    return judge_onboarding_candidates(judge, candidates)


# ---------------------------------------------------------------------------
# Two-Phase CLI Runner
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Myos LLM-as-a-Judge Offline Evaluation Suite (Two-Phase GPU)")
    parser.add_argument("--target", choices=["qa", "debrief", "onboarding", "all"], default="all")
    parser.add_argument(
        "--generalize", action="store_true", help="Run 15 unseen generalization cases across all modules"
    )
    parser.add_argument(
        "--gpu-layers", type=int, default=10, help="Layers to offload to GPU for the Judge LLM (default: 10)"
    )
    parser.add_argument(
        "--main-gpu-layers",
        type=int,
        default=None,
        help="Layers to offload to GPU for the Main LLM (default: env N_GPU_LAYERS or -1)",
    )
    parser.add_argument(
        "--phase",
        choices=["all", "generate", "judge"],
        default="all",
        help="Evaluation phase to execute: 'generate', 'judge', or 'all' (default: all)",
    )
    args = parser.parse_args()

    # Configure Main LLM GPU layers for Phase 1
    if args.main_gpu_layers is not None:
        os.environ["N_GPU_LAYERS"] = str(args.main_gpu_layers)
    elif "N_GPU_LAYERS" not in os.environ:
        os.environ["N_GPU_LAYERS"] = "-1"

    report_payload = {"timestamp": datetime.now().isoformat(), "runs": {}}
    datasets_dir = BASE_DIR / "tests" / "eval" / "datasets"

    cached_qa: list[dict[str, Any]] = []
    cached_debrief: list[dict[str, Any]] = []
    cached_onboarding: list[dict[str, Any]] = []

    if args.generalize:
        gen_file = datasets_dir / "generalization_cases.json"
        if not gen_file.exists():
            logger.error(f"Generalization dataset not found at: {gen_file}")
            return

        with open(gen_file, "r", encoding="utf-8") as f:
            gen_data = json.load(f)

        logger.info("\n" + "=" * 75)
        logger.info("🚀 RUNNING GENERALIZATION EVALUATION (15 UNSEEN CASES - TWO-PHASE GPU)")
        logger.info("=" * 75)

        qa_tmp = datasets_dir / "_tmp_gen_qa.json"
        deb_tmp = datasets_dir / "_tmp_gen_deb.json"
        onb_tmp = datasets_dir / "_tmp_gen_onb.json"

        try:
            qa_tmp.write_text(json.dumps(gen_data.get("coaching_qa", [])), encoding="utf-8")
            deb_tmp.write_text(json.dumps(gen_data.get("debrief", [])), encoding="utf-8")
            onb_tmp.write_text(json.dumps(gen_data.get("onboarding", [])), encoding="utf-8")

            # --- PHASE 1: GENERATION ---
            if args.phase in ("all", "generate"):
                cached_qa = generate_qa_candidates(qa_tmp)
                cached_debrief = generate_debrief_candidates(deb_tmp)
                cached_onboarding = generate_onboarding_candidates(onb_tmp)

                logger.info("\n🧹 Releasing Main LLM from VRAM before initializing Judge...")
                unload_llm()

            # --- PHASE 2: JUDGMENT ---
            if args.phase in ("all", "judge"):
                judge = get_judge_llm(n_gpu_layers=args.gpu_layers)

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

                onboarding_results = judge_onboarding_candidates(judge, cached_onboarding)
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

                unload_judge_llm()

        finally:
            qa_tmp.unlink(missing_ok=True)
            deb_tmp.unlink(missing_ok=True)
            onb_tmp.unlink(missing_ok=True)

    else:
        # Standard Evaluation Suite (65 cases)
        # --- PHASE 1: GENERATION ---
        if args.phase in ("all", "generate"):
            if args.target in ("qa", "all"):
                qa_data = datasets_dir / "coaching_qa_cases.json"
                cached_qa = generate_qa_candidates(qa_data)

            if args.target in ("debrief", "all"):
                debrief_data = datasets_dir / "debrief_cases.json"
                cached_debrief = generate_debrief_candidates(debrief_data)

            if args.target in ("onboarding", "all"):
                onboarding_data = datasets_dir / "onboarding_cases.json"
                cached_onboarding = generate_onboarding_candidates(onboarding_data)

            logger.info("\n🧹 Releasing Main LLM from VRAM before initializing Judge...")
            unload_llm()

        # --- PHASE 2: JUDGMENT ---
        if args.phase in ("all", "judge"):
            judge = get_judge_llm(n_gpu_layers=args.gpu_layers)

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
                onboarding_results = judge_onboarding_candidates(judge, cached_onboarding)
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

            unload_judge_llm()

    if args.phase in ("all", "judge") and report_payload.get("runs"):
        prefix = "gen_" if args.generalize else ""
        out_file = REPORTS_DIR / f"{prefix}eval_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out_file.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
        logger.info(f"\n📁 Benchmark artifact written to: {out_file}")


if __name__ == "__main__":
    main()
