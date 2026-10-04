"""Coach program draft generation."""

import logging
from datetime import UTC, datetime
from typing import Any

from agent.ProgramState import GeneratedProgramSchema
from agent.program_generator import ProgramGenerationRequest, generate_program_draft_pipeline
from service.assignments import authorized_player_ledger
from service.program_analytics import ProgramAnalyticsActor, capture_coach_program_published
from service import stall_alerts
from service import analytics

logger = logging.getLogger(__name__)


def _generated_exercise_draft(exercise: dict[str, Any]) -> dict[str, Any]:
    draft_exercise = dict(exercise)
    draft_exercise["target_rir"] = 10 - float(draft_exercise.pop("target_rpe"))
    # The Player view displays these catalog steps as coach-written notes.
    draft_exercise["notes"] = None
    return draft_exercise


def _generated_day_draft(day: dict[str, Any]) -> dict[str, Any]:
    return {
        **day,
        "exercises": [_generated_exercise_draft(exercise) for exercise in day.get("exercises", [])],
    }


def _program_draft(
    program: GeneratedProgramSchema, db: Any, coach_account_id: str, ledger: Any
) -> dict[str, Any]:
    generated = program.model_dump()
    days = [_generated_day_draft(day) for day in generated.get("days", [])]
    from service.coach_program_drafts import validate_generated_program_draft

    return validate_generated_program_draft(generated, days, db, coach_account_id, ledger)


def _coach_split_inference(scope: Any):
    from svc.llm import run_inference_sync

    def infer(function, *args, **kwargs):
        return run_inference_sync(function, *args, scope=scope, **kwargs)

    return infer


def _build_generated_draft(
    db: Any,
    actor: ProgramAnalyticsActor,
    request: ProgramGenerationRequest,
    ledger: Any,
    inference_scope: Any,
) -> dict[str, Any]:
    program, _ = generate_program_draft_pipeline(
        request,
        inference_call=_coach_split_inference(inference_scope),
        ledger=ledger,
    )
    return _program_draft(program, db, actor.account_id, ledger)


def generate_program_draft(
    db: Any,
    actor: ProgramAnalyticsActor,
    assignment_id: Any,
    request: ProgramGenerationRequest,
    *,
    replace_existing: bool = False,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
    background_tasks: Any = None,
) -> Any | None:
    """Generates a coach-owned program draft for an assigned player."""
    from service import coach_program_drafts
    from svc.llm import InferenceScope, inference_turn

    authorized = authorized_player_ledger(db, actor.account_id, assignment_id)
    if authorized is None:
        return None
    ledger, _ = authorized
    with ledger:
        coach_program_drafts.ensure_generated_program_draft_available(
            ledger, assignment_id, replace_existing=replace_existing
        )
        inference_scope = InferenceScope(
            account_id=actor.account_id,
            role="coach",
            purpose="coach_generate_draft",
            store=db,
            client=client,
        )
        with inference_turn(inference_scope, background_tasks=background_tasks):
            draft = _build_generated_draft(db, actor, request, ledger, inference_scope)
            if db.get_active_assignment_for_coach(actor.account_id, assignment_id) is None:
                return None
            if replace_existing:
                return coach_program_drafts.replace_generated_program_draft(ledger, assignment_id, draft)
        return coach_program_drafts.create_generated_program_draft(ledger, assignment_id, draft)


def record_program_publication(
    db: Any,
    context: dict[str, Any],
    published: Any,
    *,
    actor: ProgramAnalyticsActor,
    first_for_assignment: bool,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> None:
    """Records the shared catalog and analytics effects of activating a coach program."""
    assignment_id = context["assignment"]["assignment_id"]
    player_account_id = context["player"]["account_id"]
    now = datetime.now(UTC)
    try:
        stall_alerts.resolve_for_assignment(db, assignment_id, now)
    except Exception:
        logger.warning("Stall alert resolution failed after program publication", exc_info=True)
    db.create_assignment_notice(
        player_account_id,
        assignment_id,
        "program_published",
        f"Your coach published program version {published.version}.",
        now.isoformat(),
    )
    # Attendance evaluation is not run here, so refresh the roster's cached name.
    db.set_roster_program_name(assignment_id, published.program_name)
    capture_coach_program_published(
        actor,
        str(assignment_id),
        published,
        first_for_assignment,
        player_account_id=player_account_id,
        client=client,
    )
