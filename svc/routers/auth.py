"""Registration, login, legacy claim, password change/recovery, and logout."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from service import auth as auth_service
from service import password_reset as reset_service
from svc.auth import create_access_token, remember_me_hours, revoke_token
from svc.dependencies import VerifiedPlayer, bind_request, get_current_trainee, get_db
from svc.rate_limit import PASSWORD_LIMIT, REGISTER_LIMIT, LOGIN_LIMIT, RESET_LIMIT, limiter
from svc.schemas import (
    EmailUpdateIn,
    ForgotPasswordIn,
    MessageOut,
    PasswordChangeIn,
    RecoveryEmailOut,
    ResetPasswordIn,
    TokenOut,
    TraineeIn,
)

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
        return result

    result = await asyncio.to_thread(_run)
    return TokenOut(
        access_token=create_access_token(
            result["account_id"],
            expires_hours=remember_me_hours() if body.remember_me else None,
            token_version=result["session_epoch"],
        ),
        trainee_id=result["trainee_id"],
    )


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
    return TokenOut(
        access_token=create_access_token(
            result["account_id"],
            expires_hours=remember_me_hours() if body.remember_me else None,
            token_version=result["session_epoch"],
        ),
        trainee_id=result["trainee_id"],
    )


@router.post("/claim", response_model=TokenOut)
@limiter.limit(REGISTER_LIMIT)
async def claim(request: Request, body: TraineeIn, db: Annotated[Any, Depends(get_db)]):
    """One-time password claim for enrolled accounts whose ledger has no password yet."""

    def _run():
        result = auth_service.claim_trainee(db, body.trainee_id, body.password)
        if not result["ok"]:
            status_code = status.HTTP_400_BAD_REQUEST if "must be" in result["error"] else status.HTTP_401_UNAUTHORIZED
            raise HTTPException(status_code=status_code, detail=result["error"])
        return result

    result = await asyncio.to_thread(_run)
    return TokenOut(
        access_token=create_access_token(
            result["account_id"],
            expires_hours=remember_me_hours() if body.remember_me else None,
            token_version=result["session_epoch"],
        ),
        trainee_id=result["trainee_id"],
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Any, Depends(get_db)],
):
    """Revokes the presenting token; the client must discard its copy.

    A request without credentials is an idempotent no-op (204). A request that
    presents a bearer token must pass the same registry checks as any other
    authenticated request — live account, player capability, and current session
    epoch — before its ``jti`` is revoked. Unknown, deleted, capability-less, or
    stale-epoch tokens fail closed with 401 and never mount a ledger.
    """
    if credentials is None or not credentials.credentials:
        return None

    trainee = await get_current_trainee(credentials, db)

    def _run():
        bind_request(db, trainee)
        revoke_token(db, credentials.credentials)

    await asyncio.to_thread(_run)
    return None


@router.post("/change-password", response_model=MessageOut)
@limiter.limit(PASSWORD_LIMIT)
async def change_password(
    request: Request,
    body: PasswordChangeIn,
    trainee: Annotated[VerifiedPlayer, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    """Authenticated password change. Revokes ALL sessions; the client must re-login."""

    def _run():
        bind_request(db, trainee)
        result = auth_service.change_password(db, trainee.account_id, body.current_password, body.new_password)
        if not result["ok"]:
            # Deliberately 400 (never 401): 401 means "session expired" to clients.
            status_code = status.HTTP_400_BAD_REQUEST
            raise HTTPException(status_code=status_code, detail=result["error"])
        return result["trainee_id"]

    changed_id = await asyncio.to_thread(_run)
    return MessageOut(message=f"Password updated for {changed_id}. All sessions revoked; please log in again.")


@router.get("/email", response_model=RecoveryEmailOut)
async def read_recovery_email(
    trainee: Annotated[VerifiedPlayer, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    def _run():
        bind_request(db, trainee)
        return reset_service.get_recovery_email(db, trainee.account_id)

    email = await asyncio.to_thread(_run)
    return RecoveryEmailOut(email=email)


@router.post("/email", response_model=RecoveryEmailOut)
@limiter.limit(PASSWORD_LIMIT)
async def set_recovery_email(
    request: Request,
    body: EmailUpdateIn,
    trainee: Annotated[VerifiedPlayer, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        bind_request(db, trainee)
        result = reset_service.set_recovery_email(db, trainee.account_id, body.email)
        if not result["ok"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
        return result["email"]

    email = await asyncio.to_thread(_run)
    return RecoveryEmailOut(email=email)


@router.post("/forgot-password", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(RESET_LIMIT)
async def forgot_password(request: Request, body: ForgotPasswordIn, db: Annotated[Any, Depends(get_db)]):
    """Always returns the same generic message (anti-enumeration), known or unknown email."""

    def _run():
        return reset_service.request_password_reset(db, body.email)

    result = await asyncio.to_thread(_run)
    return MessageOut(message=result["message"])


@router.post("/reset-password", response_model=MessageOut)
@limiter.limit(RESET_LIMIT)
async def reset_password(request: Request, body: ResetPasswordIn, db: Annotated[Any, Depends(get_db)]):
    """Redeems a single-use reset token. Unknown/expired/used tokens share one generic error."""

    def _run():
        result = reset_service.reset_password_with_token(db, body.token, body.new_password)
        if not result["ok"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
        return result["trainee_id"]

    changed_id = await asyncio.to_thread(_run)
    return MessageOut(message=f"Password reset for {changed_id}. Please log in with the new password.")
