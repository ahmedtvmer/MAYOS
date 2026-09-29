"""Player registration, login, and opt-in claim. Returns plain dicts; no session state.

Proof level is password possession. Unknown users and wrong passwords are
indistinguishable (``Invalid credentials.``); only registration reveals
ID-taken, which is inherent to signup. Claiming an imported account requires the
owner-issued single-use claim code, and every claim failure shares one generic
error.
"""

from datetime import UTC, datetime
from typing import Any

import bcrypt

from service._base import ledger_scope
from service._tokens import hash_token

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
INVALID_CREDENTIALS = "Invalid credentials."
INVALID_CLAIM = "Invalid or expired claim code."


def validate_password(password: Any) -> str:
    if not isinstance(password, str) or not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError(f"Password must be {MIN_PASSWORD_LENGTH}–{MAX_PASSWORD_LENGTH} characters.")
    return password


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def register_player(db: Any, username: str, password: str) -> dict[str, Any]:
    """Creates an immutable account identity plus its ledger.

    A username that already has a live account, or an unenrolled local ledger,
    is refused so existing local ledgers are never silently adopted (issue #42
    owns opted-in import).
    """
    clean_id = db._sanitize_username(username)
    if not clean_id:
        return {"ok": False, "error": "Trainee ID is empty after sanitization."}
    if db.get_active_account_by_username(clean_id) is not None or db.ledger_exists(clean_id):
        return {"ok": False, "error": "This Trainee ID already exists. Please log in."}
    try:
        validate_password(password)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    account_id = db.create_account(clean_id)
    if account_id is None:
        return {"ok": False, "error": "This Trainee ID already exists. Please log in."}
    account = db.get_account(account_id) or {}
    # A reused username gets a fresh ledger id (see DatabaseManager.create_account),
    # so always mount the account's own ledger rather than the username.
    ledger_id = account.get("ledger_id") or clean_id
    with db.open_ledger(ledger_id) as ledger:
        ledger.set_password_hash(hash_password(password))
    account = db.get_account(account_id) or account
    return {
        "ok": True,
        "trainee_id": ledger_id,
        "account_id": account_id,
        "session_epoch": account.get("session_epoch", 1),
    }


def login_player(db: Any, username: str, password: str) -> dict[str, Any]:
    clean_id = db._sanitize_username(username)
    account = db.get_active_account_by_username(clean_id) if clean_id else None
    if account is None or not db.ledger_exists(account["ledger_id"]):
        return {"ok": False, "error": INVALID_CREDENTIALS}
    with db.open_ledger(account["ledger_id"]) as ledger:
        stored = ledger.get_password_hash()
        if stored is None:
            # A Linked sign-in account has no password to set or claim (#113):
            # it answers exactly like a wrong password, never claim_required.
            if db.account_has_linked_sign_in(account["account_id"]):
                return {"ok": False, "error": INVALID_CREDENTIALS}
            return {"ok": False, "error": INVALID_CREDENTIALS, "code": "claim_required"}
        if not isinstance(password, str) or not verify_password(password, stored):
            return {"ok": False, "error": INVALID_CREDENTIALS}
        profile = ledger.get_player_profile()
        return {
            "ok": True,
            "trainee_id": account["ledger_id"],
            "account_id": account["account_id"],
            "session_epoch": account["session_epoch"],
            "has_profile": bool(profile),
            "profile": profile,
            "active_program": ledger.get_active_program() if profile else None,
        }


def claim_player(db: Any, username: str, claim_code: str, password: str) -> dict[str, Any]:
    """One-time password claim for an imported account whose ledger has no password.

    Requires the owner-issued, account-bound, single-use, expiring claim code
    (ADR 019). Only an enrolled live player account with a password-less ledger
    can be claimed; a bare local ledger is refused so it is never silently
    adopted into a cloud account. Every failure — unknown account, wrong/expired/
    reused code, already-claimed ledger — returns one generic error so the
    endpoint cannot be used to enumerate accounts or probe claim state.
    """
    generic = {"ok": False, "error": INVALID_CLAIM}
    clean_id = db._sanitize_username(username)
    if not clean_id or not isinstance(claim_code, str) or not claim_code:
        return generic
    try:
        validate_password(password)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "code": "weak_new"}
    account = db.get_active_account_by_username(clean_id)
    if account is None or not account["is_player"] or not db.ledger_exists(account["ledger_id"]):
        return generic
    if db.account_has_linked_sign_in(account["account_id"]):
        # An account that signs in with a Linked sign-in never takes a password
        # this way (issue #113). The refusal is this endpoint's own generic
        # claim error — never login's "Invalid credentials." — so /auth/claim
        # still answers identically for every failure and cannot be used to
        # discover that an account is Google-linked.
        return generic
    now_iso = datetime.now(UTC).isoformat()
    with db.open_ledger(account["ledger_id"]) as ledger:
        if ledger.get_password_hash() is not None:
            return generic
        if not db.consume_claim_code(hash_token(claim_code), account["account_id"], now_iso):
            return generic
        ledger.set_password_hash(hash_password(password))
    return {
        "ok": True,
        "trainee_id": account["ledger_id"],
        "account_id": account["account_id"],
        "session_epoch": account["session_epoch"],
    }


def change_password(
    db: Any, account_id: str, current_password: str, new_password: str, ledger: Any | None = None
) -> dict[str, Any]:
    """Authenticated password change. Revokes all sessions via the registry epoch.

    ``account_id`` is the immutable id verified from the caller's JWT, never a
    reusable username: resolving by id means a request that raced a delete and
    username reuse cannot touch the new account that inherited the name. The
    account must still be a live player whose ledger exists.

    The caller is already JWT-authenticated, so a wrong current password is
    reported plainly (400-class ``error``); route layers must NOT map this to
    401 or clients will treat it as session expiry.
    """
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_player"] or not db.ledger_exists(account["ledger_id"]):
        return {"ok": False, "error": "Trainee ledger not found."}
    with ledger_scope(db, ledger, account["ledger_id"]) as handle:
        stored = handle.get_password_hash()
        if stored is None:
            return {"ok": False, "error": "No password set yet. Claim this ledger first.", "code": "claim_required"}
        if not isinstance(current_password, str) or not verify_password(current_password, stored):
            return {"ok": False, "error": "Current password is incorrect.", "code": "bad_current"}
        try:
            validate_password(new_password)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "code": "weak_new"}
        if verify_password(new_password, stored):
            return {"ok": False, "error": "New password must differ from the current one.", "code": "same_as_current"}
        handle.set_password_hash(hash_password(new_password))
    new_version = db.bump_account_session_epoch(account["account_id"])
    return {
        "ok": True,
        "trainee_id": account["ledger_id"],
        "account_id": account["account_id"],
        "token_version": new_version,
    }
