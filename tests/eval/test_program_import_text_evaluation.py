"""Text Program import fixtures and shared-runner report gate tests (#434)."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from service import program_import_ai
from service.program_import_evaluation import fixture_entries_hash
from tests.eval import run_program_import_evaluation as runner


_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_ROW_SCHEME = re.compile(r"(?P<sets>\d+)\s*(?:x|×)\s*(?P<reps>\d+(?:\s*[-–]\s*\d+)?(?:\s*/\s*\d+){0,2})", re.I)
_ARABIC_SCHEME = re.compile(
    r"(?P<sets>\d+)\s*(?:مجموعات|جولات)\s*×\s*(?P<reps>\d+(?:\s*[-–]\s*\d+)?(?:\s*/\s*\d+){0,2})"
    r"(?:\s*عدة)?|(?P<rounds>\d+)\s*جولات\s*(?P<round_reps>\d+)\s*عدة",
    re.I,
)


def _numbers(value: str) -> list[int]:
    return [int(item) for item in re.findall(r"\d+", value.translate(_ARABIC_DIGITS))]


def _parsed_scheme(line: str) -> tuple[int, int, int] | None:
    line = line.translate(_ARABIC_DIGITS)
    match = _ARABIC_SCHEME.search(line) or _ROW_SCHEME.search(line)
    if not match:
        return None
    if match.groupdict().get("rounds"):
        return int(match["rounds"]), int(match["round_reps"]), int(match["round_reps"])
    reps = _numbers(match["reps"])
    return int(match["sets"]), min(reps), max(reps)


def _parsed_effort(line: str) -> tuple[float | None, float | None]:
    # "حتى قرب الفشل" has no numeric target; these fixtures preserve it verbatim
    # in notes and mark the conversion as approximate instead of inventing RIR.
    normalized = line.translate(_ARABIC_DIGITS)
    rpe_range = re.search(r"\bRPE\s*(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", normalized, re.I)
    if rpe_range:
        low, high = map(float, rpe_range.groups())
        return None, (low + high) / 2
    range_match = re.search(r"\bRIR\s*(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", normalized, re.I)
    if range_match:
        lower, upper = map(float, range_match.groups())
        return min(5, max(0, (lower + upper) / 2)), None
    rir_match = re.search(r"(?:@\s*RIR|\bRIR)\s*(\d+(?:\.\d+)?)", normalized, re.I)
    if rir_match:
        return min(5, max(0, float(rir_match.group(1)))), None
    reserve_match = re.search(r"\b(?:two|2)\s+(?:clean\s+)?reps?\s+in\s+reserve", normalized, re.I)
    if reserve_match:
        return 2, None
    rpe_match = re.search(r"\bRPE\s*(\d+(?:\.\d+)?)", normalized, re.I)
    if rpe_match:
        return None, float(rpe_match.group(1))
    return None, None


def _parsed_rest(line: str) -> int | None:
    normalized = line.translate(_ARABIC_DIGITS).lower()
    if re.search(r"\bhold\b|ثبات", normalized):
        return None
    if re.search(r"راحة\s*دقيقتين", normalized):
        return 120
    if re.search(r"راحة\s*دقيقة", normalized):
        return 60
    if re.search(r"راحة\s*(\d+)\s*ث", normalized):
        return int(re.search(r"راحة\s*(\d+)\s*ث", normalized).group(1))
    range_match = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*sec", normalized)
    if range_match:
        low, high = map(int, range_match.groups())
        return (low + high) // 2
    match = re.search(r"(?:rest\s*)?(\d+)\s*(?:s|sec|secs|seconds?)\b|r:\s*(\d+)\s*'", normalized)
    if match:
        seconds = int(match.group(1) or (int(match.group(2)) * 60))
        return seconds
    arabic_minutes = re.search(r"راحة\s*(\d+)\s*د", normalized)
    if arabic_minutes:
        return int(arabic_minutes.group(1)) * 60
    minutes = re.search(r"(?:rest\s*)?(\d+)\s*min(?:ute)?s?", normalized)
    if minutes:
        return int(minutes.group(1)) * 60
    return None


def _check_fixture_lines(case: dict) -> list[str]:
    lines = case["text"].splitlines()
    errors = []
    row_by_line = {row["source_line"]: row for row in case["expected_rows"]}
    for row in case["expected_rows"]:
        line_number = row["source_line"]
        scheme = _parsed_scheme(row["original_text"])
        if scheme != (row["sets"], row["reps_min"], row["reps_max"]):
            errors.append(f"sets/reps {case['id']} L{line_number}: parsed {scheme}, expected {(row['sets'], row['reps_min'], row['reps_max'])}")
        rir, rpe = _parsed_effort(row["original_text"])
        expected_rir = row["rir"]
        if isinstance(expected_rir, str):
            rir_numbers = _numbers(expected_rir)
            expected_rir = min(5, max(0, sum(rir_numbers) / len(rir_numbers))) if rir_numbers else None
        if rir is not None and (expected_rir is None or float(expected_rir) != rir):
            errors.append(f"effort {case['id']} L{line_number}: parsed rir {rir}, expected {row['rir']}")
        if rpe is not None and (row["rpe"] is None or float(row["rpe"]) != rpe):
            errors.append(f"effort {case['id']} L{line_number}: parsed rpe {rpe}, expected {row['rpe']}")
        rest = _parsed_rest(row["original_text"])
        if rest != row["rest_seconds"]:
            errors.append(f"rest {case['id']} L{line_number}: parsed {rest}, expected {row['rest_seconds']}")
        text_with_cue = " ".join(lines[line_number - 1:min(line_number + 1, len(lines))])
        lower = text_with_cue.lower()
        codes = set(row["approximation_codes"])
        triggers = {
            "program_import.reps_approximated.v1": bool(re.search(r"/|amrap|failure|فشل|hold", lower)),
            "program_import.effort_approximated.v1": bool(
                re.search(r"(?:RIR|RPE)\s*\d+\s*[-–]|حتى قرب الفشل", text_with_cue, re.I)
            ),
            "program_import.rpe_converted.v1": bool(re.search(r"RPE\s*\d", text_with_cue, re.I)),
            "program_import.load_preserved_as_note.v1": bool(re.search(r"%\s*1rm|bodyweight\s*\+\s*\d+\s*kg", lower)),
            "program_import.unsupported_preserved_as_note.v1": bool(re.search(r"bodyweight\s*\+\s*\d+\s*kg|AMRAP|failure|فشل|hold", lower)),
        }
        for code in codes:
            if code not in triggers or not triggers[code]:
                errors.append(f"approximation {case['id']} L{line_number}: {code} has no trigger")
        expected_notes = row["notes"]
        if "حتى قرب الفشل" in row["original_text"] and (
            row["rir"] is not None or "حتى قرب الفشل" not in expected_notes
        ):
            errors.append(f"effort {case['id']} L{line_number}: near-failure wording must remain verbatim in notes")
        if expected_notes:
            note_parts = [part.strip() for part in re.split(r"[؛\n—]", expected_notes) if part.strip()]
            if any(text_with_cue.count(part) != 1 for part in note_parts):
                errors.append(f"notes {case['id']} L{line_number}: expected note is not present exactly once")
        if not expected_notes and line_number < len(lines):
            following = lines[line_number].strip()
            if (
                following
                and not following.endswith("?")
                and not following.startswith("---")
                and line_number + 1 not in row_by_line
                and not re.match(r"^(?:week|day|الأسبوع|اليوم|monday|upper|full body)\b", following, re.I)
            ):
                if not re.search(r"\d+\s*(?:x|×)|مجموعات|جولات", following, re.I):
                    errors.append(f"notes {case['id']} L{line_number}: non-exercise cue line was dropped")
        if not expected_notes:
            sections = re.split(r"\s*[—–]\s*", row["original_text"])
            for section in sections[1:]:
                residue = re.sub(
                    r"\b(?:RIR\s*\d+(?:\s*[-–]\s*\d+)?|RPE\s*\d+(?:\s*[-–]\s*\d+)?|(?:two|2)\s+(?:clean\s+)?reps?\s+in\s+reserve|(?:rest\s*)?\d+(?:\s*[-–]\s*\d+)?\s*(?:s|sec|secs|seconds?|min(?:ute)?s?)|r:\s*\d+\s*'|AMRAP|\d+%\s*1RM|bodyweight\s*\+\s*\d+\s*kg)\b",
                    "",
                    section,
                    flags=re.I,
                )
                residue = re.sub(r"راحة\s*(?:دقيقة|\d+\s*(?:ث|د))|حتى قرب الفشل", "", residue)
                residue = re.sub(r"\b(?:rest\s*)?\d+\s*min(?:ute)?s?\b", "", residue, flags=re.I)
                if not residue.strip().endswith("?") and re.search(r"[A-Za-z\u0600-\u06ff]{3,}", residue) and len(residue.split()) >= 3:
                    errors.append(f"notes {case['id']} L{line_number}: same-line cue was dropped")
        if row["original_text"].count(row["notes"]) > 1 and row["notes"]:
            errors.append(f"notes {case['id']} L{line_number}: cue repeats within the exercise line")
    return errors


@pytest.fixture(scope="module")
def dataset():
    return runner.load_dataset(kind=runner.TEXT_KIND)


@pytest.fixture(scope="module")
def evaluation_session():
    with runner.ProgramImportEvaluationSession() as session:
        yield session


@pytest.fixture(scope="module")
def perfect_text_run(dataset, evaluation_session):
    model = runner.build_mock_model(runner.TEXT_KIND)
    results = runner.run_suite(
        dataset["cases"], model=model, session=evaluation_session, kind=runner.TEXT_KIND
    )
    entries = dataset["fixture_entries"]
    review = {
        "reviewed": True,
        "reviewed_by": "Synthetic owner",
        "reviewed_on": "2026-10-19",
        "reviewed_dataset_hash": fixture_entries_hash(entries),
    }
    report = runner.build_report(
        results,
        mode="live",
        privacy_pass=True,
        dataset_review=review,
        dataset_entries=entries,
        model_instance=model.scripted_model,
        kind=runner.TEXT_KIND,
    )
    # Validator baseline simulates the hosted identity; no hosted model is called.
    model_id, backend = program_import_ai.coach_model_identity()
    report.update(model_run="hosted_coach", model=model_id, backend=backend)
    report["pass"] = True
    return results, report


def _write_fixtures(path: Path, entries):
    path.mkdir()
    for entry in entries:
        (path / entry["filename"]).write_text(
            json.dumps(entry["fixture"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def test_text_fixtures_cover_required_shapes_and_seeded_catalog(dataset, evaluation_session):
    cases = dataset["cases"]
    rows = [row for case in cases for row in case["expected_rows"]]
    ids = {row["expected_exercise_id"] for row in rows if row["expected_exercise_id"]}
    assert 12 <= len(cases) <= 15
    assert 150 <= len(rows) <= 220
    combined = "\n".join(case["text"] for case in cases)
    nonblank_lines = [line for line in combined.splitlines() if line.strip()]
    arabic_lines = [line for line in nonblank_lines if re.search(r"[\u0600-\u06ff]", line)]
    arabic_digit_lines = [line for line in nonblank_lines if re.search(r"[٠-٩]", line)]
    token_names = ("@RIR2", "RIR 1-2", "RPE 8", "RPE 7-8", "2 in reserve", "حتى قرب الفشل")
    effort_counts = {
        token: sum(token in row["original_text"] for row in rows)
        for token in token_names
    }
    assert all(count > 0 for count in effort_counts.values())
    assert max(effort_counts.values()) <= len(rows) * 0.35
    assert sum(row["rest_seconds"] is not None for row in rows) >= len(rows) * 0.30
    assert len(arabic_lines) / len(nonblank_lines) >= 0.30
    assert len(arabic_digit_lines) >= 15
    assert "راحة دقيقة" in combined and "راحة ٩٠ ث" in combined and "R: 2'" in combined
    assert "2 min rest" in combined and "60-90 sec" in combined
    assert "الأسبوع الأول" in combined and "اليوم التاني – رجل" in combined
    assert "٤ مجموعات × ١٠" in combined and "٣ جولات ١٢ عدة" in combined
    assert "AMRAP" in combined and "12/10/8" in combined and "sec hold" in combined
    assert "skull crushers" in combined and "hammer curls" in combined and "plank" in combined
    egyptian_notes = next(case for case in cases if case["id"] == "03_egyptian_mixed")
    assert any("خليك متحكم في النزول" in row["notes"] for row in egyptian_notes["expected_rows"])
    coaching_notes = next(case for case in cases if case["id"] == "08_coaching_notes")
    assert any("اثبت على صدرك" in row["notes"] for row in coaching_notes["expected_rows"])
    assert any("خلي الرسغ فوق الكوع" in row["notes"] for row in coaching_notes["expected_rows"])
    long_case = next(case for case in cases if case["id"] == "12_long_program")
    assert 2_000 < len(long_case["text"]) < 20_000
    assert len({row["notes"] for row in long_case["expected_rows"] if row["notes"]}) == sum(bool(row["notes"]) for row in long_case["expected_rows"])
    assert "Forwarded" in combined and "@RIR2" in combined and "RPE 8" in combined
    assert "• 💪 *bench press " in combined and "• *incline DB press " in combined
    assert all(
        name in combined
        for name in (
            "squats", "leg ext", "lat pull", "pec deck", "shoulder press machine",
            "skull crushers", "hammer curls", "calf raises", "plank",
        )
    )
    assert "4 x 8-10" in combined and "3×12" in combined and "rest 90s" in combined
    assert "60-90 sec" in combined and "70% 1RM" in combined
    assert "اليوم الأول" in combined and "Monday" in combined and "Upper A" in combined
    assert all(token in combined for token in ("بنش", "سكوات", "ضغط بنش", "رفرفة جانبي", "سحب أمامي", "ديدلفت روماني", "تمرين البطن"))
    assert "فرانكو" not in combined and "Arabizi" not in combined
    assert "kneeling face pull" not in combined and "45 degree leg press" not in combined
    case_02 = next(case for case in cases if case["id"] == "02_arabic_standard")
    case_11 = next(case for case in cases if case["id"] == "11_unresolved_names")
    names_02 = {row["input_exercise_name"] for row in case_02["expected_rows"]}
    names_11 = {row["input_exercise_name"] for row in case_11["expected_rows"]}
    assert len(names_02 & names_11) < len(names_11) / 2
    assert all(row["day"] is None and row["day_name"] is None for row in next(c for c in cases if c["id"] == "10_ambiguous_layout")["expected_rows"])
    assert all(row.get("day_placement_applicable") is False for row in next(c for c in cases if c["id"] == "10_ambiguous_layout")["expected_rows"])
    assert next(row for row in next(c for c in cases if c["id"] == "01_whatsapp_english")["expected_rows"] if row["source_line"] == 4)["day_name"] == "Push"
    repeated = next(case for case in cases if case["id"] == "07_repeated_blocks")
    assert {(row["day"], row["day_name"]) for row in repeated["expected_rows"]} == {(1, "Full Body A")}
    chosen = next(case for case in cases if case["id"] == "06_chosen_week")
    assert chosen["expected_chosen_week"] == "Week 1"
    week_rows = {week: [row for row in chosen["expected_rows"] if row["week"] == week] for week in chosen["expected_weeks"]}
    assert week_rows["Week 2"] and any(
        (first["sets"], first["reps_min"], first["reps_max"])
        != (second["sets"], second["reps_min"], second["reps_max"])
        for first, second in zip(week_rows["Week 1"], week_rows["Week 2"])
    )
    for case in cases:
        assert len(case["text"]) < 20_000
        lines = case["text"].splitlines()
        for row in case["expected_rows"]:
            assert 1 <= row["source_line"] <= len(lines)
            assert lines[row["source_line"] - 1].strip()
            assert row["original_text"] in lines[row["source_line"] - 1]
            if row["expected_exercise_id"] is not None:
                exercise = evaluation_session.db.get_exercise_library_entry(row["expected_exercise_id"])
                assert exercise["id"] == row["expected_exercise_id"]
    assert sum(bool(row["notes"]) for row in rows) >= 20
    assert len(ids) >= 28


def test_fixture_prescriptions_notes_and_approximations_match_the_written_lines(dataset):
    failures = [failure for case in dataset["cases"] for failure in _check_fixture_lines(case)]
    assert failures == [], "\n".join(failures)


def test_every_fixture_is_perfectly_self_consistent_through_http(perfect_text_run):
    results, report = perfect_text_run
    assert len(results) == 12
    fixture_by_id = {
        entry["fixture"]["id"]: entry["fixture"]
        for entry in runner.load_dataset(kind=runner.TEXT_KIND)["fixture_entries"]
    }
    for case in results:
        assert case["http_status"] == 200, (case["case_id"], case["http_error"])
        assert case["passed"], (case["case_id"], case["layout_failures"])
        assert all(not row["failures"] for row in case["row_results"])
        fixture = fixture_by_id[case["case_id"]]
        for expected in fixture["expected_rows"]:
            actual = next(
                observed for observed in case["produced_rows"]
                if observed["source_row"] == expected["source_line"] and observed["week"] == expected["week"]
            )
            assert actual["exercise_id"] == expected["expected_exercise_id"]
            if expected["expected_resolution"] == "unresolved":
                assert actual["exercise_id"] is None
                assert actual["resolution"] in {"unresolved", "ambiguous"}
            else:
                assert actual["resolution"] == "resolved"
                assert actual["exercise_id"] == expected["expected_exercise_id"]
    assert report["run"]["expected_rows"] == 193
    assert all(
        "preflight" not in sheet and "tab_choice_correct" not in sheet
        for sheet in report["runs"][0]["sheets"]
    )


def test_live_text_run_refuses_missing_or_stale_review(tmp_path, dataset):
    path = tmp_path / "set"
    _write_fixtures(path, dataset["fixture_entries"])
    assert runner.load_dataset(path, kind=runner.TEXT_KIND)["owner_review"]["reviewed"] is False
    assert runner.main(["--suite", "text", "--dataset", str(path)]) == 2
    runner.record_owner_review(path, "Owner", kind=runner.TEXT_KIND)
    changed = copy.deepcopy(dataset["fixture_entries"][0]["fixture"])
    changed["text"] += " changed"
    (path / dataset["fixture_entries"][0]["filename"]).write_text(
        json.dumps(changed, ensure_ascii=False), encoding="utf-8"
    )
    assert runner.main(["--suite", "text", "--dataset", str(path)]) == 2


def test_text_report_rejections_start_from_valid_baseline(perfect_text_run):
    _results, baseline = perfect_text_run
    assert program_import_ai.validate_report(baseline, runner.TEXT_KIND.report_config) == (True, [])

    changed_metrics = copy.deepcopy(baseline)
    changed_metrics["gates"]["evaluation"]["metrics"]["correct_rows"] += 1
    valid, reasons = program_import_ai.validate_report(changed_metrics, runner.TEXT_KIND.report_config)
    assert not valid and reasons == ["recorded evaluation metrics disagree with the per-sheet row results"]

    changed_fixture = copy.deepcopy(baseline)
    changed_fixture["dataset_fixtures"][0]["fixture"]["text"] += " changed"
    valid, reasons = program_import_ai.validate_report(changed_fixture, runner.TEXT_KIND.report_config)
    assert not valid and reasons == ["embedded dataset fixtures do not match the claimed dataset hash"]

    stale_review = copy.deepcopy(baseline)
    stale_review["dataset_review"]["reviewed_dataset_hash"] = "0" * 64
    valid, reasons = program_import_ai.validate_report(stale_review, runner.TEXT_KIND.report_config)
    assert not valid and reasons == ["evaluation report dataset hash does not match the reviewed dataset hash"]


def test_scripted_model_report_never_passes(perfect_text_run):
    results, baseline = perfect_text_run
    assert program_import_ai.validate_report(baseline, runner.TEXT_KIND.report_config)[0]
    entries = runner.load_dataset(kind=runner.TEXT_KIND)["fixture_entries"]
    review = {
        "reviewed": True,
        "reviewed_by": "Synthetic owner",
        "reviewed_on": "2026-10-19",
        "reviewed_dataset_hash": fixture_entries_hash(entries),
    }
    scripted = runner.build_report(
        results, mode="mock", privacy_pass=True, dataset_review=review, dataset_entries=entries,
        model_instance=runner.build_mock_model(runner.TEXT_KIND).scripted_model, kind=runner.TEXT_KIND,
    )
    assert scripted["backend"] == "scripted"
    assert scripted["mode"] == "mock"
    assert scripted["pass"] is False
    report = copy.deepcopy(baseline)
    for field in ("mode", "model_run", "model", "backend", "pass"):
        report[field] = scripted[field]
    valid, reasons = program_import_ai.validate_report(report, runner.TEXT_KIND.report_config)
    assert not valid and reasons == ["evaluation report was not produced by the configured hosted coach model"]


def test_valid_reports_are_rejected_by_the_other_suite_gate(perfect_text_run, evaluation_session):
    _results, text_report = perfect_text_run
    assert program_import_ai.validate_report(text_report, runner.TEXT_KIND.report_config)[0]
    valid, reasons = program_import_ai.validate_report(text_report, runner.SHEET_KIND.report_config)
    assert not valid and reasons == ["evaluation report is for a different suite"]

    case = runner.load_cases()[0]
    sheet_results = runner.run_suite([case], model=runner.build_mock_model(), session=evaluation_session)
    entries = [{"filename": f"{case['id']}.json", "fixture": case}]
    review = {
        "reviewed": True,
        "reviewed_by": "Synthetic owner",
        "reviewed_on": "2026-10-19",
        "reviewed_dataset_hash": fixture_entries_hash(entries),
    }
    sheet_report = runner.build_report(
        sheet_results, mode="live", privacy_pass=True, dataset_review=review,
        dataset_entries=entries, model_instance=runner.build_mock_model().scripted_model,
    )
    model_id, backend = program_import_ai.coach_model_identity()
    sheet_report.update(model_run="hosted_coach", model=model_id, backend=backend)
    sheet_report["pass"] = True
    assert program_import_ai.validate_report(sheet_report, runner.SHEET_KIND.report_config)[0]
    valid, reasons = program_import_ai.validate_report(sheet_report, runner.TEXT_KIND.report_config)
    assert not valid and reasons == ["evaluation report is for a different suite"]


def test_text_runner_smoke_uses_http_route_and_scripted_model(evaluation_session, dataset):
    model = runner.build_mock_model(runner.TEXT_KIND)
    result = runner.run_suite(
        dataset["cases"][:1], model=model, session=evaluation_session, kind=runner.TEXT_KIND
    )[0]
    assert result["http_status"] == 200
    assert result["import_mode"] == "text"
    assert result["passed"]


def test_text_cli_mock_and_check_report_use_text_config(tmp_path, perfect_text_run, monkeypatch):
    _results, report = perfect_text_run
    report_path = tmp_path / "text-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    assert runner.main(["--suite", "text", "--check-report", str(report_path)]) == 0

    entries = runner.load_dataset(kind=runner.TEXT_KIND)["fixture_entries"]
    dataset_path = tmp_path / "mock-data"
    _write_fixtures(dataset_path, entries)
    monkeypatch.chdir(tmp_path)
    assert runner.main(["--suite", "text", "--mock", "--dataset", str(dataset_path)]) == 0


def test_text_cli_live_path_returns_pass_status_with_scripted_model(tmp_path, monkeypatch, perfect_text_run):
    from utils import model_downloader

    entries = runner.load_dataset(kind=runner.TEXT_KIND)["fixture_entries"]
    dataset_path = tmp_path / "live-scripted-data"
    _write_fixtures(dataset_path, entries)
    runner.record_owner_review(dataset_path, "Synthetic owner", kind=runner.TEXT_KIND)
    model = runner.build_mock_model(runner.TEXT_KIND)
    def get_scripted_import_model():
        return (
            model
            if model_downloader._coach_import_llm_instance is None
            else model_downloader._coach_import_llm_instance
        )

    monkeypatch.setattr(model_downloader, "get_coach_import_llm", get_scripted_import_model)
    monkeypatch.setattr(program_import_ai, "coach_model_identity", lambda: ("configured-test", "test-provider"))
    assert runner.main(["--suite", "text", "--dataset", str(dataset_path)]) == 0
