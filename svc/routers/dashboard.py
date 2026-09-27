"""Dashboard telemetry: volume attribution and progression history."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from service import dashboard as dashboard_service
from svc.dependencies import get_db, get_ledger, get_verified_player

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/volume")
async def read_volume(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
    days: int = 7,
):
    return await asyncio.to_thread(
        dashboard_service.volume_attribution,
        db, str(player), max(1, min(days, 90)), ledger,
    )


@router.get("/exercises")
async def list_exercises(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    return await asyncio.to_thread(dashboard_service.logged_exercises, db, str(player), ledger)


@router.get("/exercises/{exercise_id}/history")
async def read_exercise_history(
    exercise_id: str,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        history = dashboard_service.exercise_history(db, str(player), exercise_id, ledger=ledger)
        return {
            "history": history,
            "caption": dashboard_service.latest_record_caption(history),
            "records": dashboard_service.exercise_records(db, str(player), exercise_id, ledger=ledger),
        }

    return await asyncio.to_thread(_run)


@router.get("/personal-records")
async def read_personal_records(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
    limit: int = 20,
):
    return await asyncio.to_thread(
        dashboard_service.recent_personal_records,
        db, str(player), max(1, min(limit, 100)), ledger,
    )
