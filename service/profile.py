"""Profile and coach-persona operations."""

from typing import Any

from agent.program_generator import generate_program_pipeline
from service._base import ledger_scope
from service.programs import COACH_CONTROLLED_ERROR, player_controls_program
from utils.equipment_access import map_equipment_access


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
    """Upserts the profile; rebuilds the routine when frequency/rep-bias/limits change.

    The profile update itself always applies. The rebuild is a player write path,
    so while an assigned coach owns the active program it is skipped and the
    response explains that a coach request is needed.
    """
    with ledger_scope(db, ledger, ledger_id) as ledger:
        profile = ledger.get_player_profile() or {}
        if "equipment_access" in payload:
            payload = {**payload, "equipment_access": map_equipment_access(payload["equipment_access"])}
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
        ledger.upsert_player_profile(updated)
        program = None
        program_blocked = False
        if freq_changed or rep_changed or limits_changed:
            if player_controls_program(db, ledger, player_account_id):
                from svc.llm import InferenceScope, run_inference_sync

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


def reset_profile(db: Any, ledger_id: str, ledger: Any | None = None) -> dict[str, Any]:
    with ledger_scope(db, ledger, ledger_id) as ledger:
        ledger.clear_player_profile()
        return {"ok": True}
