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


def remember_me_hours() -> int:
    """Lifetime for remembered sessions (default 30 days), clamped to 1 hour – 1 year."""
    try:
        return min(max(int(os.getenv("JWT_REMEMBER_ME_HOURS", "720")), 1), 8760)
    except ValueError:
        return 720


def _secret() -> str:
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET is not set; refusing to sign or verify tokens.")
    return secret


def create_access_token(subject: str, expires_hours: int | None = None, token_version: int = 1) -> str:
    """Signs a JWT whose ``sub`` is the immutable account id (never the username)."""
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "jti": uuid.uuid4().hex,
        "tv": max(1, int(token_version)),
        "iat": now,
        "exp": now + timedelta(hours=expires_hours if expires_hours is not None else expiry_hours()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def token_claims(token: str) -> dict[str, Any]:
    """Returns the verified payload or raises :class:`jwt.PyJWTError`."""
    payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    if not payload.get("sub") or not payload.get("jti"):
        raise jwt.InvalidTokenError("Token is missing subject or id.")
    if "tv" in payload:
        try:
            if int(payload["tv"]) < 1:
                raise jwt.InvalidTokenError("Token has an invalid session version.")
        except (TypeError, ValueError):
            raise jwt.InvalidTokenError("Token has an invalid session version.")
    return payload


def token_version_of(claims: dict[str, Any]) -> int:
    """Session epoch carried by the token. Pre-v3 tokens predate versioning and read as 1."""
    try:
        return max(1, int(claims.get("tv", 1)))
    except (TypeError, ValueError):
        return 1


def decode_access_token(token: str) -> str:
    """Returns the trainee ``sub`` or raises :class:`jwt.PyJWTError`."""
    return str(token_claims(token)["sub"])


def revoke_token(db: Any, token: str) -> None:
    """Revokes the token's ``jti`` in the account's ledger; prunes expired entries.

    Rechecks the immutable account in the registry before writing: a token whose
    account is unknown, deleted, missing the player capability, has a stale
    session epoch, or whose ledger no longer exists revokes nothing and never
    mounts a ledger.
    """
    from datetime import UTC, datetime

    claims = token_claims(token)
    account = db.get_account(str(claims["sub"]))
    if not db.is_live_account(account) or not account["is_player"]:
        # Unknown, inactive, deleted, or capability-less account: never create a ledger.
        return
    if token_version_of(claims) != account["session_epoch"]:
        return
    ledger_id = account["ledger_id"]
    if not db.user_exists(ledger_id):
        return
    if db.active_user != ledger_id:
        db.switch_user(ledger_id)
    exp = claims.get("exp")
    expires_at = (
        datetime.fromtimestamp(exp, UTC).isoformat() if isinstance(exp, (int, float)) else datetime.now(UTC).isoformat()
    )
    db.revoke_token(str(claims["jti"]), expires_at)
    db.prune_revoked_tokens(datetime.now(UTC).isoformat())
