"""Measure paired Arabic/English DeepSeek turns and replay trial usage (#262).

Live mode makes explicit hosted-model calls. Validation mode is hermetic and
never loads a model. The report retains synthetic inputs, config identities,
every metered call, completion outcomes, and admission replays; it does not
certify language quality or privacy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DATASET = ROOT / "tests/eval/datasets/trial_usage_workloads_262.json"
DEFAULT_REPORT = ROOT / "reports/trial_usage_262.json"
EXPECTED_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
EXPECTED_RUNTIME = "About 10–20 minutes for ten paired turns at current provider latency; this script is designed to remain below 30 minutes."


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_workloads(path: Path = DATASET) -> dict[str, Any]:
    fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    _validate_workloads(fixture)
    return fixture


def _validate_workloads(fixture: dict[str, Any]) -> None:
    if fixture.get("schema_version") != 1 or fixture.get("issue") != 262:
        raise ValueError("Unsupported trial usage workload fixture.")
    pairs = fixture.get("pairs")
    expected = {
        "short_question",
        "long_history",
        "mixed_language",
        "program_action",
        "coach_analysis",
    }
    if not isinstance(pairs, list) or {item.get("id") for item in pairs} != expected:
        raise ValueError("Trial workload fixture must contain the five paired task types.")
    for pair in pairs:
        if pair.get("review_status") not in {"pending_owner_review", "owner_reviewed"}:
            raise ValueError(f"Missing review status for {pair.get('id', 'unknown')}.")
        if pair.get("english", {}).get("history") is None or pair.get("arabic", {}).get("history") is None:
            raise ValueError(f"Missing conversation history for {pair.get('id', 'unknown')}.")
        if not pair.get("english", {}).get("question") or not pair.get("arabic", {}).get("question"):
            raise ValueError(f"Missing paired questions for {pair.get('id', 'unknown')}.")


def _call_cost(model: str, input_tokens: int, output_tokens: int, cached: int) -> tuple[str, float | None]:
    from utils.model_pricing import compute_cost, price_for

    if price_for(model) is None:
        return "unpriced", None
    return "priced", compute_cost(
        model, input_tokens, output_tokens, cached_input_tokens=cached
    )


def _call_usage(row: dict[str, Any], ordinal: int) -> dict[str, Any]:
    model = str(row.get("model") or "unknown")
    input_tokens = max(0, int(row.get("input_tokens") or 0))
    output_tokens = max(0, int(row.get("output_tokens") or 0))
    cached = max(0, min(input_tokens, int(row.get("cached_input_tokens") or 0)))
    cost_status, cost_usd = _call_cost(model, input_tokens, output_tokens, cached)
    return {
        "call_index": ordinal,
        "model": model,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "usage_source": "marked_estimate" if row.get("estimated") else "provider_reported",
        "estimated": bool(row.get("estimated")),
        "cost_status": cost_status,
        "cost_usd": cost_usd,
    }


def _turn_outcome(error: Exception | None, answer: str, finish_reasons: list[str]) -> str:
    from agent.assistant_graph import OUTPUT_LIMIT_RESPONSE
    from utils.text_scrubber import PIPELINE_ERROR_RESPONSE

    if error is not None or PIPELINE_ERROR_RESPONSE in answer:
        return "error"
    if "length" in finish_reasons:
        return "truncated"
    if OUTPUT_LIMIT_RESPONSE in answer:
        return "truncated"
    if not answer.strip():
        return "empty"
    if not finish_reasons:
        return "completed_finish_reason_unreported"
    return "completed"


def _seed_player(store: Any, ledger: Any) -> None:
    fixture = load_workloads()
    profile = fixture["seed"]["player_profile"]
    ledger.upsert_player_profile(
        profile | {"rep_preference": "balanced", "stress_and_sleep": "normal"}
    )
    _seed_program(store, ledger, fixture["seed"]["program"])


def _seeded_exercise(store: Any, name: str) -> dict[str, Any]:
    from agent.ProgramState import ProgramExerciseSchema

    matches = store.find_exercises_by_name(name, limit=1)
    if not matches:
        raise ValueError(f"Seed exercise is missing from the Exercise library: {name}")
    exercise = matches[0]
    return ProgramExerciseSchema(
        exercise_id=exercise["id"],
        exercise_name=exercise["name"],
        target_reps_min=5,
        target_reps_max=8,
    ).model_dump()


def _seed_program(store: Any, ledger: Any, facts: dict[str, Any]) -> None:
    from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema

    exercises = [_seeded_exercise(store, name) for name in facts["exercise_names"]]
    program = GeneratedProgramSchema(
        program_name=facts["program_name"],
        split_type=facts["split_type"],
        weekly_frequency=facts["weekly_frequency"],
        created_at="2026-10-01T00:00:00+00:00",
        days=[ProgramDaySchema(day_name="Upper A", day_order=1, exercises=exercises).model_dump()],
    )
    ledger.save_training_program(program.model_dump())


@dataclass
class TurnCapture:
    pair: dict[str, Any]
    language: str
    turn_id: str
    account_id: str
    role: str
    purpose: str
    prompt_path: str
    calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reasons: list[str] = field(default_factory=list)
    answer: str = ""
    error: Exception | None = None


@dataclass(frozen=True)
class MeasurementRun:
    fixture: dict[str, Any]
    dataset_path: Path
    identities: dict[str, Any]
    turns: list[dict[str, Any]]
    replays: dict[str, Any]
    run_error: dict[str, str] | None
    cap_decision: dict[str, Any]


def _new_capture(pair: dict[str, Any], language: str) -> TurnCapture:
    role = "coach" if pair["capability"] == "coach" else "player"
    purpose = "coach_assistant" if role == "coach" else "chat"
    return TurnCapture(
        pair=pair,
        language=language,
        turn_id=f"{pair['id']}-{language}",
        account_id=f"synthetic-{language}-{role}",
        role=role,
        purpose=purpose,
        prompt_path=(
            "coach_ai.render_context + build_messages + stream_answer"
            if role == "coach"
            else "chat_service history + assistant_graph.stream_assistant_turn"
        ),
    )


@contextmanager
def _capture_model_usage(capture: TurnCapture, store: Any) -> Iterator[None]:
    from utils.model_metering import UsageContext, scoped_usage_recorder, usage_context

    context = UsageContext(
        account_id=capture.account_id,
        role=capture.role,
        purpose=capture.purpose,
        store=store,
        turn_id=capture.turn_id,
        on_finish_reason=capture.finish_reasons.append,
    )
    with usage_context(context), scoped_usage_recorder(lambda **row: capture.calls.append(row)):
        yield


def _capture_player_turn(
    pair: dict[str, Any], language: str, variant: dict[str, Any], store: Any
) -> dict[str, Any]:
    from agent import assistant_graph
    from service import chat as chat_service

    capture = _new_capture(pair, language)
    with store.open_ledger(capture.turn_id) as ledger:
        state = _prepare_player_state(variant, store, ledger, capture)
        try:
            with _capture_model_usage(capture, store):
                capture.answer = "".join(
                    assistant_graph.stream_assistant_turn(state, ledger=ledger, store=store)
                )
            chat_service.persist_assistant_message(ledger, state.get("response_content"))
        except Exception as exc:  # Provider failures remain visible as incomplete turns.
            capture.error = exc
    return _turn_record(capture)


def _prepare_player_state(
    variant: dict[str, Any], store: Any, ledger: Any, capture: TurnCapture
) -> dict[str, Any]:
    from service import chat as chat_service

    _seed_player(store, ledger)
    _seed_chat_history(ledger, variant["history"])
    history = chat_service.prepare_user_turn(store, variant["question"], ledger)
    profile = ledger.get_player_profile() or {}
    return chat_service.build_turn_state(
        capture.turn_id,
        chat_service.build_tail_messages(history),
        coach_tone=profile.get("coach_tone", "direct"),
        custom_instructions=profile.get("custom_instructions", ""),
        player_account_id=capture.account_id,
    )


def _seed_chat_history(ledger: Any, history: list[dict[str, str]]) -> None:
    for message in history:
        role = "assistant" if message["role"] == "assistant" else "user"
        ledger.add_chat_message(role, message["content"])


def _capture_coach_turn(
    pair: dict[str, Any], language: str, variant: dict[str, Any], store: Any
) -> dict[str, Any]:
    from service import coach_ai

    capture = _new_capture(pair, language)
    messages, context = _coach_messages(coach_ai, variant, language)
    try:
        with _capture_model_usage(capture, store):
            capture.answer = _coach_answer(coach_ai, messages)
    except Exception as exc:
        capture.error = exc
    capture.prompt_path += f"; context_sha256={_sha256(context.encode('utf-8'))}"
    return _turn_record(capture)


def _coach_messages(coach_ai: Any, variant: dict[str, Any], language: str) -> tuple[list[Any], str]:
    context = coach_ai.render_context(coach_ai.CANONICAL_FIXTURE)
    messages = coach_ai.build_messages(
        context,
        variant["question"],
        variant["history"],
        display_language="en" if language == "english" else "ar",
    )
    return messages, context


def _coach_answer(coach_ai: Any, messages: list[Any]) -> str:
    answer = ""
    for kind, payload in coach_ai.stream_answer(messages):
        if kind == "done":
            answer = payload
    return answer


def _turn_record(capture: TurnCapture) -> dict[str, Any]:
    pair = capture.pair
    calls = [_call_usage(row, index) for index, row in enumerate(capture.calls, start=1)]
    return {
        **_turn_identity(capture),
        **_turn_usage(calls),
        "outcome": _turn_outcome(capture.error, capture.answer, capture.finish_reasons),
        "provider_finish_reasons": capture.finish_reasons,
        "answer": capture.answer,
        "error_type": type(capture.error).__name__ if capture.error else None,
        "semantic_outcome": "pending_owner_review",
        "equivalent_successful_work_eligible": False,
        "fixture_review_status": pair["review_status"],
    }


def _turn_identity(capture: TurnCapture) -> dict[str, Any]:
    pair = capture.pair
    return {
        "turn_id": capture.turn_id,
        "pair_id": pair["id"],
        "task_type": pair["task_type"],
        "capability": pair["capability"],
        "language": capture.language,
        "role": capture.role,
        "purpose": capture.purpose,
        "prompt_path": capture.prompt_path,
    }


def _turn_usage(calls: list[dict[str, Any]]) -> dict[str, Any]:
    priced = bool(calls) and all(call["cost_status"] == "priced" for call in calls)
    return {
        "call_count": len(calls),
        "calls": calls,
        "input_tokens": sum(call["input_tokens"] for call in calls),
        "cached_input_tokens": sum(call["cached_input_tokens"] for call in calls),
        "output_tokens": sum(call["output_tokens"] for call in calls),
        "total_tokens": sum(call["total_tokens"] for call in calls),
        "estimated_call_count": sum(call["estimated"] for call in calls),
        "cost_usd": sum(call["cost_usd"] or 0.0 for call in calls) if priced else None,
    }


def _configuration_identity(fixture: dict[str, Any]) -> dict[str, Any]:
    from service import coach_ai
    from utils import model_downloader

    player = model_downloader.model_identity("production")
    coach = model_downloader.model_identity("coach")
    return {
        **_model_configuration(player, coach),
        "trial_admission": _trial_configuration(),
        "pricing": _pricing_configuration(player[0], coach[0]),
        **_review_gates(fixture),
        "coach_prompt_hash": coach_ai.prompt_version_hash(),
        "coach_context_version": coach_ai.CONTEXT_VERSION,
    }


def _model_configuration(
    player: tuple[str, str], coach: tuple[str, str]
) -> dict[str, Any]:
    from utils import model_downloader

    api_base = os.getenv("LLM_API_BASE", model_downloader.DEFAULT_CLOUD_API_BASE)
    return {
        "provider": "OpenAI-compatible hosted API",
        "api_base_host": urlparse(api_base).netloc,
        "player": _player_configuration(*player),
        "coach": {"model": coach[0], "backend": coach[1]},
    }


def _player_prompt_identity() -> tuple[str, dict[str, Any]]:
    payload = _player_prompt_payload()
    prompt_hash = _sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return prompt_hash, _player_prompt_settings()


def _player_prompt_payload() -> dict[str, Any]:
    from agent import player_prompt
    from utils import player_output_budgets

    return {
        "system_core": player_prompt.STATIC_SYSTEM_CORE,
        "tail_window_size": player_prompt.TAIL_WINDOW_SIZE,
        "hosted_prompt_token_budget": player_prompt.HOSTED_PROMPT_TOKEN_BUDGET,
        "real_token_safety_ceiling": player_prompt.HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING,
        "history_reply_max_chars": player_prompt.ASSISTANT_HISTORY_REPLY_MAX_CHARS,
        "output_budgets": player_output_budgets.CALL_SITE_BUDGETS,
    }


def _player_prompt_settings() -> dict[str, Any]:
    from agent import player_prompt
    from utils import player_output_budgets

    return {
        "output_budgets": dict(player_output_budgets.CALL_SITE_BUDGETS),
        "history_tail_window": player_prompt.TAIL_WINDOW_SIZE,
        "hosted_prompt_token_budget": player_prompt.HOSTED_PROMPT_TOKEN_BUDGET,
        "hosted_prompt_real_token_safety_ceiling": player_prompt.HOSTED_PROMPT_REAL_TOKEN_SAFETY_CEILING,
    }


def _player_configuration(model: str, backend: str) -> dict[str, Any]:
    prompt_hash, config = _player_prompt_identity()
    return {
        "model": model,
        "backend": backend,
        "prompt_config_sha256": prompt_hash,
        **config,
    }


def _trial_configuration() -> dict[str, Any]:
    from service import model_limits

    return {
        "configured_daily_token_limit": model_limits.daily_token_limit(),
        "accepted_default_daily_token_limit": model_limits.DEFAULT_DAILY_TOKEN_LIMIT,
        "request_limit_per_minute": model_limits.request_limit_per_minute(),
        "reset": "UTC calendar day",
        "soft_cap": "admission-time check; a request admitted below the cap may overshoot by that turn's usage",
        "checkpoint_review_exempt": True,
    }


def _pricing_configuration(player_model: str, coach_model: str) -> dict[str, Any]:
    from utils.model_pricing import load_pricing

    pricing = load_pricing()
    return {
        model: {key: float(value) for key, value in prices.items()}
        for model, prices in pricing.items()
        if model in {player_model, coach_model}
    }


def _review_gates(fixture: dict[str, Any]) -> dict[str, Any]:
    return {
        "workload_profile_status": fixture["ordinary_day_assumptions"]["status"],
        "launch_request_counts_accepted": False,
        "quality_gate": {"status": "separate; not assessed by usage measurement"},
        "privacy_gate": {"status": "separate; synthetic fixtures only"},
    }


def _verify_models() -> dict[str, Any]:
    from utils import model_downloader

    player_model = model_downloader.get_llm()
    coach_model = model_downloader.get_coach_llm()
    identity = {
        "player": model_downloader.model_identity("production")[0],
        "coach": model_downloader.model_identity("coach")[0],
    }
    if not isinstance(player_model, model_downloader.SafeChatOpenAI):
        raise RuntimeError("The player graph did not load the configured hosted production model.")
    if not isinstance(coach_model, model_downloader.SafeChatOpenAI):
        raise RuntimeError("Coach AI did not load the configured hosted production model.")
    if set(identity.values()) != {EXPECTED_MODEL}:
        raise RuntimeError(
            f"Issue #262 requires the implemented DeepSeek model for both roles; configured identities are {identity}."
        )
    return identity


def _synthetic_store(base: Path) -> Any:
    from database.database_manager import DEFAULT_CATALOG_PATH, DatabaseManager

    catalog = base / "catalog.db"
    shutil.copyfile(DEFAULT_CATALOG_PATH, catalog)
    return DatabaseManager(
        catalog_path=catalog,
        ledgers_dir=base / "ledgers",
        backups_dir=base / "backups",
        default_ledger_id="trial-measurement-bootstrap",
    )


def _build_schedule(
    fixture: dict[str, Any], turns_by_language: dict[str, dict[str, dict[str, Any]]], language: str, key: str
) -> list[dict[str, Any]]:
    schedule: list[dict[str, Any]] = []
    for entry in fixture["ordinary_day_assumptions"][key]:
        measured = turns_by_language[language][entry["case_id"]]
        for ordinal in range(int(entry["count"])):
            schedule.append(
                {
                    **measured,
                    "turn_id": f"{measured['turn_id']}-day-{ordinal + 1}",
                }
            )
    return schedule


def run_live(fixture: dict[str, Any], dataset_path: Path = DATASET) -> dict[str, Any]:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    identities, turns, turns_by_language, run_error = _run_measurement(fixture)
    replays = _replay_profiles(fixture, turns_by_language) if run_error is None else {}
    cap_decision = _trial_cap_decision(fixture, turns, replays)
    return _measurement_report(
        MeasurementRun(fixture, dataset_path, identities, turns, replays, run_error, cap_decision)
    )


def _run_measurement(
    fixture: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, str] | None]:
    try:
        identities = _verify_models()
        turns, by_language = _measure_pairs(fixture)
    except Exception as exc:
        return {}, [], {}, {"type": type(exc).__name__}
    return identities, turns, by_language, None


def _measure_pairs(
    fixture: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, dict[str, Any]]]]:
    by_language: dict[str, dict[str, dict[str, Any]]] = {"english": {}, "arabic": {}}
    turns: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mayos-trial-usage-262-") as directory:
        store = _synthetic_store(Path(directory))
        try:
            for pair in fixture["pairs"]:
                for language in ("english", "arabic"):
                    measured = _measure_turn(pair, language, store)
                    by_language[language][pair["id"]] = measured
                    turns.append(measured)
        finally:
            _close_store(store)
    return turns, by_language


def _measure_turn(pair: dict[str, Any], language: str, store: Any) -> dict[str, Any]:
    variant = pair[language]
    if pair["capability"] == "coach":
        return _capture_coach_turn(pair, language, variant, store)
    return _capture_player_turn(pair, language, variant, store)


def _close_store(store: Any) -> None:
    store.catalog_conn.close()


def _replay_profiles(
    fixture: dict[str, Any], by_language: dict[str, dict[str, dict[str, Any]]]
) -> dict[str, Any]:
    from service.trial_usage_measurement import replay_trial_day

    replays: dict[str, Any] = {}
    for profile in ("player_only", "dual_capability"):
        for language in ("english", "arabic"):
            turns = _build_schedule(fixture, by_language, language, profile)
            replays[f"{profile}_{language}"] = replay_trial_day(
                turns,
                account_id=f"trial-replay-{profile}-{language}",
                now=datetime.now(UTC),
            )
    return replays


def _trial_cap_decision(
    fixture: dict[str, Any], turns: list[dict[str, Any]], replays: dict[str, Any]
) -> dict[str, Any]:
    from service.model_limits import DEFAULT_DAILY_TOKEN_LIMIT
    from service.trial_usage_measurement import decide_trial_cap

    decision = decide_trial_cap(
        replays.get("dual_capability_english", {}),
        replays.get("dual_capability_arabic", {}),
        current_limit=DEFAULT_DAILY_TOKEN_LIMIT,
        ordinary_use_day=_ordinary_profile_reviewed(fixture),
        equivalent_successful_work=_successful_pairs_reviewed(turns),
    )
    decision["setting_source"] = "accepted shared trial default unless eligible paired evidence demonstrates ADR 059's trigger"
    decision["review_requirements"] = _cap_review_requirements(fixture, turns)
    return decision


def _ordinary_profile_reviewed(fixture: dict[str, Any]) -> bool:
    return fixture["ordinary_day_assumptions"]["status"] == "owner_reviewed_ordinary_use"


def _successful_pairs_reviewed(turns: list[dict[str, Any]]) -> bool:
    return len(turns) == 10 and all(
        turn["outcome"] == "completed"
        and turn["estimated_call_count"] == 0
        and turn["semantic_outcome"] == "owner_reviewed_success"
        for turn in turns
    )


def _cap_review_requirements(fixture: dict[str, Any], turns: list[dict[str, Any]]) -> dict[str, bool]:
    return {
        "arabic_fixture_owner_review": any(
            pair["review_status"] != "owner_reviewed" for pair in fixture["pairs"]
        ),
        "ordinary_day_profile_owner_review": not _ordinary_profile_reviewed(fixture),
        "semantic_success_review": not _successful_pairs_reviewed(turns),
    }


def _trial_setting(cap_decision: dict[str, Any], run_error: dict[str, str] | None) -> dict[str, Any]:
    from service.model_limits import DEFAULT_DAILY_TOKEN_LIMIT

    return {
        "accepted_common_limit": DEFAULT_DAILY_TOKEN_LIMIT,
        "chosen_setting": cap_decision["setting"],
        "decision": cap_decision["decision"],
        "rationale": cap_decision["reason"],
        "live_measurement_available": run_error is None,
    }


def _measurement_report(run: MeasurementRun) -> dict[str, Any]:
    return {
        **_report_provenance(run),
        "report_version": 1,
        "issue": 262,
        "status": "runner_error" if run.run_error else "measured",
        "generated_at": datetime.now(UTC).isoformat(),
        "expected_runtime": EXPECTED_RUNTIME,
        "run_error": run.run_error,
        "paired_turns": run.turns,
        "replays": run.replays,
        "cap_decision": run.cap_decision,
        "trial_setting": _trial_setting(run.cap_decision, run.run_error),
        **_launch_sizing_status(),
    }


def _report_provenance(run: MeasurementRun) -> dict[str, Any]:
    from service.model_limits import DEFAULT_DAILY_TOKEN_LIMIT

    return {
        "dataset": _dataset_name(run.dataset_path),
        "dataset_sha256": _sha256(run.dataset_path.read_bytes()),
        "fixture_status": run.fixture["status"],
        "facts_are_synthetic": True,
        "model_identity": run.identities,
        "configuration": _configuration_identity(run.fixture),
        "accepted_trial_limit": DEFAULT_DAILY_TOKEN_LIMIT,
    }


def _dataset_name(dataset_path: Path) -> str:
    return str(dataset_path.relative_to(ROOT)) if dataset_path.is_relative_to(ROOT) else str(dataset_path)


def _launch_sizing_status() -> dict[str, Any]:
    return {
        "quality_gate": {"status": "separate; usage outcome checks are not Arabic quality certification"},
        "privacy_gate": {"status": "separate; all workload inputs are synthetic"},
        "future_launch_sizing": {
            "reusable": True,
            "proposed_free_5_pro_30_request_counts_accepted": False,
            "use_measured_turns_and_separately_review_quality_privacy_before_sale": True,
        },
    }


def write_report(path: Path, report: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Paired Arabic/English DeepSeek trial usage measurement (#262).")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true", help="Validate fixtures and print identities without loading a model.")
    mode.add_argument("--live", action="store_true", help="Run explicit hosted DeepSeek measurements (10 paired turns).")
    parser.add_argument("--dataset", type=Path, default=DATASET, help="Paired synthetic workload fixture.")
    parser.add_argument("--report", type=Path, help="Write the reproducible JSON report; required for --live.")
    args = parser.parse_args(argv)
    if args.live and args.report is None:
        parser.error("--live requires --report so results are retained.")
    return args


def _validation_summary(fixture: dict[str, Any]) -> dict[str, Any]:
    return {
        "valid": True,
        "pairs": len(fixture["pairs"]),
        "turns": len(fixture["pairs"]) * 2,
        "fixture_review_status": fixture["status"],
        "live_calls_made": False,
    }


def _write_live_report(args: argparse.Namespace, fixture: dict[str, Any]) -> int:
    report = run_live(fixture, args.dataset)
    written = write_report(args.report, report)
    print(f"report written: {written}; status={report['status']}; expected runtime: {EXPECTED_RUNTIME}")
    return 0 if report["run_error"] is None else 2


def main(argv: list[str] | None = None) -> int:
    args = _parse_arguments(argv)
    try:
        fixture = load_workloads(args.dataset)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"trial workload error: {type(exc).__name__}", file=sys.stderr)
        return 2
    if args.validate:
        print(json.dumps(_validation_summary(fixture), ensure_ascii=False))
        return 0
    return _write_live_report(args, fixture)


if __name__ == "__main__":
    raise SystemExit(main())
