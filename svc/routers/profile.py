"""Profile and coach-persona endpoints. Identity comes from the JWT, never the body."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from service import profile as profile_service
from svc.dependencies import bind_request, get_current_trainee, get_db
from svc.schemas import PersonaUpdate, ProfileUpdate

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
        payload = {key: value for key, value in body.model_dump().items() if value is not None}
        return profile_service.update_profile(db, trainee, payload)

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
