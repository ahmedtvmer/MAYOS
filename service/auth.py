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
    clean_id = db._sanitize_username(trainee_id)
    if not clean_id:
        return {"ok": False, "error": "Trainee ID is empty after sanitization."}
    if db.user_exists(clean_id):
        return {"ok": False, "error": "This Trainee ID already exists. Please log in."}
    try:
        validate_password(password)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    bind_user(db, clean_id)
    db.set_password_hash(hash_password(password))
    return {"ok": True, "trainee_id": clean_id}


def login_trainee(db: Any, trainee_id: str, password: str) -> dict[str, Any]:
    clean_id = db._sanitize_username(trainee_id)
    if not clean_id or not db.user_exists(clean_id):
        return {"ok": False, "error": INVALID_CREDENTIALS}
    bind_user(db, clean_id)
    stored = db.get_password_hash()
    if stored is None:
        return {"ok": False, "error": INVALID_CREDENTIALS, "code": "claim_required"}
    if not isinstance(password, str) or not verify_password(password, stored):
        return {"ok": False, "error": INVALID_CREDENTIALS}
    profile = db.get_user_profile()
    return {
        "ok": True,
        "trainee_id": clean_id,
        "has_profile": bool(profile),
        "profile": profile,
        "active_program": db.get_active_program() if profile else None,
    }


def claim_trainee(db: Any, trainee_id: str, password: str) -> dict[str, Any]:
    """One-time password claim for pre-password ledgers. Single-use per ledger."""
    clean_id = db._sanitize_username(trainee_id)
    if not clean_id or not db.user_exists(clean_id):
        return {"ok": False, "error": INVALID_CREDENTIALS}
    try:
        validate_password(password)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    bind_user(db, clean_id)
    if db.get_password_hash() is not None:
        return {"ok": False, "error": INVALID_CREDENTIALS}
    db.set_password_hash(hash_password(password))
    return {"ok": True, "trainee_id": clean_id}
