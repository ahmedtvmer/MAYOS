"""MAYOS-owned Exercise library curation loaded from the curation CSV."""

import csv
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from agent.program_blueprints import SLOT_STAPLES
from database.shared import BASE_DIR, _normalize_exercise_name

DEFAULT_CURATION_CSV_PATH = BASE_DIR / "data" / "exercise_curation.csv"
CURATION_COLUMNS = (
    "id",
    "source_name",
    "display_name",
    "aliases",
    "primary_action",
    "secondary_actions",
    "primary_muscle",
    "load_type",
    "hidden",
    "duplicate_of",
)


@dataclass(frozen=True)
class ExerciseCuration:
    line_number: int
    id: str
    source_name: str
    display_name: str
    aliases: tuple[str, ...]
    primary_action: str
    secondary_actions: tuple[str, ...]
    primary_muscle: str
    load_type: str
    hidden: bool
    duplicate_of: str


def load_exercise_curation(path: str | Path = DEFAULT_CURATION_CSV_PATH) -> dict[str, ExerciseCuration]:
    with Path(path).open(newline="", encoding="utf-8") as curation_file:
        reader = csv.DictReader(curation_file)
        _validate_curation_columns(reader.fieldnames)
        return _read_curation_records(reader)


def _validate_curation_columns(fieldnames: list[str] | None) -> None:
    missing_columns = set(CURATION_COLUMNS) - set(fieldnames or ())
    if fieldnames and len(fieldnames) != len(set(fieldnames)):
        raise ValueError("Exercise curation CSV has duplicate columns")
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Exercise curation CSV is missing columns: {missing}")


def _read_curation_records(reader: csv.DictReader) -> dict[str, ExerciseCuration]:
    records: dict[str, ExerciseCuration] = {}
    for line_number, row in enumerate(reader, start=2):
        record = _parse_curation_row(line_number, row)
        if record.id in records:
            raise ValueError(f"Exercise curation CSV has duplicate id {record.id!r}")
        records[record.id] = record
    return records


def _parse_curation_row(line_number: int, row: dict[str, str | None]) -> ExerciseCuration:
    exercise_id = (row["id"] or "").strip()
    source_name = (row["source_name"] or "").strip()
    if not exercise_id or not source_name:
        raise ValueError(f"Exercise curation CSV line {line_number} needs an id and source_name")
    aliases = _split_curation_values(row["aliases"])
    _validate_curation_aliases(line_number, aliases)
    hidden_value = (row["hidden"] or "").strip()
    if hidden_value.casefold() not in {"", "true", "false"}:
        raise ValueError(
            f"Exercise curation CSV line {line_number} id {exercise_id!r} "
            f"has invalid hidden value {hidden_value!r}"
        )
    return ExerciseCuration(
        line_number=line_number,
        id=exercise_id,
        source_name=source_name,
        display_name=(row["display_name"] or "").strip(),
        aliases=aliases,
        primary_action=(row["primary_action"] or "").strip(),
        secondary_actions=_split_curation_values(row["secondary_actions"]),
        primary_muscle=(row["primary_muscle"] or "").strip(),
        load_type=(row["load_type"] or "").strip(),
        hidden=hidden_value.casefold() == "true",
        duplicate_of=(row["duplicate_of"] or "").strip(),
    )


def _validate_curation_aliases(line_number: int, aliases: tuple[str, ...]) -> None:
    normalized_aliases = [_normalize_exercise_name(alias) for alias in aliases]
    if len(set(normalized_aliases)) != len(normalized_aliases):
        raise ValueError(f"Exercise curation CSV line {line_number} repeats an alias")


def _split_curation_values(cell: str | None) -> tuple[str, ...]:
    return tuple(value.strip() for value in (cell or "").split("|") if value.strip())


def _title_case_source_name(source_name: str) -> str:
    return "".join(
        _capitalize_first_letter(segment)
        for segment in re.split(r"([ -])", source_name)
    )


def _capitalize_first_letter(word: str) -> str:
    for index, character in enumerate(word):
        if character.isalpha():
            return word[:index] + character.upper() + word[index + 1 :]
    return word


def _effective_display_name(source_name: str, record: ExerciseCuration | None) -> str:
    if record and record.display_name:
        return record.display_name
    return _title_case_source_name(source_name)


def apply_exercise_curation(
    cursor: sqlite3.Cursor,
    curation_path: str | Path = DEFAULT_CURATION_CSV_PATH,
) -> None:
    curation = load_exercise_curation(curation_path)
    exercises = cursor.execute("SELECT id, name FROM exercises").fetchall()
    exercise_ids = {str(exercise_id) for exercise_id, _ in exercises}
    _validate_curation_references(curation, exercise_ids)
    effective_names = _effective_curation_names(exercises, curation)
    for exercise_id, _ in exercises:
        exercise_id = str(exercise_id)
        record = curation.get(exercise_id)
        display_name = (
            effective_names[record.duplicate_of]
            if record and record.duplicate_of
            else effective_names[exercise_id]
        )
        _upsert_exercise_names(cursor, exercise_id, record, display_name)
        _upsert_curated_fields(cursor, exercise_id, record)


def _effective_curation_names(
    exercises: list[tuple[str, str]], curation: dict[str, ExerciseCuration]
) -> dict[str, str]:
    return {
        str(exercise_id): _effective_display_name(
            str(source_name), curation.get(str(exercise_id))
        )
        for exercise_id, source_name in exercises
    }


def _validate_curation_references(
    curation: dict[str, ExerciseCuration], exercise_ids: set[str]
) -> None:
    staples = {exercise_id for staple_ids in SLOT_STAPLES.values() for exercise_id in staple_ids}
    for exercise_id, record in curation.items():
        _validate_hidden_staple(exercise_id, record, staples)
        _validate_duplicate_reference(exercise_id, record, curation, exercise_ids)


def _validate_hidden_staple(
    exercise_id: str, record: ExerciseCuration, staples: set[str]
) -> None:
    if record.hidden and exercise_id in staples:
        raise ValueError(
            f"Exercise curation CSV line {record.line_number} id {exercise_id!r} "
            "marks Staple exercise hidden with value 'true'"
        )


def _validate_duplicate_reference(
    exercise_id: str,
    record: ExerciseCuration,
    curation: dict[str, ExerciseCuration],
    exercise_ids: set[str],
) -> None:
    if not record.duplicate_of:
        return
    if not record.hidden:
        raise ValueError(
            f"Exercise curation CSV line {record.line_number} id {exercise_id!r} "
            f"sets duplicate_of to {record.duplicate_of!r} while hidden is false"
        )
    if record.duplicate_of not in exercise_ids:
        raise ValueError(
            f"Exercise curation CSV line {record.line_number} id {exercise_id!r} "
            f"has missing duplicate_of value {record.duplicate_of!r}"
        )
    target = curation.get(record.duplicate_of)
    if target and target.hidden:
        raise ValueError(
            f"Exercise curation CSV line {record.line_number} id {exercise_id!r} "
            f"has hidden duplicate_of target {record.duplicate_of!r}"
        )


def _upsert_exercise_names(
    cursor: sqlite3.Cursor,
    exercise_id: str,
    record: ExerciseCuration | None,
    display_name: str,
) -> None:
    is_reviewed = int(bool(record and record.display_name))
    cursor.execute(
        "INSERT INTO exercise_display_names (exercise_id, display_name, is_reviewed) "
        "VALUES (?, ?, ?) ON CONFLICT(exercise_id) DO UPDATE SET "
        "display_name = excluded.display_name, is_reviewed = excluded.is_reviewed",
        (exercise_id, display_name, is_reviewed),
    )
    _replace_exercise_aliases(cursor, exercise_id, record)


def _upsert_curated_fields(
    cursor: sqlite3.Cursor,
    exercise_id: str,
    record: ExerciseCuration | None,
) -> None:
    cursor.execute(
        "INSERT INTO exercise_curated_fields (exercise_id, hidden, duplicate_of) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(exercise_id) DO UPDATE SET "
        "hidden = excluded.hidden, duplicate_of = excluded.duplicate_of",
        (
            exercise_id,
            int(bool(record and record.hidden)),
            (record.duplicate_of or None) if record else None,
        ),
    )


def _replace_exercise_aliases(
    cursor: sqlite3.Cursor,
    exercise_id: str,
    record: ExerciseCuration | None,
) -> None:
    cursor.execute("DELETE FROM exercise_aliases WHERE exercise_id = ?", (exercise_id,))
    if record:
        cursor.executemany(
            "INSERT INTO exercise_aliases (exercise_id, alias, normalized_alias) VALUES (?, ?, ?)",
            [
                (exercise_id, alias, _normalize_exercise_name(alias))
                for alias in record.aliases
            ],
        )
