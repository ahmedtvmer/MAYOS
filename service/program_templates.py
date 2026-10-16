"""Coach-owned Program template library (ticket #305).

A template lives in the shared catalog, belongs to exactly one coach, and holds
no player data or Assignment reference. It stores the same normalized multiweek
Program shape as a Program draft, and every write is validated exactly as a
draft publication would be, so a template can only ever produce a publishable
program.
"""

import copy
from typing import Any

from database.registry.program_templates import ProgramTemplateCreate
from service.assignments import (
    DENIED_ERROR,
    authorized_active_assignment,
    authorized_player_ledger,
)
from service.coach_program_drafts import (
    ProgramDraftNotFound,
    ProgramDraftSourceMismatch,
    ProgramDraftValidationError,
    draft_source_template_name,
    publish_program_draft,
    validate_publishable_program,
)
from service import program_requests as program_requests_service

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


class ProgramTemplateNotFound(Exception):
    """Raised when a template is unknown or owned by another coach."""


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
