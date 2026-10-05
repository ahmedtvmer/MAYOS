"""Profile and coach-persona endpoints. Identity comes from the JWT, never the body."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status

from service import analytics, profile as profile_service
from service import weight_history as weight_history_service
from service.weight_history import WeightTrendQuery
from service.programs import player_controls_program
from service import schedule as schedule_service
from svc.dependencies import account_id_of, get_db, get_ledger, get_verified_player
from svc.llm import register_ai_analytics_background_tasks
from svc.schemas import (
    PersonaUpdate,
    ProfileUpdate,
    TrainingPauseCreateOut,
    TrainingPauseIn,
    TrainingPauseListOut,
    TrainingScheduleOut,
    TrainingScheduleSetOut,
    TrainingScheduleUpdateIn,
    WeightEntryIn,
    WeightEntryOut,
    WeightTrendOut,
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
    request: Request,
    background_tasks: BackgroundTasks,
    body: ProfileUpdate,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    register_ai_analytics_background_tasks(request, background_tasks)
    payload = {key: value for key, value in body.model_dump().items() if value is not None}
    if "target_weight_kg" in body.model_fields_set:
        payload["target_weight_kg"] = body.target_weight_kg
    result = await asyncio.to_thread(
        profile_service.update_profile,
        db,
        str(player),
        payload,
        account_id_of(player),
        ledger,
        client=analytics.client_context(request),
        background_tasks=background_tasks,
    )
    result["profile"] = {
        **(result.get("profile") or {}),
        "player_controls_program": await asyncio.to_thread(
            player_controls_program, db, ledger, account_id_of(player)
        ),
    }
    return result


@router.post("/weight", response_model=WeightEntryOut)
async def record_weight(
    body: WeightEntryIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Records today's weight and updates the latest Training profile value."""
    try:
        point = await asyncio.to_thread(
            profile_service.record_weight_entry,
            db,
            ledger,
            profile_service.WeightEntryCommand(
                ledger_id=str(player),
                player_account_id=account_id_of(player),
                weight_kg=body.weight_kg,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    return WeightEntryOut(entry_date=point.date.isoformat(), weight_kg=point.weight_kg)


@router.get("/weight/trend", response_model=WeightTrendOut)
async def read_weight_trend(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
    weeks: Annotated[int, Query(ge=1, le=52)] = 8,
):
    """Returns the recent dated weight series and the current target."""
    profile = await asyncio.to_thread(profile_service.get_profile, db, str(player), ledger)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile yet; complete onboarding.")
    trend = await asyncio.to_thread(
        weight_history_service.get_weight_trend,
        db,
        WeightTrendQuery(ledger_id=str(player), weeks=weeks),
        ledger,
    )
    return WeightTrendOut(
        points=[
            {"date": point.date.isoformat(), "weight_kg": point.weight_kg}
            for point in trend.points
        ],
        change_kg=trend.change_kg,
        target_weight_kg=profile.get("target_weight_kg"),
    )


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
    request: Request,
    body: TrainingScheduleUpdateIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Appends a new effective-dated schedule version; the program is never touched."""

    def _run():
        try:
            return schedule_service.set_schedule(
                db,
                str(player),
                body.model_dump(),
                ledger=ledger,
                player_account_id=account_id_of(player),
                client=analytics.client_context(request),
            )
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
    request: Request,
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
                client=analytics.client_context(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    return TrainingPauseCreateOut(**await asyncio.to_thread(_run))
