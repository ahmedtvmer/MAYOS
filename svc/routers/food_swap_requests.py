"""Food swap requests share the Coach's Assignment request queue."""

import asyncio

from fastapi import APIRouter, HTTPException, Request

from database import food_swap_requests as queue
from service import analytics, food_swap_requests as requests
from svc.dependencies import account_id_of
from svc.food_swap_request_schemas import FoodSwapRequestIn, FoodSwapRequestApplyIn, FoodSwapRequestDeclineIn
from svc.routers.food_log import Player, Ledger, Store
from svc.routers.nutrition_drafts import Coach

router = APIRouter(tags=["nutrition"])


def _error(error):
    status = (404 if isinstance(error, requests.RequestNotFound) else
              409 if isinstance(error, requests.RequestConflict) else
              403 if isinstance(error, PermissionError) else 400)
    return HTTPException(status, str(error))


def _capture(request, account_id, record):
    created = record["status"] == "pending"
    analytics.capture_for_request(request, analytics.AnalyticsEvent(
        account_id=account_id,
        event="nutrition_food_swap_request_created" if created else "nutrition_food_swap_request_decided",
        role="player" if created else "coach",
        domain_key=f"food-swap-request:{record['request_id']}:{record['status']}",
        properties={"request_status": record["status"]},
    ))


@router.get("/nutrition/food-swap-requests")
async def list_requests(player: Player, db: Store):
    return {"requests": await asyncio.to_thread(queue.for_player, db, account_id_of(player))}


@router.post("/nutrition/food-swap-requests", status_code=201)
async def create_request(request: Request, body: FoodSwapRequestIn, player: Player, ledger: Ledger, db: Store):
    try:
        record, created = await asyncio.to_thread(requests.create, db, ledger, account_id_of(player), body.model_dump())
    except (ValueError, PermissionError) as error:
        raise _error(error) from None
    if created:
        _capture(request, account_id_of(player), record)
    return record


@router.post("/coach/assignments/{assignment_id}/food-swap-requests/{request_id}/apply")
async def apply_request(request: Request, assignment_id: str, request_id: str,
                        body: FoodSwapRequestApplyIn, coach: Coach, db: Store):
    command = requests.Decision(coach.account_id, assignment_id, request_id, body.model_dump(), "applied")
    return await _decide(request, db, command)


@router.post("/coach/assignments/{assignment_id}/food-swap-requests/{request_id}/decline")
async def decline_request(request: Request, assignment_id: str, request_id: str,
                          body: FoodSwapRequestDeclineIn, coach: Coach, db: Store):
    command = requests.Decision(coach.account_id, assignment_id, request_id, body.model_dump(), "declined")
    return await _decide(request, db, command)


async def _decide(request, db, command):
    try:
        record = await asyncio.to_thread(requests.decide, db, command)
    except (ValueError, PermissionError) as error:
        raise _error(error) from None
    _capture(request, command.coach_id, record)
    return record
