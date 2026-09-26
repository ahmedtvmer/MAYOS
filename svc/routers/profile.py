"""Profile and coach-persona endpoints. Identity comes from the JWT, never the body."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from service import profile as profile_service
from service import schedule as schedule_service
from svc.dependencies import account_id_of, bind_request, get_current_trainee, get_db
from svc.schemas import (
    PersonaUpdate,
    ProfileUpdate,
    TrainingPauseCreateOut,
    TrainingPauseIn,
    TrainingPauseListOut,
    TrainingScheduleOut,
    TrainingScheduleSetOut,
    TrainingScheduleUpdateIn,
)

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
async def read_profile(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    def _run():
        bind_request(db, trainee)
        profile = profile_service.get_profile(db, trainee)
        if profile is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile yet; complete onboarding.")
        return profile

    return await asyncio.to_thread(_run)


@router.put("")
async def update_profile(
    body: ProfileUpdate,
    trainee: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        bind_request(db, trainee)
        account_id = account_id_of(trainee)
        payload = {key: value for key, value in body.model_dump().items() if value is not None}
        return profile_service.update_profile(db, trainee, payload, player_account_id=account_id)

    return await asyncio.to_thread(_run)


@router.put("/persona")
async def update_persona(
    body: PersonaUpdate,
    trainee: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        bind_request(db, trainee)
        return profile_service.update_persona(db, trainee, body.coach_tone, body.custom_instructions)

    return await asyncio.to_thread(_run)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def reset_profile(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    def _run():
        bind_request(db, trainee)
        profile_service.reset_profile(db, trainee)

    await asyncio.to_thread(_run)
    return None


@router.get("/schedule", response_model=TrainingScheduleOut)
async def read_schedule(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    """The player's current expected schedule, all versions, and today's active pauses."""

    def _run():
        bind_request(db, trainee)
        return schedule_service.get_schedule(db, trainee)

    return TrainingScheduleOut(**await asyncio.to_thread(_run))


@router.put("/schedule", response_model=TrainingScheduleSetOut)
async def set_schedule(
    body: TrainingScheduleUpdateIn,
    trainee: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    """Appends a new effective-dated schedule version; the program is never touched."""

    def _run():
        bind_request(db, trainee)
        try:
            return schedule_service.set_schedule(db, trainee, body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    return TrainingScheduleSetOut(**await asyncio.to_thread(_run))


@router.get("/schedule/pauses", response_model=TrainingPauseListOut)
async def list_pauses(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    """All pauses the player has scheduled, newest first."""

    def _run():
        bind_request(db, trainee)
        return schedule_service.get_pauses(db, trainee)

    return TrainingPauseListOut(pauses=await asyncio.to_thread(_run))


@router.post("/schedule/pauses", status_code=status.HTTP_201_CREATED, response_model=TrainingPauseCreateOut)
async def create_pause(
    body: TrainingPauseIn,
    trainee: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    """Stores a prospective pause (max 14 days, no reason) and best-effort notifies the coach."""

    def _run():
        bind_request(db, trainee)
        try:
            return schedule_service.schedule_pause(
                db,
                trainee,
                body.model_dump(),
                account_id_of(trainee),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    return TrainingPauseCreateOut(**await asyncio.to_thread(_run))
