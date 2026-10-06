"""MAYOS-owned Exercise library curation loaded from the curation CSV."""

import csv
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

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
    id: str
    source_name: str
    display_name: str
    aliases: tuple[str, ...]
    primary_action: str
    secondary_actions: tuple[str, ...]
    primary_muscle: str
    load_type: str
    hidden: str
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
    return ExerciseCuration(
        id=exercise_id,
        source_name=source_name,
        display_name=(row["display_name"] or "").strip(),
        aliases=aliases,
        primary_action=(row["primary_action"] or "").strip(),
        secondary_actions=_split_curation_values(row["secondary_actions"]),
        primary_muscle=(row["primary_muscle"] or "").strip(),
        load_type=(row["load_type"] or "").strip(),
        hidden=(row["hidden"] or "").strip(),
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


def apply_exercise_curation(
    cursor: sqlite3.Cursor,
    curation_path: str | Path = DEFAULT_CURATION_CSV_PATH,
) -> None:
    curation = load_exercise_curation(curation_path)
    exercises = cursor.execute("SELECT id, name FROM exercises").fetchall()
    for exercise_id, source_name in exercises:
        record = curation.get(str(exercise_id))
        _upsert_exercise_names(cursor, str(exercise_id), source_name, record)


def _upsert_exercise_names(
    cursor: sqlite3.Cursor,
    exercise_id: str,
    source_name: str,
    record: ExerciseCuration | None,
) -> None:
    display_name = (
        record.display_name
        if record and record.display_name
        else _title_case_source_name(source_name)
    )
    is_reviewed = int(bool(record and record.display_name))
    cursor.execute(
        "INSERT INTO exercise_display_names (exercise_id, display_name, is_reviewed) "
        "VALUES (?, ?, ?) ON CONFLICT(exercise_id) DO UPDATE SET "
        "display_name = excluded.display_name, is_reviewed = excluded.is_reviewed",
        (exercise_id, display_name, is_reviewed),
    )
    _replace_exercise_aliases(cursor, exercise_id, record)


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
