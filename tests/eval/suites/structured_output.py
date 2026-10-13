"""Structured player outputs checked against production schemas and catalog data."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from tests.eval.parity_gate import ScoreBar, call_with_retry
from tests.eval.suites.common import (
    empty_suite_summary,
    isolated_catalog_store,
    load_case_dataset,
    load_case_group,
    suite_summary,
)

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "tests/eval/datasets/structured_player_cases.json"
BAR = ScoreBar("count", 10)
CASE_COUNT = 5


@dataclass(frozen=True)
class StructuredResponse:
    parsed: BaseModel | None
    finish_reason: str | None
    error: str | None
    attempts: int


class HermeticSubstitutionResolution(BaseModel):
    source_exercise: str | None = None
    target_exercise: str | None = None


class StructuredOutputSuite:
    name = "structured_output"

    def run(self, context: Any) -> dict[str, Any]:
        from utils.model_downloader import get_llm

        try:
            cases = _load_cases()
        except ValueError as error:
            return _empty_summary([f"structured_output: {error}"])
        with isolated_catalog_store() as store:
            records = [
                _run_split_case(case, get_llm(), context.retry_policy, store)
                for case in cases["split_plans"]
            ]
            records.extend(
                _run_substitution_case(case, get_llm(), context.retry_policy, store)
                for case in cases["substitution_resolutions"]
            )
            summary, _ = _summarize(records, cases, store, hermetic=False)
        return summary

    def run_hermetic(self, _context: Any) -> dict[str, Any]:
        try:
            cases = _load_cases()
        except ValueError as error:
            return _empty_summary([f"structured_output: {error}"])
        records = [
            _hermetic_split_case(case)
            for case in cases["split_plans"]
        ]
        records.extend(_hermetic_substitution_case(case) for case in cases["substitution_resolutions"])
        summary, _ = _summarize(records, cases, store=None, hermetic=True)
        return summary

    def validate(self, recorded_entry: Any, report: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        try:
            cases = _load_cases()
        except ValueError as error:
            reasons = [f"structured_output: {error}"]
            return _empty_summary(reasons), reasons
        records = recorded_entry.get("cases") if isinstance(recorded_entry, dict) else None
        if not isinstance(records, list):
            return _empty_summary(["structured_output: cases are missing or invalid"]), [
                "structured_output: cases are missing or invalid"
            ]
        is_hermetic = report.get("mode") == "hermetic"
        if is_hermetic:
            summary, reasons = _summarize(records, cases, store=None, hermetic=True)
        else:
            with isolated_catalog_store() as store:
                summary, reasons = _summarize(records, cases, store, hermetic=False)
        return _compare_summary(recorded_entry, summary, reasons)


def _load_cases() -> dict[str, list[dict[str, Any]]]:
    payload = load_case_dataset(DATASET)
    split_cases = load_case_group(
        payload,
        "split_plans",
        "Structured-output split-plan dataset",
        {"count": CASE_COUNT},
    )
    substitution_cases = load_case_group(
        payload,
        "substitution_resolutions",
        "Structured-output substitution dataset",
        {"count": CASE_COUNT},
    )
    _validate_split_requests(split_cases)
    identifiers = [case.get("id") for case in (*split_cases, *substitution_cases)]
    if len(set(identifiers)) != 2 * CASE_COUNT:
        raise ValueError("Structured-output case ids must be unique.")
    return {"split_plans": split_cases, "substitution_resolutions": substitution_cases}


def _validate_split_requests(cases: list[dict[str, Any]]) -> None:
    from agent.program_blueprints import match_split_keyword

    shortcuts = {"standard", "default", "none", "balanced"}
    for case in cases:
        request = case.get("request")
        case_id = case["id"]
        if not isinstance(request, str) or not request.strip():
            raise ValueError(f"split-plan case {case_id} needs a non-empty model request.")
        if request.strip().casefold() in shortcuts or match_split_keyword(request):
            raise ValueError(
                f"split-plan case {case_id} matches a deterministic split shortcut "
                "and bypasses the player model."
            )


def _raw_finish_reason(raw_response: Any) -> str | None:
    metadata = getattr(raw_response, "response_metadata", {}) or {}
    reason = metadata.get("finish_reason")
    if reason is None:
        reason = (getattr(raw_response, "additional_kwargs", {}) or {}).get("finish_reason")
    return str(reason) if reason is not None else None


def _call_structured(model: Any, schema: type[BaseModel], prompt: Any, policy: Any, budget: int) -> StructuredResponse:
    call = call_with_retry(lambda: _invoke_structured(model, schema, prompt, budget), policy)
    response = call.response
    if isinstance(response, StructuredResponse):
        return StructuredResponse(response.parsed, response.finish_reason, call.error, call.attempts)
    return StructuredResponse(None, None, call.error or "No structured response returned", call.attempts)


def _invoke_structured(model: Any, schema: type[BaseModel], prompt: Any, budget: int) -> StructuredResponse:
    structured = model.with_structured_output(
        schema,
        include_raw=True,
        method="function_calling",
        max_completion_tokens=budget,
    )
    response = structured.invoke(prompt)
    finish_reason = _raw_finish_reason(response.get("raw"))
    if finish_reason == "length":
        return StructuredResponse(None, finish_reason, None, 0)
    parse_error = response.get("parsing_error")
    if parse_error is not None:
        raise parse_error
    parsed = response.get("parsed")
    if not isinstance(parsed, schema):
        raise ValueError(f"Structured response did not parse as {schema.__name__}.")
    return StructuredResponse(parsed, finish_reason, None, 0)


def _call_record(call: StructuredResponse) -> dict[str, Any]:
    status = "truncated" if call.finish_reason == "length" else "failed" if call.error else "parsed"
    return {
        "status": status,
        "finish_reason": call.finish_reason,
        "attempts": call.attempts,
        "error": call.error,
        "parsed_output": call.parsed.model_dump() if call.parsed else None,
    }


def _run_split_case(case: dict[str, Any], model: Any, policy: Any, store: Any) -> dict[str, Any]:
    capture: dict[str, StructuredResponse] = {}
    try:
        plan = _model_split_plan(case, model, policy, capture)
        record = _call_record(capture["call"])
        record["generated_program"] = _generate_split_program(plan, case, store)
    except Exception as error:
        record = _call_record(capture["call"]) if "call" in capture else _failed_call(error)
        record["validation_error"] = str(error)[:500]
    return {"case_id": case["id"], "kind": "split_plan", **record}


def _model_split_plan(
    case: dict[str, Any], model: Any, policy: Any, capture: dict[str, StructuredResponse]
) -> Any:
    from agent.program_rules import resolve_split
    from agent.ProgramState import DynamicSplitPlan
    from utils.player_output_budgets import player_output_budget

    def invoke_split(_invoke: Any, prompt: Any) -> dict[str, Any]:
        call = _call_structured(model, DynamicSplitPlan, prompt, policy, player_output_budget("dynamic_split_plan"))
        capture["call"] = call
        from langchain_core.messages import AIMessage

        return {
            "raw": AIMessage(content="", response_metadata={"finish_reason": call.finish_reason}),
            "parsed": deepcopy(call.parsed),
            "parsing_error": ValueError(call.error) if call.error else None,
        }

    resolved = resolve_split(case["frequency"], case["request"], case["gender"], inference_call=invoke_split)
    if "call" not in capture:
        raise ValueError(f"split-plan case {case['id']} bypassed the configured player model.")
    return resolved


def _generate_split_program(plan: Any, case: dict[str, Any], store: Any) -> dict[str, Any]:
    from agent.ProgramState import GeneratedProgramSchema
    from agent.program_generator import ProgramGenerationRequest, _generate_program_days
    from utils.equipment_access import COMMERCIAL_GYM

    profile = _split_profile(case, COMMERCIAL_GYM)
    request = ProgramGenerationRequest(rep_preference_override="balanced")
    with store.open_ledger(f"structured_{case['id']}") as ledger:
        days = _generate_program_days(profile, request, plan, ledger)
    program = GeneratedProgramSchema(
        program_name=plan.split_name,
        split_type=plan.split_name,
        weekly_frequency=len(plan.days),
        days=days,
    )
    return program.model_dump()


def _split_profile(case: dict[str, Any], equipment_access: str) -> dict[str, Any]:
    return {
        "gender": case["gender"],
        "equipment_access": equipment_access,
        "training_age_years": 2,
        "current_goal": "muscle_gain",
    }


def _run_substitution_case(case: dict[str, Any], model: Any, policy: Any, store: Any) -> dict[str, Any]:
    from agent.assistant_graph import SubstitutionResolution, _build_coreference_prompt
    from utils.player_output_budgets import player_output_budget

    try:
        source_id, prompt = _substitution_prompt(case, store, _build_coreference_prompt)
    except (ValueError, KeyError) as error:
        return {"case_id": case["id"], "kind": "substitution_resolution", **_failed_call(error)}
    call = _call_structured(
        model,
        SubstitutionResolution,
        prompt,
        policy,
        player_output_budget("substitution_resolution"),
    )
    return _substitution_record(case, source_id, call)


def _substitution_record(case: dict[str, Any], source_id: str, call: StructuredResponse) -> dict[str, Any]:
    return {
        "case_id": case["id"],
        "kind": "substitution_resolution",
        "source_exercise_id": source_id,
        "expected_target": case["expected_target"],
        **_call_record(call),
    }


def _substitution_prompt(case: dict[str, Any], store: Any, build_prompt: Any) -> tuple[str, Any]:
    from langchain_core.messages import AIMessage, HumanMessage

    active_program, source_id = _case_program(case, store)
    messages = _conversation_messages(case, HumanMessage, AIMessage)
    prompt = build_prompt(case["query"], messages, active_program, store)
    return source_id, prompt


def _conversation_messages(case: dict[str, Any], human_type: type, assistant_type: type) -> list[Any]:
    message_types = {"human": human_type, "assistant": assistant_type}
    messages = [message_types[row["role"]](content=row["content"]) for row in case["conversation"]]
    messages.append(human_type(content=case["query"]))
    return messages


def _case_program(case: dict[str, Any], store: Any) -> tuple[Any, str]:
    from agent.ProgramState import PersistedProgramDaySchema, PersistedProgramSchema

    exercise, source_id = _program_exercise(case["program_exercise"], store)
    day = PersistedProgramDaySchema(day_name="Training Day", day_order=1, exercises=[exercise])
    program = PersistedProgramSchema(
        program_name="Substitution evaluation program",
        split_type="custom",
        weekly_frequency=1,
        days=[day],
    )
    return program, source_id


def _program_exercise(source_name: str, store: Any) -> tuple[Any, str]:
    from agent.ProgramState import PersistedProgramExerciseSchema

    source_id = store.find_unique_exercise_id_by_exact_name(source_name)
    entry = store.get_exercise_library_entry(source_id) if source_id else None
    visible = source_id is not None and store.is_exercise_library_exercise_visible(source_id)
    if source_id is None or entry is None or not visible:
        raise ValueError(f"Program source is not a visible unique Exercise library entry: {source_name}")
    exercise = PersistedProgramExerciseSchema(
        exercise_id=source_id,
        exercise_name=entry["name"],
        target_sets=3,
        target_reps_min=8,
        target_reps_max=12,
        target_rpe=8.0,
    )
    return exercise, source_id


def _hermetic_split_case(case: dict[str, Any]) -> dict[str, Any]:
    from agent.program_rules import get_default_split

    plan = get_default_split(case["frequency"], case["gender"])
    return {
        "case_id": case["id"],
        "kind": "split_plan",
        "status": "parsed",
        "finish_reason": "stop",
        "attempts": 0,
        "error": None,
        "parsed_output": plan.model_dump(),
        "generated_program": None,
    }


def _hermetic_substitution_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["id"],
        "kind": "substitution_resolution",
        "status": "parsed",
        "finish_reason": "stop",
        "attempts": 0,
        "error": None,
        "parsed_output": {
            "source_exercise": case["program_exercise"],
            "target_exercise": case["expected_target"],
        },
        "source_exercise_id": "hermetic-source",
        "expected_target": case["expected_target"],
    }


def _failed_call(error: Exception) -> dict[str, Any]:
    return {
        "status": "truncated" if "finish_reason=length" in str(error) else "failed",
        "finish_reason": "length" if "finish_reason=length" in str(error) else None,
        "attempts": 0,
        "error": str(error)[:500],
        "parsed_output": None,
    }


def _summarize(
    records: list[dict[str, Any]],
    cases: dict[str, list[dict[str, Any]]],
    store: Any,
    *,
    hermetic: bool,
) -> tuple[dict[str, Any], list[str]]:
    validated, reasons = _validate_records(records, cases, store, hermetic)
    return _summary_payload(validated, reasons)


def _validate_records(
    records: list[Any], cases: dict[str, list[dict[str, Any]]], store: Any, hermetic: bool
) -> tuple[list[dict[str, Any]], list[str]]:
    indexed_cases, expected_kinds = _case_indexes(cases)
    expected_ids = [case["id"] for group in cases.values() for case in group]
    reasons: list[str] = []
    validated = []
    for record in records:
        case_id = record.get("case_id") if isinstance(record, dict) else None
        case = indexed_cases.get(case_id)
        passed, case_reasons = _validate_case(
            case, record, store, hermetic=hermetic, expected_kind=expected_kinds.get(case_id)
        )
        validated.append({**record, "passed": passed, "failure_reasons": case_reasons} if isinstance(record, dict) else {"passed": passed, "failure_reasons": case_reasons})
        reasons.extend(f"case {case_id or '?'}: {reason}" for reason in case_reasons)
    record_ids = [record.get("case_id") for record in records if isinstance(record, dict)]
    _check_case_coverage(record_ids, expected_ids, len(records), reasons)
    return validated, reasons


def _check_case_coverage(record_ids: list[Any], expected_ids: list[str], count: int, reasons: list[str]) -> None:
    if record_ids != expected_ids:
        reasons.append("structured_output: case ids must match the dataset exactly once and in order")
    if count != 2 * CASE_COUNT:
        reasons.append(f"expected {2 * CASE_COUNT} structured cases, got {count}")


def _case_indexes(cases: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, Any], dict[str, str]]:
    indexed = {case["id"]: case for group in cases.values() for case in group}
    kind_for_group = {"split_plans": "split_plan", "substitution_resolutions": "substitution_resolution"}
    kinds = {case["id"]: kind_for_group[group_name] for group_name, group in cases.items() for case in group}
    return indexed, kinds


def _summary_payload(
    validated: list[dict[str, Any]], reasons: list[str]
) -> tuple[dict[str, Any], list[str]]:
    score = sum(record["passed"] for record in validated)
    if not BAR.passes(score, 2 * CASE_COUNT):
        reasons.append(f"structured_output: score {score}/10 below required bar 10/10")
    summary = suite_summary(
        {
            "score": score,
            "total": 2 * CASE_COUNT,
            "passed": BAR.passes(score, 2 * CASE_COUNT) and not reasons,
            "failure_reasons": reasons,
            "cases": validated,
        },
        BAR,
    )
    return summary, reasons


def _validate_case(
    case: dict[str, Any] | None,
    record: Any,
    store: Any,
    *,
    hermetic: bool,
    expected_kind: str | None,
) -> tuple[bool, list[str]]:
    identity_error = _case_identity_error(case, record, expected_kind)
    if identity_error:
        return False, [identity_error]
    reasons = _call_failures(record)
    if reasons:
        return False, reasons
    output, parse_reasons = _parse_output(record, expected_kind, hermetic)
    if parse_reasons:
        return False, parse_reasons
    reasons = _validate_output(case, output, record, store, hermetic, expected_kind)
    return not reasons, reasons


def _case_identity_error(case: Any, record: Any, expected_kind: str | None) -> str | None:
    if not isinstance(record, dict):
        return "case record must be an object"
    if case is None or record.get("case_id") != case["id"]:
        return "case id is missing or not in the current dataset"
    if record.get("kind") != expected_kind:
        return "case kind does not match the structured-output dataset"
    return None


def _parse_output(record: dict[str, Any], expected_kind: str | None, hermetic: bool) -> tuple[Any, list[str]]:
    from agent.ProgramState import DynamicSplitPlan

    schema = _output_schema(expected_kind, hermetic, DynamicSplitPlan)
    try:
        return schema.model_validate(record.get("parsed_output")), []
    except (TypeError, ValueError) as error:
        return None, [f"structured output failed {schema.__name__} validation: {error}"]


def _output_schema(expected_kind: str | None, hermetic: bool, split_schema: type[BaseModel]) -> type[BaseModel]:
    if expected_kind == "split_plan":
        return split_schema
    if hermetic:
        return HermeticSubstitutionResolution
    from agent.assistant_graph import SubstitutionResolution

    return SubstitutionResolution


def _validate_output(
    case: dict[str, Any], output: Any, record: dict[str, Any], store: Any, hermetic: bool, kind: str
) -> list[str]:
    if kind == "split_plan":
        return _validate_split(case, output, record, store, hermetic)
    return _validate_substitution(case, output, record, store, hermetic)


def _call_failures(record: dict[str, Any]) -> list[str]:
    if record.get("finish_reason") == "length" or record.get("status") == "truncated":
        return ["truncated: player response finished at the length limit"]
    if record.get("error") or record.get("status") != "parsed":
        return [f"structured output did not parse: {record.get('error') or record.get('status')}"]
    return []


def _validate_split(case: dict[str, Any], plan: Any, record: dict[str, Any], store: Any, hermetic: bool) -> list[str]:
    from agent.program_rules import _sanitize_llm_plan
    from agent.program_blueprints import SLOT_SPECS

    reasons = []
    expected = case["frequency"]
    sanitized = _sanitize_llm_plan(plan, expected, case["gender"])
    if sanitized != plan:
        reasons.append("DynamicSplitPlan required sanitizing or deterministic fallback")
    if len(plan.days) != expected or any(not day.target_slots for day in plan.days):
        reasons.append(f"DynamicSplitPlan must contain {expected} non-empty days")
    if any(slot not in SLOT_SPECS for day in plan.days for slot in day.target_slots):
        reasons.append("DynamicSplitPlan contains a slot outside the production blueprint")
    if not hermetic:
        reasons.extend(_validate_generated_program(record.get("generated_program"), expected, store))
    return reasons


def _validate_generated_program(program: Any, expected_days: int, store: Any) -> list[str]:
    from agent.ProgramState import GeneratedProgramSchema

    reasons = []
    try:
        validated = GeneratedProgramSchema.model_validate(program)
    except (TypeError, ValueError) as error:
        return [f"generated program failed production validation: {error}"]
    if validated.weekly_frequency != expected_days or len(validated.days) != expected_days:
        reasons.append(f"generated program does not contain exactly {expected_days} days")
    exercise_ids = [exercise.exercise_id for day in validated.days for exercise in day.exercises]
    if not exercise_ids:
        reasons.append("generated program contains no exercises")
    if any(
        not store.is_exercise_library_exercise_visible(exercise_id)
        or store.get_exercise_library_entry(exercise_id) is None
        for exercise_id in exercise_ids
    ):
        reasons.append("generated program contains an exercise outside the visible Exercise library")
    return reasons


def _validate_substitution(
    case: dict[str, Any], resolution: Any, record: dict[str, Any], store: Any, hermetic: bool
) -> list[str]:
    if not resolution.source_exercise or not resolution.target_exercise:
        return ["SubstitutionResolution needs source_exercise and target_exercise"]
    if hermetic:
        return [] if resolution.target_exercise == case["expected_target"] else ["wrong hermetic target exercise"]
    source_reason = _validate_substitution_source(case, resolution, record, store)
    if source_reason:
        return [source_reason]
    return _validate_substitution_target(case, resolution, record, store)


def _validate_substitution_source(
    case: dict[str, Any], resolution: Any, record: dict[str, Any], store: Any
) -> str | None:
    from agent.assistant_graph import SUBSTITUTION_SOURCE_SIMILARITY_THRESHOLD, _match_substitution_source

    program, source_id = _case_program(case, store)
    matched, _day, similarity = _match_substitution_source(program.days, resolution.source_exercise)
    if (
        matched is None
        or similarity < SUBSTITUTION_SOURCE_SIMILARITY_THRESHOLD
        or str(matched.exercise_id) != source_id
    ):
        return "resolved source does not match an exercise in the active program"
    if record.get("source_exercise_id") != source_id:
        return "recorded source evidence does not match the active program"
    return None


def _validate_substitution_target(
    case: dict[str, Any], resolution: Any, record: dict[str, Any], store: Any
) -> list[str]:
    source_id = record.get("source_exercise_id")
    target_id = store.find_unique_exercise_id_by_exact_name(case["expected_target"])
    target_matches = store.find_exercises_by_name(resolution.target_exercise, limit=None)
    if target_id is None or not any(str(match["id"]) == target_id for match in target_matches):
        return ["resolved target does not match the expected Exercise library entry"]
    if target_id == source_id or not store.is_exercise_library_exercise_visible(target_id):
        return ["resolved target is not a visible replacement Exercise library entry"]
    if record.get("expected_target") != case["expected_target"]:
        return ["recorded target evidence does not match the dataset"]
    return []


def _compare_summary(
    recorded: dict[str, Any], summary: dict[str, Any], reasons: list[str]
) -> tuple[dict[str, Any], list[str]]:
    reasons = list(reasons)
    for field in ("score", "total", "bar", "passed", "failure_reasons", "cases"):
        if recorded.get(field) != summary[field]:
            reasons.append(f"structured_output: recorded {field} does not match recomputed result")
    if reasons:
        summary["passed"] = False
        summary["failure_reasons"] = reasons
    return summary, reasons


def _empty_summary(reasons: list[str]) -> dict[str, Any]:
    return empty_suite_summary(BAR, 2 * CASE_COUNT, reasons, {"cases": []})


SUITE = StructuredOutputSuite()
