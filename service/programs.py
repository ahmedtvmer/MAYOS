"""Program generation, retrieval, and export."""

from typing import Any

from agent.program_generator import generate_program_pipeline
from service._base import bind_user
from utils.exporter import export_program_to_excel


def ensure_active_program(db: Any, trainee_id: str) -> Any:
    """Returns the saved routine, synthesizing one when the profile exists but none is saved."""
    bind_user(db, trainee_id)
    profile = db.get_user_profile()
    if not profile:
        return None
    saved = db.get_active_program()
    if saved is not None:
        return saved
    program, _ = generate_program_pipeline(rep_preference_override=profile.get("rep_preference", "balanced"))
    return program


def regenerate_program(db: Any, trainee_id: str) -> Any:
    bind_user(db, trainee_id)
    profile = db.get_user_profile() or {}
    program, _ = generate_program_pipeline(
        rep_preference_override=profile.get("rep_preference", "balanced"),
        frequency_override=int(profile.get("weekly_frequency", 4)),
    )
    return program


def export_active_program(db: Any, trainee_id: str) -> tuple[str, bytes] | None:
    program = db.get_active_program() if db.active_user == db._sanitize_username(trainee_id) else None
    if program is None:
        bind_user(db, trainee_id)
        program = db.get_active_program()
    if program is None:
        return None
    filename = f"{program.program_name.replace(' ', '_').lower()}.xlsx"
    return filename, export_program_to_excel(program)
