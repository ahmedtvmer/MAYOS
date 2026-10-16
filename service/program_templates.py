"""Coach-owned Program template library (ticket #305).

A template lives in the shared catalog, belongs to exactly one coach, and holds
no player data or Assignment reference. It stores the same normalized multiweek
Program shape as a Program draft, and every write is validated exactly as a
draft publication would be, so a template can only ever produce a publishable
program.
"""

from typing import Any

from database.registry.program_templates import ProgramTemplateCreate
from service.coach_program_drafts import validate_publishable_program

MAX_TEMPLATE_NAME_LENGTH = 120
_COPY_SUFFIX = " (copy)"


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
