"""FastAPI dependencies: database handle and verified player identity."""

from typing import Annotated, Any, NamedTuple

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from svc.auth import token_claims, token_version_of

_bearer = HTTPBearer(auto_error=False)


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
    return player


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
    return player


def account_id_of(player: Any) -> str | None:
    """Returns the verified account id carried by the player, or None for a bare ledger id."""
    return player.account_id if isinstance(player, VerifiedPlayer) else None
