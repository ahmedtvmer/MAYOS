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


def test_dependency_accepts_valid_bearer(monkeypatch, temp_db_env):
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    account_id = temp_db_env.create_account("alice")
    token = create_access_token(account_id)
    assert asyncio.run(get_current_trainee(_creds(token), temp_db_env)) == "alice"


def test_dependency_rejects_missing_or_bad_token(monkeypatch, temp_db_env):
    from fastapi import HTTPException

    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_trainee(None, temp_db_env))
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_trainee(_creds("bogus"), temp_db_env))
    assert exc.value.status_code == 401


def test_dependency_rejects_revoked_token(monkeypatch, temp_db_env):
    from fastapi import HTTPException

    from svc.auth import revoke_token

    monkeypatch.setenv("JWT_SECRET", "test-secret")
    account_id = temp_db_env.create_account("alice")
    token = create_access_token(account_id)
    assert asyncio.run(get_current_trainee(_creds(token), temp_db_env)) == "alice"
    revoke_token(temp_db_env, token)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_trainee(_creds(token), temp_db_env))
    assert exc.value.status_code == 401
    assert "revoked" in exc.value.detail


def test_revoked_tokens_prune_expired(temp_db_env):
    temp_db_env.switch_user("alice")
    temp_db_env.revoke_token("old-jti", "2000-01-01T00:00:00+00:00")
    temp_db_env.revoke_token("fresh-jti", "2999-01-01T00:00:00+00:00")
    assert temp_db_env.prune_revoked_tokens("2026-01-01T00:00:00+00:00") == 1
    assert temp_db_env.is_token_revoked("fresh-jti") is True
    assert temp_db_env.is_token_revoked("old-jti") is False
