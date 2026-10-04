"""Profile and coach-persona operations."""

from typing import Any

from agent.program_generator import generate_program_pipeline
from service._base import ledger_scope
from service.profile_change_alerts import normalize_profile_value
from service.programs import COACH_CONTROLLED_ERROR, player_controls_program
from utils.equipment_access import map_equipment_access

# Profile facts that alter program structure. The intake API exposes this list
# so clients can ask for confirmation without reimplementing the service rule.
PROFILE_REBUILD_FIELDS = (
    "injuries_or_limitations",
    "equipment_access",
    "weekly_frequency",
    "rep_preference",
)


def get_profile(db: Any, ledger_id: str, ledger: Any | None = None) -> dict[str, Any] | None:
    with ledger_scope(db, ledger, ledger_id) as ledger:
        return ledger.get_player_profile()


def update_profile(
    db: Any,
    ledger_id: str,
    payload: dict[str, Any],
    player_account_id: str | None = None,
    ledger: Any | None = None,
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
        ledger.upsert_player_profile(updated)
        program = None
        program_blocked = False
        if rebuild_requested:
            if player_controls_program(db, ledger, player_account_id):
                from svc.llm import InferenceScope, run_inference_sync

                with ledger.ledger_transaction():
                    ledger.upsert_player_profile(updated)
                    program, _ = run_inference_sync(
                        generate_program_pipeline,
                        rep_preference_override=updated.get("rep_preference", "balanced"),
                        frequency_override=int(updated.get("weekly_frequency", 4)),
                        ledger=ledger,
                        scope=InferenceScope(
                            account_id=player_account_id, role="player", purpose="profile_rebuild", store=db
                        ),
                    )
            else:
                program_blocked = True
                ledger.upsert_player_profile(updated)
        else:
            ledger.upsert_player_profile(updated)
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
