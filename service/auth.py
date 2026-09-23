"""Trainee registration, login, and legacy-claim. Returns plain dicts; no session state.

Proof level is password possession. Unknown users and wrong passwords are
indistinguishable (``Invalid credentials.``); only registration reveals
ID-taken, which is inherent to signup.
"""

from typing import Any

import bcrypt

from service._base import bind_user

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
INVALID_CREDENTIALS = "Invalid credentials."


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


def register_trainee(db: Any, trainee_id: str, password: str) -> dict[str, Any]:
    """Creates an immutable account identity plus its ledger.

    A username that already has a live account, or an unenrolled local ledger,
    is refused so existing local ledgers are never silently adopted (issue #42
    owns opted-in import).
    """
    clean_id = db._sanitize_username(trainee_id)
    if not clean_id:
        return {"ok": False, "error": "Trainee ID is empty after sanitization."}
    if db.get_active_account_by_username(clean_id) is not None or db.user_exists(clean_id):
        return {"ok": False, "error": "This Trainee ID already exists. Please log in."}
    try:
        validate_password(password)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    account_id = db.create_account(clean_id)
    if account_id is None:
        return {"ok": False, "error": "This Trainee ID already exists. Please log in."}
    bind_user(db, clean_id)
    db.set_password_hash(hash_password(password))
    account = db.get_account(account_id) or {}
    return {
        "ok": True,
        "trainee_id": clean_id,
        "account_id": account_id,
        "session_epoch": account.get("session_epoch", 1),
    }


def login_trainee(db: Any, trainee_id: str, password: str) -> dict[str, Any]:
    clean_id = db._sanitize_username(trainee_id)
    account = db.get_active_account_by_username(clean_id) if clean_id else None
    if account is None or not db.user_exists(account["ledger_id"]):
        return {"ok": False, "error": INVALID_CREDENTIALS}
    bind_user(db, account["ledger_id"])
    stored = db.get_password_hash()
    if stored is None:
        return {"ok": False, "error": INVALID_CREDENTIALS, "code": "claim_required"}
    if not isinstance(password, str) or not verify_password(password, stored):
        return {"ok": False, "error": INVALID_CREDENTIALS}
    profile = db.get_user_profile()
    return {
        "ok": True,
        "trainee_id": account["ledger_id"],
        "account_id": account["account_id"],
        "session_epoch": account["session_epoch"],
        "has_profile": bool(profile),
        "profile": profile,
        "active_program": db.get_active_program() if profile else None,
    }


def claim_trainee(db: Any, trainee_id: str, password: str) -> dict[str, Any]:
    """One-time password claim for an account whose ledger has no password yet.

    Only an enrolled account can be claimed; a bare local ledger is refused so
    it is never silently adopted into a cloud account.
    """
    clean_id = db._sanitize_username(trainee_id)
    account = db.get_active_account_by_username(clean_id) if clean_id else None
    if account is None or not db.user_exists(account["ledger_id"]):
        return {"ok": False, "error": INVALID_CREDENTIALS}
    try:
        validate_password(password)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    bind_user(db, account["ledger_id"])
    if db.get_password_hash() is not None:
        return {"ok": False, "error": INVALID_CREDENTIALS}
    db.set_password_hash(hash_password(password))
    return {
        "ok": True,
        "trainee_id": account["ledger_id"],
        "account_id": account["account_id"],
        "session_epoch": account["session_epoch"],
    }


def change_password(db: Any, account_id: str, current_password: str, new_password: str) -> dict[str, Any]:
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
    if not db.is_live_account(account) or not account["is_player"] or not db.user_exists(account["ledger_id"]):
        return {"ok": False, "error": "Trainee ledger not found."}
    bind_user(db, account["ledger_id"])
    stored = db.get_password_hash()
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
    db.set_password_hash(hash_password(new_password))
    new_version = db.bump_account_session_epoch(account["account_id"])
    return {
        "ok": True,
        "trainee_id": account["ledger_id"],
        "account_id": account["account_id"],
        "token_version": new_version,
    }
