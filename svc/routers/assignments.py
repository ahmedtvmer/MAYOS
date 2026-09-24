"""Assignment invite and lifecycle routes (ticket #24).

Two route groups share this module:

* ``/coach/assignments`` — coach issue, notices, roster identity, and revoke. Every
  route requires the live coach capability, which is checked from the durable
  registry before any ledger is mounted.
* ``/assignments`` — player preview, explicit consent, current assignment, and end.

The player and coach identities always come from the verified JWT. No request body
selects an account, and no raw invite code is ever logged.
"""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from service import assignments as assignment_service
from svc.dependencies import VerifiedPlayer, get_current_coach, get_current_trainee, get_db
from svc.rate_limit import (
    ASSIGNMENT_INVITE_LIMIT,
    ASSIGNMENT_MUTATE_LIMIT,
    ASSIGNMENT_PREVIEW_LIMIT,
    ASSIGNMENT_REDEEM_LIMIT,
    limiter,
)
from svc.schemas import (
    AssignmentAccessOut,
    AssignmentEndOut,
    AssignmentInviteIssueOut,
    AssignmentInvitePreviewOut,
    AssignmentInviteTokenIn,
    AssignmentNoticeOut,
    AssignmentOut,
    AssignmentRedeemIn,
    AssignmentRedeemOut,
    CoachAssignmentsOut,
    CoachIdentityOut,
    CoachNoticeListOut,
    CoachRosterEntryOut,
)

coach_router = APIRouter(prefix="/coach/assignments", tags=["coach"])
player_router = APIRouter(prefix="/assignments", tags=["assignments"])


def _bad_request(error: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)


def _assignment_out(assignment: dict[str, Any]) -> AssignmentOut:
    return AssignmentOut(
        assignment_id=assignment["assignment_id"],
        coach=CoachIdentityOut(**assignment["coach"]),
        started_at=assignment["started_at"],
        status=assignment["status"],
    )


# --------------------------------------------------------------------------
# Coach side
# --------------------------------------------------------------------------


@coach_router.post("/invites", response_model=AssignmentInviteIssueOut)
@limiter.limit(ASSIGNMENT_INVITE_LIMIT)
async def issue_assignment_invite(
    request: Request,
    trainee: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Issues a single-use, capacity-bound assignment invite for the authenticated coach."""

    def _run():
        result = assignment_service.issue_assignment_invite(db, trainee.account_id)
        if not result["ok"]:
            raise _bad_request(result["error"])
        return result

    result = await asyncio.to_thread(_run)
    return AssignmentInviteIssueOut(**result)


@coach_router.get("", response_model=CoachAssignmentsOut)
async def list_coach_assignments(
    trainee: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Lists the coach's active assignments (identity only; no training history)."""

    rows = await asyncio.to_thread(assignment_service.list_coach_assignments, db, trainee.account_id)
    return CoachAssignmentsOut(assignments=[CoachRosterEntryOut(**row) for row in rows])


@coach_router.get("/notices", response_model=CoachNoticeListOut)
async def list_coach_notices(
    trainee: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Lists the coach's assignment notices newest-first."""

    rows = await asyncio.to_thread(assignment_service.list_coach_notices, db, trainee.account_id)
    return CoachNoticeListOut(notices=[AssignmentNoticeOut(**row) for row in rows])


@coach_router.post("/notices/read")
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def mark_coach_notices_read(
    request: Request,
    trainee: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Marks all of the coach's notices read."""

    count = await asyncio.to_thread(assignment_service.mark_coach_notices_read, db, trainee.account_id)
    return {"marked_read": count}


@coach_router.post("/{assignment_id}/revoke", response_model=AssignmentEndOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def revoke_assignment(
    request: Request,
    assignment_id: str,
    trainee: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Coach ends one of their assignments; access is revoked immediately."""

    def _run():
        result = assignment_service.end_assignment(db, trainee.account_id, assignment_id, "coach")
        if not result["ok"]:
            if "not part of this assignment" in result["error"]:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result["error"])
            raise _bad_request(result["error"])
        return result

    result = await asyncio.to_thread(_run)
    return AssignmentEndOut(**result)


# --------------------------------------------------------------------------
# Player side
# --------------------------------------------------------------------------


@player_router.post("/invites/preview", response_model=AssignmentInvitePreviewOut)
@limiter.limit(ASSIGNMENT_PREVIEW_LIMIT)
async def preview_assignment_invite(
    request: Request,
    body: AssignmentInviteTokenIn,
    trainee: Annotated[VerifiedPlayer, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    """Shows the coach identity and exact access without consuming the code.

    The code travels in the body, never the URL, so it cannot leak through access logs.
    """

    def _run():
        result = assignment_service.preview_assignment_invite(db, body.token, trainee.account_id)
        if not result["ok"]:
            raise _bad_request(result["error"])
        return result

    result = await asyncio.to_thread(_run)
    return AssignmentInvitePreviewOut(
        coach=CoachIdentityOut(**result["coach"]),
        access=AssignmentAccessOut(**result["access"]),
        expires_at=result["expires_at"],
    )


@player_router.post("/invites/redeem", response_model=AssignmentRedeemOut)
@limiter.limit(ASSIGNMENT_REDEEM_LIMIT)
async def redeem_assignment_invite(
    request: Request,
    body: AssignmentRedeemIn,
    trainee: Annotated[VerifiedPlayer, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    """Explicitly consents to and atomically redeems an assignment invite."""

    def _run():
        result = assignment_service.redeem_assignment_invite(db, body.token, trainee.account_id, body.consent)
        if not result["ok"]:
            raise _bad_request(result["error"])
        return result

    result = await asyncio.to_thread(_run)
    return AssignmentRedeemOut(
        assignment=_assignment_out(result["assignment"]),
        notices_created=result["notices_created"],
        email_sent=result["email_sent"],
    )


@player_router.get("/me", response_model=AssignmentOut | None)
async def read_my_assignment(
    trainee: Annotated[VerifiedPlayer, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    """The caller's active assignment, or ``null`` when none is active."""

    assignment = await asyncio.to_thread(assignment_service.get_player_assignment, db, trainee.account_id)
    return _assignment_out(assignment) if assignment is not None else None


@player_router.post("/me/end", response_model=AssignmentEndOut)
@limiter.limit(ASSIGNMENT_MUTATE_LIMIT)
async def end_my_assignment(
    request: Request,
    trainee: Annotated[VerifiedPlayer, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    """Player ends their active assignment; coach access is revoked immediately."""

    def _run():
        assignment = assignment_service.get_player_assignment(db, trainee.account_id)
        if assignment is None:
            raise _bad_request("You have no active coaching assignment.")
        result = assignment_service.end_assignment(
            db, trainee.account_id, assignment["assignment_id"], "player"
        )
        if not result["ok"]:
            raise _bad_request(result["error"])
        return result

    result = await asyncio.to_thread(_run)
    return AssignmentEndOut(**result)
