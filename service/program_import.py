"""In-memory readers and the shared Program import pipeline."""

import csv
import datetime as dt
import io
import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Protocol

from fastapi import BackgroundTasks
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
    MAX_PROGRAM_IMPORT_CELLS,
    MAX_PROGRAM_IMPORT_REST_SECONDS,
    MAX_PROGRAM_IMPORT_ROWS,
    MAX_PROGRAM_IMPORT_SETS,
    MAX_PROGRAM_IMPORT_TABS,
    MAX_PROGRAM_IMPORT_TAB_PROBE_ROWS,
    MAX_PROGRAM_IMPORT_GRID_COLUMNS,
    MAX_PROGRAM_IMPORT_GRID_ROWS,
    MAX_PROGRAM_IMPORT_GRID_RECTANGLE,
    MAX_PROGRAM_IMPORT_HEADER_SCAN_ROWS,
    MIN_PROGRAM_IMPORT_LAYOUT_CONFIDENCE,
)
from service import analytics, program_import_ai

if TYPE_CHECKING:
    from svc.llm import InferenceScope

TEMPLATE_COLUMNS = (
    "day", "day_name", "order", "exercise", "sets", "reps", "rir", "rpe",
    "load_kg", "load_pct_e1rm", "rest_sec", "tempo", "notes",
)
_REP_RANGE = re.compile(r"^(\d+)\s*-\s*(\d+)$")
_PER_SET_REP_LIST = re.compile(r"^(?:\d+\s*[x×]\s*)?(\d+(?:\s*[,/]\s*\d+)+)$", re.IGNORECASE)
_EFFORT_VALUE = re.compile(r"^(?:RIR\s*)?(\d+(?:\.\d+)?)$", re.IGNORECASE)
_EFFORT_RANGE = re.compile(r"^(?:RIR\s*)?(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$", re.IGNORECASE)
_RPE_VALUE = re.compile(r"^(?:RPE\s*|@\s*)?(\d+(?:\.\d+)?)$", re.IGNORECASE)
_RPE_RANGE = re.compile(r"^(?:RPE\s*|@\s*)?(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$", re.IGNORECASE)
_SOURCE_HEADER_FIELDS = {
    "day": "day", "day number": "day", "training day": "day",
    "session": "day_name", "session name": "day_name", "day name": "day_name",
    "workout": "day_name", "workout name": "day_name",
    "exercise": "exercise", "movement": "exercise",
    "exercise as written": "exercise", "lift": "exercise",
    "slot": "slot", "week": "week", "week number": "week",
    "training week": "week", "set": "sets", "sets": "sets",
    "rpe": "rpe", "rir": "rir", "reps": "reps", "rep": "reps",
    "prescription": "prescription", "reps by set": "reps_by_set",
    "rep scheme": "reps_by_set",
}
_UNSUPPORTED_PRESCRIPTION_PATTERNS = (
    (r"\bAMRAP\b|\btop\s+set\b|\bback[ -]?off\b|\bsuperset\b", "prescription"),
    (r"\d+\s*[x×]\s*\d+(?:\s*[,/]\s*\d+)+", "reps"),
    (r"\d+(?:\.\d+)?\s*%", "load_pct_e1rm"),
    (r"weekly\s+(?:progression|increase|increase reps|add reps)|[+-]\s*\d+(?:\.\d+)?\s*(?:kg|lb)\s*/\s*(?:week|wk)", "notes"),
)


class ProgramImportError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        message_params: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message_params = message_params or {}


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
    week: str | None = None
    suggestion_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReaderOutput:
    detected_tabs: list[str]
    selected_tab: str | None
    requires_tab_choice: bool
    rows: list[ProgramImportRow] = field(default_factory=list)
    detected_weeks: list[str] = field(default_factory=list)
    selected_week: str | None = None
    weeks_not_imported: list[str] = field(default_factory=list)
    confirm_layout: bool = False
    layout_days: list[dict[str, Any]] = field(default_factory=list)
    layout_confidence: float | None = None
    import_mode: str = "template"


@dataclass(frozen=True)
class ReaderDetection:
    detected_tabs: list[str]
    selected_tab: str | None
    requires_tab_choice: bool
    is_template: bool


@dataclass(frozen=True)
class FreeFormCellGrid:
    grid: dict[str, Any] | None
    tabs: list[str]
    selected_tab: str | None


@dataclass(frozen=True)
class FreeFormGridContext:
    cells_by_row: dict[int, dict[int, str]]
    columns: dict[int, tuple[str, int | None]]
    header_row: int | None
    week_labels: list[str]
    day_names: dict[int, str]
    day_numbers: dict[str, int]


@dataclass(frozen=True)
class FreeFormSourceRow:
    fields: dict[str, str]
    text: str


@dataclass(frozen=True)
class FreeFormRowValues:
    day: Any
    day_name: str | None
    rir: Any
    rpe: Any
    reps_original: Any
    approximation_markers: tuple[Approximation, ...]


@dataclass(frozen=True)
class ProgramImportRequest:
    coach_account_id: str
    assignment_id: str
    payload: bytes
    filename: str
    selected_tab: str | None = None
    reader: "ProgramImportReader | None" = None
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT
    background_tasks: BackgroundTasks | None = None


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


class FreeFormProgramImportReader:
    """Translate one bounded, coach-selected sheet through the hosted coach model."""

    def __init__(self, inference_scope: "InferenceScope"):
        self.inference_scope = inference_scope

    def read(self, prepared: FreeFormCellGrid) -> ReaderOutput:
        if prepared.grid is None:
            return ReaderOutput(prepared.tabs, prepared.selected_tab, True, import_mode="freeform")
        try:
            reply = program_import_ai.translate_sheet(prepared.grid, self.inference_scope)
        except program_import_ai.ProgramImportAIError as error:
            raise ProgramImportError(
                "program_import.interpretation_failed.v1", str(error), 422
            ) from None
        except TimeoutError:
            raise ProgramImportError(
                "program_import.model_busy.v1",
                "The import assistant is busy with another request. Try again in a minute.",
                503,
            ) from None
        return _freeform_reader_output(reply, prepared.tabs, prepared.selected_tab, prepared.grid)


def import_program_sheet(db: Any, request: ProgramImportRequest) -> dict[str, Any] | None:
    authorized = authorized_player_ledger(db, request.coach_account_id, request.assignment_id)
    if authorized is None:
        return None
    if len(request.payload) > MAX_PROGRAM_IMPORT_FILE_BYTES:
        raise ProgramImportError("program_import.file_too_large.v1", "Trim the file to 1 MB or less.", 413)
    ledger, _ = authorized
    with ledger:
        draft_exists = ledger.get_program_draft(request.assignment_id) is not None
    if request.reader is not None:
        source = request.reader.read(request.payload, request.filename, request.selected_tab)
    else:
        detection = _detect_program_reader(
            request.payload, request.filename, request.selected_tab
        )
        if detection.requires_tab_choice:
            source = ReaderOutput(
                detection.detected_tabs,
                detection.selected_tab,
                True,
                import_mode="freeform" if not detection.is_template else "template",
            )
            return _build_import_result(source, draft_exists, [])
        source = (
            TemplateProgramImportReader().read(
                request.payload,
                request.filename,
                detection.selected_tab
                if request.filename.lower().endswith(".xlsx")
                else None,
            )
            if detection.is_template
            else None
        )
    if source is not None and source.requires_tab_choice:
        return _build_import_result(source, draft_exists, [])
    if source is None:
        freeform_result = _read_freeform_program(db, request)
        if freeform_result is None:
            return None
        source, rows = freeform_result
    else:
        rows = validate_and_resolve_rows(db, request.coach_account_id, source.rows)
    return _build_import_result(source, draft_exists, rows)


def _read_freeform_program(
    db: Any, request: ProgramImportRequest
) -> tuple[ReaderOutput, list[dict[str, Any]]] | None:
    gate = program_import_ai.resolve_enable_gate()
    if not gate.enabled:
        raise ProgramImportError(
            "program_import.freeform_disabled.v1",
            "Free-form import is unavailable. Use the MAYOS template.",
            503,
        )
    source, rows = _run_freeform_import(db, request)
    if db.get_active_assignment_for_coach(
        request.coach_account_id, request.assignment_id
    ) is None:
        return None
    return source, rows


def _run_freeform_import(
    db: Any, request: ProgramImportRequest
) -> tuple[ReaderOutput, list[dict[str, Any]]]:
    prepared = _freeform_cell_grid(
        request.payload, request.filename, request.selected_tab
    )
    if prepared.grid is None:
        return ReaderOutput(
            prepared.tabs, prepared.selected_tab, True, import_mode="freeform"
        ), []
    from svc.llm import InferenceScope, inference_turn

    scope = InferenceScope(
        account_id=request.coach_account_id,
        role="coach",
        purpose="coach_program_import",
        store=db,
        client=request.client,
    )
    with inference_turn(scope, background_tasks=request.background_tasks):
        source = FreeFormProgramImportReader(scope).read(prepared)
        rows = validate_and_resolve_rows(db, request.coach_account_id, source.rows)
        _add_model_suggestions(db, rows, scope)
    return source, rows


def _detect_program_reader(
    payload: bytes, filename: str, selected_tab: str | None
) -> ReaderDetection:
    extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if extension == "csv":
        if selected_tab:
            raise ProgramImportError("program_import.tab_invalid.v1", "CSV files have one sheet.")
        header = _csv_header(payload)
        return ReaderDetection(["CSV"], "CSV", False, _is_template_header(header))
    if extension != "xlsx":
        raise ProgramImportError("program_import.file_type.v1", "Upload an XLSX or CSV file.")
    workbook = None
    try:
        workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
        return _detect_xlsx_reader(workbook, selected_tab)
    except ProgramImportError:
        raise
    except Exception as error:
        raise ProgramImportError(
            "program_import.file_invalid.v1", "The XLSX file could not be read."
        ) from error
    finally:
        if workbook is not None:
            workbook.close()


def _csv_header(payload: bytes) -> list[str]:
    try:
        table = csv.reader(io.StringIO(payload.decode("utf-8-sig")))
        header = _first_non_empty_header(table)
    except (UnicodeDecodeError, csv.Error) as error:
        raise ProgramImportError(
            "program_import.file_invalid.v1", "The CSV file could not be read."
        ) from error
    if not header and not payload.strip():
        raise ProgramImportError("program_import.sheet_empty.v1", "The CSV sheet is empty.")
    return header


def _detect_xlsx_reader(workbook: Any, selected_tab: str | None) -> ReaderDetection:
    if len(workbook.worksheets) > MAX_PROGRAM_IMPORT_TABS:
        raise ProgramImportError(
            "program_import.too_many_tabs.v1", "Trim the workbook to 20 sheets or fewer.", 413
        )
    tabs = [sheet.title for sheet in workbook.worksheets if _sheet_has_values(sheet)]
    if not tabs:
        raise ProgramImportError("program_import.sheet_empty.v1", "The workbook has no non-empty sheets.")
    choice_tabs = [tab for tab in tabs if tab.casefold() != "example"]
    if len(choice_tabs) > 1 and selected_tab is None:
        return ReaderDetection(tabs, None, True, False)
    selected = selected_tab or ("Program" if "Program" in tabs else (choice_tabs or tabs)[0])
    if selected not in tabs:
        raise ProgramImportError(
            "program_import.tab_invalid.v1", "Choose a non-empty sheet from this workbook."
        )
    sheet = workbook[selected]
    header = _first_non_empty_header(
        sheet.iter_rows(
            max_row=MAX_PROGRAM_IMPORT_HEADER_SCAN_ROWS,
            max_col=MAX_PROGRAM_IMPORT_GRID_COLUMNS,
            values_only=True,
        )
    )
    if not header:
        if (
            (sheet.max_row or 0) > MAX_PROGRAM_IMPORT_GRID_ROWS
            or (sheet.max_column or 0) > MAX_PROGRAM_IMPORT_GRID_COLUMNS
        ):
            return ReaderDetection(tabs, selected, False, False)
        raise ProgramImportError("program_import.sheet_empty.v1", "The selected sheet is empty.")
    return ReaderDetection(tabs, selected, False, _is_template_header(header))


def _first_non_empty_header(table: Iterable[Iterable[Any]]) -> list[str]:
    for row_number, values in enumerate(table, start=1):
        if row_number > MAX_PROGRAM_IMPORT_HEADER_SCAN_ROWS:
            break
        header = [_cell_text(value).casefold() for value in values]
        if any(header):
            return header
    return []


def _is_template_header(header: list[str]) -> bool:
    required = {"day", "exercise", "sets", "reps"}
    return required.issubset(set(header))


def _add_model_suggestions(
    db: Any, rows: list[dict[str, Any]], scope: "InferenceScope"
) -> None:
    names = list(dict.fromkeys(
        row["exercise_name"]
        for row in rows
        if row["exercise_id"] is None and row["exercise_name"]
    ))
    if not names:
        return
    search_terms = {
        row["exercise_name"]: row["suggestion_search_terms"]
        for row in rows
        if row["exercise_name"] in names and row["suggestion_search_terms"]
    }
    try:
        suggested = program_import_ai.suggest_exercises(db, names, scope, search_terms)
    except (program_import_ai.ProgramImportAIError, TimeoutError):
        for row in rows:
            if row["exercise_id"] is None:
                row["warnings"].append(_row_warning(
                    "program_import.suggestions_unavailable.v1",
                    row["source_row"],
                    "exercise",
                    "Automated suggestions are unavailable; search the library or create a Coach exercise.",
                ))
        return
    for row in rows:
        model_matches = suggested.get(row["exercise_name"], [])
        row["suggestions"] = _merge_suggestions(row["suggestions"], model_matches)


def _merge_suggestions(
    deterministic: list[dict[str, str]], model_suggestions: list[dict[str, str]]
) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for candidate in (*deterministic, *model_suggestions):
        merged.setdefault(candidate["exercise_id"], candidate)
    return list(merged.values())[:3]


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
    public_rows = [
        {key: value for key, value in row.items() if key != "suggestion_search_terms"}
        for row in rows
    ]
    rows_by_week = {
        week: [row for row in public_rows if row["week"] == week]
        for week in source.detected_weeks
    }
    return {
        "detected_tabs": source.detected_tabs,
        "selected_tab": source.selected_tab,
        "requires_tab_choice": source.requires_tab_choice,
        "detected_weeks": source.detected_weeks,
        "selected_week": source.selected_week,
        "weeks_not_imported": source.weeks_not_imported,
        "confirm_layout": source.confirm_layout,
        "import_mode": source.import_mode,
        "layout_days": source.layout_days,
        "layout_confidence": source.layout_confidence,
        "draft_exists": draft_exists,
        "freeform_available": program_import_ai.resolve_enable_gate().enabled,
        "rows": public_rows,
        "rows_by_week": rows_by_week,
        "errors": [error for row in rows for error in row["errors"]],
        "unresolved_names": _unresolved_names(rows),
    }


def _freeform_grid_context(
    grid: dict[str, Any], layout_days: list[Any]
) -> FreeFormGridContext:
    cells_by_row = _grid_cells_by_row(grid)
    header_row, columns = _source_columns(cells_by_row)
    day_names, day_numbers = _source_day_labels(cells_by_row, header_row, columns)
    _add_layout_day_labels(layout_days, day_names, day_numbers)
    weeks = _source_week_labels(cells_by_row, header_row, columns)
    return FreeFormGridContext(cells_by_row, columns, header_row, weeks, day_names, day_numbers)


def _grid_cells_by_row(grid: dict[str, Any]) -> dict[int, dict[int, str]]:
    rows: dict[int, dict[int, str]] = {}
    for cell in grid.get("cells", []):
        match = re.fullmatch(r"([A-Z]+)(\d+)", cell["address"])
        if match:
            row_number = int(match.group(2))
            column_number = _column_number(match.group(1))
            rows.setdefault(row_number, {})[column_number] = cell["value"]
    return rows


def _source_columns(
    cells_by_row: dict[int, dict[int, str]],
) -> tuple[int | None, dict[int, tuple[str, int | None]]]:
    best_row = None
    best_columns: dict[int, tuple[str, int | None]] = {}
    for row_number, cells in cells_by_row.items():
        columns = {
            column: field
            for column, cell_value in cells.items()
            if (field := _source_header_field(cell_value)) is not None
        }
        fields = {field_name for field_name, _week in columns.values()}
        if "exercise" in fields and fields & {"day", "day_name"} and len(columns) > len(best_columns):
            best_row, best_columns = row_number, columns
    return best_row, best_columns


def _source_header_field(header_value: str) -> tuple[str, int | None] | None:
    header = " ".join(header_value.casefold().split())
    week_prefix = re.match(r"^(?:week|wk|w)\s*(\d+)\s+(.+)$", header)
    week_number = int(week_prefix.group(1)) if week_prefix else None
    header = week_prefix.group(2) if week_prefix else header
    field_name = _source_field_name(header)
    return (field_name, week_number) if field_name else None


def _source_field_name(header: str) -> str | None:
    if header in _SOURCE_HEADER_FIELDS:
        return _SOURCE_HEADER_FIELDS[header]
    if "progression" in header:
        return "progression"
    if re.search(r"\b(?:load|weight)\b.*\b(?:kg|kilograms?)\b", header):
        return "load_kg"
    if "rep" in header and "rpe" in header:
        return "reps_effort"
    if "effort" in header:
        return "effort"
    return None


def _source_day_labels(
    cells_by_row: dict[int, dict[int, str]],
    header_row: int | None,
    columns: dict[int, tuple[str, int | None]],
) -> tuple[dict[int, str], dict[str, int]]:
    row_labels = _day_labels_from_columns(cells_by_row, header_row, columns)
    title_labels = _day_labels_from_titles(cells_by_row)
    for day_number, day_name in title_labels[0].items():
        row_labels[0].setdefault(day_number, day_name)
    row_labels[1].update({key: number for key, number in title_labels[1].items() if key not in row_labels[1]})
    return row_labels


def _day_labels_from_columns(
    cells_by_row: dict[int, dict[int, str]],
    header_row: int | None,
    columns: dict[int, tuple[str, int | None]],
) -> tuple[dict[int, str], dict[str, int]]:
    day_names: dict[int, str] = {}
    day_numbers: dict[str, int] = {}
    day_column = next((column for column, spec in columns.items() if spec[0] == "day"), None)
    name_column = next((column for column, spec in columns.items() if spec[0] == "day_name"), None)
    for row_number, cells in cells_by_row.items():
        if row_number == header_row:
            continue
        day_number = _parse_integer(cells.get(day_column)) if day_column else None
        if day_number is None or not 1 <= day_number <= MAX_PROGRAM_DAYS:
            continue
        name = _clean_day_name(cells.get(name_column)) if name_column else ""
        if name and not _is_generic_day_name(name):
            _store_day_label(day_number, name, day_names, day_numbers)
    return day_names, day_numbers


def _day_labels_from_titles(
    cells_by_row: dict[int, dict[int, str]],
) -> tuple[dict[int, str], dict[str, int]]:
    day_names: dict[int, str] = {}
    day_numbers: dict[str, int] = {}
    for cells in cells_by_row.values():
        for text in cells.values():
            title = re.match(r"^\s*day\s*(\d+)\s*[-:—–.)]+\s*(.+?)\s*$", text, re.IGNORECASE)
            if title:
                _store_day_label(int(title.group(1)), title.group(2), day_names, day_numbers)
    return day_names, day_numbers


def _add_layout_day_labels(
    layout_days: list[Any], day_names: dict[int, str], day_numbers: dict[str, int]
) -> None:
    for index, layout_day in enumerate(layout_days, start=1):
        day_number = _parse_integer(layout_day.day) or index
        name = _clean_day_name(layout_day.name)
        if 1 <= day_number <= MAX_PROGRAM_DAYS and name and not _is_generic_day_name(name):
            _store_day_label(day_number, name, day_names, day_numbers)
            day_numbers.setdefault(_day_name_key(layout_day.name), day_number)


def _store_day_label(
    day_number: int,
    name: str,
    day_names: dict[int, str],
    day_numbers: dict[str, int],
) -> None:
    clean_name = _clean_day_name(name)
    if not 1 <= day_number <= MAX_PROGRAM_DAYS or not clean_name:
        return
    day_names.setdefault(day_number, clean_name)
    day_numbers.setdefault(_day_name_key(clean_name), day_number)


def _clean_day_name(value: Any) -> str:
    name = _cell_text(value)
    return re.sub(r"^\s*day\s*\d+\s*[-:—–.)]+\s*", "", name, flags=re.IGNORECASE).strip()


def _day_name_key(value: Any) -> str:
    return " ".join(_cell_text(value).split()).casefold()


def _is_generic_day_name(value: Any) -> bool:
    return bool(re.fullmatch(r"(?:training\s+)?day\s*\d+", _cell_text(value), re.IGNORECASE))


def _source_week_labels(
    cells_by_row: dict[int, dict[int, str]],
    header_row: int | None,
    columns: dict[int, tuple[str, int | None]],
) -> list[str]:
    labels: list[str] = []
    for cells in cells_by_row.values():
        for text in cells.values():
            labels.extend(_week_labels_in_cell(text))
    for _field, week_number in columns.values():
        if week_number is not None:
            labels.append(_canonical_week_label(week_number))
    week_columns = [column for column, spec in columns.items() if spec[0] == "week"]
    for row_number, cells in cells_by_row.items():
        if row_number != header_row:
            labels.extend(_canonical_week_label(cells[column]) for column in week_columns if cells.get(column))
    return list(dict.fromkeys(label for label in labels if label))


def _week_labels_in_cell(value: str) -> list[str]:
    header_or_title = re.fullmatch(
        r"(?:week|wk)\s*([0-9]+|[a-z])(?:\s*[-—/:].*)?", value.strip(), re.IGNORECASE
    )
    if header_or_title:
        return [_canonical_week_label(f"Week {header_or_title.group(1)}")]
    column_label = re.search(
        r"\b(?:week|wk|w)\s*(\d+)\s+(?:sets?|reps?|effort|rir|rpe|load)\b",
        value,
        re.IGNORECASE,
    )
    return [_canonical_week_label(column_label.group(1))] if column_label else []


def _freeform_source_row(
    context: FreeFormGridContext, source_row: int, week: str | None
) -> FreeFormSourceRow:
    cells = context.cells_by_row.get(source_row, {})
    fields: dict[str, str] = {}
    week_fields: dict[int, dict[str, str]] = {}
    for column, text in cells.items():
        spec = context.columns.get(column)
        if spec is None:
            continue
        field_name, week_number = spec
        if week_number is None:
            fields[field_name] = text
        else:
            week_fields.setdefault(week_number, {})[field_name] = text
    week_number = _week_number(week)
    if week_number is not None:
        fields.update(week_fields.get(week_number, {}))
    row_text = " | ".join(cells[column] for column in sorted(cells))
    # A title or note above the header can set a rule for the rows below it
    # (e.g. top sets on compound lifts); every row inherits it so an unsupported
    # construct there is flagged for the coach instead of silently dropped.
    preamble = _sheet_preamble_text(context)
    return FreeFormSourceRow(fields, " | ".join(part for part in (row_text, preamble) if part))


def _sheet_preamble_text(context: FreeFormGridContext) -> str:
    if context.header_row is None:
        return ""
    return " | ".join(
        text
        for row_number in sorted(context.cells_by_row)
        if row_number < context.header_row
        for text in context.cells_by_row[row_number].values()
        if text
    )


def _freeform_reader_output(
    reply: program_import_ai.ProgramImportReply,
    tabs: list[str],
    selected_tab: str | None,
    grid: dict[str, Any],
) -> ReaderOutput:
    context = _freeform_grid_context(grid, reply.layout.days)
    weeks = _resolved_week_labels(reply.layout.weeks, context)
    selected_week = _default_import_week(weeks)
    week_lookup = {_week_identity(week): week for week in weeks}
    return ReaderOutput(
        tabs,
        selected_tab,
        False,
        _freeform_program_rows(reply.rows, week_lookup, selected_week, context),
        detected_weeks=weeks,
        selected_week=selected_week,
        weeks_not_imported=[week for week in weeks if week != selected_week],
        confirm_layout=_needs_layout_confirmation(reply.layout),
        layout_days=[day.model_dump() for day in reply.layout.days],
        layout_confidence=reply.layout.confidence,
        import_mode="freeform",
    )


def _needs_layout_confirmation(layout: Any) -> bool:
    return (
        layout.confirm_layout
        or layout.confidence < MIN_PROGRAM_IMPORT_LAYOUT_CONFIDENCE
    )


def _freeform_program_rows(
    model_rows: list[Any],
    week_lookup: dict[str, str],
    selected_week: str | None,
    context: FreeFormGridContext,
) -> list[ProgramImportRow]:
    return [
        _program_import_row(
            model_row,
            _matched_row_week(model_row.week, week_lookup, selected_week),
            _freeform_source_row(context, model_row.source_row, model_row.week),
            context,
        )
        for model_row in model_rows
    ]


def _resolved_week_labels(
    model_weeks: list[str], context: FreeFormGridContext
) -> list[str]:
    if len(context.week_labels) > 1:
        return context.week_labels
    normalized = list(dict.fromkeys(
        label for week in model_weeks if (label := _canonical_week_label(week))
    ))
    if len(normalized) < 2 or _weeks_mirror_day_numbers(normalized, context):
        return []
    return normalized


def _weeks_mirror_day_numbers(weeks: list[str], context: FreeFormGridContext) -> bool:
    week_numbers = {_week_number(week) for week in weeks}
    week_numbers.discard(None)
    return bool(context.day_names) and week_numbers == set(context.day_names)


def _canonical_week_label(value: Any) -> str:
    label = _cell_text(value)
    match = re.fullmatch(r"(?:week|wk|w)?\s*(\d+)", label, re.IGNORECASE)
    if match:
        return f"Week {int(match.group(1))}"
    word_week = re.fullmatch(r"(?:week|wk)\s*([a-z])", label, re.IGNORECASE)
    return f"Week {word_week.group(1).upper()}" if word_week else label


def _week_identity(value: Any) -> str:
    label = _canonical_week_label(value)
    number = _week_number(label)
    if number is not None:
        return f"number:{number}"
    word_week = re.fullmatch(r"(?:week|wk)\s*([a-z])|([a-z])", label, re.IGNORECASE)
    return f"word:{(word_week.group(1) or word_week.group(2)).casefold()}" if word_week else label.casefold()


def _week_number(value: Any) -> int | None:
    match = re.fullmatch(r"(?:week|wk|w)?\s*(\d+)", _cell_text(value), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _matched_row_week(
    row_week: str | None, week_lookup: dict[str, str], selected_week: str | None
) -> str | None:
    if not week_lookup:
        return None
    return week_lookup.get(_week_identity(row_week)) if row_week else selected_week


def _default_import_week(weeks: list[str]) -> str | None:
    if not weeks:
        return None
    return next(
        (week for week in weeks if re.search(r"\b(?:week|wk)\s*1\b|^1$", week, re.IGNORECASE)),
        weeks[0],
    )


def _program_import_row(
    row: Any,
    week: str | None,
    source: FreeFormSourceRow,
    context: FreeFormGridContext,
) -> ProgramImportRow:
    values = _freeform_row_values(row, source, context)
    return ProgramImportRow(
        source_row=row.source_row,
        day=values.day,
        day_name=values.day_name,
        order=row.order,
        exercise=row.exercise,
        sets=row.sets,
        reps_min=row.reps_min,
        reps_max=row.reps_max,
        reps_original=values.reps_original,
        rir=values.rir,
        rpe=_freeform_rpe_value(values.rpe),
        rest_seconds=row.rest_seconds,
        tempo=row.tempo,
        notes=row.notes,
        original_text=row.original_text,
        approximation_markers=values.approximation_markers,
        week=week,
        suggestion_terms=tuple(row.exercise_search_terms),
    )


def _freeform_row_values(
    row: Any, source: FreeFormSourceRow, context: FreeFormGridContext
) -> FreeFormRowValues:
    day, day_name = _freeform_day_values(row, source, context)
    rir, rpe = _freeform_effort_values(row, source)
    return FreeFormRowValues(
        day,
        day_name,
        rir,
        rpe,
        _freeform_reps_original(row, source),
        tuple(_freeform_approximation_markers(row, source)),
    )


def _freeform_day_values(
    row: Any, source: FreeFormSourceRow, context: FreeFormGridContext
) -> tuple[Any, str | None]:
    source_day = _parse_integer(source.fields.get("day"))
    day = source_day if source_day is not None else row.day
    source_name = source.fields.get("day_name")
    candidate_name = source_name or row.day_name
    clean_name = _clean_day_name(candidate_name)
    mapped_day = context.day_numbers.get(_day_name_key(clean_name)) if clean_name else None
    if mapped_day is not None and (source_day is None or _is_generic_day_name(source_name)):
        day = mapped_day
    day_number = _parse_integer(day)
    if _is_generic_day_name(clean_name) or not clean_name:
        clean_name = context.day_names.get(day_number) if day_number is not None else None
    return day, clean_name


def _freeform_effort_values(
    row: Any, source: FreeFormSourceRow
) -> tuple[Any, Any]:
    source_rpe = _source_rpe_value(source.fields)
    if source_rpe is not None:
        return None, source_rpe
    return row.rir, row.rpe


def _source_rpe_value(fields: dict[str, str]) -> str | None:
    column_value = fields.get("rpe")
    if column_value:
        if re.fullmatch(r"\d+(?:\.\d+)?", column_value.strip()):
            return f"RPE {column_value}"
        match = re.search(r"(?:RPE\s*|@\s*)(\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?)", column_value, re.IGNORECASE)
        if match:
            return f"RPE {match.group(1)}"
    for key in ("effort", "reps_effort"):
        raw = fields.get(key, "")
        match = re.search(r"(?:RPE\s*|@\s*)(\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?)", raw, re.IGNORECASE)
        if match:
            return f"RPE {match.group(1)}"
    return None


def _freeform_reps_original(row: Any, source: FreeFormSourceRow) -> Any:
    raw = (
        source.fields.get("reps_by_set")
        or source.fields.get("reps")
        or source.fields.get("prescription")
    )
    if raw and ("/" in raw or "," in raw) and re.search(r"\d+\s*[,/]\s*\d+", raw):
        return raw
    return row.reps_original


def _freeform_approximation_markers(
    row: Any, source: FreeFormSourceRow
) -> list[Approximation]:
    markers = [
        Approximation(_allowed_approximation_code(marker.code), marker.column, marker.original)
        for marker in row.approximation_markers
    ]
    markers.extend(_detect_unsupported_prescriptions(row, markers, source.text))
    markers.extend(_source_approximation_markers(source))
    if row.load_kg not in (None, "") and not source.fields.get("load_kg"):
        markers.append(_load_approximation(row.load_kg))
    return _dedupe_approximation_markers(markers)


def _source_approximation_markers(source: FreeFormSourceRow) -> list[Approximation]:
    markers = []
    load = source.fields.get("load_kg")
    if load and load.strip().casefold() not in {"—", "-", "n/a", "none"}:
        markers.append(_load_approximation(load))
    slot = source.fields.get("slot", "")
    if re.fullmatch(r"[A-Z]\d{1,2}", slot.strip(), re.IGNORECASE):
        markers.append(Approximation(
            "program_import.unsupported_preserved_as_note.v1", "prescription", f"superset {slot}"
        ))
    reps_by_set = source.fields.get("reps_by_set", "")
    reps = source.fields.get("reps") or source.fields.get("prescription", "")
    if reps_by_set:
        markers.append(Approximation("program_import.reps_approximated.v1", "reps", reps_by_set))
    elif re.search(r"\b(?:per|by)\s+set\b", reps, re.IGNORECASE):
        markers.append(Approximation("program_import.reps_approximated.v1", "reps", reps))
    elif re.search(r"\d+\s*[,/]\s*\d+.*\b(?:reps?|sets?)\b", reps, re.IGNORECASE):
        markers.append(Approximation("program_import.reps_approximated.v1", "reps", reps))
    return markers


def _load_approximation(value: Any) -> Approximation:
    original = _cell_text(value)
    if original and not re.search(r"\bkg\b", original, re.IGNORECASE):
        original = f"{original} kg"
    return Approximation("program_import.load_preserved_as_note.v1", "load_kg", original)


def _dedupe_approximation_markers(markers: list[Approximation]) -> list[Approximation]:
    unique: dict[tuple[str, str, str], Approximation] = {}
    for marker in markers:
        unique.setdefault((marker.code, marker.column, marker.original.casefold()), marker)
    return list(unique.values())


def _freeform_rpe_value(value: Any) -> Any:
    text = _cell_text(value)
    if text and re.fullmatch(r"\d+(?:\.\d+)?", text):
        return f"RPE {text}"
    return value


def _detect_unsupported_prescriptions(
    row: Any, existing: list[Approximation], source_text: str = ""
) -> list[Approximation]:
    source = " ".join(
        part for part in (row.original_text, _cell_text(row.notes), source_text) if part
    )
    found = []
    # Dedupe on (code, text): a weekly load progression the model already
    # preserved as a load note is still an unsupported construct to flag.
    existing_unsupported = {
        marker.original.casefold()
        for marker in existing
        if marker.original and marker.code == "program_import.unsupported_preserved_as_note.v1"
    }
    for pattern, column in _UNSUPPORTED_PRESCRIPTION_PATTERNS:
        match = re.search(pattern, source, re.IGNORECASE)
        if match and match.group(0).casefold() not in existing_unsupported:
            found.append(
                Approximation(
                    "program_import.unsupported_preserved_as_note.v1",
                    column,
                    match.group(0),
                )
            )
    return found


def _allowed_approximation_code(code: str) -> str:
    allowed = {
        "program_import.reps_approximated.v1",
        "program_import.effort_approximated.v1",
        "program_import.load_preserved_as_note.v1",
        "program_import.rpe_converted.v1",
        "program_import.unsupported_preserved_as_note.v1",
    }
    return code if code in allowed else "program_import.unsupported_preserved_as_note.v1"


def _read_csv(payload: bytes) -> ReaderOutput:
    try:
        text = payload.decode("utf-8-sig")
        return _rows_from_table(csv.reader(io.StringIO(text)), ["CSV"], "CSV")
    except ProgramImportError:
        raise
    except Exception as error:
        raise ProgramImportError("program_import.file_invalid.v1", "The CSV file could not be read.") from error


def _freeform_cell_grid(
    payload: bytes, filename: str, selected_tab: str | None
) -> FreeFormCellGrid:
    extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if extension == "csv":
        if selected_tab:
            raise ProgramImportError("program_import.tab_invalid.v1", "CSV files have one sheet.")
        try:
            table = csv.reader(io.StringIO(payload.decode("utf-8-sig")))
            cells = _compact_cell_grid(table)
        except ProgramImportError:
            raise
        except (UnicodeDecodeError, csv.Error) as error:
            raise ProgramImportError("program_import.file_invalid.v1", "The CSV file could not be read.") from error
        if not cells:
            raise ProgramImportError("program_import.sheet_empty.v1", "The CSV sheet is empty.")
        return FreeFormCellGrid({"sheet": "CSV", "cells": cells}, ["CSV"], "CSV")
    if extension != "xlsx":
        raise ProgramImportError("program_import.file_type.v1", "Upload an XLSX or CSV file.")
    workbook = None
    try:
        workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
        return _xlsx_cell_grid(workbook, selected_tab)
    except ProgramImportError:
        raise
    except Exception as error:
        raise ProgramImportError("program_import.file_invalid.v1", "The XLSX file could not be read.") from error
    finally:
        if workbook is not None:
            workbook.close()


def _xlsx_cell_grid(
    workbook: Any, selected_tab: str | None
) -> FreeFormCellGrid:
    if len(workbook.worksheets) > MAX_PROGRAM_IMPORT_TABS:
        raise ProgramImportError("program_import.too_many_tabs.v1", "Trim the workbook to 20 sheets or fewer.", 413)
    tabs = [sheet.title for sheet in workbook.worksheets if _sheet_has_values(sheet)]
    if not tabs:
        raise ProgramImportError("program_import.sheet_empty.v1", "The workbook has no non-empty sheets.")
    if len(tabs) > 1 and selected_tab is None:
        return FreeFormCellGrid(None, tabs, None)
    selected = selected_tab or tabs[0]
    if selected not in tabs:
        raise ProgramImportError("program_import.tab_invalid.v1", "Choose a non-empty sheet from this workbook.")
    sheet = workbook[selected]
    rows, columns = sheet.max_row or 0, sheet.max_column or 0
    if (
        rows * columns > MAX_PROGRAM_IMPORT_GRID_RECTANGLE
        or rows > MAX_PROGRAM_IMPORT_GRID_ROWS
        or columns > MAX_PROGRAM_IMPORT_GRID_COLUMNS
    ):
        raise _cell_limit_error()
    cells = _compact_cell_grid(
        sheet.iter_rows(max_row=rows, max_col=columns, values_only=True)
    )
    if not cells:
        raise ProgramImportError("program_import.sheet_empty.v1", "The selected sheet is empty.")
    return FreeFormCellGrid({"sheet": selected, "cells": cells}, tabs, selected)


def _compact_cell_grid(table: Iterable[Iterable[Any]]) -> list[dict[str, str]]:
    cells: list[dict[str, str]] = []
    non_empty = 0
    for row_number, raw_row in enumerate(table, start=1):
        if row_number > MAX_PROGRAM_IMPORT_GRID_ROWS:
            raise _cell_limit_error()
        for column_number, raw_value in enumerate(raw_row, start=1):
            if column_number > MAX_PROGRAM_IMPORT_GRID_COLUMNS:
                raise _cell_limit_error()
            text = _cell_text(raw_value)
            if not text:
                continue
            non_empty += 1
            if non_empty > MAX_PROGRAM_IMPORT_CELLS:
                raise _cell_limit_error()
            cells.append({"address": f"{_column_label(column_number)}{row_number}", "value": text})
    return cells


def _column_label(column_number: int) -> str:
    letters = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _column_number(label: str) -> int:
    number = 0
    for letter in label:
        number = number * 26 + ord(letter) - ord("A") + 1
    return number


def _cell_limit_error() -> ProgramImportError:
    return ProgramImportError(
        "program_import.too_many_cells.v1",
        f"Trim the selected sheet to {MAX_PROGRAM_IMPORT_CELLS} non-empty cells or fewer, then upload it again.",
        413,
        {"max_cells": MAX_PROGRAM_IMPORT_CELLS},
    )


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

    preserved_notes = [
        f"{item.column}: {item.original}"
        for item in source.approximation_markers
        if item.original and item.column not in {"reps", "rir", "rpe"}
    ]
    notes = _join_notes(source.notes, reps_note, effort_notes, *preserved_notes)
    if len(notes) > MAX_PROGRAM_NOTES_LENGTH:
        errors.append(_row_error("program_import.notes_too_long.v1", source.source_row, "notes", "Notes are too long."))

    return {
        "source_row": source.source_row,
        "week": source.week,
        "original_text": source.original_text,
        "approximation_markers": [item.code for item in source.approximation_markers],
        "suggestion_search_terms": list(source.suggestion_terms),
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
