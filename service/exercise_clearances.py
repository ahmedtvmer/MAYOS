"""Read current clearance facts for recommendations and existing-program flags."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from core.exercise_clearances import exercise_clearance
from database.exercise_resolution import resolve_exercise_display_row

logger = logging.getLogger(__name__)


def exclusion_message(language: str) -> str:
    return (
        "مش هقدر أأكد إنه آمن ليك؛ التمرين مش مسموح أو مفيش تصريح طبي مسجّل ليه مع إصابة لسه موجودة."
        if language == "ar" else
        "I can't confirm it's safe: that exercise is not cleared or has no recorded clearance for an active injury."
    )


class ExerciseClearancePolicy:
    def __init__(self, ledger: Any):
        self.injuries = [row for row in ledger.list_injury_records() if row["status"] != "resolved"]
        self.clearances = [
            record for injury in self.injuries
            for record in ledger.list_exercise_clearances(str(injury["id"]))
        ]

    def assess(self, exercise: dict[str, Any]) -> dict[str, Any]:
        return exercise_clearance(self.clearances, self.injuries, exercise)

    def allows(self, exercise: dict[str, Any]) -> bool:
        return not self.assess(exercise)["excluded"]


def assistant_program_clearances(db: Any, ledger: Any, days: Any) -> dict[str, Any]:
    """Supply current safety flags through the existing scoped program read tool."""
    policy = ExerciseClearancePolicy(ledger)
    if not policy.injuries:
        return {"status": "ok", "exercises": []}
    if db is None:
        return {"status": "unavailable"}
    flags = {}
    for day in days:
        for exercise in day.exercises:
            entry = db.get_exercise_library_entry(str(exercise.exercise_id))
            assessment = policy.assess(entry or {"exercise_id": exercise.exercise_id})
            if assessment["status"] != "allowed":
                flags[str(exercise.exercise_id)] = {
                    "exercise_name": exercise.exercise_name,
                    **assessment,
                }
    return {"status": "ok", "exercises": list(flags.values())}


def _filter_suggested_substitutes(
    db: Any, policy: ExerciseClearancePolicy, exercise: dict[str, Any]
) -> None:
    eligible = []
    for substitute in exercise.get("suggested_substitutes", []):
        candidate = resolve_exercise_display_row(db, str(substitute["exercise_id"]))
        if candidate is not None and policy.allows(candidate):
            eligible.append(substitute)
    exercise["suggested_substitutes"] = eligible


def _exercise_assessment(
    db: Any, policy: ExerciseClearancePolicy, exercise: dict[str, Any]
) -> dict[str, Any]:
    entry = db.get_exercise_library_entry(str(exercise.get("exercise_id") or ""))
    candidate = entry or {"exercise_id": exercise.get("exercise_id")}
    return policy.assess(candidate)


def _annotate_exercise(
    db: Any,
    policy: ExerciseClearancePolicy,
    exercise: dict[str, Any],
    assessment: dict[str, Any],
) -> None:
    exercise["clearance_status"] = (
        assessment["status"] if assessment["status"] != "allowed" else None
    )
    exercise["clearance_limit_notes"] = assessment["limit_notes"]
    _filter_suggested_substitutes(db, policy, exercise)


def _program_exercise_flag(
    exercise: dict[str, Any], assessment: dict[str, Any]
) -> dict[str, Any] | None:
    if not assessment["excluded"]:
        return None
    return {
        "exercise_id": exercise["exercise_id"],
        "exercise_name": exercise["exercise_name"],
        "clearance_status": assessment["status"],
    }


def _exercises_for_days(days: Any) -> Iterator[dict[str, Any]]:
    for day in days:
        yield from day.get("exercises", [])
        yield from day.get("warmup_exercises", [])


def _program_exercises(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if payload.get("weeks"):
        for week in payload["weeks"]:
            yield from _exercises_for_days(week.get("days", []))
        return
    yield from _exercises_for_days(payload.get("days", []))


def _response_program_exercises(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield from _program_exercises(payload)
    if payload.get("weeks"):
        yield from _exercises_for_days(payload.get("days", []))


def annotate_program(db: Any, ledger: Any, payload: dict[str, Any]) -> None:
    """Decorate a response copy; retain every existing prescription unchanged."""
    policy = ExerciseClearancePolicy(ledger)
    for exercise in _response_program_exercises(payload):
        assessment = _exercise_assessment(db, policy, exercise)
        _annotate_exercise(db, policy, exercise, assessment)


def program_exclusions(db: Any, ledger: Any, payload: dict[str, Any]) -> list[dict[str, Any]]:
    policy = ExerciseClearancePolicy(ledger)
    flagged: dict[str, dict[str, Any]] = {}
    for exercise in _program_exercises(payload):
        assessment = _exercise_assessment(db, policy, exercise)
        flag = _program_exercise_flag(exercise, assessment)
        if flag:
            flagged[str(flag["exercise_id"])] = flag
    return list(flagged.values())


def _program_clearance_alert(
    assignment: dict[str, Any], player_id: str, exercise: dict[str, Any]
) -> Any:
    from service import coach_analytics

    return coach_analytics.CoachAlertDraft(
        alert_id=uuid.uuid4().hex,
        assignment_id=assignment["assignment_id"],
        coach_account_id=assignment["coach_account_id"],
        player_account_id=player_id,
        alert_kind="profile_change",
        dedupe_key=f"program-clearance:{exercise['exercise_id']}",
        details={"clearance_program_exercises": [exercise]},
        created_at=datetime.now(UTC).isoformat(),
    )


def _record_program_clearance_alerts(
    db: Any, assignment: dict[str, Any], player_id: str, flagged: list[dict[str, Any]]
) -> None:
    if not flagged:
        return
    from service import coach_analytics

    with db.catalog_transaction():
        if db.get_active_assignment_for_coach(
            assignment["coach_account_id"], assignment["assignment_id"]
        ) is None:
            return
        for exercise in flagged:
            coach_analytics.create_coach_alert(
                db, _program_clearance_alert(assignment, player_id, exercise)
            )


def _notify_current_program(db: Any, ledger: Any, player_id: str) -> None:
    from service.programs import player_controls_program, with_library_equipment

    program = ledger.get_active_program()
    if program is None or player_controls_program(db, ledger, player_id, program):
        return
    assignment = db.get_active_assignment_for_player(player_id)
    if assignment is None:
        return
    payload = with_library_equipment(program, db)
    flagged = program_exclusions(db, ledger, payload)
    _record_program_clearance_alerts(db, assignment, player_id, flagged)


def notify_program_exclusions(db: Any, ledger: Any, player_account_id: str | None) -> None:
    """Use durable per-assignment/exercise alert keys, including acknowledged alerts."""
    if not player_account_id:
        return
    try:
        _notify_current_program(db, ledger, str(player_account_id))
    except sqlite3.Error:
        logger.warning("Could not record program-clearance Coach alerts.", exc_info=True)
