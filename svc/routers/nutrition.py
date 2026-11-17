"""Player Nutrition setup and read endpoints."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from service import analytics, nutrition as nutrition_service
from service import nutrition_alerts, meals
from service.weight_history import player_local_date
from svc.dependencies import account_id_of, get_db, get_ledger, get_verified_player
from svc.schemas import (
    NutritionActivityIn,
    NutritionAdherenceIn,
    NutritionGoalSaveIn,
    NutritionPaceIn,
    NutritionPaceProposalDecisionIn,
    NutritionSetupIn,
    LogPlannedMealIn,
)

router = APIRouter(prefix="/nutrition", tags=["nutrition"])
logger = logging.getLogger(__name__)


@router.get("/meals")
async def read_meals(request: Request,
                     player: Annotated[Any, Depends(get_verified_player)],
                     ledger: Annotated[Any, Depends(get_ledger)],
                     db: Annotated[Any, Depends(get_db)]):
    today, assignment, _language = _player_context(player, ledger, db, request)
    state = await asyncio.to_thread(meals.read, ledger, today)
    _apply_meal_permissions(state, ledger, assignment)
    return state


@router.post("/meals/enable")
async def enable_meals(request: Request,
                       player: Annotated[Any, Depends(get_verified_player)],
                       ledger: Annotated[Any, Depends(get_ledger)],
                       db: Annotated[Any, Depends(get_db)]):
    today, assignment, _language = _player_context(player, ledger, db, request)
    _require_player_authority(ledger, assignment)
    previous = ledger.get_active_nutrition_plan()
    try:
        state = await asyncio.to_thread(meals.enable, ledger, today)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    if previous is not None and previous["id"] != state["plan_version_id"]:
        analytics.capture_for_request(request, analytics.AnalyticsEvent(
            account_id=account_id_of(player), event="nutrition_meals_turned_on",
            domain_key=f"{player}:meals:{state['plan_version_id']}", role="player", properties={},
        ))
    _apply_meal_permissions(state, ledger, assignment)
    return state


@router.post("/meals/disable")
async def disable_meals(request: Request,
                        player: Annotated[Any, Depends(get_verified_player)],
                        ledger: Annotated[Any, Depends(get_ledger)],
                        db: Annotated[Any, Depends(get_db)]):
    today, assignment, _language = _player_context(player, ledger, db, request)
    _require_player_authority(ledger, assignment)
    previous = ledger.get_active_nutrition_plan()
    try:
        state = await asyncio.to_thread(meals.disable, ledger, today)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    version_id = state.get("plan_version_id")
    if previous is not None and version_id is not None and previous["id"] != version_id:
        analytics.capture_for_request(request, analytics.AnalyticsEvent(
            account_id=account_id_of(player), event="nutrition_meals_turned_off",
            domain_key=f"{player}:meals:{version_id}", role="player", properties={},
        ))
    _apply_meal_permissions(state, ledger, assignment)
    return state


def _apply_meal_permissions(state, ledger, assignment):
    state["can_enable"] = not _coach_holds_authority(ledger.get_active_nutrition_plan(), assignment)
    state["can_request_swap"] = not state["can_enable"] and state["status"] == "ready"


@router.post("/meals/log", status_code=201)
async def log_planned_meal(request: Request, body: LogPlannedMealIn,
                           player: Annotated[Any, Depends(get_verified_player)],
                           ledger: Annotated[Any, Depends(get_ledger)]):
    today = player_local_date(ledger, str(player))
    try:
        entries = await asyncio.to_thread(meals.log_meal, ledger, meals.LogMealCommand(
            body.slot, body.plan_version_id, body.entry_date, today))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    for entry in entries:
        analytics.capture_for_request(request, analytics.AnalyticsEvent(
            account_id=account_id_of(player), event="food_logged", role="player",
            domain_key=f"{player}:food:{entry['id']}",
            properties={"food_kind": entry["kind"], "meal_label": entry["meal_label"]},
        ))
    return {"entries": entries}


def _player_context(player: Any, ledger: Any, db: Any, request: Request | None = None):
    today = player_local_date(ledger, str(player))
    assignment = db.get_active_assignment_for_player(account_id_of(player))
    language = "ar" if request and request.headers.get("accept-language", "").lower().startswith("ar") else "en"
    return today, assignment, language


def _coach_holds_authority(active_plan: Any, assignment: dict[str, Any] | None) -> bool:
    return bool(
        active_plan is not None and assignment is not None
        and active_plan["author"] == "Coach"
        and active_plan["authority_assignment_id"] == assignment["assignment_id"]
    )


def _apply_authority_view(state: dict[str, Any], assignment: dict[str, Any] | None) -> None:
    coach_holds_authority = (
        assignment is not None
        and state.get("author") == "Coach"
        and state.get("authority_assignment_id") == assignment["assignment_id"]
    )
    state["authority"] = "coach" if coach_holds_authority else "player"
    state.pop("authority_assignment_id", None)


def _require_player_authority(ledger: Any, assignment: dict[str, Any] | None) -> None:
    if _coach_holds_authority(ledger.get_active_nutrition_plan(), assignment):
        raise HTTPException(
            status_code=403,
            detail="Your Coach controls Nutrition targets while the Assignment is active.",
        )


@router.post("/setup")
async def setup_nutrition(
    request: Request,
    body: NutritionSetupIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    today, assignment, language = _player_context(player, ledger, db, request)
    _require_player_authority(ledger, assignment)
    try:
        setup_state = await asyncio.to_thread(
            nutrition_service.setup, ledger,
            {**body.model_dump(), "screening": body.screening.model_dump(), "language": language},
            today,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if setup_state["state"] != "incomplete":
        analytics.capture_for_request(
            request,
            analytics.AnalyticsEvent(
                account_id=account_id_of(player), event="nutrition_setup_completed",
                domain_key=f"{player}:{setup_state.get('state')}:{setup_state.get('goal', 'blocked')}",
                role="player", properties={"blocked": setup_state["state"] in ("blocked", "under_18")},
            ),
        )
    state = await asyncio.to_thread(nutrition_service.read, ledger, language, today=today)
    state["today_water_glasses"] = ledger.get_water_glasses(today)
    state["coach_sees_adherence"] = assignment is not None
    _apply_authority_view(state, assignment)
    return state


@router.get("")
async def read_nutrition(
    request: Request,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    today, assignment, language = _player_context(player, ledger, db, request)
    state = await asyncio.to_thread(nutrition_service.read, ledger, language, today=today)
    state["today_water_glasses"] = ledger.get_water_glasses(today)
    state["coach_sees_adherence"] = assignment is not None
    _apply_authority_view(state, assignment)
    return state


@router.put("/adherence")
async def log_adherence(
    request: Request,
    body: NutritionAdherenceIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    today, assignment, _language = _player_context(player, ledger, db, request)
    try:
        state, updated_at = await asyncio.to_thread(
            nutrition_service.log_adherence, ledger, body.value, today, body.entry_date
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if assignment is not None:
        try:
            await asyncio.to_thread(
                nutrition_alerts.evaluate_assignment, db, assignment, datetime.now(UTC)
            )
        except Exception:
            logger.exception("Nutrition alert evaluation failed after adherence write")
    state["coach_sees_adherence"] = assignment is not None
    _apply_authority_view(state, assignment)
    analytics.capture_for_request(request, analytics.AnalyticsEvent(
        account_id=account_id_of(player), event="nutrition_adherence_logged",
        domain_key=f"{player}:{(body.entry_date or today).isoformat()}:{body.value}:{updated_at}", role="player",
        properties={"value": body.value},
    ))
    return state


@router.post("/water")
async def add_water_glass(
    request: Request,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    today, assignment, _language = _player_context(player, ledger, db)
    try:
        count, updated_at = await asyncio.to_thread(nutrition_service.change_water, ledger, today, 1)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    analytics.capture_for_request(request, analytics.AnalyticsEvent(
        account_id=account_id_of(player), event="water_log_changed",
        domain_key=f"{player}:{today.isoformat()}:{count}:{updated_at}", role="player",
        properties={"water_glasses": count},
    ))
    return {"today_water_glasses": count}


@router.delete("/water")
async def undo_water_glass(
    request: Request,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    today, _assignment, _language = _player_context(player, ledger, db)
    try:
        count, updated_at = await asyncio.to_thread(nutrition_service.change_water, ledger, today, -1)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    analytics.capture_for_request(request, analytics.AnalyticsEvent(
        account_id=account_id_of(player), event="water_log_changed",
        domain_key=f"{player}:{today.isoformat()}:{count}:{updated_at}", role="player",
        properties={"water_glasses": count},
    ))
    return {"today_water_glasses": count}


@router.put("/activity")
async def update_activity(
    body: NutritionActivityIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    today, assignment, _language = _player_context(player, ledger, db)
    _require_player_authority(ledger, assignment)
    state = await asyncio.to_thread(
        nutrition_service.update_activity, ledger, body.daily_activity, today
    )
    state["coach_sees_adherence"] = assignment is not None
    _apply_authority_view(state, assignment)
    return state


@router.post("/preview")
async def preview_nutrition(
    body: NutritionPaceIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    today, _assignment, _language = _player_context(player, ledger, db)
    return await asyncio.to_thread(nutrition_service.preview, ledger, body.goal, body.intensity, today)


@router.put("/goal")
async def save_nutrition_goal(
    request: Request,
    body: NutritionGoalSaveIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    today, assignment, _language = _player_context(player, ledger, db, request)
    _require_player_authority(ledger, assignment)
    previous_plan = await asyncio.to_thread(ledger.get_active_nutrition_plan)
    try:
        result = await asyncio.to_thread(
            nutrition_service.save_goal, ledger, body.goal, body.intensity, today,
            body.screening.model_dump() if body.screening else None,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    result["coach_sees_adherence"] = assignment is not None
    _apply_authority_view(result, assignment)
    if result.get("state") == "ready":
        active_plan = await asyncio.to_thread(ledger.get_active_nutrition_plan)
        if previous_plan is None or active_plan["id"] != previous_plan["id"]:
            analytics.capture_for_request(request, analytics.AnalyticsEvent(
                account_id=account_id_of(player), event="nutrition_goal_saved",
                domain_key=f"{player}:{active_plan['id']}", role="player",
                properties={"goal": result["goal"], "intensity": result.get("intensity") or "none",
                            "floor_applied": result["targets"]["floor_applied"]},
            ))
    return result


@router.post("/goal-offer/dismiss")
async def dismiss_goal_offer(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    today, assignment, _language = _player_context(player, ledger, db)
    _require_player_authority(ledger, assignment)
    result = await asyncio.to_thread(nutrition_service.dismiss_goal_offer, ledger, today)
    result["coach_sees_adherence"] = assignment is not None
    _apply_authority_view(result, assignment)
    return result


@router.post("/pace-proposals/{proposal_id}/decision")
async def decide_pace_proposal(
    request: Request,
    proposal_id: int,
    body: NutritionPaceProposalDecisionIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    today, assignment, _language = _player_context(player, ledger, db, request)
    _require_player_authority(ledger, assignment)
    try:
        result = await asyncio.to_thread(
            nutrition_service.decide_pace_proposal, ledger,
            nutrition_service.PaceProposalDecision(
                proposal_id, body.decision, "player", None, today),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    _apply_authority_view(result, assignment)
    analytics.capture_for_request(request, analytics.AnalyticsEvent(
        account_id=account_id_of(player), event="nutrition_pace_proposal_decided",
        domain_key=f"{player}:pace:{proposal_id}:{body.decision}:player", role="player",
        properties={"proposal_decision": body.decision, "decision_actor": "player"},
    ))
    return result
