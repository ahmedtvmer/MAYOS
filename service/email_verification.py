"""Shared catalog-backed codes for verifying account email addresses."""

import hashlib
import hmac
import os
import re
import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from database.registry.recovery import (
    EmailVerificationCheck,
    EmailVerificationIdentity,
    EmailVerificationIssue,
    RECOVERY_EMAIL_CHANGE_PURPOSE,
    RECOVERY_EMAIL_VERIFICATION_PURPOSE,
)
from service.email_hash_keys import derive_email_hash_key

CODE_LENGTH = 6
CODE_PURPOSE_RECOVERY_EMAIL = RECOVERY_EMAIL_VERIFICATION_PURPOSE
CODE_PURPOSE_RECOVERY_EMAIL_CHANGE = RECOVERY_EMAIL_CHANGE_PURPOSE
GENERIC_CODE_ERROR = "Invalid or expired verification code."
_CODE_RE = re.compile(r"^[0-9]{6}$")


def verification_code_ttl() -> timedelta:
    """Returns the configured short lifetime, bounded to five minutes through one hour."""
    try:
        minutes = int(os.getenv("EMAIL_VERIFICATION_CODE_TTL_MINUTES", "10"))
    except ValueError:
        minutes = 10
    return timedelta(minutes=max(5, min(minutes, 60)))


def _address_hash(address: str) -> str:
    return hmac.new(
        derive_email_hash_key("verification-address"),
        address.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _code_hash(account_id: str, address_hash: str, purpose: str, code: str) -> str:
    value = "\0".join((account_id, address_hash, purpose, code)).encode("utf-8")
    return hmac.new(
        derive_email_hash_key(f"verification-code:{purpose}"), value, hashlib.sha256
    ).hexdigest()


def issue_code(
    db: Any,
    identity: EmailVerificationIdentity,
    display_language: str,
    mailer: Callable[[str, str, str], bool],
) -> bool:
    """Issues one address-bound code, invalidating prior unused codes of its purpose."""
    normalized = identity.address.strip().lower()
    if not normalized:
        return False
    code = f"{secrets.randbelow(10**CODE_LENGTH):06d}"
    issue = _create_issue(identity, normalized, code)
    if not db._store_email_verification_code(issue):
        return False
    return mailer(normalized, code, display_language)


def _create_issue(
    identity: EmailVerificationIdentity, address: str, code: str
) -> EmailVerificationIssue:
    issued_at = datetime.now(UTC)
    hashed_address = _address_hash(address)
    return EmailVerificationIssue(
        identity=EmailVerificationIdentity(identity.account_id, address, identity.purpose),
        code_hash=_code_hash(identity.account_id, hashed_address, identity.purpose, code),
        address_hash=hashed_address,
        expires_at=(issued_at + verification_code_ttl()).isoformat(),
        created_at=issued_at.isoformat(),
        rolling_cutoff=(issued_at - timedelta(hours=1)).isoformat(),
    )


def verify_code(
    db: Any,
    identity: EmailVerificationIdentity,
    code: str,
    *,
    mark_recovery_email: bool = False,
) -> bool:
    """Consumes a matching, unexpired code once; every refusal is the same false result."""
    check = _verification_check(identity, code)
    if check is None:
        return False
    return db._consume_email_verification_code(
        replace(check, mark_recovery_email=mark_recovery_email)
    )


def verify_code_and_get_previous_address(
    db: Any,
    identity: EmailVerificationIdentity,
    code: str,
) -> str | None:
    """Consumes a change code and returns its replaced address from the same transaction."""
    check = _verification_check(identity, code)
    if check is None:
        return None
    verified, previous_address = db._consume_email_verification_code_with_previous_address(
        check
    )
    return previous_address if verified else None


def _verification_check(
    identity: EmailVerificationIdentity, code: str
) -> EmailVerificationCheck | None:
    if not isinstance(code, str) or not _CODE_RE.fullmatch(code):
        return None
    normalized = identity.address.strip().lower()
    if not normalized:
        return None
    checked_at = datetime.now(UTC).isoformat()
    hashed_address = _address_hash(normalized)
    return EmailVerificationCheck(
        identity=EmailVerificationIdentity(identity.account_id, normalized, identity.purpose),
        code_hash=_code_hash(identity.account_id, hashed_address, identity.purpose, code),
        address_hash=hashed_address,
        checked_at=checked_at,
        mark_recovery_email=False,
    )
