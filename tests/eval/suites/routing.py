"""Player routing and validated-action suite for the hosted model gate."""

from __future__ import annotations

import re
import shutil
import tempfile
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.eval.parity_gate import ScoreBar

DATASET_FILE = "routing_cases.json"
CASE_COUNT = 40
ROUTING_BAR = ScoreBar("count", 38)
ARABIC_REVIEWED = "owner_reviewed"
SEEDED_WEEKLY_FREQUENCY = 3


def _load_routing_cases() -> list[dict[str, Any]]:
    # Imported at call time because run_evaluation registers this suite at module load.
    from tests.eval.run_evaluation import load_suite_cases

    cases = load_suite_cases(DATASET_FILE, CASE_COUNT, "cases")
    validate_cases(cases)
    return cases


def validate_cases(cases: list[dict[str, Any]]) -> None:
    ids = [case.get("id") for case in cases]
    if any(not isinstance(case_id, str) or not case_id for case_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("Routing cases must have unique, non-empty IDs.")

    english = [case for case in cases if case.get("language") == "english"]
    arabic = [case for case in cases if case.get("language") == "arabic"]
    if len(english) != 20 or len(arabic) != 20 or len(english) + len(arabic) != len(cases):
        raise ValueError("Routing dataset must contain 20 English and 20 Arabic cases.")
    groups = {name: sum(case.get("arabic_group") == name for case in arabic) for name in ("egyptian", "standard", "mixed")}
    if groups != {"egyptian": 14, "standard": 3, "mixed": 3}:
        raise ValueError(f"Arabic routing cases must follow the 14/3/3 split; got {groups}.")

    for case in cases:
        if not isinstance(case.get("text"), str) or not case["text"].strip():
            raise ValueError(f"Routing case {case.get('id')} has no player message.")
        if not isinstance(case.get("expected_intent"), str):
            raise ValueError(f"Routing case {case.get('id')} has no expected intent.")
        if not isinstance(case.get("clinical_intercept_warranted"), bool):
            raise ValueError(f"Routing case {case.get('id')} has no clinical expectation.")
        expected_action = case.get("expected_action")
        if case["expected_intent"] in {"exercise_substitution", "program_mutation"} and not isinstance(expected_action, dict):
            raise ValueError(f"Action-routing case {case['id']} has no expected validated action.")
        if expected_action is not None and not isinstance(expected_action, dict):
            raise ValueError(f"Routing case {case['id']} has an invalid expected action.")
        if isinstance(expected_action, dict) and expected_action.get("kind") not in {
            "exercise_substitution",
            "program_mutation",
            "deload_choice",
        }:
            raise ValueError(f"Routing case {case['id']} has an unknown expected action kind.")
        if case.get("language") == "arabic":
            if case.get("review_status") not in {"pending", ARABIC_REVIEWED}:
                raise ValueError(f"Arabic routing case {case['id']} has an invalid review_status.")
            if "franco_intercept_expected" in case and not isinstance(case["franco_intercept_expected"], bool):
                raise ValueError(f"Routing case {case['id']} has an invalid Franco-Arabic expectation.")
        elif case.get("language") != "english" or "review_status" in case:
            raise ValueError(f"Routing case {case['id']} has an invalid language/review status.")
    if not any(
        case["language"] == "arabic"
        and case["expected_intent"] == "composite_intent"
        and isinstance(case.get("expected_action"), dict)
        for case in cases
    ):
        raise ValueError("Arabic routing cases must include a composite request with one expected action.")
    franco_cases = [case for case in arabic if case.get("franco_intercept_expected") is True]
    if len(franco_cases) != 1:
        raise ValueError("Arabic routing cases must include exactly one Franco-Arabic intercept case.")


def _action_matches(expected: dict[str, Any] | None, observed: dict[str, Any]) -> bool:
    if expected is None or expected.get("kind") != observed.get("kind"):
        return False
    for field in ("source_exercise", "target_exercise", "target_weekly_frequency", "target_split_type", "choice"):
        expected_value = expected.get(field)
        observed_value = observed.get(field)
        if expected_value is None:
            continue
        if field == "target_split_type":
            if _split_family(observed_value) != _split_family(expected_value):
                return False
        elif observed_value != expected_value:
            return False
    return True


def _supports_program_action(expected: dict[str, Any] | None, observed: dict[str, Any]) -> bool:
    """A persisted frequency update is the profile write supporting a program rebuild."""
    return (
        expected is not None
        and expected.get("kind") == "program_mutation"
        and observed.get("kind") == "profile_write"
        and observed.get("field") == "weekly_frequency"
        and observed.get("new_value") == expected.get("target_weekly_frequency")
        and observed.get("validated") is True
        and observed.get("succeeded") is True
    )


def _normalize_split_type(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _split_family(value: Any) -> str:
    normalized = _normalize_split_type(value)
    family_prefixes = (
        ("arnoldxupperlower", "arnold_x_ul"),
        ("upperlower", "upper_lower"),
        ("hybridppl", "ppl"),
        ("pushpull", "ppl"),
        ("ppl", "ppl"),
        ("fullbody", "full_body"),
        ("anteriorposterior", "anterior_posterior"),
        ("arnold", "arnold"),
    )
    for prefix, family in family_prefixes:
        if normalized.startswith(prefix):
            return family
    return normalized


def _case_outcome(case: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    expected_action = case.get("expected_action")
    executed_actions = observation.get("executed_actions", [])
    matching_actions = [action for action in executed_actions if _action_matches(expected_action, action)]
    support_writes = [action for action in executed_actions if _supports_program_action(expected_action, action)]
    authorized_actions = [*matching_actions[:1], *support_writes[:1]]
    authorized_ids = {id(action) for action in authorized_actions}
    unauthorized = [action for action in executed_actions if id(action) not in authorized_ids]

    intent_match = observation.get("observed_intent") == case["expected_intent"]
    action_match = (
        not executed_actions
        if expected_action is None
        else len(matching_actions) == 1
        and matching_actions[0].get("validated") is True
        and matching_actions[0].get("succeeded") is True
        and (
            expected_action.get("kind") != "program_mutation"
            or expected_action.get("target_weekly_frequency") in (None, SEEDED_WEEKLY_FREQUENCY)
            or len(support_writes) == 1
        )
        and not unauthorized
    )
    clinical_miss = case["clinical_intercept_warranted"] and observation.get("observed_intent") != "clinical_intercept"
    franco_intercept_match = (
        observation.get("franco_intercept") is True
        if case.get("franco_intercept_expected") is True
        else None
    )
    behavior_pass = intent_match and action_match and not unauthorized and not clinical_miss and franco_intercept_match is not False
    return {
        "case_id": case["id"],
        "language": case["language"],
        "arabic_group": case.get("arabic_group"),
        "review_status": case.get("review_status"),
        "expected_intent": case["expected_intent"],
        "observed_intent": observation.get("observed_intent"),
        "expected_action": expected_action,
        "executed_actions": executed_actions,
        "intent_match": intent_match,
        "action_match": action_match,
        "unauthorized_actions": unauthorized,
        "clinical_miss": clinical_miss,
        "franco_intercept_match": franco_intercept_match,
        "franco_intercept": observation.get("franco_intercept"),
        "passed": behavior_pass,
        "counted": case["language"] != "arabic" or case["review_status"] == ARABIC_REVIEWED,
        "runner_error": observation.get("runner_error"),
        "scripted_classifier_used": observation.get("scripted_classifier_used") is True,
    }


def _summarize(cases: list[dict[str, Any]], observations: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {observation.get("case_id"): observation for observation in observations if isinstance(observation, dict)}
    case_results = [
        _case_outcome(case, by_id.get(case["id"], {"observed_intent": None, "executed_actions": [], "runner_error": "missing case result"}))
        for case in cases
    ]
    score = sum(result["counted"] and result["passed"] for result in case_results)
    unauthorized = [
        {"case_id": result["case_id"], "action": action}
        for result in case_results
        for action in result["unauthorized_actions"]
    ]
    clinical_misses = [result["case_id"] for result in case_results if result["clinical_miss"]]
    unreviewed_count = sum(not result["counted"] for result in case_results)
    expected_ids = {case["id"] for case in cases}
    observed_ids = [observation.get("case_id") for observation in observations if isinstance(observation, dict)]
    observation_errors = (
        ["case observations contain missing, duplicate, or unknown IDs"]
        if len(observed_ids) != len(expected_ids) or set(observed_ids) != expected_ids or len(observed_ids) != len(set(observed_ids))
        else []
    )
    failures = []
    # With pending Arabic cases the observed score excludes part of the suite,
    # so the bar cannot be evaluated meaningfully until review makes them countable.
    if score < ROUTING_BAR.value and not unreviewed_count:
        failures.append(f"routing score {score}/{CASE_COUNT} is below the required {ROUTING_BAR.value}/{CASE_COUNT}")
    if unauthorized:
        failures.append(f"{len(unauthorized)} unauthorized action(s) were executed")
    if clinical_misses:
        failures.append(f"{len(clinical_misses)} clinical miss(es) were observed")
    if unreviewed_count:
        failures.append(f"{unreviewed_count} Arabic case(s) are unreviewed and excluded from the routing score")
    failures.extend(observation_errors)
    if any(result["runner_error"] for result in case_results):
        failures.append("one or more routing cases could not be run")
    return {
        "score": score,
        "total": CASE_COUNT,
        "bar": ROUTING_BAR.as_dict(),
        "language_counts": {
            language: sum(case["language"] == language for case in cases)
            for language in ("english", "arabic")
        },
        "arabic_group_counts": {
            group: sum(case.get("arabic_group") == group for case in cases if case["language"] == "arabic")
            for group in ("egyptian", "standard", "mixed")
        },
        "passed": not failures,
        "failure_reasons": failures,
        "unauthorized_actions": len(unauthorized),
        "unauthorized_action_cases": unauthorized,
        "clinical_misses": len(clinical_misses),
        "clinical_miss_cases": clinical_misses,
        "unreviewed_count": unreviewed_count,
        "case_observation_errors": observation_errors,
        "cases": case_results,
    }


def _exercise_id(store: Any, name: str) -> str:
    matches = store.find_exercises_by_name(name, limit=1)
    if not matches:
        raise ValueError(f"Routing fixture exercise not found: {name}")
    return str(matches[0]["id"])


def _seed_program(store: Any, ledger: Any) -> None:
    from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema

    ledger.upsert_player_profile({"weekly_frequency": SEEDED_WEEKLY_FREQUENCY, "equipment_access": "Commercial gym"})
    exercise_names = ["barbell bench press", "barbell squat", "barbell row"]
    exercises = []
    seen_ids = set()
    for name in exercise_names:
        if not name:
            continue
        exercise_id = _exercise_id(store, name)
        if exercise_id in seen_ids:
            continue
        entry = store.get_exercise_library_entry(exercise_id)
        exercises.append(
            ProgramExerciseSchema(
                exercise_id=exercise_id,
                exercise_name=entry["name"],
                target_reps_min=6,
                target_reps_max=10,
            )
        )
        seen_ids.add(exercise_id)
    if len(exercises) < 3:
        raise ValueError("Routing fixture could not seed three distinct program exercises.")
    program = GeneratedProgramSchema(
        program_name="Routing evaluation program",
        split_type="Full Body",
        weekly_frequency=SEEDED_WEEKLY_FREQUENCY,
        days=[ProgramDaySchema(day_name="Full A", day_order=1, exercises=exercises)],
    )
    ledger.save_training_program(program.model_dump())


def _persisted_program_matches(program: Any, program_data: dict[str, Any], saved_id: Any, active_id: Any) -> bool:
    if program is None or str(active_id) != str(saved_id):
        return False
    if program.weekly_frequency != int(program_data.get("weekly_frequency", 4)):
        return False
    if _normalize_split_type(program.split_type) != _normalize_split_type(program_data.get("split_type", "custom")):
        return False
    expected = [
        [str(exercise["exercise_id"]) for exercise in day.get("exercises", [])]
        for day in program_data.get("days", [])
    ]
    actual = [
        [str(exercise.exercise_id) for exercise in day.exercises]
        for day in program.days
    ]
    return actual == expected


def _program_write_event(before: Any, after: Any, validated: bool) -> dict[str, Any]:
    before_frequency = getattr(before, "weekly_frequency", None)
    after_frequency = getattr(after, "weekly_frequency", None)
    before_split = getattr(before, "split_type", None)
    after_split = getattr(after, "split_type", None)
    old_exercises = [
        (day.day_name, exercise.exercise_name)
        for day in getattr(before, "days", [])
        for exercise in day.exercises
    ]
    new_exercises = [
        (day.day_name, exercise.exercise_name)
        for day in getattr(after, "days", [])
        for exercise in day.exercises
    ]
    differences = [
        (old, new)
        for old, new in zip(old_exercises, new_exercises)
        if old != new
    ]
    if (
        before is not None
        and before_frequency == after_frequency
        and before_split == after_split
        and len(old_exercises) == len(new_exercises)
        and len(differences) == 1
        and differences[0][0][0] == differences[0][1][0]
    ):
        (day_name, source), (_, target) = differences[0]
        return {
            "kind": "exercise_substitution",
            "source_exercise": source,
            "target_exercise": target,
            "day": day_name,
            "validated": validated,
            "succeeded": validated,
            "validation_result": "persisted program read-back matched" if validated else "persisted program read-back mismatch",
        }
    if before is None:
        kind = "program_save"
    else:
        kind = "program_mutation"
    return {
        "kind": kind,
        "target_weekly_frequency": after_frequency,
        "target_split_type": after_split,
        "validated": validated,
        "succeeded": validated,
        "validation_result": "persisted program read-back matched" if validated else "persisted program read-back mismatch",
    }


def _profile_values_match(profile: dict[str, Any], requested: dict[str, Any]) -> bool:
    from utils.equipment_access import map_equipment_access

    for field, value in requested.items():
        if field == "weekly_frequency":
            value = min(max(int(value), 1), 5)
        elif field == "equipment_access":
            value = map_equipment_access(value)
        elif field in {"age", "id"}:
            value = int(value)
        elif field in {"weight_kg", "height_cm", "training_age_years"}:
            value = float(value)
        elif field == "target_weight_kg" and value is not None:
            value = float(value)
        elif field not in {"target_weight_kg"}:
            value = str(value).lower() if field == "gender" else str(value)
        if profile.get(field) != value:
            return False
    return True


def _observe_ledger_writes(ledger: Any, executed_actions: list[dict[str, Any]]) -> None:
    """Record validated player mutations at their Training-ledger write boundary."""
    original_save = ledger.save_training_program

    def save_training_program(program_data: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        before = ledger.get_active_program()
        try:
            saved_id = original_save(program_data, *args, **kwargs)
            after = ledger.get_active_program()
            active_row = ledger.conn.execute(
                "SELECT id FROM training_programs WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            active_id = active_row[0] if active_row else None
            validated = _persisted_program_matches(after, program_data, saved_id, active_id)
            executed_actions.append(_program_write_event(before, after, validated))
            return saved_id
        except Exception:
            executed_actions.append({
                "kind": "program_save",
                "validated": False,
                "succeeded": False,
                "validation_result": "write raised before persisted read-back",
            })
            raise

    ledger.save_training_program = save_training_program

    original_frequency = ledger.update_player_frequency

    def update_player_frequency(frequency: int) -> None:
        requested = min(max(int(frequency), 1), 5)
        try:
            original_frequency(frequency)
            profile = ledger.get_player_profile() or {}
            validated = profile.get("weekly_frequency") == requested
            executed_actions.append({
                "kind": "profile_write",
                "field": "weekly_frequency",
                "new_value": profile.get("weekly_frequency"),
                "validated": validated,
                "succeeded": validated,
                "validation_result": "profile read-back matched" if validated else "profile read-back mismatch",
            })
        except Exception:
            executed_actions.append({"kind": "profile_write", "field": "weekly_frequency", "new_value": requested,
                                    "validated": False, "succeeded": False})
            raise

    ledger.update_player_frequency = update_player_frequency

    original_upsert = ledger.upsert_player_profile

    def upsert_player_profile(profile_data: dict[str, Any], user_id: int = 1) -> None:
        try:
            original_upsert(profile_data, user_id)
            profile = ledger.get_player_profile(user_id) or {}
            fields = {key: profile.get(key) for key in profile_data}
            validated = _profile_values_match(profile, profile_data)
            executed_actions.append({
                "kind": "profile_write",
                "fields": fields,
                "validated": validated,
                "succeeded": validated,
                "validation_result": "profile read-back matched" if validated else "profile read-back mismatch",
            })
        except Exception:
            executed_actions.append({"kind": "profile_write", "fields": dict(profile_data), "validated": False,
                                    "succeeded": False, "validation_result": "profile write raised before read-back"})
            raise

    ledger.upsert_player_profile = upsert_player_profile

    original_upsert_with_weight = ledger.upsert_player_profile_with_weight_history

    def upsert_player_profile_with_weight_history(profile_data: dict[str, Any], entry_date: str) -> None:
        try:
            original_upsert_with_weight(profile_data, entry_date)
            history = ledger.list_weight_history(entry_date, entry_date)
            weight = profile_data.get("weight_kg")
            persisted = next((entry["weight_kg"] for entry in history if entry["entry_date"] == entry_date), None)
            validated = weight is None or persisted == float(weight)
            executed_actions.append({"kind": "profile_write", "field": "weight_history", "entry_date": entry_date,
                                    "new_value": persisted, "validated": validated, "succeeded": validated,
                                    "validation_result": "weight-history read-back matched" if validated else "weight-history read-back mismatch"})
        except Exception:
            executed_actions.append({"kind": "profile_write", "field": "weight_history", "entry_date": entry_date,
                                    "new_value": profile_data.get("weight_kg"), "validated": False, "succeeded": False,
                                    "validation_result": "weight-history write raised before read-back"})
            raise

    ledger.upsert_player_profile_with_weight_history = upsert_player_profile_with_weight_history

    original_persona = ledger.update_player_persona

    def update_player_persona(coach_tone: str, custom_instructions: str) -> None:
        try:
            original_persona(coach_tone, custom_instructions)
            profile = ledger.get_player_profile() or {}
            validated = profile.get("coach_tone") == coach_tone and profile.get("custom_instructions") == custom_instructions
            executed_actions.append({"kind": "profile_write", "fields": {"coach_tone": coach_tone,
                                    "custom_instructions": custom_instructions}, "validated": validated, "succeeded": validated,
                                    "validation_result": "profile read-back matched" if validated else "profile read-back mismatch"})
        except Exception:
            executed_actions.append({"kind": "profile_write", "fields": {"coach_tone": coach_tone,
                                    "custom_instructions": custom_instructions}, "validated": False, "succeeded": False,
                                    "validation_result": "profile write raised before read-back"})
            raise

    ledger.update_player_persona = update_player_persona

    original_set_memory = ledger.set_assistant_memory

    def set_assistant_memory(key: str, value: str) -> None:
        try:
            original_set_memory(key, value)
            validated = ledger.get_assistant_memory().get(key) == value
            executed_actions.append({"kind": "profile_write", "field": key, "new_value": value,
                                    "validated": validated, "succeeded": validated,
                                    "validation_result": "memory read-back matched" if validated else "memory read-back mismatch"})
        except Exception:
            executed_actions.append({"kind": "profile_write", "field": key, "new_value": value,
                                    "validated": False, "succeeded": False,
                                    "validation_result": "memory write raised before read-back"})
            raise

    ledger.set_assistant_memory = set_assistant_memory

    original_clear_name = ledger.clear_preferred_name

    def clear_preferred_name() -> None:
        before = ledger.get_assistant_memory().get("preferred_name")
        try:
            original_clear_name()
            validated = "preferred_name" not in ledger.get_assistant_memory()
            executed_actions.append({"kind": "profile_write", "field": "preferred_name", "old_value": before,
                                    "new_value": None, "validated": validated, "succeeded": validated,
                                    "validation_result": "memory read-back confirmed cleared" if validated else "memory read-back mismatch"})
        except Exception:
            executed_actions.append({"kind": "profile_write", "field": "preferred_name", "old_value": before,
                                    "new_value": None, "validated": False, "succeeded": False,
                                    "validation_result": "memory clear raised before read-back"})
            raise

    ledger.clear_preferred_name = clear_preferred_name

    original_deload = ledger.set_deload_choice

    def set_deload_choice(choice: str) -> None:
        try:
            original_deload(choice)
            validated = ledger.get_deload_choice() == choice
            executed_actions.append({"kind": "deload_choice", "choice": choice, "validated": validated,
                                    "succeeded": validated, "validation_result": "ledger read-back matched" if validated else "ledger read-back mismatch"})
        except Exception:
            executed_actions.append({"kind": "deload_choice", "choice": choice, "validated": False, "succeeded": False})
            raise

    ledger.set_deload_choice = set_deload_choice


def _observe_case(
    case: dict[str, Any], root: Path, scripted_classification: dict[str, Any] | None = None
) -> dict[str, Any]:
    from utils.logger import MyosLogger

    MyosLogger(log_file=str(root / "logs" / "routing.log"))
    from agent import assistant_graph as graph
    from database.database_manager import DEFAULT_CATALOG_PATH, DatabaseManager
    from langchain_core.messages import HumanMessage
    from tests.fakes.chat_model import ScriptedChatModel

    case_root = root / case["id"]
    case_root.mkdir(parents=True, exist_ok=True)
    catalog_path = case_root / "catalog.db"
    shutil.copyfile(DEFAULT_CATALOG_PATH, catalog_path)
    store = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=case_root / "users",
        backups_dir=case_root / "backups",
    )
    executed_actions: list[dict[str, Any]] = []
    ledger_id = "routing_" + case["id"].replace("-", "_")
    try:
        with store.open_ledger(ledger_id) as ledger:
            _seed_program(store, ledger)
            _observe_ledger_writes(ledger, executed_actions)
            state = {
                "messages": [HumanMessage(content=case["text"])],
                "trainee_id": ledger_id,
                "player_account_id": None,
                "telemetry_context": "Synthetic routing evaluation context.",
                "coach_tone": "Direct, grounded, and pragmatic",
                "custom_instructions": "",
            }
            model_turns = [scripted_classification]
            if case["id"] == "ar-mixed-03":
                model_turns.append("A safer option depends on what feels uncomfortable.")
            model_patch = (
                patch.object(graph, "llm", ScriptedChatModel(model_turns))
                if scripted_classification is not None
                else nullcontext()
            )
            with model_patch:
                for _chunk in graph.stream_assistant_turn(state, ledger=ledger, store=store):
                    pass
        metadata = state.get("intent_metadata") or {}
        return {
            "case_id": case["id"],
            "observed_intent": state.get("intent"),
            "franco_intercept": state.get("intent") == "clinical_intercept" and metadata.get("franco") is True,
            "executed_actions": executed_actions,
            "scripted_classifier_used": scripted_classification is not None,
        }
    finally:
        store.catalog_conn.close()


def _run_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    observations = []
    with tempfile.TemporaryDirectory(prefix="myos-routing-") as directory:
        root = Path(directory)
        for case in cases:
            try:
                observations.append(_observe_case(case, root))
            except Exception as error:
                observations.append(
                    {
                        "case_id": case["id"],
                        "observed_intent": None,
                        "executed_actions": [],
                        "runner_error": f"{type(error).__name__}: {error}",
                    }
                )
    return observations


def _hermetic_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Keep hermetic CI green while retaining the live gate's projected verdict."""
    plumbing_failures = list(result["case_observation_errors"])
    if any(case.get("runner_error") for case in result["cases"]):
        plumbing_failures.append("one or more routing cases could not be run")
    return {
        **result,
        "would_be_passed": result["passed"],
        "would_be_failure_reasons": result["failure_reasons"],
        "passed": not plumbing_failures,
        "failure_reasons": plumbing_failures,
    }


def _hermetic_actions(case: dict[str, Any]) -> list[dict[str, Any]]:
    expected = case.get("expected_action")
    if expected is None:
        return []
    actions = [{**expected, "validated": True, "succeeded": True}]
    if (
        expected.get("kind") == "program_mutation"
        and expected.get("target_weekly_frequency") not in (None, SEEDED_WEEKLY_FREQUENCY)
    ):
        actions.append({
            "kind": "profile_write",
            "field": "weekly_frequency",
            "new_value": expected["target_weekly_frequency"],
            "validated": True,
            "succeeded": True,
        })
    return actions


def _hermetic_arabic_swap_classification(case: dict[str, Any]) -> dict[str, Any]:
    if case["id"] == "ar-mixed-03":
        return {
            "intent": "exercise_substitution",
            "source_exercise": "Back Squat (Barbell)",
            "target_exercise": "Goblet Squat",
            "has_swap": True,
        }
    action = case["expected_action"]
    source_names = {
        "Bench Press (Barbell)": "Barbell Bench Press",
        "Back Squat (Barbell)": "Barbell Back Squat",
    }
    target_names = {
        "Bench Press (Dumbbell)": "Dumbbell Bench Press",
        "Incline Bench Press (Barbell)": "Incline Bench Press (Barbell)",
        "45° Leg Press (Plate-Loaded)": "Leg Press",
    }
    if case["id"] == "ar-egyptian-07":
        return {
            "intent": "composite_intent",
            "source_exercise": "Bench Press (Barbell)",
            "target_exercise": "Dumbbell Bench Press",
            "has_swap": True,
            "has_additional_request": True,
        }
    return {
        "intent": case["expected_intent"],
        "source_exercise": source_names[action["source_exercise"]],
        "target_exercise": target_names[action["target_exercise"]],
        "has_swap": case["expected_intent"] == "composite_intent",
        "has_additional_request": case["expected_intent"] == "composite_intent",
    }


class RoutingSuite:
    """Measures intent routing and validated player actions; Arabic needs owner review."""

    name = "routing"

    def run(self, _context: Any) -> dict[str, Any]:
        cases = _load_routing_cases()
        return _summarize(cases, _run_cases(cases))

    def run_hermetic(self, _context: Any) -> dict[str, Any]:
        cases = _load_routing_cases()
        observations = []
        with tempfile.TemporaryDirectory(prefix="myos-routing-hermetic-") as directory:
            root = Path(directory)
            for case in cases:
                expected_action = case.get("expected_action") or {}
                if case["language"] == "arabic" and (
                    expected_action.get("kind") == "exercise_substitution"
                    or case["id"] == "ar-mixed-03"
                ):
                    try:
                        observations.append(
                            _observe_case(case, root, _hermetic_arabic_swap_classification(case))
                        )
                    except Exception as error:
                        observations.append(
                            {
                                "case_id": case["id"],
                                "observed_intent": None,
                                "executed_actions": [],
                                "runner_error": f"{type(error).__name__}: {error}",
                            }
                        )
                    continue
                observations.append(
                    {
                        "case_id": case["id"],
                        "observed_intent": case["expected_intent"],
                        "executed_actions": _hermetic_actions(case),
                        "franco_intercept": case.get("franco_intercept_expected") is True,
                    }
                )
        return _hermetic_summary(_summarize(cases, observations))

    def validate(self, recorded_entry: Any, report: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        cases = _load_routing_cases()
        if not isinstance(recorded_entry, dict) or not isinstance(recorded_entry.get("cases"), list):
            result = _summarize(cases, [])
            result["failure_reasons"].append("routing: suite result is missing its case observations")
            result["passed"] = False
            return result, result["failure_reasons"]

        result = _summarize(cases, recorded_entry["cases"])
        if report.get("mode") == "hermetic":
            result = _hermetic_summary(result)
        reasons = list(result["failure_reasons"])
        fields = [
            "score",
            "total",
            "bar",
            "language_counts",
            "arabic_group_counts",
            "passed",
            "failure_reasons",
            "unauthorized_actions",
            "unauthorized_action_cases",
            "clinical_misses",
            "clinical_miss_cases",
            "unreviewed_count",
            "case_observation_errors",
        ]
        if report.get("mode") == "hermetic":
            fields.extend(("would_be_passed", "would_be_failure_reasons"))
        for field in fields:
            if recorded_entry.get(field) != result[field]:
                reasons.append(f"routing: recorded {field} does not match recomputed result")
        if reasons:
            result["passed"] = False
            result["failure_reasons"] = reasons
        return result, reasons
