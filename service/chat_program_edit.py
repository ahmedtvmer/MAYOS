"""Planning and resolving confirmed Player chat Program edits."""

import re
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from agent.ProgramState import program_exercise_working_sets
from agent.focus_muscles import FOCUS_EXTRA_TABLE
from agent.program_generator import (
    DayGenerationContext,
    _eligible_focus_candidate,
)
from agent.program_blueprints import experience_level_for_training_age
from service.program_analytics import ProgramAnalyticsActor
from service.program_edit import (
    ProgramEdit,
    ProgramEditExercise,
    edit_active_program_days,
)
from service.programs import player_controls_program
from utils.equipment_access import COMMERCIAL_GYM, map_equipment_access


MUSCLE_TERMS = {
    "biceps": r"\b(?:bi|biceps?)\b",
    "triceps": r"\b(?:tri|triceps?)\b",
    "side_delts": r"\b(?:side\s*delt(?:s)?|lateral\s*raise(?:s)?)\b",
    "forearms": r"\bforearms?\b",
    "abs": r"\babs?\b",
}
LOWER_TERMS = r"\b(?:leg|legs|lower|lower body)\b|أيام الرجل|يوم الرجل|الجزء السفلي"


def plan_chat_program_edit(
    db: Any, ledger: Any, player_account_id: str, query: str,
    *, base_program: Any | None = None,
) -> dict[str, Any]:
    if not player_controls_program(db, ledger, player_account_id):
        return {"error": "coach_controls"}
    context = _active_program_edit_context(ledger, base_program)
    if context is None:
        return {"error": "no_program"}
    _active_program, program, planning_ledger, week_order, days = context
    target_days = _resolve_edit_days(db, days, query)
    if not target_days:
        return {"error": "day_not_found"}
    operation = _parse_edit_operation(query)
    if not operation["muscles"] and operation["named_request"] is None and operation["named_remove"] is None and operation["named_change"] is None:
        return {"error": "exercise_not_found"}
    planning = _EditPlanningContext(
        db, ledger, planning_ledger, program, player_account_id, week_order,
        days, target_days, query, operation,
    )
    requests = _build_requested_day_edits(planning)
    if "error" in requests:
        return requests
    return _build_preview_proposal(planning, requests, base_program)


@dataclass
class _EditPlanningContext:
    db: Any
    player_ledger: Any
    planning_ledger: Any
    program: Any
    player_account_id: str
    week_order: int
    days: list[dict[str, Any]]
    target_days: list[dict[str, Any]]
    query: str
    operation: dict[str, Any]


def _build_requested_day_edits(context: _EditPlanningContext) -> dict[str, Any]:
    db, ledger, operation = context.db, context.player_ledger, context.operation
    move_sources = _move_side_delt_sources(
        db, context.days, context.target_days, context.query, operation["required"]
    )
    if move_sources.get("_error"):
        return {"error": "ambiguous_source", "message": "Name one source day for that move."}
    moved_ids = [entry["exercise_id"] for entry in move_sources.values()]
    edit_days = sorted(
        context.target_days + [day for day in context.days if int(day["day_order"]) in move_sources],
        key=lambda day: int(day["day_order"]),
    )
    profile = ledger.get_player_profile() or {}
    generation_context = DayGenerationContext(
        equipment_access=map_equipment_access(profile.get("equipment_access", COMMERCIAL_GYM)),
        limitations=profile.get("injuries_or_limitations", "None"),
        rep_preference=profile.get("rep_preference", "balanced"), recovery_cut=False,
        experience_level=experience_level_for_training_age(float(profile.get("training_age_years") or 0)),
    )
    return _collect_requested_day_edits(context, edit_days, move_sources, moved_ids, generation_context)


def _collect_requested_day_edits(context, edit_days, move_sources, moved_ids, generation_context):
    db, ledger = context.db, context.player_ledger
    context.operation["target_days"] = context.target_days
    operation = context.operation
    name = operation["named_request"]
    candidates = _named_exercise_candidates(db, ledger, name, generation_context)
    if name and not candidates:
        return {"error": "exercise_unavailable", "message": "That exercise is not available with your Equipment access."}
    mentioned = operation["mentioned_muscles"]
    muscle_ids = _exercise_ids_for_muscles(db, mentioned) if mentioned else set()
    removed_ids = _scoped_exercise_ids(db, operation["named_remove"], operation["named_change"],
                                       mentioned, muscle_ids, operation)
    if "error" in removed_ids:
        return removed_ids
    used_ids = {str(item.get("exercise_id")) for day in context.days for item in day.get("exercises", [])}
    used_ids.difference_update(moved_ids)
    requested_days, optional_rows, request_error = _assemble_day_edits(
        context, edit_days, move_sources, candidates, used_ids, removed_ids, generation_context
    )
    if request_error:
        return request_error
    error = _validate_selected_regions(context, requested_days)
    if error:
        return error
    if operation["named_change"] and not any(
        item.exercise_id in removed_ids["changed"] for _day, items in requested_days for item in items
    ):
        return {"error": "exercise_not_on_day"}
    return {"base_requests": requested_days, "optional_rows": optional_rows,
            "move_sources": move_sources}


def _scoped_exercise_ids(db, named_remove, named_change, mentioned, muscle_ids, operation):
    removed = (_operation_scope_ids(db, named_remove, mentioned, muscle_ids)
               if named_remove else (muscle_ids if operation["is_remove"] else set()))
    changed = (_operation_scope_ids(db, named_change[0], mentioned, muscle_ids)
               if named_change else (muscle_ids if operation["is_change"] else set()))
    if (named_remove and not removed) or (named_change and not changed) or (
        (operation["is_remove"] or operation["is_change"]) and mentioned and not muscle_ids
    ):
        return {"error": "exercise_not_found"}
    if operation["is_remove"] and not any(
        str(item.get("exercise_id")) in removed
        for day in operation.get("target_days", []) for item in day.get("exercises", [])
    ):
        return {"error": "exercise_not_on_day"}
    return {"removed": removed, "changed": changed}


def _operation_scope_ids(db, name, mentioned, muscle_ids):
    normalized = re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip()
    if normalized in mentioned or normalized in {"bi", "tri", "side delt", "forearm", "abs"}:
        return set(muscle_ids)
    return {str(row["id"]) for row in (db.find_exercises_by_name(name, limit=10) or [])}


def _assemble_day_edits(context, edit_days, move_sources, candidates, used_ids, scoped_ids, generation_context):
    operation = context.operation
    moved_target = False
    moved_source = next(iter(move_sources.values()), None)
    requested_days, optional_rows = [], []
    for day in edit_days:
        requested = _retained_exercises(day, move_sources, scoped_ids["removed"],
                                        scoped_ids["changed"], operation)
        if day in context.target_days:
            error = _append_requested_exercises(
                context, day, requested, candidates, used_ids, move_sources,
                moved_source, moved_target, generation_context, optional_rows,
            )
            if error:
                return [], [], error
            if operation["required"] and "side_delts" in operation["required"] and move_sources:
                moved_target = True
        requested_days.append((day, requested))
    if operation["is_remove"] and not scoped_ids["removed"]:
        return [], [], {"error": "exercise_not_on_day"}
    return requested_days, optional_rows, None


def _retained_exercises(day, move_sources, removed_ids, changed_ids, operation):
    source = move_sources.get(int(day["day_order"]))
    return [ProgramEditExercise(index, str(row["exercise_id"]),
        operation["named_change"][1] if operation["named_change"] and str(row["exercise_id"]) in changed_ids
        else program_exercise_working_sets(row)) for index, row in enumerate(day.get("exercises", []))
        if (source is None or index != source["source_index"])
        and not (day in operation.get("target_days", []) and str(row["exercise_id"]) in removed_ids)]


def _append_requested_exercises(context, day, requested, candidates, used_ids, move_sources,
                                moved_source, moved_target, generation_context, optional_rows):
    name = context.operation["named_request"]
    if name:
        candidate = next((row for row in candidates if str(row["id"]) not in used_ids), None)
        if candidate is None:
            return {"error": "exercise_unavailable", "message": "No unused available variation was found."}
        requested.append(ProgramEditExercise(-1, str(candidate["id"]), 2))
        used_ids.add(str(candidate["id"]))
    for muscle in context.operation["required"]:
        candidate, _slot = _select_focus_candidate(muscle, used_ids, generation_context, context.player_ledger)
        exercise_id = moved_source["exercise_id"] if muscle == "side_delts" and move_sources and not moved_target else (str(candidate["id"]) if candidate else None)
        if exercise_id is None:
            return {"error": "exercise_unavailable", "muscle": muscle}
        requested.append(ProgramEditExercise(-1, exercise_id,
            moved_source["target_sets"]
            if moved_source is not None and exercise_id == moved_source["exercise_id"]
            else 2))
        used_ids.add(exercise_id)
    for muscle in context.operation["optional_muscles"]:
        candidate, slot = _select_focus_candidate(muscle, used_ids, generation_context, context.player_ledger)
        if candidate is not None:
            used_ids.add(str(candidate["id"]))
            optional_rows.append({"day_order": int(day["day_order"]), "week_order": context.week_order,
                "muscle": muscle, "exercise_id": str(candidate["id"]),
                "name": candidate.get("display_name") or candidate.get("name"), "sets": 2, "slot": slot})
    return None


def _validate_selected_regions(context, requested_days):
    from agent.program_rules import exercise_mechanic
    lower_muscles = {"quads", "hamstrings", "glutes", "calves", "adductors"}
    for day, requested in requested_days:
        day_region = "lower" if _is_lower_day(context.db, day) else "upper"
        for item in requested:
            if item.source_index >= 0:
                continue
            candidate = context.db.get_exercise_library_entry(item.exercise_id) or {}
            muscle = str(candidate.get("primary_muscle") or candidate.get("target_muscle") or "").casefold()
            exercise_region = "lower" if muscle in lower_muscles else "upper"
            if exercise_mechanic(candidate) == "compound" and exercise_region != day_region:
                name = candidate.get("display_name") or candidate.get("name") or "That exercise"
                return {"error": "opposite_region_compound",
                        "message": f"{name} is a compound lift; place it on a {exercise_region} day."}
    return None


def _build_preview_proposal(context, requests, base_program):
    program, days = context.program, requests["base_requests"]
    edits = [_build_edit(day, items, program.version, context.player_account_id, context.week_order)
             for day, items in days]
    preview = edit_active_program_days(context.db, context.planning_ledger, edits)
    if "code" in preview:
        return {"error": preview["code"], "message": preview.get("message")}
    changed_ids = set()
    for day, items in days:
        for item in items:
            original = day.get("exercises", [])
            if item.source_index < 0 or item.target_sets != program_exercise_working_sets(original[item.source_index]):
                changed_ids.add((context.week_order, int(day["day_order"]), item.exercise_id))
    selected_preview_days = preview.get("days", []) if base_program is not None else [day for day, _ in days]
    preview_days = _preview_days(preview, selected_preview_days, requested_ids=changed_ids)
    optional_rows = requests["optional_rows"]
    if optional_rows:
        preview, preview_days, optional_rows = _preview_optional_edits(
            context, days, optional_rows, preview, preview_days
        )
        if base_program is not None:
            preview_days = _preview_days(preview, preview.get("days", []),
                {option["exercise_id"] for option in optional_rows}, requested_ids=changed_ids)
    proposal = {"expected_version": program.version,
        "original_query": context.query,
        **({"rebuild_base_program": base_program.model_dump() if hasattr(base_program, "model_dump") else base_program} if base_program is not None else {}),
        "rebuild_label": base_program is not None,
        **({"rebuild_frequency": program.weekly_frequency} if base_program is not None else {}),
        "week_order": context.week_order,
        "days": [{"day_name": day["day_name"], "day_order": int(day["day_order"]),
            "week_order": context.week_order, "exercises": [_exercise_payload(item) for item in items]}
            for day, items in days],
        "optional": optional_rows, "preview_days": preview_days,
        "profile_fingerprint": _profile_fingerprint(context.player_ledger.get_player_profile() or {}),
        "warnings": preview.get("volume_warnings", [])}
    prescriptions = {(int(day.get("week_order", 1)), int(day["day_order"]), str(row.get("exercise_id"))): row
        for day in preview.get("days", []) for row in day.get("exercises", [])}
    for day in proposal["days"]:
        for exercise in day["exercises"]:
            if exercise["source_index"] < 0:
                row = prescriptions.get((int(day["week_order"]), int(day["day_order"]), exercise["exercise_id"]))
                if row:
                    exercise["prescription"] = _stored_prescription(row)
    return {"proposal": proposal, "version": program.version}


def _preview_optional_edits(context, days, optional_rows, preview, preview_days):
    by_order = {int(day["day_order"]): list(items) for day, items in days}
    for option in optional_rows:
        by_order[option["day_order"]].append(ProgramEditExercise(-1, option["exercise_id"], 2))
    optional_edits = [_build_edit(day, by_order[int(day["day_order"])], context.program.version,
        context.player_account_id, context.week_order) for day, _ in days]
    optional_preview = edit_active_program_days(context.db, context.planning_ledger, optional_edits)
    if "code" in optional_preview:
        return preview, preview_days, []
    selected = {row["exercise_id"] for row in optional_rows}
    preview_days = _preview_days(optional_preview, [day for day, _ in days], selected)
    prescriptions = {(int(day["day_order"]), str(exercise.get("exercise_id"))): exercise
        for day in optional_preview.get("days", []) for exercise in day.get("exercises", [])}
    for option in optional_rows:
        row = prescriptions.get((option["day_order"], option["exercise_id"]), {})
        option.update({"reps_min": row.get("target_reps_min"), "reps_max": row.get("target_reps_max"),
            "rir": 10 - float(row.get("target_rpe", 8.5)), "rest_seconds": row.get("rest_seconds"),
            "prescription": _stored_prescription(row) if row else None})
    preview["volume_warnings"] = optional_preview.get("volume_warnings", preview.get("volume_warnings", []))
    return preview, preview_days, optional_rows


class _PlanningLedger:
    def __init__(self, ledger: Any, current: Any):
        self._ledger = ledger
        self.current = current

    def get_active_program(self):
        return self.current

    def save_training_program(self, *args, **kwargs):
        saved = self._ledger.save_training_program(*args, **kwargs)
        self.current = self._ledger.get_active_program()
        return saved

    def __getattr__(self, name):
        return getattr(self._ledger, name)


def _active_program_edit_context(ledger, base_program):
    active = ledger.get_active_program()
    if active is None:
        return None
    program = active
    if base_program is not None:
        from agent.ProgramState import PersistedProgramSchema
        payload = base_program.model_dump() if hasattr(base_program, "model_dump") else dict(base_program)
        payload["version"] = active.version
        program = PersistedProgramSchema.model_validate(payload)
    position = ledger.get_program_position(active)
    week = 1 if base_program is not None else int(position.current_week)
    days = [day for day in program.model_dump().get("days", [])
            if int(day.get("week_order", 1)) == week]
    return active, program, _PlanningLedger(ledger, program), week, days


def _resolve_edit_days(db, days, query):
    lower_requested = bool(re.search(LOWER_TERMS, query, re.IGNORECASE))
    upper_requested = bool(re.search(r"\b(?:upper|upper body)\b|أيام الجزء العلوي", query, re.IGNORECASE))
    region = "lower" if lower_requested else "upper" if upper_requested else None
    targets = ([day for day in days if (_is_lower_day(db, day) if region == "lower"
                else _is_upper_day(db, day))] if region else [
        day for day in days if str(day.get("day_name", "")).casefold() in query.casefold()
    ])
    return targets


def _parse_edit_operation(query):
    mentioned = [muscle for muscle, pattern in MUSCLE_TERMS.items()
                 if re.search(pattern, query, re.IGNORECASE)]
    arabic = {"biceps": r"باي|بايسبس", "triceps": r"تراي|ترايسبس",
              "side_delts": r"كتف\s*جانبي|الكتف\s*الجانبي",
              "forearms": r"سواعد|الساعد"}
    mentioned.extend(muscle for muscle, pattern in arabic.items()
                      if re.search(pattern, query) and muscle not in mentioned)
    named_remove = _named_remove_request(query)
    named_change = _named_set_change(query)
    removing = named_remove is not None or bool(re.search(r"\b(?:remove|take|delete)\b|شيل|احذف", query, re.I))
    changing = named_change is not None or bool(re.search(r"\b(?:change|set)\b", query, re.I))
    muscles = mentioned if not removing and not changing else []
    optional = [muscle for muscle in muscles
                if re.search(rf"\bmaybe\s+{re.escape(muscle.replace('_', ' '))}\b", query, re.I)
                or (muscle == "forearms" and re.search(r"\bmaybe\s+(?:forearms?|forearm)\b", query, re.I))]
    return {"mentioned_muscles": mentioned, "muscles": muscles,
            "optional_muscles": optional,
            "required": [muscle for muscle in muscles if muscle not in optional],
            "named_request": _named_add_request(query) if not muscles and not removing and not changing else None,
            "named_remove": named_remove, "named_change": named_change,
            "is_remove": removing, "is_change": changing}


def _select_focus_candidate(muscle: str, used_ids: set[str], context: Any, ledger: Any):
    policy = FOCUS_EXTRA_TABLE[muscle]
    for slot in policy["candidate_slots"]:
        candidate = _eligible_focus_candidate(policy, slot, used_ids, context, ledger)
        if candidate:
            return candidate, slot
    return None, None


def _move_side_delt_sources(db, days, target_days, query, muscles):
    if "side_delts" not in muscles or not re.search(r"\bmove\b|انقل", query, re.IGNORECASE):
        return {}
    target_orders = {int(day["day_order"]) for day in target_days}
    explicit = re.search(r"\bfrom\s+(?:my\s+)?(.+?)(?:\s+to\s+|$)", query, re.IGNORECASE)
    source_name = explicit.group(1).strip(" .,!?" ) if explicit else None
    matches = []
    for day in days:
        if int(day["day_order"]) in target_orders:
            continue
        if source_name and str(day.get("day_name", "")).casefold() != source_name.casefold():
            continue
        for index, item in enumerate(day.get("exercises", [])):
            entry = db.get_exercise_library_entry(str(item.get("exercise_id"))) or {}
            name = str(entry.get("display_name") or entry.get("name") or item.get("exercise_name") or "")
            if re.search(r"lateral\s*raises?", name, re.IGNORECASE):
                matches.append({int(day["day_order"]): {
                    "source_index": index,
                    "exercise_id": str(item["exercise_id"]),
                    "target_sets": program_exercise_working_sets(item),
                }})
    if len(matches) > 1:
        return {"_error": True}
    return matches[0] if matches else {}


def _named_add_request(query):
    match = re.search(
        r"\b(?:add|put)\s+(.+?)\s+(?:to|on|onto)\s+(?:my\s+)?(?:leg|legs|lower|upper)\s+days?\b",
        query, re.IGNORECASE,
    )
    return match.group(1).strip(" .,!?") if match else None


def _named_remove_request(query):
    match = re.search(
        r"\b(?:remove|take)\s+(.+?)\s+(?:from|off)\s+(?:my\s+)?(?:leg|legs|lower|upper)\s+days?\b",
        query, re.IGNORECASE,
    )
    return match.group(1).strip(" .,!?") if match else None


def _named_set_change(query):
    match = re.search(
        r"\b(?:change|set)\s+(.+?)\s+to\s+(\d+)\s+sets?\s+(?:on|in)\s+(?:my\s+)?(?:leg|legs|lower|upper)\s+days?\b",
        query, re.IGNORECASE,
    )
    return (match.group(1).strip(" .,!?"), int(match.group(2))) if match else None


def _named_exercise_candidates(db, ledger, name, context):
    if not name:
        return []
    from utils.equipment_access import equipment_access_allows

    return [
        candidate for candidate in db.find_exercises_by_name(name, limit=10) or []
        if db.is_exercise_library_exercise_visible(str(candidate["id"]))
        and equipment_access_allows(
            context.equipment_access, candidate.get("equipment")
        )
    ]


def _exercise_ids_for_muscles(db, muscles):
    from core.muscle_volume import main_group_for_focus, normalize_main_muscle

    selected = {
        normalize_main_muscle(muscle) or main_group_for_focus(muscle) or str(muscle).casefold()
        for muscle in muscles
    }
    credits_by_exercise: dict[str, set[str]] = {}
    for exercise_id, muscle in db.catalog_conn.execute(
        "SELECT exercise_id, muscle FROM exercise_muscle_credits WHERE credit > 0"
    ):
        credits_by_exercise.setdefault(str(exercise_id), set()).add(str(muscle))
    rows = db.catalog_conn.execute("SELECT id FROM exercises").fetchall()
    found = set()
    for row in rows:
        exercise_id = str(row[0])
        entry = db.get_exercise_library_entry(exercise_id) or {}
        labels = [entry.get(key) for key in ("primary_muscle", "target_muscle", "secondary_muscle")]
        labels.extend(entry.get("secondary_muscles") or ())
        values = {
            normalize_main_muscle(value) or str(value or "").casefold()
            for value in labels if value
        }
        values.update(credits_by_exercise.get(exercise_id, ()))
        if selected.intersection(values):
            found.add(exercise_id)
    return found


def _build_edit(day, requested, version, player_account_id, week_order):
    return ProgramEdit(
        day_name=day["day_name"], expected_active_version=version,
        exercises=requested, player_account_id=player_account_id,
        actor=ProgramAnalyticsActor(player_account_id, "player"),
        week_order=week_order, day_order=int(day["day_order"]),
        preview=True, via="chat",
    )


def _exercise_payload(item):
    return {"source_index": item.source_index, "exercise_id": item.exercise_id,
            "target_sets": item.target_sets}


def _preview_days(program, selected_days, optional_ids=None, requested_ids=None):
    by_order = {(int(day.get("week_order", 1)), int(day["day_order"])): day
                for day in program.get("days", [])}
    optional_ids = optional_ids or set()
    result = []
    requested_ids = requested_ids or set()
    for original in selected_days:
        week_order = int(original.get("week_order", 1))
        day = by_order[(week_order, int(original["day_order"]))]
        result.append({"day_name": day["day_name"], "day_order": day["day_order"],
            "week_order": week_order,
            "exercises": [{"name": item.get("exercise_name"), "sets": program_exercise_working_sets(item),
                "reps_min": item.get("target_reps_min"), "reps_max": item.get("target_reps_max"),
                "rir": 10 - float(item.get("target_rpe", 8.5)),
                "rest_seconds": item.get("rest_seconds"),
                "set_groups": [{"sets": int(group.get("sets", 0)),
                    "reps_min": group.get("reps_min"), "reps_max": group.get("reps_max"),
                    "rir": group.get("target_rir"), "load": group.get("load"),
                    "amrap_last_set": group.get("amrap_last_set", False)}
                    for group in item.get("set_groups", [])],
                "optional": str(item.get("exercise_id")) in optional_ids,
                "requested_edit": (week_order, int(original["day_order"]),
                    str(item.get("exercise_id"))) in requested_ids} for item in day.get("exercises", [])]})
    return result


def _stored_prescription(row):
    return {key: row[key] for key in ("exercise_name", "target_sets", "target_reps_min", "target_reps_max",
        "target_rpe", "rest_seconds", "warmup_sets", "set_groups", "program_edit_prescription_rationale")
        if key in row}


def _profile_fingerprint(profile):
    inputs = ("weekly_frequency", "equipment_access", "injuries_or_limitations", "rep_preference",
        "training_age_years", "weak_points", "stress_and_sleep", "gender")
    payload = json.dumps({key: profile.get(key) for key in inputs}, sort_keys=True,
        separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _is_lower_day(db, day):
    if re.search(LOWER_TERMS, str(day.get("day_name", "")), re.IGNORECASE):
        return True
    lower = {"quads", "hamstrings", "glutes", "calves", "adductors"}
    return any(
        str((db.get_exercise_library_entry(str(item.get("exercise_id"))) or {}).get("primary_muscle") or "").casefold() in lower
        for item in day.get("exercises", [])
    )


def _is_upper_day(db, day):
    return re.search(r"\b(?:upper|push|pull|chest|lats|traps|arms?)\b", str(day.get("day_name", "")), re.IGNORECASE) is not None


def resolve_chat_program_edit(
    db: Any, ledger: Any, player_account_id: str, preview_id: str,
    *, confirm: bool, include_optional: list[str] | None = None,
) -> dict[str, Any]:
    with ledger.ledger_transaction(immediate=True):
        return _resolve_chat_program_edit_in_transaction(
            db, ledger, player_account_id, preview_id,
            confirm=confirm, include_optional=include_optional,
        )


def _resolve_chat_program_edit_in_transaction(
    db: Any, ledger: Any, player_account_id: str, preview_id: str,
    *, confirm: bool, include_optional: list[str] | None,
) -> dict[str, Any]:
    pending = ledger.get_pending_chat_program_edit()
    if pending is None or pending["offer_id"] != preview_id:
        return {"error": "preview_expired"}
    proposal = pending["proposal"]
    if not confirm:
        ledger.clear_pending_chat_program_edit()
        active = ledger.get_active_program()
        return {"cancelled": True, "version": active.version if active is not None else None}
    active = ledger.get_active_program()
    if active is None or active.version != proposal.get("expected_version"):
        ledger.clear_pending_chat_program_edit()
        return {"error": "program_changed", "original_query": proposal.get("original_query")}
    if (proposal.get("profile_fingerprint") is not None
            and proposal["profile_fingerprint"] != _profile_fingerprint(ledger.get_player_profile() or {})):
        ledger.clear_pending_chat_program_edit()
        return {"error": "profile_changed", "original_query": proposal.get("original_query")}
    if not player_controls_program(db, ledger, player_account_id):
        ledger.clear_pending_chat_program_edit()
        return {"error": "coach_controls"}
    selected = set(include_optional or [])
    edit_ledger = ledger
    if proposal.get("rebuild_base_program") is not None:
        from agent.ProgramState import PersistedProgramSchema
        base_payload = dict(proposal["rebuild_base_program"])
        base_payload["version"] = active.version
        rebuilt = PersistedProgramSchema.model_validate(base_payload)
        edit_ledger = _PlanningLedger(ledger, rebuilt)
    edits = []
    for day in proposal["days"]:
        items = [ProgramEditExercise(**item) for item in day["exercises"]]
        for option in proposal.get("optional", []):
            if (int(option.get("week_order", day.get("week_order", 1))) == int(day["week_order"])
                    and int(option["day_order"]) == int(day["day_order"])
                    and option["exercise_id"] in selected):
                items.append(ProgramEditExercise(-1, option["exercise_id"], int(option["sets"]),
                    prescription=option.get("prescription")))
        edits.append(ProgramEdit(
            day_name=day["day_name"], expected_active_version=active.version,
            exercises=items, player_account_id=player_account_id,
            actor=ProgramAnalyticsActor(player_account_id, "player"),
            week_order=int(day["week_order"]), day_order=int(day["day_order"]),
            via="chat",
        ))
    result = edit_active_program_days(db, edit_ledger, edits,
        baseline_program=active if proposal.get("rebuild_base_program") is not None else None)
    if proposal.get("rebuild_base_program") is not None and "code" not in result and result.get("version") != active.version:
        ledger.update_player_frequency(int(proposal["rebuild_frequency"]))
    ledger.clear_pending_chat_program_edit()
    result["changed"] = result.get("version") != active.version
    return result
