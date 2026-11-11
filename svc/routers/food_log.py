"""Authenticated Player-only Food library search and private Food log endpoints."""

import asyncio
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from service import analytics, food_log, meal_setup
from service.weight_history import player_local_date
from svc.dependencies import account_id_of, get_db, get_ledger, get_verified_player
from svc.schemas import CopyMealIn, FoodLogAmountIn, FoodLogEntryIn, PersonalFoodIn, QuickAddEntryIn, QuickAddIn
from svc.schemas import MealSetupIn

router = APIRouter(prefix="/nutrition", tags=["nutrition"])
Player = Annotated[Any, Depends(get_verified_player)]
Ledger = Annotated[Any, Depends(get_ledger)]
Store = Annotated[Any, Depends(get_db)]


def _http_error(error):
    status = 404 if isinstance(error, food_log.FoodLogNotFound) else (
        403 if isinstance(error, food_log.FoodLogReadOnly) else 400)
    return HTTPException(status_code=status, detail=str(error))


@router.get("/meal-setup")
async def read_meal_setup(player: Player, ledger: Ledger, db: Store):
    return await asyncio.to_thread(meal_setup.read, db, ledger)


@router.put("/meal-setup")
async def save_meal_setup(body: MealSetupIn, player: Player, ledger: Ledger, db: Store):
    try:
        return await asyncio.to_thread(meal_setup.save, db, ledger, body.model_dump())
    except ValueError as error:
        raise _http_error(error) from None


@router.get("/foods")
async def search_foods(player: Player, ledger: Ledger, db: Store,
                       q: str = Query(default="", max_length=200)):
    return {"foods": await asyncio.to_thread(food_log.search_foods, db, ledger, q)}


@router.post("/personal-foods", status_code=201)
async def create_personal_food(body: PersonalFoodIn, player: Player, ledger: Ledger):
    return await asyncio.to_thread(food_log.create_personal_food, ledger, body.model_dump())


def _capture_entry(request, player, entry):
    analytics.capture_for_request(request, analytics.AnalyticsEvent(
        account_id=account_id_of(player), event="food_logged",
        domain_key=f"{player}:food:{entry['id']}", role="player",
        properties={"food_kind": entry["kind"], "meal_label": entry["meal_label"]},
    ))


@router.get("/food-log/yesterday-meals")
async def read_yesterday_meals(player: Player, ledger: Ledger):
    today = player_local_date(ledger, str(player))
    return {"today": today.isoformat(),
            "meal_labels": await asyncio.to_thread(food_log.yesterday_meals, ledger, today)}


@router.post("/food-log/copy-meal", status_code=201)
async def copy_food_meal(request: Request, body: CopyMealIn, player: Player, ledger: Ledger):
    today = player_local_date(ledger, str(player))
    if body.entry_date != today:
        # The client chose this meal for a day that has since ended.
        raise HTTPException(status_code=409, detail="The day has changed. Check the meal and try again.")
    try:
        entries = await asyncio.to_thread(food_log.copy_meal, ledger, body.meal_label, today,
                                          food_log.local_time(ledger, str(player)))
    except ValueError as error:
        raise _http_error(error) from None
    for entry in entries:
        _capture_entry(request, player, entry)
    return {"entries": entries}


@router.post("/food-log/quick-add", status_code=201)
async def quick_add_food(request: Request, body: QuickAddEntryIn, player: Player, ledger: Ledger):
    today = player_local_date(ledger, str(player))
    try:
        entry = await asyncio.to_thread(food_log.add_quick_entry, ledger, body.model_dump(), today,
                                        food_log.local_time(ledger, str(player)))
    except ValueError as error:
        raise _http_error(error) from None
    _capture_entry(request, player, entry)
    return entry


@router.put("/food-log/quick-add/{entry_id}")
async def edit_quick_add(entry_id: str, body: QuickAddIn, player: Player, ledger: Ledger):
    today = player_local_date(ledger, str(player))
    try:
        return await asyncio.to_thread(food_log.edit_quick_entry, ledger, entry_id, body.model_dump(), today)
    except ValueError as error:
        raise _http_error(error) from None


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
    _capture_entry(request, player, entry)
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
