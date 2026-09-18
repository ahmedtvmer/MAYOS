"""Profile and coach-persona operations."""

from typing import Any

from agent.program_generator import generate_program_pipeline
from service._base import bind_user


def get_profile(db: Any, trainee_id: str) -> dict[str, Any] | None:
    bind_user(db, trainee_id)
    return db.get_user_profile()


def update_profile(db: Any, trainee_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Upserts the profile; rebuilds the routine when frequency/rep-bias/limits change."""
    bind_user(db, trainee_id)
    profile = db.get_user_profile() or {}
    freq_changed = int(payload.get("weekly_frequency", profile.get("weekly_frequency", 4))) != int(
        profile.get("weekly_frequency", 4)
    )
    rep_changed = payload.get("rep_preference", profile.get("rep_preference", "balanced")) != profile.get(
        "rep_preference", "balanced"
    )
    limits_changed = str(payload.get("injuries_or_limitations", profile.get("injuries_or_limitations", "None"))).strip() != str(
        profile.get("injuries_or_limitations", "None")
    )
    updated = {**profile, **payload}
    db.upsert_user_profile(updated)
    program = None
    if freq_changed or rep_changed or limits_changed:
        program, _ = generate_program_pipeline(
            rep_preference_override=updated.get("rep_preference", "balanced"),
            frequency_override=int(updated.get("weekly_frequency", 4)),
        )
    return {"profile": db.get_user_profile(), "program_rebuilt": program is not None, "program": program}


def update_persona(db: Any, trainee_id: str, coach_tone: str, custom_instructions: str) -> dict[str, Any]:
    bind_user(db, trainee_id)
    db.update_user_persona(coach_tone, custom_instructions)
    return {"profile": db.get_user_profile()}


def reset_profile(db: Any, trainee_id: str) -> dict[str, Any]:
    bind_user(db, trainee_id)
    db.clear_user_profile()
    return {"ok": True}
