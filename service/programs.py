"""Program generation, retrieval, and editing."""

from typing import Any

from agent.program_generator import generate_program_pipeline
from service._base import ledger_scope

COACH_CONTROLLED_ERROR = "Your assigned coach controls your program. Ask your coach for changes."


def player_controls_program(db: Any, ledger: Any, player_account_id: str | None) -> bool:
    """True unless the active assignment's coach published the active program.

    Matches the CONTEXT.md glossary: program authority stays with the player
    until an assigned coach publishes, returns on unassignment, and a fresh
    assignment before any publication leaves self-service intact. Registry state
    comes from the app store; the active program from the explicit ledger handle.
    """
    if not player_account_id:
        return True
    assignment = db.get_active_assignment_for_player(player_account_id)
    if assignment is None:
        return True
    active = ledger.get_active_program()
    if active is None or active.published_by_coach_account_id is None:
        return True
    if active.published_by_coach_account_id != assignment["coach_account_id"]:
        return True
    if active.created_at is None or active.created_at < assignment["started_at"]:
        return True
    return False


def with_library_equipment(program: Any, db: Any) -> dict[str, Any]:
    """Return a program payload whose exercises carry library equipment.

    Older saved programs predate the equipment field. Resolve it when serving
    the program so an Active workout created from a cached program has the same
    equipment facts as a newly generated one.
    """
    payload = program.model_dump() if hasattr(program, "model_dump") else dict(program)
    for day in payload.get("days", []):
        program_movements = [
            *day.get("exercises", []),
            *day.get("warmup_exercises", []),
        ]
        for exercise in program_movements:
            entry = db.get_exercise_library_entry(
                str(exercise.get("exercise_id", ""))
            )
            if entry is not None:
                exercise["equipment"] = entry.get("equipment")
    return payload


def ensure_active_program(
    db: Any, ledger_id: str, player_account_id: str | None = None, ledger: Any | None = None
) -> Any:
    """Returns the saved routine, synthesizing one when the profile exists but none is saved.

    Synthesis is a player write path, so it obeys the single authority decision:
    while an assigned coach owns the active program, nothing is synthesized and
    ``None`` is returned with the saved program left untouched.
    """
    with ledger_scope(db, ledger, ledger_id) as ledger:
        saved = ledger.get_active_program()
        if saved is not None:
            return saved
        if not player_controls_program(db, ledger, player_account_id):
            return None
        profile = ledger.get_player_profile()
        if not profile:
            return None
        program, _ = generate_program_pipeline(
            rep_preference_override=profile.get("rep_preference", "balanced"), ledger=ledger
        )
        return program
