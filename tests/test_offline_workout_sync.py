"""Offline workout sync contract tests (ticket #34 / ADR 020/033).

A draft captured on the device commits idempotently: a retry or a reconciled
lost response produces exactly one session with its sets and derived records,
all in one ledger transaction. Validation is timezone-correct and time-bounded.
A draft captured against the current program commits against it; a draft
captured against an older version that still exists in the ledger commits as
history without rewriting the newer active program, and both the player and the
active coach see the version difference (ADR 034). A captured version that is
newer than the active one or absent from the ledger is refused with 409.
"""

import copy
import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import ProgramDaySchema, ProgramExerciseSchema
from database.database_manager import DatabaseManager
from service import analytics
from service import coach as coach_service
from service import coach_history as coach_history_service
from service import workouts as workouts_service
from service import training_status as training_status_service
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
        " ('row', 'Row', 'Back', 'Back'), ('ohp', 'Overhead Press', 'Shoulders', 'Shoulders');"
    )
    cat_conn.commit()
    cat_conn.close()
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


def _program_payload_v2():
    """A structurally different newer program: another day name, exercises, and targets."""
    return {
        "program_name": "Assigned Split v2",
        "weekly_frequency": 3,
        "split_type": "Full Body",
        "days": [
            {
                "day_name": "Full B",
                "day_order": 1,
                "exercises": [
                    {"exercise_id": "ohp", "target_sets": 4, "target_reps_min": 4, "target_reps_max": 6, "target_rpe": 8.0},
                    {"exercise_id": "bp", "target_sets": 2, "target_reps_min": 6, "target_reps_max": 10, "target_rpe": 8.0},
                    {"exercise_id": "sq", "target_sets": 4, "target_reps_min": 4, "target_reps_max": 6, "target_rpe": 8.0},
                ],
            }
        ],
    }


def _program_row_snapshot(db, program_id):
    """Every persisted day and exercise row for one program, for an unchanged check."""
    days = db.conn.execute(
        "SELECT id, day_name, day_order, warmup_json, cardio FROM program_days"
        " WHERE program_id = ? ORDER BY day_order, id",
        (program_id,),
    ).fetchall()
    exercises = db.conn.execute(
        "SELECT pe.id, pe.day_id, pe.exercise_id, pe.order_in_day, pe.target_sets,"
        " pe.target_reps_min, pe.target_reps_max, pe.target_rpe, pe.rest_seconds, pe.notes,"
        " pe.slot_key, pe.warmup_sets"
        " FROM program_exercises pe JOIN program_days pd ON pe.day_id = pd.id"
        " WHERE pd.program_id = ? ORDER BY pe.day_id, pe.order_in_day, pe.id",
        (program_id,),
    ).fetchall()
    return [tuple(row) for row in days], [tuple(row) for row in exercises]


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
    db.ledger.upsert_player_profile({"current_goal": "Strength"})
    db.ledger.save_training_program(_program_payload())
    version = db.ledger.get_active_program().version
    return headers, version


def _make_coach(client, db, username, capacity=5):
    """Registers a player, grants the coach capability, and sets roster capacity."""
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username, actor="cli")
    assert issued["ok"], issued
    assert (
        client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code
        == 200
    )
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
    """Issues an invite and has the player accept it; returns the assignment id."""
    invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert invite.status_code == 200, invite.text
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite.json()["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    return redeemed.json()["assignment"]["assignment_id"]


def _sync_body(*, client_session_id=CLIENT_ID, version, day_order=1, performed_date="2026-09-26",
               performed_timezone="UTC", captured_at="2026-09-26T11:30:00+00:00",
               captured_offline=False):
    return {
        "day_order": day_order,
        "readiness": 4,
        "session_notes": "",
        "sets": _sets_body(),
        "client_session_id": client_session_id,
        "performed_date": performed_date,
        "performed_timezone": performed_timezone,
        "program_version": version,
        "captured_at": captured_at,
        "captured_offline": captured_offline,
    }


def test_roster_stall_length_recounts_commits_and_replays_through_routes(
    api, monkeypatch, recording_analytics
):
    client, db = api
    coach_headers = _make_coach(client, db, "coach")
    player = _register(client, "p1")
    player_headers = _authed(player["access_token"])
    assignment_id = _assign(client, coach_headers, player_headers)
    db.switch_user("p1")
    db.ledger.upsert_player_profile({"current_goal": "Strength"})
    program = _program_payload()
    program["days"][0]["exercises"].append(
        {"exercise_id": "ohp", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5}
    )
    db.ledger.save_training_program(program)
    version = db.ledger.get_active_program().version

    def commit(
        session_id,
        performed_date,
        *,
        current=FIXED_NOW,
        weight=100.0,
        session_version=version,
        include_new_exercise=False,
    ):
        monkeypatch.setattr(workouts_service, "_now", lambda: current)
        body = _sync_body(
            client_session_id=session_id,
            version=session_version,
            performed_date=performed_date,
            captured_at=current.isoformat(),
        )
        body["sets"][0]["sets"][0]["weight_kg"] = weight
        if include_new_exercise:
            body["sets"].append(
                {
                    "exercise": _exercise_payload("ohp", "Overhead Press"),
                    "sets": [{"weight_kg": 50.0, "reps": 5, "rpe": 10.0}],
                }
            )
        response = client.post("/workouts/sessions", headers=player_headers, json=body)
        assert response.status_code in (200, 201), response.text
        return response

    baseline = commit(CLIENT_ID, "2026-09-23")
    assert baseline.json()["new_prs"] == []
    after_baseline = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    assert after_baseline[0]["assignment_id"] == assignment_id
    assert after_baseline[0]["stall_length"] == 1

    commit("22222222-2222-4222-8222-222222222222", "2026-09-24")
    next_response = commit("33333333-3333-4333-8333-333333333333", "2026-09-25")
    assert next_response.json()["new_prs"] == []
    roster = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    assert roster[0]["stall_length"] == 3

    replay = commit("33333333-3333-4333-8333-333333333333", "2026-09-25")
    assert replay.json() == next_response.json()
    roster = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    assert roster[0]["stall_length"] == 3

    # A late-committed session is placed by performed date before the next
    # record session, so it contributes to the count until that record resets it.
    commit("55555555-5555-4555-8555-555555555555", "2026-09-24")
    roster = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    assert roster[0]["stall_length"] == 4

    # An exercise first appears during the stall. Its first session is a
    # baseline, not a record, so the consecutive-session count keeps rising.
    first_ohp = commit(
        "99999999-9999-4999-8999-999999999999",
        "2026-09-25",
        include_new_exercise=True,
    )
    assert not any(pr["exercise_id"] == "ohp" for pr in first_ohp.json()["new_prs"])
    roster = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    assert roster[0]["stall_length"] == 5

    for index in range(3):
        stall_client_id = f"{index + 1}1111111-1111-4111-8111-111111111111"
        commit(
            stall_client_id,
            f"2026-09-{26 + index}",
            current=FIXED_NOW + timedelta(days=index),
        )
    roster = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    assert roster[0]["stall_length"] == 7
    assert not [alert for alert in client.get("/coach/alerts", headers=coach_headers).json()["alerts"] if alert["kind"] == "stall"]

    eighth_id = "41111111-1111-4111-8111-111111111111"
    eighth = commit(eighth_id, "2026-09-29", current=FIXED_NOW + timedelta(days=3))
    stall_alerts = client.get("/coach/alerts", headers=coach_headers).json()["alerts"]
    stall_alerts = [alert for alert in stall_alerts if alert["kind"] == "stall"]
    coach_id = db.get_active_account_by_username("coach")["account_id"]
    assert len(stall_alerts) == 1, (client.get("/coach/assignments", headers=coach_headers).json(), db.get_roster_alert_badges(coach_id))
    stall_alert = stall_alerts[0]
    assert stall_alert["stall_length"] == 8
    assert stall_alert["window_start_date"] == "2026-09-23"
    assert set(stall_alert) >= {"stall_length", "window_start_date"}
    assert {key: stall_alert[key] for key in ("stall_length", "window_start_date")} == {
        "stall_length": 8,
        "window_start_date": "2026-09-23",
    }
    assert stall_alert["message_code"] == "coach_alert.stall.v1"
    assert stall_alert["message_params"] == {
        "count": 8,
        "window_start_date": "2026-09-23",
    }
    assert stall_alert["message_fallback"] == (
        "Stalling — 8 sessions without a personal record (since 2026-09-23)"
    )
    assert stall_alert["session_id"] is None
    assert stall_alert["exercise_id"] is None
    assert stall_alert["exercise_name"] is None
    assert stall_alert["top_load"] is None
    assert "player_account_id" not in stall_alert
    created_events = [
        event
        for event in recording_analytics.events
        if event["event"] == "coach_alert_created"
        and event["properties"]["alert_kind"] == "stall"
    ]
    assert len(created_events) == 1
    replayed_eighth = commit(eighth_id, "2026-09-29", current=FIXED_NOW + timedelta(days=3))
    assert replayed_eighth.json() == eighth.json()
    assert len([
        event
        for event in recording_analytics.events
        if event["event"] == "coach_alert_created"
        and event["properties"]["alert_kind"] == "stall"
    ]) == 1
    coach_id = db.get_active_account_by_username("coach")["account_id"]
    notices = [notice for notice in db.list_assignment_notices(coach_id) if notice["kind"] == "stall"]
    assert len(notices) == 1
    assert "weight" not in notices[0]["message"].lower()
    acknowledged = client.post(f"/coach/alerts/{stall_alert['alert_id']}/acknowledge", headers=coach_headers)
    assert acknowledged.status_code == 200
    badges = db.get_roster_alert_badges(coach_id)[assignment_id]
    assert badges["alerts_new"] == 0
    assert badges["alerts_acknowledged"] == 1
    continued_id = "51111111-1111-4111-8111-111111111111"
    continued = commit(continued_id, "2026-09-30", current=FIXED_NOW + timedelta(days=4))
    continued_alerts = [alert for alert in client.get("/coach/alerts", headers=coach_headers).json()["alerts"] if alert["kind"] == "stall"]
    assert len(continued_alerts) == 1
    assert continued_alerts[0]["alert_id"] == stall_alert["alert_id"]
    assert continued_alerts[0]["stall_length"] == 9
    replay_stall = commit(continued_id, "2026-09-30", current=FIXED_NOW + timedelta(days=4))
    assert replay_stall.json() == continued.json()
    assert len([alert for alert in client.get("/coach/alerts", headers=coach_headers).json()["alerts"] if alert["kind"] == "stall"]) == 1

    pr = commit(
        "44444444-4444-4444-8444-444444444444",
        "2026-09-30",
        current=FIXED_NOW + timedelta(days=5),
        weight=110.0,
    )
    assert pr.json()["new_prs"]
    resolved_stalls = client.get("/coach/alerts?state=resolved", headers=coach_headers).json()["alerts"]
    assert any(alert["alert_id"] == stall_alert["alert_id"] and alert["resolved_by"] == "system" for alert in resolved_stalls)
    roster = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    assert roster[0]["stall_length"] == 0

    commit(
        "66666666-6666-4666-8666-666666666666",
        "2026-10-01",
        current=FIXED_NOW + timedelta(days=6),
    )
    roster = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    assert roster[0]["stall_length"] == 1

    db.ledger.save_training_program(_program_payload_v2())
    new_version = db.ledger.get_active_program().version
    commit(
        "77777777-7777-4777-8777-777777777777",
        "2026-10-02",
        current=FIXED_NOW + timedelta(days=7),
        session_version=new_version,
    )
    roster = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    assert roster[0]["stall_length"] == 1

    def fail_recount(*_args, **_kwargs):
        raise RuntimeError("recount unavailable")

    monkeypatch.setattr("service.stalling.recount_assignment", fail_recount)
    committed = commit(
        "88888888-8888-4888-8888-888888888888",
        "2026-10-03",
        current=FIXED_NOW + timedelta(days=8),
        session_version=new_version,
    )
    assert committed.status_code in (200, 201)
    roster = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    assert roster[0]["stall_length"] == 1

def _freeze_training_status_now(monkeypatch, instant):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.astimezone(tz)

    monkeypatch.setattr(training_status_service, "datetime", FixedDateTime)


def _seed_status_workouts(db, username, performed_dates):
    db.switch_user(username)
    for index, performed_date in enumerate(performed_dates):
        started_at = f"{performed_date}T12:00:00+00:00"
        db.ledger.log_workout_session(
            session_id=f"status-{username}-{index}",
            session_date=performed_date,
            split_name="Full A",
            started_at=started_at,
            completed_at=started_at,
        )


def test_first_commit_returns_201_and_records_sync_fields(api):
    client, db = api
    headers, version = _prepare_player(client, db)

    resp = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["session_id"]
    assert body["program_version"] == version
    assert body["active_program_version_at_sync"] == version
    assert body["is_historical_program"] is False
    assert "warmup_movements" not in body
    assert "cardio" not in body

    db.switch_user("p1")
    row = db.conn.execute(
        "SELECT client_session_id, session_date, performed_timezone, program_version,"
        " active_program_version_at_sync, captured_at, uploaded_at"
        " FROM workout_sessions WHERE id = ?",
        (body["session_id"],),
    ).fetchone()
    assert row["client_session_id"] == CLIENT_ID
    assert row["session_date"] == "2026-09-26"
    assert row["performed_timezone"] == "UTC"
    assert row["program_version"] == version
    assert row["active_program_version_at_sync"] == version
    assert row["captured_at"] == "2026-09-26T11:30:00+00:00"
    assert row["uploaded_at"] == FIXED_NOW.isoformat()


def test_workout_completed_is_aggregate_only_and_replay_emits_once(api, recording_analytics, monkeypatch):
    monkeypatch.setenv("MAYOS_ENV", "test")
    client, db = api
    headers, version = _prepare_player(client, db)
    headers["X-MAYOS-Client"] = "android/1.2.3"
    payload = _sync_body(version=version)
    payload["captured_offline"] = True
    payload["sets"] = payload["sets"][:2] + [
        {
            "exercise": _exercise_payload("ohp", "Overhead Press"),
            "sets": [{"weight_kg": 70.0, "reps": 8, "rpe": 8.0}],
        }
    ]
    payload["sets"][1]["sets"][0]["rpe"] = None
    payload["session_notes"] = "private note must stay in MAYOS"

    first = client.post("/workouts/sessions", headers=headers, json=payload)
    replay = client.post("/workouts/sessions", headers=headers, json=payload)

    assert first.status_code == 201, first.text
    assert replay.status_code == 200, replay.text
    events = [event for event in recording_analytics.events if event["event"] == "workout_completed"]
    assert len(events) == 1
    event = events[0]
    assert event["uuid"] == analytics.deterministic_event_uuid("workout_completed", CLIENT_ID)
    assert event["properties"] == {
        "role": "player",
        "platform": "android",
        "app_version": "1.2.3",
        "env": "test",
        "set_count": 3,
        "exercise_count": 3,
        "load_complete_set_count": 3,
        "reps_complete_set_count": 3,
        "rir_complete_set_count": 2,
        "divergence_count": 2,
        "unplanned_exercise_count": 1,
        "captured_offline": True,
        "sync_delay_seconds": 1800,
        "is_first_workout": True,
        "program_provenance": "generated",
        "coached": False,
    }
    assert "private note must stay in MAYOS" not in repr(event)
    assert "Squat" not in repr(event)
    assert "Overhead Press" not in repr(event)
    assert "100.0" not in repr(event)


def test_web_idempotent_commit_is_not_reported_as_offline(api, recording_analytics):
    client, db = api
    headers, version = _prepare_player(client, db)
    headers["X-MAYOS-Client"] = "web/2.0.0"

    response = client.post(
        "/workouts/sessions", headers=headers, json=_sync_body(version=version)
    )

    assert response.status_code == 201, response.text
    events = [event for event in recording_analytics.events if event["event"] == "workout_completed"]
    assert len(events) == 1
    assert events[0]["properties"]["platform"] == "web"
    assert events[0]["properties"]["captured_offline"] is False
    assert events[0]["properties"]["sync_delay_seconds"] == 0


def test_android_commit_without_offline_flag_is_not_reported_as_offline(
    api, recording_analytics
):
    client, _db = api
    headers, version = _prepare_player(client, _db)
    headers["X-MAYOS-Client"] = "android/1.2.3"

    response = client.post(
        "/workouts/sessions", headers=headers, json=_sync_body(version=version)
    )

    assert response.status_code == 201, response.text
    event = next(
        event
        for event in recording_analytics.events
        if event["event"] == "workout_completed"
    )
    assert event["properties"]["captured_offline"] is False
    assert event["properties"]["sync_delay_seconds"] == 0


def test_sync_failure_report_is_authenticated_and_catalogued(api, recording_analytics):
    client, db = api
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    payload = {"reason_code": "network", "attempt": 2}

    unauthorized = client.post("/workouts/sync-failures", json=payload)
    assert unauthorized.status_code == 401
    assert not [event for event in recording_analytics.events if event["event"] == "workout_sync_failed"]

    reported = client.post(
        "/workouts/sync-failures",
        headers=headers,
        json=payload,
    )

    assert reported.status_code == 204, reported.text
    events = [event for event in recording_analytics.events if event["event"] == "workout_sync_failed"]
    assert len(events) == 1
    assert events[0]["distinct_id"] == db.get_active_account_by_username("p1")["account_id"]
    assert events[0]["properties"]["sync_failure_reason"] == "network"
    assert events[0]["properties"]["attempt"] == 2
    update_reported = client.post(
        "/workouts/sync-failures",
        headers=headers,
        json={"reason_code": "app_update_required", "attempt": 1},
    )
    assert update_reported.status_code == 204, update_reported.text
    events = [
        event
        for event in recording_analytics.events
        if event["event"] == "workout_sync_failed"
    ]
    assert len(events) == 2
    assert events[1]["properties"]["sync_failure_reason"] == "app_update_required"
    assert events[1]["properties"]["attempt"] == 1
    rejected = client.post(
        "/workouts/sync-failures",
        headers=headers,
        json={"reason_code": "private details", "attempt": 2},
    )
    assert rejected.status_code == 422
    assert len(
        [
            event
            for event in recording_analytics.events
            if event["event"] == "workout_sync_failed"
        ]
    ) == 2

    class RaisingSink:
        def capture(self, *_args):
            raise RuntimeError("analytics unavailable")

        def set_person(self, *_args):
            raise RuntimeError("analytics unavailable")

        def set_person_once(self, *_args):
            raise RuntimeError("analytics unavailable")

        def delete_person(self, *_args):
            raise RuntimeError("analytics unavailable")

    analytics.set_sink(RaisingSink())
    still_ok = client.post("/workouts/sync-failures", headers=headers, json=payload)
    assert still_ok.status_code == 204, still_ok.text


def test_raising_analytics_sink_does_not_fail_workout_commit(api):
    class RaisingSink:
        def capture(self, *_args):
            raise RuntimeError("analytics unavailable")

        def set_person(self, *_args):
            raise RuntimeError("analytics unavailable")

        def set_person_once(self, *_args):
            raise RuntimeError("analytics unavailable")

        def delete_person(self, *_args):
            raise RuntimeError("analytics unavailable")

    client, db = api
    headers, version = _prepare_player(client, db)
    analytics.set_sink(RaisingSink())

    committed = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))

    assert committed.status_code == 201, committed.text
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 1


def test_commit_status_is_stored_and_replayed_at_commit_time(api, monkeypatch):
    client, db = api
    _freeze_training_status_now(monkeypatch, FIXED_NOW)
    headers, version = _prepare_player(client, db)
    payload = _sync_body(version=version)

    first = client.post("/workouts/sessions", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    stored_status = first.json()["training_status"]
    assert stored_status == {
        "weekly_streak": 0,
        "week_start": "2026-09-26",
        "week_done": 1,
        "week_target": 3,
        "mayos_workouts": 1,
        "next_checkpoint": 10,
        "workouts_to_next": 9,
    }

    db.switch_user("p1")
    db.ledger.conn.execute("UPDATE training_programs SET weekly_frequency = 1 WHERE is_active = 1")
    db.ledger.conn.commit()

    replay = client.post("/workouts/sessions", headers=headers, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["training_status"] == stored_status
    current_status = client.get("/dashboard/training-status", headers=headers).json()
    assert current_status["weekly_streak"] == 1
    assert current_status["week_done"] == 1
    assert current_status["week_target"] == 1


@pytest.mark.parametrize(
    "legacy", [False, True], ids=["offline-sync", "online"]
)
def test_commit_reads_import_count_before_ledger_transaction(
    api, monkeypatch, legacy
):
    client, db = api
    headers, version = _prepare_player(client, db)
    read_imported_workouts = training_status_service.imported_workout_count
    reads = []

    def read_before_transaction(database, account_id):
        assert database.ledger is not None
        assert not database.ledger.conn.in_transaction
        reads.append(account_id)
        return read_imported_workouts(database, account_id)

    monkeypatch.setattr(
        training_status_service, "imported_workout_count", read_before_transaction
    )
    payload = _sync_body(version=version)
    if legacy:
        for field in (
            "client_session_id",
            "performed_date",
            "performed_timezone",
            "program_version",
            "captured_at",
        ):
            payload.pop(field)

    response = client.post("/workouts/sessions", headers=headers, json=payload)

    assert response.status_code == 201, response.text
    assert len(reads) == 1
    assert response.json()["training_status"]["mayos_workouts"] == 1


def test_training_status_endpoint_uses_player_timezone_at_saturday_boundary(api, monkeypatch):
    client, db = api
    boundary = datetime(2026, 9, 25, 21, 30, tzinfo=UTC)
    _freeze_training_status_now(monkeypatch, boundary)
    moscow_headers, moscow_version = _prepare_player(client, db, "moscow")
    db.switch_user("moscow")
    db.ledger.append_training_schedule(
        "moscow", [6], "Europe/Moscow", "2026-09-01", "2026-09-01T00:00:00+00:00"
    )
    moscow_commit = client.post(
        "/workouts/sessions",
        headers=moscow_headers,
        json=_sync_body(
            client_session_id="22222222-2222-4222-8222-222222222222",
            version=moscow_version,
            performed_date="2026-09-26",
            performed_timezone="Europe/Moscow",
        ),
    )
    assert moscow_commit.status_code == 201, moscow_commit.text
    moscow_status = client.get("/dashboard/training-status", headers=moscow_headers).json()
    assert moscow_status["week_start"] == "2026-09-26"
    assert moscow_status["week_done"] == 1
    assert moscow_status["week_target"] == 1

    utc_headers, utc_version = _prepare_player(client, db, "utcplayer")
    utc_commit = client.post(
        "/workouts/sessions",
        headers=utc_headers,
        json=_sync_body(
            client_session_id="33333333-3333-4333-8333-333333333333",
            version=utc_version,
            performed_date="2026-09-26",
        ),
    )
    assert utc_commit.status_code == 201, utc_commit.text
    utc_status = client.get("/dashboard/training-status", headers=utc_headers).json()
    assert utc_status["week_start"] == "2026-09-19"
    assert utc_status["week_done"] == 0


def test_training_status_endpoint_applies_full_and_partial_pauses(api, monkeypatch):
    client, db = api
    _freeze_training_status_now(monkeypatch, FIXED_NOW)
    weekdays = [1, 2, 3, 4, 5, 6, 7]
    full_headers, _ = _prepare_player(client, db, "fullpause")
    db.switch_user("fullpause")
    db.ledger.append_training_schedule(
        "fullpause", weekdays, "UTC", "2026-09-01", "2026-09-01T00:00:00+00:00"
    )
    db.ledger.schedule_training_pause(
        "fullpause", "2026-09-26", "2026-10-02", "2026-09-26T00:00:00+00:00"
    )
    full = client.get("/dashboard/training-status", headers=full_headers)
    assert full.status_code == 200, full.text
    assert full.json()["week_target"] == 0

    partial_headers, _ = _prepare_player(client, db, "partialpause")
    db.switch_user("partialpause")
    db.ledger.append_training_schedule(
        "partialpause", weekdays, "UTC", "2026-09-01", "2026-09-01T00:00:00+00:00"
    )
    db.ledger.schedule_training_pause(
        "partialpause", "2026-09-26", "2026-09-26", "2026-09-26T00:00:00+00:00"
    )
    partial = client.get("/dashboard/training-status", headers=partial_headers)
    assert partial.status_code == 200, partial.text
    assert partial.json()["week_target"] == 6
    assert client.get("/dashboard/training-status").status_code == 401


def test_training_status_endpoint_keeps_in_progress_week_and_breaks_on_missed_past_week(api, monkeypatch):
    client, db = api
    _freeze_training_status_now(monkeypatch, datetime(2026, 9, 30, 12, tzinfo=UTC))
    current_headers, _ = _prepare_player(client, db, "inprogress")
    db.switch_user("inprogress")
    db.ledger.conn.execute("UPDATE training_programs SET weekly_frequency = 2 WHERE is_active = 1")
    db.ledger.conn.commit()
    _seed_status_workouts(db, "inprogress", ["2026-09-19", "2026-09-22", "2026-09-26"])
    current = client.get("/dashboard/training-status", headers=current_headers)
    assert current.status_code == 200, current.text
    assert current.json()["week_start"] == "2026-09-26"
    assert current.json()["week_done"] == 1
    assert current.json()["week_target"] == 2
    assert current.json()["weekly_streak"] == 1

    broken_headers, _ = _prepare_player(client, db, "brokenstreak")
    db.switch_user("brokenstreak")
    db.ledger.conn.execute("UPDATE training_programs SET weekly_frequency = 2 WHERE is_active = 1")
    db.ledger.conn.commit()
    _seed_status_workouts(db, "brokenstreak", ["2026-09-05", "2026-09-08", "2026-09-26"])
    broken = client.get("/dashboard/training-status", headers=broken_headers)
    assert broken.status_code == 200, broken.text
    assert broken.json()["weekly_streak"] == 0


def test_training_status_excludes_imported_workout_history(api, monkeypatch):
    client, db = api
    _freeze_training_status_now(monkeypatch, FIXED_NOW)
    headers, version = _prepare_player(client, db)
    account_id = db.get_active_account_by_username("p1")["account_id"]
    db.catalog_conn.execute(
        "INSERT INTO account_imports"
        " (import_id, account_id, source_fingerprint, source_name, counts_json, opt_in_reference, imported_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("import-p1", account_id, "fingerprint", "snapshot.db", '{"workout_sessions": 12}', "test", "2026-01-01"),
    )
    db.catalog_conn.commit()

    committed = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert committed.status_code == 201, committed.text
    assert committed.json()["training_status"]["mayos_workouts"] == 0
    status = client.get("/dashboard/training-status", headers=headers)
    assert status.status_code == 200, status.text
    assert status.json()["mayos_workouts"] == 0
    assert status.json()["next_checkpoint"] == 10


def test_legacy_online_commit_includes_training_status(api, monkeypatch):
    client, db = api
    _freeze_training_status_now(monkeypatch, FIXED_NOW)
    headers, _ = _prepare_player(client, db)
    body = _sync_body(version=1)
    for field in ("client_session_id", "performed_date", "performed_timezone", "program_version", "captured_at"):
        body.pop(field)

    committed = client.post("/workouts/sessions", headers=headers, json=body)
    assert committed.status_code == 201, committed.text
    assert committed.json()["training_status"]["mayos_workouts"] == 1


def test_warmup_movements_are_stored_without_working_set_effects_and_replay(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    control_headers, control_version = _prepare_player(client, db, username="p2")
    warmup_body = _sync_body(version=version)
    warmup_body["sets"] = warmup_body["sets"][:1]
    warmup_body["warmup_movements"] = [
        {
            "exercise_id": "ohp",
            "exercise_name": "Overhead mobility",
            "sets": [
                {"weight_kg": None, "reps": 10},
                {"weight_kg": 2.5, "reps": 8},
            ],
        }
    ]
    control_body = _sync_body(
        client_session_id="22222222-2222-4222-8222-222222222222",
        version=control_version,
    )
    control_body["sets"] = control_body["sets"][:1]

    committed = client.post("/workouts/sessions", headers=headers, json=warmup_body)
    control = client.post("/workouts/sessions", headers=control_headers, json=control_body)
    assert committed.status_code == control.status_code == 201
    body = committed.json()
    assert body["warmup_movements"] == warmup_body["warmup_movements"]
    assert body["divergences"] == control.json()["divergences"]
    assert body["total_working_sets"] == control.json()["total_working_sets"] == 1
    assert body["total_tonnage_kg"] == control.json()["total_tonnage_kg"]
    assert body["new_prs"] == control.json()["new_prs"]
    assert body["exercise_summaries"] == control.json()["exercise_summaries"]
    assert body["fatigue_post"] == control.json()["fatigue_post"]

    db.switch_user("p1")
    session_id = body["session_id"]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM workout_sets WHERE session_id = ?", (session_id,)
    ).fetchone()[0] == 1
    warmup_rows = db.conn.execute(
        "SELECT movement_index, exercise_id, exercise_name, set_index, weight_kg, reps"
        " FROM session_warmup_sets WHERE session_id = ? ORDER BY set_index",
        (session_id,),
    ).fetchall()
    assert [tuple(row) for row in warmup_rows] == [
        (0, "ohp", "Overhead mobility", 1, None, 10),
        (0, "ohp", "Overhead mobility", 2, 2.5, 8),
    ]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM session_divergences WHERE session_id = ? AND exercise_id = 'ohp'",
        (session_id,),
    ).fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM personal_records").fetchone()[0] == 0
    assert db.ledger.get_last_performance("ohp") == []
    assert "ohp" not in {
        baseline["exercise_id"]
        for baseline in workouts_service.baselines(db, "p1", ledger=db.ledger)["baselines"]
    }
    latest = db.ledger.get_latest_session_summary()
    assert latest["sets_count"] == 1
    assert latest["total_volume_kg"] == 500.0
    assert latest["warmup_movements"] == body["warmup_movements"]
    assert client.get("/workouts/sessions/latest", headers=headers).json()[
        "warmup_movements"
    ] == body["warmup_movements"]
    assert coach_history_service.recent_sessions(db.ledger, 5)[0][
        "warmup_movements"
    ] == body["warmup_movements"]

    replay_body = copy.deepcopy(warmup_body)
    replay_body["warmup_movements"] = [
        {"exercise_id": "missing", "exercise_name": "Changed", "sets": [{"reps": 1}]}
    ]
    replay = client.post("/workouts/sessions", headers=headers, json=replay_body)
    assert replay.status_code == 200
    assert replay.json() == body
    assert db.conn.execute(
        "SELECT COUNT(*) FROM session_warmup_sets WHERE session_id = ?", (session_id,)
    ).fetchone()[0] == 2


def test_cardio_is_stored_and_returned_in_player_and_coach_history_without_set_effects(api):
    client, db = api
    player_headers, version = _prepare_player(client, db)
    control_headers, control_version = _prepare_player(client, db, username="p2")
    coach_headers = _make_coach(client, db, "coach")
    assignment_id = _assign(client, coach_headers, player_headers)

    cardio_body = _sync_body(version=version)
    cardio_body["cardio"] = {"prescription": "Steady bike after lifting", "minutes": 25}
    control_body = _sync_body(
        client_session_id="22222222-2222-4222-8222-222222222222",
        version=control_version,
    )
    cardio_commit = client.post("/workouts/sessions", headers=player_headers, json=cardio_body)
    control_commit = client.post("/workouts/sessions", headers=control_headers, json=control_body)
    assert cardio_commit.status_code == control_commit.status_code == 201
    body = cardio_commit.json()
    expected_cardio = {"prescription": "Steady bike after lifting", "minutes": 25}
    assert body["cardio"] == expected_cardio
    for key in ("divergences", "total_working_sets", "total_tonnage_kg", "new_prs", "exercise_summaries", "fatigue_post"):
        assert body[key] == control_commit.json()[key]

    db.switch_user("p1")
    session_id = body["session_id"]
    row = db.conn.execute(
        "SELECT prescription, minutes FROM session_cardio WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    assert tuple(row) == (expected_cardio["prescription"], expected_cardio["minutes"])
    assert db.ledger.get_latest_session_summary()["cardio"] == expected_cardio
    assert client.get("/workouts/sessions/latest", headers=player_headers).json()["cardio"] == expected_cardio

    coach_history = client.get(
        f"/coach/assignments/{assignment_id}/player/summary", headers=coach_headers
    )
    assert coach_history.status_code == 200, coach_history.text
    history_body = coach_history.json()
    assert history_body["latest_session"]["cardio"] == expected_cardio
    assert history_body["recent_sessions"][0]["cardio"] == expected_cardio
    assert history_body["latest_session"]["sets_count"] == body["total_working_sets"]
    assert history_body["latest_session"]["total_volume_kg"] == body["total_tonnage_kg"]

    player_baselines = workouts_service.baselines(db, "p1", ledger=db.ledger)["baselines"]
    db.switch_user("p2")
    control_baselines = workouts_service.baselines(db, "p2", ledger=db.ledger)["baselines"]
    assert player_baselines == control_baselines

    db.switch_user("p1")
    replay_payload = copy.deepcopy(cardio_body)
    replay_payload["cardio"] = {"prescription": "Changed on retry", "minutes": 40}
    replay = client.post("/workouts/sessions", headers=player_headers, json=replay_payload)
    assert replay.status_code == 200
    assert replay.json() == body
    assert db.conn.execute(
        "SELECT COUNT(*) FROM session_cardio WHERE session_id = ?", (session_id,)
    ).fetchone()[0] == 1


def test_cardio_bounds_are_rejected(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    invalid_cardio = [
        {"prescription": "", "minutes": 1},
        {"prescription": "x" * 501, "minutes": 1},
        {"prescription": "Bike", "minutes": 0},
        {"prescription": "Bike", "minutes": 601},
    ]
    for cardio in invalid_cardio:
        body = _sync_body(version=version)
        body["cardio"] = cardio
        response = client.post("/workouts/sessions", headers=headers, json=body)
        assert response.status_code == 422, response.text


def test_cardio_minute_bounds_are_inclusive(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    for index, minutes in enumerate((1, 600), start=3):
        body = _sync_body(
            client_session_id=f"33333333-3333-4333-8333-33333333333{index}",
            version=version,
        )
        body["cardio"] = {"prescription": "Bike", "minutes": minutes}
        response = client.post("/workouts/sessions", headers=headers, json=body)
        assert response.status_code == 201, response.text
        assert response.json()["cardio"]["minutes"] == minutes


def test_unknown_warmup_library_id_is_saved_by_name(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    body = _sync_body(version=version)
    body["warmup_movements"] = [
        {
            "exercise_id": "removed_mobility_exercise",
            "exercise_name": "My mobility drill",
            "sets": [{"weight_kg": None, "reps": 8}],
        }
    ]

    response = client.post("/workouts/sessions", headers=headers, json=body)

    assert response.status_code == 201, response.text
    expected = [
        {
            "exercise_id": None,
            "exercise_name": "My mobility drill",
            "sets": [{"weight_kg": None, "reps": 8}],
        }
    ]
    assert response.json()["warmup_movements"] == expected
    db.switch_user("p1")
    assert db.ledger.list_session_warmup_movements(response.json()["session_id"]) == expected


def test_warmup_movement_bounds_are_rejected(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    invalid_sets = [
        [{"weight_kg": -0.1, "reps": 10}],
        [{"weight_kg": 500.1, "reps": 10}],
        [{"weight_kg": None, "reps": 0}],
        [{"weight_kg": None, "reps": 51}],
        [{"weight_kg": None, "reps": 10}] * 11,
    ]
    for sets in invalid_sets:
        body = _sync_body(version=version)
        body["warmup_movements"] = [
            {"exercise_name": "Mobility", "sets": sets}
        ]
        response = client.post("/workouts/sessions", headers=headers, json=body)
        assert response.status_code == 422, response.text

    body = _sync_body(version=version)
    body["warmup_movements"] = [
        {"exercise_name": "x" * 121, "sets": [{"reps": 10}]}
    ]
    response = client.post("/workouts/sessions", headers=headers, json=body)
    assert response.status_code == 422, response.text


def test_identical_retry_returns_200_same_body_and_one_session(api):
    client, db = api
    headers, version = _prepare_player(client, db)

    first = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert first.status_code == 201, first.text
    retry = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()

    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sets").fetchone()[0] == 3
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 1
    # The first session of an exercise is its baseline: no personal_records row (ADR 042).
    assert db.conn.execute("SELECT COUNT(*) FROM personal_records").fetchone()[0] == 0


def test_committed_client_id_replays_after_catalog_exercise_disappears(api):
    """A retry replays the stored response before any mutable catalog validation (ADR 033)."""
    client, db = api
    headers, version = _prepare_player(client, db)

    first = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert first.status_code == 201, first.text

    # The catalog changes after the commit: the prescribed exercise is gone.
    db.catalog_conn.execute("DELETE FROM exercises WHERE id = 'sq'")
    db.catalog_conn.commit()

    retry = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 1


def test_uncommitted_client_id_still_validates_the_catalog(api):
    """Replay precedence must not let a genuinely new commit skip catalog validation."""
    client, db = api
    headers, version = _prepare_player(client, db)

    db.catalog_conn.execute("DELETE FROM exercises WHERE id = 'sq'")
    db.catalog_conn.commit()

    resp = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert resp.status_code == 400, resp.text
    assert "unknown exercise" in resp.json()["detail"].lower()
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0


def test_failed_commit_writes_nothing_and_retry_succeeds(api, monkeypatch, recording_analytics):
    client, db = api
    headers, version = _prepare_player(client, db)

    original = workouts_service.evaluate_session_prs

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated failure mid-commit")

    monkeypatch.setattr(workouts_service, "evaluate_session_prs", _boom)
    with pytest.raises(RuntimeError, match="simulated failure"):
        client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))

    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sets").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 0
    assert not [event for event in recording_analytics.events if event["event"] == "workout_completed"]

    monkeypatch.setattr(workouts_service, "evaluate_session_prs", original)
    retry = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert retry.status_code == 201, retry.text
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 1
    assert len([event for event in recording_analytics.events if event["event"] == "workout_completed"]) == 1


def test_status_lookup_404_then_200(api):
    client, db = api
    headers, version = _prepare_player(client, db)

    missing = client.get(f"/workouts/sessions/by-client-id/{CLIENT_ID}", headers=headers)
    assert missing.status_code == 404

    committed = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert committed.status_code == 201, committed.text

    found = client.get(f"/workouts/sessions/by-client-id/{CLIENT_ID}", headers=headers)
    assert found.status_code == 200
    # The stored response is overlaid with the live session date and correction
    # history (ADR 035); every original field is unchanged.
    body = found.json()
    assert {key: value for key, value in body.items() if key in committed.json()} == committed.json()
    assert body["session_id"] == committed.json()["session_id"]
    assert body["session_date"] == "2026-09-26"
    assert body["edited_at"] is None
    assert body["corrections"] == []


def test_legacy_commit_without_client_session_id_emits_once(api, recording_analytics):
    client, db = api
    headers, _ = _prepare_player(client, db)

    resp = client.post(
        "/workouts/sessions",
        headers=headers,
        json={"day_order": 1, "readiness": 4, "session_notes": "", "sets": _sets_body()},
    )
    assert resp.status_code == 201, resp.text
    db.switch_user("p1")
    row = db.conn.execute("SELECT client_session_id FROM workout_sessions").fetchone()
    assert row["client_session_id"] is None
    events = [event for event in recording_analytics.events if event["event"] == "workout_completed"]
    assert len(events) == 1
    assert events[0]["uuid"] == analytics.deterministic_event_uuid(
        "workout_completed", resp.json()["session_id"]
    )


def test_workout_fact_lookup_failure_does_not_fail_committed_workout(
    api, recording_analytics, monkeypatch
):
    client, db = api
    headers, version = _prepare_player(client, db)

    def fail_assignment_lookup(_account_id):
        raise RuntimeError("assignment lookup unavailable")

    monkeypatch.setattr(db, "get_active_assignment_for_player", fail_assignment_lookup)
    response = client.post(
        "/workouts/sessions", headers=headers, json=_sync_body(version=version)
    )

    assert response.status_code == 201, response.text
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 1
    assert not [
        event
        for event in recording_analytics.events
        if event["event"] == "workout_completed"
    ]


def test_newer_program_version_is_refused_and_writes_nothing(api):
    client, db = api
    headers, version = _prepare_player(client, db)

    resp = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version + 1))
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["error"] == "program_version_mismatch"
    assert body["active_version"] == version
    assert body["message_code"] == "workout.program_version_mismatch.v1"
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 0


def test_unknown_older_program_version_is_refused(api):
    """An older version that is not in the ledger cannot be resolved as history."""
    client, db = api
    headers, version = _prepare_player(client, db)

    # Version 0 predates every stored program row.
    resp = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=0))
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["error"] == "program_version_mismatch"
    assert body["active_version"] == version
    assert body["message_code"] == "workout.program_version_mismatch.v1"
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0


def test_older_program_version_syncs_as_history_without_rewriting_active_program(api):
    client, db = api
    headers, captured_version = _prepare_player(client, db)

    db.switch_user("p1")
    active_program_id = db.ledger.save_training_program(_program_payload_v2())
    active_version = db.ledger.get_active_program().version
    assert active_version == captured_version + 1
    v2_rows_before = _program_row_snapshot(db, active_program_id)

    resp = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=captured_version))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["program_version"] == captured_version
    assert body["active_program_version_at_sync"] == active_version
    assert body["is_historical_program"] is True
    # Resolved against v1's day plan, not the active v2 plan: v1 prescribed
    # exactly the three performed movements, while v2 prescribes OHP and drops Row.
    assert [summary["name"] for summary in body["exercise_summaries"]] == ["Squat", "Bench Press", "Row"]
    assert body["divergences"] == []

    db.switch_user("p1")
    row = db.conn.execute(
        "SELECT split_name, program_version, active_program_version_at_sync"
        " FROM workout_sessions WHERE id = ?",
        (body["session_id"],),
    ).fetchone()
    assert row["split_name"] == "Full A"
    assert row["program_version"] == captured_version
    assert row["active_program_version_at_sync"] == active_version
    # The captured prescription is retained and the newer program stays active,
    # with every v2 program row byte-for-byte unchanged.
    assert db.ledger.get_program_by_version(captured_version) is not None
    assert db.ledger.get_active_program().version == active_version
    assert _program_row_snapshot(db, active_program_id) == v2_rows_before
    assert (
        db.conn.execute("SELECT COUNT(*) FROM training_programs WHERE is_active = 1").fetchone()[0] == 1
    )


def test_older_program_version_replay_is_unchanged(api):
    """Idempotent replay behaviour is identical for a historical-version commit (#34)."""
    client, db = api
    headers, captured_version = _prepare_player(client, db)
    db.switch_user("p1")
    db.ledger.save_training_program(_program_payload())

    first = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=captured_version))
    assert first.status_code == 201, first.text
    assert first.json()["is_historical_program"] is True

    retry = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=captured_version))
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()

    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 1


#: Every coach read that can expose the assigned player's sessions or exercise history.
COACH_SESSION_READS = (
    "/player/summary",
    "/player/personal-records",
    "/player/exercises",
    "/player/exercises/sq/history",
    "/check-ins",
)


def test_revoked_coach_cannot_read_a_workout_synced_after_revocation(api):
    client, db = api
    headers, captured_version = _prepare_player(client, db, username="p1")

    coach_a = _make_coach(client, db, "coachA")
    assignment_a = _assign(client, coach_a, headers)
    revoked = client.post(f"/coach/assignments/{assignment_a}/revoke", headers=coach_a)
    assert revoked.status_code == 200, revoked.text

    # A first sync establishes each exercise's baseline (ADR 042 stores no record
    # row for it), so the sync below is the one whose rows the coach reads.
    baseline = client.post(
        "/workouts/sessions",
        headers=headers,
        json=_sync_body(
            version=captured_version,
            client_session_id="22222222-2222-4222-8222-222222222222",
            performed_date="2026-09-25",
            captured_at="2026-09-25T11:00:00+00:00",
        ),
    )
    assert baseline.status_code == 201, baseline.text

    # A newer program is published after the coach is revoked but before the
    # captured draft syncs; the sync still commits as history. Its squat beat
    # the baseline sync's, so the coach's personal-records read has a row (#122).
    db.switch_user("p1")
    db.ledger.save_training_program(_program_payload())
    history_body = _sync_body(version=captured_version)
    history_body["sets"][0]["sets"] = [{"weight_kg": 105.0, "reps": 5, "rpe": 8.0}]
    synced = client.post("/workouts/sessions", headers=headers, json=history_body)
    assert synced.status_code == 201, synced.text

    # The revoked coach is denied on every session-exposing coach read.
    for suffix in COACH_SESSION_READS:
        denied = client.get(f"/coach/assignments/{assignment_a}{suffix}", headers=coach_a)
        assert denied.status_code == 403, (suffix, denied.text)
        assert denied.json()["detail"] == coach_history_service.DENIED_ERROR

    # A coach currently assigned can read the same workout and sees the difference.
    coach_b = _make_coach(client, db, "coachB")
    assignment_b = _assign(client, coach_b, headers)
    summary = client.get(f"/coach/assignments/{assignment_b}/player/summary", headers=coach_b)
    assert summary.status_code == 200, summary.text
    latest = summary.json()["latest_session"]
    assert latest["program_version"] == captured_version
    assert latest["active_program_version_at_sync"] == captured_version + 1
    assert latest["is_historical_program"] is True
    recent = summary.json()["recent_sessions"][0]
    assert recent["program_version"] == captured_version
    assert recent["active_program_version_at_sync"] == captured_version + 1
    assert recent["is_historical_program"] is True
    # The other session-exposing reads the active coach is allowed to make still work.
    records = client.get(
        f"/coach/assignments/{assignment_b}/player/personal-records", headers=coach_b
    )
    assert records.status_code == 200, records.text
    assert any(record["exercise_id"] == "sq" for record in records.json())
    exercises = client.get(f"/coach/assignments/{assignment_b}/player/exercises", headers=coach_b)
    assert exercises.status_code == 200, exercises.text
    assert {entry["id"] for entry in exercises.json()["exercises"]} >= {"sq", "bp", "row"}
    history = client.get(
        f"/coach/assignments/{assignment_b}/player/exercises/sq/history", headers=coach_b
    )
    assert history.status_code == 200, history.text
    assert history.json()["history"]
    check_ins = client.get(f"/coach/assignments/{assignment_b}/check-ins", headers=coach_b)
    assert check_ins.status_code == 200, check_ins.text


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"performed_date": "2026-09-27"}, "future"),
        ({"performed_date": "2026-09-22"}, "more than 3 days"),
        ({"performed_date": "2026/09/26"}, "ISO date"),
        ({"performed_timezone": "Mars/Olympus"}, "Unknown timezone"),
        ({"performed_timezone": ""}, "timezone is required"),
        ({"captured_at": "2026-09-26T12:21:00+00:00"}, "future"),
        ({"captured_at": "2026-09-26T12:00:00"}, "timezone offset"),
        ({"client_session_id": "not-a-uuid"}, "UUID"),
    ],
)
def test_sync_validation_errors_are_400(api, overrides, expected):
    client, db = api
    headers, version = _prepare_player(client, db)
    body = _sync_body(version=version)
    body.update(overrides)

    resp = client.post("/workouts/sessions", headers=headers, json=body)
    assert resp.status_code == 400, resp.text
    assert expected.lower() in resp.json()["detail"].lower()
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0


def test_missing_program_version_is_400(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    body = _sync_body(version=version)
    del body["program_version"]

    resp = client.post("/workouts/sessions", headers=headers, json=body)
    assert resp.status_code == 400, resp.text
    assert "program_version is required" in resp.json()["detail"]


@pytest.mark.parametrize(
    "timezone,local_today",
    [("Pacific/Kiritimati", "2026-09-27"), ("Pacific/Honolulu", "2026-09-26")],
)
def test_performed_date_uses_player_local_today_across_utc_boundary(api, timezone, local_today):
    client, db = api
    headers, version = _prepare_player(client, db)
    # FIXED_NOW is 2026-09-26T12:00Z: UTC+14 is already 2026-09-27, UTC-10 is 2026-09-26.
    ok = _sync_body(version=version, performed_timezone=timezone, performed_date=local_today)
    assert client.post("/workouts/sessions", headers=headers, json=ok).status_code == 201

    other_id = "22222222-2222-4222-8222-222222222222"
    ahead = (datetime.fromisoformat(local_today) + timedelta(days=1)).date().isoformat()
    rejected = _sync_body(
        client_session_id=other_id, version=version, performed_timezone=timezone, performed_date=ahead
    )
    resp = client.post("/workouts/sessions", headers=headers, json=rejected)
    assert resp.status_code == 400
    assert "future" in resp.json()["detail"].lower()


@pytest.mark.parametrize("timezone", ["Pacific/Kiritimati", "Pacific/Honolulu"])
def test_backdate_window_uses_local_capture_date(api, timezone):
    client, db = api
    headers, version = _prepare_player(client, db)
    captured_local = datetime(2026, 9, 26, 11, 30, tzinfo=UTC).astimezone(
        workouts_service.ZoneInfo(timezone)
    ).date()
    at_limit = (captured_local - timedelta(days=3)).isoformat()
    beyond = (captured_local - timedelta(days=4)).isoformat()

    ok = _sync_body(
        client_session_id="33333333-3333-4333-8333-333333333333",
        version=version,
        performed_timezone=timezone,
        performed_date=at_limit,
    )
    assert client.post("/workouts/sessions", headers=headers, json=ok).status_code == 201

    rejected = _sync_body(
        client_session_id="44444444-4444-4444-8444-444444444444",
        version=version,
        performed_timezone=timezone,
        performed_date=beyond,
    )
    resp = client.post("/workouts/sessions", headers=headers, json=rejected)
    assert resp.status_code == 400
    assert "3 days" in resp.json()["detail"]


def test_performed_date_after_the_capture_date_is_refused(api):
    """A draft can never claim a performed date later than when it was captured."""
    client, db = api
    headers, version = _prepare_player(client, db)
    # Captured yesterday (2026-09-25); the ceiling is the capture's local date.
    body = _sync_body(
        client_session_id="55555555-5555-4555-8555-555555555555",
        version=version,
        performed_date="2026-09-26",
        captured_at="2026-09-25T11:00:00+00:00",
    )
    resp = client.post("/workouts/sessions", headers=headers, json=body)
    assert resp.status_code == 400, resp.text
    assert "capture" in resp.json()["detail"].lower()
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0


def test_captured_at_within_clock_skew_is_accepted(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    body = _sync_body(version=version, captured_at=(FIXED_NOW + timedelta(minutes=5)).isoformat())
    assert client.post("/workouts/sessions", headers=headers, json=body).status_code == 201


def test_concurrent_duplicate_submission_commits_one_session(api):
    client, db = api
    _headers, version = _prepare_player(client, db)
    day_plan = ProgramDaySchema(
        day_name="Full A",
        day_order=1,
        exercises=[
            ProgramExerciseSchema(exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8),
            ProgramExerciseSchema(exercise_id="bp", exercise_name="Bench Press", target_reps_min=5, target_reps_max=8),
            ProgramExerciseSchema(exercise_id="row", exercise_name="Row", target_reps_min=5, target_reps_max=8),
        ],
    )
    sets_payload = [
        {
            "exercise": day_plan.exercises[0],
            "sets": [{"weight_kg": 100.0, "reps": 5, "rpe": 8.0}],
            "previous_perf": [],
        }
    ]

    barrier = threading.Barrier(2)
    outcomes = []
    errors = []

    def _worker():
        try:
            barrier.wait()
            outcomes.append(
                workouts_service.commit_logged_session(
                    db,
                    "p1",
                    day_plan.day_order,
                    4,
                    "",
                    sets_payload,
                    sync=workouts_service.SyncMetadata(
                        client_session_id=CLIENT_ID,
                        performed_date="2026-09-26",
                        performed_timezone="UTC",
                        program_version=version,
                        captured_at="2026-09-26T11:30:00+00:00",
                    ),
                    now_iso="2026-09-26T12:00:00+00:00",
                )
            )
        except Exception as exc:  # pragma: no cover - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(outcomes) == 2
    assert sum(1 for outcome in outcomes if outcome.created) == 1
    assert len({outcome.body["session_id"] for outcome in outcomes}) == 1

    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 1


def test_warmup_flag_is_honored_in_ledger_and_excluded_from_prs(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    body = _sync_body(version=version)
    # The warm-up is heavier than every working set, so any leak would be visible
    # as a 150 kg record row or event.
    body["sets"][0]["sets"] = [
        {"weight_kg": 150.0, "reps": 5, "rpe": 6.0, "is_warmup": True},
        {"weight_kg": 100.0, "reps": 5, "rpe": 8.0, "is_warmup": False},
    ]

    first = client.post("/workouts/sessions", headers=headers, json=body)
    assert first.status_code == 201, first.text

    db.switch_user("p1")
    # The first session is the exercise's baseline: it stores no record row (ADR 042).
    assert (
        db.conn.execute("SELECT COUNT(*) FROM personal_records WHERE exercise_id = 'sq'").fetchone()[0] == 0
    )

    second_body = _sync_body(
        version=version,
        client_session_id="22222222-2222-4222-8222-222222222222",
        performed_date="2026-09-25",
        captured_at="2026-09-25T11:00:00+00:00",
    )
    second_body["sets"] = body["sets"]
    second = client.post("/workouts/sessions", headers=headers, json=second_body)
    assert second.status_code == 201, second.text
    # The warm-up is excluded, so the second session only ties the baseline: a tie
    # is not a record, and a tie stores no history row either.
    assert second.json()["new_prs"] == []
    session_id = second.json()["session_id"]

    db.switch_user("p1")
    rows = db.conn.execute(
        "SELECT weight_kg, is_warmup FROM workout_sets WHERE session_id = ? AND exercise_id = 'sq' ORDER BY set_index",
        (session_id,),
    ).fetchall()
    assert [(row["weight_kg"], row["is_warmup"]) for row in rows] == [(150.0, 1), (100.0, 0)]
    assert (
        db.conn.execute("SELECT COUNT(*) FROM personal_records WHERE exercise_id = 'sq'").fetchone()[0] == 0
    )

    # A later working set beats the baseline; the 150 kg warm-up never can.
    third_body = _sync_body(
        version=version,
        client_session_id="33333333-3333-4333-8333-333333333333",
        performed_date="2026-09-24",
        captured_at="2026-09-24T11:00:00+00:00",
    )
    third_body["sets"][0]["sets"] = [
        {"weight_kg": 150.0, "reps": 5, "rpe": 6.0, "is_warmup": True},
        {"weight_kg": 105.0, "reps": 5, "rpe": 8.0, "is_warmup": False},
    ]
    third = client.post("/workouts/sessions", headers=headers, json=third_body)
    assert third.status_code == 201, third.text
    weight_event = next(
        event for event in third.json()["new_prs"] if event["record_type"] == "max_weight"
    )
    assert (weight_event["value"], weight_event["prev_value"]) == (105.0, 100.0)

    db.switch_user("p1")
    # The warm-up set is excluded from PR rows: only the working set is stored.
    prs = db.conn.execute(
        "SELECT value FROM personal_records WHERE exercise_id = 'sq' AND record_type = 'max_weight'"
    ).fetchall()
    assert [row["value"] for row in prs] == [105.0]


def test_unknown_exercise_id_is_400(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    body = _sync_body(version=version)
    body["sets"][0]["exercise"]["exercise_id"] = "not-a-catalog-exercise"

    resp = client.post("/workouts/sessions", headers=headers, json=body)
    assert resp.status_code == 400, resp.text
    assert "unknown exercise" in resp.json()["detail"].lower()
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 0


def test_player_b_cannot_read_player_a_commit_by_client_id(api):
    client, db = api
    headers_a, version = _prepare_player(client, db, username="p1")
    committed = client.post("/workouts/sessions", headers=headers_a, json=_sync_body(version=version))
    assert committed.status_code == 201, committed.text

    headers_b, _ = _prepare_player(client, db, username="p2")
    resp = client.get(f"/workouts/sessions/by-client-id/{CLIENT_ID}", headers=headers_b)
    assert resp.status_code == 404


def test_sync_fields_without_client_session_id_are_422(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    body = _sync_body(version=version)
    del body["client_session_id"]

    resp = client.post("/workouts/sessions", headers=headers, json=body)
    assert resp.status_code == 422, resp.text


def test_catalog_exercise_search_returns_matches_for_an_offline_unplanned_pick(api):
    client, db = api
    headers, _ = _prepare_player(client, db)

    resp = client.get("/workouts/exercises", headers=headers, params={"query": "squat"})
    assert resp.status_code == 200, resp.text
    matches = resp.json()["exercises"]
    assert [entry["id"] for entry in matches] == ["sq"]
    assert matches[0]["name"] == "Squat"


def test_catalog_exercise_search_requires_authentication(api):
    client, _ = api

    resp = client.get("/workouts/exercises", params={"query": "squat"})
    assert resp.status_code == 401, resp.text


@pytest.mark.parametrize("legacy", [False, True], ids=["offline-sync", "online"])
def test_checkpoint_review_is_created_once_when_commit_reaches_ten(api, legacy):
    client, db = api
    headers, version = _prepare_player(client, db)
    _seed_status_workouts(
        db, "p1", ["2026-09-17"] * 9
    )
    payload = _sync_body(
        client_session_id="22111111-1111-4111-8111-111111111111",
        version=version,
    )
    if legacy:
        for field in (
            "client_session_id",
            "performed_date",
            "performed_timezone",
            "program_version",
            "captured_at",
        ):
            payload.pop(field)

    first = client.post("/workouts/sessions", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["checkpoint"] == {"number": 10, "reached": True}

    retry = client.post("/workouts/sessions", headers=headers, json=payload)
    assert retry.status_code == (201 if legacy else 200), retry.text
    assert retry.json().get("checkpoint") == {"number": 10, "reached": True} if not legacy else "checkpoint" not in retry.json()
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM checkpoint_reviews").fetchone()[0] == 1
    assert db.conn.execute("SELECT checkpoint FROM checkpoint_reviews").fetchone()[0] == 10
    review = client.get("/checkpoint-reviews/10", headers=headers)
    assert review.status_code == 200, review.text
    assert review.json()["text"] == (
        "Checkpoint 10: 10 workouts since you started logging in MAYOS."
    )
    assert review.json()["text_is_template"] is True
    assert client.get("/checkpoint-reviews", headers=headers).json()[0]["opened"] is True


def test_checkpoint_commit_only_reports_a_new_review_insert(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    _seed_status_workouts(db, "p1", ["2026-09-26"] * 9)
    first = client.post(
        "/workouts/sessions",
        headers=headers,
        json=_sync_body(
            client_session_id="22133333-3333-4333-8333-333333333333",
            version=version,
        ),
    )
    assert first.status_code == 201, first.text
    assert first.json()["checkpoint"] == {"number": 10, "reached": True}

    db.switch_user("p1")
    db.conn.execute("DELETE FROM workout_sessions WHERE id = 'status-p1-0'")
    db.conn.commit()
    second = client.post(
        "/workouts/sessions",
        headers=headers,
        json=_sync_body(
            client_session_id="22144444-4444-4444-8444-444444444444",
            version=version,
        ),
    )
    assert second.status_code == 201, second.text
    assert second.json()["training_status"]["mayos_workouts"] == 10
    assert "checkpoint" not in second.json()
    db.switch_user("p1")
    reviews = db.conn.execute(
        "SELECT checkpoint, session_id FROM checkpoint_reviews"
    ).fetchall()
    assert [tuple(row) for row in reviews] == [(10, first.json()["session_id"])]


def test_backdated_offline_workout_sets_period_date_bounds(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    _seed_status_workouts(db, "p1", ["2026-09-26"] * 9)
    response = client.post(
        "/workouts/sessions",
        headers=headers,
        json=_sync_body(
            client_session_id="22155555-5555-4555-8555-555555555555",
            version=version,
            performed_date="2026-09-17",
            captured_at="2026-09-17T11:30:00+00:00",
        ),
    )
    assert response.status_code == 201, response.text
    assert response.json()["checkpoint"] == {"number": 10, "reached": True}

    db.switch_user("p1")
    review = db.conn.execute(
        "SELECT period_start, period_end, facts_json FROM checkpoint_reviews"
    ).fetchone()
    facts = json.loads(review["facts_json"])
    assert (review["period_start"], review["period_end"]) == (
        "2026-09-17",
        "2026-09-26",
    )
    assert (facts["weeks_met"], facts["weeks_counted"]) == (1, 2)


def test_imported_and_previously_reached_workouts_do_not_backfill_reviews(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    _seed_status_workouts(db, "p1", ["2026-09-17"] * 12)
    assert client.get("/checkpoint-reviews", headers=headers).json() == []
    next_workout = client.post(
        "/workouts/sessions", headers=headers, json=_sync_body(version=version)
    )
    assert next_workout.status_code == 201, next_workout.text
    assert next_workout.json()["training_status"]["mayos_workouts"] == 13
    assert "checkpoint" not in next_workout.json()
    db.switch_user("p1")
    assert db.conn.execute("SELECT COUNT(*) FROM checkpoint_reviews").fetchone()[0] == 0


def test_checkpoint_review_list_is_newest_first(api):
    client, db = api
    headers, _ = _prepare_player(client, db)
    _seed_status_workouts(db, "p1", ["2026-09-17"] * 25)
    for checkpoint in (10, 25):
        db.conn.execute(
            "INSERT INTO checkpoint_reviews "
            "(checkpoint, session_id, period_start, period_end, facts_json, rating_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                checkpoint,
                f"status-p1-{checkpoint - 1}",
                "2026-09-17",
                "2026-09-17",
                "{}",
                '[{"part":"Consistency","label":"Strong"}]',
                "2026-09-17T12:00:00+00:00",
            ),
        )
    db.conn.commit()

    response = client.get("/checkpoint-reviews", headers=headers)
    assert response.status_code == 200, response.text
    assert [review["checkpoint"] for review in response.json()] == [25, 10]


def test_imported_count_is_excluded_when_a_later_commit_reaches_checkpoint(api):
    client, db = api
    headers, version = _prepare_player(client, db)
    account_id = db.get_active_account_by_username("p1")["account_id"]
    db.catalog_conn.execute(
        "INSERT INTO account_imports"
        " (import_id, account_id, source_fingerprint, source_name, counts_json, opt_in_reference, imported_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("import-p1", account_id, "fingerprint", "snapshot.db", '{"workout_sessions": 9}', "test", "2026-01-01"),
    )
    db.catalog_conn.commit()
    _seed_status_workouts(db, "p1", ["2026-09-17"] * 18)
    response = client.post(
        "/workouts/sessions",
        headers=headers,
        json=_sync_body(
            client_session_id="22122222-2222-4222-8222-222222222222",
            version=version,
        ),
    )
    assert response.status_code == 201, response.text
    assert response.json()["training_status"]["mayos_workouts"] == 10
    assert response.json()["checkpoint"] == {"number": 10, "reached": True}
    db.switch_user("p1")
    review = db.conn.execute(
        "SELECT checkpoint, period_start, period_end FROM checkpoint_reviews"
    ).fetchone()
    assert tuple(review) == (10, "2026-09-17", "2026-09-26")


def test_workout_commit_emits_progression_alert_events_once_through_http(
    api, monkeypatch, recording_analytics
):
    client, db = api
    player_headers, version = _prepare_player(client, db, "progression-analytics-player")
    coach_headers = _make_coach(client, db, "progression-analytics-coach")
    assignment_id = _assign(client, coach_headers, player_headers)
    coach_id = db.get_active_account_by_username("progression-analytics-coach")["account_id"]

    original_capture = recording_analytics.capture

    def capture_after_alert_commit(account_id, event, event_uuid, properties):
        if event == "coach_alert_created":
            assert not db.catalog_conn.in_transaction
            row = db.catalog_conn.execute(
                "SELECT alert_id FROM coach_alerts WHERE coach_account_id = ?",
                (account_id,),
            ).fetchall()
            assert any(
                analytics.deterministic_event_uuid(event, f"{item[0]}:created")
                == event_uuid
                for item in row
            )
        original_capture(account_id, event, event_uuid, properties)

    monkeypatch.setattr(recording_analytics, "capture", capture_after_alert_commit)
    deload_payload = _sync_body(
        client_session_id="99111111-1111-4111-8111-111111111111",
        version=version,
        captured_at=FIXED_NOW.isoformat(),
    )
    deload_payload["readiness"] = 1
    deload_commit = client.post(
        "/workouts/sessions", headers=player_headers, json=deload_payload
    )
    assert deload_commit.status_code == 201, deload_commit.text
    assert deload_commit.json()["fatigue_post"]["reason_code"] == "acute_readiness_floor"
    prescription = client.get(
        "/workouts/prescription?day_order=1", headers=player_headers
    )
    assert prescription.status_code == 200, prescription.text
    assert prescription.json()["fatigue_info"]["reason_code"] == "acute_readiness_floor"
    deload_alert = next(
        row
        for row in client.get("/coach/alerts", headers=coach_headers).json()["alerts"]
        if row["kind"] == "deload_recommended"
    )
    assert deload_alert["message_code"] == "coach_alert.deload_recommended.v1"
    assert deload_alert["message_params"]["reason_code"] == "acute_readiness_floor"

    baseline_payload = _sync_body(
        client_session_id="99222222-2222-4222-8222-222222222222",
        version=version,
        captured_at=FIXED_NOW.isoformat(),
    )
    baseline_commit = client.post(
        "/workouts/sessions", headers=player_headers, json=baseline_payload
    )
    assert baseline_commit.status_code == 201, baseline_commit.text

    regression_payload = _sync_body(
        client_session_id="99333333-3333-4333-8333-333333333333",
        version=version,
        captured_at=FIXED_NOW.isoformat(),
    )
    for exercise in regression_payload["sets"]:
        for logged_set in exercise["sets"]:
            logged_set["weight_kg"] = float(logged_set["weight_kg"]) * 0.75
    regression_commit = client.post(
        "/workouts/sessions", headers=player_headers, json=regression_payload
    )
    assert regression_commit.status_code == 201, regression_commit.text
    replayed = client.post(
        "/workouts/sessions", headers=player_headers, json=regression_payload
    )
    assert replayed.status_code == 200, replayed.text
    alert_events = [
        event
        for event in recording_analytics.events
        if event["event"] == "coach_alert_created"
    ]
    assert {event["properties"]["alert_kind"] for event in alert_events} == {
        "deload_recommended",
        "performance_regression",
    }
    assert len({event["uuid"] for event in alert_events}) == len(alert_events)
    assert all(event["distinct_id"] == coach_id for event in alert_events)
    assert all(
        set(event["properties"]) == {"role", "platform", "app_version", "env", "alert_kind"}
        for event in alert_events
    )
    assert assignment_id == db.get_active_assignment_for_player(
        db.get_active_account_by_username("progression-analytics-player")["account_id"]
    )["assignment_id"]


def test_workout_commit_emits_missed_day_alert_after_attendance_write(api, recording_analytics):
    client, db = api
    player_headers, version = _prepare_player(client, db, "missed-commit-player")
    coach_headers = _make_coach(client, db, "missed-commit-coach")
    assignment_id = _assign(client, coach_headers, player_headers)
    coach_id = db.get_active_account_by_username("missed-commit-coach")["account_id"]
    db.switch_user("missed-commit-player")
    db.ledger.append_training_schedule(
        "missed-commit-player",
        [1, 2, 3, 4, 5, 6, 7],
        "UTC",
        "2026-09-01",
        "2026-09-01T00:00:00+00:00",
    )
    db.catalog_conn.execute(
        "UPDATE assignments SET started_at = ? WHERE assignment_id = ?",
        ("2026-09-01T00:00:00+00:00", assignment_id),
    )
    db.catalog_conn.commit()
    payload = _sync_body(
        client_session_id="99111111-2222-4222-8222-111111111111",
        version=version,
        performed_date="2026-09-26",
        captured_at=FIXED_NOW.isoformat(),
    )
    committed = client.post("/workouts/sessions", headers=player_headers, json=payload)
    assert committed.status_code == 201, committed.text
    replayed = client.post("/workouts/sessions", headers=player_headers, json=payload)
    assert replayed.status_code == 200, replayed.text
    events = [
        event
        for event in recording_analytics.events
        if event["event"] == "coach_alert_created"
        and event["properties"]["alert_kind"] == "missed_expected_days"
    ]
    assert len(events) == 1
    assert events[0]["distinct_id"] == coach_id
