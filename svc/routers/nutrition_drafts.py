"""Active-assignment Coach Nutrition draft endpoints."""

import asyncio
from functools import partial
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from database.ledger.nutrition_drafts import discard_draft
from service import analytics, coach_nutrition_drafts as drafts
from svc.dependencies import VerifiedPlayer, get_current_coach, get_db
from svc.nutrition_draft_schemas import (
    NutritionDraftPublishIn, NutritionDraftSaveIn, NutritionDraftStartIn,
)

router = APIRouter(prefix="/coach/assignments/{assignment_id}/nutrition", tags=["coach"])
Coach = Annotated[VerifiedPlayer, Depends(get_current_coach)]
Store = Annotated[Any, Depends(get_db)]


async def _run(db, coach, assignment_id, operation):
    try:
        return await asyncio.to_thread(drafts.run, db, coach.account_id, assignment_id, operation)
    except drafts.DraftNotFound as error:
        raise HTTPException(404, str(error)) from None
    except drafts.DraftConflict as error:
        raise HTTPException(409, str(error)) from None
    except drafts.DraftInvalid as error:
        raise HTTPException(400, {"message": str(error), "evaluation": error.evaluation}) from None
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


@router.get("/draft")
async def read_draft(assignment_id: str, coach: Coach, db: Store):
    return await _run(db, coach, assignment_id, partial(drafts.read, assignment_id=assignment_id))


@router.post("/draft", status_code=201)
async def start_draft(assignment_id: str, body: NutritionDraftStartIn, coach: Coach, db: Store):
    return await _run(db, coach, assignment_id,
                      partial(drafts.start, assignment_id=assignment_id, source=body.source))


@router.put("/draft")
async def save_draft(assignment_id: str, body: NutritionDraftSaveIn, coach: Coach, db: Store):
    return await _run(db, coach, assignment_id,
                      partial(drafts.save, assignment_id=assignment_id, body=body.model_dump()))


@router.delete("/draft", status_code=204)
async def delete_draft(assignment_id: str, coach: Coach, db: Store):
    await _run(db, coach, assignment_id, partial(discard_draft, assignment_id=assignment_id))
    return Response(status_code=204)


@router.get("/draft/foods")
async def search_foods(assignment_id: str, coach: Coach, db: Store,
                       q: str = Query(default="", max_length=200)):
    return await _run(db, coach, assignment_id, partial(drafts.search, query=q))


@router.post("/draft/publish")
async def publish_draft(request: Request, assignment_id: str, body: NutritionDraftPublishIn,
                        coach: Coach, db: Store):
    published = await _run(db, coach, assignment_id,
                           partial(drafts.publish, assignment_id=assignment_id, body=body.model_dump()))
    analytics.capture_for_request(request, analytics.AnalyticsEvent(
        account_id=coach.account_id, event="coach_nutrition_plan_published", role="coach",
        domain_key=f"{assignment_id}:nutrition:{published['plan_version_id']}",
        properties={"with_meals": published["with_meals"]},
    ))
    return published
