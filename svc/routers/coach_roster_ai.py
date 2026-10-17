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
from svc.llm import InferenceTurnState
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


@dataclass(frozen=True)
class _AdmittedRosterTurn:
    endpoint: _RosterAssistantRequest
    account: dict[str, Any]
    account_id: str
    scope: InferenceScope
    turn: InferenceTurnState


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
    turn: InferenceTurnState,
) -> str:
    """Runs one admitted inference turn with the standard chat failure shape."""
    try:
        return await asyncio.to_thread(
            coach_roster_ai_service.answer_question,
            prepared.messages,
            scope,
            endpoint.background_tasks,
            turn,
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
    allowance: dict[str, Any] | None = None,
) -> CoachRosterAssistantOut:
    return CoachRosterAssistantOut(
        answer=answer,
        coverage_summary=coach_roster_ai_service.coverage_summary(
            display_language, prepared
        ),
        client_mapping=prepared.client_mapping,
        left_out_for_budget=prepared.left_out_for_budget,
        excluded_for_missing_disclosure=prepared.excluded_for_missing_disclosure,
        coach_ai_allowance=allowance,
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
    admitted = _admit_roster_turn(endpoint, account, account_id, client)
    return await _answer_reserved_roster_turn(admitted)


def _admit_roster_turn(
    endpoint: _RosterAssistantRequest,
    account: dict[str, Any],
    account_id: str,
    client: Any,
) -> _AdmittedRosterTurn:
    scope = coach_inference_scope(
        endpoint.db,
        account_id,
        client,
        purpose="coach_roster_assistant",
    )
    turn = InferenceTurnState(scope, defer_allowance_finalization=True)
    turn.background_tasks = endpoint.background_tasks
    admit_coach_turn(turn)
    return _AdmittedRosterTurn(endpoint, account, account_id, scope, turn)


async def _answer_reserved_roster_turn(
    admitted: _AdmittedRosterTurn,
) -> CoachRosterAssistantOut:
    try:
        return await _complete_roster_turn(admitted)
    except BaseException as exc:
        _mark_roster_turn_failure(admitted.turn, exc)
        raise
    finally:
        admitted.turn.finalize_allowance()


async def _complete_roster_turn(
    admitted: _AdmittedRosterTurn,
) -> CoachRosterAssistantOut:
    endpoint = admitted.endpoint
    prepared = await _prepare_snapshot_question(
        endpoint.db, admitted.account_id, endpoint.body
    )
    answer = await _run_admitted_turn(
        endpoint, prepared, admitted.scope, admitted.turn
    )
    _ensure_roster_answer_complete(admitted.turn)
    return _completed_roster_reply(admitted, answer, prepared)


def _ensure_roster_answer_complete(turn: InferenceTurnState) -> None:
    from service.ai_allowance import launch_allowances_enabled

    if turn.answer_outcome == "truncated" and launch_allowances_enabled():
        raise message_http_exception(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The answer was cut off before it finished. Please retry.",
            MessageMetadata("ai_allowance.answer_truncated.v1"),
        )


def _completed_roster_reply(
    admitted: _AdmittedRosterTurn,
    answer: str,
    prepared: coach_roster_ai_service.PreparedRosterQuestion,
) -> CoachRosterAssistantOut:
    return _roster_reply(
        answer,
        admitted.account.get("display_language", "en"),
        prepared,
        _completed_roster_allowance(admitted),
    )


def _completed_roster_allowance(
    admitted: _AdmittedRosterTurn,
) -> dict[str, Any] | None:
    from service.ai_allowance import launch_allowances_enabled, get_coach_allowance

    if not launch_allowances_enabled() or admitted.turn.answer_outcome != "completed":
        return None
    plan = plans_service.effective_coach_plan(
        admitted.endpoint.db, admitted.account
    )
    return get_coach_allowance(
        admitted.endpoint.db,
        admitted.account_id,
        str(plan or "free"),
        projected_completed_turn_id=admitted.turn.turn_id,
    )


def _mark_roster_turn_failure(
    turn: InferenceTurnState, error: BaseException
) -> None:
    if isinstance(error, (asyncio.CancelledError, GeneratorExit, InterruptedError)):
        turn.mark_interrupted()
    elif turn.answer_outcome == "pending":
        turn.mark_error()


@router.post(
    "/assistant/roster",
    response_model=CoachRosterAssistantOut,
)
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
