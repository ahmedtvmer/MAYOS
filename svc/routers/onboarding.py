"""Onboarding intake.

Two contracts share this router: the legacy three-step chat state (``/start``,
``/step``, ``/complete``) kept for backward compatibility, and the structured,
resumable named-answer intake (``/intake``, ADR 021) that the visual flow uses.

Every route reaches the ledger only through an explicit handle: the structured
intake routes take ``get_ledger``, and the legacy routes open one for the
request around the onboarding graph (ADR 041).
"""

import asyncio
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage, HumanMessage

from service import analytics as analytics_service
from service import intake as intake_service
from service import onboarding as onboarding_service
from service.messages import MessageMetadata, http_error_message
from service.program_analytics import ProgramAnalyticsActor
from svc.dependencies import account_id_of, get_current_player, get_db, get_ledger, get_verified_player
from svc.llm import InferenceScope, inference_turn, register_ai_analytics_background_tasks
from svc.rate_limit import ONBOARDING_LIMIT, limiter
from svc.schemas import (
    IntakeAnswerIn,
    IntakeConfirmOut,
    IntakeOut,
    OnboardingStartOut,
    OnboardingStepIn,
    OnboardingStepOut,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])
ONBOARDING_CONFLICT_FALLBACK = "The service rejected this request."


def _onboarding_conflict(error_code: str, message_code: str) -> JSONResponse:
    """Keeps onboarding's existing error body while tagging its source outcome."""
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": error_code,
            **http_error_message(
                status.HTTP_409_CONFLICT,
                ONBOARDING_CONFLICT_FALLBACK,
                message_metadata=MessageMetadata(message_code),
            ),
        },
    )


@dataclass(frozen=True)
class _OnboardingRouteOutcome:
    response_body: dict[str, Any]
    completion: onboarding_service.OnboardingCompletionAnalytics | None = None


def _record_onboarding_started(request: Request, account_id: str | None, ledger: Any) -> None:
    marker = onboarding_service.mark_onboarding_started(ledger)
    if account_id and marker and marker.first_write:
        analytics_service.capture_for_request(
            request,
            analytics_service.AnalyticsEvent(
                account_id=account_id,
                event="onboarding_started",
                domain_key=account_id,
                role="player",
            ),
        )


def _capture_onboarding_completed(
    request: Request,
    account_id: str | None,
    completion: onboarding_service.OnboardingCompletionAnalytics | None,
) -> None:
    if not account_id or completion is None or not completion.first_completion:
        return
    analytics_service.capture_for_request(
        request,
        analytics_service.AnalyticsEvent(
            account_id=account_id,
            event="onboarding_completed",
            domain_key=account_id,
            role="player",
            properties={
                "duration_seconds": completion.duration_seconds,
                "prefilled_fields_count": completion.prefilled_fields_count,
            },
        ),
    )


def _serialize(state: dict[str, Any]) -> dict[str, Any]:
    messages = []
    for message in state.get("messages", []):
        role = "assistant" if isinstance(message, AIMessage) else "user"
        messages.append({"role": role, "content": message.content})
    return {
        "intake_step": state.get("intake_step", 1),
        "is_complete": state.get("is_complete", False),
        "profile_data": state.get("profile_data"),
        "messages": messages,
    }


def _deserialize(db: Any, player: str, data: dict[str, Any]) -> dict[str, Any]:
    messages = [
        AIMessage(content=item["content"]) if item["role"] == "assistant" else HumanMessage(content=item["content"])
        for item in data.get("messages", [])
    ]
    return {
        "messages": messages,
        "trainee_id": player,
        "intake_step": data.get("intake_step", 1),
        "is_complete": data.get("is_complete", False),
        "profile_data": data.get("profile_data"),
    }


def _public_view(state: dict[str, Any], only_new: list | None = None) -> dict[str, Any]:
    messages = only_new if only_new is not None else state.get("messages", [])
    texts = [m.content for m in messages if isinstance(m, AIMessage)]
    return {"intake_step": state.get("intake_step", 1), "is_complete": state.get("is_complete", False), "messages": texts}


def _load_or_start(
    db: Any,
    ledger: Any,
    player: str,
    account_id: str | None,
    scope: InferenceScope | None = None,
) -> dict[str, Any]:
    saved = ledger.load_onboarding_state()
    if saved is not None:
        return _deserialize(db, player, saved)
    return onboarding_service.start_onboarding(
        db, player, player_account_id=account_id, ledger=ledger, scope=scope
    )


@router.post("/start", response_model=OnboardingStartOut)
async def start_onboarding(
    request: Request,
    background_tasks: BackgroundTasks,
    player: Annotated[str, Depends(get_current_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """Starts intake, or resumes saved progress with the assistant prompts so far.

    A client that restarts mid-intake calls this again; it must not discard the
    saved state. Explicit reset stays on ``/onboarding/step`` with ``reset=true``.
    """

    register_ai_analytics_background_tasks(request, background_tasks)
    account_id = account_id_of(player)
    scope = InferenceScope(
        account_id=account_id,
        role="player",
        purpose="onboarding",
        store=db,
        client=analytics_service.client_context(request),
    )

    def _run():
        with inference_turn(scope, background_tasks=background_tasks):
            with db.open_ledger(str(player)) as ledger:
                if intake_service.structured_intake_active(db, player, ledger=ledger):
                    raise intake_service.StructuredIntakeActive()
                state = _load_or_start(db, ledger, player, account_id, scope)
                ledger.save_onboarding_state(_serialize(state))
                if not state.get("is_complete"):
                    _record_onboarding_started(request, account_id, ledger)
                return _public_view(state)

    try:
        return await asyncio.to_thread(_run)
    except intake_service.StructuredIntakeActive:
        return _onboarding_conflict(
            "structured_intake_active", "intake.structured_active.v1"
        )


@router.post("/step", response_model=OnboardingStepOut)
@limiter.limit(ONBOARDING_LIMIT)
async def answer_step(
    request: Request,
    background_tasks: BackgroundTasks,
    body: OnboardingStepIn,
    player: Annotated[str, Depends(get_current_player)],
    db: Annotated[Any, Depends(get_db)],
):
    register_ai_analytics_background_tasks(request, background_tasks)
    account_id = account_id_of(player)
    scope = InferenceScope(
        account_id=account_id,
        role="player",
        purpose="onboarding",
        store=db,
        client=analytics_service.client_context(request),
    )

    def _run():
        with inference_turn(scope, background_tasks=background_tasks):
            with db.open_ledger(str(player)) as ledger:
                if intake_service.structured_intake_active(db, player, ledger=ledger):
                    raise intake_service.StructuredIntakeActive()
                account_id = account_id_of(player)
                state = (
                    onboarding_service.start_onboarding(
                        db, player, player_account_id=account_id, ledger=ledger, scope=scope
                    )
                    if body.reset
                    else _load_or_start(db, ledger, player, account_id, scope)
                )
                seen = len(state.get("messages", []))
                if body.content:
                    state = onboarding_service.answer_intake(
                        db,
                        player,
                        state,
                        body.content,
                        player_account_id=account_id,
                        ledger=ledger,
                        scope=scope,
                    )
                ledger.save_onboarding_state(_serialize(state))
                if not state.get("is_complete"):
                    _record_onboarding_started(request, account_id, ledger)
                return _public_view(state, only_new=state.get("messages", [])[seen:])

    try:
        return await asyncio.to_thread(_run)
    except intake_service.StructuredIntakeActive:
        return _onboarding_conflict(
            "structured_intake_active", "intake.structured_active.v1"
        )


@router.get("/intake", response_model=IntakeOut)
async def read_intake(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """The named intake contract, saved answers, legacy prefill markers, and progress."""
    return await asyncio.to_thread(intake_service.build_view, db, str(player), ledger)


@router.post("/intake/disclosure", response_model=IntakeOut)
async def acknowledge_intake_disclosure(
    request: Request,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Records the hosted-processing disclosure before any answer is accepted (ADR 016/036)."""
    result = await asyncio.to_thread(intake_service.acknowledge_disclosure, db, str(player), ledger)
    if result["status"] == intake_service.STATUS_IN_PROGRESS:
        _record_onboarding_started(request, account_id_of(player), ledger)
    return result


@router.put("/intake/answers/{field}", response_model=IntakeOut)
@limiter.limit(ONBOARDING_LIMIT)
async def save_intake_answer(
    request: Request,
    field: str,
    body: IntakeAnswerIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Validates and saves one named answer; idempotent until confirmed (ADR 021)."""

    def _run():
        try:
            return intake_service.save_answer(db, str(player), field, body.value, ledger=ledger)
        except intake_service.IntakeDisclosureRequired as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from None
        except intake_service.IntakeAlreadyConfirmed as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
        except intake_service.IntakeValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    result = await asyncio.to_thread(_run)
    if result["status"] == intake_service.STATUS_IN_PROGRESS:
        _record_onboarding_started(request, account_id_of(player), ledger)
    return result


@router.post("/intake/confirm", response_model=IntakeConfirmOut)
@limiter.limit(ONBOARDING_LIMIT)
async def confirm_intake(
    request: Request,
    background_tasks: BackgroundTasks,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Writes the confirmed profile and creates the first program exactly once (ADR 021)."""

    register_ai_analytics_background_tasks(request, background_tasks)
    account_id = account_id_of(player)
    scope = InferenceScope(
        account_id=account_id,
        role="player",
        purpose="onboarding_complete",
        store=db,
        client=analytics_service.client_context(request),
    )

    def _run():
        with inference_turn(scope, background_tasks=background_tasks):
            answers = ledger.load_intake_answers()
            try:
                result = intake_service.confirm_intake(
                    db,
                    str(player),
                    player_account_id=account_id_of(player),
                    ledger=ledger,
                    client=analytics_service.client_context(request),
                    scope=scope,
                )
            except intake_service.IntakeDisclosureRequired as exc:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from None
            except intake_service.IntakeValidationError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
            if result.get("status") != intake_service.STATUS_CONFIRMED:
                return _OnboardingRouteOutcome(result)
            _record_onboarding_started(request, account_id_of(player), ledger)
            completion = onboarding_service.record_onboarding_completion(ledger, answers)
            return _OnboardingRouteOutcome(result, completion)

    try:
        outcome = await asyncio.to_thread(_run)
        _capture_onboarding_completed(request, account_id_of(player), outcome.completion)
        return outcome.response_body
    except intake_service.IntakeConfirmInProgress:
        response = _onboarding_conflict(
            "confirm_in_progress", "intake.in_progress.v1"
        )
        response.background = background_tasks
        return response


@router.post("/complete")
async def complete_onboarding(
    request: Request,
    background_tasks: BackgroundTasks,
    player: Annotated[str, Depends(get_current_player)],
    db: Annotated[Any, Depends(get_db)],
):
    register_ai_analytics_background_tasks(request, background_tasks)
    account_id = account_id_of(player)
    scope = InferenceScope(
        account_id=account_id,
        role="player",
        purpose="onboarding_complete",
        store=db,
        client=analytics_service.client_context(request),
    )

    def _run():
        with inference_turn(scope, background_tasks=background_tasks):
            with db.open_ledger(str(player)) as ledger:
                account_id = account_id_of(player)
                saved = ledger.load_onboarding_state()
                state = (
                    _deserialize(db, player, saved)
                    if saved is not None
                    else onboarding_service.start_onboarding(
                        db, player, player_account_id=account_id, ledger=ledger, scope=scope
                    )
                )
                result = onboarding_service.complete_onboarding(
                    db,
                    player,
                    state,
                    player_account_id=account_id,
                    ledger=ledger,
                    emit_program_analytics=False,
                    client=scope.client,
                    scope=scope,
                )
                answers = ledger.load_intake_answers()
                ledger.clear_onboarding_state()
                program = result["program"]
                intake_service.record_legacy_completion(
                    db,
                    player,
                    program,
                    result.get("program_message"),
                    ledger=ledger,
                    actor=ProgramAnalyticsActor(account_id, "player"),
                    program_generated=result.get("program_generated", False),
                    client=analytics_service.client_context(request),
                )
                completed = (
                    {"program_name": None, "weekly_frequency": None, "program_message": result["program_message"]}
                    if program is None
                    else {"program_name": program.program_name, "weekly_frequency": program.weekly_frequency}
                )
                _record_onboarding_started(request, account_id, ledger)
                completion = onboarding_service.record_onboarding_completion(ledger, answers, saved or state)
            return _OnboardingRouteOutcome(completed, completion)

    outcome = await asyncio.to_thread(_run)
    _capture_onboarding_completed(request, account_id_of(player), outcome.completion)
    return outcome.response_body
