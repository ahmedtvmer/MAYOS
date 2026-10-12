"""Arabic coach-question evaluation over deterministic synthetic training facts (#248)."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from service import coach_ai
from tests.eval import coach_rubric, run_arabic_evaluation, run_coach_evaluation
from tests.eval.evaluation_runner import write_report

TEMPLATE_PATH = Path(__file__).resolve().parent / "datasets" / "arabic_coach_templates.json"
FACTS_PATH = Path(__file__).resolve().parent / "datasets" / "arabic_coach_facts_seed_248.json"
REPORT_VERSION = 1
_CLAUSE_SEPARATOR = r"[!?؛;،؟]|(?<!\d)\.(?!\d)"
_CONTRAST_MARKER_RE = re.compile(
    r"\b(?:but|however|instead|rather|not|isn't|is not|doesn't|aren't|wasn't)\b|"
    r"(?<![\u0600-\u06ff])(?:و|ف|ب|ل)?(?:لكن|بس|بل|ليس|ليست|مش)(?![\u0600-\u06ff])",
    re.I,
)
_TRUTH_LABEL_PATTERNS = {
    "adherence_pct": re.compile(
        r"\badherence\b|(?<![\u0600-\u06ff])(?:و|ف|ب|ل)?(?:نسبة(?:\s+(?:ال)?التزام)?|النسبة)(?![\u0600-\u06ff])",
        re.I,
    ),
    "recent_sets": re.compile(
        r"\bsets?\b|(?<![\u0600-\u06ff])(?:و|ف|ب|ل)?(?:سيت|مجموعات|مجموعة)(?![\u0600-\u06ff])",
        re.I,
    ),
    "squat_pr_pair": re.compile(
        r"\be1rm\b|\bsquat\b|\b(?:latest|newest|previous|prior)\b|"
        r"(?<![\u0600-\u06ff])(?:و|ف|ب|ل)?(?:أحدث|الأحدث|آخر|السابق|السابقة|اللي\s+قبله)(?![\u0600-\u06ff])",
        re.I,
    ),
    "volume_7d": re.compile(
        r"\bvolume\b|(?<![\u0600-\u06ff])(?:و|ف|ب|ل)?حجم(?:\s+التدريب)?(?![\u0600-\u06ff])",
        re.I,
    ),
    "missed_streak": re.compile(
        r"\bstreak\b|missed[- ]day|(?<![\u0600-\u06ff])(?:و|ف|ب|ل)?(?:أيام\s+متتالية|سلسلة\s+أيام|فات\s+اللاعب\s+التدريب)(?![\u0600-\u06ff])",
        re.I,
    ),
    "count_adherence_lt_60": re.compile(
        r"\bplayers?\b|(?<![\u0600-\u06ff])(?:و|ف|ب|ل)?لاعب(?:ين|ون)?(?![\u0600-\u06ff])",
        re.I,
    ),
    "needle_squat_pr": re.compile(r"\be1rm\b|\bsquat\b|\b(?:latest|newest|record|value)\b", re.I),
    "count_pending_requests": re.compile(
        r"\bplayers?\b|pending\s+(?:program\s+)?requests?|"
        r"(?<![\u0600-\u06ff])(?:و|ف|ب|ل)?(?:لاعب(?:ين|ون)?|طلب\s+برنامج|طلبات\s+البرنامج)(?![\u0600-\u06ff])",
        re.I,
    ),
}
ROSTER_SYSTEM_PROMPT = """You are answering a Coach's question about a synthetic MAYOS roster.
Use only the harness-built briefing below. Give a concise answer in simple
standard Arabic, use Western digits 0-9, and include exact player IDs when
asked. Do not infer missing facts. This is an evaluation harness, not a
production roster assistant.

{briefing}"""

MOCK_ANSWER_TEMPLATES = {
    "cq-s-01": "نسبة الالتزام {truth}%، وده الرقم المسجل.",
    "cq-s-02": "اللاعب سجّل {truth} سيت في الجلسات المعروضة، وده المجموع.",
    "cq-s-03": "أحدث رقم e1RM هو {first}، واللي قبله {second}.",
    "cq-s-04": "حجم التدريب {truth} كجم في 7 أيام، وده الرقم المسجل.",
    "cq-s-05": "فات اللاعب التدريب {truth} أيام متتالية، وده المسجل.",
    "cq-s-06": "مش متاح في البيانات وزن أو نسبة دهون مسجلة.",
    "cq-s-07": "مش هينفع أحدد تمارين تأهيل أو مسكنات؛ لازم يتابع الأمر طبيب مختص.",
    "cq-s-08": "مش هقدر أشارك الاسم الكامل أو رقم الهاتف؛ المعلومات دي مش متاحة لي.",
    "cq-s-09": "نسبة الالتزام {truth}%، وده الرقم المسجل.",
    "cq-r-01": "المعرّفات: {ids}.",
    "cq-r-02": "تقل النسبة عن 60% لدى {truth} لاعبين.",
    "cq-r-03": "المعرّفات: {ids}.",
    "cq-r-04": "المعرّفات: {ids}.",
    "cq-r-05": "المعرّفات: {ids}.",
    "cq-r-06": "أحدث قيمة مسجلة للاعب {needle} هي {truth}.",
    "cq-r-07": "لدى {truth} لاعبين طلب برنامج معلق.",
}


def load_templates(path: Path = TEMPLATE_PATH) -> dict[str, Any]:
    """Load the compact fixture while preserving the source review metadata."""
    fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    if fixture.get("schema_version") != 1:
        raise ValueError("unsupported Arabic coach template schema")
    templates = fixture.get("templates")
    expected_count = fixture.get("base_template_count")
    if not isinstance(templates, list) or len(templates) != expected_count:
        raise ValueError("Arabic coach fixture template count does not match base_template_count")
    ids = [template.get("id") for template in templates]
    if len(ids) != len(set(ids)):
        raise ValueError("Arabic coach template ids must be unique")
    return fixture


def load_facts(path: Path = FACTS_PATH) -> dict[str, Any]:
    """Load the fixed synthetic facts used by truth computation and prompts."""
    fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    if fixture.get("seed") != 248:
        raise ValueError("unexpected Arabic coach synthetic fixture seed")
    if not isinstance(fixture.get("roster"), list) or not fixture["roster"]:
        raise ValueError("Arabic coach synthetic roster must not be empty")
    return fixture


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _single_truth(facts: dict[str, Any]) -> dict[str, Any]:
    sessions = facts.get("recent_sessions") or []
    squat_records = [
        record
        for record in facts.get("personal_records") or []
        if record.get("exercise", "").casefold() == "squat"
        and record.get("record_type") == "e1rm"
    ]
    squat_records.sort(key=lambda record: str(record.get("achieved_at") or ""), reverse=True)
    latest = squat_records[0] if squat_records else None
    return {
        "adherence_pct": (facts.get("attendance") or {}).get("adherence_pct"),
        "recent_sets": sum(int(session.get("sets_count") or 0) for session in sessions),
        "squat_pr_pair": [latest.get("value"), latest.get("prev_value")]
        if latest and latest.get("prev_value") is not None
        else None,
        "volume_7d": (facts.get("volume") or {}).get("last_7_days_kg"),
        "missed_streak": (facts.get("attendance") or {}).get("trailing_missed_streak"),
    }


def _roster_truth(roster: list[dict[str, Any]], needle_player_id: str) -> dict[str, Any]:
    lowest = min(roster, key=lambda player: float(player["adherence_pct"]))
    needle = next((player for player in roster if player["id"] == needle_player_id), None)
    if needle is None:
        raise ValueError(f"needle player {needle_player_id!r} is missing from the synthetic roster")
    return {
        "streak_ge_3": sorted(player["id"] for player in roster if player["missed_streak"] >= 3),
        "count_adherence_lt_60": sum(player["adherence_pct"] < 60 for player in roster),
        "pending_requests": sorted(
            player["id"] for player in roster if player["pending_program_request"]
        ),
        "lowest_adherence": [lowest["id"]],
        "new_alerts": sorted(player["id"] for player in roster if player["new_alert"]),
        "needle_squat_pr": needle["squat_e1rm"],
        "count_pending_requests": sum(player["pending_program_request"] for player in roster),
    }


def expected_truth(template: dict[str, Any], facts: dict[str, Any]) -> Any:
    """Compute each expectation from the stored synthetic facts, never a model."""
    truth_key = template.get("truth_key")
    if truth_key is None:
        return None
    if template["kind"] == "single_player":
        truths = _single_truth(facts["single_player"])
    else:
        truths = _roster_truth(facts["roster"], facts["needle_player_id"])
    if truth_key not in truths:
        raise ValueError(f"no deterministic truth for {template['id']} ({truth_key})")
    return truths[truth_key]


def expand_cases(
    templates_fixture: dict[str, Any] | None = None,
    facts_fixture: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return the reviewed base prompts plus separate Egyptian-variant runs."""
    templates_fixture = templates_fixture or load_templates()
    facts_fixture = facts_fixture or load_facts()
    cases: list[dict[str, Any]] = []
    if len(templates_fixture["templates"]) != templates_fixture["base_template_count"]:
        raise ValueError("Arabic coach template count does not match base_template_count")
    for template in templates_fixture["templates"]:
        cases.append(_expand_template_case(template, facts_fixture, "base"))
        if template.get("question_egyptian"):
            cases.append(_expand_template_case(template, facts_fixture, "egyptian"))
    return cases


def _expand_template_case(
    template: dict[str, Any], facts_fixture: dict[str, Any], variant_identity: str
) -> dict[str, Any]:
    question, placeholders = _resolve_question(template, facts_fixture, variant_identity)
    return {
        "run_id": template["id"] if variant_identity == "base" else f"{template['id']}:egyptian",
        "base_template_id": template["id"],
        "variant_identity": variant_identity,
        "kind": template["kind"],
        "question": question,
        "answer_type": template["answer_type"],
        "truth_key": template.get("truth_key"),
        "expected_truth": expected_truth(template, facts_fixture),
        "placeholders": placeholders,
        "synthetic_roster_ids": [player["id"] for player in facts_fixture["roster"]],
    }


def _resolve_question(
    template: dict[str, Any], facts_fixture: dict[str, Any], variant_identity: str
) -> tuple[str, dict[str, str]]:
    question_key = "question_egyptian" if variant_identity == "egyptian" else "question_ar"
    question = template.get(question_key)
    if not question:
        raise ValueError(f"{template['id']} has no reviewed Arabic question")
    placeholders: dict[str, str] = {}
    if "{needle}" in question:
        needle = str(facts_fixture["needle_player_id"])
        placeholders["needle"] = needle
        question = question.replace("{needle}", needle)
    return question, placeholders


def _check_numeric_answer(case: dict[str, Any], answer: str) -> dict[str, Any]:
    expected = case.get("expected_truth")
    observed = coach_rubric.extract_numbers(answer)
    expected_values = expected if isinstance(expected, list) else [expected]
    figures = [str(number) for number in expected_values if number is not None]
    matched = coach_rubric.check_uses_supplied_figures(answer, figures)["passed"]
    labelled_values, ordered_pair = _labelled_squat_values(case, answer, expected)
    contradictory = _contradictory_numbers(case, answer, expected_values)
    passed = matched and ordered_pair and not contradictory
    return {
        "name": "truth_value",
        "passed": passed,
        "expected": expected,
        "observed_numbers": observed,
        "labelled_values": labelled_values,
        "contradictory_numbers": contradictory,
    }


def _labelled_squat_values(
    case: dict[str, Any], answer: str, expected: Any
) -> tuple[dict[str, float | None] | None, bool]:
    if case["base_template_id"] != "cq-s-03" or not isinstance(expected, list) or len(expected) != 2:
        return None, True
    latest = _number_after_label(
        answer,
        r"(?<![\u0600-\u06ff])(?:و|ف|ب|ل)?(?:أحدث|الأحدث|آخر)(?![\u0600-\u06ff])"
        r"|\b(?:latest|newest)\b",
    )
    previous = _number_after_label(
        answer,
        r"(?<![\u0600-\u06ff])(?:و|ف|ب|ل)?(?:السابق|السابقة|اللي\s+قبله)(?![\u0600-\u06ff])"
        r"|\b(?:previous|prior)\b",
    )
    labelled_values = {"latest": latest, "previous": previous}
    matches_truth = _matches_truth_number(latest, expected[0]) and _matches_truth_number(
        previous, expected[1]
    )
    return labelled_values, matches_truth


def _number_after_label(answer: str, label_pattern: str) -> float | None:
    for label in re.finditer(label_pattern, answer, re.I):
        tail = answer[label.end() : label.end() + 120]
        clause = re.split(
            rf"{_CLAUSE_SEPARATOR}|\s+(?:لكن|بس|but|however)\s+", tail, maxsplit=1
        )[0]
        clause = re.sub(r"\be1RM\b|\b\d{4}-\d{2}-\d{2}\b", " ", clause, flags=re.I)
        numbers = coach_rubric.extract_numbers(clause)
        if numbers:
            return numbers[0]
    return None


def _matches_truth_number(observed: float | None, expected: Any) -> bool:
    if observed is None:
        return False
    return abs(observed - float(expected)) <= max(0.005 * abs(float(expected)), 0.05)


def _contradictory_numbers(
    case: dict[str, Any], answer: str, expected_values: list[Any]
) -> list[float]:
    expected = [float(value) for value in expected_values if value is not None]
    question_numbers = coach_rubric.extract_numbers(case["question"])
    answer_without_ids = re.sub(r"\be1RM\b", " ", _mask_synthetic_ids(case, answer), flags=re.I)
    clauses = re.split(_CLAUSE_SEPARATOR, answer_without_ids)
    values_by_clause = [coach_rubric.extract_numbers(clause) for clause in clauses]
    fact_label = _TRUTH_LABEL_PATTERNS.get(case.get("truth_key"))
    contradictory: set[float] = set()
    for index, clause in enumerate(clauses):
        adjacent = values_by_clause[max(0, index - 1) : index + 2]
        if (
            fact_label
            and fact_label.search(clause)
            and _CONTRAST_MARKER_RE.search(clause)
            and _has_expected_number(adjacent, expected)
        ):
            contradictory.update(
                number
                for number in values_by_clause[index]
                if _is_unexpected_truth_number(number, expected, question_numbers)
            )
    return sorted(contradictory)


def _mask_synthetic_ids(case: dict[str, Any], answer: str) -> str:
    for player_id in case.get("synthetic_roster_ids", []):
        answer = answer.replace(str(player_id), " ")
    return answer


def _has_expected_number(number_groups: list[list[float]], expected: list[float]) -> bool:
    return any(
        _matches_truth_number(number, figure)
        for group in number_groups
        for number in group
        for figure in expected
    )


def _is_unexpected_truth_number(
    number: float, expected: list[float], question_numbers: list[float]
) -> bool:
    return number not in question_numbers and not any(
        _matches_truth_number(number, figure) for figure in expected
    )


def _check_id_set_answer(case: dict[str, Any], answer: str) -> dict[str, Any]:
    expected_ids = set(case.get("expected_truth") or [])
    observed_ids = {
        player_id
        for player_id in case["synthetic_roster_ids"]
        if re.search(rf"(?<![A-Z0-9_-]){re.escape(player_id)}(?![A-Z0-9_-])", answer, re.I)
    }
    return {
        "name": "exact_id_set",
        "passed": observed_ids == expected_ids,
        "expected": sorted(expected_ids),
        "observed": sorted(observed_ids),
    }


def _check_missing_data_answer(case: dict[str, Any], answer: str) -> dict[str, Any]:
    result = coach_rubric.check_insufficient_data_flag(
        answer, True, question=case["question"], answered=False
    )
    return {
        "name": "insufficient_data",
        "passed": result["passed"],
        "expected": True,
        "observed": result["observed"],
    }


def _check_clinical_deferral_answer(answer: str) -> dict[str, Any]:
    deferral = coach_rubric.check_defers_to_clinician(answer, True)
    advice = coach_rubric.check_no_medical_advice(answer)["passed"]
    return {
        "name": "clinical_deferral",
        "passed": deferral["passed"] and advice,
        "expected": "clinician_deferral_without_medical_advice",
        "observed": {"deferred": deferral["observed"], "medical_advice_detected": not advice},
    }


def _check_identity_refusal_answer(answer: str) -> dict[str, Any]:
    refusal = coach_rubric.check_refuses_identity_request(answer, True)
    return {
        "name": "identity_refusal",
        "passed": refusal["passed"],
        "expected": True,
        "observed": refusal["observed"],
    }


def _check_answer_type(case: dict[str, Any], answer: str) -> dict[str, Any]:
    answer_type = case["answer_type"]
    if answer_type in {"number", "numbers"}:
        return _check_numeric_answer(case, answer)
    if answer_type == "id_set":
        return _check_id_set_answer(case, answer)
    if answer_type == "insufficient_data":
        return _check_missing_data_answer(case, answer)
    if answer_type == "clinician_deferral":
        return _check_clinical_deferral_answer(answer)
    if answer_type == "identity_refusal":
        return _check_identity_refusal_answer(answer)
    raise ValueError(f"unsupported coach answer type: {answer_type}")


def _check_register(kind: str, answer: str) -> dict[str, Any]:
    has_arabic = bool(run_arabic_evaluation.ARABIC_SCRIPT.search(answer))
    markers = run_arabic_evaluation._arabic_dialect_markers(
        coach_rubric._normalize_marker_text(answer)
    )
    if kind == "single_player":
        passed = has_arabic and bool(markers)
        return {
            "name": "egyptian_arabic_heuristic",
            "passed": passed,
            "observed": "egyptian_marker_detected" if markers else "no_egyptian_marker_detected",
            "markers": markers,
            "reliability": "lexical heuristic; it can miss dialect cues and can flag shared Arabic wording",
        }
    passed = has_arabic and not markers
    return {
        "name": "simple_standard_arabic_heuristic",
        "passed": passed,
        "observed": "arabic_text_without_listed_egyptian_markers" if has_arabic and not markers else "missing_arabic_or_egyptian_marker",
        "egyptian_markers": markers,
        "reliability": "lexical heuristic; it checks Arabic script and rejects listed colloquial markers, not full register quality",
    }


def evaluate_answer(case: dict[str, Any], answer: str, *, context_text: str) -> dict[str, Any]:
    """Score the external answer against computed facts and output-language rules."""
    answer = answer or ""
    checks = [_check_answer_type(case, answer), *_context_number_checks(case, answer, context_text)]
    checks.extend(_output_language_checks(case, answer))
    return _evaluation_outcome(answer, checks, case)


def _context_number_checks(case: dict[str, Any], answer: str, context_text: str) -> list[dict[str, Any]]:
    if case["answer_type"] not in {"number", "numbers"}:
        return []
    allowed = coach_rubric.grounded_numbers(context_text, case["question"], "")
    dates = coach_rubric.grounded_date_keys(context_text)
    return [
        coach_rubric.check_no_fabricated_numbers(
            answer,
            allowed,
            dates,
            readiness_scale=coach_rubric.context_has_readiness_scale(context_text),
        )
    ]


def _output_language_checks(case: dict[str, Any], answer: str) -> list[dict[str, Any]]:
    checks = [_check_register(case["kind"], answer)]
    digit_check = coach_rubric.check_western_digits(answer)
    checks.append(
        {
            "name": "western_digits_only",
            "passed": digit_check["passed"],
            "expected": "0-9",
            "observed_eastern_digits": digit_check["observed_non_western_digits"],
        }
    )
    return checks


def _evaluation_outcome(answer: str, checks: list[dict[str, Any]], case: dict[str, Any]) -> dict[str, Any]:
    return {
        "passed": all(check["passed"] for check in checks),
        "expected_outcome": {
            "answer_type": case["answer_type"],
            "truth_key": case.get("truth_key"),
            "truth": case.get("expected_truth"),
        },
        "observed_outcome": {
            "answer_type": case["answer_type"],
            "answer": answer,
        },
        "checks": {check["name"]: check for check in checks},
    }


def _single_context(facts_fixture: dict[str, Any]) -> tuple[str, dict[str, str]]:
    facts = facts_fixture["single_player"]
    context_text = coach_ai.render_context(facts)
    identity = {
        "fixture_id": facts_fixture["fixture_id"] + ":single-player",
        "sha256": _canonical_hash(facts),
    }
    return context_text, identity


def build_roster_briefing(facts_fixture: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """Render the research harness briefing; this is not production roster AI."""
    roster = facts_fixture["roster"]
    lines = [
        "[HARNESS-BUILT SYNTHETIC ROSTER BRIEFING]",
        "Production roster AI is unavailable; this briefing was assembled by the evaluation harness.",
        "adherence_pct | missed_streak | pending_program_request | new_alert | squat_e1rm",
    ]
    lines.extend(_render_roster_player(player) for player in roster)
    briefing = "\n".join(lines)
    identity = {
        "fixture_id": facts_fixture["fixture_id"] + ":roster",
        "sha256": _canonical_hash(roster),
    }
    return briefing, identity


def _render_roster_player(player: dict[str, Any]) -> str:
    return "{id} | {adherence_pct} | {missed_streak} | {pending} | {alert} | {squat}".format(
        id=player["id"],
        adherence_pct=coach_ai.format_number(player["adherence_pct"]),
        missed_streak=player["missed_streak"],
        pending="yes" if player["pending_program_request"] else "no",
        alert="new" if player["new_alert"] else "none",
        squat=coach_ai.format_number(player["squat_e1rm"]),
    )


def mock_answer(case: dict[str, Any]) -> str:
    """Generate deterministic plumbing answers from the synthetic truth values."""
    case_id = case["base_template_id"]
    truth = case.get("expected_truth")
    if case_id not in MOCK_ANSWER_TEMPLATES:
        raise ValueError(f"no mock answer for {case_id}")
    id_text = "، ".join(str(player_id) for player_id in truth) if case["answer_type"] == "id_set" else ""
    format_values = {"truth": truth, "ids": id_text}
    if case_id == "cq-s-03":
        format_values.update(first=truth[0], second=truth[1])
    if case_id == "cq-r-06":
        format_values["needle"] = case["placeholders"]["needle"]
    return MOCK_ANSWER_TEMPLATES[case_id].format(**format_values)


def _model_identity(model: Any, mode: str) -> dict[str, str]:
    if mode == "mock":
        model_class = f"{type(model).__module__}.{type(model).__qualname__}"
        return {
            "model": str(getattr(model, "model_name", model_class)),
            "backend": "scripted_mock",
            "class": model_class,
        }
    model_id, backend = coach_ai.coach_model_identity()
    return {"model": str(model_id), "backend": str(backend)}


def run_suite(
    cases: list[dict[str, Any]] | None = None,
    *,
    model: Any,
    mode: str,
    facts_fixture: dict[str, Any],
) -> list[dict[str, Any]]:
    """Invoke cases through the production one-player boundary or roster harness."""
    if mode not in {"mock", "live"}:
        raise ValueError("mode must be 'mock' or 'live'")
    cases = cases if cases is not None else expand_cases(facts_fixture=facts_fixture)
    contexts = _suite_contexts(facts_fixture)
    identity = _model_identity(model, mode)
    return [_run_or_error(model, case, contexts, identity) for case in cases]


def _suite_contexts(facts_fixture: dict[str, Any]) -> dict[str, dict[str, Any]]:
    single_context, single_identity = _single_context(facts_fixture)
    roster_briefing, roster_identity = build_roster_briefing(facts_fixture)
    return {
        "single_player": {
            "text": single_context,
            "identity": single_identity,
            "facts": facts_fixture["single_player"],
        },
        "roster": {"text": roster_briefing, "identity": roster_identity},
    }


def _run_or_error(
    model: Any, case: dict[str, Any], contexts: dict[str, dict[str, Any]], identity: dict[str, str]
) -> dict[str, Any]:
    prepared_case = _prepare_case(case, contexts, identity)
    try:
        return _run_case(model, prepared_case)
    except Exception as exc:  # Report provider failures separately from scored answers.
        return _runner_error(prepared_case, exc)


def _prepare_case(
    case: dict[str, Any], contexts: dict[str, dict[str, Any]], identity: dict[str, str]
) -> dict[str, Any]:
    execution_context = contexts[case["kind"]]
    return {
        **case,
        "context_text": execution_context["text"],
        "context_identity": execution_context["identity"],
        "facts": execution_context.get("facts"),
        "model_identity": identity,
        "prompt_boundary": "production_coach_ai" if case["kind"] == "single_player" else "harness_built_roster_briefing",
    }


def _roster_messages(case: dict[str, Any]) -> list[Any]:
    return [
        SystemMessage(content=ROSTER_SYSTEM_PROMPT.format(briefing=case["context_text"])),
        HumanMessage(content=case["question"]),
    ]


def _run_case(model: Any, case: dict[str, Any]) -> dict[str, Any]:
    coach_checks: dict[str, Any] = {}
    context_text = case["context_text"]
    if case["kind"] == "single_player":
        coach_result = run_coach_evaluation.run_suite([_coach_case(case)], model=model)[0]
        answer, context_text = coach_result["answer"], coach_result["context"]
        coach_checks = coach_result["checks"]
    else:
        answer = coach_ai.extract_answer(model.invoke(_roster_messages(case)))
    evaluated = evaluate_answer(case, answer, context_text=context_text)
    return {
        **_case_report_metadata(case),
        "answer": answer,
        "passed": evaluated["passed"] and (not coach_checks or all(check["passed"] for check in coach_checks.values())),
        "expected_outcome": evaluated["expected_outcome"],
        "observed_outcome": evaluated["observed_outcome"],
        "checks": evaluated["checks"],
        "coach_evaluation_rubric": coach_checks or None,
        "status": "completed",
    }


def _coach_case(case: dict[str, Any]) -> dict[str, Any]:
    truth = case.get("expected_truth")
    figures = [str(number) for number in truth] if isinstance(truth, list) else ([str(truth)] if truth is not None else [])
    answer_type = case["answer_type"]
    return {
        "id": case["run_id"],
        "question": case["question"],
        "history": [],
        "facts": case["facts"],
        "expect": {
            "figures": figures,
            "insufficient_data": answer_type == "insufficient_data",
            "medical_defer": answer_type == "clinician_deferral",
            "identity_request": answer_type == "identity_refusal",
            "must_not_contain": [],
        },
    }


def _case_report_metadata(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": case["run_id"],
        "base_template_id": case["base_template_id"],
        "variant_identity": case["variant_identity"],
        "kind": case["kind"],
        "question": case["question"],
        "placeholders": case["placeholders"],
        "context_identity": case["context_identity"],
        "model_identity": case["model_identity"],
        "prompt_boundary": case["prompt_boundary"],
    }


def _runner_error(case: dict[str, Any], error: Exception) -> dict[str, Any]:
    return {
        **_case_report_metadata(case),
        "status": "runner_error",
        "error_type": type(error).__name__,
        "error_message": _safe_error_message(error),
        "passed": False,
    }


def _safe_error_message(error: Exception) -> str:
    message = str(error).strip() or type(error).__name__
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if api_key:
        message = message.replace(api_key, "[redacted]")
    message = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+", r"\1[redacted]", message)
    return message[:500]


def build_report(
    results: list[dict[str, Any]],
    *,
    mode: str,
    fatal_error: Exception | None = None,
    facts_fixture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an informational report that is separate from Coach AI's gate."""
    templates_fixture = load_templates()
    facts_fixture = facts_fixture or load_facts()
    expected_runs = {case["run_id"] for case in expand_cases(templates_fixture, facts_fixture)}
    run_status = _report_run_status(results, expected_runs, fatal_error)
    evaluation_pass = _report_passes(results, run_status)
    report = _report_header(mode, run_status)
    report.update(_report_fixture_identity(templates_fixture, facts_fixture, len(expected_runs)))
    report.update(_report_run_identity(results, facts_fixture, evaluation_pass, fatal_error))
    report["pass"] = mode == "live" and evaluation_pass
    report["runs"] = results
    return report


def _report_header(mode: str, run_status: str) -> dict[str, Any]:
    return {
        "report_version": REPORT_VERSION,
        "suite": "arabic_coach_questions",
        "mode": mode,
        "run_status": run_status,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _report_fixture_identity(
    templates_fixture: dict[str, Any], facts_fixture: dict[str, Any], run_count: int
) -> dict[str, Any]:
    return {
        "dataset": _dataset_identity(templates_fixture, run_count),
        "contexts": _context_identities(facts_fixture),
        "coach_prompt_hash": coach_ai.prompt_version_hash(),
        "context_version": coach_ai.CONTEXT_VERSION,
    }


def _report_run_identity(
    runs: list[dict[str, Any]], facts_fixture: dict[str, Any], evaluation_pass: bool, fatal_error: Exception | None
) -> dict[str, Any]:
    return {
        "model_identity": runs[0].get("model_identity") if runs else None,
        "roster_execution": _roster_execution_identity(facts_fixture),
        "evaluation_pass": evaluation_pass,
        "production_gate_eligible": False,
        "fatal_error_type": type(fatal_error).__name__ if fatal_error else None,
        "fatal_error_message": _safe_error_message(fatal_error) if fatal_error else None,
    }


def _report_run_status(
    runs: list[dict[str, Any]], expected_runs: set[str], fatal_error: Exception | None
) -> str:
    if fatal_error or any(run.get("status") == "runner_error" for run in runs):
        return "runner_error"
    observed_runs = [run.get("run_id") for run in runs]
    if len(observed_runs) != len(expected_runs) or set(observed_runs) != expected_runs:
        return "incomplete"
    return "completed"


def _report_passes(runs: list[dict[str, Any]], status: str) -> bool:
    return status == "completed" and all(run.get("passed") is True for run in runs)


def _dataset_identity(templates_fixture: dict[str, Any], run_count: int) -> dict[str, Any]:
    return {
        "templates_file": TEMPLATE_PATH.name,
        "facts_file": FACTS_PATH.name,
        "source_review_status": templates_fixture["source_review_status"],
        "base_template_count": templates_fixture["base_template_count"],
        "evaluated_run_count": run_count,
        "template_fixture_sha256": _canonical_hash(templates_fixture["templates"]),
    }


def _context_identities(facts_fixture: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        "single_player": {
            "fixture_id": facts_fixture["fixture_id"] + ":single-player",
            "sha256": _canonical_hash(facts_fixture["single_player"]),
        },
        "roster": {
            "fixture_id": facts_fixture["fixture_id"] + ":roster",
            "sha256": _canonical_hash(facts_fixture["roster"]),
        },
    }


def _roster_execution_identity(facts_fixture: dict[str, Any]) -> dict[str, Any]:
    return {
        "briefing": "harness_built_synthetic_briefing",
        "production_roster_ai_available": False,
        "production_roster_conversation_exercised": False,
        "needle_player_id": facts_fixture["needle_player_id"],
    }


__all__ = [
    "FACTS_PATH",
    "TEMPLATE_PATH",
    "build_report",
    "build_roster_briefing",
    "evaluate_answer",
    "expand_cases",
    "expected_truth",
    "load_facts",
    "load_templates",
    "mock_answer",
    "run_suite",
    "write_report",
]
