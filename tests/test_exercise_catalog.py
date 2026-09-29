"""Read-only exercise library detail contract tests (ticket #53).

The exercise-detail screen is backed by `GET /workouts/exercises/{exercise_id}`:
an authenticated, read-only endpoint that returns the real catalog fields
(name, category == body_part, equipment, primary + secondary muscles,
instructions, and the stored media paths) without bundling or serving media.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
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
        "INSERT INTO exercises (id, name, body_part, target_muscle, equipment, instructions, image_path, gif_path)"
        " VALUES ('bp', 'Bench Press', 'Chest', 'Chest', 'barbell',"
        " 'Lie on a bench and press the bar up.', 'images/bp.jpg', 'videos/bp.gif');"
    )
    cat_conn.execute(
        "INSERT INTO exercise_secondary_muscles (exercise_id, muscle) VALUES ('bp', 'triceps'), ('bp', 'shoulders');"
    )
    # More muscles so the Replace search's pre-filter (#162) can be exercised.
    cat_conn.execute(
        "INSERT INTO exercises (id, name, body_part, target_muscle, equipment, instructions, image_path, gif_path)"
        " VALUES ('ib', 'Incline Bench Press', 'Chest', 'Chest', 'barbell', '', 'images/ib.jpg', NULL),"
        " ('sq', 'Back Squat', 'Upper Legs', 'Quads', 'barbell', '', 'images/sq.jpg', NULL),"
        " ('lp', 'Leg Press', 'Upper Legs', 'Quads', 'machine', '', 'images/lp.jpg', NULL),"
        " ('op', 'Overhead Press', 'Shoulders', 'Shoulders', 'barbell', '', 'images/op.jpg', NULL);"
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


def test_exercise_detail_returns_real_catalog_fields(api):
    client, _ = api
    token = _register(client, "player")["access_token"]
    resp = client.get("/workouts/exercises/bp", headers=_authed(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "id": "bp",
        "name": "Bench Press",
        "category": "Chest",
        "body_part": "Chest",
        "equipment": "barbell",
        "primary_muscles": ["Chest"],
        "secondary_muscles": ["shoulders", "triceps"],
        "instructions": "Lie on a bench and press the bar up.",
        "image_path": "images/bp.jpg",
        "gif_path": "videos/bp.gif",
    }


def test_exercise_detail_unknown_id_is_404(api):
    client, _ = api
    token = _register(client, "player2")["access_token"]
    resp = client.get("/workouts/exercises/nope", headers=_authed(token))
    assert resp.status_code == 404


def test_exercise_detail_requires_auth(api):
    client, _ = api
    resp = client.get("/workouts/exercises/bp")
    assert resp.status_code == 401


def test_catalog_search_returns_the_image_path_for_added_exercise_pictures(api):
    """`GET /workouts/exercises?query=` carries `image_path` so an exercise
    added from this search gets its card's catalog picture like a planned one
    (#53/#161): the client builds the public `/media` URL from it."""
    client, _ = api
    token = _register(client, "searcher")["access_token"]

    resp = client.get("/workouts/exercises", headers=_authed(token), params={"query": "bench"})
    assert resp.status_code == 200, resp.text
    matches = resp.json()["exercises"]
    assert matches, "expected the fixture's Bench Press"
    assert matches[0]["id"] == "bp"
    assert matches[0]["image_path"] == "images/bp.jpg"
    # The client's own thumbnail URL builder is fed from this field alone.
    assert matches[0]["image_path"].startswith("images/")


def test_catalog_search_by_muscle_lists_that_muscle_without_a_name_query(api):
    """`GET /workouts/exercises?target_muscle=` lists one muscle's exercises
    (#162): the logger's Replace search opens pre-filtered before the player
    types, and every row still carries the fields the client renders."""
    client, _ = api
    token = _register(client, "muscle")["access_token"]

    resp = client.get(
        "/workouts/exercises", headers=_authed(token), params={"target_muscle": "Chest"}
    )
    assert resp.status_code == 200, resp.text
    matches = resp.json()["exercises"]
    assert [m["id"] for m in matches] == ["bp", "ib"]
    assert matches[0]["target_muscle"] == "Chest"
    assert matches[0]["image_path"] == "images/bp.jpg"

    # The match is case-insensitive, like the rest of the catalog's text.
    resp = client.get(
        "/workouts/exercises", headers=_authed(token), params={"target_muscle": "quads"}
    )
    assert resp.status_code == 200, resp.text
    assert [m["id"] for m in resp.json()["exercises"]] == ["lp", "sq"]


def test_catalog_search_combines_a_name_query_with_the_muscle(api):
    """A name query stays optional and narrows within the muscle: the Replace
    search's pill keeps the catalog browsable (#162)."""
    client, _ = api
    token = _register(client, "narrow")["access_token"]

    resp = client.get(
        "/workouts/exercises",
        headers=_authed(token),
        params={"query": "press", "target_muscle": "Shoulders"},
    )
    assert resp.status_code == 200, resp.text
    assert [m["id"] for m in resp.json()["exercises"]] == ["op"]

    # The same query without a muscle still searches the whole catalog.
    resp = client.get(
        "/workouts/exercises", headers=_authed(token), params={"query": "press"}
    )
    assert resp.status_code == 200, resp.text
    assert "op" in [m["id"] for m in resp.json()["exercises"]]
    assert "bp" in [m["id"] for m in resp.json()["exercises"]]


def test_catalog_search_requires_a_query_or_a_muscle(api):
    """Neither parameter is the only refused shape: an unfiltered dump of the
    shared catalog is not what this endpoint is for."""
    client, _ = api
    token = _register(client, "empty")["access_token"]

    resp = client.get("/workouts/exercises", headers=_authed(token))
    assert resp.status_code == 400, resp.text
    resp = client.get(
        "/workouts/exercises",
        headers=_authed(token),
        params={"query": "", "target_muscle": ""},
    )
    assert resp.status_code == 400, resp.text
