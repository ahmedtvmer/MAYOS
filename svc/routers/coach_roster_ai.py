"""Stateless, de-identified roster assistant route (issue #311)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status

from service import analytics
from service import coach_roster_ai as coach_roster_ai_service
from service import plans as plans_service
from service import roster_snapshot as roster_snapshot_service
from service.messages import MessageMetadata
from svc.dependencies import VerifiedPlayer, account_id_of, get_current_coach, get_db
from svc.errors import message_http_exception
from svc.llm import InferenceScope, register_ai_analytics_background_tasks
from svc.routers.coach_ai import admit_coach_turn, coach_inference_scope
from svc.rate_limit import COACH_ASSISTANT_LIMIT, limiter
from svc.schemas import (
    CoachAssistantIn,
    CoachRosterAssistantOut,
)
from utils.text_scrubber import PIPELINE_ERROR_RESPONSE

router = APIRouter(prefix="/coach", tags=["coach"])


@dataclass(frozen=True)
class _RosterAssistantRequest:
    request: Request
    background_tasks: BackgroundTasks
    body: CoachAssistantIn
    coach: VerifiedPlayer
    db: Any


async def _require_coach_pro(db: Any, account_id: str) -> dict[str, Any]:
    """Returns the live Coach account or raises the roster Pro refusal."""
    account = await asyncio.to_thread(db.get_account, account_id)
    if not plans_service.coach_roster_ai_available(
        plans_service.effective_coach_plan(db, account)
    ):
        raise message_http_exception(
            status.HTTP_403_FORBIDDEN,
            "Coach Pro is required for roster questions.",
            MessageMetadata("coach.roster_ai_pro_required.v1"),
        )
    return account


async def _prepare_snapshot_question(
    db: Any, account_id: str, body: CoachAssistantIn
) -> coach_roster_ai_service.PreparedRosterQuestion:
    """Builds this request's disclosed roster snapshot and bounded prompt."""
    snapshot = await asyncio.to_thread(
        roster_snapshot_service.roster_signal_snapshot, db, account_id
    )
    return coach_roster_ai_service.prepare_roster_question(
        snapshot,
        body.question,
        [turn.model_dump() for turn in body.history],
    )


async def _run_admitted_turn(
    endpoint: _RosterAssistantRequest,
    prepared: coach_roster_ai_service.PreparedRosterQuestion,
    scope: InferenceScope,
) -> str:
    """Runs one admitted inference turn with the standard chat failure shape."""
    try:
        return await asyncio.to_thread(
            coach_roster_ai_service.answer_question,
            prepared.messages,
            scope,
            endpoint.background_tasks,
        )
    except Exception:
        raise message_http_exception(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            PIPELINE_ERROR_RESPONSE,
            MessageMetadata("chat.failed.v1"),
        ) from None


def _roster_reply(
    answer: str,
    display_language: str,
    prepared: coach_roster_ai_service.PreparedRosterQuestion,
) -> CoachRosterAssistantOut:
    return CoachRosterAssistantOut(
        answer=answer,
        coverage_summary=coach_roster_ai_service.coverage_summary(
            display_language, prepared
        ),
        client_mapping=prepared.client_mapping,
        left_out_for_budget=prepared.left_out_for_budget,
        excluded_for_missing_disclosure=prepared.excluded_for_missing_disclosure,
    )


async def _answer_roster_request(
    endpoint: _RosterAssistantRequest,
) -> CoachRosterAssistantOut:
    """Handles feature and plan gates, then answers without retaining the turn."""
    register_ai_analytics_background_tasks(endpoint.request, endpoint.background_tasks)
    if not coach_roster_ai_service.coach_roster_ai_enabled():
        raise message_http_exception(
            status.HTTP_404_NOT_FOUND,
            "Coach roster assistant is not available.",
            MessageMetadata("coach.roster_ai_unavailable.v1"),
        )
    account_id = account_id_of(endpoint.coach)
    account = await _require_coach_pro(endpoint.db, account_id)
    client = analytics.client_context(endpoint.request)
    admit_coach_turn(
        account_id, client, endpoint.db, endpoint.background_tasks
    )
    scope = coach_inference_scope(
        endpoint.db,
        account_id,
        client,
        purpose="coach_roster_assistant",
    )
    prepared = await _prepare_snapshot_question(endpoint.db, account_id, endpoint.body)
    answer = await _run_admitted_turn(endpoint, prepared, scope)
    return _roster_reply(answer, account.get("display_language", "en"), prepared)


@router.post("/assistant/roster", response_model=CoachRosterAssistantOut)
@limiter.limit(COACH_ASSISTANT_LIMIT)
async def coach_roster_assistant(
    request: Request,
    background_tasks: BackgroundTasks,
    body: CoachAssistantIn,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Answers over the disclosed Roster snapshot; stores only model usage."""
    endpoint = _RosterAssistantRequest(
        request, background_tasks, body, coach, db
    )
    return await _answer_roster_request(endpoint)


__all__ = ["coach_roster_assistant", "router"]
