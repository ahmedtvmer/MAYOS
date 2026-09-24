"""Coach capability redemption and coach-authored profile endpoints.

Issuance is intentionally absent here: during the closed trial only the owner
runs ``scripts/issue_coach_invite.py`` to mint an account-bound code. Redemption
is the sole path that sets ``is_coach``, and it requires a live invite bound to
the caller's immutable account id. The client body can never set the capability.
"""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from service import coach as coach_service
from svc.dependencies import VerifiedPlayer, get_current_coach, get_current_trainee, get_db
from svc.rate_limit import COACH_INVITE_LIMIT, limiter
from svc.schemas import (
    AccountCapabilitiesOut,
    AccountOut,
    CoachInviteRedeemIn,
    CoachProfileOut,
    CoachProfileUpdate,
)

router = APIRouter(prefix="/coach", tags=["coach"])


@router.post("/invite/redeem", response_model=AccountOut)
@limiter.limit(COACH_INVITE_LIMIT)
async def redeem_coach_invite(
    request: Request,
    body: CoachInviteRedeemIn,
    trainee: Annotated[VerifiedPlayer, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    """Authenticated single-use redemption of an owner-issued coach invite."""

    def _run():
        result = coach_service.redeem_coach_invite(db, trainee.account_id, body.token)
        if not result["ok"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
        return result

    result = await asyncio.to_thread(_run)
    return AccountOut(
        account_id=result["account_id"],
        trainee_id=result["username"],
        capabilities=AccountCapabilitiesOut(**result["capabilities"]),
    )


@router.get("/profile", response_model=CoachProfileOut)
async def read_coach_profile(
    trainee: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Reads the caller's coach profile; coach capability is required."""

    def _run():
        profile = coach_service.get_coach_profile(db, trainee.account_id)
        if profile is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No coach profile yet.")
        return profile

    return CoachProfileOut(**await asyncio.to_thread(_run))


@router.put("/profile", response_model=CoachProfileOut)
async def update_coach_profile(
    body: CoachProfileUpdate,
    trainee: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Updates display name, bio, specialization, and capacity; coach capability required."""

    def _run():
        result = coach_service.update_coach_profile(db, trainee.account_id, body.model_dump())
        if not result["ok"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
        return result["profile"]

    return CoachProfileOut(**await asyncio.to_thread(_run))
