"""Program generation, retrieval, and editing."""

from typing import Any

from agent.program_generator import generate_program_pipeline
from service._base import ledger_scope
from service import analytics
from service.program_analytics import ProgramAnalyticsActor, capture_program_exercise_swapped, capture_program_generated

COACH_CONTROLLED_ERROR = "Your assigned coach controls your program. Ask your coach for changes."
COACH_CONTROLLED_REQUEST_ERROR = (
    "Your assigned coach controls your program. "
    "You can review and send a request to your coach."
)


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
    db: Any,
    ledger_id: str,
    player_account_id: str | None = None,
    ledger: Any | None = None,
    *,
    actor_role: str = "player",
    trigger: str = "synthesized",
    emit_analytics: bool = True,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
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
        if emit_analytics and player_account_id:
            persisted = ledger.get_active_program()
            if persisted is None:
                raise RuntimeError("Generated program is missing from the player ledger after save.")
            capture_program_generated(
                ProgramAnalyticsActor(player_account_id, actor_role), trigger, persisted, client=client
            )
        return program


def generate_program_version(
    db: Any,
    ledger: Any,
    actor: ProgramAnalyticsActor,
    trigger: str,
    *,
    user_split_override: str | None = None,
    rep_preference_override: str | None = None,
    frequency_override: int | None = None,
    purpose: str = "program_generate",
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> Any:
    """Generates a new persisted version and reports it after the save commits."""
    from svc.llm import InferenceScope, run_inference_sync

    program, _ = run_inference_sync(
        generate_program_pipeline,
        user_split_override=user_split_override,
        rep_preference_override=rep_preference_override,
        frequency_override=frequency_override,
        ledger=ledger,
        scope=InferenceScope(account_id=actor.account_id, role=actor.role, purpose=purpose, store=db),
    )
    persisted = ledger.get_active_program()
    if persisted is None:
        raise RuntimeError("Generated program is missing from the player ledger after save.")
    capture_program_generated(actor, trigger, persisted, client=client)
    return program


def record_program_change(
    actor: ProgramAnalyticsActor,
    change: str,
    program: Any,
    *,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> None:
    """Reports one successful assistant program mutation from its committed version."""
    if change == "regenerated":
        capture_program_generated(actor, "player_request", program, client=client)
    elif change == "swapped":
        capture_program_exercise_swapped(actor, program, client=client)
