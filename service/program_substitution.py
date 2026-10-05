"""Permanent exercise substitutions in a player's active training program."""

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any

from service import analytics
from service.program_analytics import ProgramAnalyticsActor, capture_program_exercise_swapped
from service.programs import COACH_CONTROLLED_ERROR, player_controls_program


class SubstitutionErrorCode(str, Enum):
    DAY_NOT_FOUND = "day_not_found"
    SOURCE_NOT_ON_DAY = "source_not_on_day"
    REPLACEMENT_IS_SOURCE = "replacement_is_source"
    REPLACEMENT_NOT_FOUND = "replacement_not_found"
    REPLACEMENT_ALREADY_ON_DAY = "replacement_already_on_day"
    COACH_CONTROLLED = "coach_controlled"
    NO_ACTIVE_PROGRAM = "no_active_program"
    RESTORE_VERSION_NOT_FOUND = "restore_version_not_found"
    PROGRAM_CHANGED = "program_changed"


SUBSTITUTION_ERRORS = {
    SubstitutionErrorCode.DAY_NOT_FOUND: "That day is not part of your current program.",
    SubstitutionErrorCode.SOURCE_NOT_ON_DAY: "That exercise is not in that day of your current program.",
    SubstitutionErrorCode.REPLACEMENT_IS_SOURCE: "Choose a different replacement exercise.",
    SubstitutionErrorCode.REPLACEMENT_NOT_FOUND: "That replacement exercise was not found.",
    SubstitutionErrorCode.REPLACEMENT_ALREADY_ON_DAY: "That replacement exercise is already on the target day.",
    SubstitutionErrorCode.COACH_CONTROLLED: COACH_CONTROLLED_ERROR,
    SubstitutionErrorCode.NO_ACTIVE_PROGRAM: "No active program.",
    SubstitutionErrorCode.RESTORE_VERSION_NOT_FOUND: "The program version to restore was not found.",
    SubstitutionErrorCode.PROGRAM_CHANGED: "The program changed since this substitution",
}
SUBSTITUTION_MESSAGE_CODES = {
    SubstitutionErrorCode.DAY_NOT_FOUND: "program.substitution.day_not_found.v1",
    SubstitutionErrorCode.SOURCE_NOT_ON_DAY: "program.substitution.source_not_on_day.v1",
    SubstitutionErrorCode.REPLACEMENT_IS_SOURCE: "program.substitution.replacement_is_source.v1",
    SubstitutionErrorCode.REPLACEMENT_NOT_FOUND: "program.substitution.replacement_not_found.v1",
    SubstitutionErrorCode.REPLACEMENT_ALREADY_ON_DAY: "program.substitution.replacement_already_on_day.v1",
    SubstitutionErrorCode.COACH_CONTROLLED: "program.coach_controls.v1",
    SubstitutionErrorCode.NO_ACTIVE_PROGRAM: "program.no_active.v1",
    SubstitutionErrorCode.RESTORE_VERSION_NOT_FOUND: "program.substitution.restore_version_not_found.v1",
    SubstitutionErrorCode.PROGRAM_CHANGED: "program.substitution.changed.v1",
}


@dataclass(frozen=True)
class ProgramSubstitution:
    day_name: str
    exercise_id: str
    replacement_exercise_id: str
    all_occurrences: bool = False
    published_by_coach_account_id: str | None = None
    expected_active_version: int | None = None


@dataclass(frozen=True)
class ProgramSubstitutionUndo:
    restore_version: int
    expected_active_version: int


def substitute_program_exercise(
    ledger: Any, catalog: Any, active_program: Any, request: ProgramSubstitution
) -> dict[str, Any]:
    """Replace the requested slot(s), validate the new exercise, and publish a version."""
    prepared = _prepare_substitution(active_program, catalog, request)
    if not prepared["ok"]:
        return prepared
    program_data = prepared["program_data"]
    target_days = prepared["target_days"]
    replacement = prepared["replacement"]
    if request.all_occurrences:
        replaced_count = _replace_every_slot(target_days, str(request.exercise_id), replacement)
    else:
        replaced_count = _replace_first_slot(target_days[0], str(request.exercise_id), replacement)
    program_data.pop("created_at", None)
    ledger.save_training_program(program_data, published_by_coach_account_id=request.published_by_coach_account_id)
    return {
        "ok": True,
        "replacement": replacement,
        "replaced_count": replaced_count,
        "day_names": [day["day_name"] for day in target_days],
    }


def substitute_active_program_exercise(
    db: Any,
    ledger: Any,
    player_account_id: str | None,
    request: ProgramSubstitution,
    *,
    actor: ProgramAnalyticsActor,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> dict[str, Any]:
    """Authorize, check the version, publish one substitution, and reread it."""
    active, failure = _player_active_program(db, ledger, player_account_id)
    if failure:
        return failure
    if request.expected_active_version is not None and active.version != request.expected_active_version:
        return _failure(SubstitutionErrorCode.PROGRAM_CHANGED)
    substitution = substitute_program_exercise(ledger, db, active, request)
    if not substitution["ok"]:
        return substitution
    result = _updated_program_result(ledger, active.version)
    updated = ledger.get_active_program()
    if updated is not None:
        capture_program_exercise_swapped(actor, updated, client=client)
    return result


def undo_active_program_substitution(
    db: Any,
    ledger: Any,
    player_account_id: str | None,
    request: ProgramSubstitutionUndo,
    *,
    actor: ProgramAnalyticsActor,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> dict[str, Any]:
    """Restore an exact historical snapshot as a fresh, player-owned version."""
    active, failure = _player_active_program(db, ledger, player_account_id)
    if failure:
        return failure
    if active.version != request.expected_active_version:
        return _failure(SubstitutionErrorCode.PROGRAM_CHANGED)
    snapshot = ledger.get_program_by_version(request.restore_version)
    if snapshot is None:
        return _failure(SubstitutionErrorCode.RESTORE_VERSION_NOT_FOUND)
    result = _restore_program_snapshot(ledger, active.version, snapshot)
    updated = ledger.get_active_program()
    if updated is not None:
        capture_program_exercise_swapped(actor, updated, client=client)
    return result


def _player_active_program(db: Any, ledger: Any, account_id: str | None) -> tuple[Any, dict[str, Any] | None]:
    if not player_controls_program(db, ledger, account_id):
        return None, _failure(SubstitutionErrorCode.COACH_CONTROLLED)
    active = ledger.get_active_program()
    if active is None:
        return None, _failure(SubstitutionErrorCode.NO_ACTIVE_PROGRAM)
    return active, None


def _updated_program_result(ledger: Any, previous_version: int | None) -> dict[str, Any]:
    updated = ledger.get_active_program()
    if updated is None:
        return _failure(SubstitutionErrorCode.NO_ACTIVE_PROGRAM)
    return {**updated.model_dump(), "previous_version": previous_version}


def _restore_program_snapshot(ledger: Any, previous_version: int | None, snapshot: Any) -> dict[str, Any]:
    program_data = _program_data(snapshot)
    # Let the ledger allocate new identities and a monotonically increasing
    # version while retaining every content field from the historical copy.
    program_data.pop("id", None)
    program_data.pop("version", None)
    program_data.pop("created_at", None)
    for day in program_data.get("days", []):
        day.pop("id", None)
        for exercise in day.get("exercises", []):
            exercise.pop("id", None)
    ledger.save_training_program(program_data, published_by_coach_account_id=None)
    return _updated_program_result(ledger, previous_version)


def _prepare_substitution(active_program: Any, catalog: Any, request: ProgramSubstitution) -> dict[str, Any]:
    source_id = str(request.exercise_id)
    replacement = _replacement(catalog, source_id, request.replacement_exercise_id)
    if not replacement["ok"]:
        return replacement
    program_data = _program_data(active_program)
    target_days = _target_days(program_data, request, source_id)
    if not target_days["ok"]:
        return target_days
    target_days = target_days["days"]
    if any(_day_has_exercise(day, replacement["entry"]["id"]) for day in target_days):
        return _failure(SubstitutionErrorCode.REPLACEMENT_ALREADY_ON_DAY)
    return {"ok": True, "program_data": program_data, "target_days": target_days, "replacement": replacement["entry"]}


def _target_days(program_data: dict[str, Any], request: ProgramSubstitution, source_id: str) -> dict[str, Any]:
    days = program_data.get("days", [])
    named_day = next((day for day in days if day.get("day_name") == request.day_name), None)
    if named_day is None:
        return _failure(SubstitutionErrorCode.DAY_NOT_FOUND)
    if not _day_has_exercise(named_day, source_id):
        return _failure(SubstitutionErrorCode.SOURCE_NOT_ON_DAY)
    target_days = [day for day in days if _day_has_exercise(day, source_id)] if request.all_occurrences else [named_day]
    return {"ok": True, "days": target_days}


def _replacement(catalog: Any, source_id: str, replacement_id: str) -> dict[str, Any]:
    replacement_id = str(replacement_id)
    if source_id == replacement_id:
        return _failure(SubstitutionErrorCode.REPLACEMENT_IS_SOURCE)
    entry = catalog.get_exercise_library_entry(replacement_id)
    if entry is None:
        return _failure(SubstitutionErrorCode.REPLACEMENT_NOT_FOUND)
    return {"ok": True, "entry": entry}


def _failure(code: SubstitutionErrorCode) -> dict[str, Any]:
    return {
        "ok": False,
        "code": code,
        "error": SUBSTITUTION_ERRORS[code],
        "message_code": SUBSTITUTION_MESSAGE_CODES[code],
    }


def _program_data(active_program: Any) -> dict[str, Any]:
    if isinstance(active_program, dict):
        return deepcopy(active_program)
    return active_program.model_dump()


def _day_has_exercise(day: dict[str, Any], exercise_id: str) -> bool:
    return any(str(exercise.get("exercise_id")) == exercise_id for exercise in day.get("exercises", []))


def _replace_first_slot(day: dict[str, Any], source_id: str, replacement: dict[str, Any]) -> int:
    for exercise in day.get("exercises", []):
        if str(exercise.get("exercise_id")) == source_id:
            _set_replacement(exercise, replacement)
            return 1
    return 0


def _replace_every_slot(days: list[dict[str, Any]], source_id: str, replacement: dict[str, Any]) -> int:
    replaced_count = 0
    for day in days:
        for exercise in day.get("exercises", []):
            if str(exercise.get("exercise_id")) != source_id:
                continue
            _set_replacement(exercise, replacement)
            replaced_count += 1
    return replaced_count


def _set_replacement(exercise: dict[str, Any], replacement: dict[str, Any]) -> None:
    exercise.update(
        exercise_id=str(replacement["id"]),
        exercise_name=str(replacement["name"]),
        equipment=replacement.get("equipment"),
        notes=replacement.get("instructions") or "",
        image_path=replacement.get("image_path"),
        gif_path=replacement.get("gif_path"),
        suggested_substitutes=[],
    )
