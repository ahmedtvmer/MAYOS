"""Profile and coach-persona operations."""

from dataclasses import dataclass
from typing import Any

from agent.program_generator import ProgramGenerationRequest, generate_program_draft_pipeline
from service._base import ledger_scope
from service import analytics
from service.profile_change_alerts import normalize_profile_value
from service.programs import COACH_CONTROLLED_ERROR, player_controls_program
from service.program_analytics import ProgramAnalyticsActor, capture_program_generated
from service import profile_change_alerts
from service import weight_history
from service.profile_fields import PROFILE_REBUILD_FIELDS
from service.weight_trend_alerts import evaluate_for_player
from utils.equipment_access import map_equipment_access


@dataclass(frozen=True)
class WeightEntryCommand:
    """Verified caller and submitted value for one Player weight write."""

    ledger_id: str
    player_account_id: str
    weight_kg: float


def record_weight_entry(db: Any, ledger: Any, command: WeightEntryCommand) -> weight_history.WeightTrendPoint:
    """Writes a date-only weight entry, then evaluates its active Coach alert."""
    point = weight_history.record_weight(
        ledger, command.ledger_id, command.weight_kg
    )
    evaluate_for_player(db, command.player_account_id, ledger=ledger)
    return point


def get_profile(db: Any, ledger_id: str, ledger: Any | None = None) -> dict[str, Any] | None:
    with ledger_scope(db, ledger, ledger_id) as ledger:
        return ledger.get_player_profile()


def update_profile(
    db: Any,
    ledger_id: str,
    payload: dict[str, Any],
    player_account_id: str | None = None,
    ledger: Any | None = None,
    *,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
    background_tasks: Any = None,
) -> dict[str, Any]:
    """Upserts the profile; rebuilds when program-shaping inputs change.

    Player-controlled rebuild edits save atomically with the replacement program,
    so a quota refusal or generation failure leaves both unchanged. While an
    assigned coach owns the active program, profile edits still save without a
    rebuild and the response explains that a coach request is needed.
    """
    with ledger_scope(db, ledger, ledger_id) as ledger:
        profile = ledger.get_player_profile() or {}
        if "equipment_access" in payload:
            payload = {**payload, "equipment_access": map_equipment_access(payload["equipment_access"])}
        if isinstance(payload.get("injuries_or_limitations"), str):
            payload = {**payload, "injuries_or_limitations": payload["injuries_or_limitations"].strip()}
        defaults = {
            "injuries_or_limitations": "None",
            "equipment_access": profile.get("equipment_access"),
            "weekly_frequency": 4,
            "rep_preference": "balanced",
        }
        rebuild_requested = any(
            key in payload
            and normalize_profile_value(key, payload[key])
            != normalize_profile_value(key, profile.get(key, defaults.get(key)))
            for key in PROFILE_REBUILD_FIELDS
        )
        updated = {**profile, **payload}

        def persist_profile() -> None:
            if "weight_kg" in payload:
                ledger.upsert_player_profile_with_weight_history(
                    updated,
                    weight_history.player_local_date(ledger, ledger_id).isoformat(),
                )
            else:
                ledger.upsert_player_profile(updated)

        profile_change_alerts.record_profile_change(
            db,
            profile_change_alerts.ProfileChangeSnapshot(
                player_account_id=player_account_id,
                before_profile=profile,
                after_profile=updated,
                client=client,
            ),
        )
        program = None
        program_blocked = False
        if rebuild_requested:
            if player_controls_program(db, ledger, player_account_id):
                from svc.llm import InferenceScope, inference_turn, run_inference_sync

                inference_scope = InferenceScope(
                    account_id=player_account_id,
                    role="player",
                    purpose="profile_rebuild",
                    store=db,
                    client=client,
                )
                with inference_turn(inference_scope, background_tasks=background_tasks):
                    program, _ = run_inference_sync(
                        generate_program_draft_pipeline,
                        ProgramGenerationRequest(
                            rep_preference_override=updated.get("rep_preference", "balanced"),
                            frequency_override=int(updated.get("weekly_frequency", 4)),
                        ),
                        ledger=ledger,
                        profile=updated,
                        scope=inference_scope,
                    )
                    # Keep the profile and generated Program atomic, after each
                    # model call has been written to the catalog.
                    with ledger.ledger_transaction():
                        persist_profile()
                        if program is not None:
                            ledger.save_training_program(program.model_dump())
            else:
                program_blocked = True
                persist_profile()
        else:
            persist_profile()
        if "weight_kg" in payload and player_account_id:
            evaluate_for_player(db, player_account_id, ledger=ledger)
        if program is not None and player_account_id:
            persisted = ledger.get_active_program()
            if persisted is not None:
                capture_program_generated(
                    ProgramAnalyticsActor(player_account_id, "player"),
                    "profile_rebuild",
                    persisted,
                    client=client,
                )
        return {
            "profile": ledger.get_player_profile(),
            "program_rebuilt": program is not None,
            "program": program,
            "program_blocked": program_blocked,
            "program_message": COACH_CONTROLLED_ERROR if program_blocked else None,
        }


def update_persona(
    db: Any, ledger_id: str, coach_tone: str, custom_instructions: str, ledger: Any | None = None
) -> dict[str, Any]:
    with ledger_scope(db, ledger, ledger_id) as ledger:
        ledger.update_player_persona(coach_tone, custom_instructions)
        return {"profile": ledger.get_player_profile()}
