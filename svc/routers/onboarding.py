"""Onboarding intake. Conversation state persists in the per-user ledger, keyed implicitly."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from langchain_core.messages import AIMessage, HumanMessage

from service import onboarding as onboarding_service
from svc.dependencies import bind_request, get_current_trainee, get_db
from svc.rate_limit import ONBOARDING_LIMIT, limiter
from svc.schemas import OnboardingStartOut, OnboardingStepIn, OnboardingStepOut

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


def _load_or_start(db: Any, trainee: str) -> dict[str, Any]:
    saved = db.load_onboarding_state()
    if saved is not None:
        return _deserialize(db, trainee, saved)
    return onboarding_service.start_onboarding(db, trainee)


@router.post("/start", response_model=OnboardingStartOut)
async def start_onboarding(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    """Starts intake, or resumes saved progress with the assistant prompts so far.

    A client that restarts mid-intake calls this again; it must not discard the
    saved state. Explicit reset stays on ``/onboarding/step`` with ``reset=true``.
    """

    def _run():
        bind_request(db, trainee)
        state = _load_or_start(db, trainee)
        db.save_onboarding_state(_serialize(state))
        return _public_view(state)

    return await asyncio.to_thread(_run)


@router.post("/step", response_model=OnboardingStepOut)
@limiter.limit(ONBOARDING_LIMIT)
async def answer_step(
    request: Request,
    body: OnboardingStepIn,
    trainee: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        bind_request(db, trainee)
        state = onboarding_service.start_onboarding(db, trainee) if body.reset else _load_or_start(db, trainee)
        seen = len(state.get("messages", []))
        if body.content:
            state = onboarding_service.answer_intake(db, trainee, state, body.content)
        db.save_onboarding_state(_serialize(state))
        return _public_view(state, only_new=state.get("messages", [])[seen:])

    return await asyncio.to_thread(_run)


@router.post("/complete")
async def complete_onboarding(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    def _run():
        bind_request(db, trainee)
        saved = db.load_onboarding_state()
        state = _deserialize(db, trainee, saved) if saved is not None else onboarding_service.start_onboarding(db, trainee)
        result = onboarding_service.complete_onboarding(db, trainee, state)
        db.clear_onboarding_state()
        program = result["program"]
        return {"program_name": program.program_name, "weekly_frequency": program.weekly_frequency}

    return await asyncio.to_thread(_run)
