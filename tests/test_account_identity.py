"""Immutable account identity: catalog registry, JWT subjects, and fail-closed auth."""

import asyncio
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import auth as auth_service
from service import password_reset as reset_service
from svc.app import create_app
from svc.auth import create_access_token, revoke_token
from svc.dependencies import bind_request, get_current_trainee, get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    from svc.rate_limit import limiter

    limiter._storage.reset()
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
        active_user="bootstrap",
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


def _subject(token):
    return pyjwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])["sub"]


def test_account_id_is_immutable_and_distinct_from_username(api):
    client, db, _ = api
    alice = _register(client, "alice")
    alice_id = _subject(alice["access_token"])
    assert alice["trainee_id"] == "alice"
    assert alice_id != "alice"
    assert db.get_account(alice_id)["username"] == "alice"

    bob = _register(client, "bob")
    assert _subject(bob["access_token"]) != alice_id


def test_login_reissues_token_for_same_immutable_subject(api):
    client, _, _ = api
    registered = _register(client, "alice")
    login = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"})
    assert login.status_code == 200
    assert login.json()["trainee_id"] == "alice"
    assert _subject(login.json()["access_token"]) == _subject(registered["access_token"])


def test_unknown_account_token_fails_closed_without_creating_ledger(api):
    client, _, users_dir = api
    ghost_id = uuid.uuid4().hex
    token = create_access_token(ghost_id)
    before = {p.name for p in users_dir.glob("*.db")}
    assert client.get("/dashboard/exercises", headers=_authed(token)).status_code == 401
    assert {p.name for p in users_dir.glob("*.db")} == before
    assert not (users_dir / f"{ghost_id}.db").exists()


def test_old_username_subject_token_is_rejected(api):
    client, _, _ = api
    _register(client, "alice")
    legacy = pyjwt.encode({"sub": "alice", "jti": "old-style"}, TEST_JWT_SECRET, algorithm="HS256")
    assert client.get("/dashboard/exercises", headers=_authed(legacy)).status_code == 401


def test_deleted_registry_entry_fails_closed(api):
    client, db, _ = api
    registered = _register(client, "alice")
    account_id = _subject(registered["access_token"])
    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE accounts SET status = 'deleted', deleted_at = ? WHERE account_id = ?",
            (datetime.now(UTC).isoformat(), account_id),
        )
        db.catalog_conn.commit()
    assert client.get("/dashboard/exercises", headers=_authed(registered["access_token"])).status_code == 401


def test_deleted_timestamp_wins_even_when_status_stays_active(api):
    """``deleted_at`` is authoritative: an interrupted deletion that left status='active' is dead."""
    client, db, _ = api
    registered = _register(client, "alice")
    account_id = _subject(registered["access_token"])
    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE accounts SET deleted_at = ? WHERE account_id = ?",
            (datetime.now(UTC).isoformat(), account_id),
        )
        db.catalog_conn.commit()
    assert db.get_account(account_id)["status"] == "active"
    assert db.get_active_account_by_username("alice") is None
    assert client.get("/dashboard/exercises", headers=_authed(registered["access_token"])).status_code == 401


def test_account_without_player_capability_fails_closed(api):
    client, db, _ = api
    registered = _register(client, "alice")
    account_id = _subject(registered["access_token"])
    with db._catalog_lock:
        db.catalog_conn.execute("UPDATE accounts SET is_player = 0 WHERE account_id = ?", (account_id,))
        db.catalog_conn.commit()
    assert client.get("/dashboard/exercises", headers=_authed(registered["access_token"])).status_code == 401


def test_worker_bind_rechecks_the_same_account_after_revocation(api):
    client, db, _ = api
    registered = _register(client, "alice")
    token = registered["access_token"]
    verified = asyncio.run(
        get_current_trainee(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db)
    )
    old_id = _subject(token)
    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE accounts SET status = 'deleted', deleted_at = ? WHERE account_id = ?",
            (datetime.now(UTC).isoformat(), old_id),
        )
        db.catalog_conn.commit()
    assert db.create_account("alice") != old_id
    with pytest.raises(HTTPException) as exc:
        bind_request(db, verified)
    assert exc.value.status_code == 401


def test_password_change_bumps_registry_epoch(api):
    client, db, _ = api
    registered = _register(client, "alice")
    account_id = _subject(registered["access_token"])
    assert db.get_account(account_id)["session_epoch"] == 1

    changed = client.post(
        "/auth/change-password",
        json={"current_password": "correct-horse-1", "new_password": "brand-new-horse-2"},
        headers=_authed(registered["access_token"]),
    )
    assert changed.status_code == 200
    assert db.get_account(account_id)["session_epoch"] == 2
    assert client.get("/dashboard/exercises", headers=_authed(registered["access_token"])).status_code == 401


def test_password_reset_bumps_registry_epoch(api):
    client, db, _ = api
    registered = _register(client, "alice")
    account_id = _subject(registered["access_token"])
    client.post("/auth/email", json={"email": "alice@example.com"}, headers=_authed(registered["access_token"]))
    reset_service.request_password_reset(
        db, "alice@example.com", mailer=lambda to, link: True, token_factory=lambda: "reset-token-abcdef1234"
    )

    done = client.post("/auth/reset-password", json={"token": "reset-token-abcdef1234", "new_password": "reset-horse-33"})
    assert done.status_code == 200, done.text
    assert db.get_account(account_id)["session_epoch"] == 2
    assert client.get("/dashboard/exercises", headers=_authed(registered["access_token"])).status_code == 401


def test_username_can_be_reused_after_deletion(api):
    client, db, users_dir = api
    first = _register(client, "alice")
    first_id = _subject(first["access_token"])
    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE accounts SET status = 'deleted', deleted_at = ? WHERE account_id = ?",
            (datetime.now(UTC).isoformat(), first_id),
        )
        db.catalog_conn.commit()
    (users_dir / "alice.db").unlink(missing_ok=True)

    second = _register(client, "alice")
    second_id = _subject(second["access_token"])
    assert second_id != first_id
    assert db.get_account(first_id)["status"] == "deleted"
    assert db.get_account(second_id)["username"] == "alice"


def test_local_ledger_without_account_is_not_adopted(api):
    client, db, users_dir = api
    (users_dir / "ghost.db").write_bytes(b"")
    resp = client.post("/auth/register", json={"trainee_id": "ghost", "password": "correct-horse-1"})
    assert resp.status_code == 409
    assert db.get_active_account_by_username("ghost") is None


def _reset_token_count(db):
    with db._catalog_lock:
        return db.catalog_conn.execute("SELECT COUNT(*) FROM password_reset_tokens").fetchone()[0]


def test_deleted_timestamp_blocks_recovery_and_revocation(api):
    client, db, users_dir = api
    registered = _register(client, "alice")
    token = registered["access_token"]
    account_id = _subject(token)
    assert client.post("/auth/email", json={"email": "alice@example.com"}, headers=_authed(token)).status_code == 200
    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE accounts SET deleted_at = ? WHERE account_id = ?",
            (datetime.now(UTC).isoformat(), account_id),
        )
        db.catalog_conn.commit()

    # Recovery lookup must ignore the deleted-but-still-active row.
    before = _reset_token_count(db)
    assert client.post("/auth/forgot-password", json={"email": "alice@example.com"}).status_code == 202
    assert _reset_token_count(db) == before

    # Revocation must not mount or write to the dead account's ledger.
    jti = pyjwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])["jti"]
    revoke_token(db, token)
    conn = sqlite3.connect(users_dir / "alice.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM revoked_tokens WHERE jti = ?", (jti,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_deleted_account_recovery_cannot_reset_reused_username(api, monkeypatch):
    client, db, users_dir = api
    first = _register(client, "alice")
    first_id = _subject(first["access_token"])
    first_headers = _authed(first["access_token"])
    assert client.post("/auth/email", json={"email": "alice@example.com"}, headers=first_headers).status_code == 200

    reset_service.request_password_reset(
        db, "alice@example.com", mailer=lambda to, link: True, token_factory=lambda: "old-reset-token-abcdef12"
    )
    # Live recovery rows are keyed by the immutable account id, not the username.
    with db._catalog_lock:
        keyed_by_account = db.catalog_conn.execute(
            "SELECT 1 FROM password_reset_tokens WHERE trainee_id = ?", (first_id,)
        ).fetchone()
    assert keyed_by_account is not None

    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE accounts SET status = 'deleted', deleted_at = ? WHERE account_id = ?",
            (datetime.now(UTC).isoformat(), first_id),
        )
        db.catalog_conn.commit()
    (users_dir / "alice.db").unlink(missing_ok=True)

    # A fresh manager stands in for the post-deletion process: the old ledger and
    # its cached connection are gone, and the username is registered anew.
    monkeypatch.setattr(DatabaseManager, "_instance", None)
    monkeypatch.setattr(DatabaseManager, "_local", threading.local())
    fresh_db = DatabaseManager(
        catalog_path=db.catalog_path, users_dir=db.users_dir, backups_dir=db.backups_dir, active_user="bootstrap"
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: fresh_db
    try:
        with TestClient(app) as second_client:
            second = _register(second_client, "alice")
            second_id = _subject(second["access_token"])
            assert second_id != first_id
            assert fresh_db.get_active_account_by_username("alice")["account_id"] == second_id

            # The old token cannot reset the reused username's new account.
            stale = second_client.post(
                "/auth/reset-password",
                json={"token": "old-reset-token-abcdef12", "new_password": "attacker-horse-99"},
            )
            assert stale.status_code == 400
            assert stale.json()["detail"] == reset_service.GENERIC_TOKEN_ERROR

            # The old email link cannot mint a token for the new account either.
            tokens_before = _reset_token_count(fresh_db)
            forgot = second_client.post("/auth/forgot-password", json={"email": "alice@example.com"})
            assert forgot.status_code == 202
            assert _reset_token_count(fresh_db) == tokens_before

            # The new account keeps its own password; the attacker's reset password never took.
            assert second_client.post(
                "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}
            ).status_code == 200
            assert second_client.post(
                "/auth/login", json={"trainee_id": "alice", "password": "attacker-horse-99"}
            ).status_code == 401
    finally:
        if fresh_db.user_conn is not None:
            fresh_db.user_conn.close()
        fresh_db.catalog_conn.close()


def test_inactive_status_without_deletion_timestamp_is_not_active(api):
    client, db, _ = api
    registered = _register(client, "alice")
    account_id = _subject(registered["access_token"])
    with db._catalog_lock:
        db.catalog_conn.execute("UPDATE accounts SET status = 'deleted' WHERE account_id = ?", (account_id,))
        db.catalog_conn.commit()
    # Login/claim/reset resolve accounts through get_active_account_by_username.
    assert db.get_active_account_by_username("alice") is None
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 401
    assert client.get("/dashboard/exercises", headers=_authed(registered["access_token"])).status_code == 401


def test_username_uniqueness_is_atomic(api):
    _, db, _ = api
    results = []
    lock = threading.Lock()

    def worker():
        account_id = db.create_account("racer")
        with lock:
            results.append(account_id)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(1 for result in results if result is not None) == 1


def test_authenticated_route_roundtrip(api):
    client, _, _ = api
    registered = _register(client, "alice")
    headers = _authed(registered["access_token"])
    assert client.get("/dashboard/exercises", headers=headers).status_code == 200
    assert client.put("/profile", json={"current_goal": "Strength"}, headers=headers).status_code == 200
    assert client.get("/profile", headers=headers).json()["current_goal"] == "Strength"
    assert client.post("/auth/logout", headers=headers).status_code == 204
    assert client.get("/dashboard/exercises", headers=headers).status_code == 401


def test_logout_without_credentials_is_idempotent(api):
    client, _, _ = api
    assert client.post("/auth/logout").status_code == 204
    assert client.post("/auth/logout", headers={"Authorization": "Bearer "}).status_code == 204


def test_logout_with_stale_epoch_fails_closed(api):
    client, _, users_dir = api
    registered = _register(client, "alice")
    token = registered["access_token"]
    assert client.get("/dashboard/exercises", headers=_authed(token)).status_code == 200

    changed = client.post(
        "/auth/change-password",
        json={"current_password": "correct-horse-1", "new_password": "brand-new-horse-2"},
        headers=_authed(token),
    )
    assert changed.status_code == 200

    assert client.post("/auth/logout", headers=_authed(token)).status_code == 401
    # The stale token never reached the ledger write.
    jti = pyjwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])["jti"]
    conn = sqlite3.connect(users_dir / "alice.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM revoked_tokens WHERE jti = ?", (jti,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_logout_rejects_unknown_account_without_creating_ledger(api):
    client, _, users_dir = api
    token = create_access_token(uuid.uuid4().hex)
    before = {p.name for p in users_dir.glob("*.db")}
    assert client.post("/auth/logout", headers=_authed(token)).status_code == 401
    assert {p.name for p in users_dir.glob("*.db")} == before


def test_logout_rejects_deleted_account_and_missing_capability(api):
    client, db, _ = api

    deleted = _register(client, "alice")
    deleted_id = _subject(deleted["access_token"])
    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE accounts SET status = 'deleted', deleted_at = ? WHERE account_id = ?",
            (datetime.now(UTC).isoformat(), deleted_id),
        )
        db.catalog_conn.commit()
    assert client.post("/auth/logout", headers=_authed(deleted["access_token"])).status_code == 401

    coach_only = _register(client, "bob")
    coach_id = _subject(coach_only["access_token"])
    with db._catalog_lock:
        db.catalog_conn.execute("UPDATE accounts SET is_player = 0 WHERE account_id = ?", (coach_id,))
        db.catalog_conn.commit()
    assert client.post("/auth/logout", headers=_authed(coach_only["access_token"])).status_code == 401


def test_old_account_id_cannot_change_reused_username_password_or_email(api, monkeypatch):
    """A stale in-flight request carries a deleted id, not the reused username."""
    client, db, users_dir = api
    first = _register(client, "alice")
    first_id = _subject(first["access_token"])
    first_headers = _authed(first["access_token"])
    assert client.post("/auth/email", json={"email": "alice@example.com"}, headers=first_headers).status_code == 200

    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE accounts SET status = 'deleted', deleted_at = ? WHERE account_id = ?",
            (datetime.now(UTC).isoformat(), first_id),
        )
        db.catalog_conn.commit()
    (users_dir / "alice.db").unlink(missing_ok=True)

    # A fresh manager stands in for the post-deletion process: the old ledger and
    # its cached connections are gone, and the username is registered anew.
    monkeypatch.setattr(DatabaseManager, "_instance", None)
    monkeypatch.setattr(DatabaseManager, "_local", threading.local())
    fresh_db = DatabaseManager(
        catalog_path=db.catalog_path, users_dir=db.users_dir, backups_dir=db.backups_dir, active_user="bootstrap"
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: fresh_db
    try:
        with TestClient(app) as second_client:
            second = _register(second_client, "alice")
            second_id = _subject(second["access_token"])
            assert second_id != first_id

            # The service resolves by immutable id, so the deleted account is
            # refused even though its username now names a live account.
            assert auth_service.change_password(fresh_db, first_id, "correct-horse-1", "attacker-horse-99")["ok"] is False
            assert reset_service.set_recovery_email(fresh_db, first_id, "attacker@example.com")["ok"] is False

            # The reused account keeps its own password and has no recovery email.
            assert second_client.post(
                "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}
            ).status_code == 200
            assert second_client.post(
                "/auth/login", json={"trainee_id": "alice", "password": "attacker-horse-99"}
            ).status_code == 401
            assert second_client.get("/auth/email", headers=_authed(second["access_token"])).json() == {"email": None}
    finally:
        if fresh_db.user_conn is not None:
            fresh_db.user_conn.close()
        fresh_db.catalog_conn.close()
