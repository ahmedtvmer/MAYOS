"""Evaluate free-form Program import on synthetic coach spreadsheets (#350).

Live runs use the upload HTTP route and the configured hosted Coach model. The
temporary account and Assignment contain no copied Training ledger; each model
payload is made by the production import path from the selected fixture sheet.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from service import program_import_ai  # noqa: E402
from service.evaluation_report_gate import GateStatus  # noqa: E402
from service.program_import_evaluation import (  # noqa: E402
    PENDING_REVIEW_RECORD,
    dataset_hash_for_directory,
    fixture_entries_hash,
    load_fixture_entries,
    review_matches_dataset,
)
from tests.eval import evaluation_runner  # noqa: E402
from tests.eval.program_import_evaluation_session import ProgramImportEvaluationSession  # noqa: E402

DEFAULT_DATASET = Path(__file__).resolve().parent / "datasets" / "program_import"
REVIEW_FILENAME = "REVIEW.json"
PRIVACY_SUITE = "tests/test_program_import.py"


def load_dataset(dataset_path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    dataset_directory = Path(dataset_path)
    if not dataset_directory.is_dir():
        raise ValueError(f"Program import eval dataset must be a directory: {dataset_path}")
    fixture_entries = load_fixture_entries(dataset_directory)
    cases = [entry["fixture"] for entry in fixture_entries]
    if not cases:
        raise ValueError(f"Program import eval dataset must contain cases: {dataset_path}")
    if not 15 <= len(cases) <= 20:
        raise ValueError(f"Program import eval dataset must contain 15 to 20 cases: {dataset_path}")
    ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if len(ids) != len(cases) or any(not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("Program import eval case ids must be present and unique")
    review_path = dataset_directory / REVIEW_FILENAME
    if review_path.is_file():
        owner_review = json.loads(review_path.read_text(encoding="utf-8"))
    else:
        owner_review = dict(PENDING_REVIEW_RECORD)
    return {"owner_review": owner_review, "fixture_entries": fixture_entries, "cases": cases}


def load_cases(dataset_path: Path = DEFAULT_DATASET) -> list[dict[str, Any]]:
    return load_dataset(dataset_path)["cases"]


def compute_dataset_hash(dataset_path: Path = DEFAULT_DATASET) -> str:
    return dataset_hash_for_directory(dataset_path)


def record_owner_review(dataset_path: Path, reviewer: str) -> dict[str, Any]:
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("reviewer name must not be blank")
    load_dataset(dataset_path)
    review = {
        "reviewed": True,
        "reviewed_by": reviewer,
        "reviewed_on": datetime.now(timezone.utc).date().isoformat(),
        "reviewed_dataset_hash": compute_dataset_hash(dataset_path),
    }
    (Path(dataset_path) / REVIEW_FILENAME).write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return review


def spreadsheet_bytes(case: dict[str, Any]) -> bytes:
    """Builds the committed human-readable grid fixture as a CSV or XLSX upload."""
    if case["format"] == "csv":
        output = io.StringIO(newline="")
        csv.writer(output).writerows(case["grid"])
        return output.getvalue().encode("utf-8-sig")
    if case["format"] != "xlsx":
        raise ValueError(f"unsupported fixture format: {case['format']!r}")

    from openpyxl import Workbook

    workbook = Workbook()
    sheets = case["sheets"]
    first_name = next(iter(sheets))
    workbook.active.title = first_name
    for index, (name, rows) in enumerate(sheets.items()):
        worksheet = workbook.active if index == 0 else workbook.create_sheet(name)
        if index == 0:
            worksheet.title = name
        for row in rows:
            worksheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def expected_translation_reply(case: dict[str, Any]) -> dict[str, Any]:
    """Creates a clearly synthetic happy-path reply for plumbing tests only."""
    rows = []
    for index, expected in enumerate(case["expected_rows"], start=1):
        markers = [
            {
                "code": code,
                "column": _approximation_column(code),
                "original": expected.get("original_text", ""),
            }
            for code in expected["approximation_codes"]
            if code != "program_import.rpe_converted.v1"
        ]
        rows.append(
            {
                "source_row": expected["source_row"],
                "week": expected["week"],
                "exercise_search_terms": expected.get("suggestion_search_terms", []),
                "day": expected["day"],
                "day_name": expected["day_name"],
                "order": index,
                "exercise": expected.get("input_exercise_name", expected["exercise_name"]),
                "sets": expected["sets"],
                "reps_min": expected["reps_min"],
                "reps_max": expected["reps_max"],
                "reps_original": None,
                "rir": expected.get("rir"),
                "rpe": expected.get("rpe"),
                "rest_seconds": expected.get("rest_seconds"),
                "tempo": expected.get("tempo"),
                "notes": expected.get("notes"),
                "original_text": expected.get("original_text", expected["exercise_name"]),
                "approximation_markers": markers,
            }
        )
    days_by_number: dict[str, str] = {}
    for row in case["expected_rows"]:
        days_by_number.setdefault(str(row["day"]), row["day_name"])
    return {
        "rows": rows,
        "layout": {
            "days": [{"day": day, "name": name} for day, name in days_by_number.items()],
            "weeks": list(case["expected_weeks"]),
            "confidence": 0.99,
            "confirm_layout": bool(case.get("expected_confirm_layout", False)),
        },
    }


class PlumbingModel:
    """Keeps translation replies aligned when a sheet also needs suggestions."""

    def __init__(self):
        from tests.fakes.chat_model import ScriptedChatModel

        self.scripted_model = ScriptedChatModel(default_turn={"suggestions": []})

    def prepare_case(self, case: dict[str, Any], db: Any) -> None:
        turns = [expected_translation_reply(case)]
        suggestions = []
        for expected in case["expected_rows"]:
            if expected["expected_resolution"] != "unresolved":
                continue
            name = expected.get("input_exercise_name", expected["exercise_name"])
            terms = [name, *expected.get("suggestion_search_terms", [])]
            found = {}
            for term in terms:
                for entry in db.find_exercises_by_name(term, limit=3):
                    found.setdefault(str(entry["id"]), str(entry["name"]))
                if len(found) >= 3:
                    break
            if found:
                suggestions.append({"exercise_name": name, "exercise_ids": list(found)[:3]})
        if suggestions:
            turns.append({"suggestions": suggestions})
        self.scripted_model.reset(turns, default_turn={"suggestions": []})


def build_mock_model() -> PlumbingModel:
    """Returns the scripted fake used for plumbing runs; never a quality run."""
    return PlumbingModel()


def _run_cases(
    cases: list[dict[str, Any]],
    session: ProgramImportEvaluationSession,
    model: Any | None,
) -> list[dict[str, Any]]:
    scored = []
    for case in cases:
        if callable(getattr(model, "prepare_case", None)):
            model.prepare_case(case, session.db)
        scored.append(_run_case(session, case))
    return scored


def _model_instance_used(model: Any | None) -> Any | None:
    """Returns the concrete chat model instance installed for inference."""
    return model.scripted_model if isinstance(model, PlumbingModel) else model


@contextlib.contextmanager
def _evaluation_path(model: Any | None) -> Iterator[None]:
    from utils import model_downloader

    previous_model = model_downloader._coach_llm_instance
    previous_gate = program_import_ai.resolve_enable_gate
    if model is not None:
        model_downloader._coach_llm_instance = _model_instance_used(model)
    program_import_ai.resolve_enable_gate = lambda: GateStatus(requested=True, enabled=True, reason="evaluation runner")
    try:
        yield
    finally:
        model_downloader._coach_llm_instance = previous_model
        program_import_ai.resolve_enable_gate = previous_gate


def run_suite(
    cases: list[dict[str, Any]] | None = None,
    *,
    model: Any | None = None,
    dataset_path: Path = DEFAULT_DATASET,
    session: ProgramImportEvaluationSession | None = None,
) -> list[dict[str, Any]]:
    """Uploads each synthetic sheet through the same HTTP route used by Coaches."""
    cases = load_cases(dataset_path) if cases is None else cases
    if session is None:
        with ProgramImportEvaluationSession() as owned_session:
            return run_suite(
                cases,
                model=model,
                dataset_path=dataset_path,
                session=owned_session,
            )
    with _evaluation_path(model):
        return _run_cases(cases, session, model)


def _run_case(session: ProgramImportEvaluationSession, case: dict[str, Any]) -> dict[str, Any]:
    preflight_response = session.import_case(case)
    preflight: dict[str, Any] = {}
    final_response = preflight_response
    if preflight_response.status_code == 200:
        preflight = preflight_response.json()
        if preflight.get("requires_tab_choice"):
            final_response = session.import_case(case, case["expected_selected_tab"])
    if final_response.status_code != 200:
        return score_import_result(
            case,
            None,
            http_status=final_response.status_code,
            http_error=_response_error(final_response),
            preflight=preflight,
        )
    try:
        result = final_response.json()
    except ValueError:
        return score_import_result(
            case,
            None,
            http_status=final_response.status_code,
            http_error="response was not valid JSON",
            preflight=preflight,
        )
    return score_import_result(
        case,
        result,
        http_status=final_response.status_code,
        preflight=preflight or result,
    )


def _response_error(response: Any) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:1000]
    return str(body.get("detail") or body.get("message") or body)[:1000]


def score_import_result(
    case: dict[str, Any],
    result: dict[str, Any] | None,
    *,
    http_status: int,
    http_error: str | None = None,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Scores expected rows against the public import result, keeping row evidence."""
    # Normalise once at the API boundary; all scoring below works with this shape.
    result = result if isinstance(result, dict) else {}
    preflight = preflight or {}
    actual_rows = result.get("rows", [])
    actual_rows = actual_rows if isinstance(actual_rows, list) else []
    errors = result.get("errors", [])
    errors = errors if isinstance(errors, list) else []
    used: set[int] = set()
    row_results = []
    for expected in case["expected_rows"]:
        actual_index = _match_expected_row(expected, actual_rows, used)
        actual = actual_rows[actual_index] if actual_index is not None else None
        if actual_index is not None:
            used.add(actual_index)
        reported_error = any(
            error.get("source_row") == expected["source_row"] and error.get("week") == expected["week"]
            for error in errors
            if isinstance(error, dict)
        )
        whole_sheet_error = not result and bool(http_error) and http_status != 200
        present_or_reported = actual is not None or reported_error or whole_sheet_error
        failures = []
        day_sets_reps_correct = actual is not None and _day_sets_reps_match(expected, actual)
        if not day_sets_reps_correct:
            failures.append("day, sets, or reps did not match")
        if not present_or_reported:
            failures.append("expected row was neither returned nor reported as an error")
        if whole_sheet_error:
            failures.append(f"sheet import failed: {http_error}")
        warning_codes = set()
        if actual is not None:
            warning_codes.update(
                warning.get("code") for warning in actual.get("warnings", []) if isinstance(warning, dict)
            )
        expected_codes = expected["approximation_codes"]
        flagged_codes = [code for code in expected_codes if code in warning_codes]
        approximations_flagged = len(flagged_codes) == len(expected_codes)
        if not approximations_flagged:
            missing = sorted(set(expected_codes) - warning_codes)
            failures.append("approximation warning missing: " + ", ".join(missing))

        unresolved_only_suggested = True
        if expected["expected_resolution"] == "unresolved":
            unresolved_auto_applied = any(
                candidate.get("source_row") == expected["source_row"]
                and candidate.get("week") == expected["week"]
                and candidate.get("exercise_id") is not None
                for candidate in actual_rows
                if isinstance(candidate, dict)
            )
            unresolved_only_suggested = not unresolved_auto_applied
            if not unresolved_only_suggested:
                failures.append("unresolved exercise was applied instead of left for Coach review")
        row_results.append(
            {
                "source_row": expected["source_row"],
                "expected_input_exercise_name": expected.get("input_exercise_name", expected["exercise_name"]),
                "expected_exercise_id": expected.get("expected_exercise_id"),
                "exercise_name": expected["exercise_name"],
                "week": expected["week"],
                "expected_day": expected["day"],
                "expected_day_name": expected["day_name"],
                "expected_sets": expected["sets"],
                "expected_reps_min": expected["reps_min"],
                "expected_reps_max": expected["reps_max"],
                "expected_unresolved": expected["expected_resolution"] == "unresolved",
                "unresolved_auto_applied": (
                    expected["expected_resolution"] == "unresolved" and unresolved_auto_applied
                ),
                "expected_approximation_codes": expected_codes,
                "reported_errors": [
                    error
                    for error in errors
                    if isinstance(error, dict)
                    and error.get("source_row") == expected["source_row"]
                    and error.get("week") == expected["week"]
                ],
                "observed": actual,
                "checks": {
                    "present_or_reported": present_or_reported,
                    "day_sets_reps_correct": bool(day_sets_reps_correct),
                    "approximations_flagged": approximations_flagged,
                    "unresolved_only_suggested": unresolved_only_suggested,
                },
                "failures": failures,
            }
        )

    expected_tabs = case["expected_tabs"]
    detected_tabs = result.get("detected_tabs", [])
    tabs_match = detected_tabs == expected_tabs
    requires_tab_match = bool(preflight.get("requires_tab_choice")) == bool(case["expected_requires_tab_choice"])
    selected_tab_match = result.get("selected_tab") == case["expected_selected_tab"]
    tab_choice_correct = tabs_match and requires_tab_match and selected_tab_match

    expected_weeks = case["expected_weeks"]
    detected_weeks = result.get("detected_weeks", [])
    selected_week = result.get("selected_week")
    expected_not_imported = [week for week in expected_weeks if week != case["expected_chosen_week"]]
    weeks_not_imported = result.get("weeks_not_imported", [])
    weeks_correct = (
        detected_weeks == expected_weeks
        and selected_week == case["expected_chosen_week"]
        and weeks_not_imported == expected_not_imported
    )
    if "expected_confirm_layout" in case:
        weeks_correct = weeks_correct and result.get("confirm_layout") == case["expected_confirm_layout"]

    layout_failures = []
    if not tab_choice_correct:
        layout_failures.append(
            f"expected tabs/choice/selection {expected_tabs!r}/{case['expected_requires_tab_choice']!r}/{case['expected_selected_tab']!r}; "
            f"got {detected_tabs!r}/{preflight.get('requires_tab_choice')!r}/{result.get('selected_tab')!r}"
        )
    if not weeks_correct:
        layout_failures.append(
            f"expected weeks/selection/omitted {expected_weeks!r}/{case['expected_chosen_week']!r}/{expected_not_imported!r}; "
            f"got {detected_weeks!r}/{selected_week!r}/{weeks_not_imported!r}"
        )

    extra_rows = len(actual_rows) - len(used)
    return {
        "case_id": case["id"],
        "tags": case["tags"],
        "expected_rows": len(case["expected_rows"]),
        "http_status": http_status,
        "http_error": http_error,
        "import_mode": result.get("import_mode", "freeform"),
        "produced_rows": actual_rows,
        "errors": errors,
        "extra_rows": extra_rows,
        "preflight": {
            "detected_tabs": preflight.get("detected_tabs", []),
            "requires_tab_choice": bool(preflight.get("requires_tab_choice")),
        },
        "layout": {
            "detected_tabs": result.get("detected_tabs", []),
            "selected_tab": result.get("selected_tab"),
            "detected_weeks": detected_weeks,
            "selected_week": selected_week,
            "weeks_not_imported": weeks_not_imported,
            "confirm_layout": result.get("confirm_layout"),
        },
        "tab_choice_correct": tab_choice_correct,
        "week_layout_correct": weeks_correct,
        "row_results": row_results,
        "layout_failures": layout_failures,
        "passed": all(not row.get("failures") for row in row_results) and not layout_failures,
        "result": result if result else None,
    }


def _match_expected_row(expected: dict[str, Any], actual_rows: list[dict[str, Any]], used: set[int]) -> int | None:
    expected_name = _normalised_name(expected.get("input_exercise_name", expected.get("exercise_name")))
    expected_week = expected.get("week")
    for index, row in enumerate(actual_rows):
        if index in used or not isinstance(row, dict):
            continue
        if row.get("source_row") != expected.get("source_row") or row.get("week") != expected_week:
            continue
        same_written_name = _normalised_name(row.get("exercise_name")) == expected_name
        same_resolved_id = expected.get("expected_exercise_id") is not None and str(row.get("exercise_id")) == str(
            expected["expected_exercise_id"]
        )
        if same_written_name or same_resolved_id:
            return index
    return None


def _normalised_name(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _day_sets_reps_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    return (
        _number(actual.get("day")) == _number(expected["day"])
        and _normalised_name(actual.get("day_name")) == _normalised_name(expected["day_name"])
        and _number(actual.get("sets")) == _number(expected["sets"])
        and _number(actual.get("reps_min")) == _number(expected["reps_min"])
        and _number(actual.get("reps_max")) == _number(expected["reps_max"])
    )


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, int]:
    row_results = [(case, row) for case in results for row in case["row_results"] if row.get("source_row") is not None]
    expected_approximations = sum(len(row.get("expected_approximation_codes", [])) for _, row in row_results)
    flagged_approximations = sum(
        sum(
            code
            in {
                warning.get("code")
                for warning in ((row.get("observed") or {}).get("warnings", []))
                if isinstance(warning, dict)
            }
            for code in row.get("expected_approximation_codes", [])
        )
        for _, row in row_results
    )
    unresolved_expected = sum(row.get("expected_unresolved", False) for _, row in row_results)
    unresolved_auto_applied = sum(row.get("unresolved_auto_applied", False) for _, row in row_results)
    return {
        "expected_rows": len(row_results),
        "correct_rows": sum(row["checks"].get("day_sets_reps_correct") is True for _, row in row_results),
        "silently_dropped_rows": sum(row["checks"].get("present_or_reported") is False for _, row in row_results),
        "approximations": expected_approximations,
        "approximations_flagged": flagged_approximations,
        "unresolved_names": unresolved_expected,
        "unresolved_auto_applied": unresolved_auto_applied,
        "layout_errors": sum(not case["week_layout_correct"] for case in results),
        "tab_choice_errors": sum(not case["tab_choice_correct"] for case in results),
        "extra_rows": sum(case.get("extra_rows", 0) for case in results),
    }


def _model_run_for_instance(model_instance: Any) -> str:
    from tests.fakes.chat_model import ScriptedChatModel
    from utils.model_downloader import SafeChatOpenAI

    if isinstance(model_instance, ScriptedChatModel):
        return "scripted_fake"
    configured_model_id, configured_backend = program_import_ai.coach_model_identity()
    if (
        isinstance(model_instance, SafeChatOpenAI)
        and model_instance.model_name == configured_model_id
        and configured_backend == "openai"
    ):
        return "hosted_coach"
    return "unverified_model"


def build_report(
    results: list[dict[str, Any]],
    *,
    mode: str,
    privacy_pass: bool,
    dataset_review: dict[str, Any] | None = None,
    dataset_entries: list[dict[str, Any]] | None = None,
    model_instance: Any | None = None,
    dataset_path: Path = DEFAULT_DATASET,
) -> dict[str, Any]:
    metrics = aggregate_metrics(results)
    evaluation_ok, reasons, stats = program_import_ai.evaluate_pass_condition(metrics)
    dataset_review = dict(dataset_review or PENDING_REVIEW_RECORD)
    dataset_entries = dataset_entries or load_fixture_entries(dataset_path)
    dataset_hash = fixture_entries_hash(dataset_entries)
    model_run = _model_run_for_instance(model_instance)
    if model_run == "hosted_coach":
        model_id, backend = program_import_ai.coach_model_identity()
    else:
        model_id = f"{type(model_instance).__module__}.{type(model_instance).__qualname__}"
        backend = "scripted" if model_run == "scripted_fake" else "unverified"
    sheet_results = []
    for result in results:
        row_results = result["row_results"]
        row_checks = {
            "all_rows_reported": all(row["checks"]["present_or_reported"] for row in row_results),
            "all_rows_correct": all(row["checks"]["day_sets_reps_correct"] for row in row_results),
            "all_approximations_flagged": all(row["checks"]["approximations_flagged"] for row in row_results),
            "unresolved_only_suggested": all(row["checks"]["unresolved_only_suggested"] for row in row_results),
            "week_layout_correct": result["week_layout_correct"],
            "tab_choice_correct": result["tab_choice_correct"],
        }
        sheet_results.append(
            {
                "case_id": result["case_id"],
                "expected_rows": result["expected_rows"],
                "row_results": row_results,
                "produced_rows": result["produced_rows"],
                "errors": result["errors"],
                "http_status": result["http_status"],
                "http_error": result["http_error"],
                "extra_rows": result["extra_rows"],
                "preflight": result["preflight"],
                "layout": result["layout"],
                "tab_choice_correct": result["tab_choice_correct"],
                "week_layout_correct": result["week_layout_correct"],
                "checks": {name: {"passed": value} for name, value in row_checks.items()},
                "passed": all(row_checks.values()),
            }
        )
    aggregate_run = {
        "case_id": "program_import_sample_set",
        "passed": evaluation_ok,
        "checks": {name: {"passed": passed} for name, passed in program_import_ai._metric_checks(metrics).items()},
        "metrics": metrics,
        "sheets": sheet_results,
    }
    gate_ok = evaluation_ok
    dataset_fixtures = [{"filename": entry["filename"], "fixture": entry["fixture"]} for entry in dataset_entries]
    report = {
        "report_version": program_import_ai.REPORT_VERSION,
        "suite": "program_import",
        "mode": mode,
        "model_run": model_run,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": Path(dataset_path).name,
        "dataset_hash": dataset_hash,
        "dataset_review": dict(dataset_review),
        "dataset_fixtures": dataset_fixtures,
        "prompt_hash": program_import_ai.prompt_version_hash(),
        "model": model_id,
        "backend": backend,
        "gates": {
            "privacy": {"pass": bool(privacy_pass), "suite": PRIVACY_SUITE},
            "evaluation": {
                "pass": bool(gate_ok),
                "total": 1,
                "passed": int(bool(gate_ok)),
                "threshold": 1,
                "metrics": metrics,
            },
        },
        "run": {**stats, "sheets": len(results), "extra_rows": metrics["extra_rows"]},
        "reasons": reasons,
        "runs": [aggregate_run],
        "pass": bool(
            mode == "live"
            and model_run == "hosted_coach"
            and privacy_pass
            and gate_ok
            and review_matches_dataset(dataset_review, dataset_hash)
        ),
    }
    return report


def write_report(path: Path, report: dict[str, Any]) -> Path:
    return evaluation_runner.write_report(path, report, ensure_ascii=False)


def check_report(report_path: Path) -> tuple[bool, list[str]]:
    return evaluation_runner.check_report(
        report_path,
        program_import_ai.validate_report,
        strict=True,
    )


def run_privacy_suite(base_dir: Path = BASE_DIR) -> bool:
    return evaluation_runner.run_privacy_suite(PRIVACY_SUITE, base_dir)


def _approximation_column(code: str) -> str:
    if code == "program_import.reps_approximated.v1":
        return "reps"
    if code == "program_import.load_preserved_as_note.v1":
        return "load_kg"
    if code == "program_import.effort_approximated.v1":
        return "rir"
    return "prescription"


def _print_results(results: list[dict[str, Any]], metrics: dict[str, int]) -> None:
    for case in results:
        mark = "pass" if case["passed"] else "FAIL"
        print(
            f"  [{mark}] {case['case_id']} ({case['expected_rows']} expected rows; "
            f"HTTP {case['http_status']}; {case.get('extra_rows', 0)} extra rows)"
        )
        for row in case["row_results"]:
            for failure in row.get("failures", []):
                print(f"    x row {row.get('source_row')}: {row['exercise_name']}: {failure}")
        for failure in case.get("layout_failures", []):
            print(f"    x layout: {failure}")
        if case.get("http_error"):
            print(f"    x import error: {case['http_error']}")
    passed, reasons, _stats = program_import_ai.evaluate_pass_condition(metrics)
    accuracy = metrics["correct_rows"] / metrics["expected_rows"] if metrics["expected_rows"] else 0.0
    print(
        "evaluation gate: "
        f"{metrics['correct_rows']}/{metrics['expected_rows']} rows correct ({accuracy:.1%}); "
        f"{metrics['silently_dropped_rows']} silently dropped; {metrics['extra_rows']} extra rows; "
        f"{metrics['approximations_flagged']}/{metrics['approximations']} approximations flagged; "
        f"{metrics['unresolved_auto_applied']} unresolved exercises applied; "
        f"{metrics['layout_errors']} layout errors; {metrics['tab_choice_errors']} tab errors "
        f"({'passed' if passed else 'failed'})"
    )
    for reason in reasons:
        print(f"  x {reason}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate free-form Program import against reviewed synthetic sheets.")
    parser.add_argument(
        "--dataset", type=Path, default=DEFAULT_DATASET, help="Directory of reviewed sample sheet JSON files."
    )
    parser.add_argument("--mock", action="store_true", help="Run plumbing checks against the scripted fake model.")
    parser.add_argument("--write-report", type=Path, default=None, help="Write the enablement report JSON here.")
    parser.add_argument(
        "--no-privacy", action="store_true", help="Skip the privacy suite and record that gate as failed."
    )
    parser.add_argument("--check-report", type=Path, default=None, help="Re-check a report without loading a model.")
    parser.add_argument(
        "--record-review", action="store_true", help="Record that the owner reviewed the current fixture hash."
    )
    parser.add_argument("--reviewer", type=str, default="", help="Owner name used with --record-review.")
    args = parser.parse_args(argv)

    if args.check_report is not None:
        ok, reasons = check_report(args.check_report)
        try:
            checked = json.loads(args.check_report.read_text(encoding="utf-8"))
            current_hash = compute_dataset_hash(args.dataset)
            if checked.get("dataset_hash") != current_hash:
                print("notice: report dataset hash differs from current fixture files; validator verdict is unchanged")
        except (OSError, ValueError, AttributeError):
            pass
        print(f"Program import eval report: {'PASSED' if ok else 'FAILED'}")
        for reason in reasons:
            print(f"  x {reason}", file=sys.stderr)
        return 0 if ok else 1

    try:
        dataset = load_dataset(args.dataset)
    except (OSError, ValueError) as error:
        print(f"could not load Program import dataset: {error}", file=sys.stderr)
        return 2
    if args.record_review:
        try:
            review = record_owner_review(args.dataset, args.reviewer)
        except (OSError, ValueError) as error:
            print(f"could not record Program import dataset review: {error}", file=sys.stderr)
            return 2
        print(
            "Recorded owner review for dataset "
            f"{review['reviewed_dataset_hash']} ({review['reviewed_by']}, {review['reviewed_on']})"
        )
        return 0
    if args.reviewer:
        print("--reviewer requires --record-review", file=sys.stderr)
        return 2
    current_dataset_hash = compute_dataset_hash(args.dataset)
    review = dataset.get("owner_review")
    if not args.mock and not review_matches_dataset(review, current_dataset_hash):
        print(
            "live evaluation refused: the owner review is missing or stale; review the fixtures and run --record-review --reviewer <name>",
            file=sys.stderr,
        )
        return 2

    cases = dataset["cases"]
    mode = "mock" if args.mock else "live"
    expected_row_count = sum(len(case["expected_rows"]) for case in cases)
    print(f"Program import evaluation: {len(cases)} sheets, {expected_row_count} expected rows ({mode} mode)")
    if args.mock:
        print("!!! MOCK MODE: NOT A MODEL EVALUATION. This plumbing report cannot enable import. !!!")
    try:
        if args.mock:
            model = build_mock_model()
        else:
            from utils import model_downloader

            model = model_downloader.get_coach_llm()
        model_instance = _model_instance_used(model)
        results = run_suite(cases, model=model, dataset_path=args.dataset)
    except Exception as error:
        print(f"Program import evaluation could not run: {error}", file=sys.stderr)
        return 2
    metrics = aggregate_metrics(results)
    _print_results(results, metrics)

    if args.write_report is not None:
        privacy_pass = False
        if args.no_privacy:
            print("privacy gate: skipped (recorded as failed)", file=sys.stderr)
        else:
            print(f"running {PRIVACY_SUITE} ...")
            privacy_pass = run_privacy_suite(BASE_DIR)
            print(f"privacy gate: {'passed' if privacy_pass else 'failed'}")
        report = build_report(
            results,
            mode=mode,
            privacy_pass=privacy_pass,
            dataset_review=review,
            dataset_entries=dataset["fixture_entries"],
            model_instance=model_instance,
            dataset_path=args.dataset,
        )
        written_path = write_report(args.write_report, report)
        written_report = json.loads(written_path.read_text(encoding="utf-8"))
        report_ok, report_reasons = program_import_ai.validate_report(written_report)
        print(f"report written: {written_path}")
        print(f"report validator: {'ACCEPTED' if report_ok else 'REFUSED'}")
        for reason in report_reasons:
            print(f"  x {reason}", file=sys.stderr)
        if not args.mock:
            print(f"live evaluation: {'PASSED' if report_ok else 'FAILED'}")
            return 0 if report_ok else 1
        return 0

    if args.mock:
        return 0
    passed, _reasons, _stats = program_import_ai.evaluate_pass_condition(metrics)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
