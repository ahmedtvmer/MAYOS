"""Run the owner-reviewed Arabic cases through deterministic or graph evaluation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DATASET = ROOT / "tests/eval/datasets/arabic_reviewed_cases.json"
SCENARIOS = ROOT / "tests/eval/datasets/arabic_scenarios.json"
NON_WESTERN_DIGITS = re.compile(r"[٠-٩۰-۹]")
ARABIC_SCRIPT = re.compile(r"[\u0600-\u06ff]")
WEIGHT_UNIT_PATTERN = r"(?:kg|كجم|كيلوغرام|كيلوجرام)"
ARABIC_DIALECT_MARKER_PREFIXES = {
    "عايز": ("و", "ف"), "عاوز": ("و", "ف"), "إزاي": ("و", "ف"), "ازاي": ("و", "ف"),
    "إيه": ("و", "ف"), "ايه": ("و", "ف"), "بتاع": ("و", "ف"), "كده": ("و", "ف"),
    "ده": ("و", "ف"), "دي": ("و", "ف"), "قوي": ("ب",),
}
_TREND_CLAIM = re.compile(
    r"\b(?:improv\w*|increas\w*|rais\w*|rose|risen|declin\w*|decreas\w*|fell|fallen|dropp\w*|worsen\w*|"
    r"went up|went down|got better|got worse)\b|"
    r"(?<![\u0600-\u06ff])(?:يتحسن|تحسن(?:ت|وا)?|ازداد(?:ت)?|زاد(?:ت)?|ارتفع(?:ت)?|انخفض(?:ت)?|"
    r"تراجع(?:ت)?|قل(?:ت)?)(?![\u0600-\u06ff])",
    re.IGNORECASE,
)
_TREND_NEGATION = re.compile(
    r"(?:\b(?:not|never|cannot|can't|unable to|did not|does not|do not|no evidence to confirm|"
    r"cannot confirm|can't confirm|no|without)\s*$|لا\s+(?:أستطيع|يمكنني|يمكن)\s+(?:أن\s+)?(?:أؤكد|تأكيد|الجزم|القول)\s*$|"
    r"لا\s+(?:يوجد|توجد)\s*$|لم\s*$|ما\s*$)",
    re.IGNORECASE,
)


def evaluation_status(mode: str, api_key: str | None, recorded: int, expected: int, *, runner_error: bool = False, behavior_failure: bool = False) -> str:
    if runner_error:
        return "runner_error"
    if mode == "real" and not api_key:
        return "missing_credentials"
    if recorded < expected:
        return "incomplete"
    return "behavior_failures" if behavior_failure else "completed"


def cases_from(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [*data["player_messages"], *data["franco_fail_closed"]]


def _model_identity() -> dict[str, str | None]:
    from utils import model_downloader

    model_id, _provider = model_downloader.model_identity("production")
    return {"provider": "openai-compatible", "model": model_id, "revision": None}


def _verify_loaded_production_model(identity: dict[str, Any]) -> str | None:
    from utils import model_downloader

    model = model_downloader._llm_instance
    if model is None:
        return "Assistant graph did not load the configured production player model."
    if not isinstance(model, model_downloader.SafeChatOpenAI):
        return "Assistant graph did not load the configured hosted production model."
    loaded_name = getattr(model, "model_name", None) or getattr(model, "model", None)
    if loaded_name != identity.get("model"):
        return "Loaded hosted model identity does not match the configured production model."
    return None


def load_scenarios() -> dict[str, Any]:
    data = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    defaults = data.get("default_seed_program", {})
    for group in (data.get("cases", {}), data.get("smoke_scenarios", {})):
        for scenario in group.values():
            overrides = scenario.pop("seed_program_overrides", {})
            scenario["seed_program"] = defaults | overrides
    return data


def validate_scenarios(cases: list[dict[str, Any]], scenario_data: dict[str, Any]) -> None:
    mapping = scenario_data.get("cases", {})
    missing = []
    for case in cases:
        if case.get("expected_intent") in {"exercise_history", "exercise_substitution", "program_mutation"} and case["id"] not in mapping:
            missing.append(case["id"])
    if missing:
        raise ValueError("Missing Arabic scenarios for case IDs: " + ", ".join(missing))


def _program_facts(ledger: Any) -> dict[str, Any] | None:
    program = ledger.get_active_program()
    if program is None:
        return None
    return {"version": program.version, "program_name": program.program_name, "split_type": program.split_type,
            "weekly_frequency": program.weekly_frequency, "published_by_coach_account_id": program.published_by_coach_account_id,
            "days": [{"day_name": day.day_name, "exercises": [{"exercise_id": ex.exercise_id, "exercise_name": ex.exercise_name,
                "target_sets": ex.target_sets, "target_reps_min": ex.target_reps_min, "target_reps_max": ex.target_reps_max,
                "target_rpe": ex.target_rpe, "rest_seconds": ex.rest_seconds} for ex in day.exercises]} for day in program.days]}


def _effect_pass(effect: dict[str, Any], before: dict[str, Any] | None, after: dict[str, Any] | None) -> tuple[bool, dict[str, Any]]:
    kind = effect["kind"]
    if kind == "no_change":
        return before == after, {"kind": kind, "unchanged": before == after}
    if before is None or after is None:
        return False, {"kind": kind, "reason": "active program missing"}
    version_advanced = after["version"] is not None and before["version"] is not None and after["version"] > before["version"]
    if kind == "rebuild_frequency":
        matched = after["weekly_frequency"] == effect["target_weekly_frequency"] and version_advanced
        return matched, {"kind": kind, "requested_frequency": effect["target_weekly_frequency"], "observed_frequency": after["weekly_frequency"], "version_advanced": version_advanced}
    if kind == "rebuild_split":
        wanted = re.sub(r"[^a-z]", "", effect["target_split_type"].lower())
        got = re.sub(r"[^a-z]", "", after["split_type"].lower())
        frequency_ok = after["weekly_frequency"] == effect["target_weekly_frequency"]
        matched = wanted in got and frequency_ok and version_advanced
        return matched, {"kind": kind, "requested_split": effect["target_split_type"], "observed_split": after["split_type"], "requested_frequency": effect["target_weekly_frequency"], "observed_frequency": after["weekly_frequency"], "version_advanced": version_advanced}
    if kind == "substitution":
        target_day = next((d for d in after["days"] if d["day_name"] == effect["day"]), None)
        names = [e["exercise_name"].lower() for e in target_day["exercises"]] if target_day else []
        source_left = effect["source"].lower() in names
        target_found = effect["target"].lower() in names
        matched = target_found and not source_left and version_advanced
        return matched, {"kind": kind, "day": effect["day"], "source": effect["source"], "target": effect["target"], "target_present": target_found, "source_remains": source_left, "version_advanced": version_advanced}
    raise ValueError(f"Unknown expected program effect: {kind}")


def _score_history(history: dict[str, Any], reply: str, seeded_facts: dict[str, Any]) -> dict[str, Any]:
    expectation = history["expectation"]
    folded = reply.casefold()
    aliases = [alias for alias in expectation.get("aliases", []) if alias.casefold() in folded]
    kind = expectation["kind"]
    role_validation = _validate_history_number_roles(reply, seeded_facts)
    numbers_grounded = role_validation["all_numbers_bound_to_seeded_role"]
    exercise_binding = _validate_exercise_binding(reply, expectation, seeded_facts)
    if kind == "fact":
        value = str(expectation["value"])
        unit = expectation.get("unit", "")
        units = WEIGHT_UNIT_PATTERN if unit.casefold() in {"kg", "كجم", "كيلوغرام", "كيلوجرام"} else re.escape(unit)
        metric_found = bool(re.search(rf"(?<!\d){re.escape(value)}(?:\.0)?\s*{units}(?![\w])", reply, re.IGNORECASE))
        passed = bool(aliases) and metric_found and numbers_grounded and exercise_binding["all_claims_bound_to_requested_exercise"]
        return {"kind": kind, "exercise_mentioned": bool(aliases), "expected_value": expectation["value"], "unit": unit, "value_bound_to_exercise_reply": metric_found, **role_validation, **exercise_binding, "passed": passed}
    if kind == "missing_data":
        no_data = any(marker.casefold() in folded for marker in expectation["no_data_markers"])
        passed = bool(aliases) and no_data and not re.search(r"\d", reply) and exercise_binding["all_claims_bound_to_requested_exercise"]
        return {"kind": kind, "exercise_mentioned": bool(aliases), "honest_no_data": no_data, **role_validation, **exercise_binding, "passed": passed}
    if kind == "comparison":
        limitation = any(marker.casefold() in folded for marker in expectation.get("limitation_markers", []))
        if limitation:
            passed = bool(aliases) and numbers_grounded and not re.search(r"\d", reply) and exercise_binding["all_claims_bound_to_requested_exercise"]
            return {"kind": kind, "exercise_mentioned": bool(aliases), "comparison_unavailable_honestly": True, "all_reply_numbers_seeded": numbers_grounded, **role_validation, **exercise_binding, "passed": passed}
        facts = expectation["facts"]  # ordered oldest to newest
        values = []
        positions = []
        for fact in facts:
            weight_match = re.search(rf"(?<!\d){fact['weight_kg']}\s*{WEIGHT_UNIT_PATTERN}(?![\w])", reply, re.IGNORECASE)
            kg = bool(weight_match)
            reps = bool(re.search(rf"{fact['reps']}\s*(?:reps?|تكرارات|تكرار)\b", reply, re.IGNORECASE))
            values.append(kg and reps)
            positions.append(weight_match.start() if weight_match else -1)
        compared = any(marker.casefold() in folded for marker in expectation["comparison_markers"])
        chronological = len(positions) == 2 and positions[0] >= 0 and positions[1] > positions[0]
        direction = expectation["direction"]
        direction_markers = {
            "increase": ("ارتفع", "زاد", "increased", "rose"),
            "decrease": ("انخفض", "تراجع", "قل", "decreased", "fell", "dropped"),
            "no_change": ("لم يتغير", "بقي", "ثابت", "unchanged", "stayed"),
        }
        direction_found = any(marker.casefold() in folded for marker in direction_markers[direction])
        passed = bool(aliases) and all(values) and compared and chronological and direction_found and numbers_grounded and exercise_binding["all_claims_bound_to_requested_exercise"]
        return {"kind": kind, "exercise_mentioned": bool(aliases), "comparison_unavailable_honestly": False, "each_seeded_session_fact_present": values, "chronological_oldest_to_newest": chronological, "expected_direction": direction, "direction_stated": direction_found, "comparison_scope_explicit": compared, "all_reply_numbers_seeded": numbers_grounded, **role_validation, **exercise_binding, "passed": passed}
    if kind == "unsupported_monthly_scope":
        scope = any(marker.casefold() in folded for marker in expectation["scope_markers"])
        limited = any(marker.casefold() in folded for marker in expectation["limitation_markers"])
        trend_claim = _has_affirmative_trend_claim(reply)
        passed = bool(aliases) and scope and limited and not trend_claim and numbers_grounded and exercise_binding["all_claims_bound_to_requested_exercise"]
        return {"kind": kind, "exercise_mentioned": bool(aliases), "monthly_scope_named": scope, "limitation_honest": limited, "affirmative_trend_claim": trend_claim, "all_reply_numbers_seeded": numbers_grounded, **role_validation, **exercise_binding, "passed": passed}
    raise ValueError(f"Unknown history expectation: {kind}")


def _validate_history_number_roles(reply: str, seeded_facts: dict[str, Any]) -> dict[str, Any]:
    """Require every numeric claim to use a seeded value in its matching role."""
    role_values: dict[str, set[str]] = {"weight": set(), "reps": set(), "rir": set()}
    for fact in seeded_facts.values():
        if not isinstance(fact, dict):
            continue
        for role, key in (("weight", "weight_kg"), ("reps", "reps"), ("rir", "rir")):
            if key in fact:
                value = float(fact[key])
                role_values[role].add(str(int(value)) if value.is_integer() else str(value))

    patterns = {
        "weight": re.compile(rf"(?<!\d)(?P<n>\d+(?:\.\d+)?)\s*{WEIGHT_UNIT_PATTERN}(?![\w])", re.IGNORECASE),
        "reps": re.compile(r"(?<!\d)(?P<n>\d+(?:\.\d+)?)\s*(?:reps?|تكرارات|تكرار)(?![\w])", re.IGNORECASE),
        "rir": re.compile(r"(?:\bRIR\s*(?P<a>\d+(?:\.\d+)?)|(?P<b>\d+(?:\.\d+)?)\s*RIR\b)", re.IGNORECASE),
    }
    numbers = list(re.finditer(r"\d+(?:\.\d+)?", reply))
    invalid: list[str] = []
    bound: dict[int, set[str]] = {}
    for role, pattern in patterns.items():
        for match in pattern.finditer(reply):
            value = match.groupdict().get("n") or match.groupdict().get("a") or match.groupdict().get("b")
            normalized = str(int(float(value))) if float(value).is_integer() else str(float(value))
            if normalized not in role_values[role]:
                invalid.append(f"{normalized}:{role}")
            for number in numbers:
                if match.start() <= number.start() and number.end() <= match.end():
                    bound.setdefault(number.start(), set()).add(role)
    for number in numbers:
        roles = bound.get(number.start(), set())
        normalized = str(int(float(number.group()))) if float(number.group()).is_integer() else str(float(number.group()))
        if not roles:
            invalid.append(f"{normalized}:untyped")
        elif all(normalized not in role_values[role] for role in roles):
            invalid.append(f"{normalized}:wrong-role")
    return {"all_numbers_bound_to_seeded_role": not invalid, "unbound_or_misbound_numbers": invalid}


def _validate_exercise_binding(reply: str, expectation: dict[str, Any], seeded_facts: dict[str, Any]) -> dict[str, Any]:
    """Bind numeric and no-data claims to the nearest exercise in their clause."""
    exercise_aliases: dict[str, str] = {}
    for alias in expectation.get("aliases", []):
        exercise_aliases[alias.casefold()] = "requested"
    for fact in seeded_facts.values():
        if not isinstance(fact, dict) or not fact.get("exercise"):
            continue
        name = str(fact["exercise"]).casefold()
        exercise_aliases[name] = "requested" if name in exercise_aliases or name.removeprefix("barbell ") in exercise_aliases else name
        shortened = name.removeprefix("barbell ")
        exercise_aliases[shortened] = "requested" if shortened in exercise_aliases or name in exercise_aliases and exercise_aliases[name] == "requested" else name
    exercise_pattern = re.compile("|".join(re.escape(name) for name in sorted(exercise_aliases, key=len, reverse=True)), re.IGNORECASE)
    claim_patterns = (
        re.compile(rf"(?<!\d)\d+(?:\.\d+)?\s*{WEIGHT_UNIT_PATTERN}(?![\w])", re.IGNORECASE),
        re.compile(r"(?<!\d)\d+(?:\.\d+)?\s*(?:reps?|تكرارات|تكرار)(?![\w])", re.IGNORECASE),
        re.compile(r"(?:\bRIR\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*RIR\b)", re.IGNORECASE),
    )
    no_data_pattern = re.compile(r"no recorded|no data|has no (?:recorded )?(?:weight|history|data)|لا توجد(?: لدي)? بيانات(?: مسجلة)?|لا أملك بيانات|لا تتوفر(?: لدي)? بيانات مسجلة", re.IGNORECASE)
    bad_bindings: list[str] = []
    conflicts: list[str] = []
    for segment in re.split(r"[.!?؛،,\n]+", reply):
        mentions = [(match.start(), match.end(), match.group(0).casefold()) for match in exercise_pattern.finditer(segment)]
        if not mentions:
            if any(pattern.search(segment) for pattern in claim_patterns):
                bad_bindings.append(segment.strip())
            continue

        def nearest_role(position: int) -> str:
            _, _, name = min(mentions, key=lambda mention: min(abs(position - mention[0]), abs(position - mention[1])))
            return exercise_aliases[name]

        comparison_limitation = expectation.get("kind") == "comparison" and any(
            marker.casefold() in reply.casefold() for marker in expectation.get("limitation_markers", [])
        )
        if expectation.get("kind") not in {"missing_data", "unsupported_monthly_scope"} and not comparison_limitation:
            for marker in no_data_pattern.finditer(segment):
                if nearest_role(marker.start()) == "requested":
                    conflicts.append(segment.strip())
        for pattern in claim_patterns:
            for claim in pattern.finditer(segment):
                if nearest_role(claim.start()) != "requested":
                    bad_bindings.append(segment.strip())
    valid = not bad_bindings and not conflicts
    return {"all_claims_bound_to_requested_exercise": valid, "claims_attributed_to_other_exercises": bad_bindings,
            "requested_exercise_claimed_missing_data": conflicts}


def _has_affirmative_trend_claim(reply: str) -> bool:
    folded = reply.casefold()
    for match in _TREND_CLAIM.finditer(folded):
        prefix = folded[max(0, match.start() - 48):match.start()]
        if not _TREND_NEGATION.search(prefix):
            return True
    return False


def _arabic_dialect_markers(reply: str) -> list[str]:
    markers: list[str] = []
    arabic_letter = r"\u0600-\u06ff"
    for marker, prefixes in ARABIC_DIALECT_MARKER_PREFIXES.items():
        optional_prefix = rf"(?:{'|'.join(map(re.escape, prefixes))})?" if prefixes else ""
        pattern = re.compile(rf"(?<![{arabic_letter}]){optional_prefix}{re.escape(marker)}(?![{arabic_letter}])")
        if pattern.search(reply):
            markers.append(marker)
    return markers


def _seed_program(store: Any, ledger: Any, scenario: dict[str, Any], *, coach_authority: bool = False) -> None:
    from datetime import UTC, datetime, timedelta
    from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema

    names = scenario["seed_program"]["exercise_names"]
    found = [store.find_exercises_by_name(name, limit=1)[0] for name in names]
    exercises = [ProgramExerciseSchema(exercise_id=item["id"], exercise_name=item["name"], target_reps_min=5,
                                       target_reps_max=8).model_dump() for item in found]
    seed = scenario.get("seed_program", {})
    program = GeneratedProgramSchema(program_name="Synthetic evaluation program", split_type=seed.get("split_type", "Full Body"), weekly_frequency=seed.get("weekly_frequency", 4),
        published_by_coach_account_id="synthetic-coach" if coach_authority else None,
        created_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        days=[ProgramDaySchema(day_name="Full A", day_order=1, exercises=exercises).model_dump()])
    ledger.save_training_program(program.model_dump(), published_by_coach_account_id="synthetic-coach" if coach_authority else None)


def _seed_history(store: Any, ledger: Any, scenario: dict[str, Any]) -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4
    history = scenario.get("history")
    if not history:
        return {}
    seeded: dict[str, Any] = {}
    program = ledger.get_active_program()
    now = datetime.now(UTC)
    workouts = history.get("seed_workouts", [])
    for index, workout in enumerate(workouts):
        exercise = store.find_exercises_by_name(workout["exercise"], limit=1)[0]
        date = now - timedelta(days=index * 7)
        session_id = str(uuid4())
        ledger.log_workout_session(session_id, date.date().isoformat(), "Full A", date.isoformat(), date.isoformat(),
                                   readiness_score=4, program_version=program.version if program else None)
        ledger.log_workout_set(str(uuid4()), session_id, exercise["id"], 1, float(workout["weight_kg"]), int(workout["reps"]), 8.0)
        seeded[f"{workout['exercise']}#{index + 1}"] = dict(workout) | {"exercise_id": exercise["id"], "volume_kg": workout["weight_kg"] * workout["reps"], "rir": 2, "set_index": 1}
    if workouts:
        latest_date = now.date().isoformat()
        latest_workouts = [workout for workout in workouts if workout is workouts[0]]
        seeded["session"] = {"session_date": latest_date, "readiness": 4, "working_sets": len(latest_workouts), "volume_kg": sum(w["weight_kg"] * w["reps"] for w in latest_workouts), "rir": 2}
    return seeded


def _synthetic_store(base: Path):
    from database.database_manager import DEFAULT_CATALOG_PATH, DatabaseManager

    catalog = base / "catalog.db"
    shutil.copyfile(DEFAULT_CATALOG_PATH, catalog)
    return DatabaseManager(catalog_path=catalog, ledgers_dir=base / "users", backups_dir=base / "backups")


def _fake_generation(scenario: dict[str, Any], **kwargs):
    """Deterministic program-generation boundary for plumbing mode."""
    from agent.ProgramState import GeneratedProgramSchema

    ledger = kwargs["ledger"]
    current = ledger.get_active_program()
    effect = scenario["expected_program_effect"]
    desired = effect.get("target_weekly_frequency") or kwargs.get("frequency_override") or (current.weekly_frequency if current else 3)
    source = current.model_dump() if current else {"program_name": "Synthetic program", "split_type": "custom", "days": []}
    source.update(program_name="Synthetic rebuilt program", weekly_frequency=desired, version=None, created_at=None)
    if effect.get("target_split_type"):
        source["split_type"] = effect["target_split_type"]
    source.pop("published_by_coach_account_id", None)
    program = GeneratedProgramSchema(**source)
    ledger.save_training_program(program.model_dump())
    return program, "synthetic-context"


def _run_one(case: dict[str, Any], scenario: dict[str, Any], store: Any, *, mode: str, coach_authority: bool = False) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage
    from agent import assistant_graph as graph
    from unittest.mock import patch

    ledger_id = case["id"] + ("-coach" if coach_authority else "")
    with store.open_ledger(ledger_id) as ledger:
        _seed_program(store, ledger, scenario, coach_authority=coach_authority)
        seeded_facts = _seed_history(store, ledger, scenario)
        before = _program_facts(ledger)
        if coach_authority:
            store.get_active_assignment_for_player = lambda _player_id: {"coach_account_id": "synthetic-coach", "started_at": "2000-01-01T00:00:00+00:00"}
        state = {"messages": [HumanMessage(content=case["text"])], "trainee_id": ledger_id,
                 "player_account_id": "synthetic-player" if coach_authority else None, "telemetry_context": "Synthetic eval context: bench 80 kg x 5, squat 100 kg x 5; RIR is the effort measure.",
                 "coach_tone": "direct", "custom_instructions": ""}
        from tests.fakes.chat_model import ScriptedChatModel

        turn = RuntimeError("synthetic model failure") if scenario.get("plumbing_raise_model") else scenario.get(
            "plumbing_reply", "سجّل التدريب بناءً على بيانات السجل. استخدم RIR لتقدير التكرارات المتبقية."
        )
        fake_model = ScriptedChatModel([turn])
        patches = [patch.object(graph, "llm", fake_model)] if mode == "plumbing" else []
        if mode == "plumbing":
            patches.append(patch.object(graph, "generate_program_pipeline", side_effect=lambda **kwargs: _fake_generation(scenario, **kwargs)))
        from contextlib import ExitStack
        with ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            reply = "".join(graph.stream_assistant_turn(state, ledger=ledger, store=store))
        after = _program_facts(ledger)
        route = {"intent": state.get("intent"), "intent_metadata": state.get("intent_metadata", {})}
        error_response = _graph_error_response(reply)
        if error_response:
            return {"case_id": case["id"] + ("-coach-authority" if coach_authority else ""), "source_case_id": case["id"],
                "case_status": "runner_error", "error": error_response, "reply": reply,
                **_outcome_fields(case, route, reply)}
        effect = {"kind": "no_change"} if coach_authority and scenario.get("coach_authority") else scenario["expected_program_effect"]
        action_effect_pass, action_effect_observation = _effect_pass(effect, before, after)
        history_scoring = _score_history(scenario["history"], reply, seeded_facts) if scenario.get("history") else None
        dialect_markers = _arabic_dialect_markers(reply)
        latest_arabic = bool(ARABIC_SCRIPT.search(case["text"]))
        required_terms = scenario.get("quality_expectations", {}).get("required_reply_terms", [])
        return {"case_id": case["id"] + ("-coach-authority" if coach_authority else ""), "source_case_id": case["id"],
            "case_status": "completed", **_outcome_fields(case, route, reply),
            "reply": reply, "program_facts_before": before, "program_facts_after": after,
            "program_fact_diff": {"before": before, "after": after, "effect": action_effect_observation},
            "action_effect_pass": action_effect_pass,
            "history_scoring": history_scoring,
            "arabic_quality": {"arabic_script_when_arabic_input": (not latest_arabic) or bool(ARABIC_SCRIPT.search(reply)),
                "western_digits_only": not bool(NON_WESTERN_DIGITS.search(reply)), "rir_preserved": ("RIR" in reply) if "RIR" in required_terms else None,
                "english_exercise_name_preserved": all(term.lower() in reply.lower() for term in ("bench press",) if term in case["text"].lower()),
                "required_reply_terms": {term: term.casefold() in reply.casefold() for term in scenario.get("quality_expectations", {}).get("required_reply_terms", [])},
                "simple_standard_arabic_heuristic": not dialect_markers, "dialect_markers": dialect_markers},
            "fact_diff_pass": action_effect_pass,
            "expected_intent_match": route["intent"] == case.get("expected_intent")}


def _outcome_fields(case: dict[str, Any], route: dict[str, Any], reply: str) -> dict[str, Any]:
    observed_intent = route.get("intent")
    return {"expected_clinical_intercept_warranted": case["clinical_intercept_warranted"],
        "launch_block_expected": case["launch_block_expected"], "launch_response_kind": case["launch_response_kind"],
        "expected_intent": case.get("expected_intent"), "observed_intent": observed_intent,
        "observed_blocking": observed_intent == "clinical_intercept",
        "observed_response_kind": _response_kind(case, reply, route)}


def _graph_error_response(reply: str) -> str | None:
    from utils.text_scrubber import EMPTY_RESPONSE_FALLBACK, PIPELINE_ERROR_RESPONSE

    for marker in (PIPELINE_ERROR_RESPONSE, EMPTY_RESPONSE_FALLBACK):
        if marker in reply:
            return f"Assistant graph returned error response: {marker}"
    return None


def _response_kind(case: dict[str, Any], reply: str, route: dict[str, Any]) -> str:
    if case["launch_response_kind"] == "input_language_refusal":
        from agent.prompts import FRANCO_ARABIC_INPUT_RESPONSE
        return "input_language_refusal" if reply == FRANCO_ARABIC_INPUT_RESPONSE else "normal_assistant"
    if route.get("intent_metadata", {}).get("mode") == "diagnosis":
        return "diagnosis_safeguard"
    if route.get("intent") == "clinical_intercept":
        return "clinical_safeguard"
    return "normal_assistant"


def _has_behavior_failure(row: dict[str, Any]) -> bool:
    if row.get("case_status") != "completed":
        return False
    return (
        row.get("observed_blocking") != row.get("launch_block_expected")
        or row.get("observed_response_kind") != row.get("launch_response_kind")
        or (row.get("expected_intent") and row.get("observed_intent") != row.get("expected_intent"))
        or not row.get("action_effect_pass", True)
        or (row.get("history_scoring") is not None and not row["history_scoring"]["passed"])
    )


def _run_evaluation() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("deterministic", "plumbing", "real"), default="deterministic")
    parser.add_argument("--report", type=Path, required=False)
    args = parser.parse_args()
    report_path = args.report.resolve() if args.report else None
    os.makedirs("/tmp/mayos-arabic-eval", exist_ok=True)
    os.chdir("/tmp/mayos-arabic-eval")
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    cases = cases_from(data)
    scenario_data = load_scenarios()
    validate_scenarios(cases, scenario_data)
    mode_name = {"deterministic": "deterministic_guard_checks", "plumbing": "graph_fake_model_plumbing", "real": "real_configured_model"}[args.mode]
    model_identity = _model_identity() if args.mode == "real" else None
    preflight = evaluation_status(args.mode, os.getenv("LLM_API_KEY"), 0, len(cases))
    if preflight == "missing_credentials":
        status, rows = "missing_credentials", []
    else:
        status, rows = "completed", []
        runner_exception = False
        try:
            os.makedirs("/tmp/logs", exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="mayos-arabic-eval-") as temp:
                store = _synthetic_store(Path(temp))
                try:
                    for case in cases:
                        scenario = scenario_data["cases"][case["id"]]
                        if args.mode == "deterministic":
                            from agent.assistant_graph import router_node
                            from langchain_core.messages import HumanMessage
                            route = router_node({"messages": [HumanMessage(content=case["text"])], "telemetry_context": ""})
                            reply = ""
                            if route.get("intent") == "clinical_intercept":
                                from agent.assistant_graph import clinical_intercept_node
                                reply = clinical_intercept_node({"messages": [HumanMessage(content=case["text"])], **route})["response_content"]
                            rows.append({"case_id": case["id"], "case_status": "completed", **_outcome_fields(case, route, reply), "reply": reply})
                        else:
                            rows.append(_run_one(case, scenario, store, mode=args.mode))
                    if args.mode == "plumbing":
                        smoke_cases = scenario_data.get("smoke_scenarios", {})
                        for smoke_id, configured_scenario in smoke_cases.items():
                            parent = smoke_cases.get(configured_scenario.get("inherits"), {})
                            smoke_scenario = parent | configured_scenario
                            base_id = smoke_scenario.get("case_id", smoke_id)
                            smoke_case = {"id": base_id, "text": smoke_scenario["text"], "expected_intent": smoke_scenario["expected_intent"],
                                "clinical_intercept_warranted": False, "launch_block_expected": False, "launch_response_kind": "normal_assistant"}
                            action_scenario = scenario_data["cases"].get(base_id, smoke_scenario) | smoke_scenario
                            rows.append(_run_one(smoke_case, action_scenario, store, mode="plumbing", coach_authority=smoke_scenario.get("coach_authority", False)))
                finally:
                    store.catalog_conn.close()
        except Exception as exc:
            runner_exception = True
            safe_error = re.sub(r"(?i)(api[_-]?key|authorization|bearer)(?:\s*[:=]\s*|\s+)[^\s,;]+", r"\1=[REDACTED]", str(exc))
            rows.append({"case_status": "runner_error", "error": f"{type(exc).__name__}: {safe_error}"})
        completed = len([r for r in rows if r.get("case_status") == "completed"])
        behavior_failure = any(_has_behavior_failure(r) for r in rows)
        status = evaluation_status(args.mode, os.getenv("LLM_API_KEY"), completed, len(cases), runner_error=runner_exception or any(r.get("case_status") == "runner_error" for r in rows), behavior_failure=behavior_failure)
    real_model_verified = False
    if args.mode == "real" and status in {"completed", "behavior_failures"}:
        verification_error = _verify_loaded_production_model(model_identity or {})
        if verification_error:
            status = "runner_error"
            rows.append({"case_status": "runner_error", "error": verification_error})
        else:
            real_model_verified = True
    false_positives = [r["case_id"] for r in rows if r.get("observed_blocking") and r.get("observed_response_kind") in {"clinical_safeguard", "diagnosis_safeguard"} and r.get("expected_clinical_intercept_warranted") is False]
    missed = [r["case_id"] for r in rows if r.get("launch_block_expected") and not r.get("observed_blocking")]
    prompt = (ROOT / "agent/prompts.py").read_bytes()
    context_identity = hashlib.sha256(DATASET.read_bytes() + SCENARIOS.read_bytes() + b"synthetic-training-context-v1").hexdigest()
    report = {"suite": "arabic_reviewed_41", "status": status, "mode": mode_name, "real_model_run": args.mode == "real" and real_model_verified and status in {"completed", "behavior_failures"},
        "generated_at": datetime.now(timezone.utc).isoformat(), "model": model_identity if args.mode == "real" else {"provider": "deterministic fake", "model": "evaluation fake", "revision": None},
        "prompt_hash_sha256": hashlib.sha256(prompt).hexdigest(), "context_identity_sha256": context_identity, "dataset": str(DATASET.relative_to(ROOT)),
        "total_expected": len(cases), "total_recorded": len([r for r in rows if r.get("case_status") == "completed"]),
        "accepted_false_positive_ids": false_positives, "missed_blocking_ids": missed, "runs": rows}
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if status in {"completed", "behavior_failures", "missing_credentials"} else 1


def main() -> int:
    original_cwd = Path.cwd()
    try:
        return _run_evaluation()
    finally:
        os.chdir(original_cwd)

if __name__ == "__main__":
    raise SystemExit(main())
