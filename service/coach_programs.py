"""Coach program draft generation."""

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from agent.ProgramState import GeneratedProgramSchema
from agent.program_cardio import CoachCardioOptions
from agent.program_generator import (
    SPLIT_OVERRIDE_VALUES,
    ProgramGenerationRequest,
    generate_program_draft_pipeline,
)
from agent.program_rules import valid_splits_for
from database.registry.assignments import AssignmentNoticeRecord
from service.assignments import authorized_player_ledger
from service.coach_notices import build_assignment_notice_record
from service.program_analytics import ProgramAnalyticsActor, capture_coach_program_published
from service import program_end_alerts, stall_alerts, volume_review_alerts
from service import analytics

logger = logging.getLogger(__name__)


class InvalidCoachSplitSelection(ValueError):
    """A selected coach Split is not available at the requested frequency."""


class InvalidCoachCardioOptions(ValueError):
    """Coach cardio settings do not fit the selected training frequency."""


class UnrecognizedSplitOverride(ValueError):
    """A free-text Player split request that generation cannot honor."""

    message_code = "assignment.split_override_unrecognized.v1"

    def __init__(self) -> None:
        super().__init__("Unrecognized split override.")
        self.accepted_values: tuple[str, ...] = SPLIT_OVERRIDE_VALUES

    @property
    def message_params(self) -> dict[str, list[str]]:
        return {"accepted_values": list(self.accepted_values)}


def program_generation_split_options(
    db: Any, actor: ProgramAnalyticsActor, assignment_id: Any
) -> dict[str, list[dict[str, str]]] | None:
    """Return the shared Split catalog for an actively assigned Player."""
    authorized = authorized_player_ledger(db, actor.account_id, assignment_id)
    if authorized is None:
        return None
    ledger, _ = authorized
    with ledger:
        profile = ledger.get_player_profile() or {}
    gender = profile.get("gender", "male")
    return {
        str(days): _coach_split_options_for_days(days, gender)
        for days in range(1, 6)
    }


def _coach_split_options_for_days(days: int, gender: str) -> list[dict[str, str]]:
    auto_label = "Auto (Full Body)" if days == 1 else "Auto"
    return [
        {"split_id": "auto", "display_name": auto_label},
        *(
            {"split_id": split_id, "display_name": display_name}
            for split_id, display_name in valid_splits_for(days, gender)
        ),
    ]


@dataclass(frozen=True)
class ProgramPublicationDetails:
    actor: ProgramAnalyticsActor
    first_for_assignment: bool
    change_summary: dict[str, Any]
    client: analytics.ClientContext


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


def _build_generated_draft(
    db: Any,
    actor: ProgramAnalyticsActor,
    request: ProgramGenerationRequest,
    ledger: Any,
) -> dict[str, Any]:
    program, _ = generate_program_draft_pipeline(request, ledger=ledger)
    return _program_draft(program, db, actor.account_id, ledger)


def _coach_generation_options(
    profile: dict[str, Any], request: ProgramGenerationRequest, display_language: str
) -> tuple[int, str, ProgramGenerationRequest]:
    days = request.frequency_override or int(profile.get("weekly_frequency", 4))
    split_id = request.split_id_override or "auto"
    valid_ids = {
        candidate_id
        for candidate_id, _ in valid_splits_for(days, profile.get("gender", "male"))
    }
    if split_id != "auto" and split_id not in valid_ids:
        raise InvalidCoachSplitSelection()
    cardio = request.coach_cardio or CoachCardioOptions(0, 20, "none")
    if cardio.days > days:
        raise InvalidCoachCardioOptions("Cardio days cannot exceed training days.")
    cardio = replace(cardio, display_language=display_language)
    generation_request = ProgramGenerationRequest(
        rep_preference_override=request.rep_preference_override or "balanced",
        frequency_override=days,
        split_id_override=None if split_id == "auto" else split_id,
        coach_cardio=cardio,
    )
    return days, split_id, generation_request


def generate_program_draft(
    db: Any,
    actor: ProgramAnalyticsActor,
    assignment_id: Any,
    request: ProgramGenerationRequest,
    *,
    replace_existing: bool = False,
) -> Any | None:
    """Generates a coach-owned program draft for an assigned player."""
    from service import coach_program_drafts

    authorized = authorized_player_ledger(db, actor.account_id, assignment_id)
    if authorized is None:
        return None
    ledger, assignment_context = authorized
    with ledger:
        profile = ledger.get_player_profile() or {}
        days, split_id, generation_request = _coach_generation_options(
            profile, request, assignment_context["player"].get("display_language", "en")
        )
        coach_program_drafts.ensure_generated_program_draft_available(
            ledger, assignment_id, replace_existing=replace_existing
        )
        draft = _build_generated_draft(db, actor, generation_request, ledger)
        draft["generation_options"] = {
            "days": days,
            "split_id": split_id,
            "rep_preference": generation_request.rep_preference_override,
            "cardio_days": generation_request.coach_cardio.days,
            "cardio_minutes": generation_request.coach_cardio.minutes,
            "cardio_type": generation_request.coach_cardio.cardio_type,
            "cardio_custom_note": generation_request.coach_cardio.custom_note,
        }
        if db.get_active_assignment_for_coach(actor.account_id, assignment_id) is None:
            return None
        if replace_existing:
            return coach_program_drafts.replace_generated_program_draft(ledger, assignment_id, draft)
        return coach_program_drafts.create_generated_program_draft(ledger, assignment_id, draft)


def record_program_publication(
    db: Any,
    context: dict[str, Any],
    published: Any,
    details: ProgramPublicationDetails,
) -> None:
    """Records the shared catalog and analytics effects of activating a coach program."""
    assignment_id = context["assignment"]["assignment_id"]
    player_account_id = context["player"]["account_id"]
    now = datetime.now(UTC)
    try:
        stall_alerts.resolve_for_assignment(db, assignment_id, now)
    except Exception:
        logger.warning("Stall alert resolution failed after program publication", exc_info=True)
    try:
        volume_review_alerts.resolve_for_assignment(db, assignment_id)
    except Exception:
        logger.warning("Volume review alert resolution failed after program publication", exc_info=True)
    program_end_alerts.resolve_for_publish(db, assignment_id, now)
    message = f"Your coach published program version {published.version}."
    db.create_assignment_notice_record(
        build_assignment_notice_record(
            AssignmentNoticeRecord(
                account_id=player_account_id,
                assignment_id=assignment_id,
                kind="program_published",
                message=message,
                created_at=now.isoformat(),
                program_change_summary=details.change_summary,
            ),
            "assignment_notice.program_published.v1",
            {"version": published.version},
        )
    )
    # Attendance evaluation is not run here, so refresh the roster's cached name.
    db.set_roster_program_name(assignment_id, published.program_name)
    capture_coach_program_published(
        details.actor,
        str(assignment_id),
        published,
        details.first_for_assignment,
        player_account_id=player_account_id,
        client=details.client,
    )
