"""JWT issuance and verification (HS256, shared secret)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

ALGORITHM = "HS256"


def expiry_hours() -> int:
    try:
        return max(1, int(os.getenv("JWT_EXPIRY_HOURS", "2")))
    except ValueError:
        return 2


def _secret() -> str:
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET is not set; refusing to sign or verify tokens.")
    return secret


def create_access_token(trainee_id: str, expires_hours: int | None = None) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": trainee_id,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(hours=expires_hours if expires_hours is not None else expiry_hours()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def token_claims(token: str) -> dict[str, Any]:
    """Returns the verified payload or raises :class:`jwt.PyJWTError`."""
    payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    if not payload.get("sub") or not payload.get("jti"):
        raise jwt.InvalidTokenError("Token is missing subject or id.")
    return payload


def decode_access_token(token: str) -> str:
    """Returns the trainee ``sub`` or raises :class:`jwt.PyJWTError`."""
    return str(token_claims(token)["sub"])
