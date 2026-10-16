"""Catalog-side Program template contract tests (ticket #305).

Exercises the public FastAPI surface against a real temporary catalog. Covers
owner-scoped CRUD, archive/unarchive, duplicate independence, publish-equivalent
validation, and the guarantee that a template holds no player data and never
mounts a player ledger.
"""

import sqlite3
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from database.registry.coach_exercises import CoachExerciseCreate
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
    from service.analytics import override_analytics_preference_reader

    override_analytics_preference_reader(db.analytics_preference_allows)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db, tmp_path / "users"
    finally:
        override_analytics_preference_reader(None)
        if db.ledger_conn is not None:
            db.ledger_conn.close()
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
            json={
                "display_name": f"Coach {username}",
                "bio": "b",
                "specialization": "s",
                "capacity": capacity,
            },
        ).status_code
        == 200
    )
    return headers


def _program(exercise_id="sq", **overrides):
    exercise = {
        "exercise_id": exercise_id,
        "exercise_name": "Squat",
        "target_sets": 3,
        "target_reps_min": 5,
        "target_reps_max": 8,
        "target_rir": 2.0,
        "rest_seconds": 180,
        "warmup_sets": 2,
        "tempo": None,
        "notes": None,
        "suggested_substitutes": [],
    }
    exercise.update(overrides.pop("exercise", {}))
    day = {
        "day_name": "Upper 1",
        "day_order": 1,
        "week_order": 1,
        "warmup_exercises": [],
        "exercises": [exercise],
        "cardio": None,
    }
    program = {
        "program_name": "Upper Block",
        "split_type": "Upper/Lower",
        "weekly_frequency": 1,
        "instructions": "",
        "days": [day],
        "weeks": [],
    }
    program.update(overrides)
    return program


def _body(name="My Template", description="Reusable split", program=None):
    return {
        "name": name,
        "description": description,
        "program": program if program is not None else _program(),
    }


def _templates_path() -> str:
    return "/coach/program-templates"


# --------------------------------------------------------------------------
# CRUD + archive lifecycle
# --------------------------------------------------------------------------


def test_template_crud_archive_and_duplicate_lifecycle(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")

    created = client.post(_templates_path(), headers=coach, json=_body())
    assert created.status_code == 201, created.text
    template = created.json()
    template_id = template["template_id"]
    assert template["name"] == "My Template"
    assert template["description"] == "Reusable split"
    assert template["archived_at"] is None
    assert template["program"]["program_name"] == "Upper Block"
    # Weeks are normalized and days flattened to the same shape a draft uses.
    assert template["program"]["weeks"][0]["week_order"] == 1
    stored_exercise = template["program"]["weeks"][0]["days"][0]["exercises"][0]
    assert stored_exercise["exercise_id"] == "sq"
    assert stored_exercise["target_rir"] == 2.0
    assert template["program"]["days"][0]["exercises"][0]["exercise_id"] == "sq"

    listed = client.get(_templates_path(), headers=coach)
    assert listed.status_code == 200, listed.text
    assert [item["template_id"] for item in listed.json()["templates"]] == [template_id]

    read = client.get(f"{_templates_path()}/{template_id}", headers=coach)
    assert read.status_code == 200, read.text
    assert read.json()["name"] == "My Template"

    updated_program = _program(exercise={"target_sets": 5})
    updated = client.put(
        f"{_templates_path()}/{template_id}",
        headers=coach,
        json=_body(name="Renamed", description=None, program=updated_program),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["description"] is None
    assert updated.json()["program"]["days"][0]["exercises"][0]["target_sets"] == 5

    duplicated = client.post(
        f"{_templates_path()}/{template_id}/duplicate",
        headers=coach,
        json={"name": "Copied"},
    )
    assert duplicated.status_code == 201, duplicated.text
    copy_id = duplicated.json()["template_id"]
    assert copy_id != template_id
    assert duplicated.json()["name"] == "Copied"
    assert duplicated.json()["program"]["days"][0]["exercises"][0]["target_sets"] == 5

    # Editing the duplicate leaves the original untouched.
    edited_copy = client.put(
        f"{_templates_path()}/{copy_id}",
        headers=coach,
        json=_body(name="Copied", program=_program(exercise={"target_sets": 9})),
    )
    assert edited_copy.status_code == 200, edited_copy.text
    original_after = client.get(f"{_templates_path()}/{template_id}", headers=coach).json()
    assert original_after["program"]["days"][0]["exercises"][0]["target_sets"] == 5

    archived = client.post(f"{_templates_path()}/{template_id}/archive", headers=coach)
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None

    active = client.get(_templates_path(), headers=coach).json()["templates"]
    assert [item["template_id"] for item in active] == [copy_id]
    archived_list = client.get(f"{_templates_path()}?archived=true", headers=coach).json()["templates"]
    assert [item["template_id"] for item in archived_list] == [template_id]

    unarchived = client.post(f"{_templates_path()}/{template_id}/unarchive", headers=coach)
    assert unarchived.status_code == 200, unarchived.text
    assert unarchived.json()["archived_at"] is None
    assert len(client.get(_templates_path(), headers=coach).json()["templates"]) == 2


def test_template_requires_the_live_coach_capability(api):
    client, db, _ = api
    player = _register(client, "plain-player")
    headers = _authed(player["access_token"])
    assert client.get(_templates_path(), headers=headers).status_code == 403


# --------------------------------------------------------------------------
# Ownership
# --------------------------------------------------------------------------


def test_templates_are_owner_scoped_and_others_get_404(api):
    client, db, _ = api
    coach_a = _make_coach(client, db, "coach-a")
    coach_b = _make_coach(client, db, "coach-b")

    created = client.post(_templates_path(), headers=coach_a, json=_body(name="A only"))
    template_id = created.json()["template_id"]

    assert client.get(_templates_path(), headers=coach_b).json()["templates"] == []
    for method, path, kwargs in [
        ("get", f"{_templates_path()}/{template_id}", {}),
        ("put", f"{_templates_path()}/{template_id}", {"json": _body(name="hijack")}),
        ("post", f"{_templates_path()}/{template_id}/archive", {}),
        ("post", f"{_templates_path()}/{template_id}/unarchive", {}),
        ("post", f"{_templates_path()}/{template_id}/duplicate", {"json": {}}),
    ]:
        response = getattr(client, method)(path, headers=coach_b, **kwargs)
        assert response.status_code == 404, f"{method} {path} -> {response.status_code}"

    # The owner's template is unchanged by the failed attempts.
    assert client.get(f"{_templates_path()}/{template_id}", headers=coach_a).json()["name"] == "A only"


def test_template_rejects_another_coachs_exercise(api):
    client, db, _ = api
    coach_a = _make_coach(client, db, "coach-a")
    _make_coach(client, db, "coach-b")
    coach_b_id = db.get_active_account_by_username("coach-b")["account_id"]
    foreign = db.create_coach_exercise(
        coach_b_id, CoachExerciseCreate(name="Coach B Movement", equipment="Barbell")
    )

    rejected = client.post(
        _templates_path(),
        headers=coach_a,
        json=_body(program=_program(exercise_id=foreign["id"])),
    )
    assert rejected.status_code == 400, rejected.text
    codes = {issue["code"] for issue in rejected.json()["detail"]["errors"]}
    assert "unknown_exercise" in codes

    # The same coach's own exercise is accepted.
    coach_a_id = db.get_active_account_by_username("coach-a")["account_id"]
    owned = db.create_coach_exercise(
        coach_a_id, CoachExerciseCreate(name="Coach A Movement", equipment="Barbell")
    )
    accepted = client.post(
        _templates_path(),
        headers=coach_a,
        json=_body(program=_program(exercise_id=owned["id"])),
    )
    assert accepted.status_code == 201, accepted.text


def test_update_ownership_precedes_program_validation(api):
    client, db, _ = api
    coach_a = _make_coach(client, db, "coach-a")
    coach_b = _make_coach(client, db, "coach-b")
    template_id = client.post(
        _templates_path(), headers=coach_a, json=_body(name="A only")
    ).json()["template_id"]
    invalid_program = _program(exercise_id="ghost")

    # A shape-valid but semantically invalid program still yields the uniform
    # 404 for a foreign or unknown id, never a 400 that reveals the template.
    foreign = client.put(
        f"{_templates_path()}/{template_id}",
        headers=coach_b,
        json=_body(program=invalid_program),
    )
    assert foreign.status_code == 404, foreign.text
    unknown = client.put(
        f"{_templates_path()}/tmpl:missing",
        headers=coach_a,
        json=_body(program=invalid_program),
    )
    assert unknown.status_code == 404, unknown.text

    # The owner still gets the semantic 400 for the same invalid program.
    owner = client.put(
        f"{_templates_path()}/{template_id}",
        headers=coach_a,
        json=_body(program=invalid_program),
    )
    assert owner.status_code == 400, owner.text
    assert {issue["code"] for issue in owner.json()["detail"]["errors"]} == {
        "unknown_exercise"
    }


def test_template_name_boundaries(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")

    # A whitespace-only name is rejected before anything is stored.
    blank = client.post(_templates_path(), headers=coach, json=_body(name="   "))
    assert blank.status_code == 422, blank.text
    assert client.get(_templates_path(), headers=coach).json()["templates"] == []

    # A name of exactly the bound after trimming is accepted and stored trimmed.
    max_name = "x" * 120
    accepted = client.post(
        _templates_path(), headers=coach, json=_body(name=f"  {max_name}  ")
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["name"] == max_name
    template_id = accepted.json()["template_id"]

    # The stored name can be saved again unchanged.
    resaved = client.put(
        f"{_templates_path()}/{template_id}",
        headers=coach,
        json=_body(name=max_name),
    )
    assert resaved.status_code == 200, resaved.text

    # One character past the bound is rejected on create and on duplicate.
    assert (
        client.post(
            _templates_path(), headers=coach, json=_body(name="x" * 121)
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{_templates_path()}/{template_id}/duplicate",
            headers=coach,
            json={"name": "x" * 121},
        ).status_code
        == 422
    )

    # The derived duplicate name of a max-length template stays within the bound
    # and can itself be saved, while the original label is untouched.
    duplicate = client.post(
        f"{_templates_path()}/{template_id}/duplicate", headers=coach, json={}
    )
    assert duplicate.status_code == 201, duplicate.text
    copy = duplicate.json()
    assert copy["template_id"] != template_id
    assert copy["name"].endswith("(copy)")
    assert len(copy["name"]) <= 120
    resaved_copy = client.put(
        f"{_templates_path()}/{copy['template_id']}",
        headers=coach,
        json=_body(name=copy["name"]),
    )
    assert resaved_copy.status_code == 200, resaved_copy.text
    assert (
        client.get(f"{_templates_path()}/{template_id}", headers=coach).json()["name"]
        == max_name
    )


# --------------------------------------------------------------------------
# Validation matches publish validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("program_factory", "expected_code"),
    [
        (lambda: _program(exercise_id="ghost"), "unknown_exercise"),
        (lambda: _program(exercise={"target_rir": 9.0}), "invalid_rir"),
        (lambda: _program(exercise={"target_reps_min": 12, "target_reps_max": 5}), "invalid_reps"),
        (lambda: _program(exercise={"target_sets": 0}), "invalid_sets"),
        (lambda: _program(days=[{"day_name": "Empty", "day_order": 1, "exercises": []}]), "empty_day"),
        (lambda: {"days": []}, "no_days"),
    ],
)
def test_template_validation_matches_publish_validation(api, program_factory, expected_code):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    rejected = client.post(
        _templates_path(),
        headers=coach,
        json=_body(program=program_factory()),
    )
    assert rejected.status_code == 400, rejected.text
    codes = {issue["code"] for issue in rejected.json()["detail"]["errors"]}
    assert expected_code in codes, rejected.text
    # A rejected template is never stored.
    assert client.get(_templates_path(), headers=coach).json()["templates"] == []


# --------------------------------------------------------------------------
# No player data, no ledger mount
# --------------------------------------------------------------------------


def test_creating_a_template_mounts_no_player_ledger(api):
    client, db, ledgers_dir = api
    coach = _make_coach(client, db, "coach")
    before = {path.name for path in Path(ledgers_dir).glob("*.db")}

    created = client.post(_templates_path(), headers=coach, json=_body())
    assert created.status_code == 201, created.text

    after = {path.name for path in Path(ledgers_dir).glob("*.db")}
    assert after == before
    row = db.catalog_conn.execute(
        "SELECT coach_account_id, program_json FROM program_templates WHERE template_id = ?",
        (created.json()["template_id"],),
    ).fetchone()
    assert row is not None
    stored = row[1]
    assert "player" not in stored.lower()
    assert "assignment" not in stored.lower()


def test_owner_token_subject_matches_the_stored_owner(api):
    client, db, _ = api
    coach = _make_coach(client, db, "coach")
    created = client.post(_templates_path(), headers=coach, json=_body())
    owner_id = db.get_active_account_by_username("coach")["account_id"]
    subject = pyjwt.decode(coach["Authorization"].split()[1], TEST_JWT_SECRET, algorithms=["HS256"])["sub"]
    assert subject == owner_id
    assert (
        db.catalog_conn.execute(
            "SELECT coach_account_id FROM program_templates WHERE template_id = ?",
            (created.json()["template_id"],),
        ).fetchone()[0]
        == owner_id
    )
