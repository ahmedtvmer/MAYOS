"""Request-identity isolation: ContextVar binding, thread separation, and JWT auth."""

import asyncio
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials

from database.database_manager import DatabaseManager
from service._base import bind_user, current_trainee
from svc.auth import create_access_token, decode_access_token
from svc.dependencies import bind_request, get_current_trainee


@pytest.fixture
def temp_db_env(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(DatabaseManager, "_instance", None)
    monkeypatch.setattr(DatabaseManager, "_local", threading.local())
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute("CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT);")
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.commit()
    cat_conn.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        users_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        active_user="alice",
    )
    try:
        current_trainee.set(None)
        yield db
    finally:
        current_trainee.set(None)
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def test_bind_user_sets_contextvar(temp_db_env):
    assert bind_user(temp_db_env, "Alice!") == "alice"
    assert current_trainee.get() == "alice"


def test_concurrent_threads_do_not_leak_identity(temp_db_env):
    db = temp_db_env
    db.switch_user("alice")
    db.upsert_user_profile({"current_goal": "alice-goal"})
    db.switch_user("bob")
    db.upsert_user_profile({"current_goal": "bob-goal"})
    seen: dict[str, str] = {}
    errors: list[Exception] = []

    def run_as(user: str):
        try:
            bind_request(db, user)
            profile = db.get_user_profile()
            seen[user] = (profile or {}).get("current_goal", "")
            assert current_trainee.get() == user
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run_as, args=(user,)) for user in ("alice", "bob")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert seen == {"alice": "alice-goal", "bob": "bob-goal"}


def test_jwt_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    token = create_access_token("alice")
    assert decode_access_token(token) == "alice"


def test_jwt_rejects_tampered_and_expired(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    token = create_access_token("alice")
    with pytest.raises(pyjwt.PyJWTError):
        decode_access_token(token + "x")
    now = datetime.now(UTC)
    expired = pyjwt.encode(
        {"sub": "alice", "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
        "test-secret",
        algorithm="HS256",
    )
    with pytest.raises(pyjwt.PyJWTError):
        decode_access_token(expired)


def test_jwt_requires_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_access_token("alice")


def _creds(token: str | None):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token or "")


def test_dependency_accepts_valid_bearer(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    token = create_access_token("alice")
    assert asyncio.run(get_current_trainee(_creds(token))) == "alice"


def test_dependency_rejects_missing_or_bad_token(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_trainee(None))
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_trainee(_creds("bogus")))
    assert exc.value.status_code == 401
