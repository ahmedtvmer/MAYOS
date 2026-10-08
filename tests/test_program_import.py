"""Program template import contract tests (#298)."""

import io
import csv
import datetime as dt
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from service import coach as coach_service
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
HEADERS = [
    "day", "day_name", "order", "exercise", "sets", "reps", "rir", "rpe",
    "load_kg", "load_pct_e1rm", "rest_sec", "tempo", "notes",
]
CONFIRMED_ROW_FIELDS = (
    "source_row", "day", "day_name", "order", "exercise_name", "exercise_id",
    "sets", "reps_min", "reps_max", "target_rir", "rest_seconds", "tempo", "notes",
)


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    from database.database_manager import DatabaseManager
    from svc.rate_limit import limiter

    limiter._storage.reset()
    catalog_path = tmp_path / "catalog.db"
    connection = sqlite3.connect(catalog_path)
    connection.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT, "
        "equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT)"
    )
    connection.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT)")
    connection.execute(
        "INSERT INTO exercises (id, name, body_part, target_muscle, equipment) "
        "VALUES ('sq', 'Squat', 'Upper Legs', 'Quads', 'barbell'), "
        "('bp', 'Bench Press', 'Chest', 'Chest', 'barbell')"
    )
    connection.commit()
    connection.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(client, username):
    response = client.post(
        "/auth/register",
        json={"trainee_id": username, "password": "correct-horse-1"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _assignment(client, db, prefix="import"):
    coach_username = f"{prefix}-coach"
    player_username = f"{prefix}-player"
    coach_headers = _register(client, coach_username)
    invite = coach_service.issue_coach_invite(db, coach_username, actor="cli")
    assert invite["ok"]
    assert client.post(
        "/coach/invite/redeem", headers=coach_headers, json={"token": invite["token"]}
    ).status_code == 200
    assert client.put(
        "/coach/profile",
        headers=coach_headers,
        json={"display_name": "Coach", "bio": "", "specialization": "", "capacity": 5},
    ).status_code == 200
    player_headers = _register(client, player_username)
    assignment_invite = client.post("/coach/assignments/invites", headers=coach_headers).json()
    assignment = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": assignment_invite["token"], "consent": True},
    ).json()["assignment"]["assignment_id"]
    return coach_headers, player_headers, assignment


def _csv(rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(HEADERS)
    writer.writerows(rows)
    return output.getvalue().encode()


def _confirmed_rows(rows):
    return [{field: row[field] for field in CONFIRMED_ROW_FIELDS} for row in rows]


def _enable_program_import_ai(monkeypatch, tmp_path, mode="live"):
    from service import program_import_ai
    from service.program_import_evaluation import fixture_entries_hash
    from tests.eval import run_program_import_evaluation as evaluation_runner

    model, backend = program_import_ai.coach_model_identity()
    fixture = {
        "id": "test-sample",
        "description": "One synthetic row used to exercise the production enable gate.",
        "format": "csv",
        "tags": ["test"],
        "expected_tabs": ["CSV"],
        "expected_requires_tab_choice": False,
        "expected_selected_tab": "CSV",
        "expected_weeks": [],
        "expected_chosen_week": None,
        "expected_confirm_layout": False,
        "expected_rows": [{
            "source_row": 2, "week": None, "day": 1, "day_name": "Push",
            "input_exercise_name": "Squat", "exercise_name": "Squat",
            "expected_exercise_id": "sq", "expected_resolution": "library",
            "sets": 3, "reps_min": 6, "reps_max": 8, "approximation_codes": [],
        }],
    }
    entries = [{"filename": "01_sample.json", "fixture": fixture}]
    dataset_hash = fixture_entries_hash(entries)
    review = {
        "reviewed": True,
        "reviewed_by": "test owner",
        "reviewed_on": "2026-10-08",
        "reviewed_dataset_hash": dataset_hash,
    }
    actual = {
        "source_row": 2, "week": None, "day": 1, "day_name": "Push",
        "exercise_name": "Squat", "exercise_id": "sq", "sets": 3,
        "reps_min": 6, "reps_max": 8, "warnings": [],
    }
    import_result = {
        "rows": [actual], "errors": [], "detected_tabs": ["CSV"],
        "selected_tab": "CSV", "detected_weeks": [], "selected_week": None,
        "weeks_not_imported": [], "confirm_layout": False,
        "import_mode": "freeform",
    }
    scored = evaluation_runner.score_import_result(
        fixture, import_result, http_status=200, preflight=import_result
    )
    report = evaluation_runner.build_report(
        [scored], mode="live", privacy_pass=True, dataset_review=review,
        dataset_entries=entries, model_instance=None,
    )
    report["mode"] = mode
    report["model_run"] = "hosted_coach"
    report["model"] = model
    report["backend"] = backend
    report["pass"] = True
    assert report["model"] == model and report["backend"] == backend
    report_path = tmp_path / "program-import-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setenv("PROGRAM_IMPORT_AI_ENABLED", "true")
    monkeypatch.setenv("PROGRAM_IMPORT_AI_EVAL_REPORT", str(report_path))
    return program_import_ai


def test_csv_import_creates_only_program_draft_and_replacement_requires_confirmation(api):
    client, db = api
    coach_headers, player_headers, assignment_id = _assignment(client, db)
    active_before = client.get("/programs/active", headers=player_headers).json()
    upload = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("plan.csv", _csv([["1", "Push", "1", "Squat", "3", "6-8", "2", "", "", "", "90", "301", "Keep form"]]), "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    result = upload.json()
    assert result["draft_exists"] is False
    assert result["rows"][0]["exercise_id"] == "sq"
    assert result["rows"][0]["target_rir"] == 2
    assert "rest_seconds" in result["rows"][0]
    assert "rest_sec" not in result["rows"][0]

    reversed_reps = {**result["rows"][0], "reps_min": 9, "reps_max": 8}
    invalid = client.post(
        f"/coach/assignments/{assignment_id}/program-draft/import",
        headers=coach_headers,
        json={"program_name": "plan", "rows": _confirmed_rows([reversed_reps])},
    )
    assert invalid.status_code == 400
    invalid_exercise = {**result["rows"][0], "exercise_id": "not-owned"}
    rejected_exercise = client.post(
        f"/coach/assignments/{assignment_id}/program-draft/import",
        headers=coach_headers,
        json={"program_name": "plan", "rows": _confirmed_rows([invalid_exercise])},
    )
    assert rejected_exercise.status_code == 400
    assert rejected_exercise.json()["message_code"] == "program_import.no_rows.v1"

    created = client.post(
        f"/coach/assignments/{assignment_id}/program-draft/import",
        headers=coach_headers,
        json={"program_name": "plan", "rows": _confirmed_rows(result["rows"])},
    )
    assert created.status_code == 200, created.text
    assert created.json()["draft"]["days"][0]["exercises"][0]["exercise_id"] == "sq"
    assert client.get("/programs/active", headers=player_headers).json() == active_before
    assert client.post(
        f"/coach/assignments/{assignment_id}/program-draft/import",
        headers=coach_headers,
        json={"program_name": "again", "rows": _confirmed_rows(result["rows"])},
    ).status_code == 409


def test_csv_bare_rpe_values_convert_to_rir(api):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db, prefix="bare-rpe")
    upload = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("plan.csv", _csv([
            ["1", "Push", "1", "Squat", "3", "6-8", "", "8", "", "", "90", "", ""],
            ["1", "Push", "2", "Squat", "3", "6-8", "", "7.5", "", "", "90", "", ""],
        ]), "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    rows = upload.json()["rows"]
    assert [row["errors"] for row in rows] == [[], []]
    assert [row["target_rir"] for row in rows] == [2, 2.5]


def test_xlsx_requires_tab_choice_and_keeps_rpe_load_and_notes(api):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db)
    workbook = Workbook()
    program = workbook.active
    program.title = "Week A"
    program.append(HEADERS)
    program.append(["1", "يوم الدفع", "1", "Bench Press", "3", "8", "", "8", "60", "", "90", "", "ملاحظة أصلية"])
    notes = workbook.create_sheet("Notes")
    notes.append(["This tab is not a program"])
    file_bytes = io.BytesIO()
    workbook.save(file_bytes)
    first = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("plan.xlsx", file_bytes.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert first.status_code == 200, first.text
    assert first.json()["requires_tab_choice"] is True
    assert first.json()["rows"] == []

    second = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        data={"sheet": "Week A"},
        files={"file": ("plan.xlsx", file_bytes.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert second.status_code == 200, second.text
    row = second.json()["rows"][0]
    assert row["target_rir"] == 2
    assert "load: 60" in row["notes"]
    assert "ملاحظة أصلية" in row["notes"]
    assert any("load" in warning["code"] for warning in row["warnings"])


def test_unknown_exercise_is_reported_and_invalid_reps_are_row_scoped(api):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db)
    response = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("plan.csv", _csv([
            ["1", "Day A", "1", "Not in library", "3", "8", "2", "", "", "", "90", "", ""],
            ["1", "Day A", "2", "Squat", "3", "99", "2", "", "", "", "90", "", ""],
            ["1", "Day A", "3", "Bench Press", "3", "8", "hard", "", "", "", "90", "", ""],
        ]), "text/csv")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows"][0]["exercise_id"] is None
    assert body["unresolved_names"][0]["name"] == "Not in library"
    assert body["rows"][1]["valid"] is False
    assert body["rows"][1]["errors"][0]["column"] == "reps"
    assert body["rows"][1]["errors"][0]["source_row"] == 3
    assert body["rows"][2]["valid"] is False
    assert body["rows"][2]["errors"][0]["code"] == "program_import.invalid_effort.v1"
    coach_exercise = client.post(
        "/coach/exercises", headers=coach_headers, json={"name": "Not in library"}
    )
    assert coach_exercise.status_code == 201
    body["rows"][0]["exercise_id"] = coach_exercise.json()["id"]
    confirmed_rows = [dict(body["rows"][0]), dict(body["rows"][1])]
    confirmed_rows[1]["reps_min"] = 99
    imported = client.post(
        f"/coach/assignments/{assignment_id}/program-draft/import",
        headers=coach_headers,
        json={"program_name": "plan", "rows": _confirmed_rows(confirmed_rows)},
    )
    assert imported.status_code == 200, imported.text
    imported_exercises = imported.json()["draft"]["days"][0]["exercises"]
    assert len(imported_exercises) == 1
    assert imported_exercises[0]["is_coach_exercise"] is True


def test_ambiguous_alias_is_offered_as_unconfirmed_suggestions(api):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db)
    db.catalog_conn.executemany(
        "INSERT INTO exercise_aliases (exercise_id, alias, normalized_alias) VALUES (?, ?, ?)",
        [("sq", "Smith incline", "smith incline"), ("bp", "Smith incline", "smith incline")],
    )
    db.catalog_conn.commit()
    response = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("plan.csv", _csv([["1", "Day A", "1", "Smith incline", "3", "8", "2", "", "", "", "90", "", ""]]), "text/csv")},
    )
    assert response.status_code == 200, response.text
    row = response.json()["rows"][0]
    assert row["resolution"] == "ambiguous"
    assert row["exercise_id"] is None
    assert len(row["suggestions"]) == 2


def test_unsupported_amrap_is_kept_as_a_warning_and_more_than_500_rows_is_refused(api):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db)
    response = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("plan.csv", _csv([["1", "Day A", "1", "Squat", "3", "AMRAP", "2", "", "", "", "90", "", ""]]), "text/csv")},
    )
    assert response.status_code == 200, response.text
    row = response.json()["rows"][0]
    assert "reps: AMRAP" in row["notes"]
    assert any(warning["code"] == "program_import.reps_approximated.v1" for warning in row["warnings"])
    too_many = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={
            "file": (
                "plan.csv",
                _csv([["1", "Day A", str(index), "Squat", "3", "8", "2", "", "", "", "90", "", ""] for index in range(501)]),
                "text/csv",
            )
        },
    )
    assert too_many.status_code == 413


def test_upload_limits_and_assignment_gate(api, monkeypatch, tmp_path, scripted_chat_model):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db)
    _enable_program_import_ai(monkeypatch, tmp_path)
    freeform_file = ("own-layout.csv", b"Lift,Sets,Reps\nSquat,3,8", "text/csv")
    too_large = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("plan.csv", b"x" * (1024 * 1024 + 1), "text/csv")},
    )
    assert too_large.status_code == 413
    _, _, foreign_assignment_id = _assignment(client, db, prefix="foreign")
    foreign = client.post(
        f"/coach/assignments/{foreign_assignment_id}/program-import",
        headers=coach_headers,
        files={"file": freeform_file},
    )
    draft_action = client.post(
        f"/coach/assignments/{foreign_assignment_id}/program-draft/import",
        headers=coach_headers,
        json={
            "program_name": "plan",
            "rows": [{
                "source_row": 2,
                "day": 1,
                "order": 1,
                "exercise_name": "Squat",
                "exercise_id": "sq",
                "sets": 3,
                "reps_min": 8,
                "reps_max": 8,
                "target_rir": 2,
                "rest_seconds": 90,
            }],
        },
    )
    assert foreign.status_code == 403
    assert draft_action.status_code == 403
    assert foreign.json() == draft_action.json()
    unknown = client.post(
        "/coach/assignments/not-an-assignment/program-import",
        headers=coach_headers,
        files={"file": freeform_file},
    )
    assert unknown.status_code == 403
    assert foreign.json()["message_code"] == unknown.json()["message_code"] == "assignment.none_active.v1"
    assert client.post(
        f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers
    ).status_code == 200
    ended = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": freeform_file},
    )
    assert ended.status_code == 403
    assert ended.json()["message_code"] == "assignment.none_active.v1"
    assert scripted_chat_model.calls == []


def test_template_downloads_are_authenticated(api):
    client, db = api
    coach_headers, _, _ = _assignment(client, db)
    assert client.get("/coach/program-import/template.csv", headers=coach_headers).status_code == 200
    assert client.get("/coach/program-import/template.xlsx", headers=coach_headers).status_code == 200
    assert client.get("/coach/program-import/template.csv").status_code == 401


def test_effort_and_per_set_reps_are_approximated_with_original_text(api):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db)
    response = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("effort.csv", _csv([
            ["1", "Day A", "1", "Squat", "3", "8,8,6", "7-8", "", "", "", "90", "", ""],
            ["1", "Day A", "2", "Bench Press", "3", "8/8/6", "2-3", "", "", "", "90", "", ""],
            ["1", "Day A", "3", "Squat", "3", "8", "", "RPE 8", "", "", "90", "", ""],
            ["1", "Day A", "4", "Bench Press", "3", "8", "@8", "", "", "", "90", "", ""],
            ["1", "Day A", "5", "Squat", "3", "8", "hard", "", "", "", "90", "", ""],
            ["1", "Day A", "6", "Bench Press", "3", "3x8,6,4", "2", "", "", "", "90", "", ""],
            ["1", "Day A", "7", "Squat", "3", "8", "", "8", "", "", "90", "", ""],
            ["1", "Day A", "8", "Bench Press", "3", "8", "7.5", "", "", "", "90", "", ""],
            ["1", "Day A", "9", "Squat", "3", "8", "8", "", "", "", "90", "", ""],
        ]), "text/csv")},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert [row["target_rir"] for row in rows[:4]] == [5, 2.5, 2, 2]
    assert "reps: 8,8,6" in rows[0]["notes"]
    assert "effort: 7-8" in rows[0]["notes"]
    assert "reps: 8/8/6" in rows[1]["notes"]
    assert any(warning["code"] == "program_import.rpe_converted.v1" for warning in rows[2]["warnings"])
    assert any(warning["code"] == "program_import.effort_approximated.v1" for warning in rows[3]["warnings"])
    assert rows[4]["valid"] is False
    assert rows[4]["errors"][0]["code"] == "program_import.invalid_effort.v1"
    assert rows[5]["reps_min"] == 4
    assert rows[5]["reps_max"] == 8
    assert any(warning["code"] == "program_import.reps_approximated.v1" for warning in rows[5]["warnings"])
    assert rows[6]["valid"] is True
    assert rows[6]["target_rir"] == 2
    assert rows[7]["target_rir"] == 5
    assert any(warning["code"] == "program_import.effort_approximated.v1" for warning in rows[7]["warnings"])
    assert rows[8]["target_rir"] == 5
    assert any(warning["code"] == "program_import.effort_approximated.v1" for warning in rows[8]["warnings"])


def test_freeform_import_retries_malformed_reply_and_returns_week_review_without_player_data(
    api, monkeypatch, tmp_path, scripted_chat_model
):
    client, db = api
    coach_headers, player_headers, assignment_id = _assignment(client, db, prefix="freeform")
    profile_response = client.put(
        "/profile",
        headers=player_headers,
        json={"weekly_frequency": 4, "current_goal": "PRIVATE_PROFILE_MARKER"},
    )
    assert profile_response.status_code == 200
    with db.open_ledger("freeform-player") as player_ledger:
        player_ledger.log_workout_session(
            "private-import-session",
            "2026-10-08",
            "PRIVATE_SPLIT_MARKER",
            "2026-10-08T08:00:00+00:00",
            "2026-10-08T08:30:00+00:00",
            notes="PRIVATE_LEDGER_MARKER",
        )
    _enable_program_import_ai(monkeypatch, tmp_path)
    from service.model_limits import reset_model_limits

    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "1")
    reset_model_limits()
    scripted_chat_model.script(
        {"rows": "malformed"},
        {
            "rows": [
                {
                    "source_row": 2,
                    "week": "Week 1",
                    "day": 1,
                    "day_name": "يوم الدفع",
                    "order": 1,
                    "exercise": "Bench Press",
                    "sets": 3,
                    "reps_min": 8,
                    "reps_max": 8,
                    "reps_original": "8",
                    "rir": None,
                    "rpe": 8,
                    "rest_seconds": 90,
                    "tempo": None,
                    "notes": "ملاحظة أصلية",
                    "original_text": "Bench Press · 3 × 8 · RPE 8",
                    "approximation_markers": [],
                },
                {
                    "source_row": 3,
                    "week": "Week 1",
                    "day": 1,
                    "day_name": "يوم الدفع",
                    "order": 2,
                    "exercise": "Squat",
                    "sets": 0,
                    "reps_min": 8,
                    "reps_max": 8,
                    "reps_original": "8",
                    "rir": 2,
                    "rpe": None,
                    "rest_seconds": 90,
                    "tempo": None,
                    "notes": None,
                    "original_text": "Squat · 0 × 8",
                    "approximation_markers": [],
                },
            ],
            "layout": {
                "days": [{"day": 1, "name": "يوم الدفع"}],
                "weeks": ["Week 1", "Week 2"],
                "confidence": 0.98,
                "confirm_layout": False,
            },
        },
    )
    response = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={
            "file": (
                "freeform.csv",
                b"Exercise,Sets,Reps,Effort,Notes\nBench Press,3,8,RPE 8,\xd9\x85\xd9\x84\xd8\xa7\xd8\xad\xd8\xb8\xd8\xa9 \xd8\xa3\xd8\xb5\xd9\x84\xd9\x8a\xd8\xa9\nSquat,0,8,,",
                "text/csv",
            )
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["detected_weeks"] == ["Week 1", "Week 2"]
    assert result["selected_week"] == "Week 1"
    assert result["weeks_not_imported"] == ["Week 2"]
    assert result["confirm_layout"] is False
    assert result["freeform_available"] is True
    assert result["layout_days"] == [{"day": 1, "name": "يوم الدفع"}]
    assert result["layout_confidence"] == 0.98
    row = result["rows"][0]
    assert row["day_name"] == "يوم الدفع"
    assert row["target_rir"] == 2
    assert "ملاحظة أصلية" in row["notes"]
    assert any(warning["code"] == "program_import.rpe_converted.v1" for warning in row["warnings"])
    invalid_row = result["rows"][1]
    assert invalid_row["valid"] is False
    assert invalid_row["errors"][0]["code"] == "program_import.invalid_sets.v1"
    assert invalid_row["errors"][0]["column"] == "sets"
    model_payloads = [
        str(message.content)
        for call in scripted_chat_model.calls
        for message in call["messages"]
    ]
    assert any("Bench Press" in payload for payload in model_payloads)
    assert all("freeform-player" not in payload for payload in model_payloads)
    assert all("PRIVATE_PROFILE_MARKER" not in payload for payload in model_payloads)
    assert all("PRIVATE_LEDGER_MARKER" not in payload for payload in model_payloads)
    assert all("PRIVATE_SPLIT_MARKER" not in payload for payload in model_payloads)
    limited = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={
            "file": (
                "freeform.csv",
                b"Exercise,Sets,Reps\nBench Press,3,8",
                "text/csv",
            )
        },
    )
    reset_model_limits()
    assert limited.status_code == 429
    assert limited.json()["message_code"] == "ai_limit.request_rate.v1"


def test_program_import_gate_off_keeps_template_working_and_cell_cap_refuses_freeform(
    api, monkeypatch, tmp_path, scripted_chat_model
):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db, prefix="gate")
    monkeypatch.setenv("PROGRAM_IMPORT_AI_ENABLED", "false")
    monkeypatch.delenv("PROGRAM_IMPORT_AI_EVAL_REPORT", raising=False)
    template = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("plan.csv", _csv([["1", "Push", "1", "Squat", "3", "8", "2", "", "", "", "90", "", ""]]), "text/csv")},
    )
    assert template.status_code == 200, template.text

    disabled = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("own-layout.csv", b"Lift,Sets,Reps\nBench Press,3,8", "text/csv")},
    )
    assert disabled.status_code == 503
    assert disabled.json()["message_code"] == "program_import.freeform_disabled.v1"
    _enable_program_import_ai(monkeypatch, tmp_path, mode="mock")
    mock_refused = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("own-layout.csv", b"Lift,Sets,Reps\nBench Press,3,8", "text/csv")},
    )
    template_while_mocked = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("plan.csv", _csv([["1", "Push", "1", "Squat", "3", "8", "2", "", "", "", "90", "", ""]]), "text/csv")},
    )
    assert mock_refused.status_code == 503
    assert mock_refused.json()["message_code"] == "program_import.freeform_disabled.v1"
    assert template_while_mocked.status_code == 200, template_while_mocked.text
    assert template_while_mocked.json()["freeform_available"] is False
    assert scripted_chat_model.calls == []

    _enable_program_import_ai(monkeypatch, tmp_path)
    rows = [["Bench Press", "3", "8", "notes"] for _ in range(501)]
    freeform_csv = io.StringIO(newline="")
    writer = csv.writer(freeform_csv)
    writer.writerow(["Exercise", "Sets", "Reps", "Notes"])
    writer.writerows(rows)
    capped = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("large.csv", freeform_csv.getvalue().encode(), "text/csv")},
    )
    assert capped.status_code == 413
    assert capped.json()["message_code"] == "program_import.too_many_cells.v1"
    assert capped.json()["message_params"] == {"max_cells": 2000}
    assert scripted_chat_model.calls == []


def test_partial_template_header_uses_freeform_reader(api, monkeypatch, tmp_path, scripted_chat_model):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db, prefix="partial-template")
    _enable_program_import_ai(monkeypatch, tmp_path)
    scripted_chat_model.script(
        {
            "rows": [{
                "source_row": 602,
                "week": "Week 1",
                "day": 1,
                "day_name": "Push",
                "order": 1,
                "exercise": "Bench Press",
                "sets": 3,
                "reps_min": 8,
                "reps_max": 8,
                "reps_original": "8",
                "rir": None,
                "rpe": 8,
                "rest_seconds": 90,
                "tempo": None,
                "notes": None,
                "original_text": "Bench Press,3,8 @8",
                "approximation_markers": [],
            }],
            "layout": {
                "days": [{"day": 1, "name": "Push"}],
                "weeks": ["Week 1"],
                "confidence": 0.98,
                "confirm_layout": False,
            },
        }
    )

    response = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("partial.csv", b"\n" * 600 + b"day,exercise,sets,Reps x RPE\n1,Bench Press,3,8 @8", "text/csv")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["import_mode"] == "freeform"
    assert response.json()["rows"][0]["target_rir"] == 2
    assert response.json()["freeform_available"] is True


def test_malformed_freeform_reply_retries_then_returns_a_clean_failure(
    api, monkeypatch, tmp_path, scripted_chat_model
):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db, prefix="bad-model")
    _enable_program_import_ai(monkeypatch, tmp_path)
    scripted_chat_model.script({"rows": "bad"}, {"rows": "still bad"})

    response = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("own-layout.csv", b"Lift,Sets,Reps\nBench Press,3,8", "text/csv")},
    )

    assert response.status_code == 422
    assert response.json()["message_code"] == "program_import.interpretation_failed.v1"
    assert "malformed" not in response.text.lower()


def test_freeform_import_returns_all_weeks_and_defaults_to_week_one(
    api, monkeypatch, tmp_path, scripted_chat_model
):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db, prefix="week-choice")
    _enable_program_import_ai(monkeypatch, tmp_path)
    reply = {
        "rows": [
            {
                "source_row": 2,
                "week": "Week 1",
                "day": 1,
                "day_name": "Push",
                "order": 1,
                "exercise": "Bench Press",
                "sets": 3,
                "reps_min": 8,
                "reps_max": 8,
                "reps_original": "8",
                "rir": 2,
                "rpe": None,
                "rest_seconds": 90,
                "tempo": None,
                "notes": None,
                "original_text": "Bench Press, 3, 8",
                "approximation_markers": [],
            },
            {
                "source_row": 3,
                "week": "Week 2",
                "day": 1,
                "day_name": "Push",
                "order": 1,
                "exercise": "Squat",
                "sets": 3,
                "reps_min": 8,
                "reps_max": 8,
                "reps_original": "8",
                "rir": 2,
                "rpe": None,
                "rest_seconds": 90,
                "tempo": None,
                "notes": None,
                "original_text": "Squat, 3, 8",
                "approximation_markers": [],
            },
        ],
        "layout": {
            "days": [{"day": 1, "name": "Push"}],
            "weeks": ["Week 1", "Week 2"],
            "confidence": 0.99,
            "confirm_layout": False,
        },
    }
    scripted_chat_model.script(reply)
    upload = {
        "file": (
            "own-layout.csv",
            b"Exercise,Sets,Reps\nBench Press,3,8\nSquat,3,8",
            "text/csv",
        )
    }

    default_week = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files=upload,
    )
    assert default_week.status_code == 200, default_week.text
    assert default_week.json()["selected_week"] == "Week 1"
    assert [row["exercise_name"] for row in default_week.json()["rows"]] == ["Bench Press", "Squat"]
    assert [row["week"] for row in default_week.json()["rows"]] == ["Week 1", "Week 2"]
    assert [row["exercise_name"] for row in default_week.json()["rows_by_week"]["Week 1"]] == ["Bench Press"]
    assert [row["exercise_name"] for row in default_week.json()["rows_by_week"]["Week 2"]] == ["Squat"]
    assert default_week.json()["weeks_not_imported"] == ["Week 2"]


def test_freeform_model_suggestion_is_confirm_only_and_uses_library_candidates(
    api, monkeypatch, tmp_path, scripted_chat_model
):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db, prefix="suggestion")
    _enable_program_import_ai(monkeypatch, tmp_path)
    scripted_chat_model.script(
        {
            "rows": [
                {
                    "source_row": 2,
                    "week": None,
                    "day": 1,
                    "day_name": "Push",
                    "order": 1,
                    "exercise": "بنش برس",
                    "exercise_search_terms": ["bench press"],
                    "sets": 3,
                    "reps_min": 8,
                    "reps_max": 8,
                    "reps_original": "8",
                    "rir": 2,
                    "rpe": None,
                    "rest_seconds": 90,
                    "tempo": None,
                    "notes": None,
                    "original_text": "بنش برس 3 × 8",
                    "approximation_markers": [],
                }
            ],
            "layout": {
                "days": [{"day": 1, "name": "Push"}],
                "weeks": [],
                "confidence": 0.95,
                "confirm_layout": False,
            },
        },
        {"suggestions": [{"exercise_name": "بنش برس", "exercise_ids": ["bp"]}]},
    )

    response = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("own-layout.csv", b"Lift,Sets,Reps\n\xd8\xa8\xd9\x86\xd8\xb4 \xd8\xa8\xd8\xb1\xd8\xb3,3,8", "text/csv")},
    )

    assert response.status_code == 200, response.text
    row = response.json()["rows"][0]
    assert row["exercise_id"] is None
    assert row["exercise_name"] == "بنش برس"
    assert row["suggestions"] == [{"exercise_id": "bp", "name": "Bench Press"}]


def test_xlsx_date_reps_and_downloaded_template_sheet_behavior(api):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db)
    downloaded = client.get("/coach/program-import/template.xlsx", headers=coach_headers)
    assert downloaded.status_code == 200
    template = load_workbook(io.BytesIO(downloaded.content), data_only=True)
    assert template["Program"]["F1"].number_format == "@"
    assert template["Program"]["G1"].number_format == "@"
    assert template["Program"]["H1"].number_format == "@"
    assert template["Program"]["F500"].number_format == "@"
    template.close()
    upload_template = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("template.xlsx", downloaded.content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert upload_template.status_code == 200, upload_template.text
    assert upload_template.json()["requires_tab_choice"] is False
    assert upload_template.json()["selected_tab"] == "Program"
    explicit_example = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        data={"sheet": "Example"},
        files={"file": ("template.xlsx", downloaded.content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert explicit_example.status_code == 200, explicit_example.text
    assert explicit_example.json()["selected_tab"] == "Example"
    assert len(explicit_example.json()["rows"]) == 1

    rpe_without_reps = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={
            "file": (
                "missing-reps.csv",
                b"day,exercise,sets,rpe\n1,Squat,3,8\n",
                "text/csv",
            )
        },
    )
    assert rpe_without_reps.status_code == 503
    assert rpe_without_reps.json()["message_code"] == "program_import.freeform_disabled.v1"

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Program"
    sheet.append(HEADERS)
    sheet.append([1, "Day", 1, "Squat", 3, dt.date(2026, 10, 8), 2, "", "", "", 90, "", ""])
    payload = io.BytesIO()
    workbook.save(payload)
    workbook.close()
    date_response = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("date.xlsx", payload.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert date_response.status_code == 200, date_response.text
    error = date_response.json()["rows"][0]["errors"][0]
    assert error["code"] == "program_import.reps_as_date.v1"
    assert error["column"] == "reps"


def test_xlsx_file_and_row_limits_and_corrupt_workbooks_are_clean_errors(api):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db)
    too_large = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("large.xlsx", b"x" * (1024 * 1024 + 1), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert too_large.status_code == 413
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    for index in range(501):
        sheet.append([1, "Day", index + 1, "Squat", 3, 8, 2, "", "", "", 90, "", ""])
    payload = io.BytesIO()
    workbook.save(payload)
    workbook.close()
    too_many = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("many.xlsx", payload.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert too_many.status_code == 413
    malformed_zip = io.BytesIO()
    with zipfile.ZipFile(malformed_zip, "w") as archive:
        archive.writestr("[Content_Types].xml", "<broken")
    corrupt = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("broken.xlsx", malformed_zip.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert corrupt.status_code == 400
    assert corrupt.json()["message_code"] == "program_import.file_invalid.v1"

    many_tabs = Workbook()
    many_tabs.active.title = "Program"
    for index in range(20):
        many_tabs.create_sheet(f"Sheet {index}")
    many_tab_bytes = io.BytesIO()
    many_tabs.save(many_tab_bytes)
    many_tabs.close()
    too_many_tabs = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("many-tabs.xlsx", many_tab_bytes.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert too_many_tabs.status_code == 413
    assert too_many_tabs.json()["message_code"] == "program_import.too_many_tabs.v1"


def test_invalid_day_does_not_conflict_or_rename_other_rows(api):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db)
    response = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("days.csv", _csv([
            ["0", "Wrong", "1", "Squat", "3", "8", "2", "", "", "", "90", "", ""],
            ["1", "", "1", "Bench Press", "3", "8", "2", "", "", "", "90", "", ""],
            ["1", "Push", "2", "Squat", "3", "8", "2", "", "", "", "90", "", ""],
        ]), "text/csv")},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert rows[0]["valid"] is False
    assert all(error["code"] != "program_import.conflicting_day_name.v1" for error in rows[0]["errors"])
    assert rows[1]["valid"] is True
    assert rows[1]["day_name"] == "Push"


def test_invalid_day_rows_do_not_count_toward_a_real_day_limit(api):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db)
    rows = [
        ["1", "Push", str(index), "Squat", "3", "8", "2", "", "", "", "90", "", ""]
        for index in range(1, 15)
    ]
    rows.append(["bad", "Push", "15", "Squat", "3", "8", "2", "", "", "", "90", "", ""])
    response = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": ("day-limit.csv", _csv(rows), "text/csv")},
    )
    assert response.status_code == 200, response.text
    imported = response.json()["rows"]
    assert all(
        error["code"] != "program_import.too_many_exercises.v1"
        for row in imported
        for error in row["errors"]
    )
    assert imported[-1]["valid"] is False
