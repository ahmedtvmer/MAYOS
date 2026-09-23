"""Self-service account recovery: emails + single-use reset tokens.

Anti-enumeration contract: ``request_password_reset`` returns the same generic
result whether or not the email is linked, and ``reset_password_with_token``
uses one generic message for unknown/expired/used tokens. Route layers must
preserve this (same status code and body shape for both cases).
"""

import hashlib
import logging
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from service import auth as auth_service
from service._base import bind_user
from service.email_sender import build_reset_link, send_password_reset_email

logger = logging.getLogger(__name__)

GENERIC_REQUEST_MESSAGE = "If this email is linked to a ledger, a reset link is on its way."
GENERIC_TOKEN_ERROR = "Invalid or expired reset code."
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: Any) -> str | None:
    if not isinstance(email, str):
        return None
    cleaned = email.strip().lower()
    if not (3 <= len(cleaned) <= 254) or not EMAIL_RE.match(cleaned):
        return None
    return cleaned


def reset_ttl() -> timedelta:
    try:
        minutes = int(os.getenv("RESET_TOKEN_TTL_MINUTES", "30"))
    except ValueError:
        minutes = 30
    return timedelta(minutes=max(5, min(minutes, 120)))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _live_player_account(db: Any, recovery_key: Any) -> dict[str, Any] | None:
    """Resolves a stored recovery key to a live player account.

    New recovery rows store the immutable ``account_id``; legacy rows stored a
    reusable username. Only a key that resolves to a live (active, not deleted)
    player account is accepted, so a stale username-keyed row — or a row whose
    deletion left ``status='active'`` — can never target an account.
    """
    if not isinstance(recovery_key, str) or not recovery_key:
        return None
    account = db.get_account(recovery_key)
    if not db.is_live_account(account) or not account["is_player"]:
        return None
    return account


def get_recovery_email(db: Any, account_id: str) -> str | None:
    """Authenticated read: the recovery email bound to the caller's immutable account.

    ``account_id`` comes from the verified JWT, so a deleted account can never
    resolve to a new account that reused its username.
    """
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_player"] or not db.user_exists(account["ledger_id"]):
        return None
    return db.get_trainee_email(account["account_id"])


def set_recovery_email(db: Any, account_id: str, email: str) -> dict[str, Any]:
    """Authenticated: link (or replace) the recovery email for the caller's account.

    Resolves the immutable ``account_id`` from the verified JWT and refuses a
    deleted or non-player account, so a stale request cannot rebind a reused
    username's new account.
    """
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_player"] or not db.user_exists(account["ledger_id"]):
        return {"ok": False, "error": "Trainee ledger not found."}
    normalized = normalize_email(email)
    if normalized is None:
        return {"ok": False, "error": "Enter a valid email address."}
    bind_user(db, account["ledger_id"])
    try:
        db.set_trainee_email(account["account_id"], normalized)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "trainee_id": account["ledger_id"], "email": normalized}


def request_password_reset(
    db: Any,
    email: str,
    mailer: Callable[[str, str], bool] | None = None,
    token_factory: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Logged-out: issue a single-use reset token. Always returns the generic message."""
    normalized = normalize_email(email)
    recovery_key = db.get_trainee_by_email(normalized) if normalized else None
    account = _live_player_account(db, recovery_key) if recovery_key else None
    if account is None:
        return {"ok": True, "message": GENERIC_REQUEST_MESSAGE}
    raw_token = token_factory() if token_factory else secrets.token_urlsafe(32)
    expires_at = (datetime.now(UTC) + reset_ttl()).isoformat()
    try:
        db.store_reset_token(_hash_token(raw_token), account["account_id"], expires_at)
    except Exception:
        logger.exception("Failed to store password-reset token for %s", account["account_id"])
        return {"ok": True, "message": GENERIC_REQUEST_MESSAGE}
    sender = mailer or send_password_reset_email
    try:
        sender(normalized or "", build_reset_link(raw_token))
    except Exception:
        logger.exception("Password-reset mailer failed for %s", account["account_id"])
    db.prune_reset_tokens(datetime.now(UTC).isoformat())
    return {"ok": True, "message": GENERIC_REQUEST_MESSAGE}


def reset_password_with_token(db: Any, token: str, new_password: str) -> dict[str, Any]:
    """Logged-out: redeem a reset token for a new password. Revokes all sessions."""
    if not isinstance(token, str) or not (10 <= len(token) <= 128):
        return {"ok": False, "error": GENERIC_TOKEN_ERROR}
    try:
        auth_service.validate_password(new_password)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "code": "weak_new"}
    now_iso = datetime.now(UTC).isoformat()
    recovery_key = db.consume_reset_token(_hash_token(token), now_iso)
    if recovery_key is None:
        return {"ok": False, "error": GENERIC_TOKEN_ERROR}
    account = _live_player_account(db, recovery_key)
    if account is None or not db.user_exists(account["ledger_id"]):
        return {"ok": False, "error": GENERIC_TOKEN_ERROR}
    bind_user(db, account["ledger_id"])
    db.set_password_hash(auth_service.hash_password(new_password))
    db.bump_account_session_epoch(account["account_id"])
    db.prune_reset_tokens(now_iso)
    return {"ok": True, "trainee_id": account["ledger_id"]}
