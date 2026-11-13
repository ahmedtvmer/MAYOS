"""Generated exercise ordering for isolation-first Training programs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

from agent.program_blueprints import SLOT_SPECS
from agent.ProgramState import ProgramExerciseSchema, ProgramSetGroupSchema
from core.muscle_volume import normalize_main_muscle


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
    source_order: int = 0


@dataclass
class PreExhaustPlan:
    entries: list[ProgramOrderEntry]
    isolation_ids: set[str]
    after_block_ids: set[str]
    compound_ids: set[str]
    compound_by_isolation: dict[str, str]
    claimed_muscles: set[str]


def main_muscles_for_slot(slot_key: str | None) -> frozenset[str]:
    spec = SLOT_SPECS.get(slot_key or "")
    if spec is None:
        return frozenset()
    return frozenset(
        group
        for muscle in spec.primary_muscles
        if (group := normalize_main_muscle(muscle)) is not None
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
    entries = _program_order_entries(exercises, rationales)
    main_lift = _main_progressed_lift(entries)
    main_id = main_lift.exercise.exercise_id if main_lift else None
    if experience_level == "beginner":
        return _order_beginner_program(entries, main_id)
    return _order_non_beginner_program(entries, main_lift, main_id, day_family)


def _program_order_entries(
    exercises: list[ProgramExerciseSchema], rationales: list[dict[str, Any]]
) -> list[ProgramOrderEntry]:
    return [
        ProgramOrderEntry(exercise, rationale, source_order=index)
        for index, (exercise, rationale) in enumerate(zip(exercises, rationales, strict=True))
    ]


def _order_beginner_program(
    entries: list[ProgramOrderEntry], main_id: str | None
) -> list[ProgramOrderEntry]:
    entries.sort(key=lambda entry: not _is_compound(entry.exercise))
    beginner_reasons = {
        entry.exercise.exercise_id: "beginner_compound_first"
        for entry in entries
        if _is_compound(entry.exercise) and entry.exercise.exercise_id != main_id
    }
    return _refresh_position_reasons(entries, main_id, beginner_reasons)


def _order_non_beginner_program(
    entries: list[ProgramOrderEntry],
    main_lift: ProgramOrderEntry | None,
    main_id: str | None,
    day_family: str | None,
) -> list[ProgramOrderEntry]:
    entries = _place_main_lift_before_its_muscle_work(entries, main_lift)
    entries, safety_ids = _move_stabilizers_after_lifts(entries)
    pre_exhaust = _place_isolation_before_later_compound(
        entries, main_id, allow_new=not _is_crowded_upper_day(entries, day_family)
    )
    entries = _cap_pre_exhaust_work(pre_exhaust)
    safety_ids.update(_recorded_safety_entries(entries))
    reasons = _position_reason_by_id(safety_ids, pre_exhaust)
    return _refresh_position_reasons(entries, main_id, reasons)


def _position_reason_by_id(
    safety_ids: set[str], pre_exhaust: PreExhaustPlan
) -> dict[str, str]:
    reasons = {exercise_id: "pre_exhaust" for exercise_id in pre_exhaust.isolation_ids}
    reasons.update({exercise_id: "follows_pre_exhaust" for exercise_id in pre_exhaust.compound_ids})
    reasons.update({exercise_id: "after_pre_exhaust_block" for exercise_id in pre_exhaust.after_block_ids})
    for exercise_id in safety_ids:
        reasons.setdefault(exercise_id, "stabilizer_safety")
    return reasons


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
        safety_lifts = _stabilizer_lifts(entries, isolation)
        if not safety_lifts:
            continue
        safety_ids.add(isolation.exercise.exercise_id)
        _place_isolation_after_later_lifts(entries, isolation, safety_lifts, safety_ids)
    return entries, safety_ids


def _stabilizer_lifts(
    entries: list[ProgramOrderEntry], isolation: ProgramOrderEntry
) -> list[ProgramOrderEntry]:
    return [
        entry for entry in entries
        if entry is not isolation and _is_stabilizer_for(isolation.exercise, entry.exercise)
    ]


def _place_isolation_after_later_lifts(
    entries: list[ProgramOrderEntry],
    isolation: ProgramOrderEntry,
    safety_lifts: list[ProgramOrderEntry],
    prior_safety_ids: set[str],
) -> None:
    isolation_index = _entry_index(entries, isolation)
    later_lifts = [
        entry for entry in safety_lifts
        if _entry_index(entries, entry) > isolation_index
    ]
    if later_lifts:
        entries.remove(isolation)
        last_lift_index = max(_entry_index(entries, lift) for lift in later_lifts)
        prior_safety_indices = [
            _entry_index(entries, entry)
            for entry in entries
            if entry.exercise.exercise_id in prior_safety_ids
            and entry.source_order < isolation.source_order
        ]
        insert_index = max([last_lift_index, *prior_safety_indices]) + 1
        entries.insert(insert_index, isolation)


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


def _place_isolation_before_later_compound(
    entries: list[ProgramOrderEntry], main_id: str | None, *, allow_new: bool
) -> PreExhaustPlan:
    from agent.program_rationale import POSITION_AFTER_PRE_EXHAUST_BLOCK

    plan = PreExhaustPlan(
        entries=entries,
        isolation_ids=set(),
        after_block_ids={
            entry.exercise.exercise_id
            for entry in entries
            if entry.rationale.get("position", {}).get("code")
            == POSITION_AFTER_PRE_EXHAUST_BLOCK
        },
        compound_ids=set(),
        compound_by_isolation={},
        claimed_muscles=set(),
    )
    for compound in tuple(entry for entry in entries if _is_compound(entry.exercise)):
        if compound.exercise.exercise_id == main_id:
            continue
        _place_one_pre_exhaust_block(plan, compound, allow_new)
    return plan


def _place_one_pre_exhaust_block(
    plan: PreExhaustPlan,
    compound: ProgramOrderEntry,
    allow_new: bool,
) -> None:
    for muscle in sorted(main_muscles_for_slot(compound.exercise.slot_key)):
        if muscle in plan.claimed_muscles:
            continue
        block = _eligible_pre_exhaust_block(plan.entries, compound, muscle, allow_new)
        if block is None:
            continue
        isolation, extras = block
        plan.entries = _place_pre_exhaust_block(plan.entries, isolation, extras, compound)
        plan.isolation_ids.add(isolation.exercise.exercise_id)
        plan.after_block_ids.update(entry.exercise.exercise_id for entry in extras)
        plan.compound_ids.add(compound.exercise.exercise_id)
        plan.compound_by_isolation[isolation.exercise.exercise_id] = compound.exercise.exercise_id
        plan.claimed_muscles.add(muscle)
        return


def _eligible_pre_exhaust_block(
    entries: list[ProgramOrderEntry],
    compound: ProgramOrderEntry,
    muscle: str,
    allow_new: bool,
) -> tuple[ProgramOrderEntry, list[ProgramOrderEntry]] | None:
    candidates = _pre_exhaust_candidates(entries, compound, muscle)
    earlier = [
        entry for entry in candidates
        if _entry_index(entries, entry) < _entry_index(entries, compound)
    ]
    eligible = candidates if allow_new else earlier
    if not eligible:
        return None
    isolation = min(eligible, key=lambda entry: entry.source_order)
    extras = sorted(
        (entry for entry in earlier if entry is not isolation),
        key=lambda entry: entry.source_order,
    )
    return isolation, extras


def _pre_exhaust_candidates(
    entries: list[ProgramOrderEntry], compound: ProgramOrderEntry, muscle: str
) -> list[ProgramOrderEntry]:
    from agent.program_rationale import POSITION_STABILIZER_SAFETY

    return [
        entry for entry in entries
        if _is_isolation(entry.exercise)
        and muscle in main_muscles_for_slot(entry.exercise.slot_key)
        and not _is_stabilizer_for(entry.exercise, compound.exercise)
        and entry.rationale.get("position", {}).get("code") != POSITION_STABILIZER_SAFETY
    ]


def _place_pre_exhaust_block(
    entries: list[ProgramOrderEntry],
    isolation: ProgramOrderEntry,
    extras: list[ProgramOrderEntry],
    compound: ProgramOrderEntry,
) -> list[ProgramOrderEntry]:
    for entry in [isolation, *extras]:
        entries.remove(entry)
    compound_index = _entry_index(entries, compound)
    entries.insert(compound_index, isolation)
    entries[compound_index + 2:compound_index + 2] = extras
    return entries


def _cap_pre_exhaust_work(plan: PreExhaustPlan) -> list[ProgramOrderEntry]:
    entries_by_id = {entry.exercise.exercise_id: entry for entry in plan.entries}
    for isolation_id, compound_id in plan.compound_by_isolation.items():
        _cap_pre_exhaust_entry(entries_by_id, isolation_id, compound_id)
    return [entries_by_id[entry.exercise.exercise_id] for entry in plan.entries]


def _cap_pre_exhaust_entry(
    entries_by_id: dict[str, ProgramOrderEntry], isolation_id: str, compound_id: str
) -> None:
    isolation = entries_by_id[isolation_id]
    exercise, rationale, remainder = _pre_exhaust_prescription(
        isolation.exercise, isolation.rationale
    )
    isolation = replace(isolation, exercise=exercise, rationale=rationale)
    compound = entries_by_id[compound_id]
    if remainder:
        isolation, compound = _reallocate_pre_exhaust_remainder(
            isolation, compound, remainder
        )
    entries_by_id[isolation_id] = isolation
    entries_by_id[compound_id] = compound


def _reallocate_pre_exhaust_remainder(
    isolation: ProgramOrderEntry,
    compound: ProgramOrderEntry,
    remainder: int,
) -> tuple[ProgramOrderEntry, ProgramOrderEntry]:
    exercise, rationale = _receive_pre_exhaust_sets(
        compound.exercise, compound.rationale, isolation.exercise.exercise_id, remainder
    )
    source_sets = isolation.rationale["prescription"]["sets"]["params"]
    source_sets["redistributed_to"] = compound.exercise.exercise_id
    source_sets["redistribution_reason_en"] = (
        "The pre-exhaust block stays within two sets; remaining sets move to "
        "a same-muscle exercise to preserve weekly volume."
    )
    source_sets["redistribution_reason_ar"] = (
        "يظل جزء ما قبل التمرين المركب في حدود مجموعتين؛ وتنتقل المجموعات "
        "المتبقية إلى تمرين للعضلة نفسها للحفاظ على حجم التدريب الأسبوعي."
    )
    return isolation, replace(compound, exercise=exercise, rationale=rationale)


def _recorded_safety_entries(entries: list[ProgramOrderEntry]) -> set[str]:
    from agent.program_rationale import POSITION_STABILIZER_SAFETY

    return {
        entry.exercise.exercise_id
        for entry in entries
        if entry.rationale.get("position", {}).get("code") == POSITION_STABILIZER_SAFETY
    }


def _pre_exhaust_prescription(
    exercise: ProgramExerciseSchema, rationale: dict[str, Any]
) -> tuple[ProgramExerciseSchema, dict[str, Any], int]:
    # Section 1 caps this block at two non-failure isolation sets at RIR 1–3.
    set_count = min(exercise.working_sets, 2)
    redistributed_sets = exercise.working_sets - set_count
    new_groups = _pre_exhaust_set_groups(exercise.set_groups or [], set_count)
    exercise = exercise.model_copy(
        update={
            "target_sets": new_groups[0].sets,
            "target_rpe": 10 - new_groups[0].target_rir,
            "set_groups": new_groups,
        }
    )
    rationale = _pre_exhaust_rationale(rationale, new_groups, set_count)
    return exercise, rationale, redistributed_sets


def _pre_exhaust_set_groups(
    groups: list[ProgramSetGroupSchema], set_count: int
) -> list[ProgramSetGroupSchema]:
    first_group = groups[0]
    first_rir = first_group.target_rir if 1 <= first_group.target_rir <= 3 else 2.0
    first_set = first_group.model_copy(
        update={"sets": 1, "target_rir": first_rir, "amrap_last_set": False}
    )
    if set_count == 1:
        return [first_set.model_copy(update={"target_rir": 2.0})]
    working_set = groups[-1].model_copy(
        update={"sets": set_count - 1, "target_rir": 2.0, "amrap_last_set": False}
    )
    return [first_set, working_set]


def _pre_exhaust_rationale(
    rationale: dict[str, Any], groups: list[ProgramSetGroupSchema], set_count: int
) -> dict[str, Any]:
    rationale = deepcopy(rationale)
    rir = rationale["prescription"]["rir"]["params"]
    rir.update(
        target_rir=2.0,
        test_set_count=int(set_count > 1),
        test_set_rir=groups[0].target_rir if set_count > 1 else rir["test_set_rir"],
    )
    rationale["prescription"]["sets"]["params"]["count"] = set_count
    return rationale


def _receive_pre_exhaust_sets(
    exercise: ProgramExerciseSchema,
    rationale: dict[str, Any],
    source_id: str,
    set_count: int,
) -> tuple[ProgramExerciseSchema, dict[str, Any]]:
    groups = list(exercise.set_groups or [])
    last_group = groups[-1]
    groups.append(last_group.model_copy(update={"sets": set_count}))
    exercise = exercise.model_copy(update={"set_groups": groups})
    rationale = deepcopy(rationale)
    set_params = rationale["prescription"]["sets"]["params"]
    set_params["count"] = exercise.working_sets
    set_params["redistributed_from"] = source_id
    set_params["redistributed_sets"] = set_count
    set_params["redistribution_reason_en"] = (
        "Sets moved from the pre-exhaust isolation stay in this same-muscle exercise, "
        "so weekly volume is preserved."
    )
    set_params["redistribution_reason_ar"] = (
        "انتقلت المجموعات من تمرين العزل إلى هذا التمرين للعضلة نفسها للحفاظ على "
        "حجم التدريب الأسبوعي."
    )
    return exercise, rationale


def _refresh_position_reasons(
    entries: list[ProgramOrderEntry],
    main_id: str | None,
    reason_by_id: dict[str, str],
) -> list[ProgramOrderEntry]:
    slots = tuple(entry.exercise.slot_key or "" for entry in entries)
    return [
        _refresh_position_entry(
            entry,
            index,
            slots,
            "main_progressed_lift"
            if entry.exercise.exercise_id == main_id
            else reason_by_id.get(entry.exercise.exercise_id),
        )
        for index, entry in enumerate(entries, start=1)
    ]


def _refresh_position_entry(
    entry: ProgramOrderEntry,
    index: int,
    slots: tuple[str, ...],
    order_reason: str | None,
) -> ProgramOrderEntry:
    from agent.program_rationale import POSITION_AFTER_FOCUS_EXTRA, POSITION_FOCUS_FIRST
    from agent.program_rationale import position_rationale

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
            entry.exercise.slot_key or "",
            slots,
            order_reason=order_reason,
            index=index,
        )
    rationale["position"] = position
    return replace(entry, rationale=rationale)


def _entry_index(entries: list[ProgramOrderEntry], sought: ProgramOrderEntry) -> int:
    return next(index for index, entry in enumerate(entries) if entry is sought)
