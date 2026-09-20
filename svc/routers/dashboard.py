"""Dashboard telemetry: volume attribution and progression history."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from service import dashboard as dashboard_service
from svc.dependencies import bind_request, get_current_trainee, get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/volume")
async def read_volume(
    trainee: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
    days: int = 7,
):
    def _run():
        bind_request(db, trainee)
        return dashboard_service.volume_attribution(db, trainee, days_lookback=max(1, min(days, 90)))

    return await asyncio.to_thread(_run)


@router.get("/exercises")
async def list_exercises(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    def _run():
        bind_request(db, trainee)
        return dashboard_service.logged_exercises(db, trainee)

    return await asyncio.to_thread(_run)


@router.get("/exercises/{exercise_id}/history")
async def read_exercise_history(
    exercise_id: str,
    trainee: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        bind_request(db, trainee)
        history = dashboard_service.exercise_history(db, trainee, exercise_id)
        return {
            "history": history,
            "caption": dashboard_service.latest_record_caption(history),
            "records": dashboard_service.exercise_records(db, trainee, exercise_id),
        }

    return await asyncio.to_thread(_run)


@router.get("/personal-records")
async def read_personal_records(
    trainee: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
    limit: int = 20,
):
    def _run():
        bind_request(db, trainee)
        return dashboard_service.recent_personal_records(db, trainee, limit=max(1, min(limit, 100)))

    return await asyncio.to_thread(_run)
