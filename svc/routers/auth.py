"""Registration, login, Google linked sign-in, sign-in-method management, password recovery, and logout."""

import asyncio
import json
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from service import account_deletion as deletion_service
from service import acquisition as acquisition_service
from service import analytics as analytics_service
from service import auth as auth_service
from service import coach as coach_service
from service import coach_ai as coach_ai_service
from service import google_sign_in as google_service
from service import password_reset as reset_service
from service.email_verification import GENERIC_CODE_ERROR
from service import plans as plans_service
from service.messages import MessageMetadata
from svc.auth import (
    create_access_token,
    create_signup_ticket,
    remember_me_hours,
    revoke_token,
    signup_ticket_claims,
    signup_ticket_matches_id_token,
)
from svc.dependencies import (
    VerifiedPlayer,
    GoogleIdentityError,
    get_current_player,
    get_db,
    get_google_verifier,
    get_ledger,
    get_signup_subject,
    get_verified_player,
    get_verified_account,
    VerifiedAccount,
    google_sign_in_enabled,
)
from svc.errors import message_http_exception
from svc.rate_limit import PASSWORD_LIMIT, REGISTER_LIMIT, LOGIN_LIMIT, RESET_LIMIT, USERNAME_CHECK_LIMIT, limiter
from svc.schemas import (
    AccountCapabilitiesOut,
    AccountDeleteIn,
    AccountOut,
    AnalyticsPreferenceIn,
    DisplayLanguageIn,
    AccountPlansOut,
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


def _invalid_recovery_code() -> HTTPException:
    return message_http_exception(
        status.HTTP_400_BAD_REQUEST,
        GENERIC_CODE_ERROR,
        MessageMetadata("recovery.invalid_or_expired_code.v1"),
    )


def _invalid_google_credentials() -> HTTPException:
    return message_http_exception(
        status.HTTP_401_UNAUTHORIZED,
        "Invalid Google credentials.",
        MessageMetadata("google.invalid_token.v1"),
    )


def _first_touch_payload(body: TraineeIn | GoogleCompleteIn) -> dict[str, str] | None:
    return body.first_touch.model_dump(exclude_none=True) if body.first_touch else None


def _record_account_created(
    request: Request,
    account_id: str,
    *,
    invite_used: bool,
    first_touch: dict[str, str | None] | None = None,
) -> None:
    """Updates the PostHog person and records the committed account creation."""
    signup_phase = analytics_service.release_phase()
    person_properties = {"is_player": True, "is_coach": invite_used}
    if invite_used:
        person_properties["active_roster_size"] = 0
    analytics_service.set_person(account_id, person_properties)
    analytics_service.set_person_once(
        account_id,
        {
            "signup_phase": signup_phase,
            **acquisition_service.first_touch_person_properties(first_touch or {}),
        },
    )
    analytics_service.capture_for_request(
        request,
        analytics_service.AnalyticsEvent(
            account_id=account_id,
            event="account_created",
            domain_key=account_id,
            role="player",
            properties={"signup_phase": signup_phase, "invite_used": invite_used},
        ),
    )


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(REGISTER_LIMIT)
async def register(request: Request, body: TraineeIn, db: Annotated[Any, Depends(get_db)]):
    def _run():
        result = auth_service.register_player(
            db,
            body.trainee_id,
            body.password,
            auth_service.PlayerRegistration(
                coach_invite_code=body.coach_invite_code,
                display_language=body.display_language,
                first_touch=_first_touch_payload(body),
            ),
        )
        if not result["ok"]:
            status_code = (
                status.HTTP_409_CONFLICT
                if result.get("code") == "username_taken"
                else status.HTTP_400_BAD_REQUEST
            )
            if result.get("code") == "username_taken":
                raise message_http_exception(
                    status_code,
                    result["error"],
                    MessageMetadata("auth.username_taken.v1"),
                )
            if result.get("code") == "invalid_coach_invite":
                raise message_http_exception(
                    status_code,
                    result["error"],
                    MessageMetadata("coach_invite.invalid_code.v1"),
                )
            raise HTTPException(status_code=status_code, detail=result["error"])
        return result

    result = await asyncio.to_thread(_run)
    _record_account_created(
        request,
        result["account_id"],
        invite_used=body.coach_invite_code is not None,
        first_touch=result["first_touch"],
    )
    if result["coach_granted_at"] is not None:
        coach_service.capture_coach_capability_granted_event(
            result["account_id"],
            result["coach_granted_at"],
            client=analytics_service.client_context(request),
        )
    return TokenOut(
        access_token=create_access_token(
            result["account_id"],
            expires_hours=remember_me_hours() if body.remember_me else None,
            token_version=result["session_epoch"],
        ),
        trainee_id=result["trainee_id"],
        display_language=result.get("display_language", "en"),
    )


@router.post("/login", response_model=TokenOut)
@limiter.limit(LOGIN_LIMIT)
async def login(request: Request, body: TraineeIn, db: Annotated[Any, Depends(get_db)]):
    def _run():
        result = auth_service.login_player(db, body.trainee_id, body.password)
        if not result["ok"]:
            raise message_http_exception(
                status.HTTP_401_UNAUTHORIZED,
                result["error"],
                MessageMetadata("auth.invalid_credentials.v1"),
            )
        return result

    result = await asyncio.to_thread(_run)
    return TokenOut(
        access_token=create_access_token(
            result["account_id"],
            expires_hours=remember_me_hours() if body.remember_me else None,
            token_version=result["session_epoch"],
        ),
        trainee_id=result["trainee_id"],
        display_language=result.get("display_language", "en"),
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
    remember-me lifetime; any other subject gets a 15-minute signup ticket, a
    username suggestion, and a verified-recovery-email hint when applicable.
    No account or link is written here, so abandoning the flow leaves nothing
    behind (#113/#174).
    """
    try:
        identity = await asyncio.to_thread(verifier, body.id_token)
    except GoogleIdentityError:
        raise _invalid_google_credentials() from None

    def _run():
        return google_service.sign_in(db, identity)

    result = await asyncio.to_thread(_run)
    if result["kind"] == "session":
        return TokenOut(
            access_token=create_access_token(
                result["account_id"],
                expires_hours=remember_me_hours(),
                token_version=result["session_epoch"],
            ),
            trainee_id=result["trainee_id"],
            display_language=result.get("display_language", "en"),
        )
    return GoogleSignUpOut(
        signup_ticket=create_signup_ticket(
            identity.sub,
            recovery_email_conflict=result["existing_account_hint"],
            original_id_token=body.id_token,
        ),
        suggested_username=result["suggested_username"],
        existing_account_hint=result["existing_account_hint"],
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
    verifier: Annotated[Any, Depends(get_google_verifier)],
):
    """Creates the account and its link in one catalog transaction (#113).

    Mirrors registration: player capability, its own ledger, no password hash.
    An invalid username is a 400; a taken username or a subject linked
    concurrently is a 409, and the losing request creates no account.
    """
    try:
        claims = signup_ticket_claims(body.signup_ticket)
    except jwt.PyJWTError:
        raise message_http_exception(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired signup ticket.",
            MessageMetadata("auth.invalid_signup_ticket.v1"),
        ) from None
    subject = claims["sub"]
    identity = None
    if body.id_token is not None:
        try:
            identity = await asyncio.to_thread(verifier, body.id_token)
        except GoogleIdentityError:
            raise _invalid_google_credentials() from None
        if identity.sub != subject or not signup_ticket_matches_id_token(claims, body.id_token):
            raise _invalid_google_credentials()

    def _run():
        try:
            return google_service.complete_signup(
                db,
                google_service.GoogleSignupCompletion(
                    subject=subject,
                    username=body.username,
                    display_language=body.display_language,
                    identity=identity,
                    recovery_email_conflict=claims.get("recovery_email_conflict") is True,
                    first_touch=_first_touch_payload(body),
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
        except google_service.GoogleAccountAlreadyLinkedError as exc:
            raise message_http_exception(
                status.HTTP_409_CONFLICT,
                str(exc),
                MessageMetadata(
                    exc.message_code,
                    business_code="google_account_already_linked",
                ),
            ) from None
        except google_service.UsernameTakenError as exc:
            raise message_http_exception(
                status.HTTP_409_CONFLICT,
                str(exc),
                MessageMetadata(exc.message_code),
            ) from None
        except google_service.SignUpConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    result = await asyncio.to_thread(_run)
    _record_account_created(
        request,
        result["account_id"],
        invite_used=False,
        first_touch=result.get("first_touch"),
    )
    return TokenOut(
        access_token=create_access_token(
            result["account_id"],
            expires_hours=remember_me_hours(),
            token_version=result["session_epoch"],
        ),
        trainee_id=result["trainee_id"],
        display_language=result.get("display_language", "en"),
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
        raise _invalid_google_credentials() from None

    def _run():
        try:
            result = google_service.link_account(db, player.account_id, identity)
        except google_service.SignInMethodError as exc:
            raise message_http_exception(
                status.HTTP_409_CONFLICT,
                str(exc),
                MessageMetadata(exc.message_code),
            ) from None
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
            raise message_http_exception(
                status.HTTP_409_CONFLICT,
                str(exc),
                MessageMetadata(exc.message_code),
            ) from None
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
    token. Plans are server-owned per capability. The Coach plan includes the
    closed-trial override, so it is the effective entitlement clients use to
    show Pro-only surfaces. ``has_password`` and
    ``linked_sign_ins`` report how the account can sign in — provider
    names only, never a Google ``sub``. The endpoint fails closed for
    unknown/deleted/capability-less accounts via the shared auth dependency.
    """

    def _run():
        account = db.get_account(player.account_id)
        if not db.is_live_account(account):
            raise message_http_exception(
                status.HTTP_401_UNAUTHORIZED,
                "Invalid or expired token.",
                MessageMetadata("auth.invalid_or_expired_token.v1"),
            )
        plans = plans_service.effective_plans_for_account(db, account)
        return (
            account,
            plans,
            auth_service.account_has_password(db, account),
            db.list_linked_sign_in_providers(account["account_id"]),
            db.is_recovery_email_verified(account["account_id"]),
        )

    account, plans, has_password, linked_sign_ins, recovery_email_verified = await asyncio.to_thread(_run)
    return AccountOut(
        account_id=account["account_id"],
        trainee_id=account["username"],
        capabilities=AccountCapabilitiesOut(player=account["is_player"], coach=account["is_coach"]),
        plans=AccountPlansOut(**plans),
        has_password=has_password,
        linked_sign_ins=linked_sign_ins,
        display_language=account["display_language"],
        analytics_allowed=account["analytics_allowed"],
        recovery_email_verified=recovery_email_verified,
        coach_ai_enabled=coach_ai_service.coach_ai_enabled(),
    )


@router.put("/display-language")
async def update_display_language(
    body: DisplayLanguageIn,
    account: Annotated[VerifiedAccount, Depends(get_verified_account)],
    db: Annotated[Any, Depends(get_db)],
):
    """Saves the account's Display language by immutable account identity."""
    saved = await asyncio.to_thread(
        db.set_account_display_language, account.account_id, body.display_language
    )
    if not saved:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    return {"display_language": body.display_language}


@router.put("/analytics-preference")
@limiter.limit(PASSWORD_LIMIT)
async def update_analytics_preference(
    request: Request,
    body: AnalyticsPreferenceIn,
    account: Annotated[VerifiedAccount, Depends(get_verified_account)],
    db: Annotated[Any, Depends(get_db)],
):
    """Saves the account's analytics choice in the registry."""
    account_id = account.account_id
    changed = await asyncio.to_thread(
        db.set_account_analytics_allowed,
        account_id,
        body.analytics_allowed,
    )
    if changed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    if changed:
        await asyncio.to_thread(
            analytics_service.record_opt_out_change,
            account_id,
            not body.analytics_allowed,
        )
    return {"analytics_allowed": body.analytics_allowed}


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

    client = analytics_service.client_context(request)

    def _run(google_identity: Any | None = None):
        result = deletion_service.delete_account(
            db, player.account_id, body.password, google_identity=google_identity, client=client
        )
        if not result["ok"]:
            raise message_http_exception(
                status.HTTP_400_BAD_REQUEST,
                result["error"],
                MessageMetadata("auth.invalid_credentials.v1"),
            )
        return result

    if body.google_id_token is not None:
        try:
            identity = await asyncio.to_thread(verifier, body.google_id_token)
        except GoogleIdentityError:
            # Not a 401: an unverifiable token must look exactly like a wrong
            # password (#114), so this endpoint never says why it refused.
            raise message_http_exception(
                status.HTTP_400_BAD_REQUEST,
                auth_service.INVALID_CREDENTIALS,
                MessageMetadata("auth.invalid_credentials.v1"),
            ) from None
        await asyncio.to_thread(_run, identity)
    else:
        await asyncio.to_thread(_run)
    return MessageOut(message="Account deleted. All sessions have been ended.")


@router.get("/email", response_model=RecoveryEmailOut, response_model_exclude_unset=True)
async def read_recovery_email(
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)], db: Annotated[Any, Depends(get_db)]
):
    def _run():
        return (
            reset_service.get_recovery_email(db, player.account_id),
            db.is_recovery_email_verified(player.account_id),
            db.get_pending_recovery_email(player.account_id),
        )

    email, verified, pending_email = await asyncio.to_thread(_run)
    response = RecoveryEmailOut(email=email, verified=verified)
    if pending_email is not None:
        response.pending_email = pending_email
    return response


@router.post("/email", response_model=RecoveryEmailOut, response_model_exclude_unset=True)
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
        return result["email"], db.is_recovery_email_verified(player.account_id)

    email, verified = await asyncio.to_thread(_run)
    return RecoveryEmailOut(email=email, verified=verified)


@router.post("/email/change", response_model=MessageOut)
@limiter.limit(RESET_LIMIT)
async def request_recovery_email_change(
    request: Request,
    body: EmailUpdateIn,
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
):
    result = await asyncio.to_thread(
        reset_service.request_recovery_email_change,
        db,
        player.account_id,
        body.email,
    )
    if not result["ok"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return MessageOut(message="A verification code has been sent.")


@router.post("/email/verification-code", response_model=MessageOut)
@limiter.limit(RESET_LIMIT)
async def request_recovery_email_code(
    request: Request,
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """Sends a one-time code to the account's current unverified recovery email."""
    sent = await asyncio.to_thread(
        reset_service.issue_recovery_email_verification_code, db, player.account_id
    )
    if not sent:
        raise message_http_exception(
            status.HTTP_400_BAD_REQUEST,
            GENERIC_CODE_ERROR,
            MessageMetadata("recovery.code_send_limit.v1"),
        )
    return MessageOut(message="A verification code has been sent.")


@router.post("/email/verify", response_model=MessageOut)
@limiter.limit(PASSWORD_LIMIT)
async def verify_recovery_email(
    request: Request,
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """Consumes the code and confirms the account's current recovery email."""
    try:
        body = json.loads(await request.body())
    except ValueError:  # malformed JSON, bad encoding, or a number too long to parse
        raise _invalid_recovery_code() from None
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(code, str):
        raise _invalid_recovery_code()
    verified = await asyncio.to_thread(
        reset_service.verify_recovery_email_code, db, player.account_id, code
    )
    if not verified:
        raise _invalid_recovery_code()
    return MessageOut(message="Recovery email verified.")


@router.post("/email/change/verify", response_model=MessageOut)
@limiter.limit(PASSWORD_LIMIT)
async def verify_recovery_email_change(
    request: Request,
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
):
    try:
        body = json.loads(await request.body())
    except ValueError:
        raise _invalid_recovery_code() from None
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(code, str):
        raise _invalid_recovery_code()
    verified = await asyncio.to_thread(
        reset_service.verify_recovery_email_change_code, db, player.account_id, code
    )
    if not verified:
        raise _invalid_recovery_code()
    return MessageOut(message="Recovery email changed.")


@router.post("/forgot-password", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(RESET_LIMIT)
async def forgot_password(
    request: Request,
    body: ForgotPasswordIn,
    background_tasks: BackgroundTasks,
    db: Annotated[Any, Depends(get_db)],
):
    """Always returns the same generic message (anti-enumeration), known or unknown email."""
    background_tasks.add_task(reset_service.request_password_reset, db, body.email)
    return MessageOut(message=reset_service.GENERIC_REQUEST_MESSAGE)


@router.post("/reset-password", response_model=MessageOut)
@limiter.limit(RESET_LIMIT)
async def reset_password(request: Request, body: ResetPasswordIn, db: Annotated[Any, Depends(get_db)]):
    """Redeems a single-use reset token. Unknown/expired/used tokens share one generic error."""

    def _run():
        result = reset_service.reset_password_with_token(db, body.token, body.new_password)
        if not result["ok"]:
            raise message_http_exception(
                status.HTTP_400_BAD_REQUEST,
                result["error"],
                MessageMetadata("recovery.invalid_or_expired_token.v1"),
            )
        return result["trainee_id"]

    changed_id = await asyncio.to_thread(_run)
    return MessageOut(message=f"Password reset for {changed_id}. Please log in with the new password.")
