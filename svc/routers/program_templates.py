"""Coach-owned Program template library routes (ticket #305).

Every route requires the live coach capability. Reads and writes are scoped to
the owning coach in SQL, so an unknown template and another coach's template
both return the same generic 404 that reveals nothing.
"""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from service import program_templates as program_templates_service
from service import analytics
from service.coach_program_drafts import ProgramDraftValidationError
from service.messages import MessageMetadata
from svc.dependencies import VerifiedPlayer, get_current_coach, get_db
from svc.errors import message_http_exception
from svc.rate_limit import ASSIGNMENT_MUTATE_LIMIT, limiter
from svc.schemas import (
    ProgramTemplateAssignIn,
    ProgramTemplateAssignOut,
    ProgramTemplateDuplicateIn,
    ProgramTemplateIn,
    ProgramTemplateListOut,
    ProgramTemplateOut,
    ProgramTemplatePublishAllIn,
    ProgramTemplatePublishAllOut,
)

router = APIRouter(prefix="/coach/program-templates", tags=["coach"])


def _not_found() -> HTTPException:
    return message_http_exception(
        status.HTTP_404_NOT_FOUND,
        "Program template not found.",
        MessageMetadata("program.template_not_found.v1"),
    )


def _invalid(exc: ProgramDraftValidationError) -> HTTPException:
    return message_http_exception(
        status.HTTP_400_BAD_REQUEST,
        {"errors": exc.issues},
        MessageMetadata("program.template_invalid.v1"),
    )


def _run(action, *args, **kwargs):
    try:
        return action(*args, **kwargs)
    except program_templates_service.ProgramTemplateNotFound as exc:
        raise _not_found() from exc
    except ProgramDraftValidationError as exc:
        raise _invalid(exc) from exc


@router.get("", response_model=ProgramTemplateListOut)
async def list_program_templates(
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
    archived: bool = Query(default=False),
):
    templates = await asyncio.to_thread(
        _run,
        program_templates_service.list_program_templates,
        db,
        coach.account_id,
        archived=archived,
    )
    return {"templates": templates}


@router.post("", response_model=ProgramTemplateOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def create_program_template(
    request: Request,
    body: ProgramTemplateIn,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    created = await asyncio.to_thread(
        _run,
        program_templates_service.create_program_template,
        db,
        coach.account_id,
        name=body.name,
        description=body.description,
        program=body.program.model_dump(),
    )
    return created


@router.get("/{template_id}", response_model=ProgramTemplateOut)
async def read_program_template(
    template_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    return await asyncio.to_thread(
        _run,
        program_templates_service.read_program_template,
        db,
        coach.account_id,
        template_id,
    )


@router.put("/{template_id}", response_model=ProgramTemplateOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def update_program_template(
    request: Request,
    template_id: str,
    body: ProgramTemplateIn,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    return await asyncio.to_thread(
        _run,
        program_templates_service.update_program_template,
        db,
        coach.account_id,
        template_id,
        name=body.name,
        description=body.description,
        program=body.program.model_dump(),
    )


@router.post(
    "/{template_id}/duplicate",
    response_model=ProgramTemplateOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def duplicate_program_template(
    request: Request,
    template_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
    body: ProgramTemplateDuplicateIn | None = None,
):
    return await asyncio.to_thread(
        _run,
        program_templates_service.duplicate_program_template,
        db,
        coach.account_id,
        template_id,
        name=body.name if body is not None else None,
    )


@router.post("/{template_id}/archive", response_model=ProgramTemplateOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def archive_program_template(
    request: Request,
    template_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    return await asyncio.to_thread(
        _run,
        program_templates_service.set_program_template_archived,
        db,
        coach.account_id,
        template_id,
        archived=True,
    )


@router.post("/{template_id}/unarchive", response_model=ProgramTemplateOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def unarchive_program_template(
    request: Request,
    template_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    return await asyncio.to_thread(
        _run,
        program_templates_service.set_program_template_archived,
        db,
        coach.account_id,
        template_id,
        archived=False,
    )


@router.post("/{template_id}/assign", response_model=ProgramTemplateAssignOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def assign_program_template(
    request: Request,
    template_id: str,
    body: ProgramTemplateAssignIn,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Copies a template into each target assignment's Program draft (ticket #306).

    Template ownership decides the call first (uniform 404). Each assignment is
    then gated by ADR 025 and handled on its own, so a revoked, foreign, or
    non-owned assignment is rejected in its result without failing the rest.
    """
    results = await asyncio.to_thread(
        _run,
        program_templates_service.assign_program_template,
        db,
        coach.account_id,
        template_id,
        [target.model_dump() for target in body.targets],
    )
    return {"results": results}


@router.post("/{template_id}/publish-all", response_model=ProgramTemplatePublishAllOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def publish_all_program_template(
    request: Request,
    template_id: str,
    body: ProgramTemplatePublishAllIn,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Publishes each assignment's Program draft through the normal publish path.

    Each player's open program requests resolve by default. Each player reports
    its own success, validation errors, or rejection without failing the batch.
    """
    results = await asyncio.to_thread(
        _run,
        program_templates_service.publish_all_template_drafts,
        db,
        coach.account_id,
        template_id,
        body.assignment_ids,
        analytics.client_context(request),
    )
    return {"results": results}
