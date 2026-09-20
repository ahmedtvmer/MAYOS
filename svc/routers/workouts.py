"""Workout prescription, session commit, and ledger export."""

import asyncio
import io
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from service import sessions as sessions_service
from service import workouts as workouts_service
from svc.dependencies import bind_request, get_current_trainee, get_db
from svc.schemas import SessionCommitIn

router = APIRouter(prefix="/workouts", tags=["workouts"])

EXPORT_MEDIA_TYPES = {"csv": "text/csv", "json": "application/json"}


def _day_plan(db: Any, trainee: str, day_order: int) -> Any:
    program = db.get_active_program()
    if program is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active program.")
    for day in program.days:
        if day.day_order == day_order:
            return day
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No day with order {day_order}.")


@router.get("/prescription")
async def read_prescription(
    day_order: int,
    trainee: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        bind_request(db, trainee)
        return workouts_service.build_prescription(db, trainee, _day_plan(db, trainee, day_order))

    return await asyncio.to_thread(_run)


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def commit_session(
    body: SessionCommitIn,
    trainee: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        bind_request(db, trainee)
        day_plan = _day_plan(db, trainee, body.day_order)
        payload = []
        for item in body.sets:
            payload.append(
                {
                    "exercise": item.exercise,
                    "sets": [s.model_dump() for s in item.sets],
                    "previous_perf": db.get_last_performance(item.exercise.exercise_id),
                }
            )
        return workouts_service.commit_session(
            db, trainee, day_plan, body.readiness, body.session_notes, payload
        )

    return await asyncio.to_thread(_run)


async def _stream_session_log(trainee: str, db: Any, fmt: str) -> StreamingResponse:
    def _run():
        bind_request(db, trainee)
        return sessions_service.export_session_log(db, trainee, fmt)

    result = await asyncio.to_thread(_run)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No sessions logged yet.")
    filename, payload = result
    return StreamingResponse(
        io.BytesIO(payload),
        media_type=EXPORT_MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/sessions/export.csv")
async def export_sessions_csv(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    return await _stream_session_log(trainee, db, "csv")


@router.get("/sessions/export.json")
async def export_sessions_json(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    return await _stream_session_log(trainee, db, "json")
