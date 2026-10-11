"""Exact deterministic roster signal tests for ticket #310."""

import json
import sqlite3
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import (
    GeneratedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
)
from database.database_manager import DatabaseManager
from service import assignments as assignment_service
from service import coach as coach_service
from service import roster_snapshot as roster_snapshot_service
from service import stall_alerts
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    catalog_path = tmp_path / "catalog.db"
    catalog = sqlite3.connect(catalog_path)
    catalog.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    catalog.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    catalog.execute(
        "INSERT INTO exercises (id, name, body_part, target_muscle) VALUES"
        " ('sq', 'Squat', 'Upper Legs', 'Quads'), ('bp', 'Bench Press', 'Chest', 'Chest'),"
        " ('row', 'Row', 'Back', 'Back');"
    )
    catalog.commit()
    catalog.close()
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
        "/auth/register", json={"trainee_id": username, "password": "correct-horse-1"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_coach(client, db):
    coach = _register(client, "snapshotcoach")
    headers = _auth(coach["access_token"])
    invite = coach_service.issue_coach_invite(db, "snapshotcoach", actor="cli")
    assert invite["ok"]
    assert client.post("/coach/invite/redeem", headers=headers, json={"token": invite["token"]}).status_code == 200
    profile = client.put(
        "/coach/profile",
        headers=headers,
        json={"display_name": "Coach display", "bio": "", "specialization": "", "capacity": 20},
    )
    assert profile.status_code == 200, profile.text
    return headers, db.get_active_account_by_username("snapshotcoach")["account_id"]


def _assign(client, db, coach_headers, username):
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    player_auth = _register(client, username)
    headers = _auth(player_auth["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=headers,
        json={"token": token, "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    account = db.get_active_account_by_username(username)
    return {
        "headers": headers,
        "assignment_id": redeemed.json()["assignment"]["assignment_id"],
        "account_id": account["account_id"],
        "ledger_id": account["ledger_id"],
    }


def _day_plan():
    return ProgramDaySchema(
        day_name="Full A",
        day_order=1,
        exercises=[
            ProgramExerciseSchema(
                exercise_id="sq",
                exercise_name="Squat",
                slot_key="quad_compound",
                target_reps_min=5,
                target_reps_max=8,
            ),
            ProgramExerciseSchema(
                exercise_id="bp",
                exercise_name="Bench Press",
                slot_key="flat_press",
                target_reps_min=5,
                target_reps_max=8,
            ),
            ProgramExerciseSchema(
                exercise_id="row",
                exercise_name="Row",
                target_reps_min=5,
                target_reps_max=8,
            ),
        ],
    )


def _save_program(db, player):
    program = GeneratedProgramSchema(
        program_name="Snapshot plan",
        split_type="Full Body",
        weekly_frequency=1,
        days=[_day_plan()],
    )
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.save_training_program(program.model_dump())
        return int(ledger.get_active_program().version)


def _record_performed_day(db, player, on):
    session_id = uuid.uuid4().hex
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.log_workout_session(
            session_id,
            on,
            "Full A",
            f"{on}T10:00:00+00:00",
            f"{on}T11:00:00+00:00",
        )


def _record_session_fact(db, player, on, *, personal_record_exercise_id=None):
    session_id = uuid.uuid4().hex
    with db.open_ledger(player["ledger_id"]) as ledger:
        version = int(ledger.get_active_program().version)
        event = (
            [{"exercise_id": personal_record_exercise_id, "record_type": "max_e1rm"}]
            if personal_record_exercise_id
            else []
        )
        ledger.log_workout_session(
            session_id,
            on,
            "Full A",
            f"{on}T10:00:00+00:00",
            f"{on}T11:00:00+00:00",
            program_version=version,
        )
        ledger.record_session_commit(
            f"client-{session_id}",
            session_id,
            json.dumps({"new_prs": event}),
            f"{on}T11:00:00+00:00",
        )


def _insert_alert(db, coach_id, player, *, kind, details, state="new", created_at=None):
    alert_id = uuid.uuid4().hex
    now_iso = created_at or datetime.now(UTC).isoformat()
    inserted = db.insert_coach_alert(
        alert_id,
        player["assignment_id"],
        coach_id,
        player["account_id"],
        kind,
        f"snapshot-{alert_id}",
        details,
        now_iso,
    )
    if state == "acknowledged":
        acknowledged, changed = db.acknowledge_coach_alert_transition(
            alert_id, coach_id, now_iso
        )
        assert changed and acknowledged["state"] == "acknowledged"
    elif state == "resolved":
        resolved, changed = db.resolve_coach_alert_transition(
            alert_id, coach_id, now_iso, "coach"
        )
        assert changed and resolved["state"] == "resolved"
    return inserted


def _snapshot(db, coach_id, now):
    return roster_snapshot_service.roster_signal_snapshot(db, coach_id, now=now)


def test_legacy_assignment_enters_snapshot_only_after_disclosure_and_revokes(api):
    client, db = api
    coach_headers, coach_id = _make_coach(client, db)
    player = _assign(client, db, coach_headers, "legacyrosterplayer")
    instant = datetime(2026, 10, 11, 12, tzinfo=UTC)
    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE assignments SET roster_ai_disclosure_version = NULL, roster_ai_disclosed_at = NULL "
            "WHERE assignment_id = ?",
            (player["assignment_id"],),
        )
        db.catalog_conn.commit()

    before = client.get("/coach/roster/snapshot", headers=coach_headers)
    assert before.status_code == 200, before.text
    assert before.json()["snapshot"]["players"] == []
    assert client.get("/assignments/me", headers=player["headers"]).json()["roster_ai_disclosed_at"] is None

    recorded = client.post(
        "/assignments/me/roster-ai-disclosure", headers=player["headers"]
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["roster_ai_disclosure_version"] == assignment_service.ROSTER_AI_DISCLOSURE_VERSION
    assert recorded.json()["roster_ai_disclosed_at"]
    first_disclosed_at = recorded.json()["roster_ai_disclosed_at"]
    repeated_record = client.post(
        "/assignments/me/roster-ai-disclosure", headers=player["headers"]
    )
    assert repeated_record.json()["roster_ai_disclosed_at"] == first_disclosed_at
    after = client.get("/coach/roster/snapshot", headers=coach_headers)
    assert after.status_code == 200, after.text
    assert len(after.json()["snapshot"]["players"]) == 1

    ended = client.post("/assignments/me/end", headers=player["headers"])
    assert ended.status_code == 200, ended.text
    assert _snapshot(db, coach_id, instant)["snapshot"]["players"] == []


def test_deleted_assignment_player_is_not_snapshot_eligible(api):
    client, db = api
    coach_headers, coach_id = _make_coach(client, db)
    player = _assign(client, db, coach_headers, "deletedrosterplayer")
    instant = datetime(2026, 10, 11, 12, tzinfo=UTC)
    assert len(_snapshot(db, coach_id, instant)["snapshot"]["players"]) == 1

    deleted = db.delete_account(
        player["account_id"],
        now_iso="2026-10-11T12:00:00+00:00",
        ledger_id=player["ledger_id"],
    )
    assert deleted["ok"] is True
    assert _snapshot(db, coach_id, instant)["snapshot"]["players"] == []


def test_redeeming_after_ending_assignment_records_fresh_disclosure_and_eligibility(api):
    client, db = api
    coach_headers, coach_id = _make_coach(client, db)
    player = _assign(client, db, coach_headers, "renewedassignmentplayer")
    old_disclosed_at = "2000-01-01T00:00:00+00:00"
    db.catalog_conn.execute(
        "UPDATE assignments SET roster_ai_disclosed_at = ? WHERE assignment_id = ?",
        (old_disclosed_at, player["assignment_id"]),
    )
    db.catalog_conn.commit()

    ended = client.post("/assignments/me/end", headers=player["headers"])
    assert ended.status_code == 200, ended.text
    instant = datetime(2026, 10, 11, 12, tzinfo=UTC)
    assert _snapshot(db, coach_id, instant)["snapshot"]["players"] == []

    invite = client.post(
        "/coach/assignments/invites", headers=coach_headers
    )
    assert invite.status_code == 200, invite.text
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player["headers"],
        json={"token": invite.json()["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    new_assignment_id = redeemed.json()["assignment"]["assignment_id"]
    assert new_assignment_id != player["assignment_id"]

    old_row = db.catalog_conn.execute(
        "SELECT status, roster_ai_disclosure_version, roster_ai_disclosed_at "
        "FROM assignments WHERE assignment_id = ?",
        (player["assignment_id"],),
    ).fetchone()
    new_row = db.catalog_conn.execute(
        "SELECT status, roster_ai_disclosure_version, roster_ai_disclosed_at "
        "FROM assignments WHERE assignment_id = ?",
        (new_assignment_id,),
    ).fetchone()
    assert old_row[0] == "ended"
    assert old_row[2] == old_disclosed_at
    assert new_row[0] == "active"
    assert (
        new_row[1]
        == assignment_service.ROSTER_AI_DISCLOSURE_VERSION
    )
    assert new_row[2]
    assert new_row[2] != old_disclosed_at
    assert len(_snapshot(db, coach_id, instant)["snapshot"]["players"]) == 1


def test_attendance_signals_match_shared_evaluation_exactly(api):
    client, db = api
    coach_headers, coach_id = _make_coach(client, db)
    player = _assign(client, db, coach_headers, "attendancesignal")
    db.catalog_conn.execute(
        "UPDATE assignments SET started_at = ? WHERE assignment_id = ?",
        ("2026-09-08T00:00:00+00:00", player["assignment_id"]),
    )
    db.catalog_conn.commit()
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.append_training_schedule(
            player["ledger_id"], [1, 2, 3, 4, 5, 6, 7], "UTC", "2026-09-08",
            "2026-09-08T00:00:00+00:00",
        )
    for day in range(8, 29):
        _record_performed_day(db, player, f"2026-09-{day:02d}")
    db.upsert_roster_attendance(
        player["assignment_id"],
        0,
        "2026-09-28T12:00:00+00:00",
        timezone="UTC",
        last_workout_on="2026-09-28",
    )
    db.create_check_in(
        uuid.uuid4().hex,
        player["assignment_id"],
        coach_id,
        player["account_id"],
        "2026-09-30",
        "phone",
        "private check-in note",
        "2026-09-30T12:00:00+00:00",
    )
    db.create_program_request(
        uuid.uuid4().hex,
        player["assignment_id"],
        coach_id,
        player["account_id"],
        "exercise_substitution",
        1,
        "Full A",
        "sq",
        "bp",
        None,
        None,
        "private request reason",
        "2026-10-01T12:00:00+00:00",
    )

    signal = _snapshot(db, coach_id, datetime(2026, 10, 5, 12, tzinfo=UTC))["snapshot"]["players"][0]

    assert signal["missed_expected_days_7d"] == 5
    assert signal["missed_expected_days_14d"] == 5
    assert signal["adherence_pct_28d"] == 75.0
    assert signal["days_since_last_check_in"] == 5
    assert signal["urgency_inputs"] == {
        "new_lapsing_alerts": 0,
        "other_new_coach_alerts": 0,
        "pending_program_requests": 1,
        "missed_day_streak": 0,
        "follow_up_overdue_days": 0,
        "days_since_last_workout": 7,
        "stall_length_sessions": 0,
    }
    assert signal["bodyweight_trend"] is None
    assert signal["coaching_subscription_end"] is None
    assert "unanswered_program_requests" not in signal
    assert "pending_program_requests" not in signal


def test_no_schedule_keeps_attendance_null_and_uses_player_local_today(api):
    client, db = api
    coach_headers, coach_id = _make_coach(client, db)
    player = _assign(client, db, coach_headers, "localsignal")
    _record_performed_day(db, player, "2026-10-02")
    db.upsert_roster_attendance(
        player["assignment_id"],
        0,
        "2026-10-02T12:00:00+00:00",
        timezone="America/Los_Angeles",
        last_workout_on="2026-10-02",
    )
    db.create_check_in(
        uuid.uuid4().hex,
        player["assignment_id"],
        coach_id,
        player["account_id"],
        "2026-09-25",
        "phone",
        "",
        "2026-09-25T12:00:00+00:00",
    )

    signal = _snapshot(db, coach_id, datetime(2026, 10, 5, 1, tzinfo=UTC))["snapshot"]["players"][0]

    assert signal["missed_expected_days_7d"] is None
    assert signal["missed_expected_days_14d"] is None
    assert signal["adherence_pct_28d"] is None
    assert signal["weeks_without_personal_record"] is None
    assert signal["stall_threshold_met"] is False
    assert signal["days_since_last_check_in"] == 9
    assert signal["urgency_inputs"]["days_since_last_workout"] == 2
    assert signal["urgency_inputs"]["follow_up_overdue_days"] == 2


def test_personal_record_weeks_use_unbounded_pr_event_history(api):
    client, db = api
    coach_headers, coach_id = _make_coach(client, db)
    player = _assign(client, db, coach_headers, "oldprsignal")
    _save_program(db, player)
    _record_session_fact(db, player, "2026-07-01")
    _record_session_fact(db, player, "2026-07-02", personal_record_exercise_id="sq")
    for offset in range(33):
        day = (date(2026, 7, 3) + timedelta(days=offset)).isoformat()
        _record_session_fact(db, player, day)

    signal = _snapshot(db, coach_id, datetime(2026, 8, 6, 12, tzinfo=UTC))["snapshot"]["players"][0]

    assert signal["weeks_without_personal_record"] == 5
    assert signal["stall_threshold_met"] is True


def test_program_data_without_a_recent_record_can_stay_under_threshold(api):
    client, db = api
    coach_headers, coach_id = _make_coach(client, db)
    player = _assign(client, db, coach_headers, "newprogramsignal")
    _save_program(db, player)
    _record_session_fact(db, player, "2026-10-02")
    _record_session_fact(db, player, "2026-10-03", personal_record_exercise_id="sq")

    signal = _snapshot(db, coach_id, datetime(2026, 10, 5, 12, tzinfo=UTC))["snapshot"]["players"][0]

    assert signal["weeks_without_personal_record"] == 0
    assert signal["stall_threshold_met"] is False


def test_program_without_personal_record_uses_its_first_session_as_reference(api):
    client, db = api
    coach_headers, coach_id = _make_coach(client, db)
    player = _assign(client, db, coach_headers, "noprprogramsignal")
    _save_program(db, player)
    _record_session_fact(db, player, "2026-09-14")
    _record_session_fact(db, player, "2026-09-21")

    signal = _snapshot(db, coach_id, datetime(2026, 10, 5, 12, tzinfo=UTC))["snapshot"]["players"][0]

    assert signal["weeks_without_personal_record"] == 3
    assert signal["stall_threshold_met"] is True


def test_open_main_lift_regression_episode_counts_without_overshoot_badge(api):
    client, db = api
    coach_headers, coach_id = _make_coach(client, db)
    player = _assign(client, db, coach_headers, "regressionsignal")
    _save_program(db, player)
    _insert_alert(
        db,
        coach_id,
        player,
        kind="performance_regression",
        state="acknowledged",
        created_at="2026-06-01T12:00:00+00:00",
        details={
            "exercise_id": "sq",
            "top_load": 100.0,
            "e1rm_delta": -6.0,
            "status_badge": "LOAD INCREASE",
        },
    )

    signal = _snapshot(db, coach_id, datetime(2026, 10, 5, 12, tzinfo=UTC))["snapshot"]["players"][0]

    assert signal["effort_rising_same_load_main_lift"] is True


@pytest.mark.parametrize(
    ("exercise_id", "state"),
    [("row", "new"), ("sq", "resolved")],
)
def test_non_main_or_resolved_regression_does_not_raise_signal(api, exercise_id, state):
    client, db = api
    coach_headers, coach_id = _make_coach(client, db)
    player = _assign(client, db, coach_headers, f"negative{exercise_id}{state}")
    _save_program(db, player)
    _insert_alert(
        db,
        coach_id,
        player,
        kind="performance_regression",
        state=state,
        details={"exercise_id": exercise_id, "e1rm_delta": -6.0},
    )

    signal = _snapshot(db, coach_id, datetime(2026, 10, 5, 12, tzinfo=UTC))["snapshot"]["players"][0]

    assert signal["effort_rising_same_load_main_lift"] is False


def test_no_regression_episode_keeps_signal_false(api):
    client, db = api
    coach_headers, coach_id = _make_coach(client, db)
    player = _assign(client, db, coach_headers, "noregressionsignal")
    _save_program(db, player)

    signal = _snapshot(db, coach_id, datetime(2026, 10, 5, 12, tzinfo=UTC))["snapshot"]["players"][0]

    assert signal["effort_rising_same_load_main_lift"] is False


def test_urgency_rank_order_is_preserved_across_roster_players(api):
    client, db = api
    coach_headers, coach_id = _make_coach(client, db)
    first = _assign(client, db, coach_headers, "rankfirst")
    second = _assign(client, db, coach_headers, "ranksecond")
    third = _assign(client, db, coach_headers, "rankthird")
    _insert_alert(
        db,
        coach_id,
        first,
        kind="performance_regression",
        details={"exercise_id": "sq", "e1rm_delta": -6.0},
    )
    _insert_alert(
        db,
        coach_id,
        second,
        kind="missed_expected_days",
        details={"streak_start_date": "2026-10-01", "missed_count": 2},
    )

    response = _snapshot(db, coach_id, datetime(2026, 10, 5, 12, tzinfo=UTC))
    expected_assignment_order = [
        second["assignment_id"],
        first["assignment_id"],
        third["assignment_id"],
    ]

    assert [signal["urgency_rank"] for signal in response["snapshot"]["players"]] == [1, 2, 3]
    assert [entry["assignment_id"] for entry in response["client_mapping"]] == expected_assignment_order


def test_snapshot_serialization_excludes_identity_and_free_text(api):
    client, db = api
    coach_headers, coach_id = _make_coach(client, db)
    player = _assign(client, db, coach_headers, "IDENTIFY_USERNAME_41af")
    db.catalog_conn.execute(
        "UPDATE coach_profiles SET display_name = ? WHERE account_id = ?",
        ("IDENTIFY_DISPLAY_NAME_5c7d", coach_id),
    )
    db.catalog_conn.execute(
        "INSERT INTO trainee_emails (trainee_id, email, updated_at) VALUES (?, ?, ?)",
        ("IDENTIFY_USERNAME_41af", "IDENTIFY_CONTACT_9f12@example.com", "2026-10-01T00:00:00+00:00"),
    )
    db.catalog_conn.commit()
    version = _save_program(db, player)
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.set_assistant_memory("preferred_name", "IDENTIFY_PREFERRED_NAME_0aa8")
    db.create_check_in(
        uuid.uuid4().hex,
        player["assignment_id"],
        coach_id,
        player["account_id"],
        "2026-10-01",
        "phone",
        "IDENTIFY_FREE_TEXT_CHECKIN_78be",
        "2026-10-01T12:00:00+00:00",
    )
    db.create_program_request(
        uuid.uuid4().hex,
        player["assignment_id"],
        coach_id,
        player["account_id"],
        "exercise_substitution",
        version,
        "Full A",
        "sq",
        "bp",
        None,
        None,
        "IDENTIFY_FREE_TEXT_REQUEST_2b31",
        "2026-10-01T12:00:00+00:00",
    )

    response = client.get("/coach/roster/snapshot", headers=coach_headers)
    assert response.status_code == 200, response.text
    snapshot_json = json.dumps(response.json()["snapshot"])

    for private_value in (
        "IDENTIFY_USERNAME_41af",
        "IDENTIFY_PREFERRED_NAME_0aa8",
        "IDENTIFY_DISPLAY_NAME_5c7d",
        "IDENTIFY_CONTACT_9f12@example.com",
        player["account_id"],
        player["assignment_id"],
        "IDENTIFY_FREE_TEXT_CHECKIN_78be",
        "IDENTIFY_FREE_TEXT_REQUEST_2b31",
    ):
        assert private_value not in snapshot_json
    assert "player_username" not in response.json()["client_mapping"][0]


def test_eight_session_stall_coach_alert_threshold_is_unchanged(api):
    client, db = api
    coach_headers, coach_id = _make_coach(client, db)
    player = _assign(client, db, coach_headers, "stallalertthreshold")
    assignment = db.get_active_assignment_for_coach(coach_id, player["assignment_id"])

    below = stall_alerts.evaluate_commit(
        db, assignment, "seven-session-stall", 7, "2026-09-01"
    )
    at_threshold = stall_alerts.evaluate_commit(
        db, assignment, "eight-session-stall", 8, "2026-09-01"
    )

    assert below["alerts_created"] == 0
    assert at_threshold["alerts_created"] == 1
    alert = next(
        item
        for item in db.list_coach_alerts(coach_id, ("new",))
        if item["kind"] == stall_alerts.STALL_KIND
    )
    assert alert["details"]["stall_length"] == 8
