"""Onboarding intake.

Two contracts share this router: the legacy three-step chat state (``/start``,
``/step``, ``/complete``) kept for backward compatibility, and the structured,
resumable named-answer intake (``/intake``, ADR 021) that the visual flow uses.

The legacy three-step contract runs the onboarding graph, which still resolves
its ledger through the compatibility mount; those routes therefore keep the
verified-player thread-local path (``bind_request``) until Phase B2. The
structured intake routes use the explicit ledger handle.
"""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage, HumanMessage

from service import intake as intake_service
from service import onboarding as onboarding_service
from svc.dependencies import account_id_of, bind_request, get_current_trainee, get_db, get_ledger, get_verified_player
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


def _deserialize(db: Any, trainee: str, data: dict[str, Any]) -> dict[str, Any]:
    messages = [
        AIMessage(content=item["content"]) if item["role"] == "assistant" else HumanMessage(content=item["content"])
        for item in data.get("messages", [])
    ]
    return {
        "messages": messages,
        "trainee_id": trainee,
        "intake_step": data.get("intake_step", 1),
        "is_complete": data.get("is_complete", False),
        "profile_data": data.get("profile_data"),
    }


def _public_view(state: dict[str, Any], only_new: list | None = None) -> dict[str, Any]:
    messages = only_new if only_new is not None else state.get("messages", [])
    texts = [m.content for m in messages if isinstance(m, AIMessage)]
    return {"intake_step": state.get("intake_step", 1), "is_complete": state.get("is_complete", False), "messages": texts}


def _load_or_start(db: Any, trainee: str, account_id: str | None) -> dict[str, Any]:
    saved = db.load_onboarding_state()
    if saved is not None:
        return _deserialize(db, trainee, saved)
    return onboarding_service.start_onboarding(db, trainee, player_account_id=account_id)


@router.post("/start", response_model=OnboardingStartOut)
async def start_onboarding(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    """Starts intake, or resumes saved progress with the assistant prompts so far.

    A client that restarts mid-intake calls this again; it must not discard the
    saved state. Explicit reset stays on ``/onboarding/step`` with ``reset=true``.
    """

    def _run():
        bind_request(db, trainee)  # Phase B2: legacy graph reads the thread-local ledger
        if intake_service.structured_intake_active(db, trainee):
            raise intake_service.StructuredIntakeActive()
        state = _load_or_start(db, trainee, account_id_of(trainee))
        db.save_onboarding_state(_serialize(state))
        return _public_view(state)

    try:
        return await asyncio.to_thread(_run)
    except intake_service.StructuredIntakeActive:
        return JSONResponse(status_code=409, content={"error": "structured_intake_active"})


@router.post("/step", response_model=OnboardingStepOut)
@limiter.limit(ONBOARDING_LIMIT)
async def answer_step(
    request: Request,
    body: OnboardingStepIn,
    trainee: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        bind_request(db, trainee)  # Phase B2: legacy graph reads the thread-local ledger
        if intake_service.structured_intake_active(db, trainee):
            raise intake_service.StructuredIntakeActive()
        account_id = account_id_of(trainee)
        state = (
            onboarding_service.start_onboarding(db, trainee, player_account_id=account_id)
            if body.reset
            else _load_or_start(db, trainee, account_id)
        )
        seen = len(state.get("messages", []))
        if body.content:
            state = onboarding_service.answer_intake(db, trainee, state, body.content, player_account_id=account_id)
        db.save_onboarding_state(_serialize(state))
        return _public_view(state, only_new=state.get("messages", [])[seen:])

    try:
        return await asyncio.to_thread(_run)
    except intake_service.StructuredIntakeActive:
        return JSONResponse(status_code=409, content={"error": "structured_intake_active"})


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
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Records the hosted-processing disclosure before any answer is accepted (ADR 016/036)."""
    return await asyncio.to_thread(intake_service.acknowledge_disclosure, db, str(player), ledger)


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

    return await asyncio.to_thread(_run)


@router.post("/intake/confirm", response_model=IntakeConfirmOut)
@limiter.limit(ONBOARDING_LIMIT)
async def confirm_intake(
    request: Request,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Writes the confirmed profile and creates the first program exactly once (ADR 021)."""

    def _run():
        try:
            return intake_service.confirm_intake(
                db, str(player), player_account_id=account_id_of(player), ledger=ledger
            )
        except intake_service.IntakeDisclosureRequired as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from None
        except intake_service.IntakeValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    try:
        return await asyncio.to_thread(_run)
    except intake_service.IntakeConfirmInProgress:
        return JSONResponse(status_code=409, content={"error": "confirm_in_progress"})


@router.post("/complete")
async def complete_onboarding(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    def _run():
        bind_request(db, trainee)  # Phase B2: onboarding graph reads the thread-local ledger
        account_id = account_id_of(trainee)
        saved = db.load_onboarding_state()
        state = (
            _deserialize(db, trainee, saved)
            if saved is not None
            else onboarding_service.start_onboarding(db, trainee, player_account_id=account_id)
        )
        result = onboarding_service.complete_onboarding(db, trainee, state, player_account_id=account_id)
        db.clear_onboarding_state()
        program = result["program"]
        intake_service.record_legacy_completion(db, trainee, program, result.get("program_message"))
        if program is None:
            return {"program_name": None, "weekly_frequency": None, "program_message": result["program_message"]}
        return {"program_name": program.program_name, "weekly_frequency": program.weekly_frequency}

    return await asyncio.to_thread(_run)
