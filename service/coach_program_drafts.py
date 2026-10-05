"""Assignment-gated lifecycle for coach-authored Program drafts."""

from typing import Any

from pydantic import ValidationError

from agent.ProgramState import PersistedProgramSchema
from agent.program_prescription import (
    DEFAULT_TARGET_RIR,
    MAX_EXERCISES_PER_DAY,
    MAX_PROGRAM_DAYS,
    MAX_PROGRAM_NOTES_LENGTH,
    MAX_REPS,
    MAX_RAMPED_WARMUP_SETS,
    MAX_TEMPO_LENGTH,
    MAX_TARGET_RIR,
    MAX_WARMUP_MOVEMENT_REPS,
    MAX_WARMUP_MOVEMENT_SETS,
    MIN_REPS,
    MIN_RAMPED_WARMUP_SETS,
    MIN_TARGET_RIR,
    MIN_WARMUP_MOVEMENT_REPS,
    MIN_WARMUP_MOVEMENT_SETS,
)
from service import analytics
from service.assignments import authorized_player_ledger
from service.coach_programs import ProgramPublicationDetails, record_program_publication
from service.program_change_summary import summarize_program_change
from database.exercise_resolution import resolve_exercise_display_row
from service.program_analytics import ProgramAnalyticsActor


class ProgramDraftNotFound(Exception):
    """Raised when an active assignment has no open Program draft."""


class ActiveProgramNotFound(Exception):
    """Raised when an active assignment has no Training program to copy."""


class ActiveProgramVersionMismatch(Exception):
    """Raised when a Program approval targets a version that is no longer active."""

    def __init__(self, active_version: int | None):
        super().__init__("The active Program changed before approval.")
        self.active_version = active_version


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
        warmup_movement_index: int | None = None,
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
                        "warmup_movement_index": warmup_movement_index,
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


def ensure_generated_program_draft_available(
    ledger: Any, assignment_id: str, *, replace_existing: bool
) -> None:
    """Reject an unconfirmed replacement before starting generation."""
    if not replace_existing and ledger.get_program_draft(assignment_id) is not None:
        raise ProgramDraftAlreadyExists("A Program draft already exists for this assignment.")


def create_generated_program_draft(ledger: Any, assignment_id: str, draft: dict[str, Any]) -> Any:
    created = ledger.create_program_draft(assignment_id, draft)
    if created is None:
        raise ProgramDraftAlreadyExists("A Program draft already exists for this assignment.")
    return created


def replace_generated_program_draft(ledger: Any, assignment_id: str, draft: dict[str, Any]) -> Any:
    replaced = ledger.replace_program_draft(assignment_id, draft)
    if replaced is not None:
        return replaced
    created = ledger.create_program_draft(assignment_id, draft)
    if created is not None:
        return created
    replaced = ledger.replace_program_draft(assignment_id, draft)
    if replaced is None:
        raise ProgramDraftAlreadyExists("The Program draft changed while it was being generated.")
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
    warmup_movement_index = None
    field = "program"
    if "days" in loc:
        day_at = loc.index("days")
        if len(loc) > day_at + 1 and isinstance(loc[day_at + 1], int):
            day_index = loc[day_at + 1]
        if len(loc) > day_at + 2:
            section = loc[day_at + 2]
            if section == "exercises":
                if len(loc) > day_at + 3 and isinstance(loc[day_at + 3], int):
                    exercise_index = loc[day_at + 3]
                if len(loc) > day_at + 4:
                    field = str(loc[day_at + 4])
                else:
                    field = str(section)
            elif section == "warmup_exercises":
                if len(loc) > day_at + 3 and isinstance(loc[day_at + 3], int):
                    warmup_movement_index = loc[day_at + 3]
                field = (
                    str(loc[day_at + 4])
                    if len(loc) > day_at + 4
                    else str(section)
                )
            else:
                field = str(section)
        elif len(loc) > day_at + 1:
            field = str(loc[day_at + 1])
    elif loc:
        field = str(loc[0])

    error_type = str(error.get("type", ""))
    if field == "days" and error_type == "too_long":
        code, message = "too_many_days", f"A program can have at most {MAX_PROGRAM_DAYS} training days."
    elif field == "exercises" and error_type == "too_long":
        code, message = "too_many_exercises", f"A training day can have at most {MAX_EXERCISES_PER_DAY} exercises."
    elif field == "exercises" and error_type == "too_short":
        code, message = "empty_day", "Each training day needs at least one exercise."
    elif field == "target_sets":
        code, message = "invalid_sets", "Working sets must be at least 1."
    elif field in {"target_reps_min", "target_reps_max"}:
        code, message = "invalid_reps", f"Reps must be from {MIN_REPS} to {MAX_REPS}."
    elif field == "target_rpe":
        code, message = "invalid_rir", f"Target RIR must be from {MIN_TARGET_RIR:g} to {MAX_TARGET_RIR:g}."
    elif field == "warmup_sets":
        code, message = "invalid_warmup_sets", f"Warm-up sets must be from {MIN_RAMPED_WARMUP_SETS} to {MAX_RAMPED_WARMUP_SETS}."
    elif field == "sets":
        code, message = "invalid_movement_sets", f"Warm-up movements need {MIN_WARMUP_MOVEMENT_SETS} to {MAX_WARMUP_MOVEMENT_SETS} sets."
    elif field == "reps":
        code, message = "invalid_movement_reps", f"Warm-up movement reps must be from {MIN_WARMUP_MOVEMENT_REPS} to {MAX_WARMUP_MOVEMENT_REPS}."
    elif field == "day_order":
        code, message = "invalid_day_order", f"Training day order must be from 1 to {MAX_PROGRAM_DAYS}."
    elif field == "weekly_frequency":
        code, message = "invalid_weekly_frequency", f"Weekly frequency must be from 1 to {MAX_PROGRAM_DAYS}."
    elif field == "tempo" and error_type == "string_too_long":
        code, message = "tempo_too_long", f"Tempo must be at most {MAX_TEMPO_LENGTH} characters."
    elif field == "notes" and error_type == "string_too_long":
        code, message = "notes_too_long", f"Notes must be at most {MAX_PROGRAM_NOTES_LENGTH} characters."
    else:
        code, message = "invalid_program_field", "This program field is invalid."
    return {
        "code": code,
        "message": message,
        "location": {
            "day_index": day_index,
            "exercise_index": exercise_index,
            "warmup_movement_index": warmup_movement_index,
            "field": field,
        },
    }


def _active_program_as_draft(program: PersistedProgramSchema) -> dict[str, Any]:
    from svc.schemas import CoachProgramDraftIn

    try:
        return CoachProgramDraftIn.model_validate(
            program.model_dump(
                exclude={"version", "published_by_coach_account_id", "created_at"}
            )
        ).model_dump()
    except ValidationError as error:
        raise ProgramDraftValidationError(
            [_pydantic_issue(issue) for issue in error.errors()]
        ) from error


def copy_active_program_to_draft(
    db: Any,
    coach_account_id: str,
    assignment_id: str,
    *,
    replace: bool = False,
) -> dict[str, Any] | None:
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, _ = authorized
    with ledger:
        program = ledger.get_active_program()
        if program is None:
            raise ActiveProgramNotFound("No active program to copy.")
        draft = _active_program_as_draft(program)
        if replace:
            stored = ledger.replace_program_draft(assignment_id, draft)
            if stored is None:
                stored = ledger.create_program_draft(assignment_id, draft)
        else:
            stored = ledger.create_program_draft(assignment_id, draft)
        if stored is None:
            raise ProgramDraftAlreadyExists("A Program draft already exists for this assignment.")
        if not _assignment_still_active(db, coach_account_id, assignment_id):
            ledger.discard_program_draft(assignment_id)
            return None
        return stored


def _published_program(
    draft: dict[str, Any], db: Any, coach_account_id: str, ledger: Any
) -> dict[str, Any]:
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
            is_coach_exercise = False
            if entry is None:
                entry = db.get_coach_exercise(coach_account_id, exercise["exercise_id"])
                is_coach_exercise = entry is not None
            if entry is None and ledger.has_exercise_in_program_history(exercise["exercise_id"]):
                entry = db.get_coach_exercise_unscoped(exercise["exercise_id"])
                is_coach_exercise = entry is not None
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
                body_part=entry.get("body_part") if is_coach_exercise else None,
                equipment=entry["equipment"],
                image_path=entry["image_path"],
                gif_path=entry["gif_path"],
                note=entry.get("note") if is_coach_exercise else None,
                video_url=entry.get("video_url") if is_coach_exercise else None,
                is_coach_exercise=is_coach_exercise,
                suggested_substitutes=[] if is_coach_exercise else exercise.get("suggested_substitutes", []),
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


def validate_generated_program_draft(
    generated: dict[str, Any],
    days: list[dict[str, Any]],
    db: Any,
    coach_account_id: str,
    ledger: Any,
) -> dict[str, Any]:
    """Convert generated content to a valid, publishable Program draft."""
    from svc.schemas import CoachProgramDraftIn

    try:
        draft = CoachProgramDraftIn.model_validate(
            {
                "program_name": generated["program_name"],
                "split_type": generated["split_type"],
                "weekly_frequency": generated["weekly_frequency"],
                "instructions": "",
                "days": days,
            }
        ).model_dump()
    except ValidationError as error:
        raise ProgramDraftValidationError(
            [_pydantic_issue(issue) for issue in error.errors()]
        ) from error
    _published_program(draft, db, coach_account_id, ledger)
    return draft


def _publish_program(
    db: Any,
    coach_account_id: str,
    assignment_id: str,
    client: analytics.ClientContext,
    *,
    approve_version: int | None = None,
) -> Any | None:
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, assignment_context = authorized
    publishes_draft = approve_version is None
    with ledger:
        with ledger.ledger_transaction():
            prior_publication = ledger.has_program_published_by_coach_since(
                coach_account_id,
                assignment_context["assignment"]["started_at"],
            )
            previous_program = ledger.get_active_program()
            if publishes_draft:
                draft_record = ledger.get_program_draft(assignment_id)
                if draft_record is None:
                    raise ProgramDraftNotFound("Program draft not found.")
                source_draft = draft_record["draft"]
            else:
                active_program = previous_program
                if active_program is None:
                    raise ActiveProgramNotFound("No active program to approve.")
                if active_program.version != approve_version:
                    raise ActiveProgramVersionMismatch(active_program.version)
                source_draft = _active_program_as_draft(active_program)
            program_data = _published_program(
                source_draft, db, coach_account_id, ledger
            )
            program_change_summary = summarize_program_change(
                previous_program,
                PersistedProgramSchema.model_validate(program_data),
                lambda exercise_id: _published_exercise_display_name(db, exercise_id),
            )
            ledger.save_training_program(
                program_data,
                published_by_coach_account_id=coach_account_id,
            )
            if publishes_draft:
                ledger.discard_program_draft(assignment_id)
            published = ledger.get_active_program()
    if published is None:
        raise RuntimeError("Published program is missing from the player ledger after save.")
    record_program_publication(
        db,
        assignment_context,
        published,
        ProgramPublicationDetails(
            actor=ProgramAnalyticsActor(coach_account_id, "coach"),
            first_for_assignment=not prior_publication,
            change_summary=program_change_summary,
            client=client,
        ),
    )
    return published


def _published_exercise_display_name(db: Any, exercise_id: str) -> str | None:
    row = resolve_exercise_display_row(db, exercise_id)
    if row is None:
        return None
    return row.get("name") or row.get("display_name")


def publish_program_draft(
    db: Any,
    coach_account_id: str,
    assignment_id: str,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> Any | None:
    return _publish_program(
        db,
        coach_account_id,
        assignment_id,
        client,
    )


def approve_active_program(
    db: Any,
    coach_account_id: str,
    assignment_id: str,
    expected_active_version: int,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> Any | None:
    """Approves and publishes the active Program snapshot if its version is unchanged."""
    return _publish_program(
        db,
        coach_account_id,
        assignment_id,
        client,
        approve_version=expected_active_version,
    )
