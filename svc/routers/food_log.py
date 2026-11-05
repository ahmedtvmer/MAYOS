"""Authenticated Player-only Food library search and private Food log endpoints."""

import asyncio
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from service import analytics, food_log
from service.weight_history import player_local_date
from svc.dependencies import account_id_of, get_db, get_ledger, get_verified_player
from svc.schemas import FoodLogAmountIn, FoodLogEntryIn

router = APIRouter(prefix="/nutrition", tags=["nutrition"])
Player = Annotated[Any, Depends(get_verified_player)]
Ledger = Annotated[Any, Depends(get_ledger)]
Store = Annotated[Any, Depends(get_db)]


def _http_error(error):
    status = 404 if isinstance(error, food_log.FoodLogNotFound) else (
        403 if isinstance(error, food_log.FoodLogReadOnly) else 400)
    return HTTPException(status_code=status, detail=str(error))


@router.get("/foods")
async def search_foods(player: Player, ledger: Ledger, db: Store,
                       q: str = Query(default="", max_length=200)):
    usage = await asyncio.to_thread(ledger.food_log_usage)
    return {"foods": await asyncio.to_thread(db.search_food_library, q, usage)}


@router.get("/food-log")
async def read_food_log(player: Player, ledger: Ledger, day: date | None = None):
    today = player_local_date(ledger, str(player))
    try:
        return await asyncio.to_thread(food_log.read_day, ledger, day or today, today)
    except ValueError as error:
        raise _http_error(error) from None


@router.post("/food-log", status_code=201)
async def add_food_log(request: Request, body: FoodLogEntryIn,
                       player: Player, ledger: Ledger, db: Store):
    today = player_local_date(ledger, str(player))
    try:
        entry = await asyncio.to_thread(food_log.add_entry, db, ledger, body.model_dump(), today,
                                        food_log.local_time(ledger, str(player)))
    except ValueError as error:
        raise _http_error(error) from None
    analytics.capture_for_request(request, analytics.AnalyticsEvent(
        account_id=account_id_of(player), event="food_logged",
        domain_key=f"{player}:food:{entry['id']}", role="player",
        properties={"food_kind": entry["kind"], "meal_label": entry["meal_label"]},
    ))
    return entry


@router.put("/food-log/{entry_id}")
async def edit_food_log(entry_id: str, body: FoodLogAmountIn, player: Player, ledger: Ledger):
    today = player_local_date(ledger, str(player))
    try:
        return await asyncio.to_thread(food_log.edit_entry, ledger, entry_id, body.model_dump(), today)
    except ValueError as error:
        raise _http_error(error) from None


@router.delete("/food-log/{entry_id}", status_code=204)
async def delete_food_log(entry_id: str, player: Player, ledger: Ledger):
    today = player_local_date(ledger, str(player))
    try:
        await asyncio.to_thread(food_log.delete_entry, ledger, entry_id, today)
    except ValueError as error:
        raise _http_error(error) from None
    return Response(status_code=204)
