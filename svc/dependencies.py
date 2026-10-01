"""FastAPI dependencies: database handle, verified player identity, Google ID-token seam."""

import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, NamedTuple

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from service.google_sign_in import GoogleIdentity
from svc.auth import signup_ticket_subject, token_claims, token_version_of

_bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)
_monotonic = time.monotonic
_last_seen_lock = threading.Lock()
_last_seen_cache_day: str | None = None
_last_seen_retry_after_by_account: dict[str, float | None] = {}
_LAST_SEEN_RETRY_BACKOFF_SECONDS = 10 * 60

#: Config read **by name only** — never hard-coded, never logged (#113).
GOOGLE_WEB_CLIENT_ID_ENV = "GOOGLE_WEB_CLIENT_ID"
_GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
#: Leeway for ``exp``/``iat`` so a few seconds of clock drift between the app
#: server and Google does not refuse an otherwise valid ID token.
GOOGLE_CLOCK_SKEW_SECONDS = 10


class AccountDeletedError(HTTPException):
    """401 that distinguishes a deleted account from an ordinary expiry.

    Raised only after the token's signature verified and its subject is
    recorded as deleted (durable deletion record or catalog ``deleted_at``), so
    a device can safely erase local data for that account. The application maps
    it to a machine-readable ``{"error": "account_deleted"}`` body; ordinary
    expiry keeps the existing ``{"detail": ...}`` 401 shape (ADR 039).
    """

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account deleted.")


class VerifiedPlayer(str):
    """Ledger id carrying the account identity verified for this request."""

    def __new__(cls, ledger_id: str, account_id: str, session_epoch: int):
        value = str.__new__(cls, ledger_id)
        value.account_id = account_id
        value.session_epoch = session_epoch
        return value


class VerifiedAccount:
    """Authenticated account identity that does not require Player capability."""

    def __init__(self, account_id: str):
        self.account_id = account_id


async def get_db(request: Request) -> Any:
    """Returns the one store the application built at startup (ADR 041).

    Never constructs a store: the app owns exactly one, created in the lifespan
    and published on ``app.state``. Callers pass it explicitly to service code.
    """
    store = request.app.state.db
    if store is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database not ready.")
    return store


def _authorize_account(db: Any, account_id: str, token_epoch: int) -> dict[str, Any]:
    """Validates the account registry entry before any ledger is mounted.

    Raises 401 for an unknown/deleted account, a missing player capability, a
    stale session epoch, or a ledger that no longer exists. A deleted account is
    reported with the distinct :class:`AccountDeletedError` so a device holding a
    validly signed but dead token can tell "account deleted" from ordinary expiry.
    """
    if db.is_account_deleted(account_id):
        # The durable record is authoritative even before/without the catalog row.
        raise AccountDeletedError()
    account = db.get_account(account_id)
    if account is not None and account["deleted_at"] is not None:
        raise AccountDeletedError()
    if not db.is_live_account(account) or not account["is_player"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
    if token_epoch != account["session_epoch"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked.")
    if not db.ledger_exists(account["ledger_id"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
    return account


class _RegistryIdentity(NamedTuple):
    """A verified token plus its durable registry account, before any ledger mount."""

    claims: dict[str, Any]
    account: dict[str, Any]


def _resolve_registry_identity(
    credentials: HTTPAuthorizationCredentials | None, db: Any
) -> _RegistryIdentity:
    """Verifies the bearer signature and registry account without mounting a ledger.

    Every registry check — live account, player capability, session epoch, and
    ledger existence — runs here, before any ledger is opened (ADR 015). Raises
    401 for a missing/invalid/expired token, an unknown/deleted account, a
    missing player capability, a stale epoch, or a missing ledger.
    """
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    try:
        claims = token_claims(credentials.credentials)
        account_id = str(claims["sub"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.") from None
    account = _authorize_account(db, account_id, token_version_of(claims))
    return _RegistryIdentity(claims, account)


def _verified_player(identity: _RegistryIdentity) -> VerifiedPlayer:
    """Builds the verified-player marker without opening or mounting a ledger."""
    claims, account = identity
    player = VerifiedPlayer(account["ledger_id"], account["account_id"], token_version_of(claims))
    player.jti = str(claims["jti"])
    return player


def _reject_revoked_token(db: Any, player: VerifiedPlayer) -> None:
    """Rejects a token whose ``jti`` is revoked, using a short-lived ledger handle.

    The registry gate has already passed, so opening the ledger repeats only the
    deleted-ledger refusal (ADR 025 gate-then-mount). The handle closes before the
    request handler runs, which makes every authenticated route reject a
    logged-out token, not only the routes that open a request-scoped ledger.
    """
    with db.open_ledger(str(player)) as ledger:
        if ledger.is_token_revoked(player.jti):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked.")


def _utc_day() -> str:
    return datetime.now(UTC).date().isoformat()


def _record_last_seen(db: Any, account_id: str) -> None:
    """Writes activity once per account and UTC day without failing the request."""
    day = _utc_day()
    now = _monotonic()
    global _last_seen_cache_day
    with _last_seen_lock:
        if _last_seen_cache_day != day:
            _last_seen_retry_after_by_account.clear()
            _last_seen_cache_day = day
        retry_after = _last_seen_retry_after_by_account.get(account_id, -1.0)
        if retry_after is None or now < retry_after:
            return
        _last_seen_retry_after_by_account[account_id] = None
    try:
        db.set_account_last_seen_at(account_id, day)
    except Exception:
        logger.exception("Failed to update last-seen day for account %s", account_id)
        with _last_seen_lock:
            if _last_seen_cache_day == day and _last_seen_retry_after_by_account.get(account_id) is None:
                _last_seen_retry_after_by_account[account_id] = _monotonic() + _LAST_SEEN_RETRY_BACKOFF_SECONDS


async def get_verified_player(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Any, Depends(get_db)],
) -> VerifiedPlayer:
    """Resolves a verified, active player, refusing a revoked token before returning.

    Every registry check runs first (ADR 025); the ``jti`` revocation lookup then
    runs through a short-lived ledger handle that closes before the handler starts.
    """
    player = _verified_player(_resolve_registry_identity(credentials, db))
    _reject_revoked_token(db, player)
    _record_last_seen(db, player.account_id)
    return player


async def get_verified_account(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Any, Depends(get_db)],
) -> VerifiedAccount:
    """Authenticates an Account-level preference independent of its capabilities."""
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    try:
        claims = token_claims(credentials.credentials)
        account_id = str(claims["sub"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.") from None
    if db.is_account_deleted(account_id):
        raise AccountDeletedError()
    account = db.get_account(account_id)
    if account is not None and account["deleted_at"] is not None:
        raise AccountDeletedError()
    if not db.is_live_account(account) or token_version_of(claims) != account["session_epoch"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
    if not db.ledger_exists(account["ledger_id"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
    with db.open_ledger(account["ledger_id"]) as ledger:
        if ledger.is_token_revoked(str(claims["jti"])):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked.")
    _record_last_seen(db, account_id)
    return VerifiedAccount(account_id)


async def get_ledger(
    player: Annotated[VerifiedPlayer, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """Opens the verified player's ledger as an explicit handle for the request.

    ``get_verified_player`` already ran every registry check and refused a revoked
    ``jti``, so this only mounts; ``open_ledger`` still repeats the deleted-ledger
    refusal and migrations (ADR 025). The handle closes when the request finishes.
    """
    with db.open_ledger(str(player)) as ledger:
        yield ledger


async def get_current_player(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Any, Depends(get_db)],
) -> str:
    """Resolves a verified, active player account to its ledger id. Never trusts the body.

    Every registry check runs first (ADR 025); a revoked ``jti`` is then rejected
    through a short-lived ledger handle that closes before the handler runs.
    """
    player = _verified_player(_resolve_registry_identity(credentials, db))
    _reject_revoked_token(db, player)
    _record_last_seen(db, player.account_id)
    return player


async def get_current_coach(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Any, Depends(get_db)],
) -> VerifiedPlayer:
    """Resolves a verified account that currently holds the coach capability.

    The capability is read from the durable registry before any ledger is opened,
    so a valid player without coaching is refused 403 without opening a ledger. A
    grant or revocation takes effect without reissuing the token.
    """
    identity = _resolve_registry_identity(credentials, db)
    if not identity.account["is_coach"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Coach capability required.")
    player = _verified_player(identity)
    _reject_revoked_token(db, player)
    _record_last_seen(db, player.account_id)
    return player


def account_id_of(player: Any) -> str | None:
    """Returns the verified account id carried by the player, or None for a bare ledger id."""
    return player.account_id if isinstance(player, VerifiedPlayer) else None


class GoogleIdentityError(Exception):
    """A Google ID token failed verification: signature, audience, issuer, or expiry."""


#: The seam's shape: a raw ID token in, the verified identity out.
GoogleVerifier = Callable[[str], GoogleIdentity]


def google_web_client_id() -> str:
    """The one audience Google ID tokens are verified against; empty when unset."""
    return os.getenv(GOOGLE_WEB_CLIENT_ID_ENV, "").strip()


def google_sign_in_enabled() -> None:
    """The **one** place that decides "unconfigured → 503": gate for every Google endpoint.

    Nothing else changes when the variable is absent — password registration,
    login, claim and the rest of the service behave exactly as before (#113).
    """
    if not google_web_client_id():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Google sign-in is not configured.")


def get_google_verifier() -> GoogleVerifier:
    """The production verifier seam, injected like the other app-owned dependencies.

    Tests replace this dependency with a fake, so no test reaches Google's
    network; production replaces nothing and never sees a fake. Configuration
    is *not* checked here: ``google_sign_in_enabled`` owns that decision, so
    the 503 path exists in exactly one place.
    """
    return _verify_google_id_token


def get_signup_subject(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """The Google subject a signup ticket was minted for.

    The ticket rides in the ``Authorization: Bearer`` header — never the query
    string — so it cannot land in access logs. A missing, expired, tampered,
    or non-ticket token all share one 401.
    """
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing signup ticket.")
    try:
        return signup_ticket_subject(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired signup ticket.") from None


_GOOGLE_TRANSPORT: Any | None = None
_GOOGLE_TRANSPORT_LOCK = threading.Lock()


def _google_transport() -> Any:
    """The one cached google-auth ``Request``, built over a module-level session.

    Every verification shares a single ``Request`` wrapping a single
    ``requests.Session``, so sign-ins reuse one pooled connection instead of
    building a fresh ``Session``/``Request`` pair per call (cachecontrol is
    not a dependency of this project, so no HTTP-level response cache is
    layered on — a module-level session is the fallback). Built lazily, on
    first use, and guarded so concurrent first sign-ins build it once.
    """
    global _GOOGLE_TRANSPORT
    if _GOOGLE_TRANSPORT is None:
        with _GOOGLE_TRANSPORT_LOCK:
            if _GOOGLE_TRANSPORT is None:
                import requests
                from google.auth.transport import requests as google_requests

                _GOOGLE_TRANSPORT = google_requests.Request(requests.Session())
    return _GOOGLE_TRANSPORT


def _verify_google_id_token(raw_id_token: str) -> GoogleIdentity:
    """Verify against ``GOOGLE_WEB_CLIENT_ID`` and return only needed claims.

    google-auth checks the signature, the audience, ``exp``/``iat`` (with a
    small clock skew), and the issuer; every rejection — wrong audience or
    issuer included — collapses into :class:`GoogleIdentityError`, so callers
    see one generic failure.

    Verification runs on the one cached transport (:func:`_google_transport`)
    instead of a fresh ``Session`` per sign-in. Imports stay lazy so a missing
    optional transport can only ever affect these endpoints, never the rest of
    the service.
    """
    audience = google_web_client_id()
    if not audience:
        # ``google_sign_in_enabled`` is the single place that answers 503 for an
        # unconfigured audience, and the /auth/google* routes gate on it — but
        # DELETE /auth/account deliberately does not (its password proof must
        # keep working unconfigured), so that route does reach here. Fail closed
        # with a generic identity error there — the same refusal as any other
        # rejected token — rather than verifying with no audience.
        raise GoogleIdentityError("Google sign-in is not configured.")
    from google.auth import exceptions as google_auth_exceptions
    from google.oauth2 import id_token as google_id_token

    try:
        info = google_id_token.verify_oauth2_token(
            raw_id_token,
            _google_transport(),
            audience=audience,
            clock_skew_in_seconds=GOOGLE_CLOCK_SKEW_SECONDS,
        )
    except (ValueError, KeyError, google_auth_exceptions.GoogleAuthError):
        raise GoogleIdentityError("Google rejected the ID token.") from None
    # google-auth enforces this too; keeping our own check states the contract
    # independently of the library's internals.
    if not isinstance(info, dict) or info.get("iss") not in _GOOGLE_ISSUERS:
        raise GoogleIdentityError("Google ID token has an untrusted issuer.")
    sub = info.get("sub")
    if not isinstance(sub, str) or not sub:
        raise GoogleIdentityError("Google ID token has no subject.")
    iat = info.get("iat")
    given_name = info.get("given_name")
    email = info.get("email")
    return GoogleIdentity(
        sub=sub,
        iat=iat if isinstance(iat, int) else None,
        given_name=given_name if isinstance(given_name, str) else None,
        email=email if isinstance(email, str) else None,
        email_verified=info.get("email_verified") is True,
    )
