"""Privacy-safe analytics for committed workout facts."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from service import analytics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkoutCommitAnalyticsInput:
    account_id: str
    session_id: str
    sync: Any
    sets_by_exercise: list[dict[str, Any]]
    body: dict[str, Any]
    uploaded_at: str
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT
    program: Any | None = None


@dataclass(frozen=True)
class _WorkoutAnalyticsFacts:
    account_id: str
    session_id: str
    client_session_id: str | None
    sets_by_exercise: list[dict[str, Any]]
    divergences: list[dict[str, Any]]
    uploaded_at: str
    captured_at: str | None
    captured_offline: bool
    is_first_workout: bool
    program: Any | None
    coached: bool


def _capped_count(property_name: str, value: int) -> int:
    maximum = analytics.PROPERTY_TYPES[property_name].maximum
    if maximum is None:
        raise ValueError(f"{property_name} must have a catalogue bound.")
    return min(value, maximum)


def _program_provenance(program: Any | None) -> str:
    if program is None:
        return "none"
    if getattr(program, "published_by_coach_account_id", None):
        return "coach_published"
    return "generated"


def _workout_set_aggregates(sets_by_exercise: list[dict[str, Any]]) -> dict[str, int]:
    working_sets = [
        workout_set
        for exercise in sets_by_exercise
        for workout_set in exercise["sets"]
        if not workout_set.get("is_warmup", False)
    ]
    exercise_ids = {
        str(exercise["exercise"].exercise_id)
        for exercise in sets_by_exercise
        if any(not workout_set.get("is_warmup", False) for workout_set in exercise["sets"])
    }
    return {
        "set_count": _capped_count("set_count", len(working_sets)),
        "exercise_count": _capped_count("exercise_count", len(exercise_ids)),
        "load_complete_set_count": _capped_count(
            "load_complete_set_count",
            sum(workout_set.get("weight_kg") is not None for workout_set in working_sets),
        ),
        "reps_complete_set_count": _capped_count(
            "reps_complete_set_count",
            sum(workout_set.get("reps") is not None for workout_set in working_sets),
        ),
        "rir_complete_set_count": _capped_count(
            "rir_complete_set_count",
            sum(workout_set.get("rpe") is not None for workout_set in working_sets),
        ),
    }


def _sync_delay_seconds(captured_at: str | None, uploaded_at: str) -> int:
    if captured_at is None:
        return 0
    # Reuse the workout API's strict, timezone-aware instant parser.
    from service.workouts import _parse_captured_at

    delay = int(
        (_parse_captured_at(uploaded_at) - _parse_captured_at(captured_at)).total_seconds()
    )
    return _capped_count("sync_delay_seconds", max(delay, 0))


def _properties(facts: _WorkoutAnalyticsFacts) -> dict[str, Any]:
    return {
        **_workout_set_aggregates(facts.sets_by_exercise),
        "divergence_count": _capped_count("divergence_count", len(facts.divergences)),
        "unplanned_exercise_count": _capped_count(
            "unplanned_exercise_count",
            sum(divergence["kind"] == "unplanned" for divergence in facts.divergences),
        ),
        "captured_offline": facts.captured_offline,
        "sync_delay_seconds": _sync_delay_seconds(
            facts.captured_at if facts.captured_offline else None, facts.uploaded_at
        ),
        "is_first_workout": facts.is_first_workout,
        "program_provenance": _program_provenance(facts.program),
        "coached": facts.coached,
    }


def capture_workout_completed(
    db: Any,
    ledger: Any,
    observation: WorkoutCommitAnalyticsInput,
) -> None:
    """Gathers and captures workout facts without affecting a committed workout."""
    try:
        program = observation.program
        if program is None:
            program = ledger.get_active_program()
        facts = _WorkoutAnalyticsFacts(
            account_id=observation.account_id,
            session_id=observation.session_id,
            client_session_id=observation.sync.client_session_id,
            sets_by_exercise=observation.sets_by_exercise,
            divergences=observation.body["divergences"],
            uploaded_at=observation.uploaded_at,
            captured_at=observation.sync.captured_at,
            captured_offline=observation.sync.captured_offline,
            is_first_workout=observation.body["training_status"]["mayos_workouts"] == 1,
            program=program,
            coached=db.get_active_assignment_for_player(observation.account_id) is not None,
        )
        analytics.capture(
            analytics.AnalyticsEvent(
                account_id=facts.account_id,
                event="workout_completed",
                domain_key=facts.client_session_id or facts.session_id,
                role="player",
                properties=_properties(facts),
            ),
            observation.client,
        )
    except Exception:
        logger.exception("Workout analytics capture failed after the workout commit.")


def report_sync_failure(
    account_id: str,
    reason_code: str,
    attempt: int,
    *,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> None:
    try:
        maximum = analytics.PROPERTY_TYPES["attempt"].maximum
        if maximum is None:
            raise ValueError("attempt must have a catalogue bound.")
        analytics.capture(
            analytics.AnalyticsEvent(
                account_id=account_id,
                event="workout_sync_failed",
                domain_key=str(uuid.uuid4()),
                role="player",
                properties={
                    "sync_failure_reason": reason_code,
                    "attempt": min(max(attempt, 1), maximum),
                },
            ),
            client,
        )
    except Exception:
        logger.exception("Workout sync failure analytics capture failed.")
