"""Generated exercise ordering for isolation-first Training programs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from agent.program_blueprints import SLOT_SPECS
from agent.ProgramState import ProgramExerciseSchema


# Owner-approved main-muscle groups and the ordering limits come from
# docs/research/program-design.md §1.
MAIN_MUSCLE_GROUPS = {
    "chest": "chest",
    "upper chest": "chest",
    "lats": "back",
    "upper back": "back",
    "front delts": "shoulders",
    "side delts": "shoulders",
    "rear delts": "rear delts",
    "traps": "traps",
    "quads": "quads",
    "hamstrings": "hamstrings",
    "glutes": "glutes",
    "biceps": "biceps",
    "triceps": "triceps",
    "calves": "calves",
    "abs": "core",
    "core": "core",
}
COMPOUND_ARCHETYPES = frozenset({"heavy_compound", "medium_compound"})
FREE_WEIGHT_TERMS = ("barbell", "dumbbell", "kettlebell")
HEAVY_SQUAT_OR_HINGE_SLOTS = frozenset({"quad_compound", "ham_hinge"})
PULL_SLOTS = frozenset({"horizontal_row", "upper_back_pull", "vertical_pull"})
BARBELL_BENCH_SLOTS = frozenset({"flat_press", "incline_press"})
TRICEPS_ISOLATION_SLOTS = frozenset({"triceps_pushdown", "triceps_overhead"})
FOREARM_ISOLATION_SLOTS = frozenset({"forearm_wrist", "forearm_reverse"})
HAMSTRING_ISOLATION_SLOTS = frozenset({"ham_curl"})


@dataclass(frozen=True)
class ProgramOrderEntry:
    exercise: ProgramExerciseSchema
    rationale: dict[str, Any]
    position_reason: str | None = None


def main_muscles_for_slot(slot_key: str | None) -> frozenset[str]:
    spec = SLOT_SPECS.get(slot_key or "")
    if spec is None:
        return frozenset()
    return frozenset(
        MAIN_MUSCLE_GROUPS[muscle.casefold()]
        for muscle in spec.primary_muscles
        if muscle.casefold() in MAIN_MUSCLE_GROUPS
    )


def shares_main_muscle(first_slot: str | None, second_slot: str | None) -> bool:
    return bool(main_muscles_for_slot(first_slot) & main_muscles_for_slot(second_slot))


def order_program_exercises(
    exercises: list[ProgramExerciseSchema],
    rationales: list[dict[str, Any]],
    *,
    day_family: str | None,
    experience_level: str,
) -> list[ProgramOrderEntry]:
    entries = [
        ProgramOrderEntry(exercise, rationale)
        for exercise, rationale in zip(exercises, rationales, strict=True)
    ]
    main_lift = _main_progressed_lift(entries)
    main_id = main_lift.exercise.exercise_id if main_lift else None

    if experience_level == "beginner":
        entries.sort(key=lambda entry: not _is_compound(entry.exercise))
        return _refresh_position_reasons(entries, main_id, beginner=True)

    entries = _place_main_lift_before_its_muscle_work(entries, main_lift)
    entries, safety_ids = _move_stabilizers_after_lifts(entries)
    if _is_crowded_upper_day(entries, day_family):
        pre_exhaust_ids = _existing_pre_exhaust_entries(entries)
    else:
        entries, pre_exhaust_ids = _place_isolation_before_later_compound(entries, main_id)
    entries = _cap_pre_exhaust_work(entries, pre_exhaust_ids)
    safety_ids.update(_recorded_safety_entries(entries))
    return _refresh_position_reasons(entries, main_id, safety_ids, pre_exhaust_ids)


def _main_progressed_lift(entries: list[ProgramOrderEntry]) -> ProgramOrderEntry | None:
    from agent.program_rationale import POSITION_MAIN_PROGRESSED_LIFT

    recorded = next(
        (
            entry
            for entry in entries
            if entry.rationale.get("position", {}).get("code") == POSITION_MAIN_PROGRESSED_LIFT
        ),
        None,
    )
    return recorded or next((entry for entry in entries if _is_compound(entry.exercise)), None)


def _is_compound(exercise: ProgramExerciseSchema) -> bool:
    spec = SLOT_SPECS.get(exercise.slot_key or "")
    return bool(spec and spec.archetype in COMPOUND_ARCHETYPES)


def _is_isolation(exercise: ProgramExerciseSchema) -> bool:
    spec = SLOT_SPECS.get(exercise.slot_key or "")
    return bool(spec and spec.archetype == "isolation")


def _place_main_lift_before_its_muscle_work(
    entries: list[ProgramOrderEntry], main_lift: ProgramOrderEntry | None
) -> list[ProgramOrderEntry]:
    if main_lift is None:
        return entries
    main_index = _entry_index(entries, main_lift)
    muscle_groups = main_muscles_for_slot(main_lift.exercise.slot_key)
    earlier_work = next(
        (
            index
            for index, entry in enumerate(entries[:main_index])
            if main_muscles_for_slot(entry.exercise.slot_key) & muscle_groups
        ),
        None,
    )
    if earlier_work is not None:
        entries.insert(earlier_work, entries.pop(main_index))
    return entries


def _move_stabilizers_after_lifts(
    entries: list[ProgramOrderEntry],
) -> tuple[list[ProgramOrderEntry], set[str]]:
    safety_ids = set()
    for isolation in tuple(entry for entry in entries if _is_isolation(entry.exercise)):
        isolation_index = _entry_index(entries, isolation)
        later_lifts = [
            entry
            for entry in entries[isolation_index + 1 :]
            if _is_stabilizer_for(isolation.exercise, entry.exercise)
        ]
        if not later_lifts:
            continue
        last_lift = later_lifts[-1]
        entries.remove(isolation)
        moved = replace(isolation, position_reason="stabilizer_safety")
        entries.insert(_entry_index(entries, last_lift) + 1, moved)
        safety_ids.add(isolation.exercise.exercise_id)
    return entries, safety_ids


def _is_stabilizer_for(isolation: ProgramExerciseSchema, compound: ProgramExerciseSchema) -> bool:
    isolation_slot = isolation.slot_key or ""
    compound_slot = compound.slot_key or ""
    if compound_slot in HEAVY_SQUAT_OR_HINGE_SLOTS and _uses_free_weight(compound):
        return isolation_slot in HAMSTRING_ISOLATION_SLOTS or isolation_slot == "lower_back_iso"
    if compound_slot in BARBELL_BENCH_SLOTS and "barbell" in (compound.equipment or "").casefold():
        return isolation_slot in TRICEPS_ISOLATION_SLOTS
    spec = SLOT_SPECS.get(compound_slot)
    heavy_pull = compound_slot in PULL_SLOTS and (
        (spec is not None and spec.archetype == "heavy_compound")
        or _uses_free_weight(compound)
    )
    return heavy_pull and isolation_slot in FOREARM_ISOLATION_SLOTS


def _uses_free_weight(exercise: ProgramExerciseSchema) -> bool:
    equipment = (exercise.equipment or "").casefold()
    return any(term in equipment for term in FREE_WEIGHT_TERMS)


def _is_crowded_upper_day(entries: list[ProgramOrderEntry], day_family: str | None) -> bool:
    muscles = {
        muscle
        for entry in entries
        for muscle in main_muscles_for_slot(entry.exercise.slot_key)
    }
    return day_family == "upper" and len(muscles) >= 4


def _existing_pre_exhaust_entries(entries: list[ProgramOrderEntry]) -> set[str]:
    pre_exhaust_ids = set()
    for index, entry in enumerate(entries):
        if not _is_isolation(entry.exercise):
            continue
        if any(
            _is_compound(later.exercise)
            and shares_main_muscle(entry.exercise.slot_key, later.exercise.slot_key)
            and not _is_stabilizer_for(entry.exercise, later.exercise)
            for later in entries[index + 1 :]
        ):
            pre_exhaust_ids.add(entry.exercise.exercise_id)
    return pre_exhaust_ids


def _place_isolation_before_later_compound(
    entries: list[ProgramOrderEntry], main_id: str | None
) -> tuple[list[ProgramOrderEntry], set[str]]:
    claimed_muscles = set()
    pre_exhaust_ids = set()
    for compound in tuple(entry for entry in entries if _is_compound(entry.exercise)):
        if compound.exercise.exercise_id == main_id:
            continue
        for muscle in sorted(main_muscles_for_slot(compound.exercise.slot_key)):
            if muscle in claimed_muscles:
                continue
            isolation = next(
                (
                    entry
                    for entry in entries
                    if _is_isolation(entry.exercise)
                    and entry.exercise.exercise_id not in pre_exhaust_ids
                    and muscle in main_muscles_for_slot(entry.exercise.slot_key)
                    and not _is_stabilizer_for(entry.exercise, compound.exercise)
                    and entry.position_reason != "stabilizer_safety"
                ),
                None,
            )
            if isolation is None:
                continue
            entries.remove(isolation)
            entries.insert(_entry_index(entries, compound), isolation)
            pre_exhaust_ids.add(isolation.exercise.exercise_id)
            claimed_muscles.add(muscle)
            break
    return entries, pre_exhaust_ids


def _cap_pre_exhaust_work(
    entries: list[ProgramOrderEntry], pre_exhaust_ids: set[str]
) -> list[ProgramOrderEntry]:
    capped_entries = []
    for entry in entries:
        if entry.exercise.exercise_id not in pre_exhaust_ids:
            capped_entries.append(entry)
            continue
        exercise, rationale = _pre_exhaust_prescription(entry.exercise, entry.rationale)
        capped_entries.append(replace(entry, exercise=exercise, rationale=rationale))
    return capped_entries


def _recorded_safety_entries(entries: list[ProgramOrderEntry]) -> set[str]:
    from agent.program_rationale import POSITION_STABILIZER_SAFETY

    return {
        entry.exercise.exercise_id
        for entry in entries
        if entry.rationale.get("position", {}).get("code") == POSITION_STABILIZER_SAFETY
    }


def _pre_exhaust_prescription(
    exercise: ProgramExerciseSchema, rationale: dict[str, Any]
) -> tuple[ProgramExerciseSchema, dict[str, Any]]:
    # Section 1 caps this block at two non-failure isolation sets at RIR 1–3.
    set_count = min(exercise.working_sets, 2)
    groups = exercise.set_groups or []
    first_rir = groups[0].target_rir if groups and 1 <= groups[0].target_rir <= 3 else 2.0
    first_group = groups[0] if groups else None
    if set_count == 1:
        new_groups = [
            (first_group.model_copy(update={"sets": 1, "target_rir": 2.0}) if first_group else None)
        ]
    else:
        working_group = groups[-1] if groups else None
        new_groups = [
            first_group.model_copy(update={"sets": 1, "target_rir": first_rir})
            if first_group else None,
            working_group.model_copy(update={"sets": set_count - 1, "target_rir": 2.0})
            if working_group else None,
        ]
    new_groups = [group for group in new_groups if group is not None]
    exercise = exercise.model_copy(
        update={
            "target_sets": new_groups[0].sets,
            "target_rpe": 10 - new_groups[0].target_rir,
            "set_groups": new_groups,
        }
    )
    rir = rationale["prescription"]["rir"]["params"]
    rir.update(
        target_rir=2.0,
        test_set_count=int(set_count > 1),
        test_set_rir=first_rir if set_count > 1 else rir["test_set_rir"],
    )
    rationale["prescription"]["sets"]["params"]["count"] = set_count
    return exercise, rationale


def _refresh_position_reasons(
    entries: list[ProgramOrderEntry],
    main_id: str | None,
    safety_ids: set[str] | None = None,
    pre_exhaust_ids: set[str] | None = None,
    *,
    beginner: bool = False,
) -> list[ProgramOrderEntry]:
    from agent.program_rationale import POSITION_AFTER_FOCUS_EXTRA, POSITION_FOCUS_FIRST
    from agent.program_rationale import position_rationale

    safety_ids = safety_ids or set()
    pre_exhaust_ids = pre_exhaust_ids or set()
    slots = tuple(entry.exercise.slot_key or "" for entry in entries)
    refreshed = []
    for index, entry in enumerate(entries, start=1):
        exercise_id = entry.exercise.exercise_id
        if exercise_id == main_id:
            order_reason = "main_progressed_lift"
        elif beginner and _is_compound(entry.exercise):
            order_reason = "beginner_compound_first"
        elif exercise_id in pre_exhaust_ids:
            order_reason = "pre_exhaust"
        elif exercise_id in safety_ids:
            order_reason = "stabilizer_safety"
        else:
            order_reason = None
        rationale = entry.rationale
        current_position = rationale.get("position", {})
        if order_reason is None and current_position.get("code") in {
            POSITION_FOCUS_FIRST,
            POSITION_AFTER_FOCUS_EXTRA,
        }:
            position = current_position
            position.setdefault("params", {})["index"] = index
        else:
            position = position_rationale(
                exercise.slot_key or "",
                slots,
                order_reason=order_reason,
                index=index,
            )
        rationale["position"] = position
        refreshed.append(replace(entry, position_reason=order_reason, rationale=rationale))
    return refreshed


def _entry_index(entries: list[ProgramOrderEntry], sought: ProgramOrderEntry) -> int:
    return next(index for index, entry in enumerate(entries) if entry is sought)
