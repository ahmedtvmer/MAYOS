"""Computed Checkpoint reviews stored in a player's training ledger (#221)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from agent.progression_engine import set_e1rm
from service import training_status
from service._base import ledger_scope

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


def _review_from_row(row: Any, language: str) -> dict[str, Any]:
    facts = json.loads(row["facts_json"])
    rating = json.loads(row["rating_json"])
    is_template = row["text"] is None
    text = row["text"] or template_text(
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
        "text_is_template": is_template,
    }


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
    language: str = "en",
    opened_at: str | None = None,
    ledger: Any | None = None,
) -> dict[str, Any] | None:
    with ledger_scope(db, ledger, ledger_id) as open_ledger:
        if opened_at is not None:
            open_ledger.mark_checkpoint_review_opened(checkpoint, opened_at)
        row = open_ledger.get_checkpoint_review_row(checkpoint)
        return None if row is None else _review_from_row(row, language)


def coach_checkpoint_reviews(
    db: Any, coach_account_id: str, assignment_id: str
) -> list[dict[str, Any]] | None:
    from service.assignments import authorized_player_ledger

    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        return list_checkpoint_reviews(db, context["player"]["ledger_id"], ledger)


def coach_checkpoint_review(
    db: Any, coach_account_id: str, assignment_id: str, checkpoint: int
) -> dict[str, Any] | None:
    from service.assignments import authorized_player_ledger

    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        review = read_checkpoint_review(
            db, context["player"]["ledger_id"], checkpoint, ledger=ledger
        )
        if review is None:
            raise CheckpointReviewNotFoundError(checkpoint)
        return review
