"""Product analytics contracts (ADR 040)."""

import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema
from database.database_manager import DatabaseManager
from service import analytics
from service._tokens import hash_token
from svc.app import create_app
from svc.auth import create_signup_ticket
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
TRACKING_PLAN = Path(__file__).resolve().parents[1] / "docs" / "ANALYTICS.md"


def _test_program() -> GeneratedProgramSchema:
    exercises = [
        ProgramExerciseSchema(
            exercise_id=f"ex{index}",
            exercise_name=f"Test exercise {index}",
            target_reps_min=8,
            target_reps_max=12,
        )
        for index in range(1, 4)
    ]
    day = ProgramDaySchema(day_name="Day 1", day_order=1, exercises=exercises)
    return GeneratedProgramSchema(
        program_name="Training program", split_type="Full body", weekly_frequency=4, days=[day]
    )


def _program_ledger_id_for_event(
    db: DatabaseManager, account_id: str, event: str, role: str
) -> str:
    owner_account_id = account_id
    if role == "coach":
        with db.catalog_locked() as connection:
            if event == "coach_program_published":
                row = connection.execute(
                    "SELECT player_account_id FROM assignments"
                    " WHERE coach_account_id = ? AND status = 'active' ORDER BY started_at DESC LIMIT 1",
                    (account_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT player_account_id FROM program_requests"
                    " WHERE coach_account_id = ? AND status = 'applied' ORDER BY resolved_at DESC LIMIT 1",
                    (account_id,),
                ).fetchone()
        assert row is not None
        owner_account_id = str(row[0])
    owner = db.get_account(owner_account_id)
    assert owner is not None
    return str(owner["ledger_id"])


def _assert_authoritative_write_committed(
    db: DatabaseManager, account_id: str, event: str, event_uuid: str, properties: dict
) -> None:
    assert not db.catalog_conn.in_transaction
    account = db.get_account(account_id)
    if event == "assignment_ended" and properties["ended_by"] == "account_deleted":
        assert db.is_live_account(account)
    elif event == "coach_capability_disabled":
        assert account is not None and not account["is_coach"]
    else:
        assert db.is_live_account(account)
    if event in {"onboarding_started", "onboarding_completed"}:
        with db.open_ledger(account["ledger_id"]) as ledger:
            assert not ledger.conn.in_transaction
            if event == "onboarding_started":
                assert ledger.get_onboarding_analytics_started_at()
                assert (
                    ledger.get_intake_state()
                    or ledger.load_onboarding_state()
                    or ledger.get_active_program()
                    or ledger.get_chat_history()
                )
            elif event == "onboarding_completed":
                assert ledger.get_onboarding_analytics_completed_at()
                intake_state = ledger.get_intake_state()
                assert intake_state is None or intake_state["status"] == "confirmed"
                assert intake_state is not None or ledger.get_active_program() is not None
    if event == "coach_capability_granted":
        assert account["is_coach"] is True
    elif event == "assignment_invite_issued":
        assert db.count_active_assignments_for_coach(account_id) == properties["active_roster_size"]
        invite_hashes = db.catalog_conn.execute(
            "SELECT token_hash FROM assignment_invites WHERE coach_account_id = ? ORDER BY created_at DESC",
            (account_id,),
        ).fetchall()
        assert any(
            analytics.deterministic_event_uuid(event, f"{row[0]}:issued") == event_uuid
            for row in invite_hashes
        )
    elif event == "assignment_started":
        active_rows = db.catalog_conn.execute(
            "SELECT assignment_id, coach_account_id, player_account_id, started_at FROM assignments"
            " WHERE coach_account_id = ? AND status = 'active'",
            (account_id,),
        ).fetchall()
        active = next(
            (
                row
                for row in active_rows
                if analytics.deterministic_event_uuid(event, f"{row[0]}:started") == event_uuid
            ),
            None,
        )
        assert active is not None
        assert active[1] == properties["coach_id"] == account_id
        assert db.count_active_assignments_for_coach(properties["coach_id"]) == properties["active_roster_size"]
        invite_created_at = db.catalog_conn.execute(
            "SELECT created_at FROM assignment_invites WHERE assignment_id = ?", (active[0],)
        ).fetchone()[0]
        time_since_invite = max(
            0,
            int(
                (
                    datetime.fromisoformat(active[3])
                    - datetime.fromisoformat(invite_created_at)
                ).total_seconds()
            ),
        )
        assert properties["time_since_invite_seconds"] == time_since_invite
    elif event == "assignment_ended":
        ended_assignments = db.catalog_conn.execute(
            "SELECT assignment_id, coach_account_id, player_account_id, status, started_at, ended_at FROM assignments"
            " WHERE ended_by = ?"
            " AND (coach_account_id = ? OR player_account_id = ?) ORDER BY ended_at DESC",
            (properties["ended_by"], account_id, account_id),
        ).fetchall()
        ended = next(
            (
                row
                for row in ended_assignments
                if analytics.deterministic_event_uuid(event, f"{row[0]}:ended") == event_uuid
            ),
            None,
        )
        assert ended is not None and ended[3] == "ended"
        if properties["ended_by"] == "account_deleted":
            coach_was_deleted = not db.is_live_account(db.get_account(ended[1]))
            expected_distinct_id = ended[2] if coach_was_deleted else ended[1]
            assert account_id == expected_distinct_id
        assert db.count_active_assignments_for_coach(ended[1]) == properties["active_roster_size"]
        duration = max(
            0, int((datetime.fromisoformat(ended[5]) - datetime.fromisoformat(ended[4])).total_seconds())
        )
        assert properties["duration_seconds"] == duration
    if event in {"program_request_created", "program_request_resolved"}:
        assert not db.catalog_conn.in_transaction
        assert db.catalog_conn.execute("SELECT COUNT(*) FROM program_requests").fetchone()[0] > 0
    if event in {"program_generated", "coach_program_published", "program_exercise_swapped"}:
        owner_ledger_id = _program_ledger_id_for_event(db, account_id, event, properties["role"])
        with db.open_ledger(owner_ledger_id) as ledger:
            assert not ledger.conn.in_transaction
            assert ledger.get_active_program() is not None
    if event in {
        "coach_alert_created",
        "coach_alert_acknowledged",
        "coach_alert_resolved",
    }:
        rows = db.catalog_conn.execute(
            "SELECT alert_id, kind, state FROM coach_alerts WHERE coach_account_id = ?",
            (account_id,),
        ).fetchall()
        alert = next(
            (
                row
                for row in rows
                if analytics.deterministic_event_uuid(event, f"{row[0]}:{event.removeprefix('coach_alert_')}")
                == event_uuid
            ),
            None,
        )
        assert alert is not None
        if event == "coach_alert_created":
            assert alert[1] == properties["alert_kind"] and alert[2] == "new"
        elif event == "coach_alert_acknowledged":
            assert alert[2] == "acknowledged"
        else:
            assert alert[2] == "resolved"
    if event == "check_in_recorded":
        rows = db.catalog_conn.execute(
            "SELECT check_in_id FROM check_ins WHERE coach_account_id = ?", (account_id,)
        ).fetchall()
        assert any(
            analytics.deterministic_event_uuid(event, f"{row[0]}:recorded") == event_uuid
            for row in rows
        )
    if event in {"coach_alerts_viewed", "player_history_viewed"}:
        rows = db.catalog_conn.execute(
            "SELECT assignment_id, event_kind, utc_day FROM coach_analytics_daily_markers"
            " WHERE coach_account_id = ?",
            (account_id,),
        ).fetchall()
        assert any(
            row[1] == event
            and analytics.deterministic_event_uuid(
                event,
                f"{account_id}:{row[2]}" if event == "coach_alerts_viewed"
                else f"{account_id}:{row[0]}:{row[2]}",
            )
            == event_uuid
            for row in rows
        )


@pytest.fixture
def analytics_api(tmp_path, monkeypatch, recording_analytics):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("MAYOS_RELEASE_PHASE", "closed_trial")
    monkeypatch.delenv("MAYOS_ENV", raising=False)
    monkeypatch.setenv("FLY_APP_NAME", "mayos-api")
    monkeypatch.setenv("GOOGLE_WEB_CLIENT_ID", "analytics-test-client")
    from svc.rate_limit import limiter

    limiter._storage.reset()
    catalog_path = tmp_path / "catalog.db"
    catalog_connection = sqlite3.connect(catalog_path)
    catalog_connection.executescript("""
        CREATE TABLE exercises (
            id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,
            equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT
        );
        CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);
    """)
    catalog_connection.executemany(
        "INSERT INTO exercises (id, name, body_part, target_muscle) VALUES (?, ?, ?, ?)",
        [(f"ex{index}", f"Test exercise {index}", "Chest", "Chest") for index in range(1, 5)],
    )
    catalog_connection.commit()
    catalog_connection.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "ledgers",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    analytics.override_analytics_preference_reader(db.analytics_preference_allows)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    sink = recording_analytics
    sink.capture_attempts = []
    original_capture = sink.capture

    def capture_after_committed_write(account_id, event, event_uuid, properties):
        _assert_authoritative_write_committed(db, account_id, event, event_uuid, properties)
        sink.capture_attempts.append(
            {"distinct_id": account_id, "event": event, "uuid": event_uuid, "properties": dict(properties)}
        )
        original_capture(account_id, event, event_uuid, properties)

    monkeypatch.setattr(sink, "capture", capture_after_committed_write)
    try:
        with TestClient(app) as client:
            yield client, db, sink
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(client: TestClient, username: str, *, client_header: str | None = None, **extra) -> dict[str, str]:
    headers = {"X-MAYOS-Client": client_header} if client_header else None
    response = client.post(
        "/auth/register",
        json={"trainee_id": username, "password": "correct-horse-1", **extra},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    if client_header:
        headers["X-MAYOS-Client"] = client_header
    return headers


def _event(sink, name: str) -> dict:
    return next(event for event in sink.events if event["event"] == name)


def _capture_attempt_count(sink, event_name: str, event_uuid: str) -> int:
    return sum(
        attempt["event"] == event_name and attempt["uuid"] == event_uuid
        for attempt in sink.capture_attempts
    )


def _fill_required_intake(client: TestClient, headers: dict[str, str]) -> None:
    disclosure = client.post("/onboarding/intake/disclosure", headers=headers)
    assert disclosure.status_code == 200, disclosure.text
    answers = {
        "gender": "female",
        "proportions": "balanced",
        "age": 29,
        "height_cm": 168.0,
        "weight_kg": 64.5,
        "training_age_years": 3.0,
        "current_goal": "build strength",
        "long_term_goal": "stay healthy",
        "weekly_frequency": 4,
        "equipment_access": "commercial gym",
        "injuries_or_limitations": "None",
        "stress_and_sleep": "moderate stress",
    }
    for field, value in answers.items():
        response = client.put(
            f"/onboarding/intake/answers/{field}", headers=headers, json={"value": value}
        )
        assert response.status_code == 200, (field, response.text)


def _install_fake_program_generator(monkeypatch) -> None:
    def fake_program(*_args, ledger, **_kwargs):
        program = _test_program()
        ledger.save_training_program(program.model_dump())
        return program, "ready"

    monkeypatch.setattr("service.programs.generate_program_pipeline", fake_program)
    monkeypatch.setattr("agent.program_generator.generate_program_pipeline", fake_program)


def _analytics_program() -> GeneratedProgramSchema:
    exercises = [
        ProgramExerciseSchema(
            exercise_id=exercise_id,
            exercise_name=f"Test exercise {exercise_id.removeprefix('ex')}",
            target_reps_min=8,
            target_reps_max=12,
        )
        for exercise_id in ("ex1", "ex3", "ex4")
    ]
    day = ProgramDaySchema(
        day_name="Full A",
        day_order=1,
        exercises=exercises,
    )
    return GeneratedProgramSchema(
        program_name="Private program title",
        split_type="Full body",
        weekly_frequency=1,
        days=[day],
    )


def _install_analytics_program_generators(monkeypatch) -> None:
    def fake_program(*_args, ledger, published_by_coach_account_id=None, **_kwargs):
        program = _analytics_program()
        if _kwargs.get("persist_program", True):
            ledger.save_training_program(
                program.model_dump(), published_by_coach_account_id=published_by_coach_account_id
            )
        return program, "private program markdown"

    def fake_coach_draft(_request, *, inference_call=None, ledger):
        return fake_program(ledger=ledger, persist_program=False)

    monkeypatch.setattr("service.programs.generate_program_pipeline", fake_program)
    monkeypatch.setattr("service.coach_programs.generate_program_draft_pipeline", fake_coach_draft)
    monkeypatch.setattr("service.profile.generate_program_pipeline", fake_program)
    monkeypatch.setattr("service.program_requests.generate_program_pipeline", fake_program)


def _assigned_analytics_player(client, db, player_headers, *, coach_username="analytics-coach"):
    from service import coach as coach_service

    coach_headers = _register(client, coach_username)
    issued = coach_service.issue_coach_invite(db, coach_username, actor="test")
    assert issued["ok"]
    redeemed_coach = client.post(
        "/coach/invite/redeem", headers=coach_headers, json={"token": issued["token"]}
    )
    assert redeemed_coach.status_code == 200, redeemed_coach.text
    configured = client.put(
        "/coach/profile",
        headers=coach_headers,
        json={"display_name": "Coach", "bio": "", "specialization": "", "capacity": 5},
    )
    assert configured.status_code == 200, configured.text
    invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert invite.status_code == 200, invite.text
    assignment = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite.json()["token"], "consent": True},
    )
    assert assignment.status_code == 200, assignment.text
    return coach_headers, assignment.json()["assignment"]["assignment_id"]


def _insert_alert(db, coach_account_id, player_account_id, assignment_id, kind="missed_expected_days"):
    inserted = db.insert_coach_alert(
        uuid.uuid4().hex,
        assignment_id,
        coach_account_id,
        player_account_id,
        kind,
        f"test:{uuid.uuid4().hex}",
        {},
        datetime.now(UTC).isoformat(),
    )
    assert inserted["created"]
    return inserted["alert"]


class RaisingAnalyticsSink:
    def capture(self, *_args, **_kwargs):
        raise RuntimeError("sink unavailable")

    def set_person(self, *_args, **_kwargs):
        raise RuntimeError("sink unavailable")

    def set_person_once(self, *_args, **_kwargs):
        raise RuntimeError("sink unavailable")

    def delete_person(self, *_args, **_kwargs):
        raise RuntimeError("sink unavailable")


def test_registration_and_onboarding_events_follow_successful_api_writes(analytics_api, monkeypatch):
    client, db, sink = analytics_api
    headers = _register(client, "analytics-player", client_header="android/1.2.3")

    account = db.get_active_account_by_username("analytics-player")
    created = _event(sink, "account_created")
    assert created["distinct_id"] == account["account_id"]
    assert created["properties"] == {
        "role": "player",
        "platform": "android",
        "app_version": "1.2.3",
        "env": "development",
        "signup_phase": "closed_trial",
        "invite_used": False,
    }
    assert sink.people[account["account_id"]] == {"is_player": True, "is_coach": False}
    assert sink.people_set_once[account["account_id"]] == {"signup_phase": "closed_trial"}

    view = client.get("/onboarding/intake", headers=headers)
    assert view.status_code == 200, view.text
    assert not [event for event in sink.events if event["event"].startswith("onboarding_")]

    _fill_required_intake(client, headers)
    assert len([event for event in sink.events if event["event"] == "onboarding_started"]) == 1
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.save_intake_answer("gender", "female", prefilled=True)

    _install_fake_program_generator(monkeypatch)
    completed = client.post("/onboarding/intake/confirm", headers=headers)
    assert completed.status_code == 200, completed.text
    replay = client.post("/onboarding/intake/confirm", headers=headers)
    assert replay.status_code == 200, replay.text

    completion_events = [event for event in sink.events if event["event"] == "onboarding_completed"]
    assert len(completion_events) == 1
    completion = completion_events[0]
    assert completion["distinct_id"] == account["account_id"]
    assert completion["properties"]["duration_seconds"] >= 0
    assert completion["properties"]["prefilled_fields_count"] == 1
    assert completion["properties"]["role"] == "player"
    assert completion["properties"]["env"] == "development"
    assert completion["uuid"] == analytics.deterministic_event_uuid(
        "onboarding_completed", account["account_id"]
    )
    generated = [event for event in sink.events if event["event"] == "program_generated"]
    assert len(generated) == 1
    assert generated[0]["properties"]["trigger"] == "onboarding"
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert ledger.get_intake_state()["status"] == "confirmed"


def test_account_analytics_preference_defaults_allowed_and_gates_every_server_path(
    analytics_api, monkeypatch
):
    client, db, sink = analytics_api
    headers = _register(client, "analytics-opt-out")
    account_id = db.get_active_account_by_username("analytics-opt-out")["account_id"]
    assert db.get_first_touch_acquisition(account_id) is not None
    sink.people_updates.clear()
    original_set_person = sink.set_person

    def record_after_preference_commit(distinct_id, properties):
        if "analytics_opted_out" in properties:
            assert not db.catalog_conn.in_transaction
            assert db.get_account(distinct_id)["analytics_allowed"] is not properties["analytics_opted_out"]
        original_set_person(distinct_id, properties)

    monkeypatch.setattr(sink, "set_person", record_after_preference_commit)

    account_info = client.get("/auth/me", headers=headers)
    assert account_info.status_code == 200, account_info.text
    assert account_info.json()["analytics_allowed"] is True
    assert db.get_account(account_id)["analytics_allowed"] is True

    disabled = client.put(
        "/auth/analytics-preference",
        headers=headers,
        json={"analytics_allowed": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json() == {"analytics_allowed": False}
    assert db.get_account(account_id)["analytics_allowed"] is False
    assert sink.people[account_id]["analytics_opted_out"] is True
    assert sink.people_updates == [
        {
            "distinct_id": account_id,
            "properties": {"analytics_opted_out": True},
            "operation": "set",
        }
    ]

    # All server sends share this boundary, including future event families and
    # mutable/set-once person updates.
    sink.events.clear()
    before_person = dict(sink.people[account_id])
    analytics.capture(
        analytics.AnalyticsEvent(
            account_id=account_id,
            event="account_created",
            domain_key=f"{account_id}:retry",
            role="player",
            properties={"signup_phase": "closed_trial", "invite_used": False},
        )
    )
    analytics.set_person(account_id, {"coached": True})
    analytics.set_person_once(account_id, {"signup_phase": "public"})
    assert sink.events == []
    assert sink.people[account_id] == before_person
    assert sink.people_set_once[account_id] == {"signup_phase": "closed_trial"}

    repeated = client.put(
        "/auth/analytics-preference",
        headers=headers,
        json={"analytics_allowed": False},
    )
    assert repeated.status_code == 200, repeated.text
    assert sink.people[account_id]["analytics_opted_out"] is True
    assert len(sink.people_updates) == 1
    refreshed = client.get("/auth/me", headers=headers)
    assert refreshed.json()["analytics_allowed"] is False

    with db.catalog_transaction(immediate=True):
        db.catalog_conn.execute(
            "CREATE TRIGGER reject_analytics_preference_delete "
            "BEFORE DELETE ON account_analytics_preferences "
            "BEGIN SELECT RAISE(ABORT, 'preference write failed'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="preference write failed"):
        client.put(
            "/auth/analytics-preference",
            headers=headers,
            json={"analytics_allowed": True},
        )
    assert db.get_account(account_id)["analytics_allowed"] is False
    assert len(sink.people_updates) == 1
    with db.catalog_transaction(immediate=True):
        db.catalog_conn.execute("DROP TRIGGER reject_analytics_preference_delete")

    enabled = client.put(
        "/auth/analytics-preference",
        headers=headers,
        json={"analytics_allowed": True},
    )
    assert enabled.status_code == 200, enabled.text
    assert db.get_account(account_id)["analytics_allowed"] is True
    assert sink.people[account_id]["analytics_opted_out"] is False
    assert sink.people_updates[-1] == {
        "distinct_id": account_id,
        "properties": {"analytics_opted_out": False},
        "operation": "set",
    }
    repeated_enable = client.put(
        "/auth/analytics-preference",
        headers=headers,
        json={"analytics_allowed": True},
    )
    assert repeated_enable.status_code == 200, repeated_enable.text
    assert len(sink.people_updates) == 2
    analytics.capture(
        analytics.AnalyticsEvent(
            account_id=account_id,
            event="account_created",
            domain_key=f"{account_id}:resumed",
            role="player",
            properties={"signup_phase": "closed_trial", "invite_used": False},
        )
    )
    assert len(sink.events) == 1

    disabled_again = client.put(
        "/auth/analytics-preference",
        headers=headers,
        json={"analytics_allowed": False},
    )
    assert disabled_again.status_code == 200, disabled_again.text
    assert len(sink.people_updates) == 3
    sink.events.clear()
    deleted = client.request(
        "DELETE",
        "/auth/account",
        headers=headers,
        json={"password": "correct-horse-1"},
    )
    assert deleted.status_code == 200, deleted.text
    assert sink.events == []
    assert db.catalog_conn.execute(
        "SELECT COUNT(*) FROM account_analytics_preferences WHERE account_id = ?",
        (account_id,),
    ).fetchone()[0] == 0
    assert db.get_first_touch_acquisition(account_id) is None
    assert account_id in sink.deleted_people


def test_opted_out_account_suppresses_http_onboarding_and_program_events(analytics_api, monkeypatch):
    client, db, sink = analytics_api
    _install_analytics_program_generators(monkeypatch)
    headers = _register(client, "analytics-opt-out-onboarding")
    account = db.get_active_account_by_username("analytics-opt-out-onboarding")
    disabled = client.put(
        "/auth/analytics-preference",
        headers=headers,
        json={"analytics_allowed": False},
    )
    assert disabled.status_code == 200, disabled.text
    sink.events.clear()

    _fill_required_intake(client, headers)
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.save_intake_answer("gender", "female", prefilled=True)
    completed = client.post("/onboarding/intake/confirm", headers=headers)
    generated = client.post("/programs/generate", headers=headers, json={})

    assert completed.status_code == 200, completed.text
    assert generated.status_code == 200, generated.text
    assert sink.events == []
    assert sink.people[account["account_id"]]["analytics_opted_out"] is True


def test_opted_out_accounts_suppress_http_assignment_events(analytics_api):
    client, db, sink = analytics_api
    coach_headers, coach_id = _grant_analytics_coach(client, db, "analytics-opt-out-coach")
    _set_analytics_coach_profile(client, coach_headers, capacity=1)
    invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert invite.status_code == 200, invite.text
    coach_opt_out = client.put(
        "/auth/analytics-preference",
        headers=coach_headers,
        json={"analytics_allowed": False},
    )
    assert coach_opt_out.status_code == 200, coach_opt_out.text

    player_headers = _register(client, "analytics-opt-out-player")
    player = db.get_active_account_by_username("analytics-opt-out-player")
    player_opt_out = client.put(
        "/auth/analytics-preference",
        headers=player_headers,
        json={"analytics_allowed": False},
    )
    assert player_opt_out.status_code == 200, player_opt_out.text
    sink.events.clear()

    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite.json()["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    ended = client.post("/assignments/me/end", headers=player_headers)

    assert ended.status_code == 200, ended.text
    assert sink.events == []
    assert sink.people[player["account_id"]]["analytics_opted_out"] is True
    assert sink.people[coach_id]["analytics_opted_out"] is True


def test_opted_out_player_assignment_redemption_is_attributed_to_allowed_coach(analytics_api):
    client, db, sink = analytics_api
    coach_headers, coach_id = _grant_analytics_coach(client, db, "analytics-mixed-coach")
    _set_analytics_coach_profile(client, coach_headers, capacity=1)
    invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert invite.status_code == 200, invite.text

    player_headers = _register(client, "analytics-mixed-player")
    player_id = db.get_active_account_by_username("analytics-mixed-player")["account_id"]
    opted_out = client.put(
        "/auth/analytics-preference",
        headers=player_headers,
        json={"analytics_allowed": False},
    )
    assert opted_out.status_code == 200, opted_out.text
    sink.events.clear()
    sink.capture_attempts.clear()
    sink.people_updates.clear()

    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite.json()["token"], "consent": True},
    )

    assert redeemed.status_code == 200, redeemed.text
    assert [event["event"] for event in sink.events] == ["assignment_started"]
    assignment_started = sink.events[0]
    assert assignment_started["distinct_id"] == coach_id
    assert assignment_started["properties"]["coach_id"] == coach_id
    assert all(event["distinct_id"] != player_id for event in sink.events)
    assert all(attempt["distinct_id"] != player_id for attempt in sink.capture_attempts)
    assert all(update["distinct_id"] != player_id for update in sink.people_updates)


def test_analytics_boundary_fails_closed_when_registry_preference_cannot_be_read(recording_analytics):
    account_id = "00000000-0000-0000-0000-000000000001"
    analytics.override_analytics_preference_reader(lambda _account_id: (_ for _ in ()).throw(OSError()))

    analytics.capture(
        analytics.AnalyticsEvent(
            account_id=account_id,
            event="account_created",
            domain_key=account_id,
            role="player",
            properties={"signup_phase": "closed_trial", "invite_used": False},
        )
    )
    analytics.set_person(account_id, {"is_player": True})
    analytics.set_person_once(account_id, {"signup_phase": "closed_trial"})

    assert recording_analytics.events == []
    assert recording_analytics.people == {}
    assert recording_analytics.people_set_once == {}
    analytics.override_analytics_preference_reader(None)


def test_server_events_resolve_android_web_and_missing_client_dimensions(analytics_api):
    client, db, sink = analytics_api
    preflight = client.options(
        "/auth/me",
        headers={
            "Origin": "http://localhost:7357",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-mayos-client",
        },
    )
    assert preflight.status_code == 200
    assert "x-mayos-client" in preflight.headers["access-control-allow-headers"].lower()

    _register(client, "analytics-android", client_header="android/1.2.3")
    _register(client, "analytics-web", client_header="web/2.4.0")
    _register(client, "analytics-unknown")

    for username, expected in (
        ("analytics-android", ("android", "1.2.3")),
        ("analytics-web", ("web", "2.4.0")),
        ("analytics-unknown", ("unknown", "unknown")),
    ):
        account = db.get_active_account_by_username(username)
        event = next(
            captured
            for captured in sink.events
            if captured["event"] == "account_created"
            and captured["distinct_id"] == account["account_id"]
        )
        assert (
            event["properties"]["platform"],
            event["properties"]["app_version"],
        ) == expected


def test_registration_failure_and_incomplete_confirmation_emit_no_event(analytics_api):
    client, _, sink = analytics_api
    headers = _register(client, "analytics-failure")
    failed_signup = client.post(
        "/auth/register",
        json={"trainee_id": "analytics-failure", "password": "correct-horse-1"},
    )
    assert failed_signup.status_code == 409
    assert len([event for event in sink.events if event["event"] == "account_created"]) == 1

    assert client.get("/onboarding/intake", headers=headers).status_code == 200
    assert client.post("/onboarding/intake/disclosure", headers=headers).status_code == 200
    incomplete = client.post("/onboarding/intake/confirm", headers=headers)
    assert incomplete.status_code == 400
    assert not [event for event in sink.events if event["event"] == "onboarding_completed"]


def test_google_completion_captures_only_after_account_creation(analytics_api):
    client, db, sink = analytics_api
    ticket = create_signup_ticket("analytics-google-subject")

    failed = client.post(
        "/auth/google/complete", json={"signup_ticket": ticket, "username": "bad username"}
    )
    assert failed.status_code == 400, failed.text
    assert not [event for event in sink.events if event["event"] == "account_created"]

    completed = client.post(
        "/auth/google/complete", json={"signup_ticket": ticket, "username": "analytics-google"}
    )
    assert completed.status_code == 200, completed.text
    account = db.get_active_account_by_username("analytics-google")
    created = [event for event in sink.events if event["event"] == "account_created"]
    assert len(created) == 1
    assert created[0]["distinct_id"] == account["account_id"]
    assert created[0]["properties"]["invite_used"] is False


def test_registration_stores_normalized_first_touch_once_and_login_does_not_replace_it(analytics_api):
    client, db, sink = analytics_api
    first_touch = {
        "utm_source": " Google-Ads ",
        "utm_medium": "paid search",
        "utm_campaign": "Summer_2026",
        "referrer_host": "https://www.Example.com/landing?email=private@example.com",
    }
    _register(client, "first-touch-player", first_touch=first_touch, client_header="web/1.2.3")
    account = db.get_active_account_by_username("first-touch-player")
    account_id = account["account_id"]
    stored = db.get_first_touch_acquisition(account_id)
    assert stored == {
        "utm_source": "google-ads",
        "utm_medium": None,
        "utm_campaign": "summer_2026",
        "referrer_host": "www.example.com",
        "referring_coach_id": None,
    }
    assert "private@example.com" not in str(stored)
    assert sink.people_set_once[account_id] == {
        "signup_phase": "closed_trial",
        "utm_source": "google-ads",
        "utm_campaign": "summer_2026",
        "referrer_host": "www.example.com",
    }

    columns = {
        row[1]
        for row in db.catalog_conn.execute("PRAGMA table_info(first_touch_acquisition)").fetchall()
    }
    assert columns == {
        "account_id",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "referrer_host",
        "referring_coach_id",
        "referred_at",
    }
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.catalog_conn.execute(
            "UPDATE first_touch_acquisition SET utm_source = 'later' WHERE account_id = ?", (account_id,)
        )
    db.catalog_conn.rollback()

    login = client.post(
        "/auth/login",
        json={
            "trainee_id": "first-touch-player",
            "password": "correct-horse-1",
            "first_touch": {"utm_source": "later-session"},
        },
    )
    assert login.status_code == 200, login.text
    retry = client.post(
        "/auth/register",
        json={
            "trainee_id": "first-touch-player",
            "password": "correct-horse-1",
            "first_touch": {"utm_source": "later-registration"},
        },
    )
    assert retry.status_code == 409
    assert db.get_first_touch_acquisition(account_id) == stored
    assert sink.people_set_once[account_id]["utm_source"] == "google-ads"
    assert len([event for event in sink.events if event["event"] == "account_created"]) == 1


def test_google_signup_accepts_only_device_parsed_install_referrer_labels(analytics_api):
    client, db, sink = analytics_api
    ticket = create_signup_ticket("analytics-google-first-touch")
    referrer = "utm_source=google-play&utm_medium=organic&utm_campaign=trial_launch&gclid=private-click-id"
    raw_referrer = client.post(
        "/auth/google/complete",
        json={
            "signup_ticket": ticket,
            "username": "google-first-touch",
            "first_touch": {"install_referrer": referrer},
        },
    )
    assert raw_referrer.status_code == 422
    completed = client.post(
        "/auth/google/complete",
        json={
            "signup_ticket": ticket,
            "username": "google-first-touch",
            "first_touch": {
                "utm_source": "google-play",
                "utm_medium": "organic",
                "utm_campaign": "trial_launch",
            },
        },
    )
    assert completed.status_code == 200, completed.text
    account = db.get_active_account_by_username("google-first-touch")
    stored = db.get_first_touch_acquisition(account["account_id"])
    assert stored == {
        "utm_source": "google-play",
        "utm_medium": "organic",
        "utm_campaign": "trial_launch",
        "referrer_host": None,
        "referring_coach_id": None,
    }
    assert "gclid" not in str(stored)
    assert sink.people_set_once[account["account_id"]] == {
        "signup_phase": "closed_trial",
        "utm_source": "google-play",
        "utm_medium": "organic",
        "utm_campaign": "trial_launch",
    }


def test_first_assignment_invite_sets_referring_coach_once_after_commit(analytics_api):
    client, db, sink = analytics_api
    player_headers = _register(client, "analytics-referred-player")
    _assigned_analytics_player(client, db, player_headers)

    player = db.get_active_account_by_username("analytics-referred-player")
    coach = db.get_active_account_by_username("analytics-coach")
    record = db.get_first_touch_acquisition(player["account_id"])
    assert record["referring_coach_id"] == coach["account_id"]
    assert db.catalog_conn.execute(
        "SELECT referred_at FROM first_touch_acquisition WHERE account_id = ?",
        (player["account_id"],),
    ).fetchone()[0]
    assert sink.people_set_once[player["account_id"]]["referring_coach_id"] == coach["account_id"]
    assert not db.catalog_conn.in_transaction

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.catalog_conn.execute(
            "UPDATE first_touch_acquisition SET referring_coach_id = ?, referred_at = ? "
            "WHERE account_id = ?",
            ("0" * 32, datetime.now(UTC).isoformat(), player["account_id"]),
        )
    db.catalog_conn.rollback()


def test_legacy_start_captures_once_after_its_first_write(analytics_api):
    client, db, sink = analytics_api
    headers = _register(client, "analytics-legacy-start")
    account = db.get_active_account_by_username("analytics-legacy-start")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.save_onboarding_state(
            {
                "intake_step": 1,
                "is_complete": False,
                "profile_data": None,
                "messages": [{"role": "assistant", "content": "What is your goal?"}],
            }
        )

    for _ in range(2):
        started = client.post("/onboarding/start", headers=headers)
        assert started.status_code == 200, started.text

    onboarding_events = [event for event in sink.events if event["event"].startswith("onboarding_")]
    assert [event["event"] for event in onboarding_events] == ["onboarding_started"]


def test_legacy_completion_is_captured_once_across_a_retry(analytics_api, monkeypatch):
    from agent.onboarding_graph import onboarding_graph

    client, db, sink = analytics_api
    headers = _register(client, "analytics-legacy-complete")
    account = db.get_active_account_by_username("analytics-legacy-complete")
    saved_state = {
        "intake_step": 3,
        "is_complete": False,
        "profile_data": {"gender": "female", "current_goal": "build strength"},
        "messages": [],
    }
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.save_onboarding_state(saved_state)

    monkeypatch.setattr(onboarding_graph, "invoke", lambda state, **_kwargs: state)
    _install_fake_program_generator(monkeypatch)
    for _ in range(2):
        completed = client.post("/onboarding/complete", headers=headers)
        assert completed.status_code == 200, completed.text

    completions = [event for event in sink.events if event["event"] == "onboarding_completed"]
    assert len(completions) == 1
    assert completions[0]["properties"]["prefilled_fields_count"] == 2
    generated = [event for event in sink.events if event["event"] == "program_generated"]
    assert len(generated) == 1
    assert generated[0]["properties"]["trigger"] == "onboarding"


def test_raising_sink_does_not_fail_structured_or_legacy_completion(analytics_api, monkeypatch):
    client, db, _sink = analytics_api
    analytics.set_sink(RaisingAnalyticsSink())

    structured_headers = _register(client, "analytics-raising-confirm")
    _fill_required_intake(client, structured_headers)
    _install_fake_program_generator(monkeypatch)
    confirmed = client.post("/onboarding/intake/confirm", headers=structured_headers)
    assert confirmed.status_code == 200, confirmed.text

    legacy_headers = _register(client, "analytics-raising-legacy")
    account = db.get_active_account_by_username("analytics-raising-legacy")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.save_training_program(_test_program().model_dump())
        ledger.save_onboarding_state(
            {"intake_step": 1, "is_complete": False, "profile_data": None, "messages": []}
        )
    completed = client.post("/onboarding/complete", headers=legacy_headers)
    assert completed.status_code == 200, completed.text


def test_program_and_request_events_follow_committed_api_operations(analytics_api, monkeypatch):
    client, db, sink = analytics_api
    _install_analytics_program_generators(monkeypatch)

    player_headers = _register(client, "analytics-program-player")
    player_account = db.get_active_account_by_username("analytics-program-player")
    player_id = player_account["account_id"]
    player_headers = {**player_headers, "X-MAYOS-Client": "android/2.4.1"}

    generated = client.post("/programs/generate", headers=player_headers, json={})
    assert generated.status_code == 200, generated.text
    generated_events = [event for event in sink.events if event["event"] == "program_generated"]
    assert len(generated_events) == 1
    assert generated_events[0]["distinct_id"] == player_id
    assert generated_events[0]["properties"] == {
        "role": "player",
        "platform": "android",
        "app_version": "2.4.1",
        "env": "development",
        "trigger": "player_request",
        "day_count": 1,
    }

    with db.open_ledger(player_account["ledger_id"]) as ledger:
        ledger.upsert_player_profile(
            {"equipment_access": "Commercial gym", "weekly_frequency": 1, "rep_preference": "balanced"}
        )
    rebuilt = client.put("/profile", headers=player_headers, json={"weekly_frequency": 2})
    assert rebuilt.status_code == 200, rebuilt.text
    generated_events = [event for event in sink.events if event["event"] == "program_generated"]
    assert [event["properties"]["trigger"] for event in generated_events] == [
        "player_request",
        "profile_rebuild",
    ]

    swap = client.post(
        "/programs/active/substitutions",
        headers=player_headers,
        json={
            "day_name": "Full A",
            "exercise_id": "ex1",
            "replacement_exercise_id": "ex2",
            "expected_active_version": 2,
        },
    )
    assert swap.status_code == 200, swap.text
    assert swap.json()["version"] == 3
    player_swaps = [event for event in sink.events if event["event"] == "program_exercise_swapped"]
    assert len(player_swaps) == 1
    assert player_swaps[0]["properties"]["role"] == "player"

    undone = client.post(
        "/programs/active/substitutions/undo",
        headers=player_headers,
        json={"restore_version": 2, "expected_active_version": 3},
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["version"] == 4
    player_swaps = [event for event in sink.events if event["event"] == "program_exercise_swapped"]
    assert len(player_swaps) == 2

    failed_swap = client.post(
        "/programs/active/substitutions",
        headers=player_headers,
        json={"day_name": "Full A", "exercise_id": "ex1", "replacement_exercise_id": "missing"},
    )
    assert failed_swap.status_code == 404
    assert len([event for event in sink.events if event["event"] == "program_exercise_swapped"]) == 2

    coach_headers, assignment_id = _assigned_analytics_player(client, db, player_headers)
    coach_headers = {**coach_headers, "X-MAYOS-Client": "web/5.1.0"}
    for expected_first in (True, False):
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
        publication_events = [event for event in sink.events if event["event"] == "coach_program_published"]
        assert publication_events[-1]["properties"] == {
            "role": "coach",
            "platform": "web",
            "app_version": "5.1.0",
            "env": "development",
            "day_count": 1,
            "first_for_assignment": expected_first,
            "is_coaching_action": True,
        }

    invalid_request = client.post(
        "/assignments/me/program-requests",
        headers=player_headers,
        json={"kind": "split_change", "desired_weekly_frequency": 2, "reason": "   "},
    )
    assert invalid_request.status_code == 400
    assert not [event for event in sink.events if event["event"] == "program_request_created"]

    created_request = client.post(
        "/assignments/me/program-requests",
        headers=player_headers,
        json={
            "kind": "exercise_substitution",
            "day_name": "Full A",
            "exercise_id": "ex1",
            "replacement_exercise_id": "ex2",
            "reason": "PRIVATE_REQUEST_SENTINEL",
        },
    )
    assert created_request.status_code == 200, created_request.text
    apply_path = (
        f"/coach/assignments/{assignment_id}/program-requests/"
        f"{created_request.json()['request_id']}/apply"
    )
    applied = client.post(apply_path, headers=coach_headers)
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    replayed_apply = client.post(apply_path, headers=coach_headers)
    assert replayed_apply.status_code == 400
    assert len([event for event in sink.events if event["event"] == "program_request_resolved"]) == 1

    split_request = client.post(
        "/assignments/me/program-requests",
        headers=player_headers,
        json={"kind": "split_change", "desired_weekly_frequency": 3, "reason": "PRIVATE_SPLIT_SENTINEL"},
    )
    assert split_request.status_code == 200, split_request.text
    split_applied = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{split_request.json()['request_id']}/apply",
        headers=coach_headers,
    )
    assert split_applied.status_code == 200, split_applied.text
    generated_events = [event for event in sink.events if event["event"] == "program_generated"]
    assert generated_events[-1]["properties"]["trigger"] == "coach_request"
    assert generated_events[-1]["properties"]["role"] == "coach"

    declined_request = client.post(
        "/assignments/me/program-requests",
        headers=player_headers,
        json={"kind": "split_change", "desired_weekly_frequency": 2, "reason": "PRIVATE_REASON_SENTINEL"},
    )
    assert declined_request.status_code == 200, declined_request.text
    declined = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/"
        f"{declined_request.json()['request_id']}/decline",
        headers=coach_headers,
        json={"response": "PRIVATE_RESPONSE_SENTINEL"},
    )
    assert declined.status_code == 200, declined.text

    cancelled_request = client.post(
        "/assignments/me/program-requests",
        headers=player_headers,
        json={"kind": "split_change", "desired_weekly_frequency": 3, "reason": "PRIVATE_CANCEL_SENTINEL"},
    )
    assert cancelled_request.status_code == 200, cancelled_request.text
    cancelled = client.post(
        f"/assignments/me/program-requests/{cancelled_request.json()['request_id']}/cancel",
        headers=player_headers,
    )
    assert cancelled.status_code == 200, cancelled.text

    all_events = [event for event in sink.events if event["event"].startswith("program_") or event["event"] == "coach_program_published"]
    assert len([event for event in all_events if event["event"] == "program_generated"]) == 3
    assert len([event for event in all_events if event["event"] == "coach_program_published"]) == 2
    swaps = [event for event in all_events if event["event"] == "program_exercise_swapped"]
    assert [event["properties"]["role"] for event in swaps] == ["player", "player", "coach"]
    requests_created = [event for event in all_events if event["event"] == "program_request_created"]
    assert len(requests_created) == 4
    assert {event["properties"]["kind"] for event in requests_created} == {
        "exercise_substitution",
        "split_change",
    }
    resolutions = [event for event in all_events if event["event"] == "program_request_resolved"]
    assert {event["properties"]["outcome"] for event in resolutions} == {"applied", "declined", "cancelled"}
    assert all(event["properties"]["time_open_seconds"] >= 0 for event in resolutions)
    assert all(event["properties"]["is_coaching_action"] for event in resolutions if event["properties"]["role"] == "coach")
    assert next(event for event in resolutions if event["properties"]["outcome"] == "cancelled")["properties"]["is_coaching_action"] is False
    for event in all_events:
        assert "PRIVATE_" not in repr(event)
        assert event["distinct_id"] not in {"analytics-program-player", "analytics-coach"}

    with db.open_ledger(player_account["ledger_id"]) as ledger:
        assert not ledger.conn.in_transaction
        assert ledger.get_active_program().version == 8
    assert not db.catalog_conn.in_transaction


def test_failed_program_generation_emits_no_event(analytics_api, monkeypatch):
    client, _, sink = analytics_api
    headers = _register(client, "analytics-program-failure")

    def fail_generation(*_args, **_kwargs):
        raise ValueError("generation rejected")

    monkeypatch.setattr("service.programs.generate_program_pipeline", fail_generation)
    failed = client.post("/programs/generate", headers=headers, json={})
    assert failed.status_code == 400
    assert not [event for event in sink.events if event["event"] == "program_generated"]


def test_active_program_lazy_synthesis_emits_once_with_synthesized_trigger(analytics_api, monkeypatch):
    client, db, sink = analytics_api
    headers = _register(client, "analytics-synthesized")
    headers["X-MAYOS-Client"] = "web/4.2.0"
    account = db.get_active_account_by_username("analytics-synthesized")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.upsert_player_profile(
            {"equipment_access": "Commercial gym", "weekly_frequency": 1, "rep_preference": "balanced"}
        )
    _install_fake_program_generator(monkeypatch)

    for _ in range(2):
        response = client.get("/programs/active", headers=headers)
        assert response.status_code == 200, response.text
    generated = [event for event in sink.events if event["event"] == "program_generated"]
    assert len(generated) == 1
    assert generated[0]["properties"]["trigger"] == "synthesized"
    assert generated[0]["properties"]["platform"] == "web"


def test_chat_regeneration_and_swap_emit_once_through_http(analytics_api, monkeypatch):
    client, db, sink = analytics_api
    headers = _register(client, "analytics-chat")
    account = db.get_active_account_by_username("analytics-chat")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.save_training_program(_analytics_program().model_dump())
    _install_fake_program_generator(monkeypatch)

    def fake_turn(state, *, ledger, store, **_kwargs):
        user_text = state["messages"][-1].content
        if user_text == "rebuild my split":
            program = _analytics_program()
            ledger.save_training_program(program.model_dump())
            state["program_change"] = "regenerated"
        else:
            from service.program_substitution import ProgramSubstitution, substitute_program_exercise

            active = ledger.get_active_program()
            result = substitute_program_exercise(
                ledger,
                store,
                active,
                ProgramSubstitution(
                    day_name=active.days[0].day_name,
                    exercise_id=active.days[0].exercises[0].exercise_id,
                    replacement_exercise_id="ex2",
                ),
            )
            assert result["ok"]
            state["program_change"] = "swapped"
        state["program_updated"] = True
        state["response_content"] = "Your program was updated."
        yield state["response_content"]

    monkeypatch.setattr("svc.routers.chat.stream_assistant_turn", fake_turn)
    for content in ("rebuild my split", "swap this exercise"):
        with client.stream("POST", "/chat/messages", headers=headers, json={"content": content}) as response:
            payload = response.read().decode()
        assert response.status_code == 200
        assert '"done": true' in payload
    program_events = [
        event for event in sink.events
        if event["event"] in {"program_generated", "program_exercise_swapped"}
    ]
    assert [event["event"] for event in program_events] == [
        "program_generated",
        "program_exercise_swapped",
    ]
    assert program_events[0]["properties"]["trigger"] == "player_request"


def test_recording_sink_keeps_every_capture_call_and_coach_events_use_player_owner(recording_analytics):
    from types import SimpleNamespace

    from service.program_analytics import ProgramAnalyticsActor, capture_program_generated

    analytics.override_analytics_preference_reader(lambda _account_id: True)
    account_id = uuid.uuid4().hex
    event = analytics.AnalyticsEvent(
        account_id=account_id,
        event="onboarding_started",
        domain_key=account_id,
        role="player",
    )
    analytics.capture(event)
    analytics.capture(event)
    assert len(recording_analytics.events) == 2

    recording_analytics.events.clear()
    coach = ProgramAnalyticsActor(account_id, "coach")
    program = SimpleNamespace(version=1, days=[])
    capture_program_generated(coach, "coach_request", program, player_account_id="player-one")
    capture_program_generated(coach, "coach_request", program, player_account_id="player-two")
    assert recording_analytics.events[0]["uuid"] != recording_analytics.events[1]["uuid"]


def test_raising_sink_does_not_fail_program_generation(analytics_api, monkeypatch):
    client, db, _sink = analytics_api
    _install_analytics_program_generators(monkeypatch)
    headers = _register(client, "analytics-program-raising")
    account = db.get_active_account_by_username("analytics-program-raising")
    analytics.set_sink(RaisingAnalyticsSink())

    generated = client.post("/programs/generate", headers=headers, json={})
    assert generated.status_code == 200, generated.text
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert ledger.get_active_program() is not None


def test_raising_sink_does_not_fail_program_request_or_swap_operations(analytics_api, monkeypatch):
    client, db, _sink = analytics_api
    _install_analytics_program_generators(monkeypatch)
    player_headers = _register(client, "analytics-raising-requests")
    account = db.get_active_account_by_username("analytics-raising-requests")
    assert client.post("/programs/generate", headers=player_headers, json={}).status_code == 200
    coach_headers, assignment_id = _assigned_analytics_player(client, db, player_headers)

    analytics.set_sink(RaisingAnalyticsSink())
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

    def create_split_request(frequency):
        return client.post(
            "/assignments/me/program-requests",
            headers=player_headers,
            json={"kind": "split_change", "desired_weekly_frequency": frequency, "reason": "private"},
        )

    split_request = create_split_request(3)
    assert split_request.status_code == 200, split_request.text
    applied = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{split_request.json()['request_id']}/apply",
        headers=coach_headers,
    )
    assert applied.status_code == 200, applied.text

    declined_request = create_split_request(2)
    assert declined_request.status_code == 200, declined_request.text
    declined = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{declined_request.json()['request_id']}/decline",
        headers=coach_headers,
        json={"response": "not now"},
    )
    assert declined.status_code == 200, declined.text

    cancelled_request = create_split_request(2)
    assert cancelled_request.status_code == 200, cancelled_request.text
    cancelled = client.post(
        f"/assignments/me/program-requests/{cancelled_request.json()['request_id']}/cancel",
        headers=player_headers,
    )
    assert cancelled.status_code == 200, cancelled.text

    swap_request = client.post(
        "/assignments/me/program-requests",
        headers=player_headers,
        json={
            "kind": "exercise_substitution",
            "day_name": "Full A",
            "exercise_id": "ex1",
            "replacement_exercise_id": "ex2",
            "reason": "private swap request",
        },
    )
    assert swap_request.status_code == 200, swap_request.text
    swap_applied = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{swap_request.json()['request_id']}/apply",
        headers=coach_headers,
    )
    assert swap_applied.status_code == 200, swap_applied.text

    revoked = client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers)
    assert revoked.status_code == 200, revoked.text
    with db.open_ledger(account["ledger_id"]) as ledger:
        active = ledger.get_active_program()
    player_swap = client.post(
        "/programs/active/substitutions",
        headers=player_headers,
        json={
            "day_name": active.days[0].day_name,
            "exercise_id": active.days[0].exercises[-1].exercise_id,
            "replacement_exercise_id": "ex1",
        },
    )
    assert player_swap.status_code == 200, player_swap.text


def test_account_created_marks_invite_use_and_release_phase_once(analytics_api, monkeypatch):
    client, db, sink = analytics_api
    monkeypatch.setenv("MAYOS_RELEASE_PHASE", "public")
    code = "coach-invite-code-123"
    expires = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert db.issue_new_account_coach_invite(hash_token(code), "invited-coach", expires)
    _register(
        client,
        "invited-coach",
        coach_invite_code=code,
        first_touch={"utm_source": "owner-invite"},
    )
    account = db.get_active_account_by_username("invited-coach")
    assert db.get_first_touch_acquisition(account["account_id"])["utm_source"] == "owner-invite"

    event = _event(sink, "account_created")
    assert event["properties"]["signup_phase"] == "public"
    assert event["properties"]["invite_used"] is True
    grant = _event(sink, "coach_capability_granted")
    assert grant["distinct_id"] == event["distinct_id"]
    assert grant["properties"]["role"] == "coach"
    assert sink.events.index(event) < sink.events.index(grant)
    assert _capture_attempt_count(sink, "account_created", event["uuid"]) == 1
    assert _capture_attempt_count(sink, "coach_capability_granted", grant["uuid"]) == 1
    assert sink.people[event["distinct_id"]] == {
        "is_player": True,
        "is_coach": True,
        "active_roster_size": 0,
    }
    assert sink.people_set_once[event["distinct_id"]] == {
        "signup_phase": "public",
        "utm_source": "owner-invite",
    }


def test_recording_sink_rejects_unknown_contract_and_private_values(recording_analytics):
    sink = recording_analytics
    account_id = uuid.uuid4().hex
    valid = {
        "role": "player",
        "platform": "unknown",
        "app_version": "unknown",
        "env": "development",
        "signup_phase": "closed_trial",
        "invite_used": False,
    }
    with pytest.raises(analytics.AnalyticsContractError):
        sink.capture(account_id, "unknown_event", analytics.deterministic_event_uuid("unknown_event", account_id), valid)
    with pytest.raises(analytics.AnalyticsContractError):
        sink.capture(
            account_id,
            "account_created",
            analytics.deterministic_event_uuid("account_created", account_id),
            {**valid, "username": "alice"},
        )
    with pytest.raises(analytics.AnalyticsContractError):
        sink.capture(
            account_id,
            "account_created",
            analytics.deterministic_event_uuid("account_created", account_id),
            {**valid, "env": "alice@example.com"},
        )
    with pytest.raises(analytics.AnalyticsContractError):
        sink.capture(
            account_id,
            "account_created",
            analytics.deterministic_event_uuid("account_created", account_id),
            {**valid, "app_version": "eyJhbGciOi.token"},
        )
    with pytest.raises(analytics.AnalyticsContractError):
        sink.delete_person("alice@example.com")
    account_id = str(uuid.uuid4())
    sink.set_person(account_id, {"is_player": True})
    sink.set_person_once(account_id, {"signup_phase": "closed_trial"})
    sink.delete_person(account_id)
    assert account_id in sink.deleted_people
    assert account_id not in sink.people
    assert account_id not in sink.people_set_once


def test_server_recording_sink_rejects_client_origin(recording_analytics, monkeypatch):
    sink = recording_analytics
    account_id = str(uuid.uuid4())
    contract = analytics.EVENT_CATALOGUE["account_created"]
    monkeypatch.setitem(
        analytics.EVENT_CATALOGUE,
        "account_created",
        analytics.EventContract("client", contract.properties),
    )
    properties = {
        "role": "player",
        "platform": "unknown",
        "app_version": "unknown",
        "env": "development",
        "signup_phase": "closed_trial",
        "invite_used": False,
    }
    with pytest.raises(analytics.AnalyticsContractError, match="not owned by the server"):
        sink.capture(
            account_id,
            "account_created",
            analytics.deterministic_event_uuid("account_created", account_id),
            properties,
        )


def test_posthog_sink_drops_invalid_payload_without_logging_private_event(caplog):
    account_id = str(uuid.uuid4())

    class RecordingPostHogClient:
        def __init__(self):
            self.events = []

        def capture(self, *args, **kwargs):
            self.events.append((args, kwargs))

    sink = analytics.PostHogAnalyticsSink.__new__(analytics.PostHogAnalyticsSink)
    sink.client = RecordingPostHogClient()
    sink.capture(account_id, "alice@example.com", str(uuid.uuid4()), {})
    assert sink.client.events == []
    assert "alice@example.com" not in caplog.text
    assert any(record.levelname == "WARNING" for record in caplog.records)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (202, {"persons_found": 1, "persons_queued_for_deletion": 1, "deletion_errors": []}, "delivered"),
        (202, {"persons_found": 1, "persons_queued_for_deletion": 0, "deletion_errors": [{"step": "delete"}]}, "pending"),
        (202, {"persons_found": 0, "persons_queued_for_deletion": 0, "deletion_errors": []}, "delivered"),
        (403, {"detail": "forbidden"}, "pending"),
    ],
)
def test_posthog_person_deletion_uses_synchronous_private_api(monkeypatch, caplog, status, body, expected):
    import httpx

    from service.analytics import PostHogAnalyticsSink

    request_details = {}

    def open_request(url, *, headers, json, timeout):
        request_details["url"] = url
        request_details["authorization"] = headers["Authorization"]
        request_details["body"] = json
        request_details["timeout"] = timeout
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr("service.analytics.httpx.post", open_request)
    sink = PostHogAnalyticsSink.__new__(PostHogAnalyticsSink)
    sink.person_api_key = "private-key"
    sink.project_id = "1234"
    sink.person_api_host = "https://eu.posthog.com"

    account_id = str(uuid.uuid4())
    assert sink.delete_person(account_id).value == expected
    assert request_details["url"] == "https://eu.posthog.com/api/projects/1234/persons/bulk_delete/"
    assert request_details["authorization"] == "Bearer private-key"
    assert request_details["body"] == {
        "distinct_ids": [account_id],
        "delete_events": True,
        "delete_recordings": False,
    }
    assert request_details["timeout"] == 2.0
    if status == 403:
        assert "person:write" in caplog.text
        assert "private-key" not in caplog.text


def test_onboarding_step_viewed_is_a_client_event_with_allowlisted_identifiers():
    contract = analytics.EVENT_CATALOGUE["onboarding_step_viewed"]
    assert contract.origin == "client"
    assert set(contract.properties) == {
        "role",
        "platform",
        "app_version",
        "env",
        "step",
    }
    assert contract.properties["step"].validate("gender")
    assert contract.properties["step"].validate("review")
    assert not contract.properties["step"].validate("left knee pain")


def test_workout_sync_failure_reason_does_not_widen_invite_reason_code():
    assert analytics.PROPERTY_TYPES["sync_failure_reason"].validate("network")
    assert not analytics.PROPERTY_TYPES["reason_code"].validate("network")


def test_tracking_plan_events_and_properties_match_code_catalogue():
    document = TRACKING_PLAN.read_text(encoding="utf-8")
    section = document.split("<!-- event-catalogue:start -->", 1)[1].split("<!-- event-catalogue:end -->", 1)[0]
    documented: dict[str, tuple[str, set[str]]] = {}
    for row in section.splitlines():
        columns = [column.strip() for column in row.strip().strip("|").split("|")]
        if len(columns) != 4 or not columns[0].startswith("`"):
            continue
        event_name = columns[0].strip("`")
        documented[event_name] = (columns[1].strip("`"), set(re.findall(r"`([a-z_]+)`", columns[3])))
    assert documented == {
        name: (contract.origin, set(contract.properties)) for name, contract in analytics.EVENT_CATALOGUE.items()
    }

    property_table = document.split("### Property definitions", 1)[1]
    documented_properties = set(re.findall(r"\|\s*`([a-z_]+)`\s*\|", property_table))
    catalogue_properties = set(analytics.PERSON_PROPERTY_CATALOGUE)
    for contract in analytics.EVENT_CATALOGUE.values():
        catalogue_properties.update(contract.properties)
    assert documented_properties == catalogue_properties


def test_analytics_configuration_is_noop_without_key_or_in_tests(monkeypatch):
    monkeypatch.delenv("MAYOS_ENV", raising=False)
    monkeypatch.setenv("FLY_APP_NAME", "mayos-api")
    assert analytics.deployment_environment() == "development"
    monkeypatch.setenv("MAYOS_ENV", "production")
    assert analytics.deployment_environment() == "production"
    monkeypatch.setenv("MAYOS_ENV", "staging")
    assert analytics.deployment_environment() == "development"

    monkeypatch.delenv("POSTHOG_API_KEY", raising=False)
    monkeypatch.delenv("TESTING", raising=False)
    assert isinstance(analytics.create_sink_from_environment(), analytics.NoOpAnalyticsSink)
    monkeypatch.setenv("POSTHOG_API_KEY", "configured-test-key")
    monkeypatch.setenv("TESTING", "1")
    assert isinstance(analytics.create_sink_from_environment(), analytics.NoOpAnalyticsSink)


def test_raising_sink_does_not_fail_registration(analytics_api):
    client, _, _ = analytics_api

    class RaisingSink:
        def capture(self, *_args):
            raise RuntimeError("sink unavailable")

        def set_person(self, *_args):
            raise RuntimeError("sink unavailable")

        def set_person_once(self, *_args):
            raise RuntimeError("sink unavailable")

        def delete_person(self, *_args):
            raise RuntimeError("sink unavailable")

    analytics.set_sink(RaisingSink())
    response = client.post(
        "/auth/register",
        json={"trainee_id": "analytics-raising", "password": "correct-horse-1"},
    )
    assert response.status_code == 201, response.text


def _grant_analytics_coach(client, db, username: str, *, client_header: str = "web/3.1"):
    from service import coach as coach_service

    headers = _register(client, username, client_header=client_header)
    account = db.get_active_account_by_username(username)
    invite = coach_service.issue_coach_invite(db, username, actor="test")
    assert invite["ok"]
    response = client.post("/coach/invite/redeem", headers=headers, json={"token": invite["token"]})
    assert response.status_code == 200, response.text
    return headers, account["account_id"]


def _set_analytics_coach_profile(client, headers, capacity: int = 5):
    response = client.put(
        "/coach/profile",
        headers=headers,
        json={"display_name": "Coach", "bio": "", "specialization": "", "capacity": capacity},
    )
    assert response.status_code == 200, response.text


def test_assignment_events_follow_commits_and_keep_roster_properties_current(analytics_api):
    client, db, sink = analytics_api
    coach_headers, coach_id = _grant_analytics_coach(client, db, "analytics-coach")
    _set_analytics_coach_profile(client, coach_headers, capacity=1)

    coach_granted = _event(sink, "coach_capability_granted")
    assert coach_granted["distinct_id"] == coach_id
    assert coach_granted["properties"]["role"] == "coach"
    assert coach_granted["properties"]["platform"] == "web"
    assert sink.people[coach_id]["is_coach"] is True
    assert sink.people[coach_id]["active_roster_size"] == 0

    issued = client.post("/coach/assignments/invites", headers=coach_headers)
    assert issued.status_code == 200, issued.text
    invite_event = _event(sink, "assignment_invite_issued")
    assert invite_event["distinct_id"] == coach_id
    assert invite_event["properties"]["active_roster_size"] == 0

    player_headers = _register(client, "analytics-player", client_header="android/4.2.1")
    player_id = db.get_active_account_by_username("analytics-player")["account_id"]
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": issued.json()["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    assignment_id = redeemed.json()["assignment"]["assignment_id"]
    started = _event(sink, "assignment_started")
    assert started["distinct_id"] == coach_id
    assert started["properties"]["coach_id"] == coach_id
    assert started["properties"]["active_roster_size"] == 1
    assert started["properties"]["time_since_invite_seconds"] >= 0
    assert started["properties"]["platform"] == "android"
    assert sink.people[player_id]["coached"] is True
    assert sink.people[coach_id]["active_roster_size"] == 1
    full_roster_invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert full_roster_invite.status_code == 400
    assert len([event for event in sink.events if event["event"] == "assignment_invite_issued"]) == 1

    ended = client.post("/assignments/me/end", headers=player_headers)
    assert ended.status_code == 200, ended.text
    end_event = _event(sink, "assignment_ended")
    assert end_event["distinct_id"] == coach_id
    assert end_event["properties"]["ended_by"] == "player"
    assert end_event["properties"]["active_roster_size"] == 0
    assert end_event["properties"]["duration_seconds"] >= 0
    assignment_status = db.catalog_conn.execute(
        "SELECT status FROM assignments WHERE assignment_id = ?", (assignment_id,)
    ).fetchone()[0]
    assert assignment_status == "ended"
    assert sink.people[player_id]["coached"] is False
    assert sink.people[coach_id]["active_roster_size"] == 0

    second_invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert second_invite.status_code == 200, second_invite.text
    second_player_headers = _register(client, "analytics-coach-revoke", client_header="android/4.2.1")
    second_assignment = client.post(
        "/assignments/invites/redeem",
        headers=second_player_headers,
        json={"token": second_invite.json()["token"], "consent": True},
    )
    assert second_assignment.status_code == 200, second_assignment.text
    assignment_to_revoke = second_assignment.json()["assignment"]["assignment_id"]
    revoked = client.post(
        f"/coach/assignments/{assignment_to_revoke}/revoke", headers=coach_headers
    )
    assert revoked.status_code == 200, revoked.text
    coach_revoke_event = next(
        event
        for event in sink.events
        if event["event"] == "assignment_ended" and event["properties"]["ended_by"] == "coach"
    )
    assert coach_revoke_event["distinct_id"] == coach_id
    for capture in sink.capture_attempts:
        assert _capture_attempt_count(sink, capture["event"], capture["uuid"]) == 1


def test_coach_disablement_and_account_deletion_emit_assignment_ends_once(analytics_api):
    client, db, sink = analytics_api
    coach_headers, coach_id = _grant_analytics_coach(client, db, "analytics-disable-coach")
    _set_analytics_coach_profile(client, coach_headers)
    player_headers = _register(client, "analytics-disable-player")
    player_id = db.get_active_account_by_username("analytics-disable-player")["account_id"]
    invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert invite.status_code == 200, invite.text
    assignment = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite.json()["token"], "consent": True},
    )
    assert assignment.status_code == 200, assignment.text

    disabled = client.post("/coach/capability/disable", headers=coach_headers)
    assert disabled.status_code == 200, disabled.text
    disabled_events = [event for event in sink.events if event["event"] == "coach_capability_disabled"]
    assert len(disabled_events) == 1
    ended_events = [event for event in sink.events if event["event"] == "assignment_ended"]
    assert len(ended_events) == 1
    assert ended_events[0]["properties"]["ended_by"] == "coach_capability_disabled"
    assert sink.people[coach_id]["is_coach"] is False
    assert sink.people[coach_id]["active_roster_size"] == 0
    assert sink.people[player_id]["coached"] is False

    deleting_coach_headers, deleting_coach_id = _grant_analytics_coach(
        client, db, "analytics-deleted-coach"
    )
    _set_analytics_coach_profile(client, deleting_coach_headers)
    deleting_player_headers = _register(client, "analytics-deleted-player")
    deleted_assignment_invite = client.post(
        "/coach/assignments/invites", headers=deleting_coach_headers
    )
    assert deleted_assignment_invite.status_code == 200, deleted_assignment_invite.text
    assignment_response = client.post(
        "/assignments/invites/redeem",
        headers=deleting_player_headers,
        json={"token": deleted_assignment_invite.json()["token"], "consent": True},
    )
    assert assignment_response.status_code == 200, assignment_response.text
    deleted = client.request(
        "DELETE", "/auth/account", headers=deleting_player_headers, json={"password": "correct-horse-1"}
    )
    assert deleted.status_code == 200, deleted.text
    all_end_events = [event for event in sink.events if event["event"] == "assignment_ended"]
    deletion_events = [
        event for event in all_end_events if event["properties"]["ended_by"] == "account_deleted"
    ]
    assert len(deletion_events) == 1
    assert deletion_events[0]["distinct_id"] == deleting_coach_id
    assert sink.people[deleting_coach_id]["active_roster_size"] == 0

    from svc.rate_limit import limiter

    limiter._storage.reset()
    deleted_coach_headers, deleted_coach_id = _grant_analytics_coach(
        client, db, "analytics-account-deleted-coach"
    )
    _set_analytics_coach_profile(client, deleted_coach_headers)
    assigned_player_headers = _register(client, "analytics-account-deleted-roster")
    coach_invite = client.post("/coach/assignments/invites", headers=deleted_coach_headers)
    assert coach_invite.status_code == 200, coach_invite.text
    assigned = client.post(
        "/assignments/invites/redeem",
        headers=assigned_player_headers,
        json={"token": coach_invite.json()["token"], "consent": True},
    )
    assert assigned.status_code == 200, assigned.text
    assigned_player_id = db.get_active_account_by_username("analytics-account-deleted-roster")["account_id"]
    coach_deleted = client.request(
        "DELETE", "/auth/account", headers=deleted_coach_headers, json={"password": "correct-horse-1"}
    )
    assert coach_deleted.status_code == 200, coach_deleted.text
    deleted_coach_end = next(
        event
        for event in sink.events
        if event["event"] == "assignment_ended"
        and event["distinct_id"] == assigned_player_id
        and event["properties"]["ended_by"] == "account_deleted"
    )
    assert deleted_coach_end["properties"]["active_roster_size"] == 0
    deleted_coach_disable = [
        event
        for event in sink.events
        if event["event"] == "coach_capability_disabled" and event["distinct_id"] == deleted_coach_id
    ]
    assert deleted_coach_disable == []
    assert deleted_coach_id in sink.deleted_people
    assert assigned_player_id in sink.people and sink.people[assigned_player_id]["coached"] is False
    assert deleted_coach_id not in sink.people
    assert deleted_coach_id not in sink.people_set_once
    for capture in sink.capture_attempts:
        assert _capture_attempt_count(sink, capture["event"], capture["uuid"]) == 1


def test_failed_end_and_disable_do_not_emit_success_events(analytics_api, monkeypatch):
    client, db, sink = analytics_api
    coach_headers, _coach_id = _grant_analytics_coach(client, db, "analytics-failed-end-coach")
    other_coach_headers, _other_coach_id = _grant_analytics_coach(
        client, db, "analytics-failed-end-other-coach"
    )
    _set_analytics_coach_profile(client, coach_headers)
    _set_analytics_coach_profile(client, other_coach_headers)
    player_headers = _register(client, "analytics-failed-end-player")
    invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert invite.status_code == 200, invite.text
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite.json()["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    assignment_id = redeemed.json()["assignment"]["assignment_id"]
    event_attempts_before_failures = len(sink.capture_attempts)

    forbidden_end = client.post(
        f"/coach/assignments/{assignment_id}/revoke", headers=other_coach_headers
    )
    assert forbidden_end.status_code == 403
    monkeypatch.setattr(db, "disable_coach_account", lambda *_args, **_kwargs: {"ok": False})
    failed_disable = client.post("/coach/capability/disable", headers=coach_headers)
    assert failed_disable.status_code == 400
    assert len(sink.capture_attempts) == event_attempts_before_failures
    assert not any(
        attempt["event"] in {"assignment_ended", "coach_capability_disabled"}
        for attempt in sink.capture_attempts[event_attempts_before_failures:]
    )


def test_raising_sink_does_not_fail_end_disable_or_delete(analytics_api):
    client, db, _sink = analytics_api
    coach_headers, coach_id = _grant_analytics_coach(client, db, "analytics-raising-end-coach")
    second_coach_headers, _second_coach_id = _grant_analytics_coach(
        client, db, "analytics-raising-delete-coach"
    )
    _set_analytics_coach_profile(client, coach_headers)
    _set_analytics_coach_profile(client, second_coach_headers)
    end_player_headers = _register(client, "analytics-raising-end-player")
    delete_player_headers = _register(client, "analytics-raising-delete-player")
    delete_player_id = db.get_active_account_by_username("analytics-raising-delete-player")["account_id"]
    end_invite = client.post("/coach/assignments/invites", headers=coach_headers)
    delete_invite = client.post("/coach/assignments/invites", headers=second_coach_headers)
    assert end_invite.status_code == delete_invite.status_code == 200
    for headers, invite in ((end_player_headers, end_invite), (delete_player_headers, delete_invite)):
        redeemed = client.post(
            "/assignments/invites/redeem",
            headers=headers,
            json={"token": invite.json()["token"], "consent": True},
        )
        assert redeemed.status_code == 200, redeemed.text

    class RaisingSink:
        def capture(self, *_args):
            raise RuntimeError("sink unavailable")

        def set_person(self, *_args):
            raise RuntimeError("sink unavailable")

        def set_person_once(self, *_args):
            raise RuntimeError("sink unavailable")

        def delete_person(self, *_args):
            raise RuntimeError("sink unavailable")

    analytics.set_sink(RaisingSink())
    ended = client.post("/assignments/me/end", headers=end_player_headers)
    assert ended.status_code == 200, ended.text
    disabled = client.post("/coach/capability/disable", headers=coach_headers)
    assert disabled.status_code == 200, disabled.text
    deleted = client.request(
        "DELETE", "/auth/account", headers=delete_player_headers, json={"password": "correct-horse-1"}
    )
    assert deleted.status_code == 200, deleted.text
    assert db.get_account(coach_id)["is_coach"] is False
    assert db.get_account(delete_player_id)["deleted_at"] is not None


def test_invite_redemption_failures_are_reason_coded_and_raising_sink_is_isolated(analytics_api):
    client, db, sink = analytics_api
    coach_a_headers, _coach_a_id = _grant_analytics_coach(client, db, "analytics-reason-coach-a")
    coach_b_headers, _coach_b_id = _grant_analytics_coach(client, db, "analytics-reason-coach-b")
    _set_analytics_coach_profile(client, coach_a_headers, capacity=1)
    _set_analytics_coach_profile(client, coach_b_headers, capacity=1)
    player_a_headers = _register(client, "analytics-reason-player-a")
    player_b_headers = _register(client, "analytics-reason-player-b")
    non_player_headers = _register(client, "analytics-reason-not-player")
    non_player_id = db.get_active_account_by_username("analytics-reason-not-player")["account_id"]

    def redeem(headers, token, *, consent=True):
        return client.post(
            "/assignments/invites/redeem",
            headers=headers,
            json={"token": token, "consent": consent},
        )

    def assert_failure(response, reason_code: str, detail: str = "Invalid or expired invite code."):
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == detail
        matching = [
            attempt
            for attempt in sink.capture_attempts
            if attempt["event"] == "invite_redemption_failed"
            and attempt["properties"]["reason_code"] == reason_code
        ]
        assert len(matching) == 1
        assert _capture_attempt_count(sink, "invite_redemption_failed", matching[0]["uuid"]) == 1

    assert_failure(redeem(player_a_headers, "unknown-valid-token"), "unknown_code")
    assert_failure(
        redeem(player_a_headers, "another-valid-shaped-token", consent=False),
        "consent_required",
        "You must explicitly accept the assignment to redeem this invite.",
    )

    coach_a_tokens = [
        client.post("/coach/assignments/invites", headers=coach_a_headers).json()["token"]
        for _ in range(3)
    ]
    coach_b_tokens = [
        client.post("/coach/assignments/invites", headers=coach_b_headers).json()["token"]
        for _ in range(3)
    ]
    assert_failure(redeem(coach_a_headers, coach_a_tokens[2]), "self_assignment", "You cannot assign yourself as your own coach.")

    accepted = redeem(player_a_headers, coach_a_tokens[0])
    assert accepted.status_code == 200, accepted.text
    assert_failure(redeem(player_a_headers, coach_a_tokens[0]), "already_redeemed")
    assert_failure(redeem(player_b_headers, coach_a_tokens[1]), "capacity", "This coach's roster is full. Ask them for a new invite later.")
    assert_failure(redeem(player_a_headers, coach_b_tokens[0]), "already_assigned", "You already have an active coaching assignment.")

    with db.catalog_locked() as conn:
        conn.execute(
            "UPDATE assignment_invites SET expires_at = ? WHERE token_hash = ?",
            ("2000-01-01T00:00:00+00:00", hash_token(coach_b_tokens[1])),
        )
        conn.commit()
    assert_failure(redeem(player_b_headers, coach_b_tokens[1]), "expired")
    disabled = client.post("/coach/capability/disable", headers=coach_b_headers)
    assert disabled.status_code == 200, disabled.text
    assert_failure(redeem(player_b_headers, coach_b_tokens[2]), "coach_unavailable")

    with db.catalog_locked() as conn:
        conn.execute("UPDATE accounts SET is_player = 0 WHERE account_id = ?", (non_player_id,))
        conn.commit()
    from svc.dependencies import VerifiedPlayer, get_current_player

    prior_override = client.app.dependency_overrides.get(get_current_player)
    client.app.dependency_overrides[get_current_player] = lambda: VerifiedPlayer(
        non_player_id, non_player_id, 1
    )
    try:
        assert_failure(redeem(non_player_headers, coach_a_tokens[1]), "not_a_player")
    finally:
        if prior_override is None:
            client.app.dependency_overrides.pop(get_current_player, None)
        else:
            client.app.dependency_overrides[get_current_player] = prior_override

    class RaisingSink:
        def capture(self, *_args):
            raise RuntimeError("sink unavailable")

        def set_person(self, *_args):
            raise RuntimeError("sink unavailable")

        def set_person_once(self, *_args):
            raise RuntimeError("sink unavailable")

        def delete_person(self, *_args):
            raise RuntimeError("sink unavailable")

    _set_analytics_coach_profile(client, coach_a_headers, capacity=2)
    analytics.set_sink(RaisingSink())
    invite = client.post("/coach/assignments/invites", headers=coach_a_headers)
    assert invite.status_code == 200, invite.text
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_b_headers,
        json={"token": invite.json()["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text


def test_hourly_sweep_retries_failed_person_deletion_once_until_delivered(analytics_api, monkeypatch):
    client, db, sink = analytics_api
    headers = _register(client, "analytics-deletion-retry")
    account_id = db.get_active_account_by_username("analytics-deletion-retry")["account_id"]
    sink_delete_person = sink.delete_person
    attempts = 0

    def fail_first_person_deletion(distinct_id):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("sink unavailable")
        return sink_delete_person(distinct_id)

    monkeypatch.setattr(sink, "delete_person", fail_first_person_deletion)
    deleted = client.request(
        "DELETE", "/auth/account", headers=headers, json={"password": "correct-horse-1"}
    )
    assert deleted.status_code == 200, deleted.text
    assert attempts == 1
    assert account_id not in sink.deleted_people
    deletion_state = db.deletions_conn.execute(
        "SELECT deleted_at, analytics_deleted_at, analytics_delete_attempts, analytics_delete_status"
        " FROM account_deletions WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    assert deletion_state[1:] == (None, 1, "pending")
    deleted_at = datetime.fromisoformat(deletion_state[0])

    from service.alert_sweep import run_sweep

    run_sweep(db, now=deleted_at + timedelta(minutes=30))
    assert attempts == 1
    unchanged = db.deletions_conn.execute(
        "SELECT analytics_deleted_at, analytics_delete_attempts, analytics_delete_status"
        " FROM account_deletions WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    assert unchanged == (None, 1, "pending")

    run_sweep(db, now=deleted_at + timedelta(hours=1))
    assert attempts == 2
    assert account_id in sink.deleted_people
    deletion_state = db.deletions_conn.execute(
        "SELECT analytics_deleted_at, analytics_delete_attempts, analytics_delete_status"
        " FROM account_deletions WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    assert deletion_state[0] is not None
    assert deletion_state[1:] == (2, "delivered")
    run_sweep(db)
    assert attempts == 2


def test_empty_posthog_result_stays_pending_until_grace_period(analytics_api, monkeypatch):
    import httpx

    client, db, _sink = analytics_api
    headers = _register(client, "analytics-deletion-grace")
    account_id = db.get_active_account_by_username("analytics-deletion-grace")["account_id"]
    posthog_sink = analytics.PostHogAnalyticsSink.__new__(analytics.PostHogAnalyticsSink)
    posthog_sink.person_api_key = "private-key"
    posthog_sink.project_id = "1234"
    posthog_sink.person_api_host = analytics.POSTHOG_EU_API_HOST
    requests = []

    def accepted_empty_delete(url, **_kwargs):
        requests.append(url)
        return httpx.Response(
            202,
            json={"persons_found": 0, "persons_queued_for_deletion": 0, "deletion_errors": []},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("service.analytics.httpx.post", accepted_empty_delete)
    analytics.set_sink(posthog_sink)
    deleted = client.request(
        "DELETE", "/auth/account", headers=headers, json={"password": "correct-horse-1"}
    )
    assert deleted.status_code == 200, deleted.text
    deleted_at = datetime.fromisoformat(
        db.deletions_conn.execute(
            "SELECT deleted_at FROM account_deletions WHERE account_id = ?", (account_id,)
        ).fetchone()[0]
    )
    state = db.deletions_conn.execute(
        "SELECT analytics_deleted_at, analytics_delete_attempts, analytics_delete_status"
        " FROM account_deletions WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    assert state == (None, 1, "pending")
    assert len(requests) == 1

    from service.alert_sweep import run_sweep

    run_sweep(db, now=deleted_at + timedelta(minutes=59))
    assert len(requests) == 1
    run_sweep(db, now=deleted_at + timedelta(hours=1))
    assert len(requests) == 2
    state = db.deletions_conn.execute(
        "SELECT analytics_deleted_at, analytics_delete_attempts, analytics_delete_status"
        " FROM account_deletions WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    assert state[0] is not None and state[1:] == (2, "delivered")
    run_sweep(db, now=deleted_at + timedelta(hours=2))
    assert len(requests) == 2


def test_unconfigured_analytics_deletion_stays_pending_without_attempts(analytics_api):
    client, db, _sink = analytics_api
    analytics.set_sink(analytics.NoOpAnalyticsSink())
    headers = _register(client, "analytics-deletion-noop")
    account_id = db.get_active_account_by_username("analytics-deletion-noop")["account_id"]

    deleted = client.request(
        "DELETE", "/auth/account", headers=headers, json={"password": "correct-horse-1"}
    )

    assert deleted.status_code == 200, deleted.text
    deletion_state = db.deletions_conn.execute(
        "SELECT analytics_deleted_at, analytics_delete_attempts, analytics_delete_status"
        " FROM account_deletions WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    assert deletion_state == (None, 0, "pending")

    from service.alert_sweep import run_sweep

    run_sweep(db)
    assert db.deletions_conn.execute(
        "SELECT analytics_deleted_at, analytics_delete_attempts, analytics_delete_status"
        " FROM account_deletions WHERE account_id = ?",
        (account_id,),
    ).fetchone() == (None, 0, "pending")


def test_missing_posthog_person_credentials_skip_deletion_batch(analytics_api, monkeypatch):
    client, db, _sink = analytics_api
    headers = _register(client, "analytics-deletion-missing-creds")
    account_id = db.get_active_account_by_username("analytics-deletion-missing-creds")["account_id"]
    posthog_sink = analytics.PostHogAnalyticsSink.__new__(analytics.PostHogAnalyticsSink)
    posthog_sink.person_api_key = ""
    posthog_sink.project_id = ""
    posthog_sink.person_api_host = analytics.POSTHOG_EU_API_HOST
    analytics.set_sink(posthog_sink)

    deleted = client.request(
        "DELETE", "/auth/account", headers=headers, json={"password": "correct-horse-1"}
    )
    assert deleted.status_code == 200, deleted.text
    row = db.deletions_conn.execute(
        "SELECT analytics_deleted_at, analytics_delete_attempts, analytics_delete_status"
        " FROM account_deletions WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    assert row == (None, 0, "pending")

    from service.alert_sweep import run_sweep

    run_sweep(db)
    assert db.deletions_conn.execute(
        "SELECT analytics_deleted_at, analytics_delete_attempts, analytics_delete_status"
        " FROM account_deletions WHERE account_id = ?",
        (account_id,),
    ).fetchone() == (None, 0, "pending")


def test_posthog_four_xx_deletion_response_stays_pending(analytics_api, monkeypatch, caplog):
    import httpx

    client, db, _sink = analytics_api
    headers = _register(client, "analytics-deletion-scope-error")
    account_id = db.get_active_account_by_username("analytics-deletion-scope-error")["account_id"]
    posthog_sink = analytics.PostHogAnalyticsSink.__new__(analytics.PostHogAnalyticsSink)
    posthog_sink.person_api_key = "private-secret"
    posthog_sink.project_id = "1234"
    posthog_sink.person_api_host = analytics.POSTHOG_EU_API_HOST
    requests = []

    def reject_request(url, **kwargs):
        requests.append((url, kwargs))
        return httpx.Response(
            403, json={"detail": "forbidden"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr("service.analytics.httpx.post", reject_request)
    analytics.set_sink(posthog_sink)
    deleted = client.request(
        "DELETE", "/auth/account", headers=headers, json={"password": "correct-horse-1"}
    )
    assert deleted.status_code == 200, deleted.text
    deleted_at = datetime.fromisoformat(
        db.deletions_conn.execute(
            "SELECT deleted_at FROM account_deletions WHERE account_id = ?", (account_id,)
        ).fetchone()[0]
    )

    from service.account_deletion import retry_analytics_deletions

    retry_analytics_deletions(db, now=deleted_at + timedelta(hours=1))
    state = db.deletions_conn.execute(
        "SELECT analytics_deleted_at, analytics_delete_attempts, analytics_delete_status"
        " FROM account_deletions WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    assert state == (None, 2, "pending")
    assert len(requests) == 2
    assert "person:write" in caplog.text
    assert "private-secret" not in caplog.text


def test_reused_username_gets_a_new_analytics_identity_after_deletion(analytics_api):
    client, db, sink = analytics_api
    first_headers = _register(
        client,
        "analytics-reused-identity",
        first_touch={"utm_source": "old-channel"},
    )
    first_id = db.get_active_account_by_username("analytics-reused-identity")["account_id"]
    deleted = client.request(
        "DELETE",
        "/auth/account",
        headers=first_headers,
        json={"password": "correct-horse-1"},
    )
    assert deleted.status_code == 200, deleted.text
    assert first_id in sink.deleted_people

    _register(
        client,
        "analytics-reused-identity",
        first_touch={"utm_source": "new-channel"},
    )
    second_id = db.get_active_account_by_username("analytics-reused-identity")["account_id"]

    assert second_id != first_id
    assert second_id not in sink.deleted_people
    assert db.analytics_preference_allows(second_id)
    assert db.get_first_touch_acquisition(second_id)["utm_source"] == "new-channel"
    assert any(
        event["event"] == "account_created" and event["distinct_id"] == second_id
        for event in sink.events
    )
    assert deletion_attempts == []


def test_coach_alert_and_review_events_are_committed_private_and_deduplicated(analytics_api):
    client, db, sink = analytics_api
    player_headers = _register(client, "analytics-coached-player")
    coach_headers, assignment_id = _assigned_analytics_player(client, db, player_headers)
    coach = db.get_active_account_by_username("analytics-coach")
    coach_id = coach["account_id"]
    client_headers = {**coach_headers, "X-MAYOS-Client": "web/1.2.3"}
    sink.events.clear()

    empty_list = client.get("/coach/alerts", headers=client_headers)
    assert empty_list.status_code == 200
    assert not [event for event in sink.events if event["event"] == "coach_alerts_viewed"]

    started_at = datetime.now(UTC) - timedelta(days=9)
    db.catalog_conn.execute(
        "UPDATE assignments SET started_at = ? WHERE assignment_id = ?",
        (started_at.isoformat(), assignment_id),
    )
    db.catalog_conn.commit()
    from service.alert_sweep import run_sweep

    sweep_now = datetime.now(UTC)
    assert run_sweep(db, now=sweep_now)["follow_ups_created"] == 1
    assert run_sweep(db, now=sweep_now)["follow_ups_created"] == 0
    created = [event for event in sink.events if event["event"] == "coach_alert_created"]
    assert len(created) == 1
    assert created[0]["distinct_id"] == coach_id
    assert created[0]["properties"]["alert_kind"] == "follow_up_due"
    assert created[0]["properties"]["role"] == "coach"
    assert set(created[0]["properties"]) == {
        "role", "platform", "app_version", "env", "alert_kind"
    }
    alert = db.list_coach_alerts(coach_id, ("new",))[0]

    first_list = client.get("/coach/alerts", headers=client_headers)
    second_list = client.get("/coach/alerts", headers=client_headers)
    assert first_list.status_code == second_list.status_code == 200
    viewed = [event for event in sink.events if event["event"] == "coach_alerts_viewed"]
    assert len(viewed) == 1
    assert viewed[0]["distinct_id"] == coach_id
    assert viewed[0]["properties"]["platform"] == "web"
    assert "player_id" not in viewed[0]["properties"]

    acknowledged = client.post(
        f"/coach/alerts/{alert['alert_id']}/acknowledge", headers=client_headers
    )
    repeated_acknowledgement = client.post(
        f"/coach/alerts/{alert['alert_id']}/acknowledge", headers=client_headers
    )
    assert acknowledged.status_code == repeated_acknowledgement.status_code == 200
    resolved = client.post(f"/coach/alerts/{alert['alert_id']}/resolve", headers=client_headers)
    assert resolved.status_code == 200
    actions = [
        event for event in sink.events
        if event["event"] in {"coach_alert_acknowledged", "coach_alert_resolved"}
    ]
    assert [event["event"] for event in actions] == [
        "coach_alert_acknowledged", "coach_alert_resolved"
    ]
    assert all(event["distinct_id"] == coach_id for event in actions)
    assert all(event["properties"]["is_coaching_action"] is True for event in actions)
    assert all(event["properties"]["time_open_seconds"] >= 0 for event in actions)
    assert all(
        set(event["properties"])
        == {"role", "platform", "app_version", "env", "time_open_seconds", "is_coaching_action"}
        for event in actions
    )

    check_in = client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=client_headers,
        json={"checked_in_on": sweep_now.date().isoformat(), "channel": "phone", "note": "private note"},
    )
    assert check_in.status_code == 200, check_in.text
    check_in_event = next(event for event in sink.events if event["event"] == "check_in_recorded")
    assert check_in_event["distinct_id"] == coach_id
    assert check_in_event["properties"]["is_coaching_action"] is True
    assert set(check_in_event["properties"]) == {
        "role", "platform", "app_version", "env", "is_coaching_action"
    }
    assert "private note" not in repr(check_in_event)

    sink.events.clear()
    failed_check_in = client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=client_headers,
        json={"checked_in_on": sweep_now.date().isoformat(), "channel": "unknown", "note": "not recorded"},
    )
    assert failed_check_in.status_code == 400
    assert not [event for event in sink.events if event["event"] == "check_in_recorded"]

    history_url = f"/coach/assignments/{assignment_id}/player/summary"
    assert client.get(history_url, headers=client_headers).status_code == 200
    assert client.get(history_url, headers=client_headers).status_code == 200
    exercise_url = f"/coach/assignments/{assignment_id}/player/exercises"
    assert client.get(exercise_url, headers=client_headers).status_code == 200
    history_events = [event for event in sink.events if event["event"] == "player_history_viewed"]
    assert len(history_events) == 1
    assert history_events[0]["distinct_id"] == coach_id
    assert set(history_events[0]["properties"]) == {"role", "platform", "app_version", "env"}

    sink.events.clear()
    denied = client.get("/coach/assignments/not-an-active-assignment/player/summary", headers=client_headers)
    assert denied.status_code == 403
    assert not [event for event in sink.events if event["event"] == "player_history_viewed"]


def test_raising_sink_does_not_fail_coach_check_in(analytics_api):
    client, db, _sink = analytics_api
    player_headers = _register(client, "analytics-raising-player")
    coach_headers, assignment_id = _assigned_analytics_player(client, db, player_headers)
    from service import analytics as analytics_service

    analytics_service.set_sink(RaisingAnalyticsSink())
    response = client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": datetime.now(UTC).date().isoformat(), "channel": "phone", "note": "kept private"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["check_in"]["note"] == "kept private"


def test_coach_history_api_events_cover_review_endpoints_and_utc_day_rollover(
    analytics_api, monkeypatch
):
    client, db, sink = analytics_api
    player_headers = _register(client, "analytics-history-player")
    coach_headers, assignment_id = _assigned_analytics_player(client, db, player_headers)
    coach_id = db.get_active_account_by_username("analytics-coach")["account_id"]
    player = db.get_active_account_by_username("analytics-history-player")
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.log_workout_session(
            "checkpoint-session",
            "2026-10-01",
            "Full A",
            "2026-10-01T00:00:00+00:00",
            "2026-10-01T01:00:00+00:00",
            4,
            "",
        )
        assert ledger.insert_checkpoint_review(
            {
                "checkpoint": 10,
                "session_id": "checkpoint-session",
                "period_start": "2026-09-01",
                "period_end": "2026-10-01",
                "facts_json": '{"workouts_in_period": 10}',
                "rating_json": '[{"part":"consistency","label":"Holding"}]',
                "created_at": "2026-10-01T00:00:00+00:00",
            }
        )

    from service import coach_analytics

    current = [datetime(2026, 10, 4, 23, 59, tzinfo=UTC)]
    monkeypatch.setattr(coach_analytics, "_now", lambda: current[0])
    base = f"/coach/assignments/{assignment_id}/player"
    assert client.get(f"{base}/personal-records", headers=coach_headers).status_code == 200
    assert client.get(f"{base}/personal-records", headers=coach_headers).status_code == 200
    assert len([event for event in sink.events if event["event"] == "player_history_viewed"]) == 1

    current[0] = datetime(2026, 10, 5, 0, 1, tzinfo=UTC)
    history = client.get(f"{base}/exercises/ex1/history", headers=coach_headers)
    assert history.status_code == 200, history.text
    current[0] = datetime(2026, 10, 6, 0, 1, tzinfo=UTC)
    assert client.get(f"{base}/checkpoint-reviews", headers=coach_headers).status_code == 200
    current[0] = datetime(2026, 10, 7, 0, 1, tzinfo=UTC)
    assert client.get(f"{base}/checkpoint-reviews/10", headers=coach_headers).status_code == 200
    history_events = [event for event in sink.events if event["event"] == "player_history_viewed"]
    assert len(history_events) == 4
    assert all(event["distinct_id"] == coach_id for event in history_events)
    assert all(set(event["properties"]) == {"role", "platform", "app_version", "env"} for event in history_events)

    daily_alert = _insert_alert(
        db,
        coach_id,
        player["account_id"],
        assignment_id,
        "missed_expected_days",
    )
    current[0] = datetime(2026, 10, 5, 23, 59, tzinfo=UTC)
    assert client.get("/coach/alerts", headers=coach_headers).status_code == 200
    assert client.get("/coach/alerts", headers=coach_headers).status_code == 200
    current[0] = datetime(2026, 10, 6, 0, 1, tzinfo=UTC)
    assert client.get("/coach/alerts", headers=coach_headers).status_code == 200
    alert_views = [event for event in sink.events if event["event"] == "coach_alerts_viewed"]
    assert len(alert_views) == 2
    assert all(event["distinct_id"] == coach_id for event in alert_views)
    assert daily_alert["assignment_id"] == assignment_id


def test_coach_alert_api_denials_and_non_new_lists_emit_nothing(analytics_api):
    client, db, sink = analytics_api
    player_a_headers = _register(client, "analytics-denied-player-a")
    coach_a_headers, assignment_a = _assigned_analytics_player(
        client, db, player_a_headers, coach_username="analytics-denied-coach-a"
    )
    player_b_headers = _register(client, "analytics-denied-player-b")
    coach_b_headers, assignment_b = _assigned_analytics_player(
        client, db, player_b_headers, coach_username="analytics-denied-coach-b"
    )
    coach_a_id = db.get_active_account_by_username("analytics-denied-coach-a")["account_id"]
    coach_b_id = db.get_active_account_by_username("analytics-denied-coach-b")["account_id"]
    player_a = db.get_active_account_by_username("analytics-denied-player-a")
    player_b = db.get_active_account_by_username("analytics-denied-player-b")
    own_alert = _insert_alert(db, coach_a_id, player_a["account_id"], assignment_a)
    foreign_alert = _insert_alert(db, coach_b_id, player_b["account_id"], assignment_b)

    sink.events.clear()
    for action in ("acknowledge", "resolve"):
        response = client.post(
            f"/coach/alerts/{foreign_alert['alert_id']}/{action}", headers=coach_a_headers
        )
        assert response.status_code == 403
    ended = client.post("/assignments/me/end", headers=player_a_headers)
    assert ended.status_code == 200, ended.text
    for action in ("acknowledge", "resolve"):
        response = client.post(
            f"/coach/alerts/{own_alert['alert_id']}/{action}", headers=coach_a_headers
        )
        assert response.status_code == 403
    assert client.get(
        f"/coach/assignments/{assignment_a}/player/summary", headers=coach_a_headers
    ).status_code == 403
    assert client.get(
        f"/coach/assignments/{assignment_b}/player/summary", headers=coach_a_headers
    ).status_code == 403
    assert not [
        event
        for event in sink.events
        if event["event"] in {
            "coach_alert_acknowledged",
            "coach_alert_resolved",
            "player_history_viewed",
        }
    ]

    acknowledged, transitioned = db.acknowledge_coach_alert_transition(
        foreign_alert["alert_id"], coach_b_id, datetime.now(UTC).isoformat()
    )
    assert transitioned and acknowledged is not None
    db.catalog_conn.execute(
        "DELETE FROM coach_analytics_daily_markers WHERE coach_account_id = ?", (coach_b_id,)
    )
    db.catalog_conn.commit()
    sink.events.clear()
    non_new = client.get("/coach/alerts?state=acknowledged", headers=coach_b_headers)
    assert non_new.status_code == 200, non_new.text
    assert any(alert["state"] == "acknowledged" for alert in non_new.json()["alerts"])
    assert not [event for event in sink.events if event["event"] == "coach_alerts_viewed"]


def test_raising_sink_does_not_fail_coach_alert_actions_or_history_reads(analytics_api):
    client, db, _sink = analytics_api
    player_headers = _register(client, "analytics-raising-coach-read-player")
    coach_headers, assignment_id = _assigned_analytics_player(client, db, player_headers)
    coach_id = db.get_active_account_by_username("analytics-coach")["account_id"]
    player = db.get_active_account_by_username("analytics-raising-coach-read-player")
    alert = _insert_alert(db, coach_id, player["account_id"], assignment_id)
    analytics.set_sink(RaisingAnalyticsSink())

    listed = client.get("/coach/alerts", headers=coach_headers)
    assert listed.status_code == 200, listed.text
    acknowledged = client.post(
        f"/coach/alerts/{alert['alert_id']}/acknowledge", headers=coach_headers
    )
    assert acknowledged.status_code == 200, acknowledged.text
    resolved = client.post(
        f"/coach/alerts/{alert['alert_id']}/resolve", headers=coach_headers
    )
    assert resolved.status_code == 200, resolved.text
    history = client.get(
        f"/coach/assignments/{assignment_id}/player/summary", headers=coach_headers
    )
    assert history.status_code == 200, history.text


def test_profile_change_alert_is_captured_from_the_profile_api(analytics_api, monkeypatch):
    client, db, sink = analytics_api
    player_headers = _register(client, "analytics-profile-alert-player")
    _coach_headers, _assignment_id = _assigned_analytics_player(client, db, player_headers)
    db.switch_user("analytics-profile-alert-player")
    db.ledger.upsert_player_profile(
        {"equipment_access": "Commercial gym", "injuries_or_limitations": "None"}
    )
    _install_analytics_program_generators(monkeypatch)
    sink.events.clear()

    updated = client.put(
        "/profile", headers=player_headers, json={"equipment_access": "Home gym"}
    )
    assert updated.status_code == 200, updated.text
    events = [event for event in sink.events if event["event"] == "coach_alert_created"]
    assert len(events) == 1
    assert events[0]["distinct_id"] == db.get_active_account_by_username("analytics-coach")["account_id"]
    assert events[0]["properties"]["alert_kind"] == "profile_change"
    assert set(events[0]["properties"]) == {
        "role", "platform", "app_version", "env", "alert_kind"
    }


def test_consent_missed_day_alert_uses_the_shared_creation_event_seam(analytics_api, monkeypatch):
    client, db, sink = analytics_api
    player_headers = _register(client, "analytics-consent-missed-player")
    player_id = db.get_active_account_by_username("analytics-consent-missed-player")["account_id"]
    db.switch_user("analytics-consent-missed-player")
    started = datetime.now(UTC) - timedelta(days=10)
    db.ledger.append_training_schedule(
        "analytics-consent-missed-player",
        [1, 2, 3, 4, 5, 6, 7],
        "UTC",
        (started.date() - timedelta(days=1)).isoformat(),
        started.isoformat(),
    )

    from service import coach as coach_service
    import service.assignments as assignment_service

    coach_headers = _register(client, "analytics-consent-missed-coach")
    issued = coach_service.issue_coach_invite(db, "analytics-consent-missed-coach", actor="test")
    assert issued["ok"]
    assert client.post(
        "/coach/invite/redeem", headers=coach_headers, json={"token": issued["token"]}
    ).status_code == 200
    assert client.put(
        "/coach/profile",
        headers=coach_headers,
        json={"display_name": "Coach", "bio": "", "specialization": "", "capacity": 5},
    ).status_code == 200
    invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert invite.status_code == 200, invite.text

    frozen = started

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz is None else frozen.astimezone(tz)

    monkeypatch.setattr(assignment_service, "datetime", FrozenDateTime)
    sink.events.clear()
    consent = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite.json()["token"], "consent": True},
    )
    assert consent.status_code == 200, consent.text
    events = [event for event in sink.events if event["event"] == "coach_alert_created"]
    assert len(events) == 1
    assert events[0]["distinct_id"] == db.get_active_account_by_username("analytics-consent-missed-coach")["account_id"]
    assert events[0]["properties"]["alert_kind"] == "missed_expected_days"
    assert db.get_active_account_by_username("analytics-consent-missed-player")["account_id"] == player_id


def test_check_in_event_precedes_follow_up_failure_and_created_alert_keeps_client_context(
    analytics_api, monkeypatch
):
    client, db, sink = analytics_api
    player_headers = _register(client, "analytics-follow-up-player")
    coach_headers, assignment_id = _assigned_analytics_player(client, db, player_headers)
    coach_id = db.get_active_account_by_username("analytics-coach")["account_id"]
    started = datetime.now(UTC) - timedelta(days=20)
    db.catalog_conn.execute(
        "UPDATE assignments SET started_at = ? WHERE assignment_id = ?",
        (started.isoformat(), assignment_id),
    )
    db.catalog_conn.commit()
    headers = {**coach_headers, "X-MAYOS-Client": "web/3.2.1"}
    checked_in_on = (datetime.now(UTC).date() - timedelta(days=12)).isoformat()
    sink.events.clear()

    response = client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=headers,
        json={"checked_in_on": checked_in_on, "channel": "phone", "note": "private"},
    )
    assert response.status_code == 200, response.text
    check_in_event = _event(sink, "check_in_recorded")
    follow_up_event = next(
        event
        for event in sink.events
        if event["event"] == "coach_alert_created"
        and event["properties"]["alert_kind"] == "follow_up_due"
    )
    assert check_in_event["distinct_id"] == follow_up_event["distinct_id"] == coach_id
    assert check_in_event["properties"]["platform"] == "web"
    assert follow_up_event["properties"]["platform"] == "web"
    assert follow_up_event["properties"]["app_version"] == "3.2.1"
    assert "private" not in repr(check_in_event)

    import service.check_ins as check_in_service

    def fail_follow_up(*_args, **_kwargs):
        raise RuntimeError("follow-up reconciliation failed")

    monkeypatch.setattr(check_in_service, "evaluate_follow_up", fail_follow_up)
    with pytest.raises(RuntimeError, match="follow-up reconciliation failed"):
        client.post(
            f"/coach/assignments/{assignment_id}/check-ins",
            headers=headers,
            json={"checked_in_on": datetime.now(UTC).date().isoformat(), "channel": "phone"},
        )
    assert len([event for event in sink.events if event["event"] == "check_in_recorded"]) == 2
