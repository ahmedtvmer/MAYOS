"""FastAPI dependencies: database handle and verified trainee identity."""

from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from service._base import bind_user
from svc.auth import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_db() -> Any:
    from database.database_manager import DatabaseManager

    return DatabaseManager()


async def get_current_trainee(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """Derives the trainee id from a verified Bearer JWT. Never from the body."""
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    try:
        return decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.") from None


def bind_request(db: Any, trainee_id: str) -> str:
    """Mounts the verified trainee ledger on this worker thread and sets the request ContextVar."""
    return bind_user(db, trainee_id)
