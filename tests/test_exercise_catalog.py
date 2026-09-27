"""Read-only exercise catalog detail contract tests (ticket #53).

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
            yield client, db
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
