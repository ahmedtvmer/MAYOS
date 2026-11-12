"""Authenticated client transport-failure uploads (#691)."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from svc.connection_failures import ConnectionFailureMetrics
from svc.dependencies import VerifiedAccount, get_verified_account
from svc.rate_limit import CLIENT_CONNECTION_FAILURE_LIMIT, limiter
from svc.schemas import ClientConnectionFailureBatchIn

router = APIRouter(prefix="/client", tags=["client"])
_MAX_EVENT_AGE = timedelta(days=30)
_MAX_CLOCK_SKEW = timedelta(minutes=5)


@router.post("/connection-failures", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(CLIENT_CONNECTION_FAILURE_LIMIT)
async def record_connection_failures(
    request: Request,
    batch: ClientConnectionFailureBatchIn,
    _account: Annotated[VerifiedAccount, Depends(get_verified_account)],
) -> dict[str, int]:
    now = datetime.now(UTC)
    metrics: ConnectionFailureMetrics = request.app.state.connection_failure_metrics
    allowed_routes: frozenset[str] = request.app.state.connection_failure_route_templates
    accepted = 0
    for failure in batch.failures:
        if failure.occurred_at < now - _MAX_EVENT_AGE:
            continue
        if failure.occurred_at > now + _MAX_CLOCK_SKEW:
            continue
        metrics.record(failure, allowed_routes)
        accepted += 1
    return {"accepted": accepted}
