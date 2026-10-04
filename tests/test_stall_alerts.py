"""Stall Coach alert route coverage (issue #204, ADR 032)."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema
from database.database_manager import DatabaseManager
from service import alert_sweep, coach as coach_service, coach_ai, stall_alerts
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
ALL_DAYS = [1, 2, 3, 4, 5, 6, 7]


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    catalog_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(catalog_path)
    conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    conn.execute(
        "INSERT INTO exercises (id, name, body_part, target_muscle) VALUES"
        " ('sq', 'Squat', 'Upper Legs', 'Quads'), ('bp', 'Bench Press', 'Chest', 'Chest'),"
        " ('row', 'Row', 'Back', 'Back');"
    )
    conn.commit()
    conn.close()
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
    response = client.post("/auth/register", json={"trainee_id": username, "password": "correct-horse-1"})
    assert response.status_code == 201, response.text
    return response.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _assigned(api):
    client, db = api
    coach = _register(client, "coach")
    coach_headers = _auth(coach["access_token"])
    invite = coach_service.issue_coach_invite(db, "coach", actor="cli")
    assert invite["ok"]
    assert client.post("/coach/invite/redeem", headers=coach_headers, json={"token": invite["token"]}).status_code == 200
    assert client.put(
        "/coach/profile",
        headers=coach_headers,
        json={"display_name": "Coach", "bio": "", "specialization": "", "capacity": 5},
    ).status_code == 200
    assignment_token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    player = _register(client, "player")
    player_headers = _auth(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": assignment_token, "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    assignment_id = redeemed.json()["assignment"]["assignment_id"]
    player_account_id = db.get_active_account_by_username("player")["account_id"]
    assignment = db.get_active_assignment_for_player(player_account_id)
    return coach_headers, player_headers, assignment_id, player_account_id, assignment


def _open_stall(api, assignment):
    _, db = api
    result = stall_alerts.evaluate_commit(
        db, assignment, "threshold-session", 8, "2026-09-01"
    )
    assert result["alerts_created"] == 1


def _program():
    return GeneratedProgramSchema(
        program_name="New Coach Program",
        split_type="Full Body",
        weekly_frequency=1,
        days=[
            ProgramDaySchema(
                day_name="Full A",
                day_order=1,
                exercises=[
                    ProgramExerciseSchema(exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8),
                    ProgramExerciseSchema(exercise_id="bp", exercise_name="Bench Press", target_reps_min=5, target_reps_max=8),
                    ProgramExerciseSchema(exercise_id="row", exercise_name="Row", target_reps_min=5, target_reps_max=8),
                ],
            )
        ],
    )


def test_publishing_program_resolves_stall_and_resolved_alert_is_not_urgent(api, monkeypatch):
    client, db = api
    coach_headers, _, assignment_id, _, assignment = _assigned(api)
    _open_stall(api, assignment)

    def fake_generate(_request, *, inference_call=None, ledger):
        program = _program()
        return program, "md"

    monkeypatch.setattr("service.coach_programs.generate_program_draft_pipeline", fake_generate)
    generated = client.post(
        f"/coach/assignments/{assignment_id}/program-draft/generate",
        headers=coach_headers,
        json={},
    )
    assert generated.status_code == 200, generated.text
    published = client.post(
        f"/coach/assignments/{assignment_id}/program-draft/publish",
        headers=coach_headers,
    )
    assert published.status_code == 200, published.text

    alerts = client.get("/coach/alerts?state=resolved", headers=coach_headers).json()["alerts"]
    stall = next(alert for alert in alerts if alert["kind"] == stall_alerts.STALL_KIND)
    assert stall["resolved_by"] == "system"
    roster = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    assert roster[0]["alerts_new"] == 0
    assert roster[0]["alerts_acknowledged"] == 0


def test_missed_day_sweep_resolves_stall_and_suppresses_opening_during_streak(api):
    client, db = api
    coach_headers, _, assignment_id, _, assignment = _assigned(api)
    _open_stall(api, assignment)
    now = datetime.now(UTC)
    started = now - timedelta(days=10)
    db.catalog_conn.execute(
        "UPDATE assignments SET started_at = ? WHERE assignment_id = ?",
        (started.isoformat(), assignment_id),
    )
    db.catalog_conn.commit()
    db.switch_user("player")
    db.ledger.append_training_schedule(
        "player", ALL_DAYS, "UTC", (started.date() - timedelta(days=1)).isoformat(), "2026-01-01T00:00:00+00:00"
    )

    alert_sweep.run_sweep(db, now=now)
    resolved = client.get("/coach/alerts?state=resolved", headers=coach_headers).json()["alerts"]
    stall = next(alert for alert in resolved if alert["kind"] == stall_alerts.STALL_KIND)
    assert stall["resolved_by"] == "system"
    result = stall_alerts.evaluate_commit(
        db, assignment, "stall-during-missed-streak", 9, "2026-09-01"
    )
    assert result["alerts_created"] == 0
    open_alerts = client.get("/coach/alerts", headers=coach_headers).json()["alerts"]
    assert not [alert for alert in open_alerts if alert["kind"] == stall_alerts.STALL_KIND]


def test_stall_evidence_is_excluded_from_coach_ai_allowlist():
    evidence = {"stall_length", "window_start_date"}
    assert evidence.isdisjoint(coach_ai._ALERT_EVIDENCE_FIELDS)
    rendered = coach_ai._render_alerts(
        {
            "alerts": [
                {
                    "kind": "stall",
                    "state": "new",
                    "stall_length": 8,
                    "window_start_date": "2026-09-01",
                }
            ]
        }
    )
    assert "stall_length" not in "\n".join(rendered)
    assert "2026-09-01" not in "\n".join(rendered)
