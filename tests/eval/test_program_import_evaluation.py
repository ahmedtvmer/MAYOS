"""Hermetic evaluation plumbing and report-gate tests for Program import (#350)."""

from __future__ import annotations

import copy
import json
import shutil
from collections import Counter

import pytest

from service import program_import_ai
from service.program_import_evaluation import fixture_entries_hash, list_fixture_files
from tests.eval import run_program_import_evaluation as runner


@pytest.fixture(scope="module")
def cases():
    return runner.load_cases()


@pytest.fixture(scope="module")
def evaluation_session():
    with runner.ProgramImportEvaluationSession() as session:
        yield session


def _review(entries):
    return {
        "reviewed": True,
        "reviewed_by": "MAYOS sample owner",
        "reviewed_on": "2026-10-08",
        "reviewed_dataset_hash": fixture_entries_hash(entries),
    }


def _valid_report(case, evaluation_session):
    results = runner.run_suite([case], model=runner.build_mock_model(), session=evaluation_session)
    entries = [{"filename": f"{case['id']}.json", "fixture": case}]
    report = runner.build_report(
        results,
        mode="live",
        privacy_pass=True,
        dataset_review=_review(entries),
        dataset_entries=entries,
    )
    # This report is fixture evidence for validator tests. Live-run model identity
    # is separately checked on the runner path and against configured identity.
    report["model_run"] = "hosted_coach"
    report["model"], report["backend"] = program_import_ai.coach_model_identity()
    report["pass"] = True
    return report


def test_sample_sheets_are_full_synthetic_programs_and_cover_required_shapes(cases, evaluation_session):
    assert 15 <= len(cases) <= 20
    assert len({case["id"] for case in cases}) == len(cases)
    assert sum(len(case["expected_rows"]) for case in cases) >= 300
    tags = {tag for case in cases for tag in case["tags"]}
    assert {
        "english",
        "arabic",
        "mixed",
        "franco_arabic",
        "multiweek",
        "rpe",
        "amrap",
        "superset",
        "per_set_reps",
        "percent_load",
        "kg_load",
        "top_set",
        "backoff",
        "weekly_progression",
        "unknown_exercises",
        "tab_picker",
    } <= tags

    edge_counts = Counter(edge for case in cases for row in case["expected_rows"] for edge in row["edge_cases"])
    assert edge_counts["amrap"] >= 3
    assert edge_counts["superset"] >= 8
    assert edge_counts["per_set_reps"] >= 8
    assert edge_counts["percent_1rm"] >= 6
    assert edge_counts["kg_load"] >= 8
    assert edge_counts["top_set_backoff"] >= 3
    assert edge_counts["weekly_progression"] >= 6
    unresolved_names = {
        row["input_exercise_name"]
        for case in cases
        for row in case["expected_rows"]
        if row["expected_resolution"] == "unresolved"
    }
    assert len(unresolved_names) >= 6
    assert {"سكوات", "ضغط بنش", "سحب أمامي"} <= unresolved_names
    assert {"RDL", "DB bench", "Cable Y-raise"} <= {
        row["input_exercise_name"] for case in cases for row in case["expected_rows"]
    }
    rir_targets = {
        str(row["rir"])
        for case in cases
        for row in case["expected_rows"]
        if row.get("rir") is not None
    }
    rpe_targets = {
        str(row["rpe"])
        for case in cases
        for row in case["expected_rows"]
        if row.get("rpe") is not None
    }
    assert {"0", "4"} <= rir_targets
    assert {"6", "9.5"} <= rpe_targets

    for case in cases:
        assert isinstance(case.get("description"), str) and len(case["description"]) >= 24
        payload = runner.spreadsheet_bytes(case)
        assert payload and len(payload) <= 1024 * 1024
        assert case["expected_rows"]
        assert len({row.get("notes") for row in case["expected_rows"]}) >= min(12, len(case["expected_rows"]))
        selected_grid = case.get("grid") or case.get("sheets", {}).get(case["expected_selected_tab"], [])
        note_headers = []
        for header_index, header in enumerate(selected_grid):
            header_values = [str(value).casefold() for value in header]
            has_exercise_header = any(
                "exercise" in value or "movement" in value or "التمرين" in value or "الحركة" in value
                for value in header_values
            )
            note_column = next(
                (index for index, value in enumerate(header_values) if "note" in value or "cue" in value or "ملاحظات" in value),
                None,
            )
            if has_exercise_header and note_column is not None:
                note_headers.append((header_index, note_column))
        for row in case["expected_rows"]:
            source_index = row["source_row"] - 1
            prior_headers = [header for header in note_headers if header[0] < source_index]
            assert prior_headers and row["notes"] == selected_grid[source_index][max(prior_headers)[1]]
        has_rest_column = any(
            any("exercise" in str(value).casefold() or "التمرين" in str(value) for value in header)
            and any("rest" in str(value).casefold() or "راحة" in str(value) for value in header)
            for header in selected_grid
        )
        if has_rest_column:
            assert all(type(row.get("rest_seconds")) is int and row["rest_seconds"] > 0 for row in case["expected_rows"])
        assert case["expected_chosen_week"] in (case["expected_weeks"] or [None])
        if case["expected_weeks"]:
            assert len(case["expected_weeks"]) in {3, 4}
            for week in case["expected_weeks"]:
                week_rows = [row for row in case["expected_rows"] if row["week"] == week]
                assert len(week_rows) >= 12
                assert len({row["day"] for row in week_rows}) >= 3
                assert min(Counter(row["day"] for row in week_rows).values()) >= 4
        else:
            assert len(case["expected_rows"]) >= 12
            assert len(case["expected_rows"]) <= 40
            per_day = Counter(row["day"] for row in case["expected_rows"])
            assert len(per_day) >= 3
            assert min(per_day.values()) >= 4
        assert set(case["expected_unresolved_names"]) == {
            row["input_exercise_name"] for row in case["expected_rows"] if row["expected_resolution"] == "unresolved"
        }
        for row in case["expected_rows"]:
            assert row["expected_resolution"] in {"library", "unresolved"}
            source_name = row["input_exercise_name"]
            resolved_id = evaluation_session.db.find_unique_exercise_id_by_exact_name(source_name)
            assert (resolved_id is not None) == (row["expected_resolution"] == "library"), (
                case["id"],
                source_name,
                resolved_id,
            )
            assert (str(resolved_id) if resolved_id is not None else None) == row["expected_exercise_id"]
            if resolved_id is not None:
                entry = evaluation_session.db.get_exercise_library_entry(resolved_id)
                assert entry["name"] == row["exercise_name"], case["id"]
            assert isinstance(row["approximation_codes"], list)
            assert set(row["approximation_reasons"]) == set(row["approximation_codes"])
            assert all(reason.strip() for reason in row["approximation_reasons"].values())


def test_runner_uses_http_import_path_and_reports_a_dropped_row(evaluation_session, cases):
    from tests.fakes.chat_model import ScriptedChatModel

    case = copy.deepcopy(next(case for case in cases if case["id"] == "17_coach_abbreviations_and_unknowns"))
    reply = runner.expected_translation_reply(case)
    reply["rows"].pop()
    results = runner.run_suite(
        [case],
        model=ScriptedChatModel([reply], default_turn={"suggestions": []}),
        session=evaluation_session,
    )

    assert results[0]["import_mode"] == "freeform"
    assert results[0]["http_status"] == 200
    assert results[0]["row_results"][-1]["checks"]["present_or_reported"] is False
    assert runner.aggregate_metrics(results)["silently_dropped_rows"] == 1
    assert results[0]["row_results"][-1]["failures"]


def test_side_by_side_weeks_keep_row_identity_and_error_attribution(evaluation_session, cases):
    case = next(case for case in cases if case["id"] == "06_three_week_side_by_side")
    results = runner.run_suite([case], model=runner.build_mock_model(), session=evaluation_session)
    result = results[0]["result"]
    assert len(result["rows"]) == 36
    assert [len(result["rows_by_week"][week]) for week in ("Week 1", "Week 2", "Week 3")] == [12, 12, 12]
    for week in result["rows_by_week"].values():
        assert len({row["source_row"] for row in week}) == 12
    assert result["selected_week"] == "Week 1"
    assert result["weeks_not_imported"] == ["Week 2", "Week 3"]
    assert results[0]["week_layout_correct"] is True

    first = case["expected_rows"][0]
    error_case = runner.score_import_result(
        case,
        {
            "rows": [],
            "errors": [{"source_row": first["source_row"], "week": "Week 1", "code": "test.invalid"}],
            "detected_tabs": case["expected_tabs"],
            "selected_tab": case["expected_selected_tab"],
            "detected_weeks": case["expected_weeks"],
            "selected_week": case["expected_chosen_week"],
            "weeks_not_imported": ["Week 2", "Week 3"],
            "confirm_layout": False,
        },
        http_status=200,
        preflight={"detected_tabs": case["expected_tabs"], "requires_tab_choice": False},
    )
    same_source = [row for row in error_case["row_results"] if row["source_row"] == first["source_row"]]
    assert [row["checks"]["present_or_reported"] for row in same_source] == [True, False, False]


def test_scorer_requires_row_week_and_exercise_and_counts_extra_rows(cases):
    case = copy.deepcopy(next(case for case in cases if case["id"] == "01_english_strength_week"))
    expected = case["expected_rows"][0]
    invented = {
        "source_row": expected["source_row"],
        "week": None,
        "exercise_name": "Invented movement",
        "exercise_id": None,
        "day": expected["day"],
        "day_name": expected["day_name"],
        "sets": expected["sets"],
        "reps_min": expected["reps_min"],
        "reps_max": expected["reps_max"],
        "warnings": [],
    }
    result = {
        "rows": [invented],
        "errors": [],
        "detected_tabs": case["expected_tabs"],
        "selected_tab": case["expected_selected_tab"],
        "detected_weeks": [],
        "selected_week": None,
        "weeks_not_imported": [],
        "confirm_layout": False,
    }
    scored = runner.score_import_result(
        case,
        result,
        http_status=200,
        preflight={
            "detected_tabs": case["expected_tabs"],
            "requires_tab_choice": False,
        },
    )
    assert scored["row_results"][0]["checks"]["present_or_reported"] is False
    assert scored["extra_rows"] == 1
    assert runner.aggregate_metrics([scored])["extra_rows"] == 1
    assert runner.aggregate_metrics([scored])["silently_dropped_rows"] == len(case["expected_rows"])


def test_whole_sheet_http_failure_is_reported_for_each_row_but_fails_correctness(cases):
    case = next(case for case in cases if case["id"] == "09_compact_sets_reps_cells")
    scored = runner.score_import_result(
        case,
        None,
        http_status=503,
        http_error="temporary import failure",
        preflight={"detected_tabs": ["CSV"], "requires_tab_choice": False},
    )

    assert all(row["checks"]["present_or_reported"] for row in scored["row_results"])
    assert all(not row["checks"]["day_sets_reps_correct"] for row in scored["row_results"])
    assert runner.aggregate_metrics([scored])["silently_dropped_rows"] == 0
    assert scored["passed"] is False


def test_invented_rows_are_reported_without_becoming_a_pass_condition(evaluation_session, cases):
    case = next(case for case in cases if case["id"] == "09_compact_sets_reps_cells")
    results = runner.run_suite([case], model=runner.build_mock_model(), session=evaluation_session)
    results[0]["produced_rows"].append(
        {
            "source_row": 999,
            "week": None,
            "exercise_name": "Invented row",
            "exercise_id": None,
            "warnings": [],
        }
    )
    results[0]["extra_rows"] = 1
    entries = [{"filename": f"{case['id']}.json", "fixture": case}]
    report = runner.build_report(
        results,
        mode="live",
        privacy_pass=True,
        dataset_review=_review(entries),
        dataset_entries=entries,
    )
    report["model_run"] = "hosted_coach"
    report["model"], report["backend"] = program_import_ai.coach_model_identity()
    report["pass"] = True

    assert report["gates"]["evaluation"]["metrics"]["extra_rows"] == 1
    assert program_import_ai.validate_report(report)[0] is True


def test_scorer_uses_warning_codes_consistently_and_never_applies_unresolved_names(evaluation_session, cases):
    from tests.fakes.chat_model import ScriptedChatModel

    load_case = copy.deepcopy(next(case for case in cases if case["id"] == "15_kilogram_load_column"))
    load_reply = runner.expected_translation_reply(load_case)
    load_reply["rows"][0]["approximation_markers"] = []
    load_results = runner.run_suite(
        [load_case],
        model=ScriptedChatModel([load_reply], default_turn={"suggestions": []}),
        session=evaluation_session,
    )
    assert load_results[0]["row_results"][0]["checks"]["approximations_flagged"] is False
    assert (
        runner.aggregate_metrics(load_results)["approximations_flagged"]
        < runner.aggregate_metrics(load_results)["approximations"]
    )

    unknown_case = copy.deepcopy(next(case for case in cases if case["id"] == "17_coach_abbreviations_and_unknowns"))
    applied_reply = runner.expected_translation_reply(unknown_case)
    unresolved_index = next(
        i for i, row in enumerate(unknown_case["expected_rows"]) if row["expected_resolution"] == "unresolved"
    )
    applied_reply["rows"][unresolved_index]["exercise"] = "Bench Press (Barbell)"
    applied_results = runner.run_suite(
        [unknown_case],
        model=ScriptedChatModel([applied_reply], default_turn={"suggestions": []}),
        session=evaluation_session,
    )
    assert applied_results[0]["row_results"][unresolved_index]["checks"]["unresolved_only_suggested"] is False
    assert runner.aggregate_metrics(applied_results)["unresolved_auto_applied"] == 1


def test_mock_run_writes_plumbing_report_and_prints_summary(tmp_path, capsys):
    report_path = tmp_path / "program_import_mock.json"
    assert runner.main(["--mock", "--write-report", str(report_path), "--no-privacy"]) == 0
    output = capsys.readouterr().out
    assert "NOT A MODEL EVALUATION" in output
    assert "316 expected rows" in output

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mode"] == "mock"
    assert report["model_run"] == "scripted_fake"
    assert report["pass"] is False
    assert report["dataset_hash"] == runner.compute_dataset_hash()
    assert report["prompt_hash"] == program_import_ai.prompt_version_hash()
    assert report["model"] == "tests.fakes.chat_model.ScriptedChatModel"
    assert report["backend"] == "scripted"
    assert report["gates"]["privacy"]["pass"] is False
    assert len(report["runs"][0]["sheets"]) == 19
    assert all(sheet["passed"] for sheet in report["runs"][0]["sheets"])
    assert program_import_ai.validate_report(report)[0] is False


def test_live_report_validator_recomputes_metrics_rows_sheets_and_hash(evaluation_session, cases):
    case = next(case for case in cases if case["id"] == "09_compact_sets_reps_cells")
    report = _valid_report(case, evaluation_session)
    assert program_import_ai.validate_report(report)[0] is True

    hand_edited_metrics = copy.deepcopy(report)
    hand_edited_metrics["gates"]["evaluation"]["metrics"]["correct_rows"] -= 1
    assert program_import_ai.validate_report(hand_edited_metrics)[0] is False

    hand_edited_run_metrics = copy.deepcopy(report)
    hand_edited_run_metrics["runs"][0]["metrics"]["correct_rows"] -= 1
    assert program_import_ai.validate_report(hand_edited_run_metrics)[0] is False

    zero_sheets = copy.deepcopy(report)
    zero_sheets["runs"][0]["sheets"] = []
    assert program_import_ai.validate_report(zero_sheets)[0] is False

    failed_row_without_metric_change = copy.deepcopy(report)
    failed_row_without_metric_change["runs"][0]["sheets"][0]["row_results"][0]["checks"]["day_sets_reps_correct"] = (
        False
    )
    assert program_import_ai.validate_report(failed_row_without_metric_change)[0] is False

    changed_fixture = copy.deepcopy(report)
    changed_fixture["dataset_fixtures"][0]["fixture"]["description"] += " edited"
    assert program_import_ai.validate_report(changed_fixture)[0] is False

    changed_sheet_ids = copy.deepcopy(report)
    changed_sheet_ids["runs"][0]["sheets"][0]["case_id"] = "other-sheet"
    assert program_import_ai.validate_report(changed_sheet_ids)[0] is False

    changed_row_count = copy.deepcopy(report)
    changed_row_count["runs"][0]["sheets"][0]["expected_rows"] += 1
    assert program_import_ai.validate_report(changed_row_count)[0] is False


def test_row_evidence_failures_and_mock_instance_cannot_claim_live(cases, evaluation_session):
    case = next(case for case in cases if case["id"] == "09_compact_sets_reps_cells")
    report = _valid_report(case, evaluation_session)
    for field, value in (
        ("pass", False),
        ("prompt_hash", "stale"),
        ("model", "different-model"),
        ("model_run", "scripted_fake"),
        ("dataset_hash", "f" * 64),
    ):
        changed = copy.deepcopy(report)
        changed[field] = value
        assert program_import_ai.validate_report(changed)[0] is False, field

    incomplete_review = copy.deepcopy(report)
    incomplete_review["dataset_review"] = {
        "reviewed": True,
        "reviewed_by": "",
        "reviewed_on": "",
        "reviewed_dataset_hash": "",
    }
    assert program_import_ai.validate_report(incomplete_review)[0] is False


def test_fixture_edit_requires_new_owner_review_but_check_report_verdict_is_self_contained(
    tmp_path, evaluation_session, cases, capsys
):
    case = next(case for case in cases if case["id"] == "09_compact_sets_reps_cells")
    report = _valid_report(case, evaluation_session)
    assert program_import_ai.validate_report(report)[0] is True

    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    for path in list_fixture_files(runner.DEFAULT_DATASET):
        shutil.copyfile(path, dataset_dir / path.name)
    recorded_review = runner.record_owner_review(dataset_dir, "Sample owner")
    fixture_path = dataset_dir / "01_english_strength_week.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture["description"] += " changed after review"
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    assert runner.review_matches_dataset(recorded_review, runner.compute_dataset_hash(dataset_dir)) is False

    report_path = tmp_path / "embedded-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    assert runner.main(["--check-report", str(report_path), "--dataset", str(dataset_dir)]) == 0
    assert "differs from current fixture files" in capsys.readouterr().out
    assert program_import_ai.validate_report(report)[0] is True

    # Live runs are refused before loading the hosted model while REVIEW.json is stale.
    assert (
        runner.main(["--dataset", str(dataset_dir), "--write-report", str(tmp_path / "live.json"), "--no-privacy"]) == 2
    )
    assert "owner review is missing or stale" in capsys.readouterr().err


def test_record_review_cli_binds_current_canonical_hash(tmp_path, capsys):
    directory = tmp_path / "fixtures"
    shutil.copytree(runner.DEFAULT_DATASET, directory)
    assert runner.main(["--record-review", "--reviewer", "Sample owner", "--dataset", str(directory)]) == 0
    assert "Recorded owner review" in capsys.readouterr().out
    review = json.loads((directory / "REVIEW.json").read_text(encoding="utf-8"))
    assert review["reviewed"] is True
    assert review["reviewed_dataset_hash"] == runner.compute_dataset_hash(directory)
    assert json.loads((directory / "REVIEW.json").read_text(encoding="utf-8")) == review
