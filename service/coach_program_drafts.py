"""Assignment-gated lifecycle for coach-authored Program drafts."""

from typing import Any

from pydantic import ValidationError

from agent.ProgramState import PersistedProgramSchema
from agent.program_prescription import (
    DEFAULT_TARGET_RIR,
    MAX_REPS,
    MAX_TARGET_RIR,
    MIN_REPS,
    MIN_TARGET_RIR,
)
from service import analytics
from service.assignments import authorized_player_ledger
from service.coach_programs import record_program_publication
from service.program_analytics import ProgramAnalyticsActor


class ProgramDraftNotFound(Exception):
    """Raised when an active assignment has no open Program draft."""


class ProgramDraftAlreadyExists(Exception):
    """Raised when an assignment already has its one open Program draft."""


class ProgramDraftValidationError(Exception):
    """One or more saved draft fields cannot become an active program."""

    def __init__(self, issues: list[dict[str, Any]]):
        super().__init__("The Program draft has invalid fields.")
        self.issues = issues

    @classmethod
    def one(
        cls,
        code: str,
        message: str,
        *,
        day_index: int | None = None,
        exercise_index: int | None = None,
        field: str,
    ) -> "ProgramDraftValidationError":
        return cls(
            [
                {
                    "code": code,
                    "message": message,
                    "location": {
                        "day_index": day_index,
                        "exercise_index": exercise_index,
                        "field": field,
                    },
                }
            ]
        )


def _assignment_still_active(db: Any, coach_account_id: str, assignment_id: str) -> bool:
    return db.get_active_assignment_for_coach(coach_account_id, assignment_id) is not None


def create_program_draft(
    db: Any, coach_account_id: str, assignment_id: str, draft: dict[str, Any]
) -> dict[str, Any] | None:
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, _ = authorized
    with ledger:
        created = ledger.create_program_draft(assignment_id, draft)
        if created is None:
            raise ProgramDraftAlreadyExists("A Program draft already exists for this assignment.")
        if not _assignment_still_active(db, coach_account_id, assignment_id):
            ledger.discard_program_draft(assignment_id)
            return None
        return created


def read_program_draft(db: Any, coach_account_id: str, assignment_id: str) -> dict[str, Any] | None:
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, _ = authorized
    with ledger:
        draft = ledger.get_program_draft(assignment_id)
    if draft is None:
        raise ProgramDraftNotFound("Program draft not found.")
    return draft


def replace_program_draft(
    db: Any, coach_account_id: str, assignment_id: str, draft: dict[str, Any]
) -> dict[str, Any] | None:
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, _ = authorized
    with ledger:
        replaced = ledger.replace_program_draft(assignment_id, draft)
        if replaced is None:
            raise ProgramDraftNotFound("Program draft not found.")
        if not _assignment_still_active(db, coach_account_id, assignment_id):
            ledger.discard_program_draft(assignment_id)
            return None
        return replaced


def discard_program_draft(db: Any, coach_account_id: str, assignment_id: str) -> bool | None:
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, _ = authorized
    with ledger:
        return ledger.discard_program_draft(assignment_id)


def _pydantic_issue(error: dict[str, Any]) -> dict[str, Any]:
    loc = list(error.get("loc", ()))
    day_index = None
    exercise_index = None
    field = "program"
    if "days" in loc:
        day_at = loc.index("days")
        if len(loc) > day_at + 1 and isinstance(loc[day_at + 1], int):
            day_index = loc[day_at + 1]
        if len(loc) > day_at + 2:
            section = loc[day_at + 2]
            if section in {"exercises", "warmup_exercises"}:
                if len(loc) > day_at + 3 and isinstance(loc[day_at + 3], int):
                    exercise_index = loc[day_at + 3]
                if len(loc) > day_at + 4:
                    field = str(loc[day_at + 4])
                else:
                    field = str(section)
            else:
                field = str(section)
        elif len(loc) > day_at + 1:
            field = str(loc[day_at + 1])
    elif loc:
        field = str(loc[0])

    error_type = str(error.get("type", ""))
    if field == "exercises" and error_type == "too_long":
        code, message = "too_many_exercises", "A training day can have at most 14 exercises."
    elif field == "exercises" and error_type == "too_short":
        code, message = "empty_day", "Each training day needs at least one exercise."
    elif field == "target_sets":
        code, message = "invalid_sets", "Working sets must be at least 1."
    elif field in {"target_reps_min", "target_reps_max"}:
        code, message = "invalid_reps", f"Reps must be from {MIN_REPS} to {MAX_REPS}."
    elif field == "target_rpe":
        code, message = "invalid_rir", f"Target RIR must be from {MIN_TARGET_RIR:g} to {MAX_TARGET_RIR:g}."
    elif field == "warmup_sets":
        code, message = "invalid_warmup_sets", "Warm-up sets must be from 0 to 4."
    elif field == "day_order":
        code, message = "invalid_day_order", "Training day order must be from 1 to 5."
    elif field == "weekly_frequency":
        code, message = "invalid_weekly_frequency", "Weekly frequency must be from 1 to 5."
    else:
        code, message = "invalid_program_field", "This program field is invalid."
    return {
        "code": code,
        "message": message,
        "location": {
            "day_index": day_index,
            "exercise_index": exercise_index,
            "field": field,
        },
    }


def _published_program(draft: dict[str, Any], db: Any) -> dict[str, Any]:
    days = draft.get("days", [])
    if not days:
        raise ProgramDraftValidationError.one(
            "no_days", "A program needs at least one training day.", field="days"
        )

    issues = []
    program = {**draft, "days": []}
    for day_index, day in enumerate(days):
        published_day = {**day, "exercises": []}
        for exercise_index, exercise in enumerate(day.get("exercises", [])):
            entry = db.get_exercise_library_entry(exercise["exercise_id"])
            if entry is None:
                issues.append(
                    {
                        "code": "unknown_exercise",
                        "message": "Exercise is not in the Exercise library.",
                        "location": {
                            "day_index": day_index,
                            "exercise_index": exercise_index,
                            "field": "exercise_id",
                        },
                    }
                )
                continue
            raw_rir = exercise.get("target_rir", DEFAULT_TARGET_RIR)
            try:
                target_rir = float(raw_rir)
            except (TypeError, ValueError, OverflowError):
                target_rir = float("nan")
            if not MIN_TARGET_RIR <= target_rir <= MAX_TARGET_RIR:
                issues.append(
                    {
                        "code": "invalid_rir",
                        "message": f"Target RIR must be from {MIN_TARGET_RIR:g} to {MAX_TARGET_RIR:g}.",
                        "location": {
                            "day_index": day_index,
                            "exercise_index": exercise_index,
                            "field": "target_rir",
                        },
                    }
                )
                continue
            published_exercise = dict(exercise)
            published_exercise.pop("target_rir", None)
            published_exercise["target_rpe"] = 10 - target_rir
            published_exercise.update(
                exercise_name=entry["name"],
                equipment=entry["equipment"],
                image_path=entry["image_path"],
                gif_path=entry["gif_path"],
            )
            published_day["exercises"].append(published_exercise)
        program["days"].append(published_day)
    if issues:
        raise ProgramDraftValidationError(issues)

    try:
        validated = PersistedProgramSchema.model_validate(program)
    except ValidationError as error:
        raise ProgramDraftValidationError([_pydantic_issue(issue) for issue in error.errors()]) from error

    issues = []
    for day_index, day in enumerate(validated.days):
        for exercise_index, exercise in enumerate(day.exercises):
            if exercise.target_reps_min > exercise.target_reps_max:
                issues.append(
                    {
                        "code": "invalid_reps",
                        "message": f"Reps must be from {MIN_REPS} to {MAX_REPS}, with the lower bound first.",
                        "location": {
                            "day_index": day_index,
                            "exercise_index": exercise_index,
                            "field": "target_reps_min",
                        },
                    }
                )
    if issues:
        raise ProgramDraftValidationError(issues)
    return validated.model_dump()


def publish_program_draft(
    db: Any,
    coach_account_id: str,
    assignment_id: str,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> Any | None:
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, context = authorized
    with ledger:
        prior_publication = ledger.has_program_published_by_coach_since(
            coach_account_id, context["assignment"]["started_at"]
        )
        with ledger.ledger_transaction():
            draft_record = ledger.get_program_draft(assignment_id)
            if draft_record is None:
                raise ProgramDraftNotFound("Program draft not found.")
            program_data = _published_program(draft_record["draft"], db)
            ledger.save_training_program(program_data, published_by_coach_account_id=coach_account_id)
            ledger.discard_program_draft(assignment_id)
            published = ledger.get_active_program()
        if published is None:
            raise RuntimeError("Published program is missing from the player ledger after save.")
    record_program_publication(
        db,
        context,
        published,
        actor=ProgramAnalyticsActor(coach_account_id, "coach"),
        first_for_assignment=not prior_publication,
        client=client,
    )
    return published
