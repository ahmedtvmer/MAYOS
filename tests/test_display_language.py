"""Public account Display language contract (#250)."""

from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from svc.app import create_app
from svc.dependencies import get_db


def test_password_account_language_registers_restores_and_updates(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-0123456789abcdef")
    db = DatabaseManager(
        catalog_path=tmp_path / "catalog.db",
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    app = create_app()
    app.state.test_db = db
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            created = client.post("/auth/register", json={
                "trainee_id": "arabic-player", "password": "strong-password", "display_language": "ar"
            })
            assert created.status_code == 201, created.text
            assert created.json()["display_language"] == "ar"
            headers = {"Authorization": f"Bearer {created.json()['access_token']}"}
            assert client.get("/auth/me", headers=headers).json()["display_language"] == "ar"
            assert client.put("/auth/display-language", headers=headers, json={"display_language": "en"}).json() == {"display_language": "en"}
            assert client.get("/auth/me", headers=headers).json()["display_language"] == "en"
            invalid = client.put("/auth/display-language", headers=headers, json={"display_language": "fr"})
            assert invalid.status_code == 422
            assert client.get("/auth/me", headers=headers).json()["display_language"] == "en"
            logged_in = client.post("/auth/login", json={"trainee_id": "arabic-player", "password": "strong-password"})
            assert logged_in.status_code == 200
            assert logged_in.json()["display_language"] == "en"
            login_headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
            assert client.put("/auth/display-language", headers=login_headers,
                              json={"display_language": "fr"}).status_code == 422
            assert client.get("/auth/me", headers=login_headers).json()["display_language"] == "en"
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def test_existing_account_schema_migrates_to_english(tmp_path: Path):
    path = tmp_path / "catalog.db"
    legacy = sqlite3.connect(path)
    legacy.execute("""CREATE TABLE accounts (
        account_id TEXT PRIMARY KEY, username TEXT NOT NULL, ledger_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active', is_player INTEGER NOT NULL DEFAULT 1,
        is_coach INTEGER NOT NULL DEFAULT 0, session_epoch INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, deleted_at TEXT, last_seen_at TEXT)""")
    legacy.execute(
        "INSERT INTO accounts (account_id, username, ledger_id, created_at) VALUES (?, ?, ?, ?)",
        ("old-account", "oldplayer", "oldplayer", "2025-01-01T00:00:00+00:00"),
    )
    legacy.commit()
    legacy.close()
    db = DatabaseManager(catalog_path=path, ledgers_dir=tmp_path / "users", backups_dir=tmp_path / "backups")
    try:
        assert db.get_account("old-account")["display_language"] == "en"
    finally:
        db.catalog_conn.close()
