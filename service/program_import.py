"""In-memory readers and the shared Program import pipeline."""

import csv
import datetime as dt
import io
import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from openpyxl import Workbook, load_workbook

from agent.program_prescription import (
    DEFAULT_EXERCISE_REST_SECONDS,
    DEFAULT_TARGET_REPS_MAX,
    DEFAULT_TARGET_REPS_MIN,
    DEFAULT_TARGET_RIR,
    DEFAULT_TARGET_SETS,
    MAX_EXERCISES_PER_DAY,
    MAX_PROGRAM_DAYS,
    MAX_PROGRAM_NOTES_LENGTH,
    MAX_REPS,
    MAX_TEMPO_LENGTH,
    MAX_TARGET_RIR,
    MIN_REPS,
    MIN_TARGET_RIR,
)
from service import coach_program_drafts
from service.assignments import authorized_player_ledger
from service.program_import_constants import (
    MAX_PROGRAM_IMPORT_COLUMNS,
    MAX_PROGRAM_IMPORT_DAY_NAME_LENGTH,
    MAX_PROGRAM_IMPORT_EXERCISE_NAME_LENGTH,
    MAX_PROGRAM_IMPORT_FILE_BYTES,
    MAX_PROGRAM_IMPORT_REST_SECONDS,
    MAX_PROGRAM_IMPORT_ROWS,
    MAX_PROGRAM_IMPORT_SETS,
    MAX_PROGRAM_IMPORT_TABS,
    MAX_PROGRAM_IMPORT_TAB_PROBE_ROWS,
)

TEMPLATE_COLUMNS = (
    "day", "day_name", "order", "exercise", "sets", "reps", "rir", "rpe",
    "load_kg", "load_pct_e1rm", "rest_sec", "tempo", "notes",
)
_REP_RANGE = re.compile(r"^(\d+)\s*-\s*(\d+)$")
_PER_SET_REP_LIST = re.compile(r"^(?:\d+\s*[x×]\s*)?(\d+(?:\s*[,/]\s*\d+)+)$", re.IGNORECASE)
_EFFORT_VALUE = re.compile(r"^(?:RIR\s*)?(\d+(?:\.\d+)?)$", re.IGNORECASE)
_EFFORT_RANGE = re.compile(r"^(?:RIR\s*)?(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$", re.IGNORECASE)
_RPE_VALUE = re.compile(r"^(?:RPE\s*|@\s*)(\d+(?:\.\d+)?)$", re.IGNORECASE)
_RPE_RANGE = re.compile(r"^(?:RPE\s*|@\s*)?(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$", re.IGNORECASE)


class ProgramImportError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class Approximation:
    code: str
    column: str
    original: str = ""


ImportValue = int | float | str | bool | dt.date | dt.datetime | dt.time | None


@dataclass(frozen=True)
class ProgramImportRow:
    """Reader-neutral row. Values stay typed where possible; source text is retained for review."""

    source_row: int
    day: ImportValue
    day_name: ImportValue
    order: ImportValue
    exercise: ImportValue
    sets: ImportValue
    reps_min: ImportValue
    reps_max: ImportValue
    rir: ImportValue
    rpe: ImportValue
    rest_seconds: ImportValue
    tempo: ImportValue
    notes: ImportValue
    original_text: str
    reps_original: ImportValue = None
    approximation_markers: tuple[Approximation, ...] = ()
    confirmed_exercise_id: str | None = None


@dataclass(frozen=True)
class ReaderOutput:
    detected_tabs: list[str]
    selected_tab: str | None
    requires_tab_choice: bool
    rows: list[ProgramImportRow] = field(default_factory=list)


class ProgramImportReader(Protocol):
    def read(self, payload: bytes, filename: str, selected_tab: str | None) -> ReaderOutput:
        """Return canonical rows; all validation and resolution happens after this boundary."""


class TemplateProgramImportReader:
    """Translate the MAYOS XLSX/CSV columns to the reader-neutral row shape."""

    def read(self, payload: bytes, filename: str, selected_tab: str | None) -> ReaderOutput:
        extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if extension == "csv":
            if selected_tab:
                raise ProgramImportError("program_import.tab_invalid.v1", "CSV files have one sheet.")
            return _read_csv(payload)
        if extension == "xlsx":
            return _read_xlsx(payload, selected_tab)
        raise ProgramImportError("program_import.file_type.v1", "Upload an XLSX or CSV file.")


def import_program_sheet(
    db: Any,
    coach_account_id: str,
    assignment_id: str,
    payload: bytes,
    filename: str,
    selected_tab: str | None = None,
    reader: ProgramImportReader | None = None,
) -> dict[str, Any] | None:
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    if len(payload) > MAX_PROGRAM_IMPORT_FILE_BYTES:
        raise ProgramImportError("program_import.file_too_large.v1", "Trim the file to 1 MB or less.", 413)
    ledger, _ = authorized
    with ledger:
        draft_exists = ledger.get_program_draft(assignment_id) is not None
    source = (reader or TemplateProgramImportReader()).read(payload, filename, selected_tab)
    rows = [] if source.requires_tab_choice else validate_and_resolve_rows(db, coach_account_id, source.rows)
    return _build_import_result(source, draft_exists, rows)


def create_imported_program_draft(
    db: Any,
    coach_account_id: str,
    assignment_id: str,
    program_name: str | None,
    rows: list[dict[str, Any]],
    *,
    replace: bool = False,
) -> dict[str, Any] | None:
    authorized = authorized_player_ledger(db, coach_account_id, assignment_id)
    if authorized is None:
        return None
    ledger, _ = authorized
    # authorized_player_ledger opens the ledger; close it here before the draft service reopens it.
    with ledger:
        pass
    source_rows = [_confirmed_row(row) for row in rows]
    reviewed_rows = validate_and_resolve_rows(db, coach_account_id, source_rows)
    grouped = _confirmed_rows_by_day(db, coach_account_id, reviewed_rows)
    draft = {
        "program_name": (program_name or "").strip() or "Imported program",
        "split_type": "custom",
        "weekly_frequency": len(grouped),
        "instructions": "",
        "days": grouped,
    }
    from svc.schemas import CoachProgramDraftIn

    validated = CoachProgramDraftIn.model_validate(draft).model_dump()
    return _save_imported_draft(db, coach_account_id, assignment_id, validated, replace)


def _save_imported_draft(
    db: Any,
    coach_account_id: str,
    assignment_id: str,
    draft: dict[str, Any],
    replace: bool,
) -> dict[str, Any] | None:
    try:
        if replace:
            try:
                return coach_program_drafts.replace_program_draft(db, coach_account_id, assignment_id, draft)
            except coach_program_drafts.ProgramDraftNotFound:
                return coach_program_drafts.create_program_draft(db, coach_account_id, assignment_id, draft)
        return coach_program_drafts.create_program_draft(db, coach_account_id, assignment_id, draft)
    except coach_program_drafts.ProgramDraftAlreadyExists as error:
        raise ProgramImportError("assignment.program_draft_exists.v1", str(error), 409) from error


def template_csv_bytes() -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(TEMPLATE_COLUMNS)
    writer.writerow((1, "Example: Push", 1, "Bench Press", 3, "6-8", 2, "", "", "", 120, "2-0-1", "Pause briefly at the chest"))
    return output.getvalue().encode("utf-8-sig")


def template_xlsx_bytes() -> bytes:
    workbook = Workbook()
    program = workbook.active
    program.title = "Program"
    program.append(TEMPLATE_COLUMNS)
    example = workbook.create_sheet("Example")
    example.append(TEMPLATE_COLUMNS)
    example.append((1, "Push", 1, "Bench Press", 3, "6-8", 2, "", "", "", 120, "2-0-1", "Pause briefly at the chest"))
    for worksheet in (program, example):
        for column in ("F", "G", "H"):
            worksheet.column_dimensions[column].number_format = "@"
            for row_number in range(1, MAX_PROGRAM_IMPORT_ROWS + 2):
                worksheet[f"{column}{row_number}"].number_format = "@"
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _build_import_result(source: ReaderOutput, draft_exists: bool, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "detected_tabs": source.detected_tabs,
        "selected_tab": source.selected_tab,
        "requires_tab_choice": source.requires_tab_choice,
        "detected_weeks": [],
        "selected_week": None,
        "weeks_not_imported": [],
        "confirm_layout": False,
        "draft_exists": draft_exists,
        "rows": rows,
        "errors": [error for row in rows for error in row["errors"]],
        "unresolved_names": _unresolved_names(rows),
    }


def _read_csv(payload: bytes) -> ReaderOutput:
    try:
        text = payload.decode("utf-8-sig")
        return _rows_from_table(csv.reader(io.StringIO(text)), ["CSV"], "CSV")
    except ProgramImportError:
        raise
    except Exception as error:
        raise ProgramImportError("program_import.file_invalid.v1", "The CSV file could not be read.") from error


def _read_xlsx(payload: bytes, selected_tab: str | None) -> ReaderOutput:
    workbook = None
    try:
        workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
        return _read_selected_xlsx(workbook, selected_tab)
    except ProgramImportError:
        raise
    except Exception as error:
        raise ProgramImportError("program_import.file_invalid.v1", "The XLSX file could not be read.") from error
    finally:
        if workbook is not None:
            try:
                workbook.close()
            except Exception:
                pass


def _read_selected_xlsx(workbook: Any, selected_tab: str | None) -> ReaderOutput:
    if len(workbook.worksheets) > MAX_PROGRAM_IMPORT_TABS:
        raise ProgramImportError(
            "program_import.too_many_tabs.v1",
            f"Trim the workbook to {MAX_PROGRAM_IMPORT_TABS} sheets or fewer.",
            413,
        )
    tabs = [sheet.title for sheet in workbook.worksheets if _sheet_has_values(sheet)]
    if not tabs:
        raise ProgramImportError("program_import.sheet_empty.v1", "The workbook has no non-empty sheets.")
    choice_tabs = [tab for tab in tabs if tab.casefold() != "example"]
    if len(choice_tabs) > 1 and selected_tab is None:
        return ReaderOutput(tabs, None, True)
    if selected_tab is None:
        selected = "Program" if "Program" in tabs else (choice_tabs or tabs)[0]
    else:
        selected = selected_tab
    if selected not in tabs:
        raise ProgramImportError("program_import.tab_invalid.v1", "Choose a non-empty sheet from this workbook.")
    sheet = workbook[selected]
    if (sheet.max_row or 0) > MAX_PROGRAM_IMPORT_ROWS + 2:
        raise ProgramImportError("program_import.too_many_rows.v1", "Trim the sheet to 500 exercise rows or fewer.", 413)
    if (sheet.max_column or 0) > MAX_PROGRAM_IMPORT_COLUMNS:
        raise ProgramImportError(
            "program_import.too_many_columns.v1",
            f"Trim the sheet to {MAX_PROGRAM_IMPORT_COLUMNS} columns or fewer.",
            413,
        )
    return _rows_from_table(
        sheet.iter_rows(max_row=MAX_PROGRAM_IMPORT_ROWS + 2, max_col=MAX_PROGRAM_IMPORT_COLUMNS, values_only=True),
        tabs,
        selected,
    )


def _sheet_has_values(sheet: Any) -> bool:
    for row in sheet.iter_rows(
        max_row=MAX_PROGRAM_IMPORT_TAB_PROBE_ROWS,
        max_col=MAX_PROGRAM_IMPORT_COLUMNS,
        values_only=True,
    ):
        if any(value is not None and str(value).strip() for value in row):
            return True
    # Dimensions are metadata. Treat content beyond the bounded probe as possibly non-empty.
    return (sheet.max_row or 0) > MAX_PROGRAM_IMPORT_TAB_PROBE_ROWS or (sheet.max_column or 0) > MAX_PROGRAM_IMPORT_COLUMNS


def _rows_from_table(
    table: Iterable[Iterable[Any]], detected_tabs: list[str], selected_tab: str | None
) -> ReaderOutput:
    columns: dict[str, int] | None = None
    rows: list[ProgramImportRow] = []
    required = {"day", "exercise", "sets"}
    for row_number, values in enumerate(table, start=1):
        if row_number > MAX_PROGRAM_IMPORT_ROWS + 2:
            raise ProgramImportError("program_import.too_many_rows.v1", "Trim the sheet to 500 exercise rows or fewer.", 413)
        cells = list(values)
        if len(cells) > MAX_PROGRAM_IMPORT_COLUMNS:
            raise ProgramImportError(
                "program_import.too_many_columns.v1",
                f"Trim the sheet to {MAX_PROGRAM_IMPORT_COLUMNS} columns or fewer.",
                413,
            )
        if columns is None:
            headers = [_cell_text(cell).casefold() for cell in cells]
            if not any(headers):
                continue
            columns = {name: index for index, name in enumerate(headers) if name in TEMPLATE_COLUMNS}
            missing = required - columns.keys()
            if "reps" not in columns:
                missing.add("reps")
            if missing:
                raise ProgramImportError(
                    "program_import.template_columns.v1",
                    "Required template columns are missing: " + ", ".join(sorted(missing)),
                )
            continue
        named = {
            name: cells[index] if index < len(cells) else None
            for name, index in columns.items()
        }
        if not any(value is not None and str(value).strip() for value in named.values()):
            continue
        rows.append(_template_row(row_number, named))
        if len(rows) > MAX_PROGRAM_IMPORT_ROWS:
            break
    if columns is None:
        raise ProgramImportError("program_import.sheet_empty.v1", "The selected sheet is empty.")
    return ReaderOutput(detected_tabs, selected_tab, False, rows)


def _template_row(source_row: int, cells: dict[str, Any]) -> ProgramImportRow:
    reps = cells.get("reps")
    reps_min, reps_max, rep_markers = _reader_reps(reps)
    notes = _cell_text(cells.get("notes"))
    markers = list(rep_markers)
    for column, label in (("load_kg", "load"), ("load_pct_e1rm", "% e1RM")):
        value = _cell_text(cells.get(column))
        if value:
            notes = "\n".join(part for part in (notes, f"{label}: {value}") if part)
            markers.append(Approximation("program_import.load_preserved_as_note.v1", column, value))
    raw_values = {key: _cell_text(value) for key, value in cells.items() if value is not None}
    return ProgramImportRow(
        source_row=source_row,
        day=cells.get("day"),
        day_name=cells.get("day_name"),
        order=cells.get("order"),
        exercise=cells.get("exercise"),
        sets=cells.get("sets"),
        reps_min=reps_min,
        reps_max=reps_max,
        reps_original=reps,
        rir=cells.get("rir"),
        rpe=cells.get("rpe"),
        rest_seconds=cells.get("rest_sec"),
        tempo=cells.get("tempo"),
        notes=notes,
        original_text=" | ".join(f"{key}: {value}" for key, value in raw_values.items()),
        approximation_markers=tuple(markers),
    )


def _reader_reps(value: Any) -> tuple[ImportValue, ImportValue, tuple[Approximation, ...]]:
    if isinstance(value, (dt.date, dt.datetime)):
        return value, None, ()
    if isinstance(value, bool):
        return value, None, ()
    if isinstance(value, int) or (isinstance(value, float) and math.isfinite(value) and value.is_integer()):
        number = int(value)
        return number, number, ()
    text = _cell_text(value)
    if not text:
        return None, None, ()
    match = _REP_RANGE.fullmatch(text)
    if match:
        return int(match.group(1)), int(match.group(2)), ()
    if re.fullmatch(r"\d+", text):
        value = int(text)
        return value, value, ()
    list_match = _PER_SET_REP_LIST.fullmatch(text)
    if list_match:
        reps = [int(part) for part in re.split(r"[,/]", list_match.group(1))]
        return min(reps), max(reps), (Approximation("program_import.reps_approximated.v1", "reps", text),)
    return text, None, ()


def validate_and_resolve_rows(
    db: Any, coach_account_id: str, source_rows: list[ProgramImportRow]
) -> list[dict[str, Any]]:
    """Shared normalization, row validation, row-level checks, and exercise resolution."""
    if len(source_rows) > MAX_PROGRAM_IMPORT_ROWS:
        raise ProgramImportError("program_import.too_many_rows.v1", "Trim the sheet to 500 exercise rows or fewer.", 413)
    output: list[dict[str, Any]] = []
    order_by_day: dict[int, int] = {}
    for source in source_rows:
        row = _normalise_row(source, order_by_day)
        resolution = _resolve_exercise(db, coach_account_id, row["exercise_name"], source.confirmed_exercise_id)
        resolution_errors = resolution.pop("errors", [])
        resolution_warnings = resolution.pop("warnings", [])
        for item in resolution_errors + resolution_warnings:
            item["source_row"] = source.source_row
        row["errors"].extend(resolution_errors)
        row["warnings"].extend(resolution_warnings)
        row.update(resolution)
        row["approximation_markers"] = [warning["code"] for warning in row["warnings"]]
        row["valid"] = not row["errors"]
        output.append(row)
    _normalise_day_names(output)
    _mark_per_day_count_errors(output)
    _mark_conflicting_day_names(output)
    return output


def _normalise_row(source: ProgramImportRow, order_by_day: dict[int, int]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings = [_row_warning(item.code, source.source_row, item.column, "") for item in source.approximation_markers]
    day = _parse_integer(source.day)
    day_valid = day is not None and 1 <= day <= MAX_PROGRAM_DAYS
    if not day_valid:
        errors.append(_row_error("program_import.invalid_day.v1", source.source_row, "day", "Day is outside the supported range."))
        day = 1
    if day_valid:
        order_by_day[day] = order_by_day.get(day, 0) + 1
    order = _parse_integer(source.order)
    if order is None:
        order = order_by_day.get(day, 1)
    elif not 1 <= order <= MAX_PROGRAM_IMPORT_ROWS:
        errors.append(_row_error("program_import.invalid_order.v1", source.source_row, "order", "Exercise order is outside the supported range."))
        order = order_by_day.get(day, 1)

    sets, set_error, set_warning = _normalise_sets(source.sets, source.source_row)
    if set_error:
        errors.append(set_error)
    if set_warning:
        warnings.append(set_warning)

    reps_min, reps_max, reps_error, reps_warning, reps_note = _normalise_reps(
        source.reps_min, source.reps_max, source.reps_original, source.source_row
    )
    if reps_error:
        errors.append(reps_error)
    if reps_warning:
        warnings.append(reps_warning)
    marker_notes = [f"reps: {item.original}" for item in source.approximation_markers if item.column == "reps" and item.original]
    if marker_notes:
        reps_note = "\n".join(marker_notes)

    target_rir, effort_errors, effort_warnings, effort_notes = _normalise_effort(
        source.rir, source.rpe, source.source_row
    )
    errors.extend(effort_errors)
    warnings.extend(effort_warnings)

    rest_seconds = _parse_integer(source.rest_seconds)
    if source.rest_seconds not in (None, "") and (
        rest_seconds is None or not 0 <= rest_seconds <= MAX_PROGRAM_IMPORT_REST_SECONDS
    ):
        errors.append(_row_error("program_import.invalid_rest.v1", source.source_row, "rest_seconds", "Rest is outside the supported range."))
        rest_seconds = DEFAULT_EXERCISE_REST_SECONDS
    elif rest_seconds is None:
        rest_seconds = DEFAULT_EXERCISE_REST_SECONDS

    exercise_name = _cell_text(source.exercise)
    if not exercise_name:
        errors.append(_row_error("program_import.exercise_required.v1", source.source_row, "exercise", "Enter an exercise name."))
    elif len(exercise_name) > MAX_PROGRAM_IMPORT_EXERCISE_NAME_LENGTH:
        errors.append(_row_error("program_import.exercise_name_too_long.v1", source.source_row, "exercise", "Exercise name is too long."))

    day_name = _cell_text(source.day_name) or None
    if day_name and len(day_name) > MAX_PROGRAM_IMPORT_DAY_NAME_LENGTH:
        errors.append(_row_error("program_import.day_name_too_long.v1", source.source_row, "day_name", "Day name is too long."))

    tempo = _cell_text(source.tempo) or None
    if tempo and len(tempo) > MAX_TEMPO_LENGTH:
        errors.append(_row_error("program_import.tempo_too_long.v1", source.source_row, "tempo", "Tempo is too long."))

    notes = _join_notes(source.notes, reps_note, effort_notes)
    if len(notes) > MAX_PROGRAM_NOTES_LENGTH:
        errors.append(_row_error("program_import.notes_too_long.v1", source.source_row, "notes", "Notes are too long."))

    return {
        "source_row": source.source_row,
        "original_text": source.original_text,
        "approximation_markers": [item.code for item in source.approximation_markers],
        "day": day,
        "day_valid": day_valid,
        "day_name": day_name,
        "order": order,
        "exercise_name": exercise_name,
        "exercise_id": source.confirmed_exercise_id,
        "resolution": "unresolved",
        "suggestions": [],
        "sets": sets,
        "reps_min": reps_min,
        "reps_max": reps_max,
        "target_rir": target_rir,
        "rest_seconds": rest_seconds,
        "tempo": tempo,
        "notes": notes or None,
        "errors": errors,
        "warnings": warnings,
    }


def _normalise_sets(value: Any, source_row: int) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None]:
    sets = _parse_integer(value)
    if sets is not None and 1 <= sets <= MAX_PROGRAM_IMPORT_SETS:
        return sets, None, None
    error = _row_error("program_import.invalid_sets.v1", source_row, "sets", "Working sets are outside the supported range.")
    return DEFAULT_TARGET_SETS, error, None


def _normalise_reps(
    lower_value: Any, upper_value: Any, original_value: Any, source_row: int
) -> tuple[int, int, dict[str, Any] | None, dict[str, Any] | None, str]:
    if isinstance(lower_value, (dt.date, dt.datetime)):
        error = _row_error("program_import.reps_as_date.v1", source_row, "reps", "Format reps as text and type the prescription again.")
        return DEFAULT_TARGET_REPS_MIN, DEFAULT_TARGET_REPS_MAX, error, None, ""
    lower = _parse_integer(lower_value)
    upper = _parse_integer(upper_value)
    raw = _cell_text(lower_value)
    original = _cell_text(original_value)
    if upper is None and raw:
        match = _REP_RANGE.fullmatch(raw)
        if match:
            lower, upper = int(match.group(1)), int(match.group(2))
        elif list_match := _PER_SET_REP_LIST.fullmatch(raw):
            values = [int(part) for part in re.split(r"[,/]", list_match.group(1))]
            lower, upper = min(values), max(values)
            warning = _row_warning("program_import.reps_approximated.v1", source_row, "reps", "Per-set repetitions were converted to a range.")
            return _check_rep_bounds(lower, upper, source_row, warning, raw)
        elif re.fullmatch(r"\d+(?:\.0+)?", raw):
            lower = upper = int(float(raw))
        elif _is_unsupported_rep_prescription(raw or original):
            raw = raw or original
            warning = _row_warning("program_import.reps_approximated.v1", source_row, "reps", "Unsupported repetitions were approximated.")
            return DEFAULT_TARGET_REPS_MIN, DEFAULT_TARGET_REPS_MAX, None, warning, f"reps: {raw}"
        else:
            error = _row_error("program_import.invalid_reps.v1", source_row, "reps", "Enter a number, range, or supported prescription.")
            return DEFAULT_TARGET_REPS_MIN, DEFAULT_TARGET_REPS_MAX, error, None, ""
    if lower is None or upper is None:
        error = _row_error("program_import.reps_required.v1", source_row, "reps", "Enter repetitions.")
        return DEFAULT_TARGET_REPS_MIN, DEFAULT_TARGET_REPS_MAX, error, None, ""
    return _check_rep_bounds(lower, upper, source_row, None, "")


def _check_rep_bounds(
    lower: int,
    upper: int,
    source_row: int,
    warning: dict[str, Any] | None,
    original: str,
) -> tuple[int, int, dict[str, Any] | None, dict[str, Any] | None, str]:
    if lower > upper or lower < MIN_REPS or upper > MAX_REPS:
        error = _row_error("program_import.invalid_reps.v1", source_row, "reps", "Repetitions are outside the supported range.")
        return DEFAULT_TARGET_REPS_MIN, DEFAULT_TARGET_REPS_MAX, error, None, ""
    return lower, upper, None, warning, f"reps: {original}" if warning and original else ""


def _is_unsupported_rep_prescription(value: str) -> bool:
    clean = value.casefold()
    return any(token in clean for token in ("amrap", "failure", "%", "top set", "back-off", "back off", "superset", "+", "x"))


def _normalise_effort(
    rir_value: Any, rpe_value: Any, source_row: int
) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    notes: list[str] = []
    raw_rir, raw_rpe = _cell_text(rir_value), _cell_text(rpe_value)
    if (raw_rir.startswith("@") or raw_rir.casefold().startswith("rpe")) and not raw_rpe:
        raw_rpe, raw_rir = raw_rir, ""
    rir, rir_approx, rir_garbage = _parse_effort_value(raw_rir, is_rpe=False)
    rpe, rpe_approx, rpe_garbage = _parse_effort_value(raw_rpe, is_rpe=True)
    if rir_garbage or rpe_garbage:
        column = "rir" if rir_garbage else "rpe"
        errors.append(_row_error("program_import.invalid_effort.v1", source_row, column, "Enter a numeric RIR or RPE value."))
    converted = None if rpe is None else 10.0 - rpe
    if rir is not None and converted is not None and abs(rir - converted) > 0.001:
        errors.append(_row_error("program_import.conflicting_effort.v1", source_row, "rpe", "RIR and RPE values do not match."))
    if converted is not None:
        warnings.append(_row_warning("program_import.rpe_converted.v1", source_row, "rpe", "RPE was converted to RIR."))
        notes.append(f"RPE: {raw_rpe}")
    if rir_approx or rpe_approx:
        original = raw_rir or raw_rpe
        warnings.append(_row_warning("program_import.effort_approximated.v1", source_row, "rir" if raw_rir else "rpe", "Effort was approximated using the midpoint, clamped to the supported range."))
        notes.append(f"effort: {original}")
    selected = rir if rir is not None else converted
    if selected is None:
        return DEFAULT_TARGET_RIR, errors, warnings, notes
    return min(MAX_TARGET_RIR, max(MIN_TARGET_RIR, selected)), errors, warnings, notes


def _parse_effort_value(raw: str, *, is_rpe: bool) -> tuple[float | None, bool, bool]:
    if not raw:
        return None, False, False
    value_match = _RPE_VALUE.fullmatch(raw) if is_rpe else _EFFORT_VALUE.fullmatch(raw)
    range_match = _RPE_RANGE.fullmatch(raw) if is_rpe else _EFFORT_RANGE.fullmatch(raw)
    approximate = False
    if value_match:
        value = float(value_match.group(1))
        approximate = raw != value_match.group(1)
    elif range_match:
        value = (float(range_match.group(1)) + float(range_match.group(2))) / 2
        approximate = True
    else:
        return None, False, True
    low, high = (5.0, 10.0) if is_rpe else (MIN_TARGET_RIR, MAX_TARGET_RIR)
    if not low <= value <= high:
        value = min(high, max(low, value))
        approximate = True
    return value, approximate, False


def _join_notes(*values: Any) -> str:
    return "\n".join(text for value in values if (text := _cell_text(value)))


def _normalise_day_names(rows: list[dict[str, Any]]) -> None:
    names: dict[int, str] = {}
    for row in rows:
        if row["day_valid"] and row["day_name"]:
            names.setdefault(row["day"], row["day_name"])
    for row in rows:
        if not row["day_name"]:
            row["day_name"] = names.get(row["day"], f"Day {row['day']}")


def _mark_per_day_count_errors(rows: list[dict[str, Any]]) -> None:
    counts: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        if row["valid"] and row["day_valid"] and row["exercise_name"]:
            counts.setdefault(row["day"], []).append(row)
    for day_rows in counts.values():
        for row in day_rows[MAX_EXERCISES_PER_DAY:]:
            row["errors"].append(_row_error("program_import.too_many_exercises.v1", row["source_row"], "exercise", "A day has too many exercises."))
            row["valid"] = False


def _mark_conflicting_day_names(rows: list[dict[str, Any]]) -> None:
    names: dict[int, str] = {}
    for row in rows:
        if not row["day_valid"] or not row["day_name"]:
            continue
        current = names.setdefault(row["day"], row["day_name"])
        if row["day_name"] != current:
            row["errors"].append(_row_error("program_import.conflicting_day_name.v1", row["source_row"], "day_name", "Use one name for each day number."))
            row["valid"] = False


def _resolve_exercise(db: Any, coach_account_id: str, name: str, confirmed_id: str | None) -> dict[str, Any]:
    if confirmed_id:
        entry = db.get_exercise_library_entry(confirmed_id)
        if entry is None:
            entry = db.get_coach_exercise(coach_account_id, confirmed_id)
        if entry is None:
            return {"exercise_id": None, "resolution": "invalid", "suggestions": [],
                    "errors": [_row_error("program_import.exercise_invalid.v1", 0, "exercise", "Choose an exercise owned by this coach or in the library.")]}
        return {"exercise_id": confirmed_id, "exercise_name": entry["name"], "resolution": "confirmed", "suggestions": [], "errors": []}
    exact_id = db.find_unique_exercise_id_by_exact_name(name) if name else None
    if exact_id:
        entry = db.get_exercise_library_entry(exact_id)
        return {"exercise_id": exact_id, "exercise_name": entry["name"], "resolution": "resolved", "suggestions": [], "errors": []}
    coach_matches = db.search_coach_exercises(coach_account_id, name, limit=None) if name else []
    own_exact = [entry for entry in coach_matches if entry["name"].casefold() == name.casefold()]
    if len(own_exact) == 1:
        entry = own_exact[0]
        return {"exercise_id": entry["id"], "exercise_name": entry["name"], "resolution": "resolved", "suggestions": [], "errors": []}
    library_matches = db.find_exercises_by_name(name, limit=10) if name else []
    suggestions = _unique_suggestions([*library_matches, *own_exact])[:3]
    ambiguous = len(library_matches) > 1 or len(own_exact) > 1
    code = "program_import.exercise_ambiguous.v1" if ambiguous else "program_import.exercise_unresolved.v1"
    column_message = "Several exercises match; choose one." if ambiguous else "No exact exercise match; choose a suggestion or create your exercise."
    warning = _row_warning(code, 0, "exercise", column_message)
    return {"exercise_id": None, "resolution": "ambiguous" if ambiguous else "unresolved", "suggestions": suggestions, "errors": [], "warnings": [warning]}


def _unique_suggestions(matches: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    suggestions = []
    for match in matches:
        exercise_id = str(match["id"])
        if exercise_id not in seen:
            seen.add(exercise_id)
            suggestions.append({"exercise_id": exercise_id, "name": str(match["name"])})
    return suggestions


def _unresolved_names(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unresolved: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["resolution"] in {"resolved", "confirmed"}:
            continue
        name = row["exercise_name"]
        item = unresolved.setdefault(name, {"name": name, "resolution": row["resolution"], "rows": [], "suggestions": row["suggestions"]})
        item["rows"].append(row["source_row"])
    return list(unresolved.values())


def _confirmed_row(row: dict[str, Any]) -> ProgramImportRow:
    return ProgramImportRow(
        source_row=row["source_row"],
        day=row["day"],
        day_name=row.get("day_name"),
        order=row.get("order"),
        exercise=row["exercise_name"],
        sets=row["sets"],
        reps_min=row["reps_min"],
        reps_max=row["reps_max"],
        reps_original=f"{row['reps_min']}-{row['reps_max']}",
        rir=row["target_rir"],
        rpe=None,
        rest_seconds=row["rest_seconds"],
        tempo=row.get("tempo"),
        notes=row.get("notes"),
        original_text="",
        confirmed_exercise_id=row["exercise_id"],
    )


def _confirmed_rows_by_day(db: Any, coach_account_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    days: dict[int, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda candidate: (candidate["day"], candidate["order"], candidate["source_row"])):
        if not row["valid"] or not row["exercise_id"]:
            continue
        if row["errors"]:
            continue
        exercise_id = row["exercise_id"]
        entry = db.get_exercise_library_entry(exercise_id)
        is_coach = False
        if entry is None:
            entry = db.get_coach_exercise(coach_account_id, exercise_id)
            is_coach = entry is not None
        if entry is None:
            continue
        day_number = row["day"]
        day = days.setdefault(day_number, {
            "day_name": row["day_name"], "day_order": day_number,
            "warmup_exercises": [], "exercises": [], "cardio": None,
        })
        day["exercises"].append({
            "exercise_id": exercise_id,
            "exercise_name": entry["name"],
            "body_part": entry.get("body_part") if is_coach else None,
            "equipment": entry.get("equipment"),
            "note": entry.get("note") if is_coach else None,
            "video_url": entry.get("video_url") if is_coach else None,
            "is_coach_exercise": is_coach,
            "target_sets": row["sets"],
            "target_reps_min": row["reps_min"],
            "target_reps_max": row["reps_max"],
            "target_rir": row["target_rir"],
            "rest_seconds": row["rest_seconds"],
            "tempo": row["tempo"],
            "notes": row["notes"],
        })
    if not days:
        raise ProgramImportError("program_import.no_rows.v1", "No valid confirmed rows are ready to create a draft.")
    return list(days.values())


def _cell_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _parse_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    try:
        text = _cell_text(value)
        return int(text) if text else None
    except (ValueError, TypeError, OverflowError):
        return None


def _row_error(code: str, source_row: int, column: str, message: str) -> dict[str, Any]:
    return {"source_row": source_row, "column": column, "code": code, "message": message}


def _row_warning(code: str, source_row: int, column: str, message: str) -> dict[str, Any]:
    return {"source_row": source_row, "column": column, "code": code, "message": message}
