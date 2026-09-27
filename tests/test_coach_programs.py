"""Coach program publication contract tests (ticket #26).

Exercises the public FastAPI surface against real temporary SQLite catalogs and
player ledgers. Covers assignment-gated publication with coach provenance and a
stable version, the player's in-app notice, program authority transfer (player
self-service before publication, refused after), retention and authority return
on unassignment, version increments, and the generic denial for every
non-active assignment case.
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import (
    GeneratedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
)
from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import coach_history as coach_history_service
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
        " ('row', 'Row', 'Back', 'Back');"
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


def _register(client, username, password="correct-horse-1"):
    resp = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _subject(token):
    return pyjwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])["sub"]


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


def _program() -> GeneratedProgramSchema:
    return GeneratedProgramSchema(
        program_name="Coach Plan",
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


def _coach_generation(db, monkeypatch):
    """Replaces the LLM-free pipeline at the coach service seam, saving through the real ledger."""

    def fake(**kwargs):
        program = _program()
        kwargs["ledger"].save_training_program(
            program.model_dump(),
            published_by_coach_account_id=kwargs.get("published_by_coach_account_id"),
        )
        return program, "md"

    monkeypatch.setattr("service.coach_programs.generate_program_pipeline", fake)


def _player_generation(db, monkeypatch):
    """Replaces the pipeline at the player router seam (self-service, no provenance)."""

    def fake(**kwargs):
        program = _program()
        kwargs["ledger"].save_training_program(program.model_dump())
        return program, "md"

    monkeypatch.setattr("svc.routers.programs.generate_program_pipeline", fake)


def _publish(client, coach_headers, assignment_id, **body):
    return client.post(f"/coach/assignments/{assignment_id}/program", headers=coach_headers, json=body)


# --------------------------------------------------------------------------
# Publication, provenance, version, notice
# --------------------------------------------------------------------------


def test_publish_activates_immediately_with_provenance_and_notice(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)

    published = _publish(client, coach_headers, assignment_id, frequency_override=3)
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["version"] == 1
    assert body["published_by_coach_account_id"] == coach_account_id

    active = client.get("/programs/active", headers=player_headers).json()
    assert active["version"] == 1
    assert active["published_by_coach_account_id"] == coach_account_id

    notices = client.get("/assignments/notices", headers=player_headers).json()["notices"]
    assert len(notices) == 1
    assert notices[0]["kind"] == "program_published"
    assert "version 1" in notices[0]["message"]
    assert notices[0]["read_at"] is None

    marked = client.post("/assignments/notices/read", headers=player_headers)
    assert marked.status_code == 200
    assert marked.json()["marked_read"] == 1
    assert client.get("/assignments/notices", headers=player_headers).json()["notices"][0]["read_at"] is not None


def test_second_publish_increments_version_and_keeps_first_stable(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)

    assert _publish(client, coach_headers, assignment_id).json()["version"] == 1
    assert _publish(client, coach_headers, assignment_id).json()["version"] == 2

    assert client.get("/programs/active", headers=player_headers).json()["version"] == 2

    db.switch_user("p1")
    rows = db.conn.execute(
        "SELECT version, published_by_coach_account_id FROM training_programs ORDER BY version ASC"
    ).fetchall()
    assert [int(row[0]) for row in rows] == [1, 2]
    assert all(row[1] == coach_account_id for row in rows)


# --------------------------------------------------------------------------
# Program authority
# --------------------------------------------------------------------------


def test_player_self_service_works_while_assigned_before_first_publication(api, monkeypatch):
    client, db, _ = api
    _, player_headers, assignment_id, _, _ = _assigned_player(api)
    _player_generation(db, monkeypatch)

    generated = client.post("/programs/generate", headers=player_headers, json={})
    assert generated.status_code == 200, generated.text

    active = client.get("/programs/active", headers=player_headers).json()
    assert active["published_by_coach_account_id"] is None


def test_player_generate_refused_after_publication(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    refused = client.post("/programs/generate", headers=player_headers, json={})
    assert refused.status_code == 403
    assert refused.json()["detail"] == programs_service.COACH_CONTROLLED_ERROR


def test_assistant_swap_refused_when_coach_controls_program(api, monkeypatch):
    from agent import assistant_graph

    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, player_account_id = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    db.switch_user("p1")
    swap = MagicMock(return_value=True)
    monkeypatch.setattr(db.ledger, "swap_program_exercise", swap)

    from langchain_core.messages import HumanMessage

    state = {
        "messages": [HumanMessage(content="swap squat for bench press")],
        "trainee_id": "p1",
        "player_account_id": player_account_id,
        "intent": "exercise_substitution",
        "intent_metadata": {"mode": "direct_swap", "source_exercise": "Squat", "target_exercise": "Bench Press"},
    }
    result = assistant_graph.exercise_substitution_node(
        state, {"configurable": {"ledger": db.ledger, "store": db}}
    )
    assert result["response_content"] == programs_service.COACH_CONTROLLED_ERROR
    swap.assert_not_called()


def test_assistant_mutation_refused_when_coach_controls_program(api, monkeypatch):
    from agent import assistant_graph
    from langchain_core.messages import HumanMessage

    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    pipeline = MagicMock(return_value=(_program(), "md"))
    monkeypatch.setattr(assistant_graph, "generate_program_pipeline", pipeline)
    db.switch_user("p1")

    state = {
        "messages": [HumanMessage(content="rebuild my program")],
        "trainee_id": "p1",
        "player_account_id": player_account_id,
        "intent": "program_mutation",
        "intent_metadata": {"target_frequency": None},
    }
    result = assistant_graph.program_mutation_node(
        state, {"configurable": {"ledger": db.ledger, "store": db}}
    )
    assert result["response_content"] == programs_service.COACH_CONTROLLED_ERROR
    pipeline.assert_not_called()


# --------------------------------------------------------------------------
# Unassignment retains content and returns authority
# --------------------------------------------------------------------------


@pytest.mark.parametrize("ended_by", ["coach", "player"])
def test_unassignment_retains_program_and_returns_authority(api, monkeypatch, ended_by):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    if ended_by == "coach":
        ended = client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers)
    else:
        ended = client.post("/assignments/me/end", headers=player_headers)
    assert ended.status_code == 200, ended.text

    retained = client.get("/programs/active", headers=player_headers).json()
    assert retained["version"] == 1
    assert retained["published_by_coach_account_id"] == coach_account_id

    _player_generation(db, monkeypatch)
    assert client.post("/programs/generate", headers=player_headers, json={}).status_code == 200

    denied = _publish(client, coach_headers, assignment_id)
    assert denied.status_code == 403
    assert denied.json()["detail"] == coach_history_service.DENIED_ERROR


def test_fresh_assignment_before_publication_keeps_self_service(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    assert client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers).status_code == 200

    new_token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    redeemed = client.post(
        "/assignments/invites/redeem", headers=player_headers, json={"token": new_token, "consent": True}
    )
    assert redeemed.status_code == 200, redeemed.text

    retained = client.get("/programs/active", headers=player_headers).json()
    assert retained["version"] == 1
    assert retained["published_by_coach_account_id"] == coach_account_id

    _player_generation(db, monkeypatch)
    generated = client.post("/programs/generate", headers=player_headers, json={})
    assert generated.status_code == 200, generated.text


# --------------------------------------------------------------------------
# Denial is generic
# --------------------------------------------------------------------------


def test_non_coach_cannot_publish(api, monkeypatch):
    client, db, _ = api
    _, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)

    denied = _publish(client, player_headers, assignment_id)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Coach capability required."


def test_unknown_and_other_coach_assignments_are_indistinguishable(api, monkeypatch):
    client, db, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    other_headers = _make_coach(client, db, "intruder", capacity=5)

    other = _publish(client, other_headers, assignment_id)
    unknown = _publish(client, other_headers, "does-not-exist")
    assert other.status_code == unknown.status_code == 403
    assert other.json()["detail"] == unknown.json()["detail"] == coach_history_service.DENIED_ERROR


def test_publish_requires_authentication(api):
    client, _, _ = api
    assert client.post("/coach/assignments/x/program").status_code == 401
