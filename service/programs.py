"""Program generation, retrieval, and editing."""

from typing import Any

from pydantic import BaseModel

from agent.program_generator import PROGRAM_DESIGN_VERSION, generate_program_pipeline
from agent.program_weeks import (
    final_week_is_complete,
    flatten_program_days,
    normalize_program_weeks,
)
from service._base import ledger_scope
from service import analytics
from service.program_analytics import ProgramAnalyticsActor, capture_program_exercise_swapped, capture_program_generated

COACH_CONTROLLED_ERROR = "Your assigned coach controls your program. Ask your coach for changes."
COACH_CONTROLLED_REQUEST_ERROR = (
    "Your assigned coach controls your program. "
    "You can review and send a request to your coach."
)


class ProgramRepeatError(Exception):
    """The player cannot restart this program block from Week 1."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


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
    return not coach_controls_program(assignment, ledger.get_active_program())


def coach_controls_program(assignment: dict[str, Any] | None, program: Any) -> bool:
    """True when the assignment's coach published this program during the assignment."""
    if assignment is None or program is None:
        return False
    if program.published_by_coach_account_id != assignment["coach_account_id"]:
        return False
    return program.created_at is not None and program.created_at >= assignment["started_at"]


def with_library_equipment(program: Any, db: Any) -> dict[str, Any]:
    """Return a program payload whose exercises carry library equipment.

    Older saved programs predate the equipment field. Resolve it when serving
    the program so an Active workout created from a cached program has the same
    equipment facts as a newly generated one.
    """
    payload = program.model_dump() if isinstance(program, BaseModel) else dict(program)
    weeks = normalize_program_weeks(payload)
    for week in weeks:
        for day in week["days"]:
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
    payload["weeks"] = weeks
    payload["days"] = flatten_program_days(weeks)
    source_template_id = payload.get("source_template_id")
    payload["source_template_name"] = (
        db.get_program_template_name_for_provenance(source_template_id)
        if source_template_id
        else None
    )
    return payload


def active_program_response(
    db: Any, ledger: Any, player_account_id: str, program: Any
) -> dict[str, Any]:
    """Build the Player API payload with authority, cursor, and block state."""
    version = getattr(program, "version", None)
    completed_days = ledger.completed_program_days(int(version)) if version is not None else set()
    position = ledger.get_program_position(program)
    payload = with_library_equipment(program, db)
    payload["offer_design_regeneration"] = should_offer_design_regeneration(
        db, ledger, player_account_id, program
    )
    return {
        **payload,
        "player_controls_program": player_controls_program(db, ledger, player_account_id),
        "current_week": position.current_week,
        "week_count": position.week_count,
        "next_day_order": position.next_day_order,
        "final_week_completed": final_week_is_complete(program, completed_days),
    }


def should_offer_design_regeneration(
    db: Any, ledger: Any, player_account_id: str, program: Any
) -> bool:
    return (
        player_controls_program(db, ledger, player_account_id)
        and program.published_by_coach_account_id is None
        and program.source_template_id is None
        and program.design_version != PROGRAM_DESIGN_VERSION
        and ledger.program_design_offer_decision() is None
    )


def dismiss_design_regeneration_offer(db: Any, ledger: Any, player_account_id: str) -> bool:
    active = ledger.get_active_program()
    if active is None or not should_offer_design_regeneration(db, ledger, player_account_id, active):
        return False
    ledger.record_program_design_offer_decision("dismissed")
    return True


def accept_design_regeneration_offer(
    db: Any,
    ledger: Any,
    actor: ProgramAnalyticsActor,
    client: analytics.ClientContext,
    background_tasks: Any,
) -> Any:
    if not player_controls_program(db, ledger, actor.account_id):
        raise PermissionError(COACH_CONTROLLED_ERROR)
    active = ledger.get_active_program()
    if active is None or not should_offer_design_regeneration(db, ledger, actor.account_id, active):
        raise ValueError("This program no longer has a regeneration offer.")
    if not ledger.try_claim_program_design_offer():
        raise ValueError("This program no longer has a regeneration offer.")
    try:
        return generate_program_version(
            db,
            ledger,
            actor,
            "player_request",
            purpose="program_generate",
            client=client,
            background_tasks=background_tasks,
        )
    except Exception:
        ledger.release_program_design_offer_claim()
        raise


def repeat_program_from_week_one(
    db: Any,
    ledger: Any,
    player_account_id: str,
    expected_active_version: int,
) -> Any:
    """Create a fresh version of the same program starting at Week 1, Day 1."""
    with ledger.ledger_transaction():
        active = _repeatable_program(
            db, ledger, player_account_id, expected_active_version
        )
        ledger.save_training_program(
            _program_copy_for_new_version(active),
            published_by_coach_account_id=None,
        )
        return ledger.get_active_program()


def _repeatable_program(
    db: Any, ledger: Any, player_account_id: str, expected_version: int
) -> Any:
    if not player_controls_program(db, ledger, player_account_id):
        raise ProgramRepeatError("coach_controlled", COACH_CONTROLLED_ERROR)
    active = ledger.get_active_program()
    if active is None:
        raise ProgramRepeatError("no_active_program", "There is no active program to repeat.")
    if active.version != expected_version or active.version is None:
        raise ProgramRepeatError("program_changed", "The active program changed. Refresh and try again.")
    completed_days = ledger.completed_program_days(int(active.version))
    if not final_week_is_complete(active, completed_days):
        raise ProgramRepeatError(
            "final_week_incomplete", "The final Program week is not complete."
        )
    return active


def _program_copy_for_new_version(active: Any) -> dict[str, Any]:
    program_copy = active.model_dump()
    for field in ("id", "version", "created_at", "published_by_coach_account_id"):
        program_copy.pop(field, None)
    weeks = normalize_program_weeks(program_copy)
    for week in weeks:
        week.pop("id", None)
        for day in week["days"]:
            day.pop("id", None)
            for movement in [*day.get("exercises", []), *day.get("warmup_exercises", [])]:
                movement.pop("id", None)
    program_copy["weeks"] = weeks
    program_copy["days"] = flatten_program_days(weeks)
    return program_copy


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
        if program is None:
            return None
        persisted = ledger.get_active_program()
        if persisted is None:
            raise RuntimeError("Generated program is missing from the player ledger after save.")
        if emit_analytics and player_account_id:
            capture_program_generated(
                ProgramAnalyticsActor(player_account_id, actor_role), trigger, persisted, client=client
            )
        return persisted


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
    background_tasks: Any = None,
) -> Any:
    """Generates a new persisted version and reports it after the save commits."""
    from svc.llm import InferenceScope, inference_turn, run_inference_sync

    inference_scope = InferenceScope(
        account_id=actor.account_id,
        role=actor.role,
        purpose=purpose,
        store=db,
        client=client,
    )
    with inference_turn(inference_scope, background_tasks=background_tasks):
        program, _ = run_inference_sync(
            generate_program_pipeline,
            user_split_override=user_split_override,
            rep_preference_override=rep_preference_override,
            frequency_override=frequency_override,
            ledger=ledger,
            scope=inference_scope,
        )
        persisted = ledger.get_active_program()
        if persisted is None:
            raise RuntimeError("Generated program is missing from the player ledger after save.")
        capture_program_generated(actor, trigger, persisted, client=client)
        return persisted


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
