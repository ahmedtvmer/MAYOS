"""Dashboard telemetry: volume attribution and progression history."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from service import dashboard as dashboard_service
from service import training_status as training_status_service
from svc.dependencies import (
    account_id_of,
    get_db,
    get_ledger,
    get_verified_player,
)
from svc.schemas import TrainingStatusOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/training-status", response_model=TrainingStatusOut)
async def read_training_status(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    account_id = account_id_of(player)
    imported_workouts = await asyncio.to_thread(
        training_status_service.imported_workout_count, db, account_id
    )
    result = await asyncio.to_thread(
        training_status_service.get_training_status,
        db,
        str(player),
        account_id=account_id,
        ledger=ledger,
        imported_workouts=imported_workouts,
    )
    return result.as_dict()


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
            "equipment": dashboard_service.exercise_equipment(db, exercise_id),
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
