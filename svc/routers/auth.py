"""Registration, login, Google linked sign-in, sign-in-method management, legacy claim, password change/recovery, and logout."""

import asyncio
from typing import Annotated, Any

import jwt
from fastapi.responses import JSONResponse
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from service import account_deletion as deletion_service
from service import auth as auth_service
from service import coach_ai as coach_ai_service
from service import google_sign_in as google_service
from service import password_reset as reset_service
from service import plans as plans_service
from svc.auth import create_access_token, create_signup_ticket, remember_me_hours, revoke_token, signup_ticket_subject
from svc.dependencies import (
    VerifiedPlayer,
    GoogleIdentityError,
    get_current_player,
    get_db,
    get_google_verifier,
    get_ledger,
    get_signup_subject,
    get_verified_player,
    google_sign_in_enabled,
)
from svc.rate_limit import PASSWORD_LIMIT, REGISTER_LIMIT, LOGIN_LIMIT, RESET_LIMIT, USERNAME_CHECK_LIMIT, limiter
from svc.schemas import (
    AccountCapabilitiesOut,
    AccountDeleteIn,
    AccountOut,
    AccountPlansOut,
    ClaimIn,
    EmailUpdateIn,
    ForgotPasswordIn,
    GoogleCompleteIn,
    GoogleLinkIn,
    GoogleSignInIn,
    GoogleSignUpOut,
    MessageOut,
    PasswordChangeIn,
    RecoveryEmailOut,
    ResetPasswordIn,
    SetPasswordIn,
    TokenOut,
    TraineeIn,
    UsernameAvailableOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(REGISTER_LIMIT)
async def register(request: Request, body: TraineeIn, db: Annotated[Any, Depends(get_db)]):
    def _run():
        result = auth_service.register_player(db, body.trainee_id, body.password)
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
        result = auth_service.login_player(db, body.trainee_id, body.password)
        if not result["ok"] and result.get("code") != "claim_required":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=result["error"])
        return result

    result = await asyncio.to_thread(_run)
    if not result["ok"]:
        # Machine-readable code so clients can offer the claim flow (#42).
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "This account must be claimed with its claim code.", "code": "claim_required"},
        )
    return TokenOut(
        access_token=create_access_token(
            result["account_id"],
            expires_hours=remember_me_hours() if body.remember_me else None,
            token_version=result["session_epoch"],
        ),
        trainee_id=result["trainee_id"],
    )


@router.post("/google")
@limiter.limit(LOGIN_LIMIT)
async def google_sign_in(
    request: Request,
    body: GoogleSignInIn,
    db: Annotated[Any, Depends(get_db)],
    google_enabled: Annotated[Any, Depends(google_sign_in_enabled)],
    verifier: Annotated[Any, Depends(get_google_verifier)],
):
    """Signs in with a Google ID token: straight in when linked, ticket otherwise.

    The token is verified against ``GOOGLE_WEB_CLIENT_ID`` (503 while that is
    unset). A subject already linked to a live account gets a session with the
    remember-me lifetime; any other subject gets a 15-minute signup ticket plus
    a username suggestion. No account, link, or profile data is written here,
    so abandoning the flow leaves nothing behind (#113).
    """
    try:
        identity = await asyncio.to_thread(verifier, body.id_token)
    except GoogleIdentityError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google credentials.") from None

    def _run():
        return google_service.sign_in(db, identity.sub, identity.given_name)

    result = await asyncio.to_thread(_run)
    if result["kind"] == "session":
        return TokenOut(
            access_token=create_access_token(
                result["account_id"],
                expires_hours=remember_me_hours(),
                token_version=result["session_epoch"],
            ),
            trainee_id=result["trainee_id"],
        )
    return GoogleSignUpOut(
        signup_ticket=create_signup_ticket(identity.sub),
        suggested_username=result["suggested_username"],
    )


@router.get("/username-available", response_model=UsernameAvailableOut, response_model_exclude_none=True)
@limiter.limit(USERNAME_CHECK_LIMIT)
async def username_available(
    request: Request,
    db: Annotated[Any, Depends(get_db)],
    google_enabled: Annotated[Any, Depends(google_sign_in_enabled)],
    subject: Annotated[str, Depends(get_signup_subject)],
    username: str,
):
    """Answers the picker: is this username free? Requires a signup ticket.

    The ticket travels in the ``Authorization: Bearer`` header (never in the
    query string) so it cannot land in access logs. A username that breaks the
    picker's rule is refused with a clear 400, never silently rewritten.
    """

    def _run():
        try:
            return google_service.username_available(db, username)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    return await asyncio.to_thread(_run)


@router.post("/google/complete", response_model=TokenOut)
@limiter.limit(REGISTER_LIMIT)
async def google_complete(
    request: Request,
    body: GoogleCompleteIn,
    db: Annotated[Any, Depends(get_db)],
    google_enabled: Annotated[Any, Depends(google_sign_in_enabled)],
):
    """Creates the account and its link in one catalog transaction (#113).

    Mirrors registration: player capability, its own ledger, no password hash.
    An invalid username is a 400; a taken username or a subject linked
    concurrently is a 409, and the losing request creates no account.
    """
    try:
        subject = signup_ticket_subject(body.signup_ticket)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired signup ticket."
        ) from None

    def _run():
        try:
            return google_service.complete_signup(db, subject, body.username)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
        except google_service.SignUpConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    result = await asyncio.to_thread(_run)
    return TokenOut(
        access_token=create_access_token(
            result["account_id"],
            expires_hours=remember_me_hours(),
            token_version=result["session_epoch"],
        ),
        trainee_id=result["trainee_id"],
    )


@router.post("/google/link", response_model=MessageOut)
@limiter.limit(PASSWORD_LIMIT)
async def link_google(
    request: Request,
    body: GoogleLinkIn,
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
    google_enabled: Annotated[Any, Depends(google_sign_in_enabled)],
    verifier: Annotated[Any, Depends(get_google_verifier)],
):
    """Connects a verified Google identity to the signed-in caller (#114).

    The token is verified the same way sign-in verifies it (503 while
    ``GOOGLE_WEB_CLIENT_ID`` is unset; a rejected token is the ordinary 401).
    Linking the same subject again is an idempotent success. A subject already
    connected to another MAYOS account is a 409 that never says which one, and
    a caller who already connected a different Google identity gets a 409
    telling them to disconnect it first. Connecting never bumps the session
    epoch: no credential changed.
    """
    try:
        identity = await asyncio.to_thread(verifier, body.id_token)
    except GoogleIdentityError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google credentials.") from None

    def _run():
        try:
            result = google_service.link_account(db, player.account_id, identity.sub)
        except google_service.SignInMethodError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
        if not result["ok"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
        return result["message"]

    message = await asyncio.to_thread(_run)
    return MessageOut(message=message)


@router.delete("/google/link", response_model=MessageOut)
@limiter.limit(PASSWORD_LIMIT)
async def unlink_google(
    request: Request,
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
    google_enabled: Annotated[Any, Depends(google_sign_in_enabled)],
):
    """Disconnects the caller's Google identity, refused while it has no password (#114).

    An account always keeps at least one way to sign in (CONTEXT.md, "Linked
    sign-in"), so a Google-only account must set a password first and gets a
    409 saying so. An account with no link is an idempotent success, and
    disconnecting never bumps the session epoch.
    """

    def _run():
        try:
            result = google_service.unlink_account(db, player.account_id)
        except google_service.SignInMethodError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
        if not result["ok"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
        return result["message"]

    message = await asyncio.to_thread(_run)
    return MessageOut(message=message)


@router.get("/me", response_model=AccountOut)
async def read_current_account(
    player: Annotated[VerifiedPlayer, Depends(get_current_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """Returns the authenticated account's identity, capabilities, plan states, and sign-in methods.

    Capabilities are read from the durable registry on every call, so a change
    (for example, a granted coach capability) is visible without reissuing the
    token. Plans are server-owned per capability and default to the ongoing Free
    plan for every capability the account holds. ``has_password`` and
    ``linked_sign_ins`` report how the account can sign in (#114) — provider
    names only, never a Google ``sub``. The endpoint fails closed for
    unknown/deleted/capability-less accounts via the shared auth dependency.
    """

    def _run():
        account = db.get_account(player.account_id)
        if not db.is_live_account(account):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
        return (
            account,
            plans_service.plans_for_account(db, account),
            auth_service.account_has_password(db, account),
            db.list_linked_sign_in_providers(account["account_id"]),
        )

    account, plans, has_password, linked_sign_ins = await asyncio.to_thread(_run)
    return AccountOut(
        account_id=account["account_id"],
        trainee_id=account["username"],
        capabilities=AccountCapabilitiesOut(player=account["is_player"], coach=account["is_coach"]),
        plans=AccountPlansOut(**plans),
        has_password=has_password,
        linked_sign_ins=linked_sign_ins,
        coach_ai_enabled=coach_ai_service.coach_ai_enabled(),
    )


@router.post("/claim", response_model=TokenOut)
@limiter.limit(REGISTER_LIMIT)
async def claim(request: Request, body: ClaimIn, db: Annotated[Any, Depends(get_db)]):
    """One-time password claim for an imported account with its owner-issued code.

    Requires the single-use, expiring, account-bound claim code (ADR 019). Every
    failure — unknown account, wrong/expired/reused code, or an already-claimed
    ledger — returns the same generic 401 so the endpoint cannot enumerate
    accounts or probe claim state. A too-weak password is a plain 400.
    """

    def _run():
        result = auth_service.claim_player(db, body.trainee_id, body.claim_code, body.password)
        if not result["ok"]:
            status_code = (
                status.HTTP_400_BAD_REQUEST if result.get("code") == "weak_new" else status.HTTP_401_UNAUTHORIZED
            )
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

    # Registry gate: the shared dependency verifies live account, player
    # capability, and current session epoch before the jti is revoked.
    await get_current_player(credentials, db)

    def _run():
        revoke_token(db, credentials.credentials)

    await asyncio.to_thread(_run)
    return None


@router.post("/change-password", response_model=MessageOut)
@limiter.limit(PASSWORD_LIMIT)
async def change_password(
    request: Request,
    body: PasswordChangeIn,
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Authenticated password change. Revokes ALL sessions; the client must re-login."""

    def _run():
        result = auth_service.change_password(
            db, player.account_id, body.current_password, body.new_password, ledger=ledger
        )
        if not result["ok"]:
            # Deliberately 400 (never 401): 401 means "session expired" to clients.
            status_code = status.HTTP_400_BAD_REQUEST
            raise HTTPException(status_code=status_code, detail=result["error"])
        return result["trainee_id"]

    changed_id = await asyncio.to_thread(_run)
    return MessageOut(message=f"Password updated for {changed_id}. All sessions revoked; please log in again.")


@router.post("/set-password", response_model=MessageOut)
@limiter.limit(PASSWORD_LIMIT)
async def set_password(
    request: Request,
    body: SetPasswordIn,
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """Gives a passwordless (e.g. Google-only) account its first password (#114).

    Only an account with **no** password may use it; one that already has a
    password is sent to ``change-password`` with a 409 instead. Validation is
    the existing password rule (400 when too weak, like every other password
    endpoint), and the session epoch is deliberately **not** bumped: adding a
    sign-in method must not sign the caller's other sessions out.
    """

    def _run():
        result = auth_service.set_initial_password(db, player.account_id, body.new_password)
        if not result["ok"]:
            status_code = (
                status.HTTP_409_CONFLICT if result.get("code") == "password_exists" else status.HTTP_400_BAD_REQUEST
            )
            raise HTTPException(status_code=status_code, detail=result["error"])
        return result["trainee_id"]

    trainee_id = await asyncio.to_thread(_run)
    return MessageOut(message=f"Password set for {trainee_id}. You can now also sign in with your password.")


@router.delete("/account", response_model=MessageOut)
@limiter.limit(PASSWORD_LIMIT)
async def delete_account(
    request: Request,
    body: AccountDeleteIn,
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
    verifier: Annotated[Any, Depends(get_google_verifier)],
):
    """Proof-confirmed, irreversible deletion of the caller's account (ADR 015/039).

    Exactly one proof is accepted: ``password`` or ``google_id_token`` (#114).
    The Google path needs a token whose ``sub`` is linked to the caller and
    whose ``iat`` is within the last 5 minutes; every failure of that check —
    stale, wrong sub, unverifiable — answers with the same generic 400 as a
    wrong password, so the endpoint reveals nothing about the link. A wrong
    password changes nothing and returns a generic 400 (never 401, which
    clients read as session expiry). On success every session is invalidated in
    the durable registry, the live ledger and its backups are removed, and the
    ``linked_sign_ins`` rows go in the same catalog transaction, so the Google
    account is free to create a new MAYOS account later. The username becomes
    reusable only as a new immutable account.

    The route holds no ledger handle: the password check opens a short-lived
    handle that closes before ``db.delete_account`` unlinks the ledger files, so
    deletion never races an open connection.
    """

    def _run(google_identity: Any | None = None):
        result = deletion_service.delete_account(
            db, player.account_id, body.password, google_identity=google_identity
        )
        if not result["ok"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
        return result

    if body.google_id_token is not None:
        try:
            identity = await asyncio.to_thread(verifier, body.google_id_token)
        except GoogleIdentityError:
            # Not a 401: an unverifiable token must look exactly like a wrong
            # password (#114), so this endpoint never says why it refused.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=auth_service.INVALID_CREDENTIALS
            ) from None
        await asyncio.to_thread(_run, identity)
    else:
        await asyncio.to_thread(_run)
    return MessageOut(message="Account deleted. All sessions have been ended.")


@router.get("/email", response_model=RecoveryEmailOut)
async def read_recovery_email(
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)], db: Annotated[Any, Depends(get_db)]
):
    def _run():
        return reset_service.get_recovery_email(db, player.account_id)

    email = await asyncio.to_thread(_run)
    return RecoveryEmailOut(email=email)


@router.post("/email", response_model=RecoveryEmailOut)
@limiter.limit(PASSWORD_LIMIT)
async def set_recovery_email(
    request: Request,
    body: EmailUpdateIn,
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        result = reset_service.set_recovery_email(db, player.account_id, body.email)
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
