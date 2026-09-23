"""FastAPI dependencies: database handle and verified trainee identity."""

from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from service._base import bind_user
from svc.auth import token_claims, token_version_of

_bearer = HTTPBearer(auto_error=False)


class VerifiedPlayer(str):
    """Ledger id carrying the account identity verified for this request."""

    def __new__(cls, ledger_id: str, account_id: str, session_epoch: int):
        value = str.__new__(cls, ledger_id)
        value.account_id = account_id
        value.session_epoch = session_epoch
        return value


def get_db() -> Any:
    from database.database_manager import DatabaseManager

    return DatabaseManager()


def _authorize_account(db: Any, account_id: str, token_epoch: int) -> dict[str, Any]:
    """Validates the account registry entry before any ledger is mounted.

    Raises 401 for an unknown/deleted account, a missing player capability, a
    stale session epoch, or a ledger that no longer exists.
    """
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_player"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
    if token_epoch != account["session_epoch"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked.")
    if not db.user_exists(account["ledger_id"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
    return account


async def get_current_trainee(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Any, Depends(get_db)],
) -> str:
    """Resolves a verified, active account to its ledger id. Never trusts the body.

    The JWT ``sub`` is the immutable account id; the registry is checked before
    the ledger is mounted, so a bad token cannot create a ledger as a side effect.
    """
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    try:
        claims = token_claims(credentials.credentials)
        account_id = str(claims["sub"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.") from None

    account = _authorize_account(db, account_id, token_version_of(claims))
    bind_user(db, account["ledger_id"])
    if db.is_token_revoked(str(claims["jti"])):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked.")
    return VerifiedPlayer(account["ledger_id"], account_id, token_version_of(claims))


def bind_request(db: Any, trainee_id: str) -> str:
    """Mounts the verified trainee ledger on this worker thread and sets the request ContextVar."""
    if isinstance(trainee_id, VerifiedPlayer):
        account = _authorize_account(db, trainee_id.account_id, trainee_id.session_epoch)
        if account["ledger_id"] != trainee_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
    return bind_user(db, trainee_id)
