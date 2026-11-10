"""Profile and coach-persona operations."""

from dataclasses import dataclass
from typing import Any

from agent.program_generator import (
    PROGRAM_DESIGN_VERSION,
    ProgramGenerationRequest,
    generate_program_draft_pipeline,
)
from service._base import ledger_scope
from service import analytics
from service.profile_change_alerts import normalize_profile_value
from service.programs import COACH_CONTROLLED_ERROR, player_controls_program
from service.program_analytics import ProgramAnalyticsActor, capture_program_generated
from service import profile_change_alerts
from service import injuries as injuries_service
from service import weight_history
from service.profile_fields import PROFILE_REBUILD_FIELDS
from service.weight_trend_alerts import evaluate_for_player
from core.weak_point_suggestions import suggest_weak_points_for_goals
from core.movement_restriction_suggestions import suggest_movement_restrictions
from core.movement_restrictions import restriction_for_candidate
from utils.equipment_access import map_equipment_access
from utils.preferred_name import validate_preferred_name
from core.movement_restrictions import validate_movement_restrictions


@dataclass(frozen=True)
class WeightEntryCommand:
    """Verified caller and submitted value for one Player weight write."""

    ledger_id: str
    player_account_id: str
    weight_kg: float


PROFILE_ANSWER_FIELDS = frozenset(
    {
        "gender",
        "proportions",
        "age",
        "height_cm",
        "weight_kg",
        "target_weight_kg",
        "rep_preference",
        "current_goal",
        "long_term_goal",
        "weekly_frequency",
        "training_age_years",
        "equipment_access",
        "injuries_or_limitations",
        "stress_and_sleep",
        "weak_points",
    }
)


class ProfileRevisionConflict(ValueError):
    """A profile changed while a replacement Program was being generated."""


def record_weight_entry(db: Any, ledger: Any, command: WeightEntryCommand) -> weight_history.WeightTrendPoint:
    """Writes a date-only weight entry, then evaluates its active Coach alert."""
    point = weight_history.record_weight(
        ledger, command.ledger_id, command.weight_kg
    )
    evaluate_for_player(db, command.player_account_id, ledger=ledger)
    return point


def get_profile(db: Any, ledger_id: str, ledger: Any | None = None) -> dict[str, Any] | None:
    with ledger_scope(db, ledger, ledger_id) as ledger:
        profile = _profile_with_preferred_name(ledger, ledger.get_player_profile())
        return {**profile, "injuries": injuries_service.list_injuries(ledger)} if profile else None


def _profile_with_preferred_name(
    ledger: Any, profile: dict[str, Any] | None
) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
        **profile,
        "preferred_name": ledger.get_assistant_memory().get("preferred_name"),
        "suggested_weak_points": suggest_weak_points_for_goals(
            profile.get("current_goal", ""), profile.get("long_term_goal", "")
        ),
        "suggested_movement_restrictions": suggest_movement_restrictions(
            profile.get("injuries_or_limitations", "")
        ),
    }


def update_profile(
    db: Any,
    ledger_id: str,
    payload: dict[str, Any],
    player_account_id: str | None = None,
    ledger: Any | None = None,
    *,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
    background_tasks: Any = None,
    inference_gate_held: bool = False,
) -> dict[str, Any]:
    """Upserts the profile; rebuilds when program-shaping inputs change.

    Player-controlled rebuild edits save atomically with the replacement program,
    so a quota refusal or generation failure leaves both unchanged. While an
    assigned coach owns the active program, profile edits still save without a
    rebuild and the response explains that a coach request is needed.
    """
    with ledger_scope(db, ledger, ledger_id) as ledger:
        profile = ledger.get_player_profile() or {}
        preferred_name_supplied = "preferred_name" in payload
        preferred_name = payload.get("preferred_name")
        if preferred_name_supplied and preferred_name is not None:
            validate_preferred_name(preferred_name)
        if preferred_name_supplied:
            payload = {
                key: value for key, value in payload.items() if key != "preferred_name"
            }
        if "equipment_access" in payload:
            payload = {**payload, "equipment_access": map_equipment_access(payload["equipment_access"])}
        if isinstance(payload.get("injuries_or_limitations"), str):
            payload = {**payload, "injuries_or_limitations": payload["injuries_or_limitations"].strip()}
        if "movement_restrictions" in payload:
            payload = {**payload, "movement_restrictions": validate_movement_restrictions(payload["movement_restrictions"])}
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
        weak_points_changed = (
            "weak_points" in payload
            and normalize_profile_value("weak_points", payload["weak_points"])
            != normalize_profile_value("weak_points", profile.get("weak_points"))
        )
        updated = {**profile, **payload}

        def persist_profile() -> None:
            nonlocal updated
            with ledger.ledger_transaction():
                latest = ledger.get_player_profile() or {}
                if program is not None:
                    changed_during_generation = [
                        field for field in PROFILE_REBUILD_FIELDS
                        if normalize_profile_value(field, latest.get(field, defaults.get(field)))
                        != normalize_profile_value(field, profile.get(field, defaults.get(field)))
                        and normalize_profile_value(field, latest.get(field, defaults.get(field)))
                        != normalize_profile_value(field, payload.get(field, profile.get(field, defaults.get(field))))
                    ]
                    if changed_during_generation:
                        raise ProfileRevisionConflict(
                            "The Training profile changed while the replacement Program was generated."
                        )
                updated = {**latest, **payload}
                if "weight_kg" in payload:
                    ledger.upsert_player_profile_with_weight_history(
                        updated,
                        weight_history.player_local_date(ledger, ledger_id).isoformat(),
                    )
                else:
                    ledger.upsert_player_profile(updated)
                for field in PROFILE_ANSWER_FIELDS & payload.keys():
                    ledger.save_intake_answer(field, payload[field], prefilled=False)
                if "injuries_or_limitations" in payload:
                    injuries_service.import_legacy_injury_text(
                        db,
                        ledger,
                        injuries_service.LegacyInjuryImport(
                            player_account_id,
                            payload["injuries_or_limitations"],
                            client,
                        ),
                    )

        restrictions_changed = (
            payload.get("movement_restrictions") is not None
            and payload.get("movement_restrictions") != profile.get("movement_restrictions", [])
        )
        movement_conflicts = _active_program_movement_conflicts(
            db, ledger, updated.get("movement_restrictions", [])
        ) if restrictions_changed else ()
        profile_change_alerts.record_profile_change(
            db,
            profile_change_alerts.ProfileChangeSnapshot(
                player_account_id=player_account_id,
                before_profile=profile,
                after_profile=updated,
                client=client,
                movement_restriction_conflicts=movement_conflicts,
            ),
        )
        program = None
        focus_explanation = None
        removed_exercises: list[dict[str, str]] = []
        program_blocked = False
        regeneration_offer_created = False
        if rebuild_requested:
            if player_controls_program(db, ledger, player_account_id):
                previous_program = ledger.get_active_program()
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
                        gate_already_held=inference_gate_held,
                    )
                    removed_exercises = _removed_restricted_exercises(
                        db, previous_program, program, updated.get("movement_restrictions", [])
                    )
                    # Keep the profile and generated Program atomic, after each
                    # model call has been written to the catalog.
                    with ledger.ledger_transaction():
                        persist_profile()
                        if program is not None:
                            ledger.save_training_program(
                                {
                                    **program.model_dump(),
                                    "design_version": PROGRAM_DESIGN_VERSION,
                                },
                                starting_position=None,
                            )
                            from service.focus_explanation import cross_day_focus_explanation
                            focus_explanation = cross_day_focus_explanation(ledger, program)
            else:
                program_blocked = True
                persist_profile()
        else:
            persist_profile()
        if (
            weak_points_changed
            and program is None
            and player_account_id
            and player_controls_program(db, ledger, player_account_id)
        ):
            active = ledger.get_active_program()
            if (
                active is not None
                and active.published_by_coach_account_id is None
                and active.source_template_id is None
            ):
                # Keep the single offer pending and show the latest change reason.
                ledger.record_program_regeneration_offer("focus_muscles_changed")
                regeneration_offer_created = True
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
        if preferred_name_supplied:
            if preferred_name is None:
                ledger.clear_preferred_name()
            else:
                ledger.set_assistant_memory("preferred_name", preferred_name)
        return {
            "profile": _profile_with_preferred_name(
                ledger, ledger.get_player_profile()
            ),
            "program_rebuilt": program is not None,
            "focus_cross_day_explanation": focus_explanation,
            "program": program,
            "program_blocked": program_blocked,
            "regeneration_offer_created": regeneration_offer_created,
            "program_message": COACH_CONTROLLED_ERROR if program_blocked else None,
            "removed_exercises": removed_exercises,
            "movement_restriction_conflicts": list(movement_conflicts),
            "coach_notified_of_movement_restrictions": bool(program_blocked and restrictions_changed),
        }


def _active_program_movement_conflicts(db: Any, ledger: Any, restrictions: list[str]) -> tuple[dict[str, Any], ...]:
    program = ledger.get_active_program()
    if program is None or not restrictions:
        return ()
    conflicts = []
    for day in program.days:
        for exercise in day.exercises:
            entry = db.get_exercise_library_entry(str(exercise.exercise_id)) or {}
            restriction = restriction_for_candidate(
                entry, str(getattr(exercise, "slot_key", "") or ""), restrictions
            )
            if restriction:
                conflicts.append({
                    "exercise_name": str(entry.get("name") or exercise.exercise_name),
                    "exercise_id": str(exercise.exercise_id),
                    "slot": str(getattr(exercise, "slot_key", "") or ""),
                    "restriction": restriction,
                })
    return tuple(conflicts)


def _removed_restricted_exercises(db: Any, before: Any, after: Any, restrictions: list[str]) -> list[dict[str, str]]:
    if before is None or after is None or not restrictions:
        return []
    remaining_ids = {str(exercise.exercise_id) for day in after.days for exercise in day.exercises}
    removed = []
    for day in before.days:
        for exercise in day.exercises:
            if str(exercise.exercise_id) in remaining_ids:
                continue
            entry = db.get_exercise_library_entry(str(exercise.exercise_id)) or {}
            restriction = restriction_for_candidate(
                entry, str(getattr(exercise, "slot_key", "") or ""), restrictions
            )
            if restriction:
                removed.append({
                    "exercise_name": str(exercise.exercise_name),
                    "slot": str(getattr(exercise, "slot_key", "") or ""),
                    "restriction": restriction,
                })
    return removed


def update_persona(
    db: Any, ledger_id: str, coach_tone: str, custom_instructions: str, ledger: Any | None = None
) -> dict[str, Any]:
    with ledger_scope(db, ledger, ledger_id) as ledger:
        ledger.update_player_persona(coach_tone, custom_instructions)
        return {
            "profile": _profile_with_preferred_name(
                ledger, ledger.get_player_profile()
            )
        }
