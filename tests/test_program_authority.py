"""Program authority enforcement across every player write path (ticket #27).

Builds on ADR 026's single ``player_controls_program`` decision: a player cannot
change a coach-controlled program through any route or assistant action. Covers
direct generation, active-program auto-generation, profile-triggered rebuild,
onboarding completion, chat program mutation, and assistant exercise swap —
each before coach publication, during coach control, and after unassignment.
"""

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
        users_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db, tmp_path / "users"
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


def _assigned_player(api, player_name="p1"):
    """Coach "coach" is actively assigned "p1"; returns headers, assignment id, accounts."""
    client, db, _ = api
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
    db.ledger.upsert_user_profile({"rep_preference": "balanced"})

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
    db.ledger.upsert_user_profile({"rep_preference": "balanced"})

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
    assert result["response_content"] == programs_service.COACH_CONTROLLED_ERROR
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
    swap = MagicMock(return_value=True)
    monkeypatch.setattr(db.ledger, "swap_program_exercise", swap)

    state = {
        "messages": [HumanMessage(content="swap bench press for dumbbell press")],
        "trainee_id": "p1",
        "player_account_id": player_account_id,
        "intent": "exercise_substitution",
        "intent_metadata": {"mode": "direct_swap", "source_exercise": "Bench Press", "target_exercise": "Dumbbell Press"},
    }
    result = assistant_graph.exercise_substitution_node(state, {"configurable": {"ledger": db.ledger, "store": db}})
    assert result["response_content"] != programs_service.COACH_CONTROLLED_ERROR
    swap.assert_called_once()


def test_assistant_swap_refused_during_control(api, monkeypatch):
    from agent import assistant_graph
    from langchain_core.messages import HumanMessage

    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    db.switch_user("p1")
    swap = MagicMock(return_value=True)
    monkeypatch.setattr(db.ledger, "swap_program_exercise", swap)

    state = {
        "messages": [HumanMessage(content="swap bench press for dumbbell press")],
        "trainee_id": "p1",
        "player_account_id": player_account_id,
        "intent": "exercise_substitution",
        "intent_metadata": {"mode": "direct_swap", "source_exercise": "Bench Press", "target_exercise": "Dumbbell Press"},
    }
    result = assistant_graph.exercise_substitution_node(state, {"configurable": {"ledger": db.ledger, "store": db}})
    assert result["response_content"] == programs_service.COACH_CONTROLLED_ERROR
    swap.assert_not_called()


def test_assistant_swap_proceeds_after_unassignment(api, monkeypatch):
    from agent import assistant_graph
    from langchain_core.messages import HumanMessage

    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, player_account_id = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    _end_assignment(client, player_headers)

    db.switch_user("p1")
    swap = MagicMock(return_value=True)
    monkeypatch.setattr(db.ledger, "swap_program_exercise", swap)

    state = {
        "messages": [HumanMessage(content="swap bench press for dumbbell press")],
        "trainee_id": "p1",
        "player_account_id": player_account_id,
        "intent": "exercise_substitution",
        "intent_metadata": {"mode": "direct_swap", "source_exercise": "Bench Press", "target_exercise": "Dumbbell Press"},
    }
    result = assistant_graph.exercise_substitution_node(state, {"configurable": {"ledger": db.ledger, "store": db}})
    assert result["response_content"] != programs_service.COACH_CONTROLLED_ERROR
    swap.assert_called_once()
