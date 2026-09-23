"""Fly.io trial storage contract tests.

Behavioral FastAPI tests at the agreed seam: a temporary directory stands in for
the mounted volume and a real SQLite catalog/ledger is created on it. Register
and login touch only SQLite, so no LLM or external service is involved.
"""

import os
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from svc.app import create_app


def _close_db():
    instance = DatabaseManager._instance
    if instance is None:
        return
    for attr in ("user_conn", "catalog_conn"):
        conn = getattr(instance, attr, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass


def _start_fresh_db(monkeypatch):
    """Detach the singleton for a test without touching the pre-existing one."""
    from utils import model_downloader as md

    monkeypatch.setattr(DatabaseManager, "_instance", None)
    monkeypatch.setattr(DatabaseManager, "_local", threading.local())
    md._llm_instance = None
    md._judge_llm_instance = None
    md._coach_llm_instance = None


@pytest.fixture
def clean_db(monkeypatch):
    _start_fresh_db(monkeypatch)
    yield
    _close_db()


def _prepare_env(monkeypatch, data_dir: Path):
    from svc.rate_limit import limiter

    limiter._storage.reset()
    monkeypatch.setenv("MAYOS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("MAYOS_REQUIRE_PERSISTENT_DATA", raising=False)
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-0123456789abcdef")
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.delenv("SKIP_LLM_LOAD", raising=False)


def test_missing_mount_rejects_readiness_and_writes(clean_db, monkeypatch, tmp_path):
    missing = tmp_path / "not-mounted"
    _prepare_env(monkeypatch, missing)

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503
        response = client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})

    # A valid-looking request must fail, not silently provision ephemeral state.
    assert response.status_code >= 500
    assert not missing.exists()


def test_mounted_root_persists_account_across_restart(clean_db, monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _prepare_env(monkeypatch, data_dir)

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        created = client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})
    assert created.status_code == 201
    assert (data_dir / "catalog.db").is_file()
    assert (data_dir / "users" / "alice.db").is_file()

    # Simulate an always-on Machine restart: drop the test instance and boot a
    # fresh app against the same mounted root. The account must survive.
    _close_db()
    _start_fresh_db(monkeypatch)
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        duplicate = client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"})
        login = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"})
    assert duplicate.status_code == 409
    assert login.status_code == 200


def test_readyz_flips_when_data_root_becomes_unwritable(clean_db, monkeypatch, tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root bypasses directory permissions")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _prepare_env(monkeypatch, data_dir)

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        assert client.get("/readyz").status_code == 200
        data_dir.chmod(0o500)
        try:
            response = client.get("/readyz")
        finally:
            data_dir.chmod(0o700)

    assert response.status_code == 503
    assert response.json()["details"]["storage"] is False
    assert response.json()["details"]["storage_detail"] == "data-dir-not-ready"
