"""FastAPI dependencies: database handle and verified trainee identity."""

from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from service._base import bind_user
from svc.auth import token_claims, token_version_of

_bearer = HTTPBearer(auto_error=False)


def get_db() -> Any:
    from database.database_manager import DatabaseManager

    return DatabaseManager()


async def get_current_trainee(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Any, Depends(get_db)],
) -> str:
    """Derives the trainee id from a verified, non-revoked Bearer JWT. Never from the body."""
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    try:
        claims = token_claims(credentials.credentials)
        trainee = str(claims["sub"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.") from None
    bind_user(db, trainee)
    if db.is_token_revoked(str(claims["jti"])):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked.")
    if token_version_of(claims) != db.get_token_version():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked.")
    return trainee


def bind_request(db: Any, trainee_id: str) -> str:
    """Mounts the verified trainee ledger on this worker thread and sets the request ContextVar."""
    return bind_user(db, trainee_id)
