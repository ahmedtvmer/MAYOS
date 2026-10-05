"""Deterministic structured summaries for published Training program changes."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from agent.ProgramState import PersistedProgramSchema


@dataclass
class _ExerciseMatches:
    old: list[Any]
    new: list[Any]
    by_new_index: dict[int, int] = field(default_factory=dict)
    used_old: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class _ExerciseChangeContext:
    changes: list[dict[str, Any]]
    old_day_name: str
    new_day_name: str
    resolve_exercise_name: Callable[[str], str | None]


def summarize_program_change(
    previous: PersistedProgramSchema | None,
    current: PersistedProgramSchema,
    resolve_exercise_name: Callable[[str], str | None],
) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    previous_days = previous.days if previous is not None else []
    current_days = current.days
    for old_index, new_index in _match_days(previous_days, current_days):
        before = previous_days[old_index] if old_index is not None else None
        after = current_days[new_index] if new_index is not None else None
        if before is None:
            _append_unmatched_day(changes, after, "day_added", resolve_exercise_name)
        elif after is None:
            _append_unmatched_day(changes, before, "day_removed", resolve_exercise_name)
        else:
            _append_day_changes(changes, before, after, resolve_exercise_name)
    return _finish_summary(previous, current, changes)


def _finish_summary(
    previous: PersistedProgramSchema | None,
    current: PersistedProgramSchema,
    changes: list[dict[str, Any]],
) -> dict[str, Any]:
    unchanged = previous is not None and _program_content(previous) == _program_content(current)
    if not unchanged and not changes:
        changes.append({"type": "other_details_changed"})
    return {"version": 1, "unchanged": unchanged, "changes": changes}


def _program_content(program: PersistedProgramSchema) -> dict[str, Any]:
    return program.model_dump(
        mode="python",
        exclude={"version", "published_by_coach_account_id", "created_at"},
    )


def _match_days(old: list[Any], new: list[Any]) -> list[tuple[int | None, int | None]]:
    old_for_new, used_old = _match_days_by_name(old, new)
    _pair_remaining_days(old, new, old_for_new, used_old)
    return _ordered_day_pairs(old, new, old_for_new, used_old)


def _match_days_by_name(old: list[Any], new: list[Any]) -> tuple[dict[int, int], set[int]]:
    old_by_name: dict[str, list[int]] = {}
    for old_index, day in enumerate(old):
        old_by_name.setdefault(day.day_name, []).append(old_index)

    old_for_new: dict[int, int] = {}
    used_old: set[int] = set()
    for new_index, day in enumerate(new):
        old_index = next(
            (candidate for candidate in old_by_name.get(day.day_name, []) if candidate not in used_old),
            None,
        )
        if old_index is not None:
            old_for_new[new_index] = old_index
            used_old.add(old_index)
    return old_for_new, used_old


def _pair_remaining_days(old: list[Any], new: list[Any], old_for_new: dict[int, int], used_old: set[int]) -> None:
    unmatched_old = [index for index in range(len(old)) if index not in used_old]
    unmatched_new = [index for index in range(len(new)) if index not in old_for_new]
    for old_index, new_index in zip(unmatched_old, unmatched_new):
        old_for_new[new_index] = old_index
        used_old.add(old_index)


def _ordered_day_pairs(
    old: list[Any], new: list[Any], old_for_new: dict[int, int], used_old: set[int]
) -> list[tuple[int | None, int | None]]:
    pairs = [(old_for_new.get(new_index), new_index) for new_index in range(len(new))]
    pairs.extend((old_index, None) for old_index in range(len(old)) if old_index not in used_old)
    return pairs


def _append_unmatched_day(
    changes: list[dict[str, Any]],
    day: Any,
    day_change_type: Literal["day_added", "day_removed"],
    resolve_name: Callable[[str], str | None],
) -> None:
    exercise_type = {"day_added": "exercise_added", "day_removed": "exercise_removed"}[day_change_type]
    changes.append({"type": day_change_type, "day": day.day_name})
    for exercise in day.exercises:
        changes.append(
            {
                "type": exercise_type,
                "day": day.day_name,
                "exercise": _exercise_name(exercise, resolve_name),
            }
        )


def _append_day_changes(
    changes: list[dict[str, Any]], previous: Any, current: Any, resolve_name: Callable[[str], str | None]
) -> None:
    if previous.day_name != current.day_name:
        changes.append(
            {"type": "day_renamed", "before": previous.day_name, "after": current.day_name}
        )
    _append_exercise_changes(changes, previous, current, resolve_name)


def _append_exercise_changes(
    changes: list[dict[str, Any]], previous_day: Any, current_day: Any, resolve_name: Callable[[str], str | None]
) -> None:
    context = _ExerciseChangeContext(changes, previous_day.day_name, current_day.day_name, resolve_name)
    for old_index, new_index in _match_exercises(previous_day.exercises, current_day.exercises):
        before = previous_day.exercises[old_index] if old_index is not None else None
        after = current_day.exercises[new_index] if new_index is not None else None
        _append_exercise_change(context, before, after)


def _match_exercises(old: list[Any], new: list[Any]) -> list[tuple[int | None, int | None]]:
    state = _ExerciseMatches(old, new)
    _match_by_key(state, "exercise_id")
    _match_by_key(state, "slot_key")
    for new_index, exercise in enumerate(new):
        if new_index not in state.by_new_index and new_index < len(old) and new_index not in state.used_old:
            state.by_new_index[new_index] = new_index
            state.used_old.add(new_index)
    pairs = [(state.by_new_index.get(i), i) for i in range(len(new))]
    pairs.extend((i, None) for i in range(len(old)) if i not in state.used_old)
    return pairs


def _match_by_key(state: _ExerciseMatches, field_name: str) -> None:
    old_by_key: dict[str, list[int]] = {}
    for index, exercise in enumerate(state.old):
        key = getattr(exercise, field_name)
        if key:
            old_by_key.setdefault(key, []).append(index)
    for new_index, exercise in enumerate(state.new):
        key = getattr(exercise, field_name)
        old_index = next(
            (candidate for candidate in old_by_key.get(key, []) if candidate not in state.used_old),
            None,
        )
        if new_index not in state.by_new_index and old_index is not None and old_index not in state.used_old:
            state.by_new_index[new_index] = old_index
            state.used_old.add(old_index)


def _append_exercise_change(context: _ExerciseChangeContext, before: Any, after: Any) -> None:
    day_name = context.new_day_name if after is not None else context.old_day_name
    if before is None:
        context.changes.append(
            {"type": "exercise_added", "day": day_name, "exercise": _exercise_name(after, context.resolve_exercise_name)}
        )
        return
    if after is None:
        context.changes.append(
            {"type": "exercise_removed", "day": day_name, "exercise": _exercise_name(before, context.resolve_exercise_name)}
        )
        return
    if before.exercise_id != after.exercise_id:
        _append_replacement(context, day_name, before, after)
    _append_prescription_change(context, before, after)


def _append_replacement(context: _ExerciseChangeContext, day_name: str, before: Any, after: Any) -> None:
    context.changes.append(
        {
            "type": "exercise_replaced",
            "day": day_name,
            "before": _exercise_name(before, context.resolve_exercise_name),
            "after": _exercise_name(after, context.resolve_exercise_name),
        }
    )


def _append_prescription_change(context: _ExerciseChangeContext, before: Any, after: Any) -> None:
    fields = _prescription_fields(before, after)
    if fields:
        context.changes.append(
            {
                "type": "prescription_changed",
                "day": context.new_day_name,
                "exercise": _exercise_name(after, context.resolve_exercise_name),
                "fields": fields,
            }
        )


def _prescription_fields(before: Any, after: Any) -> dict[str, dict[str, int | float | str]]:
    fields: dict[str, dict[str, int | float | str]] = {}
    _add_field_change(fields, "sets", before.target_sets, after.target_sets)
    _add_field_change(fields, "warmup_sets", before.warmup_sets, after.warmup_sets)
    _add_field_change(fields, "reps", _reps(before), _reps(after))
    _add_field_change(fields, "rir", _rir(before.target_rpe), _rir(after.target_rpe))
    _add_field_change(fields, "rest_seconds", before.rest_seconds, after.rest_seconds)
    return fields


def _add_field_change(
    fields: dict[str, dict[str, int | float | str]], name: str, before: int | float | str, after: int | float | str
) -> None:
    if before != after:
        fields[name] = {"before": before, "after": after}


def _reps(exercise: Any) -> str:
    if exercise.target_reps_min == exercise.target_reps_max:
        return str(exercise.target_reps_min)
    return f"{exercise.target_reps_min}–{exercise.target_reps_max}"


def _rir(target_rpe: float) -> int | float:
    rir = round(10 - target_rpe, 2)
    return int(rir) if rir.is_integer() else rir


def _exercise_name(exercise: Any, resolve_name: Callable[[str], str | None]) -> str:
    return resolve_name(exercise.exercise_id) or exercise.exercise_name
