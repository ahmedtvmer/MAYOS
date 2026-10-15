"""Structured, resumable onboarding intake (ADR 021)."""

import asyncio
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from service import analytics as analytics_service
from service import intake as intake_service
from service import onboarding as onboarding_service
from service.messages import MessageMetadata, http_error_message
from svc.dependencies import account_id_of, get_db, get_ledger, get_verified_player
from svc.rate_limit import ONBOARDING_LIMIT, limiter
from svc.schemas import (
    IntakeAnswerIn,
    IntakeConfirmOut,
    IntakeOut,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])
ONBOARDING_CONFLICT_FALLBACK = "The service rejected this request."


def _onboarding_conflict(error_code: str, message_code: str) -> JSONResponse:
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
    """Records acknowledgment of the onboarding privacy notice before answers are accepted."""
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
            return intake_service.save_answer(
                db,
                str(player),
                field,
                body.value,
                ledger=ledger,
                player_account_id=account_id_of(player),
                client=analytics_service.client_context(request),
            )
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
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Writes the confirmed profile and creates the first program exactly once (ADR 021)."""

    def _run():
        answers = ledger.load_intake_answers()
        try:
            result = intake_service.confirm_intake(
                db,
                str(player),
                player_account_id=account_id_of(player),
                ledger=ledger,
                client=analytics_service.client_context(request),
            )
        except intake_service.IntakeDisclosureRequired as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from None
        except intake_service.IntakeValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
        field_copy = intake_service.build_view(db, str(player), ledger)["fields"]
        response = {**result, "fields": field_copy}
        if result.get("status") != intake_service.STATUS_CONFIRMED:
            return _OnboardingRouteOutcome(response)
        _record_onboarding_started(request, account_id_of(player), ledger)
        completion = onboarding_service.record_onboarding_completion(ledger, answers)
        return _OnboardingRouteOutcome(response, completion)

    try:
        outcome = await asyncio.to_thread(_run)
    except intake_service.IntakeConfirmInProgress:
        return _onboarding_conflict("confirm_in_progress", "intake.in_progress.v1")
    _capture_onboarding_completed(request, account_id_of(player), outcome.completion)
    return outcome.response_body
