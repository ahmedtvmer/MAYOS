"""Profile and coach-persona endpoints. Identity comes from the JWT, never the body."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from service import profile as profile_service
from service.programs import player_controls_program
from service import schedule as schedule_service
from svc.dependencies import account_id_of, get_db, get_ledger, get_verified_player
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
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    profile = await asyncio.to_thread(profile_service.get_profile, db, str(player), ledger)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile yet; complete onboarding.")
    return {
        **profile,
        "player_controls_program": await asyncio.to_thread(
            player_controls_program, db, ledger, account_id_of(player)
        ),
    }


@router.put("")
async def update_profile(
    body: ProfileUpdate,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    payload = {key: value for key, value in body.model_dump().items() if value is not None}
    result = await asyncio.to_thread(
        profile_service.update_profile,
        db, str(player), payload, account_id_of(player), ledger,
    )
    result["profile"] = {
        **(result.get("profile") or {}),
        "player_controls_program": await asyncio.to_thread(
            player_controls_program, db, ledger, account_id_of(player)
        ),
    }
    return result


@router.put("/persona")
async def update_persona(
    body: PersonaUpdate,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    return await asyncio.to_thread(
        profile_service.update_persona, db, str(player), body.coach_tone, body.custom_instructions, ledger
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def reset_profile(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    await asyncio.to_thread(profile_service.reset_profile, db, str(player), ledger)
    return None


@router.get("/schedule", response_model=TrainingScheduleOut)
async def read_schedule(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """The player's current expected schedule, all versions, and today's active pauses."""
    return TrainingScheduleOut(**await asyncio.to_thread(
        schedule_service.get_schedule, db, str(player), ledger
    ))


@router.put("/schedule", response_model=TrainingScheduleSetOut)
async def set_schedule(
    body: TrainingScheduleUpdateIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Appends a new effective-dated schedule version; the program is never touched."""

    def _run():
        try:
            return schedule_service.set_schedule(db, str(player), body.model_dump(), ledger=ledger)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    return TrainingScheduleSetOut(**await asyncio.to_thread(_run))


@router.get("/schedule/pauses", response_model=TrainingPauseListOut)
async def list_pauses(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """All pauses the player has scheduled, newest first."""
    return TrainingPauseListOut(pauses=await asyncio.to_thread(
        schedule_service.get_pauses, db, str(player), ledger
    ))


@router.post("/schedule/pauses", status_code=status.HTTP_201_CREATED, response_model=TrainingPauseCreateOut)
async def create_pause(
    body: TrainingPauseIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Stores a prospective pause (max 14 days, no reason) and best-effort notifies the coach."""

    def _run():
        try:
            return schedule_service.schedule_pause(
                db,
                str(player),
                body.model_dump(),
                account_id_of(player),
                ledger=ledger,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    return TrainingPauseCreateOut(**await asyncio.to_thread(_run))
