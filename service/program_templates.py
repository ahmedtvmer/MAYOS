"""Coach-owned Program template library (ticket #305).

A template lives in the shared catalog, belongs to exactly one coach, and holds
no player data or Assignment reference. It stores the same normalized multiweek
Program shape as a Program draft, and every write is validated exactly as a
draft publication would be, so a template can only ever produce a publishable
program.
"""

import copy
from typing import Any

from agent.program_weeks import (
    find_program_day,
    flatten_program_days,
    normalize_program_weeks,
)
from database.registry.coach_exercises import (
    COACH_EXERCISE_ID_PREFIX,
    CoachExerciseCreate,
)
from database.registry.program_templates import ProgramTemplateCreate
from service.assignments import (
    DENIED_ERROR,
    authorized_active_assignment,
    authorized_player_ledger,
)
from service import program_requests as program_requests_service
from service.coach_program_drafts import (
    ActiveProgramNotFound,
    ProgramDraftNotFound,
    ProgramDraftSourceMismatch,
    ProgramDraftValidationError,
    active_program_as_draft,
    canonical_publishable_draft,
    draft_source_template_name,
    publish_program_draft,
    validate_publishable_program,
)

MAX_TEMPLATE_NAME_LENGTH = 120
_COPY_SUFFIX = " (copy)"

SKIP_EXISTING_DRAFT = "skip"

ASSIGNED = "assigned"
REPLACED = "replaced"
SKIPPED = "skipped"
REJECTED = "rejected"
PUBLISHED = "published"
INVALID = "invalid"
NO_DRAFT = "no_draft"

SOURCE_ACTIVE_PROGRAM = "active"
SOURCE_PROGRAM_DRAFT = "draft"


class ProgramTemplateNotFound(Exception):
    """Raised when a template is unknown or owned by another coach."""


class ProgramSourceChanged(Exception):
    """Raised when the reviewed source program changed before it was copied.

    Saving a program as a template copies what the coach reviewed. If the active
    program was republished or the Program draft was replaced (here or by another
    device) between review and save, the copy would silently disagree with the
    review, so the save is refused rather than guessing (ticket #307).
    """


def _clean_description(description: str | None) -> str | None:
    if description is None:
        return None
    trimmed = description.strip()
    return trimmed or None


def _copy_name(source_name: str) -> str:
    """Builds a non-blank duplicate name that always fits the name bound."""
    room = MAX_TEMPLATE_NAME_LENGTH - len(_COPY_SUFFIX)
    base = source_name[:room].strip() or source_name[:room]
    return f"{base}{_COPY_SUFFIX}"


def create_program_template(
    db: Any,
    coach_account_id: str,
    *,
    name: str,
    description: str | None,
    program: dict[str, Any],
) -> dict[str, Any]:
    fields = ProgramTemplateCreate(
        name=name,
        description=_clean_description(description),
        program=validate_publishable_program(program, db, coach_account_id),
    )
    return db.create_program_template(coach_account_id, fields)


def list_program_templates(
    db: Any, coach_account_id: str, *, archived: bool
) -> list[dict[str, Any]]:
    return db.list_program_templates(coach_account_id, archived=archived)


def read_program_template(
    db: Any, coach_account_id: str, template_id: str
) -> dict[str, Any]:
    template = db.get_program_template(coach_account_id, template_id)
    if template is None:
        raise ProgramTemplateNotFound("Program template not found.")
    return template


def update_program_template(
    db: Any,
    coach_account_id: str,
    template_id: str,
    *,
    name: str,
    description: str | None,
    program: dict[str, Any],
) -> dict[str, Any]:
    # Ownership is decided before semantic validation so a foreign or unknown id
    # always returns the same 404, never a 400 that would reveal its existence.
    if db.get_program_template(coach_account_id, template_id) is None:
        raise ProgramTemplateNotFound("Program template not found.")
    updated = db.update_program_template(
        coach_account_id,
        template_id,
        name=name,
        description=_clean_description(description),
        program=validate_publishable_program(program, db, coach_account_id),
    )
    if updated is None:
        raise ProgramTemplateNotFound("Program template not found.")
    return updated


def duplicate_program_template(
    db: Any,
    coach_account_id: str,
    template_id: str,
    *,
    name: str | None = None,
) -> dict[str, Any]:
    source = read_program_template(db, coach_account_id, template_id)
    fields = ProgramTemplateCreate(
        name=name if name else _copy_name(source["name"]),
        description=source["description"],
        program=source["program"],
    )
    return db.create_program_template(coach_account_id, fields)


def set_program_template_archived(
    db: Any, coach_account_id: str, template_id: str, *, archived: bool
) -> dict[str, Any]:
    updated = db.set_program_template_archived(
        coach_account_id, template_id, archived=archived
    )
    if updated is None:
        raise ProgramTemplateNotFound("Program template not found.")
    return updated


def _rejection(assignment_id: str, message_code: str, message_fallback: str) -> dict[str, Any]:
    return {
        "assignment_id": assignment_id,
        "status": REJECTED,
        "message_code": message_code,
        "message_fallback": message_fallback,
    }


def _assignment_still_active(db: Any, coach_account_id: str, assignment_id: str) -> bool:
    return db.get_active_assignment_for_coach(coach_account_id, assignment_id) is not None


def _draft_assignment_result(
    template: dict[str, Any], stored: dict[str, Any], status: str
) -> dict[str, Any]:
    return {
        "assignment_id": stored["assignment_id"],
        "status": status,
        "source_template_id": template["template_id"],
        "source_template_name": template["name"],
        "draft": {**stored, "source_template_name": template["name"]},
    }


def _skipped_assignment_result(
    db: Any, coach_account_id: str, stored: dict[str, Any]
) -> dict[str, Any]:
    """Reports a skipped draft with its ACTUAL stored origin, not the requested template (#306)."""
    return {
        "assignment_id": stored["assignment_id"],
        "status": SKIPPED,
        "source_template_id": stored.get("source_template_id"),
        "source_template_name": draft_source_template_name(
            db, coach_account_id, stored
        ),
        "draft": {
            **stored,
            "source_template_name": draft_source_template_name(
                db, coach_account_id, stored
            ),
        },
    }


def _assign_one(
    db: Any,
    coach_account_id: str,
    template: dict[str, Any],
    assignment_id: str,
    decision: str,
) -> dict[str, Any]:
    """Copies a template into one assignment's Program draft, gated per assignment.

    The ADR 025 gate runs before the ledger is mounted; a revoked, foreign, or
    non-owned assignment is rejected on its own and never fails the batch.
    """
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return _rejection(assignment_id, "assignment.none_active.v1", DENIED_ERROR)
    ledger, _ = authorized
    draft = copy.deepcopy(template["program"])
    template_id = template["template_id"]
    with ledger:
        existing = ledger.get_program_draft(assignment_id)
        if existing is not None and decision == SKIP_EXISTING_DRAFT:
            return _skipped_assignment_result(db, coach_account_id, existing)
        if existing is not None:
            stored = ledger.replace_program_draft(
                assignment_id, draft, source_template_id=template_id
            )
            status = REPLACED
        else:
            stored = ledger.create_program_draft(
                assignment_id, draft, source_template_id=template_id
            )
            status = ASSIGNED
            if stored is None:
                # A concurrent writer created the draft between the check and the
                # insert; honor the decision rather than dropping the copy.
                raced = ledger.get_program_draft(assignment_id)
                if decision == SKIP_EXISTING_DRAFT and raced is not None:
                    return _skipped_assignment_result(db, coach_account_id, raced)
                stored = ledger.replace_program_draft(
                    assignment_id, draft, source_template_id=template_id
                )
                status = REPLACED
        if not _assignment_still_active(db, coach_account_id, assignment_id):
            ledger.discard_program_draft(assignment_id)
            return _rejection(assignment_id, "assignment.none_active.v1", DENIED_ERROR)
    if stored is None:
        return _rejection(
            assignment_id, "assignment.program_draft_not_found.v1", "Program draft not found."
        )
    return _draft_assignment_result(template, stored, status)


def assign_program_template(
    db: Any,
    coach_account_id: str,
    template_id: str,
    targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assigns a template to each target assignment as an independent draft copy.

    Template ownership is decided first (a uniform 404 for an unknown or foreign
    id). Each assignment is then handled on its own: a bad assignment is reported
    in its result without failing the rest.
    """
    template = read_program_template(db, coach_account_id, template_id)
    return [
        _assign_one(
            db,
            coach_account_id,
            template,
            target["assignment_id"],
            target.get("existing_draft", SKIP_EXISTING_DRAFT),
        )
        for target in targets
    ]


def _pending_request_ids(db: Any, assignment_id: str) -> list[str]:
    return [
        request["request_id"]
        for request in db.list_program_requests_for_assignment(assignment_id)
        if request.get("status") == "pending"
    ]


def _publish_one(
    db: Any, coach_account_id: str, template_id: str, assignment_id: str, client: Any
) -> dict[str, Any]:
    # Catalog-only ADR 025 gate: the publish core below opens and closes the
    # player's ledger itself, so no second handle is mounted here.
    if authorized_active_assignment(db, coach_account_id, assignment_id) is None:
        return _rejection(assignment_id, "assignment.none_active.v1", DENIED_ERROR)
    try:
        published = publish_program_draft(
            db,
            coach_account_id,
            assignment_id,
            client,
            resolve_request_ids=_pending_request_ids(db, assignment_id),
            expected_source_template_id=template_id,
        )
    except ProgramDraftNotFound:
        return {
            "assignment_id": assignment_id,
            "status": NO_DRAFT,
            "message_code": "assignment.program_draft_not_found.v1",
            "message_fallback": "Program draft not found.",
        }
    except ProgramDraftValidationError as exc:
        return {
            "assignment_id": assignment_id,
            "status": INVALID,
            "message_code": "assignment.program_draft_invalid.v1",
            "message_fallback": "The Program draft has invalid fields.",
            "errors": exc.issues,
        }
    except ProgramDraftSourceMismatch:
        return _rejection(
            assignment_id,
            "assignment.program_draft_changed.v1",
            "The Program draft changed before it could be published.",
        )
    except program_requests_service.ProgramRequestSelectionError as exc:
        return _rejection(
            assignment_id, "program_request.selection_invalid.v1", str(exc)
        )
    if published is None:
        return _rejection(assignment_id, "assignment.none_active.v1", DENIED_ERROR)
    return {
        "assignment_id": assignment_id,
        "status": PUBLISHED,
        "version": published.program.version,
        "resolved_request_ids": published.resolved_request_ids,
        "resolved_request_count": len(published.resolved_request_ids),
    }


def publish_all_template_drafts(
    db: Any,
    coach_account_id: str,
    template_id: str,
    assignment_ids: list[str],
    client: Any,
) -> list[dict[str, Any]]:
    """Publishes each assignment's Program draft through the normal publish path.

    Ownership of the template is checked first (uniform 404). Only drafts still
    carrying this template as their origin are published; a draft since replaced
    by another origin is rejected per player, so 'Publish all' never ships an
    unrelated or manual draft. Each player's open requests resolve by default,
    and each player reports its own success, validation errors, or rejection
    without failing the batch.
    """
    read_program_template(db, coach_account_id, template_id)
    return [
        _publish_one(db, coach_account_id, template_id, assignment_id, client)
        for assignment_id in assignment_ids
    ]

def _blank_program_notes(weeks: list[dict[str, Any]]) -> None:
    """Clears every reviewed free-text note so only accepted ones survive."""
    for week in weeks:
        for day in week.get("days", []) or []:
            for movement in day.get("warmup_exercises", []) or []:
                movement["notes"] = None
            for exercise in day.get("exercises", []) or []:
                exercise["notes"] = None


def apply_program_template_notes(
    program: dict[str, Any], notes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Returns the program structure with only the reviewed notes kept.

    Every copied note starts blank, so a note the coach never confirmed is never
    carried into the template. Each decision addresses its source location by
    the stable week/day order and the item's position within that day.
    """
    weeks = normalize_program_weeks(program)
    _blank_program_notes(weeks)
    reviewed_locations: set[tuple[Any, ...]] = set()
    for decision in notes:
        field = decision["field"]
        if field == "program_instructions":
            location = (field,)
            if location in reviewed_locations:
                raise ProgramDraftValidationError.one(
                    "duplicate_review_location",
                    "A program text item was reviewed more than once.",
                    field="notes",
                )
            reviewed_locations.add(location)
            program["instructions"] = decision["value"] or ""
            continue

        week_order = decision.get("week_order")
        day_order = decision.get("day_order")
        day = (
            None
            if week_order is None or day_order is None
            else find_program_day(weeks, week_order, day_order=day_order)
        )
        if field == "day_cardio":
            location = (field, week_order, day_order)
            if location in reviewed_locations:
                raise ProgramDraftValidationError.one(
                    "duplicate_review_location",
                    "A program text item was reviewed more than once.",
                    field="notes",
                )
            reviewed_locations.add(location)
            if day is None:
                raise ProgramDraftValidationError.one(
                    "invalid_note_location",
                    "A reviewed cardio prescription pointed outside the copied program.",
                    field="notes",
                )
            day["cardio"] = decision["value"] or None
            continue

        item_index = decision.get("item_index")
        if field == "warmup_note":
            items = [] if day is None else day.get("warmup_exercises", []) or []
        else:
            items = [] if day is None else day.get("exercises", []) or []
        location = (field, week_order, day_order, item_index)
        if location in reviewed_locations:
            raise ProgramDraftValidationError.one(
                "duplicate_review_location",
                "A program text item was reviewed more than once.",
                field="notes",
            )
        reviewed_locations.add(location)
        if day is None or item_index is None or item_index >= len(items):
            raise ProgramDraftValidationError.one(
                "invalid_note_location",
                "A reviewed note pointed outside the copied program.",
                field="notes",
            )
        items[item_index]["notes"] = decision["value"]
    return {
        **program,
        "days": flatten_program_days(weeks),
        "weeks": weeks,
    }


_EXERCISE_STRUCTURE_FIELDS = (
    "exercise_id",
    "warmup_sets",
    "target_sets",
    "target_reps_min",
    "target_reps_max",
    "target_rir",
    "load",
    "set_groups",
    "rest_seconds",
    "tempo",
)
_EXERCISE_RPE_FALLBACK_FIELD = "target_rpe"
_WARMUP_STRUCTURE_FIELDS = (
    "exercise_id",
    "exercise_name",
    "equipment",
    "sets",
    "reps",
    "rest_seconds",
    "image_path",
    "gif_path",
)
_DAY_STRUCTURE_FIELDS = ("day_name", "day_order", "week_order")


def _pick(source: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: source[field] for field in fields if field in source}


def _exercise_structure(exercise: dict[str, Any]) -> dict[str, Any]:
    """Keeps only an exercise's prescription, dropping every piece of free text.

    Catalog metadata (``exercise_name``, ``equipment``, ``body_part``, media and
    ``note``) is deliberately omitted here: it is re-derived from the trusted
    catalog during canonicalization, never copied from the player's program.
    """
    structure = _pick(exercise, _EXERCISE_STRUCTURE_FIELDS)
    if "target_rir" not in structure and _EXERCISE_RPE_FALLBACK_FIELD in exercise:
        legacy_rpe = exercise[_EXERCISE_RPE_FALLBACK_FIELD]
        try:
            structure["target_rir"] = 10 - float(legacy_rpe)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ProgramDraftValidationError.one(
                "invalid_program_field",
                "A copied exercise had an invalid target effort.",
                field="target_rir",
            ) from exc
    return structure


def _reviewed_template_program(
    source: dict[str, Any], *, template_name: str, notes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Builds the template copy from an explicit allowlist of the source.

    Only accepted structural and prescription values survive from the player's
    program. The name is the coach-supplied template name, never the player's
    ``program_name``. Instructions and per-day cardio begin blank; only the
    explicit review decisions add them back. Generation options are omitted.
    """
    weeks: list[dict[str, Any]] = []
    for week in normalize_program_weeks(source):
        week_order = int(week.get("week_order", 1))
        days: list[dict[str, Any]] = []
        for day in week.get("days", []) or []:
            days.append(
                {
                    **_pick(day, _DAY_STRUCTURE_FIELDS),
                    "day_name": day.get("day_name") or f"Day {day.get('day_order', 1)}",
                    "day_order": int(day.get("day_order", 1)),
                    "week_order": int(day.get("week_order", week_order)),
                    "cardio": None,
                    "warmup_exercises": [
                        _pick(movement, _WARMUP_STRUCTURE_FIELDS)
                        for movement in day.get("warmup_exercises", []) or []
                    ],
                    "exercises": [
                        _exercise_structure(exercise)
                        for exercise in day.get("exercises", []) or []
                    ],
                }
            )
        weeks.append(
            {
                "week_name": week.get("week_name") or f"Week {week_order}",
                "week_order": week_order,
                "days": days,
            }
        )
    reviewed = {
        "program_name": template_name,
        "instructions": "",
        "split_type": source.get("split_type", "custom"),
        "weekly_frequency": source.get("weekly_frequency", 1),
        "weeks": weeks,
        "days": flatten_program_days(weeks),
    }
    return apply_program_template_notes(reviewed, notes)


def _active_program_revision(program: Any) -> str:
    version = getattr(program, "version", None)
    return "" if version is None else str(version)


def _copy_foreign_source_exercises(
    program: dict[str, Any], db: Any, coach_account_id: str, ledger: Any
) -> None:
    """Copies only foreign Coach exercises prescribed in this reviewed source.

    The definition comes from the catalog, never from the Player's program. Its
    Coach-authored note is private free text and is intentionally cleared.
    Repeated prescriptions share one new Coach-owned exercise id.
    """
    copied_ids: dict[str, dict[str, Any]] = {}
    for week in program["weeks"]:
        for day in week["days"]:
            for collection in ("warmup_exercises", "exercises"):
                for movement in day.get(collection, []) or []:
                    exercise_id = movement.get("exercise_id")
                    if (
                        not isinstance(exercise_id, str)
                        or not exercise_id.startswith(COACH_EXERCISE_ID_PREFIX)
                        or db.get_exercise_library_entry(exercise_id) is not None
                        or db.get_coach_exercise(coach_account_id, exercise_id) is not None
                    ):
                        continue
                    # A draft is coach-editable and can contain arbitrary IDs.
                    # Only an Exercise already present in this authorized
                    # Player's persisted program history is visible to clone.
                    if not ledger.has_exercise_in_program_history(exercise_id):
                        raise ProgramDraftValidationError.one(
                            "unknown_exercise",
                            "Exercise is not in the Exercise library.",
                            field="exercise_id",
                        )
                    if exercise_id not in copied_ids:
                        source = db.get_coach_exercise_for_template_copy(exercise_id)
                        if source is None or source[0] == str(coach_account_id):
                            if collection == "warmup_exercises" and source is None:
                                raise ProgramDraftValidationError.one(
                                    "unknown_exercise",
                                    "Warm-up exercise is not in the Exercise library.",
                                    field="exercise_id",
                                )
                            continue
                        _, definition = source
                        clone = db.create_coach_exercise(
                            coach_account_id,
                            CoachExerciseCreate(
                                name=definition["name"],
                                body_part=definition.get("body_part"),
                                equipment=definition.get("equipment"),
                                # A previous Coach's free-text note is private and
                                # has no review UI in this copy flow.
                                note=None,
                                video_url=definition.get("video_url"),
                            ),
                        )
                        copied_ids[exercise_id] = clone
                    clone = copied_ids.get(exercise_id)
                    if clone is None:
                        continue
                    movement["exercise_id"] = clone["id"]
            for movement in day.get("warmup_exercises", []) or []:
                exercise_id = movement.get("exercise_id")
                if not isinstance(exercise_id, str):
                    continue
                catalog_entry = db.get_exercise_library_entry(exercise_id)
                if catalog_entry is None:
                    catalog_entry = db.get_coach_exercise(
                        coach_account_id, exercise_id
                    )
                if catalog_entry is not None:
                    movement.update(
                        exercise_name=catalog_entry["name"],
                        equipment=catalog_entry.get("equipment"),
                        image_path=catalog_entry.get("image_path"),
                        gif_path=catalog_entry.get("gif_path"),
                    )


def save_program_as_template(
    db: Any,
    coach_account_id: str,
    assignment_id: str,
    *,
    source: str,
    name: str,
    description: str | None,
    notes: list[dict[str, Any]],
    source_revision: str | None,
) -> dict[str, Any] | None:
    """Copies a player's program into a new coach-owned template (ticket #307).

    The assignment gate runs before any ledger read. The stored source program is
    authoritative: only its allowlisted structure/prescriptions and the explicit
    reviewed note decisions reach the template, so no player id, name, history,
    provenance or assignment reference can ever be carried over. The copy is bound
    to the revision the coach reviewed, checked inside the same authorized ledger
    transaction, so a concurrent change is refused instead of copied. Returns
    ``None`` when the coach cannot read the assignment.
    """
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, _ = authorized
    with ledger:
        if source == SOURCE_PROGRAM_DRAFT:
            record = ledger.get_program_draft(assignment_id)
            if record is None:
                raise ProgramDraftNotFound("Program draft not found.")
            current_revision = str(record["updated_at"])
            source_program = record["draft"]
        else:
            program = ledger.get_active_program()
            if program is None:
                raise ActiveProgramNotFound("No active program to copy.")
            current_revision = _active_program_revision(program)
            source_program = active_program_as_draft(program)
        if not source_revision or source_revision != current_revision:
            raise ProgramSourceChanged(
                "The program changed since it was reviewed; reload and review again."
            )
        reviewed = _reviewed_template_program(
            source_program, template_name=name, notes=notes
        )
        with db.catalog_transaction(immediate=True):
            _copy_foreign_source_exercises(reviewed, db, coach_account_id, ledger)
            canonical = canonical_publishable_draft(reviewed, db, coach_account_id)
            return create_program_template(
                db,
                coach_account_id,
                name=name,
                description=description,
                program=canonical,
            )
