"""API contract tests for player Exercise substitution (#169)."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import (
    GeneratedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
)
from database.database_manager import DatabaseManager
from service import coach as coach_service
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
        "INSERT INTO exercises (id, name, body_part, target_muscle, instructions, image_path, gif_path) VALUES"
        " ('sq', 'Squat', 'Upper Legs', 'Quads', 'Sit back.', 'squat.png', 'squat.gif'),"
        " ('bp', 'Bench Press', 'Chest', 'Chest', 'Press steadily.', 'bench.png', 'bench.gif'),"
        " ('row', 'Row', 'Back', 'Back', 'Pull to ribs.', 'row.png', 'row.gif'),"
        " ('ohp', 'Overhead Press', 'Shoulders', 'Shoulders', 'Press overhead with control', 'ohp.png', 'ohp.gif');"
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


def _register(client, username: str, password: str = "correct-horse-1") -> dict:
    response = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert response.status_code == 201, response.text
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _exercise(exercise_id: str, name: str) -> ProgramExerciseSchema:
    return ProgramExerciseSchema(
        exercise_id=exercise_id,
        exercise_name=name,
        warmup_sets=1,
        target_sets=3,
        target_reps_min=6,
        target_reps_max=9,
        target_rpe=8.0,
        rest_seconds=120,
        notes="Keep the same prescription.",
    )


def _program() -> GeneratedProgramSchema:
    return GeneratedProgramSchema(
        program_name="Player Plan",
        split_type="Full Body",
        weekly_frequency=2,
        days=[
            ProgramDaySchema(
                day_name="Full A",
                day_order=1,
                exercises=[_exercise("sq", "Squat"), _exercise("bp", "Bench Press"), _exercise("row", "Row")],
            ),
            ProgramDaySchema(
                day_name="Full B",
                day_order=2,
                exercises=[_exercise("sq", "Squat"), _exercise("bp", "Bench Press"), _exercise("row", "Row")],
            ),
        ],
    )


def _make_player_with_program(client, db):
    registered = _register(client, "player")
    headers = _headers(registered["access_token"])
    db.switch_user("player")
    db.ledger.save_training_program(_program().model_dump())
    return headers


def test_substitution_changes_only_named_slot_and_keeps_old_version(api):
    client, db = api
    headers = _make_player_with_program(client, db)

    response = client.post(
        "/programs/active/substitutions",
        headers=headers,
        json={"day_name": "Full A", "exercise_id": "sq", "replacement_exercise_id": "ohp"},
    )

    assert response.status_code == 200, response.text
    substitution_response = response.json()
    active = substitution_response
    assert substitution_response["previous_version"] == 1
    assert substitution_response["version"] == 2
    assert active["version"] == 2
    assert active["published_by_coach_account_id"] is None
    assert active["days"][0]["exercises"][0]["exercise_id"] == "ohp"
    assert active["days"][0]["exercises"][0]["exercise_name"] == "Overhead Press"
    assert active["days"][0]["exercises"][0]["notes"] == "Press overhead with control"
    assert active["days"][0]["exercises"][0]["image_path"] == "ohp.png"
    assert active["days"][0]["exercises"][0]["gif_path"] == "ohp.gif"
    assert (
        active["days"][0]["exercises"][0]["warmup_sets"],
        active["days"][0]["exercises"][0]["target_sets"],
        active["days"][0]["exercises"][0]["target_reps_min"],
        active["days"][0]["exercises"][0]["target_reps_max"],
        active["days"][0]["exercises"][0]["target_rpe"],
        active["days"][0]["exercises"][0]["rest_seconds"],
    ) == (1, 3, 6, 9, 8.0, 120)
    assert active["days"][1]["exercises"][0]["exercise_id"] == "sq"
    assert db.ledger.get_program_by_version(1).days[0].exercises[0].exercise_id == "sq"


def test_all_occurrences_undo_restores_exact_snapshot_with_existing_replacement(api):
    client, db = api
    registered = _register(client, "player")
    headers = _headers(registered["access_token"])
    db.switch_user("player")
    program = _program().model_dump()
    # The chosen replacement already exists on Full B, where the source does
    # not occur. Undo must restore that exact pre-existing slot and prescription.
    program["days"][1]["exercises"][0].update(
        exercise_id="ohp", exercise_name="Overhead Press", notes="Existing OHP",
        image_path="existing.png", gif_path="existing.gif", target_sets=4,
    )
    db.ledger.save_training_program(program)
    original = db.ledger.get_active_program()
    original_days = [day.model_dump() for day in original.days]

    swapped = client.post(
        "/programs/active/substitutions",
        headers=headers,
        json={
            "day_name": "Full A",
            "exercise_id": "sq",
            "replacement_exercise_id": "ohp",
            "all_occurrences": True,
        },
    )
    assert swapped.status_code == 200, swapped.text
    assert swapped.json()["previous_version"] == 1
    assert swapped.json()["version"] == 2
    assert [day["exercises"][0]["exercise_id"] for day in swapped.json()["days"]] == ["ohp", "ohp"]

    undone = client.post(
        "/programs/active/substitutions/undo",
        headers=headers,
        json={"restore_version": 1, "expected_active_version": 2},
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["version"] == 3
    assert undone.json()["published_by_coach_account_id"] is None
    assert [day for day in undone.json()["days"]] == original_days
    assert db.ledger.get_program_by_version(2).days[0].exercises[0].exercise_id == "ohp"


def test_undo_restores_duplicate_source_slots_on_the_same_day(api):
    client, db = api
    headers = _make_player_with_program(client, db)
    program = db.ledger.get_active_program().model_dump()
    program["days"][0]["exercises"].append(dict(program["days"][0]["exercises"][0]))
    db.ledger.save_training_program(program)
    original = db.ledger.get_active_program()
    original_days = [day.model_dump() for day in original.days]

    swapped = client.post(
        "/programs/active/substitutions",
        headers=headers,
        json={
            "day_name": "Full A",
            "exercise_id": "sq",
            "replacement_exercise_id": "ohp",
            "all_occurrences": True,
        },
    )
    assert swapped.status_code == 200, swapped.text
    assert all(
        exercise["exercise_id"] == "ohp"
        for day in swapped.json()["days"]
        for exercise in day["exercises"]
        if exercise["exercise_id"] in {"sq", "ohp"}
    )
    undone = client.post(
        "/programs/active/substitutions/undo",
        headers=headers,
        json={"restore_version": 2, "expected_active_version": 3},
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["days"] == original_days


def test_substitution_expected_version_and_undo_reject_stale_program(api):
    client, db = api
    headers = _make_player_with_program(client, db)
    stale = client.post(
        "/programs/active/substitutions",
        headers=headers,
        json={"day_name": "Full A", "exercise_id": "sq", "replacement_exercise_id": "ohp", "expected_active_version": 9},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "The program changed since this substitution"
    swapped = client.post(
        "/programs/active/substitutions",
        headers=headers,
        json={"day_name": "Full A", "exercise_id": "sq", "replacement_exercise_id": "ohp"},
    )
    assert swapped.status_code == 200, swapped.text
    newer = db.ledger.get_active_program().model_dump()
    newer["program_name"] = "Later plan"
    db.ledger.save_training_program(newer)
    stale_undo = client.post(
        "/programs/active/substitutions/undo",
        headers=headers,
        json={"restore_version": 1, "expected_active_version": 2},
    )
    assert stale_undo.status_code == 409
    assert stale_undo.json()["detail"] == "The program changed since this substitution"


@pytest.mark.parametrize(
    ("body", "status_code", "message"),
    [
        ({"day_name": "Missing", "exercise_id": "sq", "replacement_exercise_id": "ohp"}, 400, "That day is not part of your current program."),
        ({"day_name": "Full A", "exercise_id": "missing", "replacement_exercise_id": "ohp"}, 400, "That exercise is not in that day of your current program."),
        ({"day_name": "Full A", "exercise_id": "sq", "replacement_exercise_id": "sq"}, 400, "Choose a different replacement exercise."),
        ({"day_name": "Full A", "exercise_id": "sq", "replacement_exercise_id": "missing"}, 404, "That replacement exercise was not found."),
        ({"day_name": "Full A", "exercise_id": "sq", "replacement_exercise_id": "bp"}, 400, "That replacement exercise is already on the target day."),
    ],
)
def test_substitution_validation_returns_clear_client_error(api, body, status_code, message):
    client, db = api
    headers = _make_player_with_program(client, db)

    response = client.post("/programs/active/substitutions", headers=headers, json=body)

    assert response.status_code == status_code
    assert response.json()["detail"] == message
    assert db.ledger.get_active_program().version == 1


def test_substitution_refuses_a_coach_controlled_program(api):
    client, db = api
    coach = _register(client, "coach")
    coach_headers = _headers(coach["access_token"])
    issued = coach_service.issue_coach_invite(db, "coach")
    assert issued["ok"]
    assert client.post("/coach/invite/redeem", headers=coach_headers, json={"token": issued["token"]}).status_code == 200
    assert client.put(
        "/coach/profile",
        headers=coach_headers,
        json={"display_name": "Coach", "bio": "", "specialization": "Strength", "capacity": 5},
    ).status_code == 200
    invite = client.post("/coach/assignments/invites", headers=coach_headers)
    player = _register(client, "player")
    player_headers = _headers(player["access_token"])
    joined = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite.json()["token"], "consent": True},
    )
    assert joined.status_code == 200, joined.text
    coach_account_id = db.get_active_account_by_username("coach")["account_id"]
    db.switch_user("player")
    db.ledger.save_training_program(
        _program().model_dump(), published_by_coach_account_id=coach_account_id
    )

    response = client.post(
        "/programs/active/substitutions",
        headers=player_headers,
        json={"day_name": "Full A", "exercise_id": "sq", "replacement_exercise_id": "ohp"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Your assigned coach controls your program. Ask your coach for changes."
    undo = client.post(
        "/programs/active/substitutions/undo",
        headers=player_headers,
        json={"restore_version": 1, "expected_active_version": 1},
    )
    assert undo.status_code == 403
    assert undo.json()["detail"] == response.json()["detail"]
