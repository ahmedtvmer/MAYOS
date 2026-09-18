"""Trainee registration and login. Returns plain dicts; no session state."""

from typing import Any

from service._base import bind_user


def register_trainee(db: Any, trainee_id: str) -> dict[str, Any]:
    clean_id = db._sanitize_username(trainee_id)
    if not clean_id:
        return {"ok": False, "error": "Trainee ID is empty after sanitization."}
    if db.user_exists(clean_id):
        return {"ok": False, "error": "This Trainee ID already exists. Please log in."}
    bind_user(db, clean_id)
    return {"ok": True, "trainee_id": clean_id}


def login_trainee(db: Any, trainee_id: str) -> dict[str, Any]:
    clean_id = db._sanitize_username(trainee_id)
    if not clean_id or not db.user_exists(clean_id):
        return {"ok": False, "error": "Trainee ID not found. Verify spelling or create a new profile."}
    bind_user(db, clean_id)
    profile = db.get_user_profile()
    return {
        "ok": True,
        "trainee_id": clean_id,
        "has_profile": bool(profile),
        "profile": profile,
        "active_program": db.get_active_program() if profile else None,
    }
