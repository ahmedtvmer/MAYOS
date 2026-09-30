"""Customer proof-based and owner-initiated durable account deletion (ADR 015/039).

The account holder proves possession — with their password, or with a fresh
Google ID token whose linked subject is their own (#114) — then the account is
durably deleted: every session invalidated in the registry, the live ledger and
its backups removed, the ``linked_sign_ins`` rows dropped in the same catalog
transaction (so that Google account can later create a new MAYOS account), and a
record kept outside the catalog snapshot so a restored backup cannot resurrect
the identity. The caller is JWT-authenticated, so a wrong password or a
stale/wrong-sub/unverifiable token is reported plainly (400-class) and changes
nothing; route layers must NOT map it to 401 or clients will treat it as session
expiry.

Every refusal — unknown or non-live account, non-player account, a ledger with
no password hash (imported-but-unclaimed, ADR 045), a non-string password, a
wrong password, or a Google identity that fails any part of its check — returns
the same generic ``Invalid credentials.`` (#43, #114), and the password path
spends exactly one bcrypt verification, so neither the in-app path nor the
public web form leaks "does this account exist?" through timing.

The owner dashboard instead requires a live owner session, CSRF, the exact
username, a fresh step-up TOTP code, and a privacy-checked reason. It uses the
same database deletion routine and records accepted and rejected attempts in
the owner audit log.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from service import audit_log, email_sender
from service._base import ledger_scope
from service.auth import INVALID_CREDENTIALS, hash_password, verify_password
from service.google_sign_in import PROVIDER

logger = logging.getLogger(__name__)

#: The Google proof must be this fresh: ``iat`` within the last 5 minutes (#114).
GOOGLE_TOKEN_MAX_AGE_SECONDS = 5 * 60
#: Clock drift between the app server and Google before a token is "from the future".
GOOGLE_IAT_FUTURE_SKEW_SECONDS = 10

# Lazily built so importing this module stays cheap; one bcrypt verification is
# spent against it for every refusal that has no stored hash to compare with.
_UNKNOWN_ACCOUNT_HASH: str | None = None


@dataclass(frozen=True)
class OwnerDeleteRequest:
    account_id: str
    actor: str
    reason: str
    source_ip: str | None
    username_confirmation: str
    totp_code: str


class StepUpResult(str, Enum):
    SUCCESS = "success"
    REJECTED = "rejected"
    LOCKED_OUT = "locked_out"
    LOCKOUT_STARTED = "lockout_started"


def _spend_one_bcrypt(password: Any) -> None:
    """Burns exactly one bcrypt verification for a refusal with no stored hash.

    The password is coerced to ``""`` when it is not a string, so a caller that
    skipped validation (the public deletion form) costs the same as a wrong
    password instead of skipping the work and answering faster.
    """
    global _UNKNOWN_ACCOUNT_HASH
    if _UNKNOWN_ACCOUNT_HASH is None:
        _UNKNOWN_ACCOUNT_HASH = hash_password("mayos-unknown-account-equalizer")
    verify_password(password if isinstance(password, str) else "", _UNKNOWN_ACCOUNT_HASH)


def delete_account(
    db: Any,
    account_id: str,
    password: Any = None,
    *,
    google_identity: Any | None = None,
    ledger: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verifies one proof and deletes the account and its active data.

    The proof is either ``password`` or ``google_identity`` — the ``sub``/``iat``
    of an ID token the route already verified against Google (:func:`_google_identity_deletes`)
    — never both. Both paths answer with the same generic ``Invalid credentials.``
    on failure, so the endpoint cannot be used to tell a wrong password from a
    stale or foreign Google token.

    ``account_id`` is the immutable id verified from the caller's JWT, never the
    reusable username, so a request that raced a deletion and username reuse can
    never delete the new account that inherited the name.
    """
    if password is not None and google_identity is not None:
        raise ValueError("Deletion accepts one proof at a time: password or google_identity.")
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_player"]:
        if password is not None:
            _spend_one_bcrypt(password)
        return {"ok": False, "error": INVALID_CREDENTIALS}

    if google_identity is None:
        with ledger_scope(db, ledger, account["ledger_id"]) as ledger:
            stored = ledger.get_password_hash()
            if stored is None:
                _spend_one_bcrypt(password)
                return {"ok": False, "error": INVALID_CREDENTIALS}
            if not verify_password(password if isinstance(password, str) else "", stored):
                return {"ok": False, "error": INVALID_CREDENTIALS}
    elif not _google_identity_deletes(db, account_id, google_identity, now):
        return {"ok": False, "error": INVALID_CREDENTIALS}

    db.delete_account(account["account_id"], datetime.now(UTC).isoformat(), ledger_id=account["ledger_id"])
    return {"ok": True, "account_id": account["account_id"], "trainee_id": account["ledger_id"]}


def owner_delete_account(
    db: Any,
    request: OwnerDeleteRequest,
    verify_step_up: Callable[[str], StepUpResult],
    mailer: Callable[[str, str], bool] | None = None,
) -> dict[str, Any]:
    """Deletes any live account after owner step-up and records the outcome.

    The username, reason, and TOTP checks happen before any deletion record is written.
    The notice uses the recovery address captured here, after the durable
    deletion record is appended but before ADR 039 clears recovery identity.
    """
    account = db.get_account(request.account_id)
    if not db.is_live_account(account):
        return {"outcome": "not_found"}
    error = _owner_delete_request_error(account, request, verify_step_up)
    if error:
        if error == "lockout_started":
            _write_owner_delete_audit(
                db,
                audit_log.AuditEvent(
                    actor=request.actor,
                    action="login_locked_out",
                    source_ip=request.source_ip,
                ),
            )
        _owner_delete_rejected(db, request)
        if error == "lockout_started":
            error = "confirmation_failed"
        return {"outcome": "rejected", "error": error}
    return _apply_owner_delete(db, account, request, mailer)


def _owner_delete_request_error(
    account: dict[str, Any],
    request: OwnerDeleteRequest,
    verify_step_up: Callable[[str], StepUpResult],
) -> str | None:
    if request.username_confirmation != account["username"]:
        return "confirmation_failed"
    if not request.reason.strip():
        return "reason_required"
    try:
        audit_log.validate_audit_reason(request.reason)
    except ValueError:
        return "reason_invalid"
    step_up_result = verify_step_up(request.totp_code)
    if step_up_result is not StepUpResult.SUCCESS:
        return "lockout_started" if step_up_result is StepUpResult.LOCKOUT_STARTED else "confirmation_failed"
    return None


def _apply_owner_delete(
    db: Any,
    account: dict[str, Any],
    request: OwnerDeleteRequest,
    mailer: Callable[[str, str], bool] | None,
) -> dict[str, Any]:
    recovery_email = db.get_account_email(request.account_id)
    deleted_at = datetime.now(UTC).isoformat()
    db.record_account_deletion(request.account_id, account["ledger_id"], deleted_at)
    email_failed = False
    if recovery_email:
        email_failed = _send_owner_deletion_notice(recovery_email, account["username"], mailer)
    try:
        deletion = db.delete_account(request.account_id, deleted_at, ledger_id=account["ledger_id"])
    except Exception as exc:
        logger.error("Owner account deletion is pending replay (%s)", type(exc).__name__)
        _write_owner_delete_audit(
            db,
            audit_log.AuditEvent(
                actor=request.actor,
                action="account_delete_pending",
                target_account_id=request.account_id,
                source_ip=request.source_ip,
                reason=request.reason.strip(),
            ),
        )
        if email_failed:
            _write_owner_delete_audit(
                db,
                audit_log.AuditEvent(
                    actor=request.actor,
                    action="account_deleted_email_failed",
                    target_account_id=request.account_id,
                    source_ip=request.source_ip,
                ),
            )
        return {"outcome": "pending", "account_id": request.account_id}
    if not deletion.get("ok"):
        return {"outcome": "not_found"}
    _audit_owner_deletion(db, request, email_failed)
    return {"outcome": "deleted", "account_id": request.account_id}


def _send_owner_deletion_notice(
    recovery_email: str,
    username: str,
    mailer: Callable[[str, str], bool] | None,
) -> bool:
    sender = mailer or email_sender.send_account_deleted_email
    try:
        return not sender(recovery_email, username)
    except Exception as exc:
        logger.error("Owner account deletion notice delivery failed (%s)", type(exc).__name__)
        return True


def _audit_owner_deletion(db: Any, request: OwnerDeleteRequest, email_failed: bool) -> None:
    _write_owner_delete_audit(
        db,
        audit_log.AuditEvent(
            actor=request.actor,
            action="account_deleted",
            target_account_id=request.account_id,
            source_ip=request.source_ip,
            reason=request.reason.strip(),
        ),
    )
    if email_failed:
        _write_owner_delete_audit(
            db,
            audit_log.AuditEvent(
                actor=request.actor,
                action="account_deleted_email_failed",
                target_account_id=request.account_id,
                source_ip=request.source_ip,
            ),
        )


def _owner_delete_rejected(db: Any, request: OwnerDeleteRequest) -> None:
    _write_owner_delete_audit(
        db,
        audit_log.AuditEvent(
            actor=request.actor,
            action="account_delete_rejected",
            target_account_id=request.account_id,
            source_ip=request.source_ip,
        ),
    )


def _write_owner_delete_audit(db: Any, event: audit_log.AuditEvent) -> None:
    try:
        audit_log.write_audit_entry(db, event)
    except Exception as exc:
        logger.error("Owner account deletion audit write failed (%s)", type(exc).__name__)


def _google_identity_deletes(db: Any, account_id: str, identity: Any, now: datetime | None = None) -> bool:
    """True when a verified Google identity proves possession of *this* account.

    Every condition must hold: the token's ``sub`` is linked to the caller
    (never merely to any account), and its ``iat`` is within the last
    :data:`GOOGLE_TOKEN_MAX_AGE_SECONDS`, so a stale or replayed ID token is
    refused exactly like a wrong password. Each failure collapses to the same
    ``False``, so nothing here reveals whether the subject is linked, whose it
    is, or that the token was merely old.
    """
    sub = getattr(identity, "sub", None)
    iat = getattr(identity, "iat", None)
    if not isinstance(sub, str) or not sub:
        return False
    if isinstance(iat, bool) or not isinstance(iat, int):
        return False
    age = (now or datetime.now(UTC)).timestamp() - float(iat)
    if age < -GOOGLE_IAT_FUTURE_SKEW_SECONDS or age > GOOGLE_TOKEN_MAX_AGE_SECONDS:
        return False
    return db.get_linked_sign_in_account_id(PROVIDER, sub) == account_id


def delete_account_by_username(db: Any, username: Any, password: Any) -> dict[str, Any]:
    """External deletion-request path: resolve the reusable username, then delete.

    The username is normalised exactly as ``service.auth.login_player`` does it
    (``db._sanitize_username`` plus the live-ledger check), so a form submission
    and a login agree on which account is meant. The deletion and its password
    confirmation are then the same code the in-app ``DELETE /auth/account`` runs
    (ADR 015/039); only the way the caller identifies the account differs,
    because a browser form has no session. Every failure returns the same
    ``INVALID_CREDENTIALS`` shape and spends one bcrypt verification, so the
    form can never reveal whether an account exists (#43).
    """
    clean_id = db._sanitize_username(username if isinstance(username, str) else "")
    account = db.get_active_account_by_username(clean_id) if clean_id else None
    if account is None or not account["is_player"] or not db.ledger_exists(account["ledger_id"]):
        _spend_one_bcrypt(password)
        return {"ok": False, "error": INVALID_CREDENTIALS}
    return delete_account(db, account["account_id"], password)
