"""Computed Checkpoint reviews stored in a player's training ledger (#221)."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from agent.progression_engine import set_e1rm
from service import analytics as analytics_service
from service import coach_analytics
from service import analytics
from service import training_status
from service._base import ledger_scope
from service.keyed_locks import KeyedLocks

logger = logging.getLogger(__name__)

CONSISTENCY_STRONG_THRESHOLD = 0.8
CONSISTENCY_STEADY_THRESHOLD = 0.5
VOLUME_RISING_THRESHOLD = 1.05
VOLUME_FALLING_THRESHOLD = 0.95


@dataclass(frozen=True)
class CheckpointFactsInput:
    workouts: list[dict[str, Any]]
    previous_workouts: list[dict[str, Any]]
    working_sets: list[dict[str, Any]]
    personal_records: list[dict[str, Any]]
    schedule_versions: list[dict[str, Any]]
    pauses: list[dict[str, Any]]
    weekly_frequency: int


class CheckpointReviewNotFoundError(LookupError):
    """A review is missing after coach access has already been authorized."""


_generation_locks = KeyedLocks()


@dataclass(frozen=True)
class _ReviewReadContext:
    db: Any
    ledger_id: str
    checkpoint: int
    language: str
    account_id: str | None
    ledger_handle: Any | None
    client: analytics.ClientContext
    background_tasks: Any = None


def resolve_display_language(account_id: str | None = None) -> str:
    """Current Display language; #135 will connect this to account preference."""
    # TODO(#135): read the account's persisted Display language here.
    return "en"


def _session_ids(workouts: list[dict[str, Any]]) -> set[str]:
    return {str(workout["session_id"]) for workout in workouts}


def _working_sets_by_session(
    rows: list[dict[str, Any]], session_ids: set[str]
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        session_id = str(row["session_id"])
        if session_id in session_ids and not row["is_warmup"]:
            grouped.setdefault(session_id, []).append(row)
    return grouped


def _best_e1rm(
    workouts: list[dict[str, Any]],
    sets_by_session: dict[str, list[dict[str, Any]]],
) -> dict[str, float]:
    best: dict[str, float] = {}
    for workout in workouts:
        for row in sets_by_session.get(str(workout["session_id"]), []):
            weight = float(row["weight_kg"])
            reps = int(row["reps"])
            if weight <= 0 or reps <= 0:
                continue
            exercise_id = str(row["exercise_id"])
            estimate = set_e1rm(weight, reps, row["rpe"])
            best[exercise_id] = max(best.get(exercise_id, 0.0), estimate)
    return best


def _period_weeks(
    workouts: list[dict[str, Any]],
    schedule_versions: list[dict[str, Any]],
    pauses: list[dict[str, Any]],
    weekly_frequency: int,
) -> tuple[int, int]:
    first_date, last_date = _period_date_bounds(workouts)
    week_start = training_status.saturday_week_start(first_date)
    last_week = training_status.saturday_week_start(last_date)
    weeks_met = 0
    weeks_counted = 0
    while week_start <= last_week:
        target = training_status.weekly_target_for(
            week_start, schedule_versions, pauses, weekly_frequency
        )
        if target > 0:
            week_end = week_start + timedelta(days=6)
            met = sum(
                week_start <= date.fromisoformat(str(workout["session_date"])) <= week_end
                for workout in workouts
            ) >= target
            partial = first_date > week_start or last_date < week_end
            if not partial or met:
                weeks_counted += 1
                weeks_met += int(met)
        week_start += timedelta(days=7)
    return weeks_met, weeks_counted


def _period_date_bounds(workouts: list[dict[str, Any]]) -> tuple[date, date]:
    dates = [date.fromisoformat(str(workout["session_date"])) for workout in workouts]
    return min(dates), max(dates)


def compute_checkpoint_facts(inputs: CheckpointFactsInput) -> dict[str, Any]:
    """Computes the reduced facts and rating inputs without reading storage."""
    current_ids = _session_ids(inputs.workouts)
    previous_ids = _session_ids(inputs.previous_workouts)
    relevant_ids = current_ids | previous_ids
    sets_by_session = _working_sets_by_session(inputs.working_sets, relevant_ids)
    prs = {
        str(record["exercise_id"])
        for record in inputs.personal_records
        if str(record["session_id"]) in current_ids
    }
    current_best = _best_e1rm(inputs.workouts, sets_by_session)
    previous_best = _best_e1rm(inputs.previous_workouts, sets_by_session)
    regressed = sum(
        current_best[exercise_id] < previous_best[exercise_id]
        for exercise_id in current_best.keys() & previous_best.keys()
    )
    volumes = {
        session_id: sum(
            float(row["weight_kg"]) * int(row["reps"])
            for row in session_sets
        )
        for session_id, session_sets in sets_by_session.items()
    }
    split = len(inputs.workouts) // 2
    first_half = inputs.workouts[:split]
    second_half = inputs.workouts[split:]
    weeks_met, weeks_counted = _period_weeks(
        inputs.workouts,
        inputs.schedule_versions,
        inputs.pauses,
        inputs.weekly_frequency,
    )
    return {
        "workouts_in_period": len(inputs.workouts),
        "weeks_met": weeks_met,
        "weeks_counted": weeks_counted,
        "personal_records": len(prs),
        "regressed_exercises": int(regressed),
        "volume_first_half": sum(volumes.get(str(row["session_id"]), 0.0) for row in first_half),
        "volume_second_half": sum(volumes.get(str(row["session_id"]), 0.0) for row in second_half),
    }


def rate_checkpoint_facts(facts: dict[str, Any]) -> list[dict[str, str]]:
    """Maps computed facts to the fixed, independently labelled scales."""
    weeks_counted = int(facts["weeks_counted"])
    weeks_met = int(facts["weeks_met"])
    if weeks_counted == 0:
        consistency = "Not enough weeks yet"
    elif weeks_met / weeks_counted >= CONSISTENCY_STRONG_THRESHOLD:
        consistency = "Strong"
    elif weeks_met / weeks_counted >= CONSISTENCY_STEADY_THRESHOLD:
        consistency = "Steady"
    else:
        consistency = "Needs attention"

    records = int(facts["personal_records"])
    regressed = int(facts["regressed_exercises"])
    if records >= 2 and records > regressed:
        progression = "Strong"
    elif records >= regressed and records + regressed > 0:
        progression = "Steady"
    elif records < regressed:
        progression = "Needs attention"
    else:
        progression = "Holding"

    first_volume = float(facts["volume_first_half"])
    second_volume = float(facts["volume_second_half"])
    if first_volume == 0:
        volume_trend = "Not enough data"
    elif second_volume / first_volume >= VOLUME_RISING_THRESHOLD:
        volume_trend = "Rising"
    elif second_volume / first_volume <= VOLUME_FALLING_THRESHOLD:
        volume_trend = "Falling"
    else:
        volume_trend = "Holding"
    return [
        {"part": "Consistency", "label": consistency},
        {"part": "Progression", "label": progression},
        {"part": "Volume trend", "label": volume_trend},
    ]


def _ledger_workouts(ledger: Any, imported_workouts: int) -> list[dict[str, str]]:
    rows = ledger.list_checkpoint_workouts()
    return rows[max(0, imported_workouts):]


def _review_periods(
    workouts: list[dict[str, str]], checkpoint: int
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    previous = training_status.previous_checkpoint(checkpoint)
    if previous is None:
        return workouts[:checkpoint], []
    previous_period_start = training_status.previous_checkpoint(previous)
    current = workouts[previous:checkpoint]
    prior_start = 0 if previous_period_start is None else previous_period_start
    prior = workouts[prior_start:previous]
    return current, prior


def create_checkpoint_review(
    ledger: Any,
    checkpoint: int,
    imported_workouts: int,
    created_at: str,
) -> bool:
    """Creates the checkpoint row inside the caller's ledger transaction."""
    workouts = _ledger_workouts(ledger, imported_workouts)
    if not training_status.is_checkpoint(checkpoint) or len(workouts) != checkpoint:
        return False
    period, previous_period = _review_periods(workouts, checkpoint)
    set_rows = ledger.list_checkpoint_working_sets()
    pr_rows = ledger.list_checkpoint_personal_records()
    program = ledger.get_active_program()
    facts = compute_checkpoint_facts(
        CheckpointFactsInput(
            workouts=period,
            previous_workouts=previous_period,
            working_sets=set_rows,
            personal_records=pr_rows,
            schedule_versions=ledger.list_training_schedules(ledger.ledger_id),
            pauses=ledger.list_training_pauses(ledger.ledger_id),
            weekly_frequency=int(program.weekly_frequency) if program is not None else 0,
        )
    )
    rating = rate_checkpoint_facts(facts)
    start_date, end_date = _period_date_bounds(period)
    return ledger.insert_checkpoint_review(
        {
            "checkpoint": checkpoint,
            "session_id": workouts[checkpoint - 1]["session_id"],
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "facts_json": json.dumps(facts, sort_keys=True),
            "rating_json": json.dumps(rating, sort_keys=True),
            "created_at": created_at,
        }
    )


def _neutral_review_from_row(row: Any, language: str) -> dict[str, Any]:
    facts = json.loads(row["facts_json"])
    rating = json.loads(row["rating_json"])
    text = template_text(
        int(row["checkpoint"]),
        int(facts["workouts_in_period"]),
        language,
        int(row["checkpoint"]) == 10,
    )
    return {
        "checkpoint": int(row["checkpoint"]),
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "facts": facts,
        "rating": rating,
        "text": text,
        "text_is_template": True,
    }


def _review_from_row(row: Any, language: str) -> dict[str, Any]:
    review = _neutral_review_from_row(row, language)
    if row["text"] is not None:
        review.update(text=row["text"] or review["text"], text_is_template=False)
    return review


def _get_review_row(context: _ReviewReadContext, opened_at: str | None = None) -> dict[str, Any] | None:
    with ledger_scope(context.db, context.ledger_handle, context.ledger_id) as open_ledger:
        if opened_at is not None:
            open_ledger.mark_checkpoint_review_opened(context.checkpoint, opened_at)
        return open_ledger.get_checkpoint_review_row(context.checkpoint)


def _generation_lock(ledger_id: str, checkpoint: int) -> threading.Lock:
    key = (ledger_id, checkpoint)
    return _generation_locks.get(key)


def _claim_generation_attempt(context: _ReviewReadContext, now: datetime) -> bool:
    attempted_at = now.isoformat()
    retry_after = (now - timedelta(minutes=10)).isoformat()
    with ledger_scope(context.db, context.ledger_handle, context.ledger_id) as open_ledger:
        return open_ledger.claim_checkpoint_review_text_attempt(context.checkpoint, attempted_at, retry_after)


def _store_review_text(context: _ReviewReadContext, text: str) -> None:
    with ledger_scope(context.db, context.ledger_handle, context.ledger_id) as open_ledger:
        open_ledger.store_checkpoint_review_text(context.checkpoint, text, context.language)


def _latest_or_template(context: _ReviewReadContext, fallback: dict[str, Any]) -> dict[str, Any] | None:
    latest = _get_review_row(context)
    if latest is None:
        return None
    return fallback if latest["text"] is None else _review_from_row(latest, context.language)


def _review_generation_request(context: _ReviewReadContext, row: dict[str, Any]) -> Any:
    from agent.prompts import DEFAULT_ASSISTANT_STYLE
    from service import checkpoint_review_ai

    with ledger_scope(context.db, context.ledger_handle, context.ledger_id) as ledger:
        profile = ledger.get_player_profile() or {}
    return checkpoint_review_ai.ReviewGenerationRequest(
        db=context.db,
        account_id=context.account_id,
        facts=json.loads(row["facts_json"]),
        rating=json.loads(row["rating_json"]),
        language=context.language,
        coach_tone=profile.get("coach_tone") or DEFAULT_ASSISTANT_STYLE,
        custom_instructions=profile.get("custom_instructions") or "",
        inference_scope=_checkpoint_inference_scope(context),
    )


def _checkpoint_inference_scope(context: _ReviewReadContext) -> Any:
    from database.registry.model_usage import ALLOWANCE_EXEMPT_PURPOSE
    from svc.llm import InferenceScope

    return InferenceScope(
        account_id=context.account_id,
        role="player",
        purpose=ALLOWANCE_EXEMPT_PURPOSE,
        admit=False,
        store=context.db,
        client=context.client,
    )


def _generate_and_store_review_text(
    context: _ReviewReadContext, row: dict[str, Any], fallback: dict[str, Any]
) -> dict[str, Any] | None:
    from service import checkpoint_review_ai

    from svc.llm import inference_turn
    from service.model_limits import ModelLimitExceeded

    request = _review_generation_request(context, row)
    with inference_turn(request.inference_scope, background_tasks=context.background_tasks) as turn:
        try:
            generated = checkpoint_review_ai.generate_review_text(request)
        except ModelLimitExceeded:
            turn.suppress_completion()
            return fallback
        except Exception as exc:
            turn.mark_error()
            # Provider failures vary by backend; review wording is optional so a failed turn uses its template.
            logger.warning("Checkpoint review text generation failed (%s).", type(exc).__name__)
            return fallback
        if not generated:
            return fallback
        _store_review_text(context, generated)
        return _latest_or_template(context, fallback)


def _generate_review_after_claim(context: _ReviewReadContext) -> dict[str, Any] | None:
    row = _get_review_row(context)
    if row is None:
        return None
    if row["text"] is not None:
        return _review_from_row(row, context.language)
    fallback = _review_from_row(row, context.language)
    if not _claim_generation_attempt(context, datetime.now(UTC)):
        return _latest_or_template(context, fallback)
    return _generate_and_store_review_text(context, row, fallback)


def _generate_missing_review_text(context: _ReviewReadContext, fallback: dict[str, Any]) -> dict[str, Any] | None:
    if context.account_id is None:
        return fallback
    from service import checkpoint_review_ai

    if not checkpoint_review_ai.checkpoint_review_ai_enabled():
        return fallback
    # A local lock makes simultaneous request threads reuse the first stored text.
    with _generation_lock(context.ledger_id, context.checkpoint):
        return _generate_review_after_claim(context)


def template_text(checkpoint: int, workouts: int, language: str, first: bool) -> str:
    if language == "ar":
        # TODO(#135): review wording for Arabic dialect before model-written text lands.
        period = "منذ بدء تسجيلك في MAYOS" if first else "منذ نقطة التحقق السابقة"
        return f"نقطة التحقق {checkpoint}: {workouts} تمرينًا {period}."
    period = "since you started logging in MAYOS" if first else "since your last checkpoint"
    return f"Checkpoint {checkpoint}: {workouts} workouts {period}."


def list_checkpoint_reviews(
    db: Any, ledger_id: str, ledger: Any | None = None
) -> list[dict[str, Any]]:
    with ledger_scope(db, ledger, ledger_id) as open_ledger:
        rows = open_ledger.list_checkpoint_review_rows()
        return [
            {
                "checkpoint": int(row["checkpoint"]),
                "period_start": row["period_start"],
                "period_end": row["period_end"],
                "rating": json.loads(row["rating_json"]),
                "opened": row["opened_at"] is not None,
            }
            for row in rows
        ]


def read_checkpoint_review(
    db: Any,
    ledger_id: str,
    checkpoint: int,
    *,
    language: str | None = None,
    account_id: str | None = None,
    opened_at: str | None = None,
    ledger: Any | None = None,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
    background_tasks: Any = None,
) -> dict[str, Any] | None:
    language = language or resolve_display_language(account_id)
    context = _ReviewReadContext(db, ledger_id, checkpoint, language, account_id, ledger, client, background_tasks)
    row = _get_review_row(context, opened_at)
    if row is None:
        return None
    if row["text"] is not None:
        return _review_from_row(row, language)
    fallback = _review_from_row(row, language)
    return _generate_missing_review_text(context, fallback)


def coach_checkpoint_reviews(
    db: Any,
    coach_account_id: str,
    assignment_id: str,
    *,
    client: analytics_service.ClientContext = analytics_service.UNKNOWN_CLIENT,
) -> list[dict[str, Any]] | None:
    from service.assignments import authorized_player_ledger

    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        reviews = list_checkpoint_reviews(db, context["player"]["ledger_id"], ledger)
    coach_analytics.capture_player_history_viewed(
        db,
        coach_analytics.CoachDailyView(coach_account_id, assignment_id, client=client),
    )
    return reviews


def coach_checkpoint_review(
    db: Any,
    coach_account_id: str,
    assignment_id: str,
    checkpoint: int,
    *,
    client: analytics_service.ClientContext = analytics_service.UNKNOWN_CLIENT,
) -> dict[str, Any] | None:
    from service.assignments import authorized_player_ledger

    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        row = ledger.get_checkpoint_review_row(checkpoint)
        if row is None:
            raise CheckpointReviewNotFoundError(checkpoint)
        language = resolve_display_language(context["player"]["account_id"])
        review = _neutral_review_from_row(row, language)
    coach_analytics.capture_player_history_viewed(
        db,
        coach_analytics.CoachDailyView(coach_account_id, assignment_id, client=client),
    )
    return review
