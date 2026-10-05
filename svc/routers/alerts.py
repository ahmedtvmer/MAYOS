"""Coach missed-day alert routes (ticket #31, ADR 030).

The alert centre is catalog-only: listing and resolving alerts resolves the
authenticated coach's active assignment from the catalog and never mounts a
player ledger (ADR 025). An unknown, foreign, or ended assignment returns the
same generic denial as the rest of the coach surface.
"""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from service import analytics as analytics_service
from service import missed_day_alerts as alerts_service
from service.assignments import DENIED_ERROR
from service.messages import MessageMetadata
from svc.dependencies import VerifiedPlayer, get_current_coach, get_db
from svc.errors import message_http_exception
from svc.rate_limit import ASSIGNMENT_MUTATE_LIMIT, limiter
from svc.schemas import CoachAlertListOut, CoachAlertOut

router = APIRouter(prefix="/coach/alerts", tags=["coach"])


def _no_active_assignment() -> HTTPException:
    """One generic 403 for unknown, ended, and other-coach assignments alike.

    A resolved alert is not a denial: acknowledge/resolve on it is idempotent and
    returns 200 with the alert still resolved.
    """
    return message_http_exception(
        status.HTTP_403_FORBIDDEN,
        DENIED_ERROR,
        MessageMetadata("assignment.none_active.v1"),
    )


@router.get("", response_model=CoachAlertListOut)
async def list_coach_alerts(
    request: Request,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
    state: Annotated[list[str] | None, Query()] = None,
):
    """Lists the coach's missed-day alerts; defaults to new + acknowledged."""
    states = tuple(state) if state else alerts_service.DEFAULT_ALERT_STATES
    for requested in states:
        if requested not in alerts_service.ALERT_STATES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="state must be new, acknowledged, or resolved.",
            )
    client = analytics_service.client_context(request)
    rows = await asyncio.to_thread(
        alerts_service.list_alerts, db, coach.account_id, states, client=client
    )
    return CoachAlertListOut(alerts=[CoachAlertOut(**row) for row in rows])


@router.post("/{alert_id}/acknowledge", response_model=CoachAlertOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def acknowledge_coach_alert(
    request: Request,
    alert_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Acknowledges one of the coach's alerts; an already-acknowledged alert is idempotent."""
    alert = await asyncio.to_thread(
        alerts_service.acknowledge_alert,
        db,
        coach.account_id,
        alert_id,
        client=analytics_service.client_context(request),
    )
    if alert is None:
        raise _no_active_assignment()
    return CoachAlertOut(**alert)


@router.post("/{alert_id}/resolve", response_model=CoachAlertOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def resolve_coach_alert(
    request: Request,
    alert_id: str,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Resolves one of the coach's alerts; an already-resolved alert is idempotent."""
    alert = await asyncio.to_thread(
        alerts_service.resolve_alert,
        db,
        coach.account_id,
        alert_id,
        client=analytics_service.client_context(request),
    )
    if alert is None:
        raise _no_active_assignment()
    return CoachAlertOut(**alert)
