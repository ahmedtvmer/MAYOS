"""Assignment-gated lifecycle for coach-authored Program drafts."""

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from agent.ProgramState import (
    MAX_PROGRAM_LOAD_KG,
    MAX_PROGRAM_LOAD_PCT_E1RM,
    MIN_PROGRAM_LOAD_KG,
    MIN_PROGRAM_LOAD_PCT_E1RM,
    PersistedProgramSchema,
)
from agent.program_weeks import (
    default_week_name,
    flatten_program_days,
    normalize_program_weeks,
)
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
from database.exercise_resolution import resolve_exercise_display_row
from service import analytics
from service import program_requests as program_requests_service
from service.assignments import authorized_player_ledger
from service.coach_programs import ProgramPublicationDetails, record_program_publication
from service.program_change_summary import summarize_program_change
from service.program_analytics import ProgramAnalyticsActor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProgramPublicationResult:
    program: Any
    resolved_request_ids: list[str]


@dataclass(frozen=True)
class _ProgramPublishContext:
    db: Any
    coach_account_id: str
    ledger_handle: Any | None


@dataclass(frozen=True)
class _ProgramDayPosition:
    week_order: int
    week_index: int
    day_index: int
    week_count: int


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


class ProgramDraftSourceMismatch(Exception):
    """Raised when a template publish finds the draft's origin changed (#306)."""


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


def draft_source_template_name(
    db: Any, coach_account_id: str, record: dict[str, Any] | None
) -> str | None:
    """Resolves the owning Coach's template name recorded as a draft's origin (#306).

    The id is stored server-side on the draft; the label is resolved from the
    catalog at read time. A template that no longer exists yields ``None`` and
    never fails the draft read.
    """
    if not record:
        return None
    template_id = record.get("source_template_id")
    if not template_id:
        return None
    template = db.get_program_template(coach_account_id, template_id)
    return template["name"] if template else None


def _with_source_template_label(
    db: Any, coach_account_id: str, record: dict[str, Any] | None
) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        **record,
        "source_template_name": draft_source_template_name(db, coach_account_id, record),
    }


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
        return _with_source_template_label(db, coach_account_id, created)


def read_program_draft(db: Any, coach_account_id: str, assignment_id: str) -> dict[str, Any] | None:
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, _ = authorized
    with ledger:
        draft = ledger.get_program_draft(assignment_id)
    if draft is None:
        raise ProgramDraftNotFound("Program draft not found.")
    return _with_source_template_label(db, coach_account_id, draft)


def replace_program_draft(
    db: Any,
    coach_account_id: str,
    assignment_id: str,
    draft: dict[str, Any],
    *,
    preserve_source_template: bool = True,
) -> dict[str, Any] | None:
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, _ = authorized
    with ledger:
        if preserve_source_template:
            replaced = ledger.replace_program_draft(assignment_id, draft)
        else:
            replaced = ledger.replace_program_draft(assignment_id, draft, source_template_id=None)
        if replaced is None:
            raise ProgramDraftNotFound("Program draft not found.")
        if not _assignment_still_active(db, coach_account_id, assignment_id):
            ledger.discard_program_draft(assignment_id)
            return None
        return _with_source_template_label(db, coach_account_id, replaced)


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
    # A freshly generated draft has no template origin; clearing any stale stored
    # origin keeps provenance honest when generation replaces a template draft.
    replaced = ledger.replace_program_draft(assignment_id, draft, source_template_id=None)
    if replaced is not None:
        return replaced
    created = ledger.create_program_draft(assignment_id, draft, source_template_id=None)
    if created is not None:
        return created
    replaced = ledger.replace_program_draft(assignment_id, draft, source_template_id=None)
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
    elif field == "load":
        code = "invalid_load"
        message = (
            f"Load must be greater than {MIN_PROGRAM_LOAD_KG:g} and at most "
            f"{MAX_PROGRAM_LOAD_KG:g} kg, or "
            f"{MIN_PROGRAM_LOAD_PCT_E1RM:g}–{MAX_PROGRAM_LOAD_PCT_E1RM:g}% e1RM."
        )
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


def active_program_as_draft(program: PersistedProgramSchema) -> dict[str, Any]:
    from svc.schemas import CoachProgramDraftIn

    try:
        return CoachProgramDraftIn.model_validate(
            program.model_dump(
                exclude={
                    "version",
                    "published_by_coach_account_id",
                    "source_template_id",
                    "source_template_name",
                    "created_at",
                    "design_version",
                }
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
        draft = active_program_as_draft(program)
        source_template_id = program.source_template_id

        if replace:
            stored = ledger.replace_program_draft(
                assignment_id, draft, source_template_id=source_template_id
            )
            if stored is None:
                stored = ledger.create_program_draft(
                    assignment_id, draft, source_template_id=source_template_id
                )
        else:
            stored = ledger.create_program_draft(
                assignment_id, draft, source_template_id=source_template_id
            )
        if stored is None:
            raise ProgramDraftAlreadyExists("A Program draft already exists for this assignment.")
        if not _assignment_still_active(db, coach_account_id, assignment_id):
            ledger.discard_program_draft(assignment_id)
            return None
        return _with_source_template_label(db, coach_account_id, stored)


def _published_program(
    draft: dict[str, Any], db: Any, coach_account_id: str, ledger: Any | None
) -> dict[str, Any]:
    weeks = normalize_program_weeks(draft)
    if not any(week.get("days") for week in weeks):
        raise ProgramDraftValidationError.one(
            "no_days", "A program needs at least one training day.", field="days"
        )
    context = _ProgramPublishContext(db, coach_account_id, ledger)
    published_weeks, issues = _published_weeks(weeks, context)
    program = {
        **draft,
        "weekly_frequency": (
            draft.get("weekly_frequency", 1)
            if len(published_weeks) == 1
            else max((len(week["days"]) for week in published_weeks), default=1)
        ),
        "days": flatten_program_days(published_weeks),
        "weeks": published_weeks,
    }
    if issues:
        raise ProgramDraftValidationError(issues)
    return _validate_published_program(program)


def normalize_program_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Normalizes a Program draft to the stored multiweek shape (weeks + flat days)."""
    weeks = normalize_program_weeks(draft)
    return {
        **draft,
        "weekly_frequency": (
            draft.get("weekly_frequency", 1)
            if len(weeks) == 1
            else max((len(week["days"]) for week in weeks), default=1)
        ),
        "days": flatten_program_days(weeks),
        "weeks": weeks,
    }


def validate_publishable_program(
    draft: dict[str, Any], db: Any, coach_account_id: str
) -> dict[str, Any]:
    """Validates a draft exactly as publication would, then returns it normalized.

    The owning coach's Coach exercises resolve. A template has no player ledger,
    so no player history is consulted: a Coach exercise from another coach is
    rejected even when some player's history contains its id (ticket #305).
    """
    _published_program(draft, db, coach_account_id, None)
    return normalize_program_draft(draft)


def canonical_publishable_draft(
    draft: dict[str, Any], db: Any, coach_account_id: str
) -> dict[str, Any]:
    """Returns the publication-normalized draft with trusted catalog metadata.

    ``validate_publishable_program`` only proves publishability and echoes the
    caller's draft, including any free text it carried. This instead returns the
    sanitized article a publication would persist: exercise names, equipment,
    media and catalog notes are re-derived from trusted catalog/coach-library
    entries, so untrusted free text on a copied draft can never reach a stored
    template (ticket #307).
    """
    published = _published_program(draft, db, coach_account_id, None)
    return active_program_as_draft(PersistedProgramSchema.model_validate(published))


def _published_weeks(
    weeks: list[dict[str, Any]], context: _ProgramPublishContext
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    published_weeks = []
    issues = []
    week_count = len(weeks)
    for week_index, week in enumerate(weeks):
        published_week, week_issues = _published_week(
            week, week_index, week_count, context
        )
        published_weeks.append(published_week)
        issues.extend(week_issues)
    return published_weeks, issues


def _published_week(
    week: dict[str, Any],
    week_index: int,
    week_count: int,
    context: _ProgramPublishContext,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    week_order = week_index + 1
    published_days = []
    issues = []
    for day_index, day in enumerate(week.get("days", [])):
        position = _ProgramDayPosition(week_order, week_index, day_index, week_count)
        published_day, day_issues = _published_day(
            day, position, context
        )
        published_days.append(published_day)
        issues.extend(day_issues)
    return {
        "week_name": week.get("week_name") or default_week_name(week_order),
        "week_order": week_order,
        "days": published_days,
    }, issues


def _published_day(
    day: dict[str, Any],
    position: _ProgramDayPosition,
    context: _ProgramPublishContext,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    exercises = []
    issues = []
    for exercise_index, exercise in enumerate(day.get("exercises", [])):
        published, issue = _published_exercise(
            exercise, position, exercise_index, context
        )
        if issue is not None:
            issues.append(issue)
        if published is not None:
            exercises.append(published)
    return {
        **day,
        "day_order": day.get("day_order", position.day_index + 1)
        if position.week_count == 1
        else position.day_index + 1,
        "week_order": position.week_order,
        "exercises": exercises,
    }, issues


def _published_exercise(
    exercise: dict[str, Any],
    position: _ProgramDayPosition,
    exercise_index: int,
    context: _ProgramPublishContext,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    entry, is_coach_exercise = _program_exercise_entry(exercise, context)
    if entry is None:
        return None, _unknown_exercise_issue(position, exercise_index)
    target_rir = _valid_target_rir(exercise.get("target_rir", DEFAULT_TARGET_RIR))
    if target_rir is None:
        return None, _invalid_target_rir_issue(position, exercise_index)
    return _program_exercise_payload(exercise, entry, is_coach_exercise, target_rir), None


def _program_exercise_entry(
    exercise: dict[str, Any], context: _ProgramPublishContext
) -> tuple[dict[str, Any] | None, bool]:
    exercise_id = exercise["exercise_id"]
    entry = context.db.get_exercise_library_entry(exercise_id)
    is_coach_exercise = False
    if entry is None:
        entry = context.db.get_coach_exercise(context.coach_account_id, exercise_id)
        is_coach_exercise = entry is not None
    if (
        entry is None
        and context.ledger_handle is not None
        and context.ledger_handle.has_exercise_in_program_history(exercise_id)
    ):
        entry = context.db.get_coach_exercise_unscoped(exercise_id)
        is_coach_exercise = entry is not None
    return entry, is_coach_exercise


def _valid_target_rir(value: Any) -> float | None:
    try:
        target_rir = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return target_rir if MIN_TARGET_RIR <= target_rir <= MAX_TARGET_RIR else None


def _unknown_exercise_issue(
    position: _ProgramDayPosition, exercise_index: int
) -> dict[str, Any]:
    return _program_exercise_issue(
        "unknown_exercise",
        "Exercise is not in the Exercise library.",
        _program_exercise_location(position, exercise_index, "exercise_id"),
    )


def _invalid_target_rir_issue(
    position: _ProgramDayPosition, exercise_index: int
) -> dict[str, Any]:
    return _program_exercise_issue(
        "invalid_rir",
        f"Target RIR must be from {MIN_TARGET_RIR:g} to {MAX_TARGET_RIR:g}.",
        _program_exercise_location(position, exercise_index, "target_rir"),
    )


def _program_exercise_location(
    position: _ProgramDayPosition, exercise_index: int, field: str
) -> dict[str, Any]:
    location = {
        "day_index": position.day_index,
        "exercise_index": exercise_index,
        "field": field,
    }
    if position.week_count > 1:
        location["week_index"] = position.week_index
    return location


def _program_exercise_issue(
    code: str, message: str, location: dict[str, Any]
) -> dict[str, Any]:
    return {"code": code, "message": message, "location": location}


def _program_exercise_payload(
    exercise: dict[str, Any],
    entry: dict[str, Any],
    is_coach_exercise: bool,
    target_rir: float,
) -> dict[str, Any]:
    published = dict(exercise)
    published.pop("target_rir", None)
    published["target_rpe"] = 10 - target_rir
    published.update(
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
    return published


def _validate_published_program(program: dict[str, Any]) -> dict[str, Any]:
    try:
        validated = PersistedProgramSchema.model_validate(program)
    except ValidationError as error:
        raise ProgramDraftValidationError([_pydantic_issue(issue) for issue in error.errors()]) from error

    _validate_program_rep_ranges(validated.days, len(validated.weeks))
    return validated.model_dump()


def _validate_program_rep_ranges(days: list[Any], week_count: int) -> None:
    issues = []
    for day in days:
        for exercise_index, exercise in enumerate(day.exercises):
            if exercise.target_reps_min > exercise.target_reps_max:
                issues.append(_invalid_rep_range_issue(day, exercise_index, week_count))
    if issues:
        raise ProgramDraftValidationError(issues)


def _invalid_rep_range_issue(
    day: Any, exercise_index: int, week_count: int
) -> dict[str, Any]:
    location = {
        "day_index": day.day_order - 1,
        "exercise_index": exercise_index,
        "field": "target_reps_min",
    }
    if week_count > 1:
        location["week_index"] = day.week_order - 1
    return {
        "code": "invalid_reps",
        "message": f"Reps must be from {MIN_REPS} to {MAX_REPS}, with the lower bound first.",
        "location": location,
    }


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
    resolve_request_ids: list[str] | None = None,
    expected_source_template_id: str | None = None,
) -> Any | None:
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, assignment_context = authorized
    selected_requests = program_requests_service.validate_publish_request_ids(
        db, coach_account_id, assignment_id, resolve_request_ids or []
    )
    publishes_draft = approve_version is None
    with ledger:
        with ledger.ledger_transaction():
            prior_publication = ledger.has_program_published_by_coach_since(
                coach_account_id,
                assignment_context["assignment"]["started_at"],
            )
            previous_program = ledger.get_active_program()
            starting_position = (
                ledger.get_program_position(previous_program)
                if not publishes_draft and previous_program is not None
                else None
            )
            source_template_id = None
            if publishes_draft:
                draft_record = ledger.get_program_draft(assignment_id)
                if draft_record is None:
                    raise ProgramDraftNotFound("Program draft not found.")
                source_draft = draft_record["draft"]
                source_template_id = draft_record.get("source_template_id")
                if (
                    expected_source_template_id is not None
                    and source_template_id != expected_source_template_id
                ):
                    # Verify the draft's origin inside the same gated transaction
                    # that would publish it, so a draft swapped between assign and
                    # publish can never be published as the expected template (#306).
                    raise ProgramDraftSourceMismatch(
                        "The Program draft changed before it could be published."
                    )
            else:
                active_program = previous_program
                if active_program is None:
                    raise ActiveProgramNotFound("No active program to approve.")
                if active_program.version != approve_version:
                    raise ActiveProgramVersionMismatch(active_program.version)
                source_draft = active_program_as_draft(active_program)
                source_template_id = active_program.source_template_id

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
                starting_position=starting_position,
                source_template_id=source_template_id,
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
    resolved_request_ids = []
    if selected_requests:
        try:
            resolved_request_ids = program_requests_service.resolve_published_requests(
                db,
                ProgramAnalyticsActor(coach_account_id, "coach"),
                selected_requests,
                int(published.version or 0),
                client=client,
            )
        except Exception:
            logger.warning("Program request resolution failed after program publication", exc_info=True)
    return ProgramPublicationResult(published, resolved_request_ids)


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
    *,
    resolve_request_ids: list[str] | None = None,
    expected_source_template_id: str | None = None,
) -> Any | None:
    return _publish_program(
        db,
        coach_account_id,
        assignment_id,
        client,
        resolve_request_ids=resolve_request_ids,
        expected_source_template_id=expected_source_template_id,
    )


def approve_active_program(
    db: Any,
    coach_account_id: str,
    assignment_id: str,
    expected_active_version: int,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
    *,
    resolve_request_ids: list[str] | None = None,
) -> Any | None:
    """Approves and publishes the active Program snapshot if its version is unchanged."""
    return _publish_program(
        db,
        coach_account_id,
        assignment_id,
        client,
        approve_version=expected_active_version,
        resolve_request_ids=resolve_request_ids,
    )
