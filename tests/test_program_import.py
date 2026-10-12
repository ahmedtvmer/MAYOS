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
    # A developer .env may enable free-form import; tests opt in explicitly.
    monkeypatch.delenv("PROGRAM_IMPORT_AI_ENABLED", raising=False)
    monkeypatch.delenv("PROGRAM_IMPORT_AI_EVAL_REPORT", raising=False)
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
    assert "[]" not in rows[2]["notes"]
    assert "effort: RPE 8" in rows[2]["notes"]
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


def test_freeform_source_cells_recover_day_names_and_canonical_week_labels():
    from service import program_import
    from service.program_import_ai import ProgramImportReply

    source_grid = {
        "sheet": "CSV",
        "cells": program_import._compact_cell_grid([
            ["Day", "Session", "Exercise", "Week 1 sets", "Week 1 reps", "Week 1 effort", "Week 2 sets", "Week 2 reps", "Week 2 effort"],
            [1, "Lower A", "Squat", 3, 8, "2 RIR", 4, 6, "@8"],
            [2, "Push A", "Bench Press", 3, 10, "2 RIR", 4, 8, "@8"],
        ]),
    }
    rows = []
    for source_row, day, day_name, exercise in (
        (2, 1, "Day 1", "Squat"),
        (2, 1, None, "Squat"),
        (3, "Push A", "Day 2", "Bench Press"),
        (3, "Push A", "Day 2", "Bench Press"),
    ):
        week = "1" if len(rows) % 2 == 0 else "2"
        rows.append({
            "source_row": source_row, "week": week, "day": day, "day_name": day_name,
            "exercise": exercise, "sets": 3, "reps_min": 8, "reps_max": 8,
            "rir": 2, "rpe": None, "original_text": exercise,
        })
    reply = ProgramImportReply.model_validate({
        "rows": rows,
        "layout": {
            "days": [{"day": 1, "name": "Day 1"}, {"day": 2, "name": "Day 2"}],
            "weeks": ["1", "2"], "confidence": 0.99,
        },
    })

    source = program_import._freeform_reader_output(reply, ["CSV"], "CSV", source_grid)
    assert source.detected_weeks == ["Week 1", "Week 2"]
    assert [row.week for row in source.rows] == ["Week 1", "Week 2"] * 2
    assert [(row.day, row.day_name) for row in source.rows] == [
        (1, "Lower A"), (1, "Lower A"), (2, "Push A"), (2, "Push A"),
    ]
    normalized = [program_import._normalise_row(row, {}) for row in source.rows]
    assert any(warning["code"] == "program_import.rpe_converted.v1" for warning in normalized[1]["warnings"])


def test_single_week_title_does_not_turn_day_numbers_into_week_selection():
    from service import program_import
    from service.program_import_ai import ProgramImportReply

    source_grid = {
        "sheet": "CSV",
        "cells": program_import._compact_cell_grid([
            ["Week A / primary work"],
            ["Day", "Session", "Exercise", "Sets", "Reps", "Effort"],
            [1, "Lower A", "Squat", 3, 8, "2 RIR"],
            [2, "Push A", "Bench Press", 3, 8, "2 RIR"],
            [3, "Pull A", "Row", 3, 8, "2 RIR"],
        ]),
    }
    rows = [
        {
            "source_row": row_number, "week": str(day), "day": day,
            "day_name": day_name, "exercise": exercise, "sets": 3,
            "reps_min": 8, "reps_max": 8, "rir": 2, "original_text": exercise,
        }
        for row_number, day, day_name, exercise in (
            (3, 1, "Lower A", "Squat"),
            (4, 2, "Push A", "Bench Press"),
            (5, 3, "Pull A", "Row"),
        )
    ]
    reply = ProgramImportReply.model_validate({
        "rows": rows,
        "layout": {
            "days": [{"day": 1, "name": "Lower A"}, {"day": 2, "name": "Push A"}, {"day": 3, "name": "Pull A"}],
            "weeks": ["1", "2", "3"], "confidence": 0.99,
        },
    })

    source = program_import._freeform_reader_output(reply, ["CSV"], "CSV", source_grid)
    assert source.detected_weeks == []
    assert all(row.week is None for row in source.rows)


# #400 found note cells being misread as day/week layout titles.
def test_grid_titles_ignore_day_notes_and_preserve_model_day_names():
    from service import program_import
    from service.program_import_ai import ProgramImportReply

    source_grid = {
        "sheet": "CSV",
        "cells": program_import._compact_cell_grid([
            ["Day", "Session", "Exercise", "Sets", "Reps", "Notes"],
            [1, "Sheet Push", "Bench Press", 3, 8, ""],
            ["Day 9 - deload", "", "", "", "", ""],
            [2, "Pull", "Squat", 3, 8, ""],
        ]),
    }
    reply = ProgramImportReply.model_validate({
        "rows": [
            {
                "source_row": 2, "day": 1, "day_name": "Model Push", "exercise": "Bench Press",
                "sets": 3, "reps_min": 8, "reps_max": 8, "original_text": "Bench Press",
            },
            {
                "source_row": 4, "day": 2, "day_name": "Pull", "exercise": "Squat",
                "sets": 3, "reps_min": 8, "reps_max": 8, "original_text": "Squat",
            },
        ],
        "layout": {
            "days": [{"day": 1, "name": "Model Push"}, {"day": 2, "name": "Pull"}],
            "weeks": [], "confidence": 0.99,
        },
    })

    source = program_import._freeform_reader_output(reply, ["CSV"], "CSV", source_grid)

    assert [(row.day, row.day_name) for row in source.rows] == [(1, "Model Push"), (2, "Pull")]
    context = program_import._freeform_grid_context(source_grid, reply.layout.days)
    assert 9 not in context.day_names


def test_week_note_next_to_exercise_data_does_not_add_a_week():
    from service import program_import
    from service.program_import_ai import ProgramImportReply

    source_grid = {
        "sheet": "CSV",
        "cells": program_import._compact_cell_grid([
            ["Week 3 - accumulation"],
            ["Day", "Session", "Exercise", "Sets", "Reps", "Notes"],
            [1, "Push", "Bench Press", 3, 8, "Wk 4 - test 1RM"],
            [2, "Pull", "Squat", 3, 8, ""],
        ]),
    }
    reply = ProgramImportReply.model_validate({
        "rows": [
            {
                "source_row": source_row, "week": "Week 3", "day": day, "day_name": name,
                "exercise": exercise, "sets": 3, "reps_min": 8, "reps_max": 8,
                "original_text": exercise,
            }
            for source_row, day, name, exercise in (
                (3, 1, "Push", "Bench Press"), (4, 2, "Pull", "Squat"),
            )
        ],
        "layout": {
            "days": [{"day": 1, "name": "Push"}, {"day": 2, "name": "Pull"}],
            "weeks": ["Week 3"], "confidence": 0.99,
        },
    })

    source = program_import._freeform_reader_output(reply, ["CSV"], "CSV", source_grid)

    assert source.detected_weeks == []
    assert source.selected_week is None
    assert source.weeks_not_imported == []
    assert all(row.week is None for row in source.rows)


@pytest.mark.parametrize("model_weeks", [["Week 3"], []])
def test_week_note_between_exercise_rows_does_not_override_model_layout(model_weeks):
    from service import program_import
    from service.program_import_ai import ProgramImportReply

    source_grid = {
        "sheet": "Week 3",
        "cells": program_import._compact_cell_grid([
            ["Day", "Session", "Exercise", "Sets", "Reps", "Notes"],
            [1, "Push", "Bench Press", 3, 8, ""],
            ["", "", "", "", "", "Wk 4 - test 1RM"],
            [2, "Pull", "Squat", 3, 8, ""],
        ]),
    }
    reply = ProgramImportReply.model_validate({
        "rows": [
            {
                "source_row": source_row,
                "week": model_weeks[0] if model_weeks else None,
                "day": day,
                "day_name": name, "exercise": exercise, "sets": 3,
                "reps_min": 8, "reps_max": 8, "original_text": exercise,
            }
            for source_row, day, name, exercise in (
                (2, 1, "Push", "Bench Press"), (4, 2, "Pull", "Squat"),
            )
        ],
        "layout": {
            "days": [{"day": 1, "name": "Push"}, {"day": 2, "name": "Pull"}],
            "weeks": model_weeks, "confidence": 0.99,
        },
    })

    source = program_import._freeform_reader_output(reply, ["Week 3"], "Week 3", source_grid)

    assert source.detected_weeks == []
    assert source.selected_week is None
    assert source.weeks_not_imported == []


def test_day_title_in_later_exercise_column_cannot_rename_generic_model_day():
    from service import program_import
    from service.program_import_ai import ProgramImportReply

    source_grid = {
        "sheet": "CSV",
        "cells": program_import._compact_cell_grid([
            ["Day", "Session", "Exercise", "Sets", "Reps"],
            [1, "Push", "Bench Press", 3, 8],
            ["", "", "", "", "", "Day", "Session", "Movement", "Sets", "Reps"],
            ["", "", "", "", "", "", "", "Day 2 - optional cardio"],
            ["", "", "", "", "", 2, "Day 2", "Squat", 3, 8],
        ]),
    }
    reply = ProgramImportReply.model_validate({
        "rows": [
            {
                "source_row": 2, "day": 1, "day_name": "Push", "exercise": "Bench Press",
                "sets": 3, "reps_min": 8, "reps_max": 8, "original_text": "Bench Press",
            },
            {
                "source_row": 5, "day": 2, "day_name": "Day 2", "exercise": "Squat",
                "sets": 3, "reps_min": 8, "reps_max": 8, "original_text": "Squat",
            },
        ],
        "layout": {
            "days": [{"day": 1, "name": "Push"}, {"day": 2, "name": "Day 2"}],
            "weeks": [], "confidence": 0.99,
        },
    })

    source = program_import._freeform_reader_output(reply, ["CSV"], "CSV", source_grid)
    context = program_import._freeform_grid_context(source_grid, reply.layout.days)

    assert context.day_names == {1: "Push"}
    assert all(row.day_name != "optional cardio" for row in source.rows)
    assert program_import._has_unplaced_exercise_rows(context, reply.rows[:1]) is True


def test_layout_day_rename_keeps_column_derived_name_to_number_mapping():
    from service import program_import
    from service.program_import_ai import ProgramImportReply

    source_grid = {
        "cells": program_import._compact_cell_grid([
            ["Day", "Session", "Exercise", "Sets", "Reps"],
            [1, "Column Push", "Bench Press", 3, 8],
        ])
    }
    reply = ProgramImportReply.model_validate({
        "rows": [{
            "source_row": 2, "day": 1, "day_name": "Model Push", "exercise": "Bench Press",
            "sets": 3, "reps_min": 8, "reps_max": 8, "original_text": "Bench Press",
        }],
        "layout": {
            "days": [{"day": 1, "name": "Model Push"}],
            "weeks": [], "confidence": 0.99,
        },
    })

    context = program_import._freeform_grid_context(source_grid, reply.layout.days)

    assert context.day_names[1] == "Model Push"
    assert context.day_numbers["column push"] == 1
    assert context.day_numbers["model push"] == 1


@pytest.mark.parametrize("note_column", [0, 5])
def test_week_note_below_table_does_not_create_a_week(note_column):
    from service import program_import
    from service.program_import_ai import ProgramImportReply

    rows = [
        ["Week 3 - accumulation"],
        ["Day", "Session", "Exercise", "Sets", "Reps", "Notes"],
        [1, "Push", "Bench Press", 3, 8, ""],
        [2, "Pull", "Squat", 3, 8, ""],
    ]
    note = [""] * 6
    note[note_column] = "Wk 4 - test 1RM"
    rows.append(note)
    source_grid = {"sheet": "Week 3", "cells": program_import._compact_cell_grid(rows)}
    reply = ProgramImportReply.model_validate({
        "rows": [
            {
                "source_row": source_row, "week": "Week 3", "day": day,
                "day_name": name, "exercise": exercise, "sets": 3,
                "reps_min": 8, "reps_max": 8, "original_text": exercise,
            }
            for source_row, day, name, exercise in (
                (3, 1, "Push", "Bench Press"), (4, 2, "Pull", "Squat"),
            )
        ],
        "layout": {
            "days": [{"day": 1, "name": "Push"}, {"day": 2, "name": "Pull"}],
            "weeks": ["Week 3"], "confidence": 0.99,
        },
    })

    source = program_import._freeform_reader_output(reply, ["Week 3"], "Week 3", source_grid)

    assert source.detected_weeks == []
    assert source.selected_week is None
    assert source.weeks_not_imported == []
    assert all(row.week is None for row in source.rows)


@pytest.mark.parametrize(
    ("title", "model_week"),
    [
        ("Week 3 — Coach shorthand retained from notebook", "Week 3"),
        ("Week 3", "Week 3"),
        ("Wk 2 heavy", "Week 2"),
        ("الأسبوع 3", "Week 3"),
    ],
)
def test_single_week_sheet_title_does_not_tag_rows_with_that_week(title, model_week):
    from service import program_import
    from service.program_import_ai import ProgramImportReply

    source_grid = {
        "sheet": "CSV",
        "cells": program_import._compact_cell_grid([
            [title],
            ["Day", "Session", "Exercise", "Sets", "Reps"],
            [1, "Lower A", "Back Squat", 3, 8],
            [2, "Push A", "Bench Press", 3, 8],
        ]),
    }
    reply = ProgramImportReply.model_validate({
        "rows": [
            {
                "source_row": source_row, "week": model_week, "day": day,
                "day_name": day_name, "exercise": exercise, "sets": 3,
                "reps_min": 8, "reps_max": 8, "original_text": exercise,
            }
            for source_row, day, day_name, exercise in (
                (3, 1, "Lower A", "Back Squat"), (4, 2, "Push A", "Bench Press"),
            )
        ],
        "layout": {
            "days": [{"day": 1, "name": "Lower A"}, {"day": 2, "name": "Push A"}],
            "weeks": [model_week], "confidence": 0.99,
        },
    })

    source = program_import._freeform_reader_output(reply, ["CSV"], "CSV", source_grid)
    context = program_import._freeform_grid_context(source_grid, reply.layout.days)

    assert context.week_labels == [model_week]
    assert source.detected_weeks == []
    assert source.selected_week is None
    assert source.weeks_not_imported == []
    assert all(row.week is None for row in source.rows)


def test_unlabeled_week_blocks_expand_model_rows_from_source_values():
    from service import program_import
    from service.program_import_ai import ProgramImportReply

    fixture_path = Path(__file__).parent / "eval/datasets/program_import/21_unlabeled_week_blocks.json"
    case = json.loads(fixture_path.read_text(encoding="utf-8"))
    tab_name, fixture_rows = next(iter(case["sheets"].items()))
    source_grid = {
        "sheet": tab_name,
        "cells": program_import._compact_cell_grid(fixture_rows),
    }
    first_week_rows = [row for row in case["expected_rows"] if row["week"] == "Week 1"]
    day_orders: dict[int, int] = {}
    model_rows = []
    for expected in first_week_rows:
        day = expected["day"]
        order = day_orders.get(day, 0) + 1
        day_orders[day] = order
        model_rows.append({
            "source_row": expected["source_row"], "week": None, "day": day,
            "day_name": expected["day_name"], "order": order,
            "exercise": expected["input_exercise_name"], "sets": expected["sets"],
            "reps_min": expected["reps_min"], "reps_max": expected["reps_max"],
            "rir": expected["rir"], "rpe": expected["rpe"],
            "original_text": expected["original_text"],
        })
    reply = ProgramImportReply.model_validate({
        "rows": model_rows,
        "layout": {
            "days": [{"day": day, "name": name} for day, name in (
                (1, "Lower A"), (2, "Push A"), (3, "Pull A"),
            )],
            "weeks": [], "confidence": 0.99,
        },
    })

    source = program_import._freeform_reader_output(reply, [tab_name], tab_name, source_grid)
    normalized = [program_import._normalise_row(row, {}) for row in source.rows]

    assert source.detected_weeks == ["Week 1", "Week 2"]
    assert source.confirm_layout is True
    assert [
        (row.source_row, row.week, int(row.sets), int(row.reps_min))
        for row in source.rows
    ] == [
        (row["source_row"], row["week"], row["sets"], row["reps_min"])
        for row in case["expected_rows"]
    ]
    assert not any(
        error["code"] == "program_import.invalid_order.v1"
        for row in normalized
        for error in row["errors"]
    )
    assert [row["target_rir"] for row in normalized] == [
        float(row["rir"]) for row in case["expected_rows"]
    ]


@pytest.mark.parametrize(
    ("order_base", "order_step", "expected_step"),
    [(0, 1, 1), (1, 1, 1), (1, 2, 2)],
    ids=["zero-based-renumbered", "one-based-kept", "gapped-in-range-kept"],
)
def test_issue_400_unlabeled_week_blocks_normalize_orders_and_preserve_notes(
    api, monkeypatch, tmp_path, scripted_chat_model, order_base, order_step, expected_step
):
    client, db = api
    coach_headers, _, assignment_id = _assignment(client, db, prefix="week-order")

    fixture_path = (
        Path(__file__).parent
        / "eval/datasets/program_import/21_unlabeled_week_blocks.json"
    )
    case = json.loads(fixture_path.read_text(encoding="utf-8"))
    tab_name, fixture_rows = next(iter(case["sheets"].items()))
    expected_week_one = [row for row in case["expected_rows"] if row["week"] == "Week 1"]
    exercises = {
        (row["expected_exercise_id"], row["exercise_name"])
        for row in expected_week_one
    }
    db.catalog_conn.executemany(
        "INSERT INTO exercises (id, name, body_part, target_muscle, equipment) "
        "VALUES (?, ?, 'Other', 'Other', 'barbell')",
        sorted(exercises),
    )
    db.catalog_conn.commit()
    _enable_program_import_ai(monkeypatch, tmp_path)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = tab_name
    for row in fixture_rows:
        sheet.append(row)
    workbook_bytes = io.BytesIO()
    workbook.save(workbook_bytes)
    workbook.close()

    def model_reply():
        day_orders = {}
        rows = []
        for expected in expected_week_one:
            day = expected["day"]
            order = day_orders[day] + order_step if day in day_orders else order_base
            day_orders[day] = order
            rows.append({
                "source_row": expected["source_row"],
                "week": "",
                "day": day,
                "day_name": expected["day_name"],
                "order": order,
                "exercise": expected["input_exercise_name"],
                "sets": expected["sets"],
                "reps_min": expected["reps_min"],
                "reps_max": expected["reps_max"],
                "rir": expected["rir"],
                "rpe": expected["rpe"],
                "notes": expected["notes"],
                "original_text": expected["original_text"],
            })
        return {
            "rows": rows,
            "layout": {
                "days": [
                    {"day": 1, "name": "Lower A"},
                    {"day": 2, "name": "Push A"},
                    {"day": 3, "name": "Pull A"},
                ],
                "weeks": [],
                "confidence": 0.99,
                "confirm_layout": True,
            },
        }

    scripted_chat_model.script(model_reply())

    response = client.post(
        f"/coach/assignments/{assignment_id}/program-import",
        headers=coach_headers,
        files={"file": (
            "blocks.xlsx",
            workbook_bytes.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["detected_weeks"] == ["Week 1", "Week 2"]
    assert result["selected_week"] == "Week 1"
    assert result["confirm_layout"] is True
    assert len(result["rows"]) == 24
    assert {row["week"] for row in result["rows"]} == {"Week 1", "Week 2"}
    assert all(row["valid"] for row in result["rows"])
    assert not any("[]" in (row["notes"] or "") for row in result["rows"])

    expected_notes = {row["source_row"]: row["notes"] for row in expected_week_one}
    grouped_orders = {}
    for row in result["rows"]:
        grouped_orders.setdefault((row["week"], row["day"]), []).append(
            (row["source_row"], row["order"])
        )
        note = expected_notes[row["source_row"]]
        assert row["notes"] == note
    for rows in grouped_orders.values():
        ordered = sorted(rows)
        assert [order for _source_row, order in ordered] == list(
            range(1, expected_step * len(ordered) + 1, expected_step)
        )


def test_implicit_week_expansion_preserves_model_values_and_normalizes_missing_source_values():
    from service import program_import
    from service.program_import_ai import ProgramImportReply

    source_grid = {
        "sheet": "CSV",
        "cells": program_import._compact_cell_grid([
            ["Day", "Session", "Exercise", "Sets", "Reps", "Effort", "Sets", "Reps", "Effort"],
            [1, "Push", "Bench Press", 5, 7, "3 RIR", 4, "8-10", "2 RIR"],
        ]),
    }
    reply = ProgramImportReply.model_validate({
        "rows": [{
            "source_row": 2, "week": None, "day": 1, "day_name": "Push",
            "exercise": "Bench Press", "sets": 3, "reps_min": 6, "reps_max": 6,
            "rir": 4, "original_text": "Bench Press",
        }],
        "layout": {
            "days": [{"day": 1, "name": "Push"}], "weeks": [], "confidence": 0.99,
        },
    })

    source = program_import._freeform_reader_output(reply, ["CSV"], "CSV", source_grid)
    first_week, second_week = source.rows
    normalized_second_week = program_import._normalise_row(second_week, {})

    assert (first_week.week, first_week.sets, first_week.reps_min, first_week.reps_max, first_week.rir) == (
        "Week 1", 3, 6, 6, 4,
    )
    assert (
        second_week.week, second_week.sets, second_week.reps_min,
        second_week.reps_max, normalized_second_week["target_rir"],
    ) == ("Week 2", 4, 8, 10, 2)


def test_two_distinct_grid_and_model_week_labels_are_reported():
    from service import program_import
    from service.program_import_ai import ProgramImportReply

    source_grid = {
        "sheet": "CSV",
        "cells": program_import._compact_cell_grid([
            ["Week 3"],
            ["Day", "Session", "Exercise", "Sets", "Reps"],
            [1, "Push", "Bench Press", 3, 8],
            ["Week 4"],
            [2, "Pull", "Squat", 3, 8],
        ]),
    }
    reply = ProgramImportReply.model_validate({
        "rows": [{
            "source_row": 3, "week": "Week 3", "day": 1, "day_name": "Push",
            "exercise": "Bench Press", "sets": 3, "reps_min": 8, "reps_max": 8,
            "original_text": "Bench Press",
        }],
        "layout": {
            "days": [{"day": 1, "name": "Push"}],
            "weeks": ["Week 3", "Week 4"], "confidence": 0.99,
        },
    })

    context = program_import._freeform_grid_context(source_grid, reply.layout.days)
    source = program_import._freeform_reader_output(reply, ["CSV"], "CSV", source_grid)

    assert context.week_labels == ["Week 3"]
    assert source.detected_weeks == ["Week 3", "Week 4"]
    assert source.selected_week == "Week 3"
    assert source.weeks_not_imported == ["Week 4"]


def test_stacked_day_title_rows_preserve_names_without_day_column():
    from service import program_import
    from service.program_import_ai import ProgramImportReply

    source_grid = {
        "sheet": "CSV",
        "cells": program_import._compact_cell_grid([
            ["Day 1 - Upper"],
            ["Exercise", "Sets", "Reps"],
            ["Bench Press", 3, 8],
            ["Day 2 - Lower"],
            ["Squat", 3, 8],
        ]),
    }
    reply = ProgramImportReply.model_validate({
        "rows": [
            {
                "source_row": 3, "day": 1, "day_name": "Day 1", "exercise": "Bench Press",
                "sets": 3, "reps_min": 8, "reps_max": 8, "original_text": "Bench Press",
            },
            {
                "source_row": 5, "day": 2, "day_name": "Day 2", "exercise": "Squat",
                "sets": 3, "reps_min": 8, "reps_max": 8, "original_text": "Squat",
            },
        ],
        "layout": {
            "days": [{"day": 1, "name": "Day 1"}, {"day": 2, "name": "Day 2"}],
            "weeks": [], "confidence": 0.99,
        },
    })

    source = program_import._freeform_reader_output(reply, ["CSV"], "CSV", source_grid)

    assert [(row.day, row.day_name) for row in source.rows] == [(1, "Upper"), (2, "Lower")]


def test_single_implicit_day_without_day_column_does_not_need_confirmation():
    from service import program_import
    from types import SimpleNamespace

    grid = {
        "cells": program_import._compact_cell_grid([
            ["Exercise", "Sets", "Reps"],
            ["Bench Press", 3, 8],
            ["Squat", 3, 8],
        ])
    }
    context = program_import._freeform_grid_context(grid, [])
    rows = [
        SimpleNamespace(source_row=2, day=None, day_name=None),
        SimpleNamespace(source_row=3, day=None, day_name=None),
    ]

    assert context.header_row is None
    assert context.columns == {}
    assert program_import._needs_layout_confirmation(context, rows) is False


def test_multiple_day_titles_without_axis_need_confirmation_when_unplaced():
    from service import program_import
    from types import SimpleNamespace

    grid = {
        "cells": program_import._compact_cell_grid([
            ["Day 1 - Upper"],
            ["Exercise", "Sets", "Reps"],
            ["Bench Press", 3, 8],
            ["Day 2 - Lower"],
            ["Squat", 3, 8],
        ])
    }
    context = program_import._freeform_grid_context(grid, [])
    rows = [
        SimpleNamespace(source_row=3, day=None, day_name=None),
        SimpleNamespace(source_row=5, day=None, day_name=None),
    ]

    assert program_import._needs_layout_confirmation(context, rows) is True


@pytest.mark.parametrize(
    ("candidate_exercise", "candidate_reps"),
    [("Warm-up: Band Pull Apart", 10), ("Bench Press", "AMRAP")],
)
def test_reported_or_rejected_candidate_row_does_not_need_confirmation(
    candidate_exercise, candidate_reps
):
    from service import program_import
    from types import SimpleNamespace

    grid = {
        "cells": program_import._compact_cell_grid([
            ["Day", "Exercise", "Sets", "Reps", "Notes"],
            [1, candidate_exercise, 1, candidate_reps, "reported as a notice"],
        ])
    }
    context = program_import._freeform_grid_context(grid, [])
    reported_row = SimpleNamespace(source_row=2, day=1, day_name="Day 1", exercise=None)

    assert program_import._has_unplaced_exercise_rows(context, [reported_row]) is False


def test_unreported_exercise_row_needs_confirmation():
    from service import program_import

    grid = {
        "cells": program_import._compact_cell_grid([
            ["Day", "Exercise", "Sets", "Reps"],
            [1, "Bench Press", 3, 8],
        ])
    }
    context = program_import._freeform_grid_context(grid, [])

    assert program_import._has_unplaced_exercise_rows(context, []) is True


def test_clear_recognized_layout_ignores_model_confirmation_hint_and_low_confidence():
    from service import program_import
    from types import SimpleNamespace

    grid = {
        "cells": program_import._compact_cell_grid([
            ["Day", "Session", "Exercise", "Sets", "Reps"],
            [1, "Push", "Bench Press", 3, 8],
        ])
    }
    context = program_import._freeform_grid_context(grid, [])
    model_rows = [SimpleNamespace(source_row=2, day=1, day_name="Push")]

    assert program_import._needs_layout_confirmation(context, model_rows, True, 0.3) is False


def test_recognized_header_without_day_axis_ignores_model_confirmation_hint():
    from service import program_import
    from types import SimpleNamespace

    grid = {
        "cells": program_import._compact_cell_grid([
            ["Exercise", "Sets", "Reps"],
            ["Bench Press", 3, 8],
            ["Squat", 3, 8],
        ])
    }
    context = program_import._freeform_grid_context(grid, [])
    model_rows = [
        SimpleNamespace(source_row=2, day=1, day_name="Day 1"),
        SimpleNamespace(source_row=3, day=1, day_name="Day 1"),
    ]

    assert context.header_row is None
    assert context.row_facts.header_rows == frozenset({1})
    assert program_import._needs_layout_confirmation(context, model_rows, True, 0.3) is False


@pytest.mark.parametrize(
    ("model_confirm_layout", "layout_confidence"),
    [(True, 0.99), (False, 0.74)],
)
def test_unrecognized_header_honors_model_confirmation_hint_or_low_confidence(
    model_confirm_layout, layout_confidence
):
    from service import program_import

    grid = {
        "cells": program_import._compact_cell_grid([
            ["Tag", "Übung", "Sätze", "Wdh"],
            [1, "Bench Press", 3, 8],
        ])
    }
    context = program_import._freeform_grid_context(grid, [])

    assert context.header_row is None
    assert program_import._needs_layout_confirmation(
        context, [], model_confirm_layout, layout_confidence
    ) is True


def test_structural_grid_ambiguity_requires_confirmation_even_with_confident_model():
    from service import program_import
    from types import SimpleNamespace

    grid = {
        "cells": program_import._compact_cell_grid([
            ["Day", "Session", "Exercise", "Sets", "Reps", "Sets", "Reps"],
            [1, "Push", "Bench Press", 3, 8, 4, 6],
        ])
    }
    context = program_import._freeform_grid_context(grid, [])
    model_rows = [SimpleNamespace(source_row=2, day=1, day_name="Push")]

    assert program_import._needs_layout_confirmation(context, model_rows, False, 0.99) is True


def test_arabic_headers_map_to_repaired_source_fields():
    from service import program_import

    grid = {
        "cells": program_import._compact_cell_grid([
            ["برنامج القوة"],
            ["اليوم", "اسم اليوم", "التمرين", "سيتات", "تكرارات", "RIR/RPE", "راحة", "الوزن", "ملاحظات"],
            [1, "دفع", "Bench Press", 3, 8, "2 RIR", 90, 60, "ثبت الكتفين"],
        ])
    }
    context = program_import._freeform_grid_context(grid, [])
    source = program_import._freeform_source_row(context, 3, None)

    assert source.fields == {
        "day": "1", "day_name": "دفع", "exercise": "Bench Press", "sets": "3",
        "reps": "8", "effort": "2 RIR", "rest_seconds": "90", "load_kg": "60",
        "notes": "ثبت الكتفين",
    }


@pytest.mark.parametrize(
    ("header", "expected_field"),
    [
        ("تمرين", "exercise"), ("التمرين", "exercise"),
        ("مجموعات", "sets"), ("جولات", "sets"), ("سيتات", "sets"),
        ("تكرارات", "reps"), ("عدات", "reps"),
        ("راحة", "rest_seconds"), ("RIR / RPE", "effort"),
        ("وزن / كجم", "load_kg"), ("الوزن", "load_kg"), ("ملاحظات", "notes"),
        ("Exercise / التمرين", "exercise"), ("Day / اليوم", "day"),
        ("Session / الحصة", "day_name"), ("ملاحظات المدرب", "notes"),
    ],
)
def test_arabic_coach_header_aliases_map_to_import_fields(header, expected_field):
    from service import program_import

    mapped_header = program_import._source_header_field(header)

    assert mapped_header is not None
    assert mapped_header[0] == expected_field


@pytest.mark.parametrize(
    ("header", "expected_week"),
    [("Week 2 sets", 2), ("الأسبوع 2 sets", 2), ("اسبوع 3 مجموعات", 3)],
)
def test_english_and_arabic_week_prefixes_map_to_source_headers(header, expected_week):
    from service import program_import

    assert program_import._source_header_field(header) == ("sets", expected_week)


def test_freeform_source_preserves_kg_per_set_and_superset_approximations():
    from service import program_import
    from service.program_import_ai import ProgramImportReply

    source_grid = {
        "sheet": "CSV",
        "cells": program_import._compact_cell_grid([
            ["Day", "Session", "Exercise", "Reps by set", "Load (kg)", "Effort", "Slot", "Load progression"],
            [1, "Lower A", "Squat", "10/8/6", 65, "RPE 8", "A1", "+2.5 kg/week"],
        ]),
    }
    reply = ProgramImportReply.model_validate({
        "rows": [{
            "source_row": 2, "week": None, "day": 1, "day_name": "Lower A",
            "exercise": "Squat", "sets": 3, "reps_min": 6, "reps_max": 10,
            "rir": 2, "rpe": None, "load_kg": 65, "original_text": "Squat",
        }],
        "layout": {"days": [{"day": 1, "name": "Lower A"}], "weeks": [], "confidence": 0.99},
    })

    source = program_import._freeform_reader_output(reply, ["CSV"], "CSV", source_grid)
    row = program_import._normalise_row(source.rows[0], {})
    warning_codes = {warning["code"] for warning in row["warnings"]}
    assert warning_codes >= {
        "program_import.load_preserved_as_note.v1",
        "program_import.reps_approximated.v1",
        "program_import.rpe_converted.v1",
        "program_import.unsupported_preserved_as_note.v1",
    }
    assert "load_kg: 65 kg" in row["notes"]
    assert "reps: 10/8/6" in row["notes"]
    assert "+2.5 kg/week" in row["notes"]


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


def test_weekly_progression_is_flagged_even_when_preserved_as_a_load_note():
    from types import SimpleNamespace

    from service.program_import import Approximation, _detect_unsupported_prescriptions

    row = SimpleNamespace(original_text="Back Squat (Barbell)", notes="load_progression: +2.5 kg/week")
    existing = [Approximation("program_import.load_preserved_as_note.v1", "notes", "+2.5 kg/week")]

    found = _detect_unsupported_prescriptions(row, existing)

    assert [marker.code for marker in found] == ["program_import.unsupported_preserved_as_note.v1"]


def test_sheet_title_rule_reaches_every_exercise_row():
    from service import program_import

    grid = {
        "cells": program_import._compact_cell_grid([
            ["Compounds: one top set followed by back-off work"],
            ["Day", "Exercise", "Sets", "Reps"],
            [1, "Back Squat (Barbell)", 1, 5],
            [1, "Romanian Deadlift (Barbell)", 3, 10],
        ])
    }
    context = program_import._freeform_grid_context(grid, [])
    sources = [program_import._freeform_source_row(context, row_number, None) for row_number in (3, 4)]

    assert all("top set" in source.text for source in sources)


def test_full_inference_queue_reports_busy_not_uninterpretable(monkeypatch):
    import pytest

    from service import program_import, program_import_ai

    def busy(*_args, **_kwargs):
        raise TimeoutError("Inference queue is full; retry shortly.")

    monkeypatch.setattr(program_import_ai, "translate_sheet", busy)
    grid = program_import.FreeFormCellGrid({"sheet": "CSV", "cells": [{"address": "A1", "value": "Squat"}]}, ["CSV"], "CSV")

    with pytest.raises(program_import.ProgramImportError) as raised:
        program_import.FreeFormProgramImportReader(None).read(grid)

    assert raised.value.code == "program_import.model_busy.v1"
    assert raised.value.status_code == 503
