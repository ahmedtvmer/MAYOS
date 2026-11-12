"""Player-only permanent Food swaps, guarded by the authored plan version."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from service import analytics, food_swaps
from svc.dependencies import account_id_of
from svc.food_swap_schemas import FoodSwapIn, FoodSwapTargetIn
from svc.routers.food_log import Ledger, Player, Store

router = APIRouter(prefix="/nutrition/meals", tags=["nutrition"])


def _http_error(error):
    return HTTPException(status_code=403 if isinstance(error, PermissionError) else 409, detail=str(error))


@router.get("/swap-candidates")
async def swap_candidates(player: Player, ledger: Ledger, db: Store,
                          target: Annotated[FoodSwapTargetIn, Depends()],
                          q: str = Query(default="", max_length=200)):
    try:
        return await asyncio.to_thread(food_swaps.candidates, db, ledger,
                                       food_swaps.SwapTarget(**target.model_dump()), q)
    except (PermissionError, ValueError) as error:
        raise _http_error(error) from None


@router.post("/swap", status_code=201)
async def swap_food(request: Request, body: FoodSwapIn, player: Player, ledger: Ledger):
    command = food_swaps.SwapCommand(
        food_swaps.SwapTarget(**body.model_dump(exclude={"food_id"})), body.food_id)
    try:
        saved = await asyncio.to_thread(food_swaps.make_swap, ledger, command)
    except (PermissionError, ValueError) as error:
        raise _http_error(error) from None
    analytics.capture_for_request(request, analytics.AnalyticsEvent(
        account_id=account_id_of(player), event="nutrition_food_swapped", role="player",
        domain_key=f"{player}:food-swap:{saved['plan_version_id']}", properties={},
    ))
    return saved
