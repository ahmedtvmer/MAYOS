"""Program generation, retrieval, and export."""

from typing import Any

from agent.program_generator import generate_program_pipeline
from service._base import bind_user
from utils.exporter import export_program_to_excel

COACH_CONTROLLED_ERROR = "Your assigned coach controls your program. Ask your coach for changes."


def player_controls_program(db: Any, player_account_id: str | None) -> bool:
    """True unless the active assignment's coach published the active program.

    Matches the CONTEXT.md glossary: program authority stays with the player
    until an assigned coach publishes, returns on unassignment, and a fresh
    assignment before any publication leaves self-service intact.
    """
    if not player_account_id:
        return True
    assignment = db.get_active_assignment_for_player(player_account_id)
    if assignment is None:
        return True
    active = db.get_active_program()
    if active is None or active.published_by_coach_account_id is None:
        return True
    if active.published_by_coach_account_id != assignment["coach_account_id"]:
        return True
    if active.created_at is None or active.created_at < assignment["started_at"]:
        return True
    return False


def ensure_active_program(db: Any, trainee_id: str, player_account_id: str | None = None) -> Any:
    """Returns the saved routine, synthesizing one when the profile exists but none is saved.

    Synthesis is a player write path, so it obeys the single authority decision:
    while an assigned coach owns the active program, nothing is synthesized and
    ``None`` is returned with the saved program left untouched.
    """
    bind_user(db, trainee_id)
    saved = db.get_active_program()
    if saved is not None:
        return saved
    if not player_controls_program(db, player_account_id):
        return None
    profile = db.get_user_profile()
    if not profile:
        return None
    program, _ = generate_program_pipeline(rep_preference_override=profile.get("rep_preference", "balanced"))
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
