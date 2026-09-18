"""Registration, login, legacy claim, and logout. Issues JWTs on password proof."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from service import auth as auth_service
from svc.auth import create_access_token, revoke_token
from svc.dependencies import get_db
from svc.rate_limit import REGISTER_LIMIT, LOGIN_LIMIT, limiter
from svc.schemas import TokenOut, TraineeIn

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(REGISTER_LIMIT)
async def register(request: Request, body: TraineeIn, db: Annotated[Any, Depends(get_db)]):
    def _run():
        result = auth_service.register_trainee(db, body.trainee_id, body.password)
        if not result["ok"]:
            status_code = status.HTTP_409_CONFLICT if "already exists" in result["error"] else status.HTTP_400_BAD_REQUEST
            raise HTTPException(status_code=status_code, detail=result["error"])
        return result["trainee_id"]

    trainee_id = await asyncio.to_thread(_run)
    return TokenOut(access_token=create_access_token(trainee_id), trainee_id=trainee_id)


@router.post("/login", response_model=TokenOut)
@limiter.limit(LOGIN_LIMIT)
async def login(request: Request, body: TraineeIn, db: Annotated[Any, Depends(get_db)]):
    def _run():
        result = auth_service.login_trainee(db, body.trainee_id, body.password)
        if not result["ok"]:
            if result.get("code") == "claim_required":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This ledger predates passwords. Set one to continue.",
                )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=result["error"])
        return result

    result = await asyncio.to_thread(_run)
    return TokenOut(access_token=create_access_token(result["trainee_id"]), trainee_id=result["trainee_id"])


@router.post("/claim", response_model=TokenOut)
@limiter.limit(REGISTER_LIMIT)
async def claim(request: Request, body: TraineeIn, db: Annotated[Any, Depends(get_db)]):
    """One-time password claim for pre-password ledgers."""

    def _run():
        result = auth_service.claim_trainee(db, body.trainee_id, body.password)
        if not result["ok"]:
            status_code = status.HTTP_400_BAD_REQUEST if "must be" in result["error"] else status.HTTP_401_UNAUTHORIZED
            raise HTTPException(status_code=status_code, detail=result["error"])
        return result["trainee_id"]

    trainee_id = await asyncio.to_thread(_run)
    return TokenOut(access_token=create_access_token(trainee_id), trainee_id=trainee_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Any, Depends(get_db)],
):
    """Revokes the presenting token; the client must discard its copy."""
    if credentials is None or not credentials.credentials:
        return None

    def _run():
        import jwt as pyjwt

        try:
            revoke_token(db, credentials.credentials)
        except pyjwt.PyJWTError:
            pass

    await asyncio.to_thread(_run)
    return None
