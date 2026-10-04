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


def _assert_authoritative_write_committed(db: DatabaseManager, account_id: str, event: str) -> None:
    account = db.get_account(account_id)
    assert db.is_live_account(account)
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
        [(f"ex{index}", f"Test exercise {index}", "Chest", "Chest") for index in range(1, 4)],
    )
    catalog_connection.commit()
    catalog_connection.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "ledgers",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    sink = recording_analytics
    original_capture = sink.capture

    def capture_after_committed_write(account_id, event, event_uuid, properties):
        _assert_authoritative_write_committed(db, account_id, event)
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
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _event(sink, name: str) -> dict:
    return next(event for event in sink.events if event["event"] == name)


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
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert ledger.get_intake_state()["status"] == "confirmed"


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
        ledger.save_training_program(_test_program().model_dump())
        ledger.save_onboarding_state(saved_state)

    monkeypatch.setattr(onboarding_graph, "invoke", lambda state, **_kwargs: state)
    for _ in range(2):
        completed = client.post("/onboarding/complete", headers=headers)
        assert completed.status_code == 200, completed.text

    completions = [event for event in sink.events if event["event"] == "onboarding_completed"]
    assert len(completions) == 1
    assert completions[0]["properties"]["prefilled_fields_count"] == 2


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


def test_account_created_marks_invite_use_and_release_phase_once(analytics_api, monkeypatch):
    client, db, sink = analytics_api
    monkeypatch.setenv("MAYOS_RELEASE_PHASE", "public")
    code = "coach-invite-code-123"
    expires = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert db.issue_new_account_coach_invite(hash_token(code), "invited-coach", expires)
    _register(client, "invited-coach", coach_invite_code=code)

    event = _event(sink, "account_created")
    assert event["properties"]["signup_phase"] == "public"
    assert event["properties"]["invite_used"] is True
    assert sink.people[event["distinct_id"]] == {"is_player": True, "is_coach": True}
    assert sink.people_set_once[event["distinct_id"]] == {"signup_phase": "public"}


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
