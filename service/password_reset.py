"""Self-service account recovery: emails + single-use reset tokens.

Anti-enumeration contract: ``request_password_reset`` returns the same generic
result whether or not the email is linked, and ``reset_password_with_token``
uses one generic message for unknown/expired/used tokens. Route layers must
preserve this (same status code and body shape for both cases).
"""

import logging
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from service import audit_log, auth as auth_service
from service._tokens import hash_token
from service.email_sender import build_reset_link, send_password_reset_email

logger = logging.getLogger(__name__)

GENERIC_REQUEST_MESSAGE = "If this email is linked to a ledger, a reset link is on its way."
GENERIC_TOKEN_ERROR = "Invalid or expired reset code."
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class OwnerPasswordError(Exception):
    """A password-set request the owner CLI can report to its operator."""


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


def admin_reset_link_ttl() -> timedelta:
    try:
        minutes = int(os.getenv("ADMIN_RESET_LINK_TTL_MINUTES", "1440"))
    except ValueError:
        minutes = 1440
    return timedelta(minutes=max(5, min(minutes, 10080)))


def _new_reset_token(db: Any, account_id: str, ttl: timedelta) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + ttl
    raw_token = secrets.token_urlsafe(32)
    db.store_reset_token(hash_token(raw_token), account_id, expires_at.isoformat())
    return raw_token, expires_at


def _live_reset_account(db: Any, account_id: str) -> dict[str, Any] | None:
    account = _live_player_account(db, account_id)
    if account is None or not db.ledger_exists(account["ledger_id"]):
        return None
    return account


def _write_owner_reset_audit(db: Any, event: audit_log.AuditEvent) -> None:
    try:
        audit_log.write_audit_entry(db, event)
    except Exception:
        logger.error("Owner password-reset audit write failed")


def _deliver_owner_reset_email(email: str, raw_token: str) -> bool:
    try:
        return send_password_reset_email(email, build_reset_link(raw_token))
    except Exception:
        logger.exception("Owner password-reset email delivery failed")
        return False


def owner_send_reset_email(db: Any, account_id: str, actor: str, source_ip: str | None) -> dict[str, str]:
    account = _live_reset_account(db, account_id)
    if account is None:
        return {"outcome": "not_found"}
    email = normalize_email(db.get_account_email(account_id))
    if email is None:
        return {"outcome": "no_recovery_email"}

    try:
        raw_token, _ = _new_reset_token(db, account_id, reset_ttl())
    except Exception:
        logger.error("Owner password-reset token storage failed")
        _write_owner_reset_audit(
            db,
            audit_log.AuditEvent(
                actor=actor,
                action="reset_email_failed",
                target_account_id=account_id,
                source_ip=source_ip,
            ),
        )
        return {"outcome": "send_failed"}
    db.prune_reset_tokens(datetime.now(UTC).isoformat())
    delivered = _deliver_owner_reset_email(email, raw_token)
    action = "reset_email_sent" if delivered else "reset_email_failed"
    _write_owner_reset_audit(
        db,
        audit_log.AuditEvent(actor=actor, action=action, target_account_id=account_id, source_ip=source_ip),
    )
    return {"outcome": "sent" if delivered else "send_failed"}


def owner_issue_reset_link(db: Any, account_id: str, actor: str, source_ip: str | None) -> dict[str, str]:
    if _live_reset_account(db, account_id) is None:
        return {"outcome": "not_found"}
    now = datetime.now(UTC)
    expires_at = now + admin_reset_link_ttl()
    raw_token = secrets.token_urlsafe(32)
    with db.catalog_transaction():
        db.invalidate_unused_reset_tokens(account_id, now.isoformat())
        db.store_reset_token(hash_token(raw_token), account_id, expires_at.isoformat())
    db.prune_reset_tokens(now.isoformat())
    _write_owner_reset_audit(
        db,
        audit_log.AuditEvent(
            actor=actor,
            action="reset_link_issued",
            target_account_id=account_id,
            source_ip=source_ip,
        ),
    )
    return {
        "outcome": "issued",
        "link": build_reset_link(raw_token),
        "expires_at": expires_at.isoformat(),
    }


def owner_set_password(
    db: Any,
    username_or_ledger_id: str,
    new_password: str,
    actor: str,
) -> tuple[str, int, bool]:
    ledger_id, epoch, enrolled, account_id = _set_owner_password(db, username_or_ledger_id, new_password)
    _write_owner_reset_audit(
        db,
        audit_log.AuditEvent(actor=actor, action="password_set_by_owner", target_account_id=account_id),
    )
    return ledger_id, epoch, enrolled


def _write_and_revoke_owner_password(db: Any, ledger_id: str, new_password: str, account: dict[str, Any] | None) -> int:
    with db.open_ledger(ledger_id) as ledger:
        ledger.set_password_hash(auth_service.hash_password(new_password))
        ledger_epoch = ledger.bump_token_version()
        if account is None:
            epoch = ledger_epoch
        else:
            epoch = db.bump_account_session_epoch(account["account_id"])
            if epoch is None:
                raise OwnerPasswordError("error: could not advance the account registry epoch; sessions were NOT revoked.")
        ledger.prune_revoked_tokens(datetime.now(UTC).isoformat())
    return epoch


def _set_owner_password(
    db: Any,
    username_or_ledger_id: str,
    new_password: str,
) -> tuple[str, int, bool, str | None]:
    clean_id = db._sanitize_username(username_or_ledger_id)
    if not clean_id:
        raise OwnerPasswordError(f"error: unknown trainee ledger '{username_or_ledger_id}'.")
    account = db.get_active_account_by_username(clean_id)
    if account is None:
        account = db.get_account_by_ledger_id(clean_id)
    ledger_id = account["ledger_id"] if account is not None else clean_id
    if not db.ledger_exists(ledger_id):
        raise OwnerPasswordError(f"error: unknown trainee ledger '{ledger_id}'.")
    try:
        auth_service.validate_password(new_password)
    except ValueError as exc:
        raise OwnerPasswordError(f"error: {exc}") from exc
    epoch = _write_and_revoke_owner_password(db, ledger_id, new_password, account)
    return ledger_id, epoch, account is not None, account["account_id"] if account else None


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
    if not db.is_live_account(account) or not account["is_player"] or not db.ledger_exists(account["ledger_id"]):
        return None
    return db.get_account_email(account["account_id"])


def set_recovery_email(db: Any, account_id: str, email: str) -> dict[str, Any]:
    """Authenticated: link (or replace) the recovery email for the caller's account.

    Resolves the immutable ``account_id`` from the verified JWT and refuses a
    deleted or non-player account, so a stale request cannot rebind a reused
    username's new account.
    """
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_player"] or not db.ledger_exists(account["ledger_id"]):
        return {"ok": False, "error": "Trainee ledger not found."}
    normalized = normalize_email(email)
    if normalized is None:
        return {"ok": False, "error": "Enter a valid email address."}
    try:
        db.set_account_email(account["account_id"], normalized)
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
    recovery_key = db.get_account_by_email(normalized) if normalized else None
    account = _live_player_account(db, recovery_key) if recovery_key else None
    if account is None:
        return {"ok": True, "message": GENERIC_REQUEST_MESSAGE}
    try:
        if token_factory is None:
            raw_token, _ = _new_reset_token(db, account["account_id"], reset_ttl())
        else:
            raw_token = token_factory()
            expires_at = (datetime.now(UTC) + reset_ttl()).isoformat()
            db.store_reset_token(hash_token(raw_token), account["account_id"], expires_at)
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
    recovery_key = db.consume_reset_token(hash_token(token), now_iso)
    if recovery_key is None:
        return {"ok": False, "error": GENERIC_TOKEN_ERROR}
    account = _live_player_account(db, recovery_key)
    if account is None or not db.ledger_exists(account["ledger_id"]):
        return {"ok": False, "error": GENERIC_TOKEN_ERROR}
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.set_password_hash(auth_service.hash_password(new_password))
    db.bump_account_session_epoch(account["account_id"])
    db.prune_reset_tokens(now_iso)
    return {"ok": True, "trainee_id": account["ledger_id"]}
