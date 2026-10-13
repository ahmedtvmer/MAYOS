"""Arabic player replies scored for language and reviewed Egyptian register."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from tests.eval.parity_gate import ScoreBar, call_with_retry, _model_family
from tests.eval.suites.common import (
    empty_suite_summary,
    isolated_catalog_store,
    load_case_dataset,
    load_case_group,
    suite_summary,
)

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "tests/eval/datasets/arabic_reviewed_cases.json"
REVIEW_DIR = ROOT / "tests/eval/datasets/arabic_judge_review"
REVIEW_FILE = REVIEW_DIR / "REVIEW.json"
SAMPLE_FILE = REVIEW_DIR / "sample.json"
ARABIC_BAR = ScoreBar("percent", 90)
JUDGE_NAMES = ("judge_1", "judge_2")

ARABIC_DIALECT_RUBRIC = """Classify the register of the assistant reply itself, not the user's message.
Return exactly one label: egyptian, standard, or mixed.

Egyptian means polite everyday Egyptian Arabic, with Egyptian wording or grammar
such as عايز, إزاي, كده, ده/دي, or خليك. Standard means predominantly Modern
Standard Arabic, such as ينبغي, يمكنك, or يرجى. Label the reply by its DOMINANT register. Mixed means neither register clearly
dominates, or there is too little Arabic to identify one. Neutral words shared by
both registers (such as برنامج, تمام, أقدر, تمرين), English gym terms, exercise
names, RIR, and kg are not standard-Arabic markers. Do not judge coaching accuracy or safety.
Give one short rationale citing words from the reply."""


class ArabicDialectJudgment(BaseModel):
    label: Literal["egyptian", "standard", "mixed"]
    rationale: str = Field(min_length=1, max_length=300)


class ArabicReplySuite:
    name = "arabic_replies"

    def run(self, context: Any) -> dict[str, Any]:
        from tests.eval.run_arabic_evaluation import load_scenarios, validate_scenarios
        from utils.model_downloader import model_identity

        cases = _load_cases()
        scenario_data = load_scenarios()
        validate_scenarios(cases, scenario_data)
        with isolated_catalog_store() as store:
            records = [
                _evaluate_reply_case(case, scenario_data["cases"], context, store)
                for case in cases
            ]
        return _summarize(records, cases, context.judge_metadata, model_identity("production")[0])

    def run_hermetic(self, context: Any) -> dict[str, Any]:
        cases = _load_cases()
        records = [
            _hermetic_reply(case, context.judge_metadata)
            for case in cases
        ]
        return _summarize(records, cases, context.judge_metadata, "not-called")

    def validate(self, recorded_entry: Any, report: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        cases = _load_cases()
        records = recorded_entry.get("cases") if isinstance(recorded_entry, dict) else None
        if not isinstance(records, list):
            reasons = ["arabic_replies: cases are missing or invalid"]
            return _empty_summary(reasons), reasons
        judge_models, metadata_reasons = _judge_models(report)
        summary = _summarize(
            records,
            cases,
            report.get("judges", []),
            report.get("player_model"),
            judge_models=judge_models,
        )
        reasons = [*metadata_reasons, *summary["failure_reasons"]]
        if recorded_entry.get("cases") != summary["cases"]:
            reasons.append("arabic_replies: recorded cases do not match recomputed results")
        if reasons:
            summary["passed"] = False
            summary["failure_reasons"] = reasons
        return summary, reasons


def _load_cases() -> list[dict[str, Any]]:
    from tests.eval.run_arabic_evaluation import ARABIC_SCRIPT

    payload = load_case_dataset(DATASET)
    cases = load_case_group(
        payload,
        "player_messages",
        "Arabic reply suite",
        {"status": "owner_reviewed"},
    )
    if any(not ARABIC_SCRIPT.search(case.get("text", "")) for case in cases):
        raise ValueError("Arabic reply suite contains a message without Arabic script.")
    return cases


def _evaluate_reply_case(
    case: dict[str, Any], scenarios: dict[str, Any], context: Any, store: Any
) -> dict[str, Any]:
    from tests.eval.parity_gate import _safe_error_message
    from utils.text_scrubber import scrub_coach_output

    try:
        scenario = scenarios[case["id"]]
        reply = _generate_reply(case, scenario, store, scrub_coach_output)
        record = _score_reply(case, reply)
        record["judges"] = _judge_reply(case, reply, context.judges, context.retry_policy)
        return record
    except Exception as error:
        return _failed_reply(case, _safe_error_message(error))


def _generate_reply(case: dict[str, Any], scenario: dict[str, Any], store: Any, scrub_output: Any) -> str:
    from langchain_core.messages import HumanMessage
    from tests.eval.run_arabic_evaluation import seed_arabic_player_context

    trainee_id = f"eval_ar_{case['id']}"
    state = {
        "messages": [HumanMessage(content=case["text"])],
        "trainee_id": trainee_id,
        "player_account_id": None,
        "coach_tone": "Direct, grounded, and pragmatic",
        "custom_instructions": "",
        "telemetry_context": "",
    }
    with store.open_ledger(trainee_id) as ledger:
        seed_arabic_player_context(store, ledger, scenario)
        graph_output = _invoke_with_training_ledger(state, ledger, store)
    return scrub_output(graph_output.get("response_content", ""))


def _invoke_with_training_ledger(state: dict[str, Any], ledger: Any, store: Any) -> dict[str, Any]:
    from agent.assistant_graph import assistant_graph

    config = {"configurable": {"ledger": ledger, "store": store}}
    return assistant_graph.invoke(state, config=config)


def _mostly_arabic(case: dict[str, Any], reply: str) -> tuple[bool, float, dict[str, Any]]:
    from tests.eval.run_arabic_evaluation import score_arabic_reply_language

    result = score_arabic_reply_language(case["text"], reply, case["launch_response_kind"])
    return result["mostly_arabic"], result["arabic_letter_share"], result["arabic_quality"]


def _expected_register(case: dict[str, Any]) -> str:
    return "egyptian" if case["launch_response_kind"] == "normal_assistant" else "standard"


def _score_reply(case: dict[str, Any], reply: str) -> dict[str, Any]:
    mostly, share, quality = _mostly_arabic(case, reply)
    return {
        "case_id": case["id"],
        "query": case["text"],
        "generated_output": reply,
        "expected_register": _expected_register(case),
        "mostly_arabic": mostly,
        "arabic_letter_share": round(share, 4),
        "arabic_quality": quality,
        "generation_error": None,
    }


def _judge_messages(reply: str) -> list[Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    return [
        SystemMessage(content=ARABIC_DIALECT_RUBRIC),
        HumanMessage(content=f"[ASSISTANT REPLY]\n{reply}"),
    ]


def _judge_reply(case: dict[str, Any], reply: str, judges: list[dict[str, Any]], policy: Any) -> dict[str, Any]:
    records = {}
    for judge in judges:
        def invoke():
            structured = judge["client"].with_structured_output(ArabicDialectJudgment, method="function_calling")
            return structured.invoke(_judge_messages(reply))

        call = call_with_retry(invoke, policy)
        judgment = call.response
        records[judge["name"]] = {
            "model": judge["model"],
            "label": judgment.label if isinstance(judgment, ArabicDialectJudgment) else None,
            "rationale": judgment.rationale if isinstance(judgment, ArabicDialectJudgment) else None,
            "attempts": call.attempts,
            "error": call.error,
        }
    return records


def _failed_reply(case: dict[str, Any], error: str) -> dict[str, Any]:
    failed = _score_reply(case, "")
    failed.update(
        {
            "generated_output": None,
            "mostly_arabic": False,
            "generation_error": error,
            "judges": {
                name: {"model": None, "label": None, "rationale": None, "attempts": 0, "error": error}
                for name in JUDGE_NAMES
            },
        }
    )
    return failed


def _hermetic_reply(case: dict[str, Any], judge_metadata: list[dict[str, str]]) -> dict[str, Any]:
    is_egyptian = _expected_register(case) == "egyptian"
    reply = (
        "تمام، خلّينا نثبت السيتات ونزوّد العدّات بالتدريج."
        if is_egyptian
        else "ينبغي إيقاف التمرين وطلب تقييم مختص عند استمرار الألم."
    )
    record = _score_reply(case, reply)
    record["judges"] = {
        judge["name"]: {
            "model": judge["model"],
            "label": "egyptian" if is_egyptian else "standard",
            "rationale": "Hermetic fixture dialect label.",
            "attempts": 0,
            "error": None,
        }
        for judge in judge_metadata
    }
    return record


def _judge_models(report: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    judges = report.get("judges")
    if not isinstance(judges, list) or len(judges) != len(JUDGE_NAMES):
        return {}, ["arabic_replies: report must identify both configured judges"]
    models, reasons = {}, []
    for name, record in zip(JUDGE_NAMES, judges, strict=True):
        if not isinstance(record, dict) or record.get("name") != name:
            reasons.append(f"arabic_replies: report is missing metadata for {name}")
            continue
        model = record.get("model")
        if not isinstance(model, str) or not model.strip():
            reasons.append(f"arabic_replies: {name} metadata needs a model ID")
            continue
        if record.get("family") != _model_family(model):
            reasons.append(f"arabic_replies: {name} family does not match its model ID")
        models[name] = model
    if len(models) == len(JUDGE_NAMES) and models[JUDGE_NAMES[0]] == models[JUDGE_NAMES[1]]:
        reasons.append("arabic_replies: judges must use different model IDs")
    return models, reasons


def _validate_case(
    case: dict[str, Any], record: Any, judge_models: dict[str, str]
) -> tuple[dict[str, Any], list[str]]:
    if not case:
        return {}, ["arabic_replies: report contains a case outside the reviewed dataset"]
    if not isinstance(record, dict) or record.get("case_id") != case["id"]:
        return {}, [f"case {case['id']}: missing or mismatched case record"]
    reasons = []
    reply = record.get("generated_output")
    if record.get("generation_error") or not isinstance(reply, str):
        reasons.append(f"case {case['id']}: player reply generation failed")
        reply = ""
    if record.get("query") != case["text"]:
        reasons.append(f"case {case['id']}: query does not match reviewed dataset")
    scored = _score_reply(case, reply)
    judges = _validate_judgments(case, record.get("judges"), judge_models, reasons)
    result = {**scored, "generation_error": record.get("generation_error"), "judges": judges}
    if record.get("mostly_arabic") is not scored["mostly_arabic"]:
        reasons.append(f"case {case['id']}: mostly-Arabic result does not match reply text")
    return result, reasons


def _validate_judgments(
    case: dict[str, Any], records: Any, expected_models: dict[str, str], reasons: list[str]
) -> dict[str, Any]:
    validated = {}
    if not isinstance(records, dict):
        reasons.append(f"case {case['id']}: judge labels are missing")
        return validated
    for name in JUDGE_NAMES:
        row = records.get(name)
        if not isinstance(row, dict):
            reasons.append(f"case {case['id']}: missing label from {name}")
            continue
        validated[name] = _validate_judgment(case, name, row, expected_models, reasons)
    return validated


def _validate_judgment(
    case: dict[str, Any], name: str, row: dict[str, Any], expected_models: dict[str, str], reasons: list[str]
) -> dict[str, Any]:
    if row.get("label") not in {"egyptian", "standard", "mixed"}:
        reasons.append(f"case {case['id']}: invalid label from {name}")
    if row.get("model") != expected_models.get(name):
        reasons.append(f"case {case['id']}: {name} model ID mismatch")
    rationale = row.get("rationale")
    if row.get("error") or not isinstance(rationale, str) or not rationale.strip():
        reasons.append(f"case {case['id']}: {name} did not return a structured label")
    fields = ("model", "label", "rationale", "attempts", "error")
    return {key: row.get(key) for key in fields}


def _review_status(judge_models: dict[str, str], player_model: str | None) -> dict[str, Any]:
    try:
        review = json.loads(REVIEW_FILE.read_text(encoding="utf-8"))
        sample = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "unreviewed", "reason": "10-reply judge sample has not been reviewed."}
    sample_hash = _sample_hash(sample.get("examples"))
    if not _review_matches(review, sample, sample_hash, judge_models, player_model):
        return {"status": "unreviewed", "reason": "judge review is pending or does not match this sample and configuration."}
    return {
        "status": "reviewed",
        "sample_sha256": sample_hash,
        "reviewed_by": review["reviewed_by"],
        "reviewed_on": review["reviewed_on"],
    }


def _review_matches(
    review: Any,
    sample: Any,
    sample_hash: str | None,
    judge_models: dict[str, str],
    player_model: Any,
) -> bool:
    if not isinstance(review, dict) or not isinstance(sample, dict) or sample_hash is None:
        return False
    if review.get("review_status") != "reviewed" or review.get("sample_sha256") != sample_hash:
        return False
    if not _review_configuration_matches(review, sample, judge_models, player_model):
        return False
    try:
        date.fromisoformat(review["reviewed_on"])
    except (TypeError, ValueError):
        return False
    return _sample_has_balanced_registers(sample)


def _review_configuration_matches(
    review: dict[str, Any],
    sample: dict[str, Any],
    judge_models: dict[str, str],
    player_model: Any,
) -> bool:
    if not isinstance(player_model, str) or not player_model.strip():
        return False
    if review.get("player_model") != player_model or sample.get("player_model") != player_model:
        return False
    if review.get("judge_models") != [judge_models.get(name) for name in JUDGE_NAMES]:
        return False
    if sample.get("judge_models") != [judge_models.get(name) for name in JUDGE_NAMES]:
        return False
    if review.get("rubric_sha256") != rubric_hash() or sample.get("rubric_sha256") != rubric_hash():
        return False
    if not isinstance(review.get("reviewed_by"), str) or not review["reviewed_by"].strip():
        return False
    return True


def _sample_has_balanced_registers(sample: dict[str, Any]) -> bool:
    examples = sample.get("examples")
    if not isinstance(examples, list) or any(not isinstance(example, dict) for example in examples):
        return False
    expected = [example.get("expected_register") for example in examples]
    return len(examples) == 10 and expected.count("egyptian") == 5 and expected.count("standard") == 5


def rubric_hash() -> str:
    return hashlib.sha256(ARABIC_DIALECT_RUBRIC.encode("utf-8")).hexdigest()


def _sample_hash(examples: Any) -> str | None:
    if not isinstance(examples, list) or len(examples) != 10:
        return None
    encoded = json.dumps(examples, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _summarize(
    records: list[Any],
    cases: list[dict[str, Any]],
    judge_metadata: list[dict[str, str]],
    player_model: str | None,
    *,
    judge_models: dict[str, str] | None = None,
) -> dict[str, Any]:
    if judge_models is None:
        judge_models = {row["name"]: row["model"] for row in judge_metadata}
    validated, reasons = _validate_records(records, cases, judge_models)
    mostly = _mostly_measure(cases, validated, reasons)
    egyptian, review = _reviewed_egyptian(cases, validated, judge_models, player_model, reasons)
    return _summary_payload(cases, validated, reasons, mostly, egyptian, review)


def _validate_records(
    records: list[Any], cases: list[dict[str, Any]], judge_models: dict[str, str]
) -> tuple[list[dict[str, Any]], list[str]]:
    reasons = []
    validated = []
    indexed = {case["id"]: case for case in cases}
    for record in records:
        case_id = record.get("case_id") if isinstance(record, dict) else None
        case, case_reasons = _validate_case(indexed.get(case_id, {}), record, judge_models)
        validated.append(case)
        reasons.extend(case_reasons)
    if len(records) != len(cases):
        reasons.append(f"arabic_replies: expected {len(cases)} replies, got {len(records)}")
    record_ids = [record.get("case_id") for record in records if isinstance(record, dict)]
    if record_ids != [case["id"] for case in cases]:
        reasons.append("arabic_replies: case ids must match the reviewed dataset exactly once and in order")
    if not all(validated):
        reasons.append("arabic_replies: at least one Arabic reply failed validation")
    return validated, reasons


def _mostly_measure(
    cases: list[dict[str, Any]], validated: list[dict[str, Any]], reasons: list[str]
) -> dict[str, Any]:
    score = sum(case.get("mostly_arabic") is True for case in validated)
    passed = ARABIC_BAR.passes(score, len(cases))
    if not passed:
        reasons.append(f"arabic_replies: mostly-Arabic score {score}/{len(cases)} below required 90%")
    return {"score": score, "total": len(cases), "bar": ARABIC_BAR.as_dict(), "passed": passed}


def _reviewed_egyptian(
    cases: list[dict[str, Any]],
    validated: list[dict[str, Any]],
    judge_models: dict[str, str],
    player_model: str | None,
    reasons: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    egyptian = _egyptian_measure(cases, validated)
    review = _review_status(judge_models, player_model)
    egyptian = _apply_review_status(egyptian, review)
    _check_egyptian_bar(egyptian, reasons)
    return egyptian, review


def _apply_review_status(
    egyptian: dict[str, Any], review: dict[str, Any]
) -> dict[str, Any]:
    if review["status"] == "reviewed":
        egyptian["status"] = "reviewed"
        egyptian["passed"] = ARABIC_BAR.passes(egyptian["both_judges_score"], egyptian["total"])
    else:
        egyptian["status"] = "unreviewed"
        egyptian["passed"] = None
        egyptian["unreviewed_reason"] = review["reason"]
    return egyptian


def _check_egyptian_bar(egyptian: dict[str, Any], reasons: list[str]) -> None:
    if egyptian["status"] == "reviewed" and not egyptian["passed"]:
        reasons.append(
            f"arabic_replies: Egyptian label by both judges {egyptian['both_judges_score']}/{egyptian['total']} below required 90%"
        )


def _summary_payload(
    cases: list[dict[str, Any]],
    validated: list[dict[str, Any]],
    reasons: list[str],
    mostly: dict[str, Any],
    egyptian: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    return suite_summary(
        {
            "score": mostly["score"],
            "total": len(cases),
            "passed": mostly["passed"]
            and (egyptian["status"] == "unreviewed" or egyptian["passed"])
            and not reasons,
            "failure_reasons": reasons,
            "mostly_arabic": mostly,
            "egyptian_register": {**egyptian, "review": review},
            "measures": _measure_lines(mostly, egyptian),
            "unreviewed_count": int(egyptian["status"] == "unreviewed"),
            "cases": validated,
        },
        ARABIC_BAR,
    )


def _measure_lines(mostly: dict[str, Any], egyptian: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"name": "mostly Arabic", **mostly},
        {"name": "Egyptian register", "score": egyptian["both_judges_score"], **egyptian},
    ]


def _egyptian_measure(cases: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [record for record in records if record.get("expected_register") == "egyptian"]
    judge_scores = {
        name: sum(record.get("judges", {}).get(name, {}).get("label") == "egyptian" for record in eligible)
        for name in JUDGE_NAMES
    }
    both_score = sum(
        all(record.get("judges", {}).get(name, {}).get("label") == "egyptian" for name in JUDGE_NAMES)
        for record in eligible
    )
    return {
        "status": "unreviewed",
        "total": len(eligible),
        "both_judges_score": both_score,
        "judge_scores": judge_scores,
        "excluded_standard_replies": sum(case["launch_response_kind"] != "normal_assistant" for case in cases),
        "bar": ARABIC_BAR.as_dict(),
        "passed": None,
    }


def _empty_summary(reasons: list[str]) -> dict[str, Any]:
    return empty_suite_summary(
        ARABIC_BAR,
        0,
        reasons,
        {
            "mostly_arabic": {"score": 0, "total": 0, "bar": ARABIC_BAR.as_dict(), "passed": False},
            "egyptian_register": {"status": "unreviewed", "passed": None, "total": 0},
            "measures": [],
            "unreviewed_count": 1,
            "cases": [],
        },
    )


def write_review_sample(report_path: Path) -> Path:
    sample = _review_sample(report_path)
    sample_hash = _sample_hash(sample["examples"])
    if sample_hash is None:
        raise ValueError("The calibration sample must contain five Egyptian and five standard replies.")
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_FILE.write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_pending_review(sample_hash, sample["judge_models"], sample["player_model"])
    return SAMPLE_FILE


def _review_sample(report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("mode") != "live":
        raise ValueError("A live player-gate report is required for judge calibration.")
    judge_models, reasons = _judge_models(report)
    if reasons:
        raise ValueError("; ".join(reasons))
    player_model = report.get("player_model")
    if not isinstance(player_model, str) or not player_model.strip():
        raise ValueError("Live report must identify its configured player model.")
    suite_results = report.get("suite_results")
    entry = suite_results.get("arabic_replies") if isinstance(suite_results, dict) else None
    rows = entry.get("cases") if isinstance(entry, dict) else None
    examples = _review_examples(rows)
    return {
        "schema_version": 1,
        "source_report": str(report_path),
        "player_model": player_model,
        "judge_models": [judge_models[name] for name in JUDGE_NAMES],
        "rubric_sha256": rubric_hash(),
        "examples": examples,
    }


def _review_examples(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError("Arabic reply report is missing its cases.")
    selected: dict[str, list[dict[str, Any]]] = {"egyptian": [], "standard": []}
    for row in rows:
        register = row.get("expected_register") if isinstance(row, dict) else None
        if register not in selected or len(selected[register]) == 5:
            continue
        judges = row.get("judges")
        if not isinstance(row.get("generated_output"), str) or not isinstance(judges, dict):
            continue
        if any(not isinstance(judges.get(name), dict) or not judges[name].get("label") for name in JUDGE_NAMES):
            continue
        selected[register].append(_review_example(row))
    if any(len(group) != 5 for group in selected.values()):
        raise ValueError("Report needs five judged Egyptian and five judged standard replies for review.")
    return [*selected["egyptian"], *selected["standard"]]


def _review_example(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": row["case_id"],
        "expected_register": row["expected_register"],
        "player_message": row["query"],
        "assistant_reply": row["generated_output"],
        "judges": {
            name: {"label": row["judges"][name].get("label"), "rationale": row["judges"][name].get("rationale")}
            for name in JUDGE_NAMES
        },
    }


def _write_pending_review(sample_hash: str, judge_models: list[str], player_model: str) -> None:
    pending = {
        "review_status": "pending",
        "sample_sha256": sample_hash,
        "judge_models": judge_models,
        "player_model": player_model,
        "rubric_sha256": rubric_hash(),
        "reviewed_by": None,
        "reviewed_on": None,
    }
    if REVIEW_FILE.is_file():
        existing = json.loads(REVIEW_FILE.read_text(encoding="utf-8"))
        if (
            existing.get("review_status") == "reviewed"
            and existing.get("sample_sha256") == sample_hash
            and existing.get("judge_models") == judge_models
            and existing.get("player_model") == player_model
            and existing.get("rubric_sha256") == rubric_hash()
        ):
            return
    REVIEW_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


SUITE = ArabicReplySuite()
