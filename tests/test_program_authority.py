"""Program authority enforcement across every player write path (ticket #27).

Builds on ADR 026's single ``player_controls_program`` decision: a player cannot
change a coach-controlled program through any route or assistant action. Covers
direct generation, active-program auto-generation, profile-triggered rebuild,
onboarding completion, chat program mutation, and assistant exercise swap —
each before coach publication, during coach control, and after unassignment.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import (
    GeneratedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
)
from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import onboarding as onboarding_service
from service import programs as programs_service
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
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.execute(
        "INSERT INTO exercises (id, name, body_part, target_muscle) VALUES"
        " ('sq', 'Squat', 'Upper Legs', 'Quads'), ('bp', 'Bench Press', 'Chest', 'Chest'),"
        " ('dbp', 'Dumbbell Press', 'Chest', 'Chest'), ('row', 'Row', 'Back', 'Back');"
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
            yield client, db, tmp_path / "users"
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


@pytest.fixture
def shipped_library_api(monkeypatch, fresh_store):
    """API fixture backed by the shipped exercise library for real generation."""
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: fresh_store
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, fresh_store


def _register(client, username, password="correct-horse-1"):
    resp = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _make_coach(client, db, username, capacity=10):
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username, actor="cli")
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


def _assigned_player(api, player_name="p1"):
    """Coach "coach" is actively assigned "p1"; returns headers, assignment id, accounts."""
    client, db = api[:2]
    coach_headers = _make_coach(client, db, "coach", capacity=5)
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    player = _register(client, player_name)
    player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem", headers=player_headers, json={"token": token, "consent": True}
    )
    assert redeemed.status_code == 200, redeemed.text
    coach_account_id = db.get_active_account_by_username("coach")["account_id"]
    player_account_id = db.get_active_account_by_username(player_name)["account_id"]
    return (
        coach_headers,
        player_headers,
        redeemed.json()["assignment"]["assignment_id"],
        coach_account_id,
        player_account_id,
    )


def _program(name: str = "Coach Plan") -> GeneratedProgramSchema:
    return GeneratedProgramSchema(
        program_name=name,
        split_type="Full Body",
        weekly_frequency=1,
        days=[
            ProgramDaySchema(
                day_name="Full A",
                day_order=1,
                exercises=[
                    ProgramExerciseSchema(
                        exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8
                    ),
                    ProgramExerciseSchema(
                        exercise_id="bp", exercise_name="Bench Press", target_reps_min=5, target_reps_max=8
                    ),
                    ProgramExerciseSchema(
                        exercise_id="row", exercise_name="Row", target_reps_min=5, target_reps_max=8
                    ),
                ],
            )
        ],
    )


def _counting_saver(db: Any, program_name: str):
    """Returns (fake pipeline, call counter) that saves through the real ledger."""
    calls = {"n": 0}

    def fake(**kwargs):
        calls["n"] += 1
        program = _program(program_name)
        kwargs["ledger"].save_training_program(
            program.model_dump(),
            published_by_coach_account_id=kwargs.get("published_by_coach_account_id"),
        )
        return program, "md"

    return fake, calls


def _coach_generation(db, monkeypatch):
    fake, _ = _counting_saver(db, "Coach Plan")
    monkeypatch.setattr("service.coach_programs.generate_program_pipeline", fake)


def _player_generation(db, monkeypatch):
    fake, calls = _counting_saver(db, "Player Plan")
    monkeypatch.setattr("svc.routers.programs.generate_program_pipeline", fake)
    return fake, calls


def _auto_generation(db, monkeypatch):
    fake, calls = _counting_saver(db, "Player Plan")
    monkeypatch.setattr("service.programs.generate_program_pipeline", fake)
    return fake, calls


def _profile_generation(db, monkeypatch):
    fake, calls = _counting_saver(db, "Player Plan")
    monkeypatch.setattr("service.profile.generate_program_pipeline", fake)
    return fake, calls


def _publish(client, coach_headers, assignment_id, **body):
    return client.post(f"/coach/assignments/{assignment_id}/program", headers=coach_headers, json=body)


def _chat_done_event(client, player_headers, content):
    response = client.post("/chat/messages", headers=player_headers, json={"content": content})
    assert response.status_code == 200, response.text
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    return next(event for event in events if event.get("done") is True)


def _active(db, player="p1"):
    db.switch_user(player)
    return db.ledger.get_active_program()


def _program_rows(db, player="p1"):
    db.switch_user(player)
    return db.conn.execute("SELECT COUNT(*) FROM training_programs").fetchone()[0]


def _end_assignment(client, player_headers):
    ended = client.post("/assignments/me/end", headers=player_headers)
    assert ended.status_code == 200, ended.text


# --------------------------------------------------------------------------
# 1. POST /programs/generate
# --------------------------------------------------------------------------


def test_direct_generation_allowed_before_publication(api, monkeypatch):
    client, db, _ = api
    _, player_headers, _, _, _ = _assigned_player(api)
    _, calls = _player_generation(db, monkeypatch)

    generated = client.post("/programs/generate", headers=player_headers, json={})
    assert generated.status_code == 200, generated.text
    assert generated.json()["player_controls_program"] is True
    assert calls["n"] == 1
    assert client.get("/programs/active", headers=player_headers).json()["published_by_coach_account_id"] is None


def test_direct_generation_refused_during_control(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    before = _active(db)

    _, calls = _player_generation(db, monkeypatch)
    refused = client.post("/programs/generate", headers=player_headers, json={})
    assert refused.status_code == 403
    assert refused.json()["detail"] == programs_service.COACH_CONTROLLED_ERROR
    assert calls["n"] == 0
    assert _active(db).version == before.version


def test_direct_generation_allowed_after_unassignment(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    _end_assignment(client, player_headers)

    _, calls = _player_generation(db, monkeypatch)
    generated = client.post("/programs/generate", headers=player_headers, json={})
    assert generated.status_code == 200, generated.text
    assert calls["n"] == 1


# --------------------------------------------------------------------------
# 2. GET /programs/active auto-generation
# --------------------------------------------------------------------------


def test_active_autogeneration_synthesizes_before_publication(api, monkeypatch):
    client, db, _ = api
    _, player_headers, _, _, _ = _assigned_player(api)
    db.switch_user("p1")
    db.ledger.upsert_player_profile({"rep_preference": "balanced"})

    _, calls = _auto_generation(db, monkeypatch)
    active = client.get("/programs/active", headers=player_headers)
    assert active.status_code == 200, active.text
    assert active.json()["program_name"] == "Player Plan"
    assert active.json()["published_by_coach_account_id"] is None
    assert calls["n"] == 1
    assert _active(db).version == 1


def test_active_autogeneration_returns_coach_program_unchanged_during_control(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, player_account_id = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    before = _active(db)
    rows_before = _program_rows(db)
    notices_before = len(db.list_assignment_notices(player_account_id))

    _, calls = _auto_generation(db, monkeypatch)
    body = client.get("/programs/active", headers=player_headers).json()
    assert body["program_name"] == "Coach Plan"
    assert body["version"] == before.version
    assert calls["n"] == 0
    assert _program_rows(db) == rows_before
    assert len(db.list_assignment_notices(player_account_id)) == notices_before


def test_active_autogeneration_returns_retained_program_after_unassignment(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    _end_assignment(client, player_headers)

    _, calls = _auto_generation(db, monkeypatch)
    body = client.get("/programs/active", headers=player_headers).json()
    assert body["program_name"] == "Coach Plan"
    assert body["version"] == 1
    assert body["published_by_coach_account_id"] == coach_account_id
    assert calls["n"] == 0


# --------------------------------------------------------------------------
# 3. PUT /profile-triggered rebuild
# --------------------------------------------------------------------------


def test_profile_rebuild_allowed_before_publication(api, monkeypatch):
    client, db, _ = api
    _, player_headers, _, _, _ = _assigned_player(api)
    _, calls = _profile_generation(db, monkeypatch)

    resp = client.put("/profile", headers=player_headers, json={"weekly_frequency": 3})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["program_rebuilt"] is True
    assert body["program_blocked"] is False
    assert body["program_message"] is None
    assert calls["n"] == 1
    assert _active(db).program_name == "Player Plan"


def test_profile_rebuild_quota_refusal_rolls_back_and_can_retry(shipped_library_api, monkeypatch):
    from service.model_limits import reset_model_limits
    from agent.program_generator import generate_program_pipeline

    client, db = shipped_library_api
    registered = _register(client, "quota-player")
    player_headers = _authed(registered["access_token"])
    player_account_id = db.get_active_account_by_username("quota-player")["account_id"]
    db.switch_user("quota-player")
    db.ledger.upsert_player_profile(
        {
            "equipment_access": "Commercial gym",
            "weekly_frequency": 4,
            "rep_preference": "balanced",
            "weight_kg": 82.55,
        }
    )
    generate_program_pipeline(ledger=db.ledger)
    before_profile = db.ledger.get_player_profile()
    before_program = _active(db, "quota-player")

    # The inference admission gateway refuses this account under a real
    # configured daily token limit, before the generation pipeline is called.
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "1")
    reset_model_limits()
    db.record_model_usage(
        account_id=player_account_id,
        role="player",
        model="test-model",
        input_tokens=1,
        output_tokens=0,
        cost_usd=0,
        estimated=True,
        purpose="test",
    )

    refused = client.put(
        "/profile", headers=player_headers, json={"equipment_access": "Home gym"}
    )
    assert refused.status_code == 429, refused.text
    assert db.ledger.get_player_profile() == before_profile
    after_refusal = _active(db, "quota-player")
    assert (after_refusal.program_name, after_refusal.version) == (
        before_program.program_name,
        before_program.version,
    )
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "0")
    retried = client.put(
        "/profile", headers=player_headers, json={"equipment_access": "Home gym"}
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["profile"]["equipment_access"] == "Home gym"
    assert retried.json()["program_rebuilt"] is True
    rebuilt = _active(db, "quota-player")
    assert rebuilt.version == before_program.version + 1


def test_profile_rebuild_persistence_failure_rolls_back_and_can_retry(shipped_library_api, monkeypatch):
    from service.model_limits import reset_model_limits
    from agent.program_generator import generate_program_pipeline

    client, db = shipped_library_api
    registered = _register(client, "persistence-player")
    player_headers = _authed(registered["access_token"])
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "0")
    reset_model_limits()
    db.switch_user("persistence-player")
    db.ledger.upsert_player_profile(
        {
            "equipment_access": "Commercial gym",
            "weekly_frequency": 3,
            "rep_preference": "balanced",
            "weight_kg": 82.55,
        }
    )
    generate_program_pipeline(ledger=db.ledger)
    before_profile = db.ledger.get_player_profile()
    before_program = _active(db, "persistence-player")
    db.ledger.conn.execute(
        "CREATE TRIGGER reject_profile_rebuild_program "
        "BEFORE INSERT ON training_programs "
        "BEGIN SELECT RAISE(ABORT, 'forced program persistence failure'); END"
    )
    db.ledger.conn.commit()

    failed = client.put(
        "/profile", headers=player_headers, json={"equipment_access": "Home gym"}
    )
    assert failed.status_code == 502, failed.text
    assert db.ledger.get_player_profile() == before_profile
    after_failure = _active(db, "persistence-player")
    assert (after_failure.program_name, after_failure.version) == (
        before_program.program_name,
        before_program.version,
    )

    db.ledger.conn.execute("DROP TRIGGER reject_profile_rebuild_program")
    db.ledger.conn.commit()
    retried = client.put(
        "/profile", headers=player_headers, json={"equipment_access": "Home gym"}
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["profile"]["equipment_access"] == "Home gym"
    assert retried.json()["program_rebuilt"] is True
    rebuilt = _active(db, "persistence-player")
    assert rebuilt.version == before_program.version + 1


@pytest.mark.parametrize(
    ("field", "value", "rebuilds"),
    [
        ("equipment_access", "Home gym", True),
        ("injuries_or_limitations", "Left knee pain", True),
        ("weekly_frequency", 3, True),
        ("rep_preference", "high", True),
        ("current_goal", "Lose fat", False),
        ("weight_kg", 71, False),
    ],
)
def test_profile_edit_rebuild_triggers(api, monkeypatch, field, value, rebuilds):
    client, db, _ = api
    _, player_headers, _, _, _ = _assigned_player(api)
    db.switch_user("p1")
    db.ledger.upsert_player_profile(
        {
            "equipment_access": "Commercial gym",
            "injuries_or_limitations": "None",
            "weekly_frequency": 4,
            "rep_preference": "balanced",
            "current_goal": "Get stronger",
            "weight_kg": 70,
        }
    )
    _, calls = _profile_generation(db, monkeypatch)

    response = client.put("/profile", headers=player_headers, json={field: value})

    assert response.status_code == 200, response.text
    assert response.json()["program_rebuilt"] is rebuilds
    assert calls["n"] == int(rebuilds)
    assert response.json()["profile"][field] == value


def test_profile_refuses_proportions_and_onboarding_only_fields(api):
    client, _, _ = api
    _, player_headers, _, _, _ = _assigned_player(api)

    for field in ("proportions", "height_cm", "age", "gender", "long_term_goal"):
        response = client.put("/profile", headers=player_headers, json={field: "balanced"})
        assert response.status_code == 422, (field, response.text)


def test_intake_exposes_profile_contract_and_rebuild_fields(api):
    client, _, _ = api
    _, player_headers, _, _, _ = _assigned_player(api)

    response = client.get("/onboarding/intake", headers=player_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["profile_rebuild_fields"] == [
        "injuries_or_limitations", "equipment_access", "weekly_frequency", "rep_preference"
    ]
    fields = {field["name"]: field for field in body["fields"]}
    assert (fields["weight_kg"]["minimum"], fields["weight_kg"]["maximum"]) == (30, 250)
    assert (fields["equipment_access"]["allowed_values"] == [
        "Commercial gym", "Home gym", "Bodyweight only"
    ])
    assert (fields["current_goal"]["minimum_length"], fields["current_goal"]["maximum_length"]) == (2, 500)


def test_profile_edit_uses_intake_catalog_validation(api):
    client, _, _ = api
    _, player_headers, _, _, _ = _assigned_player(api)

    for body in (
        {"weight_kg": 29.9},
        {"weight_kg": 250.1},
        {"current_goal": "x"},
        {"injuries_or_limitations": "x"},
    ):
        response = client.put("/profile", headers=player_headers, json=body)
        assert response.status_code == 422, (body, response.text)


def test_profile_rebuild_blocked_during_control(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    before = _active(db)

    _, calls = _profile_generation(db, monkeypatch)
    resp = client.put("/profile", headers=player_headers, json={"weekly_frequency": 3})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["profile"]["weekly_frequency"] == 3
    assert body["program_rebuilt"] is False
    assert body["program_blocked"] is True
    assert body["program_message"] == programs_service.COACH_CONTROLLED_ERROR
    assert calls["n"] == 0
    after = _active(db)
    assert after.program_name == "Coach Plan"
    assert after.version == before.version


def test_coach_frequency_override_preserves_profile_and_drives_weekly_streak_fallback(shipped_library_api):
    client, db = shipped_library_api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player((client, db))
    with db.open_ledger("p1") as ledger:
        ledger.upsert_player_profile({"weekly_frequency": 2})

    published = client.post(
        f"/coach/assignments/{assignment_id}/program",
        headers=coach_headers,
        json={"frequency_override": 4},
    )

    assert published.status_code == 200, published.text
    assert published.json()["weekly_frequency"] == 4
    with db.open_ledger("p1") as ledger:
        assert ledger.get_player_profile()["weekly_frequency"] == 2

    profile_edit = client.put("/profile", headers=player_headers, json={"weekly_frequency": 3})
    assert profile_edit.status_code == 200, profile_edit.text
    assert profile_edit.json()["profile"]["weekly_frequency"] == 3
    assert profile_edit.json()["program_blocked"] is True
    assert client.get("/dashboard/training-status", headers=player_headers).json()["week_target"] == 4


def test_coached_profile_edit_saves_equipment_goal_weight_without_rebuild(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    before = client.get("/programs/active", headers=player_headers).json()
    _, calls = _profile_generation(db, monkeypatch)

    response = client.put(
        "/profile",
        headers=player_headers,
        json={"equipment_access": "Home gym", "current_goal": "Build strength", "weight_kg": 82},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["profile"]["equipment_access"] == "Home gym"
    assert body["profile"]["current_goal"] == "Build strength"
    assert body["profile"]["weight_kg"] == 82
    assert body["program_rebuilt"] is False
    assert body["program_blocked"] is True
    assert body["program_message"] == programs_service.COACH_CONTROLLED_ERROR
    assert calls["n"] == 0
    after = client.get("/programs/active", headers=player_headers).json()
    assert (after["program_name"], after["version"]) == (
        before["program_name"], before["version"]
    )


def test_profile_rebuild_allowed_after_unassignment(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    _end_assignment(client, player_headers)

    _, calls = _profile_generation(db, monkeypatch)
    resp = client.put("/profile", headers=player_headers, json={"weekly_frequency": 3})
    assert resp.status_code == 200, resp.text
    assert resp.json()["program_rebuilt"] is True
    assert calls["n"] == 1
    assert _active(db).program_name == "Player Plan"


# --------------------------------------------------------------------------
# 4. Onboarding completion
# --------------------------------------------------------------------------


def _onboarding_state():
    return {"messages": [], "trainee_id": "p1", "intake_step": 3, "is_complete": True, "profile_data": None}


def test_onboarding_synthesizes_before_publication(api, monkeypatch):
    _, db, _ = api
    _assigned_player(api)
    player_account_id = db.get_active_account_by_username("p1")["account_id"]
    db.switch_user("p1")
    db.ledger.upsert_player_profile({"rep_preference": "balanced"})

    _, calls = _auto_generation(db, monkeypatch)
    result = onboarding_service.complete_onboarding(
        db, "p1", _onboarding_state(), player_account_id=player_account_id
    )
    assert result["program"] is not None
    assert calls["n"] == 1
    assert _active(db).version == 1


def test_onboarding_leaves_coach_program_unchanged_during_control(api, monkeypatch):
    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    before = _active(db)

    _, calls = _auto_generation(db, monkeypatch)
    pipeline = MagicMock(return_value=(_program(), "md"))
    monkeypatch.setattr("agent.program_generator.generate_program_pipeline", pipeline)

    result = onboarding_service.complete_onboarding(
        db, "p1", _onboarding_state(), player_account_id=player_account_id
    )
    assert result["program"] is not None
    assert result["program"].program_name == "Coach Plan"
    assert result["program"].version == before.version
    assert calls["n"] == 0
    pipeline.assert_not_called()
    assert _active(db).version == before.version


def test_onboarding_leaves_retained_program_unchanged_after_unassignment(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, player_account_id = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    _end_assignment(client, player_headers)
    before = _active(db)

    _, calls = _auto_generation(db, monkeypatch)
    result = onboarding_service.complete_onboarding(
        db, "p1", _onboarding_state(), player_account_id=player_account_id
    )
    assert result["program"].version == before.version
    assert calls["n"] == 0
    assert _active(db).version == before.version


def test_onboarding_coach_controlled_without_saved_program_writes_welcome(api, monkeypatch):
    _, db, _ = api
    _assigned_player(api)
    player_account_id = db.get_active_account_by_username("p1")["account_id"]

    monkeypatch.setattr(programs_service, "player_controls_program", lambda *args, **kwargs: False)

    result = onboarding_service.complete_onboarding(
        db, "p1", _onboarding_state(), player_account_id=player_account_id
    )
    assert result["program"] is None
    assert result["program_message"] == programs_service.COACH_CONTROLLED_ERROR
    with db.open_ledger("p1") as ledger:
        history = ledger.get_chat_history()
    assert any(
        message["role"] == "assistant"
        and f"Welcome! {programs_service.COACH_CONTROLLED_ERROR}" in message["content"]
        for message in history
    )


# --------------------------------------------------------------------------
# 5. Assistant chat mutation and exercise swap
# --------------------------------------------------------------------------


def test_assistant_mutation_proceeds_before_publication(api, monkeypatch):
    from agent import assistant_graph
    from langchain_core.messages import HumanMessage

    client, db, _ = api
    _, _, _, _, player_account_id = _assigned_player(api)

    pipeline = MagicMock(return_value=(_program("Mutated Plan"), "md"))
    monkeypatch.setattr(assistant_graph, "generate_program_pipeline", pipeline)
    db.switch_user("p1")

    state = {
        "messages": [HumanMessage(content="rebuild my program")],
        "trainee_id": "p1",
        "player_account_id": player_account_id,
        "intent": "program_mutation",
        "intent_metadata": {"target_frequency": None},
    }
    result = assistant_graph.program_mutation_node(state, {"configurable": {"ledger": db.ledger, "store": db}})
    assert result["program_updated"] is True
    pipeline.assert_called_once()


def test_assistant_mutation_refused_during_control(api, monkeypatch):
    from agent import assistant_graph
    from langchain_core.messages import HumanMessage

    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    pipeline = MagicMock(return_value=(_program("Mutated Plan"), "md"))
    monkeypatch.setattr(assistant_graph, "generate_program_pipeline", pipeline)
    db.switch_user("p1")

    state = {
        "messages": [HumanMessage(content="rebuild my program")],
        "trainee_id": "p1",
        "player_account_id": player_account_id,
        "intent": "program_mutation",
        "intent_metadata": {"target_frequency": None},
    }
    result = assistant_graph.program_mutation_node(state, {"configurable": {"ledger": db.ledger, "store": db}})
    assert result["response_content"] == programs_service.COACH_CONTROLLED_REQUEST_ERROR
    assert result["request_suggestion"]["kind"] == "split_change"
    pipeline.assert_not_called()


def test_assistant_mutation_proceeds_after_unassignment(api, monkeypatch):
    from agent import assistant_graph
    from langchain_core.messages import HumanMessage

    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, player_account_id = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    _end_assignment(client, player_headers)

    pipeline = MagicMock(return_value=(_program("Mutated Plan"), "md"))
    monkeypatch.setattr(assistant_graph, "generate_program_pipeline", pipeline)
    db.switch_user("p1")

    state = {
        "messages": [HumanMessage(content="rebuild my program")],
        "trainee_id": "p1",
        "player_account_id": player_account_id,
        "intent": "program_mutation",
        "intent_metadata": {"target_frequency": None},
    }
    result = assistant_graph.program_mutation_node(state, {"configurable": {"ledger": db.ledger, "store": db}})
    assert result["program_updated"] is True
    pipeline.assert_called_once()


def test_assistant_swap_proceeds_before_publication(api, monkeypatch):
    from agent import assistant_graph
    from langchain_core.messages import HumanMessage

    client, db, _ = api
    _, player_headers, _, _, player_account_id = _assigned_player(api)

    _, calls = _player_generation(db, monkeypatch)
    generated = client.post("/programs/generate", headers=player_headers, json={})
    assert generated.status_code == 200, generated.text
    assert calls["n"] == 1

    db.switch_user("p1")
    state = {
        "messages": [HumanMessage(content="swap bench press for dumbbell press")],
        "trainee_id": "p1",
        "player_account_id": player_account_id,
        "intent": "exercise_substitution",
        "intent_metadata": {"mode": "direct_swap", "source_exercise": "Bench Press", "target_exercise": "Dumbbell Press"},
    }
    result = assistant_graph.exercise_substitution_node(state, {"configurable": {"ledger": db.ledger, "store": db}})
    assert result["response_content"] != programs_service.COACH_CONTROLLED_ERROR
    active = db.ledger.get_active_program()
    assert active.version == 2
    assert active.days[0].exercises[1].exercise_id == "dbp"
    rows = db.conn.execute(
        "SELECT version, is_active, published_by_coach_account_id FROM training_programs ORDER BY version"
    ).fetchall()
    assert [(row[0], row[1], row[2]) for row in rows] == [(1, 0, None), (2, 1, None)]


def test_assistant_swap_refused_during_control(api, monkeypatch):
    from agent import assistant_graph
    from langchain_core.messages import HumanMessage

    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    db.switch_user("p1")
    swap = MagicMock()
    monkeypatch.setattr(assistant_graph, "substitute_program_exercise", swap)

    state = {
        "messages": [HumanMessage(content="swap bench press for dumbbell press")],
        "trainee_id": "p1",
        "player_account_id": player_account_id,
        "intent": "exercise_substitution",
        "intent_metadata": {"mode": "direct_swap", "source_exercise": "Bench Press", "target_exercise": "Dumbbell Press"},
    }
    result = assistant_graph.exercise_substitution_node(state, {"configurable": {"ledger": db.ledger, "store": db}})
    assert result["response_content"] == programs_service.COACH_CONTROLLED_REQUEST_ERROR
    assert result["request_suggestion"]["kind"] == "exercise_substitution"
    swap.assert_not_called()


def test_chat_api_suggests_prefilled_substitution_only_from_resolved_ledger_facts(api, monkeypatch):
    from agent import assistant_graph
    from service.program_requests import MAX_REASON_CHARS
    from svc.routers import chat as chat_router

    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    monkeypatch.setattr(chat_router, "admit_model_request", lambda *args, **kwargs: None)

    content = "swap bench press for dumbbell press"
    done = _chat_done_event(client, player_headers, content)
    assert done["response_content"] == programs_service.COACH_CONTROLLED_REQUEST_ERROR
    assert done["program_updated"] is False
    assert done["request_suggestion"] == {
        "kind": "exercise_substitution",
        "day_name": "Full A",
        "exercise_id": "bp",
        "replacement_exercise_id": "dbp",
        "reason": content,
    }

    unresolved = "swap bench-ish press for dumbbell press"
    unresolved_done = _chat_done_event(client, player_headers, unresolved)
    assert unresolved_done["request_suggestion"]["day_name"] is None
    assert unresolved_done["request_suggestion"]["exercise_id"] is None
    assert unresolved_done["request_suggestion"]["replacement_exercise_id"] == "dbp"

    long_reason = f"{content} " + "details " * 100
    db.switch_user("p1")
    substitution_suggestion = assistant_graph._substitution_request_suggestion(
        db,
        db.ledger,
        long_reason,
        {"source_exercise": "Bench Press", "target_exercise": "Dumbbell Press"},
    )
    split_suggestion = assistant_graph._split_change_request_suggestion(
        long_reason, {}
    )
    assert substitution_suggestion["reason"] == long_reason[:MAX_REASON_CHARS]
    assert split_suggestion["reason"] == long_reason[:MAX_REASON_CHARS]
    history = client.get("/chat/history", headers=player_headers).json()
    assert all("request_suggestion" not in message for message in history)
    db.switch_user("p1")
    assert db.ledger.get_active_program().version == 1


def test_chat_api_suggests_split_change_for_coach_controlled_mutation(api, monkeypatch):
    from svc.routers import chat as chat_router

    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    monkeypatch.setattr(chat_router, "admit_model_request", lambda *args, **kwargs: None)

    content = "change routine to 3 days من فضلك"
    done = _chat_done_event(client, player_headers, content)
    assert done["response_content"] == (
        "يتولى مدربك المعيّن التحكم في برنامجك التدريبي. "
        "يمكنك مراجعة طلب وإرساله إلى مدربك."
    )
    assert done["program_updated"] is False
    assert done["request_suggestion"] == {
        "kind": "split_change",
        "desired_weekly_frequency": 3,
        "desired_split_preference": None,
        "reason": content,
    }
    unresolved = _chat_done_event(client, player_headers, "change routine to 7 days")
    assert unresolved["request_suggestion"]["desired_weekly_frequency"] is None


def test_chat_api_composite_refusal_keeps_only_the_first_suggestion(api, monkeypatch):
    from svc.routers import chat as chat_router

    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    monkeypatch.setattr(chat_router, "admit_model_request", lambda *args, **kwargs: None)

    done = _chat_done_event(
        client,
        player_headers,
        "swap bench press for dumbbell press; change routine to 3 days",
    )
    assert done["request_suggestion"] == {
        "kind": "exercise_substitution",
        "day_name": "Full A",
        "exercise_id": "bp",
        "replacement_exercise_id": "dbp",
        "reason": "swap bench press for dumbbell press",
    }
    db.switch_user("p1")
    assert db.ledger.get_active_program().version == 1


def test_chat_api_keeps_deload_choice_available_under_coach_authority(api, monkeypatch):
    from service import workouts as workouts_service
    from svc.routers import chat as chat_router

    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    monkeypatch.setattr(chat_router, "admit_model_request", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        workouts_service,
        "build_prescription",
        lambda *args, **kwargs: {
            "deload": {"state": "suggested", "reason": "fatigue signal"}
        },
    )

    done = _chat_done_event(client, player_headers, "apply the deload")
    assert done["program_updated"] is True
    assert "request_suggestion" not in done
    db.switch_user("p1")
    assert db.ledger.get_deload_choice() == "apply"


def test_chat_api_edits_player_controlled_program_without_suggestion(api, monkeypatch):
    from agent import assistant_graph
    from svc.routers import chat as chat_router

    client, db, _ = api
    _, player_headers, _, _, _ = _assigned_player(api)
    _, calls = _player_generation(db, monkeypatch)
    assert client.post("/programs/generate", headers=player_headers, json={}).status_code == 200
    pipeline, mutation_calls = _counting_saver(db, "Mutated Plan")
    monkeypatch.setattr(assistant_graph, "generate_program_pipeline", pipeline)
    monkeypatch.setattr(chat_router, "admit_model_request", lambda *args, **kwargs: None)

    done = _chat_done_event(client, player_headers, "rebuild my program")
    assert done["program_updated"] is True
    assert "request_suggestion" not in done
    assert calls["n"] == 1
    assert mutation_calls["n"] == 1
    db.switch_user("p1")
    assert db.ledger.get_active_program().program_name == "Mutated Plan"


def test_chat_api_edits_player_controlled_exercise_without_suggestion(api, monkeypatch):
    from svc.routers import chat as chat_router

    client, db, _ = api
    _, player_headers, _, _, _ = _assigned_player(api)
    _player_generation(db, monkeypatch)
    assert client.post("/programs/generate", headers=player_headers, json={}).status_code == 200
    monkeypatch.setattr(chat_router, "admit_model_request", lambda *args, **kwargs: None)

    done = _chat_done_event(
        client, player_headers, "swap bench press for dumbbell press"
    )
    assert done["program_updated"] is True
    assert "request_suggestion" not in done
    db.switch_user("p1")
    assert db.ledger.get_active_program().days[0].exercises[1].exercise_id == "dbp"


def test_assistant_swap_proceeds_after_unassignment(api, monkeypatch):
    from agent import assistant_graph
    from langchain_core.messages import HumanMessage

    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, player_account_id = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    _end_assignment(client, player_headers)

    db.switch_user("p1")
    state = {
        "messages": [HumanMessage(content="swap bench press for dumbbell press")],
        "trainee_id": "p1",
        "player_account_id": player_account_id,
        "intent": "exercise_substitution",
        "intent_metadata": {"mode": "direct_swap", "source_exercise": "Bench Press", "target_exercise": "Dumbbell Press"},
    }
    result = assistant_graph.exercise_substitution_node(state, {"configurable": {"ledger": db.ledger, "store": db}})
    assert result["response_content"] != programs_service.COACH_CONTROLLED_ERROR
    active = db.ledger.get_active_program()
    assert active.version == 2
    assert active.days[0].exercises[1].exercise_id == "dbp"


def test_assistant_substitution_targets_named_day_and_publishes_version(api, monkeypatch):
    from agent import assistant_graph
    from agent.fitness_abbreviations import AbbreviationExpansion
    from copy import deepcopy
    from langchain_core.messages import HumanMessage

    client, db, _ = api
    _, player_headers, _, _, player_account_id = _assigned_player(api)
    _, calls = _player_generation(db, monkeypatch)
    generated = client.post("/programs/generate", headers=player_headers, json={})
    assert generated.status_code == 200, generated.text
    assert calls["n"] == 1

    db.switch_user("p1")
    original = db.ledger.get_active_program()
    program_data = original.model_dump()
    program_data.pop("created_at", None)
    second_day = deepcopy(program_data["days"][0])
    second_day["day_name"] = "Full B"
    second_day["day_order"] = 2
    program_data["days"].append(second_day)
    db.ledger.save_training_program(program_data)

    structured_model = MagicMock()
    structured_model.invoke.return_value = AbbreviationExpansion(
        is_fitness_movement=True,
        canonical_name="dumbbell press",
    )
    model = MagicMock()
    model.with_structured_output.return_value = structured_model
    monkeypatch.setattr("agent.fitness_abbreviations.llm", model)

    state = {
        "messages": [HumanMessage(content="swap bench press for XYZ on Full B")],
        "trainee_id": "p1",
        "player_account_id": player_account_id,
        "intent": "exercise_substitution",
        "intent_metadata": {
            "mode": "direct_swap",
            "source_exercise": "Bench Press",
            "target_exercise": "XYZ on Full B",
        },
    }
    result = assistant_graph.exercise_substitution_node(state, {"configurable": {"ledger": db.ledger, "store": db}})

    assert result["program_updated"] is True, result["response_content"]
    structured_model.invoke.assert_called_once()
    active = db.ledger.get_active_program()
    assert active.version == 3
    assert active.days[0].day_name == "Full A"
    assert active.days[0].exercises[1].exercise_id == "bp"
    assert active.days[1].day_name == "Full B"
    assert active.days[1].exercises[1].exercise_id == "dbp"
    rows = db.conn.execute(
        "SELECT version, is_active, published_by_coach_account_id FROM training_programs ORDER BY version"
    ).fetchall()
    assert [(row[0], row[1], row[2]) for row in rows] == [(1, 0, None), (2, 0, None), (3, 1, None)]
