"""Catalog library and assignment-gated snapshot/apply endpoints."""

import asyncio
from functools import partial

from fastapi import APIRouter, HTTPException, Query, Request, Response

from database.registry import nutrition_templates as storage
from service import analytics, nutrition_templates as templates
from svc.nutrition_template_schemas import (
    NutritionTemplateApplyIn, NutritionTemplateIn, NutritionTemplateSaveFromIn,
)
from svc.routers.nutrition_drafts import Coach, Store
from service import coach_nutrition_drafts as drafts

router = APIRouter(tags=["coach"])
LIBRARY = "/coach/nutrition-templates"


async def _run(operation):
    try:
        return await asyncio.to_thread(operation)
    except drafts.DraftNotFound as error:
        raise HTTPException(404, str(error)) from None
    except drafts.DraftConflict as error:
        raise HTTPException(409, str(error)) from None
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


def _capture(request, coach, event, domain_key):
    analytics.capture_for_request(request, analytics.AnalyticsEvent(
        account_id=coach.account_id, event=event, role="coach", domain_key=domain_key,
    ))


@router.get(LIBRARY)
async def list_templates(coach: Coach, db: Store):
    return {"templates": await _run(partial(storage.list_templates, db, coach.account_id))}


@router.get(f"{LIBRARY}/foods")
async def search_foods(coach: Coach, db: Store, q: str = Query(default="", max_length=200)):
    return await _run(partial(templates.food_options, db, q))


@router.post(LIBRARY, status_code=201)
async def create_template(request: Request, body: NutritionTemplateIn, coach: Coach, db: Store):
    created = await _run(partial(templates.create, db, coach.account_id, body.model_dump()))
    _capture(request, coach, "nutrition_template_saved", created["template_id"])
    return created


@router.get(f"{LIBRARY}/{{template_id}}")
async def read_template(template_id: str, coach: Coach, db: Store):
    return await _run(partial(templates.editor_template, db, coach.account_id, template_id))


@router.put(f"{LIBRARY}/{{template_id}}")
async def update_template(template_id: str, body: NutritionTemplateIn, coach: Coach, db: Store):
    return await _run(partial(templates.update, db, coach.account_id, template_id, body.model_dump()))


@router.delete(f"{LIBRARY}/{{template_id}}", status_code=204)
async def delete_template(template_id: str, coach: Coach, db: Store):
    await _run(partial(templates.delete, db, coach.account_id, template_id))
    return Response(status_code=204)


@router.post("/coach/assignments/{assignment_id}/nutrition/save-template", status_code=201)
async def save_template(request: Request, assignment_id: str, body: NutritionTemplateSaveFromIn,
                        coach: Coach, db: Store):
    created = await _run(partial(templates.save_from_assignment, db, coach.account_id,
                               assignment_id, body.model_dump()))
    _capture(request, coach, "nutrition_template_saved", created["template_id"])
    return created


@router.get("/coach/assignments/{assignment_id}/nutrition/template-source")
async def current_source(assignment_id: str, coach: Coach, db: Store):
    return await _run(partial(drafts.run, db, coach.account_id, assignment_id, templates.current_source))


@router.post(f"{LIBRARY}/{{template_id}}/apply")
async def apply_template(request: Request, template_id: str, body: NutritionTemplateApplyIn,
                         coach: Coach, db: Store):
    applied = await _run(partial(templates.apply, db, coach.account_id, template_id, body.model_dump()))
    _capture(request, coach, "nutrition_template_applied",
             f"{template_id}:{body.assignment_id}:{applied['updated_at']}")
    return applied
