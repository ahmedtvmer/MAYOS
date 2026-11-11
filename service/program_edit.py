"""Permanent edits to a player's active program day."""

from copy import deepcopy
from agent.ProgramState import program_exercise_working_sets
from agent.program_blueprints import experience_level_for_training_age
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from agent.program_rationale import CHANGE_PROGRAM_EDIT_REMOVED, CHANGE_PROGRAM_EDIT_REORDERED, CHANGE_PROGRAM_EDIT_TRIMMED, CHANGE_PROGRAM_EDIT_ADDED, CHANGE_PROGRAM_EDIT_RAISED, SETS_PLAYER_EDIT
from agent.program_weeks import (
    flatten_program_days,
    find_program_day,
    normalize_program_weeks,
)
from service import analytics
from service.program_analytics import ProgramAnalyticsActor, capture_program_edited
from service.programs import COACH_CONTROLLED_ERROR, player_controls_program


class ProgramEditErrorCode(str, Enum):
    DAY_NOT_FOUND = "day_not_found"
    EXERCISE_NOT_ON_DAY = "exercise_not_on_day"
    DUPLICATE_EXERCISE = "duplicate_exercise"
    EMPTY_DAY = "empty_day"
    INVALID_SET_COUNT = "invalid_set_count"
    COACH_CONTROLLED = "coach_controlled"
    NO_ACTIVE_PROGRAM = "no_active_program"
    PROGRAM_CHANGED = "program_changed"
    EXERCISE_NOT_AVAILABLE = "exercise_not_available"
    DAY_LIMIT = "day_limit"
    MOVEMENT_RESTRICTED = "movement_restricted"
    CLEARANCE_EXCLUDED = "clearance_excluded"


PROGRAM_EDIT_ERRORS = {
    ProgramEditErrorCode.CLEARANCE_EXCLUDED: "That exercise is not cleared or has no recorded clearance for an active injury. I can't confirm it's safe.",
    ProgramEditErrorCode.DAY_NOT_FOUND: "That day is not part of your current program.",
    ProgramEditErrorCode.EXERCISE_NOT_ON_DAY: "That exercise is not in that day of your current program.",
    ProgramEditErrorCode.DUPLICATE_EXERCISE: "Each exercise entry can appear only once in a Program edit.",
    ProgramEditErrorCode.EMPTY_DAY: "A training day must keep at least one working-set exercise.",
    ProgramEditErrorCode.INVALID_SET_COUNT: "Working sets must be from 1 to 4.",
    ProgramEditErrorCode.COACH_CONTROLLED: COACH_CONTROLLED_ERROR,
    ProgramEditErrorCode.NO_ACTIVE_PROGRAM: "No active program.",
    ProgramEditErrorCode.PROGRAM_CHANGED: "The program changed since this edit was opened.",
    ProgramEditErrorCode.EXERCISE_NOT_AVAILABLE: "That exercise is not available in the Exercise library.",
    ProgramEditErrorCode.DAY_LIMIT: "A training day can have at most 10 working-set exercises.",
    ProgramEditErrorCode.MOVEMENT_RESTRICTED: "That exercise conflicts with a Movement restriction in your profile.",
}
PROGRAM_EDIT_MESSAGE_CODES = {
    ProgramEditErrorCode.CLEARANCE_EXCLUDED: "program.clearance_excluded.v1",
    ProgramEditErrorCode.DAY_NOT_FOUND: "program.edit.day_not_found.v1",
    ProgramEditErrorCode.EXERCISE_NOT_ON_DAY: "program.edit.exercise_not_on_day.v1",
    ProgramEditErrorCode.DUPLICATE_EXERCISE: "program.edit.duplicate_exercise.v1",
    ProgramEditErrorCode.EMPTY_DAY: "program.edit.empty_day.v1",
    ProgramEditErrorCode.INVALID_SET_COUNT: "program.edit.invalid_set_count.v1",
    ProgramEditErrorCode.COACH_CONTROLLED: "program.coach_controls.v1",
    ProgramEditErrorCode.NO_ACTIVE_PROGRAM: "program.no_active.v1",
    ProgramEditErrorCode.PROGRAM_CHANGED: "program.edit.changed.v1",
    ProgramEditErrorCode.EXERCISE_NOT_AVAILABLE: "program.edit.exercise_not_available.v1",
    ProgramEditErrorCode.DAY_LIMIT: "program.edit.day_limit.v1",
    ProgramEditErrorCode.MOVEMENT_RESTRICTED: "program.movement_restricted.v1",
}


@dataclass(frozen=True)
class ProgramEditExercise:
    source_index: int
    exercise_id: str
    target_sets: int
    show_all_equipment: bool = False
    prescription: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProgramEdit:
    day_name: str
    expected_active_version: int
    exercises: list[ProgramEditExercise]
    player_account_id: str
    actor: ProgramAnalyticsActor
    week_order: int | None = None
    day_order: int | None = None
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT
    preview: bool = False
    via: str = "program_tab"


@dataclass(frozen=True)
class _PreparedProgramEdit:
    program_copy: dict[str, Any]
    day: dict[str, Any]


def edit_active_program_day(db: Any, ledger: Any, edit_request: ProgramEdit) -> dict[str, Any]:
    active, failure = _active_program_for_edit(db, ledger, edit_request)
    if failure:
        return failure
    current_position = ledger.get_program_position(active)
    if edit_request.week_order is None:
        edit_request = replace(edit_request, week_order=current_position.current_week)
    prepared, failure = _prepare_program_edit(active, edit_request)
    if failure:
        return failure
    from service.exercise_clearances import ExerciseClearancePolicy
    policy = ExerciseClearancePolicy(ledger)
    for item in edit_request.exercises:
        # Retaining an existing restricted slot is allowed; new selections are not.
        original = prepared.day["exercises"]
        if item.source_index >= 0 and original[item.source_index]["exercise_id"] == item.exercise_id:
            continue
        candidate = db.get_exercise_library_entry(item.exercise_id)
        if candidate and not policy.allows(candidate):
            return _failure(ProgramEditErrorCode.CLEARANCE_EXCLUDED)
    if len(edit_request.exercises) > 10:
        return _failure(ProgramEditErrorCode.DAY_LIMIT)
    if any(item.source_index < 0 for item in edit_request.exercises):
        profile = ledger.get_player_profile() or {}
        from utils.equipment_access import equipment_access_allows
        for item in edit_request.exercises:
            if item.source_index >= 0:
                continue
            candidate = db.get_exercise_library_entry(item.exercise_id)
            if (candidate is None or not db.is_exercise_library_exercise_visible(item.exercise_id)
                    or (not item.show_all_equipment and not equipment_access_allows(profile.get("equipment_access"), candidate.get("equipment")))):
                return _failure(ProgramEditErrorCode.EXERCISE_NOT_AVAILABLE)
    previous_version = active.version
    if _is_unchanged(prepared.day["exercises"], edit_request.exercises):
        week_order = int(prepared.day.get("week_order", edit_request.week_order or current_position.current_week))
        warnings = _volume_warnings(
            ledger, active.model_dump(), ledger.get_player_profile() or {}, week_order
        )
        preview_payload = (
            {**active.model_dump(), "previous_version": previous_version}
            if edit_request.preview
            else _updated_program_result(db, ledger, previous_version)
        )
        return {**preview_payload, "volume_warnings": warnings}
    _apply_program_edit(prepared, edit_request.exercises)
    _prepare_added_prescriptions(db, ledger, prepared.day, edit_request.exercises)
    restriction_failure = _restricted_program_edit(db, ledger, prepared.day)
    if restriction_failure:
        return restriction_failure
    from service.program_rationale_changes import (
        carry_program_rationale,
        occurrence_mappings_for_days,
    )
    old_days = flatten_program_days(normalize_program_weeks(active))
    new_days = prepared.program_copy.get("days", [])
    day_key = (int(prepared.day.get("week_order", edit_request.week_order or 1)), int(prepared.day.get("day_order", edit_request.day_order or 1)))
    old_day = next((day for day in old_days if (int(day.get("week_order", 1)), int(day.get("day_order", 0))) == day_key), None)
    new_day = next((day for day in new_days if (int(day.get("week_order", 1)), int(day.get("day_order", 0))) == day_key), None)
    source_positions: dict[tuple[int, int], dict[int, int]] = {}
    changes_by_target: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    removed_entries = []
    if old_day and new_day:
        source_positions[day_key] = {}
        for target_position, requested in enumerate(edit_request.exercises, 1):
            if requested.source_index < 0:
                prescription = prepared.day["exercises"][target_position - 1].get("program_edit_prescription_rationale", {})
                params = {"exercise_id": requested.exercise_id, "by": "player", "prescription": prescription}
                if edit_request.via == "chat":
                    params["via"] = "chat"
                changes_by_target[(*day_key, target_position)] = [{"code": CHANGE_PROGRAM_EDIT_ADDED, "params": params}]
                continue
            from_position = requested.source_index + 1
            source_positions[day_key][target_position] = from_position
            old = old_day["exercises"][requested.source_index]
            new = new_day["exercises"][target_position - 1]
            entries = []
            before = int(old.get("target_sets", 0))
            after = int(new.get("target_sets", 0))
            if before != after:
                params = {"from_sets": before, "to_sets": after}
                if edit_request.via == "chat":
                    params.update({"by": "player", "via": "chat"})
                entries.append({"code": CHANGE_PROGRAM_EDIT_RAISED if after > before else CHANGE_PROGRAM_EDIT_TRIMMED, "params": params})
            if from_position != target_position:
                params = {"from_position": from_position, "to_position": target_position}
                if edit_request.via == "chat":
                    params.update({"by": "player", "via": "chat"})
                entries.append({"code": CHANGE_PROGRAM_EDIT_REORDERED, "params": params})
            if entries:
                changes_by_target[(*day_key, target_position)] = entries
        kept_positions = {item.source_index + 1 for item in edit_request.exercises if item.source_index >= 0}
        removed_entries = [
            {"week_order": day_key[0], "day_order": day_key[1],
             "exercise_id": str(exercise["exercise_id"]), "code": CHANGE_PROGRAM_EDIT_REMOVED,
             **({"params": {"by": "player", "via": "chat"}} if edit_request.via == "chat" else {})}
            for position, exercise in enumerate(old_day["exercises"], 1)
            if position not in kept_positions
        ]
    mappings = occurrence_mappings_for_days(
        old_days, new_days, source_positions=source_positions,
        changes_by_target=changes_by_target,
    )
    for exercise in prepared.day["exercises"]:
        exercise.pop("program_edit_prescription_rationale", None)
    carry_program_rationale(active, prepared.program_copy,
                            occurrence_mappings=mappings, removed_entries=removed_entries)
    warnings = _volume_warnings(ledger, prepared.program_copy, ledger.get_player_profile() or {}, day_key[0])
    if edit_request.preview:
        return {
            **prepared.program_copy,
            "previous_version": active.version,
            "volume_warnings": warnings,
        }
    prepared.program_copy.pop("created_at", None)
    ledger.save_training_program(
        prepared.program_copy,
        published_by_coach_account_id=None,
        starting_position=current_position,
    )
    updated = ledger.get_active_program()
    if updated is not None:
        capture_program_edited(edit_request.actor, updated, client=edit_request.client)
    return {**_updated_program_result(db, ledger, previous_version), "volume_warnings": warnings}


def _volume_warnings(ledger: Any, program: dict[str, Any], profile: dict[str, Any], current_week: int) -> list[dict[str, Any]]:
    from agent.focus_muscles import FOCUS_REVIEW_MUSCLES
    from agent.program_weeks import normalize_program_weeks
    from agent.ProgramState import program_exercise_working_sets
    level = experience_level_for_training_age(float(profile.get("training_age_years") or 0))
    ceilings = {"beginner": 8, "intermediate": 10, "advanced": 13}
    weeks = normalize_program_weeks(program)
    days = next((week["days"] for week in weeks if int(week["week_order"]) == current_week), weeks[0]["days"] if weeks else [])
    exercises = [exercise for day in days for exercise in day.get("exercises", [])]
    targets = ledger.volume_review_exercise_targets(sorted({str(ex["exercise_id"]) for ex in exercises}))
    totals: dict[str, int] = {}
    for exercise in exercises:
        muscle = targets.get(str(exercise["exercise_id"]))
        if muscle:
            totals[muscle] = totals.get(muscle, 0) + program_exercise_working_sets(exercise)
    focus_keys = {str(item.get("muscle", "")) for item in (program.get("program_rationale") or {}).get("focus_muscles", []) if isinstance(item, dict)}
    focus_groups = {group.lower() for key in focus_keys for group in FOCUS_REVIEW_MUSCLES.get(key, set())}
    return [{"muscle": muscle, "weekly_sets": sets, "ceiling": round(ceilings[level] * (1.3 if muscle.lower() in focus_groups else 1.0))}
            for muscle, sets in sorted(totals.items())
            if sets > round(ceilings[level] * (1.3 if muscle.lower() in focus_groups else 1.0))]


def _restricted_program_edit(db: Any, ledger: Any, day: dict[str, Any]) -> dict[str, Any] | None:
    from core.movement_restrictions import is_movement_restricted

    restrictions = (ledger.get_player_profile() or {}).get("movement_restrictions", ())
    for exercise in day["exercises"]:
        entry = db.get_exercise_library_entry(str(exercise["exercise_id"]))
        if is_movement_restricted(
            entry or exercise, str(exercise.get("slot_key") or ""), restrictions
        ):
            return _failure(ProgramEditErrorCode.MOVEMENT_RESTRICTED)
    return None


def _active_program_for_edit(db: Any, ledger: Any, edit_request: ProgramEdit) -> tuple[Any, dict[str, Any] | None]:
    if not player_controls_program(db, ledger, edit_request.player_account_id):
        return None, _failure(ProgramEditErrorCode.COACH_CONTROLLED)
    active = ledger.get_active_program()
    if active is None:
        return None, _failure(ProgramEditErrorCode.NO_ACTIVE_PROGRAM)
    if active.version != edit_request.expected_active_version:
        return None, _failure(ProgramEditErrorCode.PROGRAM_CHANGED)
    return active, None


def _prepare_program_edit(
    active: Any,
    edit_request: ProgramEdit,
) -> tuple[_PreparedProgramEdit | None, dict[str, Any] | None]:
    program_copy = active.model_dump()
    weeks = normalize_program_weeks(program_copy)
    week_order = edit_request.week_order or 1
    day = find_program_day(
        weeks,
        week_order,
        day_order=edit_request.day_order,
        day_name=edit_request.day_name,
    )
    if day is None:
        return None, _failure(ProgramEditErrorCode.DAY_NOT_FOUND)
    if not edit_request.exercises:
        return None, _failure(ProgramEditErrorCode.EMPTY_DAY)
    failure = _validate_program_edit(day["exercises"], edit_request.exercises)
    if failure:
        return None, failure
    program_copy["weeks"] = weeks
    program_copy["days"] = flatten_program_days(weeks)
    return _PreparedProgramEdit(program_copy, day), None


def _validate_program_edit(
    current_exercises: list[dict[str, Any]],
    requested_exercises: list[ProgramEditExercise],
) -> dict[str, Any] | None:
    requested_indexes = [exercise.source_index for exercise in requested_exercises if exercise.source_index >= 0]
    if len(set(requested_indexes)) != len(requested_indexes):
        return _failure(ProgramEditErrorCode.DUPLICATE_EXERCISE)
    by_exercise: dict[str, list[ProgramEditExercise]] = {}
    for exercise in requested_exercises:
        by_exercise.setdefault(exercise.exercise_id, []).append(exercise)
    if any(len(items) > 1 and any(item.source_index < 0 for item in items) for items in by_exercise.values()):
        return _failure(ProgramEditErrorCode.DUPLICATE_EXERCISE)
    if any(
        exercise.source_index >= len(current_exercises)
        or str(current_exercises[exercise.source_index]["exercise_id"]) != exercise.exercise_id
        for exercise in requested_exercises if exercise.source_index >= 0
    ):
        return _failure(ProgramEditErrorCode.EXERCISE_NOT_ON_DAY)
    for item in requested_exercises:
        maximum_sets = 4
        minimum_sets = 1
        if item.source_index >= 0:
            current = current_exercises[item.source_index]
            maximum_sets = max(maximum_sets, program_exercise_working_sets(current))
            minimum_sets += sum(
                int(group.get("sets", 0))
                for group in (current.get("set_groups") or [])[1:]
            )
        if item.target_sets < minimum_sets or item.target_sets > maximum_sets:
            return _failure(ProgramEditErrorCode.INVALID_SET_COUNT)
    return None


def _is_unchanged(
    current_exercises: list[dict[str, Any]],
    requested_exercises: list[ProgramEditExercise],
) -> bool:
    return len(current_exercises) == len(requested_exercises) and all(
        requested.source_index == index
        and program_exercise_working_sets(current) == requested.target_sets
        for index, (current, requested) in enumerate(zip(current_exercises, requested_exercises))
    )


def _apply_program_edit(
    prepared: _PreparedProgramEdit,
    requested_exercises: list[ProgramEditExercise],
) -> None:
    current_exercises = prepared.day["exercises"]
    prepared.day["exercises"] = []
    for requested in requested_exercises:
        if requested.source_index < 0:
            prepared.day["exercises"].append({"exercise_id": requested.exercise_id, "target_sets": requested.target_sets})
            continue
        exercise_copy = deepcopy(current_exercises[requested.source_index])
        groups = exercise_copy.get("set_groups") or []
        if groups:
            backoff_sets = sum(int(group.get("sets", 0)) for group in groups[1:])
            groups[0]["sets"] = requested.target_sets - backoff_sets
            exercise_copy["set_groups"] = groups
            exercise_copy["target_sets"] = groups[0]["sets"]
        else:
            exercise_copy["target_sets"] = requested.target_sets
        prepared.day["exercises"].append(exercise_copy)


def _prepare_added_prescriptions(db: Any, ledger: Any, day: dict[str, Any], requested: list[ProgramEditExercise]) -> None:
    from agent.program_rules import exercise_mechanic, get_target_rep_window
    profile = ledger.get_player_profile() or {}
    from agent.program_blueprints import (
        REST_SECONDS_RANGES_BY_CLASS,
        TARGET_RIR_BY_EXPERIENCE_AND_CLASS,
        WARMUP_SET_RANGES_BY_CLASS,
    )
    level = experience_level_for_training_age(float(profile.get("training_age_years") or 0))
    for exercise, item in zip(day["exercises"], requested):
        if item.source_index >= 0:
            continue
        if item.prescription is not None:
            exercise.update(deepcopy(item.prescription))
            continue
        row = db.get_exercise_library_entry(item.exercise_id)
        mechanic = exercise_mechanic(row)
        prescription_class = "calf_abs" if (row.get("primary_muscle") or "").lower() in {"calves", "abs"} else ("medium_compound" if mechanic == "compound" else "isolation")
        rir = TARGET_RIR_BY_EXPERIENCE_AND_CLASS[(level, prescription_class)]
        warmup_sets = WARMUP_SET_RANGES_BY_CLASS[prescription_class][0]
        rest_min, rest_max = REST_SECONDS_RANGES_BY_CLASS[prescription_class]
        reps = get_target_rep_window(mechanic, profile.get("rep_preference", "balanced"))
        exercise.update({"exercise_name": row["name"], "target_reps_min": reps[0], "target_reps_max": reps[1],
            "target_rpe": 10 - rir, "rest_seconds": (rest_min + rest_max) // 2, "warmup_sets": warmup_sets,
            "set_groups": [{"sets": item.target_sets, "reps_min": reps[0], "reps_max": reps[1], "target_rir": rir}]})
        exercise["program_edit_prescription_rationale"] = {
            "sets": {"code": SETS_PLAYER_EDIT, "params": {"count": item.target_sets}},
            "reps": {"code": "reps.rep_preference", "params": {"rep_preference": profile.get("rep_preference", "balanced"), "rep_min": reps[0], "rep_max": reps[1], "movement_class": mechanic}},
            "rir": {"code": "rir.experience_level", "params": {"experience_level": level, "target_rir": rir, "prescription_class": prescription_class}},
            "rest": {"code": "rest.movement_class", "params": {"rest_seconds": (rest_min + rest_max) // 2, "prescription_class": prescription_class}},
            "warmup": {"code": "warmup.template", "params": {"count": warmup_sets, "prescription_class": prescription_class}},
        }


def _updated_program_result(db: Any, ledger: Any, previous_version: int) -> dict[str, Any]:
    updated = ledger.get_active_program()
    if updated is None:
        return _failure(ProgramEditErrorCode.NO_ACTIVE_PROGRAM)
    result = updated.model_dump()
    from service.exercise_clearances import annotate_program
    annotate_program(db, ledger, result)
    return {**result, "previous_version": previous_version}


def edit_active_program_days(db: Any, ledger: Any, edits: list[ProgramEdit], *, baseline_program: Any = None) -> dict[str, Any]:
    """Validates every requested day then publishes all edits as one version."""
    if not edits:
        return _failure(ProgramEditErrorCode.EMPTY_DAY)
    active = ledger.get_active_program()
    if active is None:
        return _failure(ProgramEditErrorCode.NO_ACTIVE_PROGRAM)
    expected = edits[0].expected_active_version
    if any(edit.expected_active_version != expected for edit in edits):
        return _failure(ProgramEditErrorCode.PROGRAM_CHANGED)
    class PreviewLedger:
        def __init__(self, current):
            self.current = current
        def get_active_program(self):
            return self.current
        def __getattr__(self, name):
            return getattr(ledger, name)

    preview_ledger = PreviewLedger(active)
    warnings: list[dict[str, Any]] = []
    result: dict[str, Any] = active.model_dump()
    for edit in edits:
        result = edit_active_program_day(
            db, preview_ledger, replace(edit, preview=True, via="chat")
        )
        if "code" in result:
            return result
        warnings.extend(result.get("volume_warnings", []))
        from agent.ProgramState import PersistedProgramSchema
        preview_ledger.current = PersistedProgramSchema.model_validate(result)
    result["volume_warnings"] = list({
        (item.get("muscle"), item.get("weekly_sets"), item.get("ceiling")): item
        for item in warnings
    }.values())
    result["previous_version"] = active.version
    if all(edit.preview for edit in edits):
        from service.exercise_clearances import annotate_program
        annotate_program(db, ledger, result)
        return result
    baseline = baseline_program or active
    unchanged = (_same_program_content(baseline, result) if baseline_program is not None else
        _same_program_exercises(baseline.model_dump().get("days", []), result.get("days", [])))
    if unchanged:
        return {**_updated_program_result(db, ledger, active.version), "volume_warnings": list({
            (item.get("muscle"), item.get("weekly_sets"), item.get("ceiling")): item
            for item in warnings
        }.values())}
    position = ledger.get_program_position(active)
    result.pop("previous_version", None)
    result.pop("volume_warnings", None)
    result.pop("created_at", None)
    ledger.save_training_program(
        result, published_by_coach_account_id=None, starting_position=position
    )
    updated = ledger.get_active_program()
    if updated is not None:
        capture_program_edited(edits[0].actor, updated, client=edits[0].client)
    return {**_updated_program_result(db, ledger, active.version), "volume_warnings": list({
        (item.get("muscle"), item.get("weekly_sets"), item.get("ceiling")): item
        for item in warnings
    }.values())}


def _same_program_exercises(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> bool:
    def signature(days):
        return [
            (int(day.get("week_order", 1)), int(day.get("day_order", 0)),
             [(str(item.get("exercise_id")), program_exercise_working_sets(item))
              for item in day.get("exercises", [])])
            for day in days
        ]
    return signature(before) == signature(after)


def _same_program_content(before: Any, after: dict[str, Any]) -> bool:
    before_payload = before.model_dump()
    ignored = {"version", "created_at", "previous_version", "volume_warnings"}
    return ({key: value for key, value in before_payload.items() if key not in ignored}
            == {key: value for key, value in after.items() if key not in ignored})


def _failure(code: ProgramEditErrorCode) -> dict[str, Any]:
    return {
        "code": code,
        "error": PROGRAM_EDIT_ERRORS[code],
        "message_code": PROGRAM_EDIT_MESSAGE_CODES[code],
    }
