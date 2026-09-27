"""Performed-date correction contract tests (ticket #36, ADR 020/035).

A player may correct a recent committed session's performed date within the
same three-day window as offline entry. The correction rewrites only the
session's date and appends an immutable correction row while the capture and
upload timestamps stay untouched; correcting to the current date is a no-op.
The affected missed-day attendance alerts are recalculated, and the active coach
sees the correction history through the existing gate-first reads.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import coach_history as coach_history_service
from service import missed_day_alerts as alerts_service
from service import workouts as workouts_service
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"

#: Pinned "now" so validation never depends on the wall clock (UTC Saturday).
FIXED_NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
CLIENT_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setattr(workouts_service, "_now", lambda: FIXED_NOW)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.execute(
        "INSERT INTO exercises (id, name, body_part, target_muscle) VALUES"
        " ('sq', 'Squat', 'Upper Legs', 'Quads'), ('bp', 'Bench Press', 'Chest', 'Chest'),"
        " ('row', 'Row', 'Back', 'Back');"
    )
    cat_conn.commit()
    cat_conn.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        users_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def _register(client, username, password="correct-horse-1"):
    resp = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _exercise_payload(exercise_id, exercise_name):
    return {
        "exercise_id": exercise_id,
        "exercise_name": exercise_name,
        "target_sets": 3,
        "target_reps_min": 5,
        "target_reps_max": 8,
        "target_rpe": 8.5,
        "rest_seconds": 120,
        "notes": None,
    }


def _program_payload():
    return {
        "program_name": "Assigned Split",
        "weekly_frequency": 3,
        "split_type": "Full Body",
        "days": [
            {
                "day_name": "Full A",
                "day_order": 1,
                "exercises": [
                    {"exercise_id": "sq", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                    {"exercise_id": "bp", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                    {"exercise_id": "row", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                ],
            }
        ],
    }


def _sets_body():
    return [
        {"exercise": _exercise_payload("sq", "Squat"), "sets": [{"weight_kg": 100.0, "reps": 5, "rpe": 8.0}]},
        {"exercise": _exercise_payload("bp", "Bench Press"), "sets": [{"weight_kg": 80.0, "reps": 5, "rpe": 8.0}]},
        {"exercise": _exercise_payload("row", "Row"), "sets": [{"weight_kg": 60.0, "reps": 8, "rpe": 8.5}]},
    ]


def _prepare_player(client, db, username="p1"):
    player = _register(client, username)
    headers = _authed(player["access_token"])
    db.switch_user(username)
    db.ledger.upsert_user_profile({"current_goal": "Strength"})
    db.ledger.save_training_program(_program_payload())
    version = db.ledger.get_active_program().version
    return headers, version


def _sync_body(*, client_session_id=CLIENT_ID, version, performed_date="2026-09-26",
               performed_timezone="UTC", captured_at="2026-09-26T11:30:00+00:00"):
    return {
        "day_order": 1,
        "readiness": 4,
        "session_notes": "",
        "sets": _sets_body(),
        "client_session_id": client_session_id,
        "performed_date": performed_date,
        "performed_timezone": performed_timezone,
        "program_version": version,
        "captured_at": captured_at,
    }


def _commit_session(client, db, headers, version, **overrides):
    resp = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version, **overrides))
    assert resp.status_code == 201, resp.text
    return resp.json()["session_id"]


def _session_row(db, session_id):
    return db.conn.execute(
        "SELECT session_date, uploaded_at, captured_at, edited_at"
        " FROM workout_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()


def _make_coach(client, db, username, capacity=10):
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username)
    assert issued["ok"], issued
    assert client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code == 200
    assert (
        client.put(
            "/coach/profile",
            headers=headers,
            json={"display_name": f"Coach {username}", "bio": "b", "specialization": "s", "capacity": capacity},
        ).status_code
        == 200
    )
    return headers


def _assign(client, coach_headers, player_headers):
    invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert invite.status_code == 200, invite.text
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite.json()["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    return redeemed.json()["assignment"]["assignment_id"]


# --------------------------------------------------------------------------
# Validation and the ledger write
# --------------------------------------------------------------------------


def test_in_window_correction_records_edit_and_correction_row(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    session_id = _commit_session(client, db, headers, version)

    db.switch_user("p1")
    before = _session_row(db, session_id)
    assert before["uploaded_at"] == FIXED_NOW.isoformat()
    assert before["captured_at"] == "2026-09-26T11:30:00+00:00"
    assert before["edited_at"] is None

    resp = client.patch(
        f"/workouts/sessions/{session_id}/performed-date",
        headers=headers,
        json={"performed_date": "2026-09-25"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["changed"] is True
    assert body["session_date"] == "2026-09-25"
    assert body["previous_date"] == "2026-09-26"
    assert body["edited_at"] == FIXED_NOW.isoformat()
    assert body["corrections"] == [
        {
            "previous_date": "2026-09-26",
            "corrected_date": "2026-09-25",
            "corrected_at": FIXED_NOW.isoformat(),
        }
    ]

    db.switch_user("p1")
    after = _session_row(db, session_id)
    assert after["session_date"] == "2026-09-25"
    assert after["uploaded_at"] == before["uploaded_at"]
    assert after["captured_at"] == before["captured_at"]
    assert after["edited_at"] == FIXED_NOW.isoformat()
    rows = db.ledger.list_performed_date_corrections(session_id)
    assert [(row["previous_date"], row["corrected_date"]) for row in rows] == [
        ("2026-09-26", "2026-09-25")
    ]


def test_correcting_to_the_same_date_is_a_noop(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    session_id = _commit_session(client, db, headers, version)

    resp = client.patch(
        f"/workouts/sessions/{session_id}/performed-date",
        headers=headers,
        json={"performed_date": "2026-09-26"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["changed"] is False
    assert body["session_date"] == "2026-09-26"
    assert body["edited_at"] is None
    assert body["corrections"] == []

    db.switch_user("p1")
    assert db.ledger.list_performed_date_corrections(session_id) == []
    assert _session_row(db, session_id)["edited_at"] is None


def test_noop_to_the_current_date_wins_over_the_recency_window(api):
    """An old session corrected to its own date is unchanged, not a 409."""
    client, db = api
    headers, version = _prepare_player(client, db)
    # Captured six days before the pinned now: past the correction window.
    session_id = _commit_session(
        client, db, headers, version,
        performed_date="2026-09-20", captured_at="2026-09-20T11:30:00+00:00",
    )

    resp = client.patch(
        f"/workouts/sessions/{session_id}/performed-date",
        headers=headers,
        json={"performed_date": "2026-09-20"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["changed"] is False
    assert body["session_date"] == "2026-09-20"
    assert body["corrections"] == []
    db.switch_user("p1")
    assert db.ledger.list_performed_date_corrections(session_id) == []
    assert _session_row(db, session_id)["edited_at"] is None


def test_correction_after_the_capture_date_is_refused(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    # A draft captured yesterday (performed yesterday) cannot be moved to today.
    session_id = _commit_session(
        client, db, headers, version,
        performed_date="2026-09-25", captured_at="2026-09-25T11:00:00+00:00",
    )

    resp = client.patch(
        f"/workouts/sessions/{session_id}/performed-date",
        headers=headers,
        json={"performed_date": "2026-09-26"},
    )
    assert resp.status_code == 400, resp.text
    assert "future" in resp.json()["detail"].lower()
    db.switch_user("p1")
    assert _session_row(db, session_id)["session_date"] == "2026-09-25"
    assert db.ledger.list_performed_date_corrections(session_id) == []


def test_future_performed_date_is_refused(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    session_id = _commit_session(client, db, headers, version)

    resp = client.patch(
        f"/workouts/sessions/{session_id}/performed-date",
        headers=headers,
        json={"performed_date": "2026-09-27"},
    )
    assert resp.status_code == 400, resp.text
    assert "future" in resp.json()["detail"].lower()
    db.switch_user("p1")
    assert _session_row(db, session_id)["session_date"] == "2026-09-26"
    assert db.ledger.list_performed_date_corrections(session_id) == []


def test_date_older_than_the_window_is_refused(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    session_id = _commit_session(client, db, headers, version)

    resp = client.patch(
        f"/workouts/sessions/{session_id}/performed-date",
        headers=headers,
        json={"performed_date": "2026-09-22"},
    )
    assert resp.status_code == 400, resp.text
    assert "3 days" in resp.json()["detail"]


def test_malformed_performed_date_is_refused(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    session_id = _commit_session(client, db, headers, version)

    resp = client.patch(
        f"/workouts/sessions/{session_id}/performed-date",
        headers=headers,
        json={"performed_date": "26/09/2026"},
    )
    assert resp.status_code == 400, resp.text
    assert "ISO date" in resp.json()["detail"]


def test_session_older_than_the_window_cannot_be_corrected(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    # Captured six days before the pinned now: history that can no longer change.
    session_id = _commit_session(
        client, db, headers, version,
        performed_date="2026-09-20", captured_at="2026-09-20T11:30:00+00:00",
    )

    resp = client.patch(
        f"/workouts/sessions/{session_id}/performed-date",
        headers=headers,
        json={"performed_date": "2026-09-21"},
    )
    assert resp.status_code == 409, resp.text
    assert "3 days" in resp.json()["detail"]
    db.switch_user("p1")
    assert _session_row(db, session_id)["session_date"] == "2026-09-20"
    assert db.ledger.list_performed_date_corrections(session_id) == []


def test_another_players_session_is_not_correctable(api):
    client, db = api
    headers_a, version = _prepare_player(client, db, username="p1")
    session_id = _commit_session(client, db, headers_a, version)

    headers_b, _ = _prepare_player(client, db, username="p2")
    resp = client.patch(
        f"/workouts/sessions/{session_id}/performed-date",
        headers=headers_b,
        json={"performed_date": "2026-09-25"},
    )
    assert resp.status_code == 404, resp.text


def test_unknown_session_id_is_404(api):
    client, db = api
    headers, _ = _prepare_player(client, db)
    resp = client.patch(
        "/workouts/sessions/does-not-exist/performed-date",
        headers=headers,
        json={"performed_date": "2026-09-25"},
    )
    assert resp.status_code == 404, resp.text


def test_replay_stays_original_and_by_client_id_reflects_the_correction(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    first = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert first.status_code == 201, first.text
    session_id = first.json()["session_id"]

    corrected = client.patch(
        f"/workouts/sessions/{session_id}/performed-date",
        headers=headers,
        json={"performed_date": "2026-09-25"},
    )
    assert corrected.status_code == 200, corrected.text

    # The idempotency record is immutable: the retry replays the original body.
    retry = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()

    # The current-state read the client reconciles with shows the corrected date.
    found = client.get(f"/workouts/sessions/by-client-id/{CLIENT_ID}", headers=headers)
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["session_id"] == session_id
    assert body["session_date"] == "2026-09-25"
    assert body["edited_at"] == FIXED_NOW.isoformat()
    assert body["corrections"][0]["corrected_date"] == "2026-09-25"


# --------------------------------------------------------------------------
# Missed-day alert recalculation
# --------------------------------------------------------------------------


def _backdate_assignment(db, assignment_id, started_at):
    db.catalog_conn.execute(
        "UPDATE assignments SET started_at = ? WHERE assignment_id = ?",
        (started_at.isoformat(), assignment_id),
    )
    db.catalog_conn.commit()


def _seed_schedule(db, player, weekdays, effective_from):
    db.switch_user(player)
    db.ledger.append_training_schedule(
        player, weekdays, "UTC", effective_from.isoformat(), "2026-01-01T00:00:00+00:00"
    )


def _seed_session(db, player, session_id, session_date, captured_at):
    db.switch_user(player)
    db.ledger.log_workout_session(
        session_id,
        session_date.isoformat(),
        "Full A",
        session_date.isoformat() + "T10:00:00+00:00",
        session_date.isoformat() + "T10:00:00+00:00",
        4,
        "",
        performed_timezone="UTC",
        captured_at=captured_at.isoformat(),
        uploaded_at=captured_at.isoformat(),
    )


def _fixed_hook_now(monkeypatch):
    """Makes the correction's best-effort attendance hook use the pinned now."""
    real = alerts_service.evaluate_for_ledger

    def _with_fixed_now(db_arg, account_id, now=None):
        return real(db_arg, account_id, now=FIXED_NOW)

    monkeypatch.setattr(alerts_service, "evaluate_for_ledger", _with_fixed_now)


def _open_alerts(db, coach_account_id):
    return [
        alert
        for alert in db.list_coach_alerts(coach_account_id, ("new", "acknowledged"))
        if alert["kind"] == alerts_service.MISSED_DAY_KIND
    ]


def _resolved_alerts(db, coach_account_id):
    return [
        alert
        for alert in db.list_coach_alerts(coach_account_id, ("resolved",))
        if alert["kind"] == alerts_service.MISSED_DAY_KIND
    ]


def test_correction_that_fills_a_missed_day_resolves_the_alert(api, monkeypatch):
    client, db = api
    _fixed_hook_now(monkeypatch)
    coach_headers = _make_coach(client, db, "coach", capacity=5)
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    assignment_id = _assign(client, coach_headers, headers)
    coach_account_id = db.get_active_account_by_username("coach")["account_id"]
    _backdate_assignment(db, assignment_id, datetime(2026, 9, 20, tzinfo=UTC))
    _seed_schedule(db, "p1", [3, 4], datetime(2026, 9, 18).date())
    # A workout that satisfies no expected day: the two expected days are missed.
    _seed_session(db, "p1", "sess-resolve", datetime(2026, 9, 19).date(), datetime(2026, 9, 26, 11, 0, tzinfo=UTC))
    db.switch_user("p1")
    account_id = db.get_active_account_by_username("p1")["account_id"]
    assignment = db.get_active_assignment_for_player(account_id)
    alerts_service.evaluate_assignment(db, assignment, now=FIXED_NOW)
    assert len(_open_alerts(db, coach_account_id)) == 1

    resp = client.patch(
        "/workouts/sessions/sess-resolve/performed-date",
        headers=headers,
        json={"performed_date": "2026-09-23"},
    )
    assert resp.status_code == 200, resp.text

    assert _open_alerts(db, coach_account_id) == []
    resolved = _resolved_alerts(db, coach_account_id)
    assert len(resolved) == 1
    assert resolved[0]["resolved_by"] == "system"


def test_correction_that_removes_a_satisfying_workout_opens_an_alert(api, monkeypatch):
    client, db = api
    _fixed_hook_now(monkeypatch)
    coach_headers = _make_coach(client, db, "coach", capacity=5)
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    assignment_id = _assign(client, coach_headers, headers)
    coach_account_id = db.get_active_account_by_username("coach")["account_id"]
    _backdate_assignment(db, assignment_id, datetime(2026, 9, 20, tzinfo=UTC))
    _seed_schedule(db, "p1", [3, 4], datetime(2026, 9, 18).date())
    # The workout satisfies the first expected day, so the streak is only one day.
    _seed_session(db, "p1", "sess-open", datetime(2026, 9, 24).date(), datetime(2026, 9, 26, 11, 0, tzinfo=UTC))
    db.switch_user("p1")
    account_id = db.get_active_account_by_username("p1")["account_id"]
    assignment = db.get_active_assignment_for_player(account_id)
    alerts_service.evaluate_assignment(db, assignment, now=FIXED_NOW)
    assert _open_alerts(db, coach_account_id) == []

    # Moving it off any expected day leaves both expected days missed.
    resp = client.patch(
        "/workouts/sessions/sess-open/performed-date",
        headers=headers,
        json={"performed_date": "2026-09-26"},
    )
    assert resp.status_code == 200, resp.text

    opened = _open_alerts(db, coach_account_id)
    assert len(opened) == 1
    assert opened[0]["details"]["missed_count"] == 2


# --------------------------------------------------------------------------
# Coach visibility (gate-first)
# --------------------------------------------------------------------------


def test_active_coach_sees_the_correction_history(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    coach_headers = _make_coach(client, db, "coach", capacity=5)
    assignment_id = _assign(client, coach_headers, headers)
    session_id = _commit_session(client, db, headers, version)

    corrected = client.patch(
        f"/workouts/sessions/{session_id}/performed-date",
        headers=headers,
        json={"performed_date": "2026-09-25"},
    )
    assert corrected.status_code == 200, corrected.text

    summary = client.get(f"/coach/assignments/{assignment_id}/player/summary", headers=coach_headers)
    assert summary.status_code == 200, summary.text
    latest = summary.json()["latest_session"]
    assert latest["session_date"] == "2026-09-25"
    assert latest["uploaded_at"] == FIXED_NOW.isoformat()
    assert latest["edited_at"] == FIXED_NOW.isoformat()
    assert latest["corrections"] == [
        {
            "previous_date": "2026-09-26",
            "corrected_date": "2026-09-25",
            "corrected_at": FIXED_NOW.isoformat(),
        }
    ]
    recent = summary.json()["recent_sessions"][0]
    assert recent["session_id"] == session_id
    assert recent["edited_at"] == FIXED_NOW.isoformat()
    assert recent["corrections"][0]["previous_date"] == "2026-09-26"


def test_revoked_coach_cannot_see_a_correction(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    coach_headers = _make_coach(client, db, "coach", capacity=5)
    assignment_id = _assign(client, coach_headers, headers)
    session_id = _commit_session(client, db, headers, version)
    client.patch(
        f"/workouts/sessions/{session_id}/performed-date",
        headers=headers,
        json={"performed_date": "2026-09-25"},
    )
    revoked = client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers)
    assert revoked.status_code == 200, revoked.text

    denied = client.get(
        f"/coach/assignments/{assignment_id}/player/summary", headers=coach_headers
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"] == coach_history_service.DENIED_ERROR


# --------------------------------------------------------------------------
# Service-level validation helper (no API)
# --------------------------------------------------------------------------


def test_validate_performed_date_correction_uses_the_entry_window():
    from datetime import date

    performed, previous, timezone = workouts_service.validate_performed_date_correction(
        "2026-09-24",
        session_date="2026-09-25",
        performed_timezone="UTC",
        schedule_timezone=None,
        capture_instant="2026-09-26T11:00:00+00:00",
        now=FIXED_NOW,
    )
    assert (performed, previous, timezone) == (date(2026, 9, 24), date(2026, 9, 25), "UTC")

    with pytest.raises(workouts_service.SessionSyncValidationError):
        workouts_service.validate_performed_date_correction(
            "2026-09-22",
            session_date="2026-09-25",
            performed_timezone="UTC",
            schedule_timezone=None,
            capture_instant="2026-09-26T11:00:00+00:00",
            now=FIXED_NOW,
        )

    with pytest.raises(workouts_service.SessionCorrectionNotAllowedError):
        workouts_service.validate_performed_date_correction(
            "2026-09-21",
            session_date="2026-09-20",
            performed_timezone="UTC",
            schedule_timezone=None,
            capture_instant="2026-09-20T11:00:00+00:00",
            now=FIXED_NOW,
        )
