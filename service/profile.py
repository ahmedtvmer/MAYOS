"""Profile and coach-persona operations."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from agent.program_generator import generate_program_pipeline
from service._base import ledger_scope
from service.programs import COACH_CONTROLLED_ERROR, player_controls_program
from utils.equipment_access import map_equipment_access

logger = logging.getLogger(__name__)
PROFILE_CHANGE_KIND = "profile_change"
PROFILE_CHANGE_FIELDS = ("injuries_or_limitations", "equipment_access")

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

    The profile update itself always applies. The rebuild is a player write path,
    so while an assigned coach owns the active program it is skipped and the
    response explains that a coach request is needed.
    """
    with ledger_scope(db, ledger, ledger_id) as ledger:
        profile = ledger.get_player_profile() or {}
        if "equipment_access" in payload:
            payload = {**payload, "equipment_access": map_equipment_access(payload["equipment_access"])}
        defaults = {
            "injuries_or_limitations": "None",
            "equipment_access": profile.get("equipment_access"),
            "weekly_frequency": 4,
            "rep_preference": "balanced",
        }
        rebuild_requested = any(
            key in payload
            and (
                int(payload[key]) != int(profile.get(key, defaults[key]))
                if key == "weekly_frequency"
                else str(payload[key]).strip() != str(profile.get(key, defaults[key]))
                if key == "injuries_or_limitations"
                else payload[key] != profile.get(key, defaults[key])
            )
            for key in PROFILE_REBUILD_FIELDS
        )
        updated = {**profile, **payload}
        ledger.upsert_player_profile(updated)
        _notify_profile_change(db, player_account_id, profile, updated)
        program = None
        program_blocked = False
        if rebuild_requested:
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


def _notify_profile_change(
    db: Any, player_account_id: str | None, before_profile: dict[str, Any], after_profile: dict[str, Any]
) -> None:
    """Best-effort catalog alert for changed program-shaping Training profile facts."""
    if not player_account_id:
        return
    changes: dict[str, dict[str, str]] = {}
    for field in PROFILE_CHANGE_FIELDS:
        before = before_profile.get(field)
        after = after_profile.get(field)
        if before is None or after is None or str(before) == str(after):
            continue
        changes[field] = {"before": str(before), "after": str(after)}
    if not changes:
        return
    try:
        now_iso = datetime.now(UTC).isoformat()
        with db.catalog_transaction():
            assignment = db.get_active_assignment_for_player(str(player_account_id))
            if assignment is None:
                return
            # list_coach_alerts is the catalog-side active-assignment gate used
            # by the alert centre. The catalog transaction makes lookup and
            # insert/update one serialized transition for repeated edits.
            existing = next(
                (
                    row for row in db.list_coach_alerts(assignment["coach_account_id"], ("new", "acknowledged"))
                    if row["assignment_id"] == assignment["assignment_id"] and row["kind"] == PROFILE_CHANGE_KIND
                ),
                None,
            )
            merged = dict(existing["details"].get("profile_changes", {})) if existing else {}
            for field, change in changes.items():
                prior = merged.get(field)
                merged[field] = {
                    "before": prior["before"] if isinstance(prior, dict) else change["before"],
                    "after": change["after"],
                }
            details = {"profile_changes": merged}
            if existing is not None:
                db.update_coach_alert_details(existing["alert_id"], details)
                return
            inserted = db.insert_coach_alert(
                uuid.uuid4().hex,
                assignment["assignment_id"],
                assignment["coach_account_id"],
                str(player_account_id),
                PROFILE_CHANGE_KIND,
                uuid.uuid4().hex,
                details,
                now_iso,
            )
            if not inserted["created"]:
                return
        from service.coach_notices import notify_coach, player_display_name

        notify_coach(
            db,
            assignment,
            PROFILE_CHANGE_KIND,
            f"{player_display_name(db, assignment)} changed their Training profile. Review the alert in your roster.",
            now_iso,
        )
    except Exception:
        logger.warning("Could not create profile-change Coach alert for account %s.", player_account_id, exc_info=True)


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
