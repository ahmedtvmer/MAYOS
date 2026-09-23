"""Password change, recovery-email, and forgot/reset flows against real JWTs."""

import os
import sqlite3
import threading
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
    monkeypatch.setenv("RESET_TOKEN_TTL_MINUTES", "30")
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
        catalog_path=catalog_path, users_dir=tmp_path / "users", backups_dir=tmp_path / "backups", active_user="bootstrap"
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    from svc.rate_limit import limiter as _limiter

    _limiter._storage.reset()
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def _register(api_client, trainee_id, password="correct-horse-1"):
    resp = api_client.post("/auth/register", json={"trainee_id": trainee_id, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def test_change_password_revokes_all_sessions(api):
    client, _ = api
    _register(client, "alice")
    token_a = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()["access_token"]
    token_b = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()["access_token"]
    assert client.get("/dashboard/exercises", headers=_authed(token_a)).status_code == 200

    changed = client.post(
        "/auth/change-password",
        json={"current_password": "correct-horse-1", "new_password": "brand-new-horse-2"},
        headers=_authed(token_a),
    )
    assert changed.status_code == 200, changed.text

    # Both sessions are dead.
    assert client.get("/dashboard/exercises", headers=_authed(token_a)).status_code == 401
    assert client.get("/dashboard/exercises", headers=_authed(token_b)).status_code == 401
    # Old password is dead; new password works.
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 401
    fresh = client.post("/auth/login", json={"trainee_id": "alice", "password": "brand-new-horse-2"})
    assert fresh.status_code == 200
    assert client.get("/dashboard/exercises", headers=_authed(fresh.json()["access_token"])).status_code == 200


def test_change_password_failures_are_400_and_keep_session(api):
    client, _ = api
    token = _register(client, "alice")
    headers = _authed(token)

    wrong = client.post(
        "/auth/change-password",
        json={"current_password": "not-the-password", "new_password": "brand-new-horse-2"},
        headers=headers,
    )
    assert wrong.status_code == 400
    weak = client.post(
        "/auth/change-password",
        json={"current_password": "correct-horse-1", "new_password": "short"},
        headers=headers,
    )
    assert weak.status_code in {400, 422}
    same = client.post(
        "/auth/change-password",
        json={"current_password": "correct-horse-1", "new_password": "correct-horse-1"},
        headers=headers,
    )
    assert same.status_code == 400
    # Failed attempts must not revoke the live session (and must not look like expiry).
    assert client.get("/dashboard/exercises", headers=headers).status_code == 200


def test_change_password_requires_auth(api):
    client, _ = api
    _register(client, "alice")
    assert client.post("/auth/change-password", json={"current_password": "x", "new_password": "y" * 12}).status_code in {
        401,
        403,
    }


def test_recovery_email_set_get_and_conflict(api):
    client, _ = api
    alice = _register(client, "alice")
    _register(client, "bob")
    assert client.get("/auth/email", headers=_authed(alice)).json() == {"email": None}
    saved = client.post("/auth/email", json={"email": "Alice@Example.com"}, headers=_authed(alice))
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"email": "alice@example.com"}
    assert client.get("/auth/email", headers=_authed(alice)).json() == {"email": "alice@example.com"}
    assert client.post("/auth/email", json={"email": "not-an-email"}, headers=_authed(alice)).status_code == 400
    clash = client.post("/auth/email", json={"email": "alice@example.com"}, headers=_authed(_register(client, "carol")))
    assert clash.status_code == 400


def test_forgot_password_is_generic_and_reset_roundtrip(api):
    from service import password_reset as reset_service

    client, db = api
    _register(client, "alice")
    alice_token = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()["access_token"]
    client.post("/auth/email", json={"email": "alice@example.com"}, headers=_authed(alice_token))

    known = client.post("/auth/forgot-password", json={"email": "alice@example.com"})
    unknown = client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert "reset link" in known.json()["message"]

    # Issue a deterministic token through the service (mailer captured, nothing sent).
    sent = []
    reset_service.request_password_reset(
        db, "alice@example.com", mailer=lambda to, link: sent.append((to, link)) or True, token_factory=lambda: "fixed-reset-token-1234567890"
    )
    assert sent and sent[0][0] == "alice@example.com" and "fixed-reset-token-1234567890" in sent[0][1]

    done = client.post("/auth/reset-password", json={"token": "fixed-reset-token-1234567890", "new_password": "reset-horse-33"})
    assert done.status_code == 200, done.text
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "reset-horse-33"}).status_code == 200
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 401


def test_reset_token_single_use_expiry_and_generic_errors(api):
    from service import password_reset as reset_service

    client, db = api
    _register(client, "alice")
    alice_token = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()["access_token"]
    client.post("/auth/email", json={"email": "alice@example.com"}, headers=_authed(alice_token))

    reset_service.request_password_reset(db, "alice@example.com", mailer=lambda to, link: True, token_factory=lambda: "one-time-token-abcdef1234")
    assert client.post("/auth/reset-password", json={"token": "one-time-token-abcdef1234", "new_password": "first-reset-11"}).status_code == 200
    reuse = client.post("/auth/reset-password", json={"token": "one-time-token-abcdef1234", "new_password": "second-reset-22"})
    assert reuse.status_code == 400
    assert reuse.json()["detail"] == reset_service.GENERIC_TOKEN_ERROR

    garbage = client.post("/auth/reset-password", json={"token": "no-such-token-zzzzzzzzzz", "new_password": "whatever-horse-1"})
    assert garbage.status_code == 400
    assert garbage.json() == reuse.json()

    # Expired token: backdate the stored expiry, then redeem. Tokens are keyed by account id.
    reset_service.request_password_reset(db, "alice@example.com", mailer=lambda to, link: True, token_factory=lambda: "stale-token-abcdef1234")
    account_id = db.get_active_account_by_username("alice")["account_id"]
    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE password_reset_tokens SET expires_at = ? WHERE trainee_id = ?",
            ("2000-01-01T00:00:00+00:00", account_id),
        )
        db.catalog_conn.commit()
    from svc.rate_limit import limiter

    limiter._storage.reset()
    stale = client.post("/auth/reset-password", json={"token": "stale-token-abcdef1234", "new_password": "whatever-horse-2"})
    assert stale.status_code == 400
    assert stale.json() == reuse.json()


def test_reset_weak_password_does_not_consume_token(api):
    from service import password_reset as reset_service

    client, db = api
    _register(client, "alice")
    login_token = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()["access_token"]
    client.post("/auth/email", json={"email": "alice@example.com"}, headers=_authed(login_token))
    reset_service.request_password_reset(db, "alice@example.com", mailer=lambda to, link: True, token_factory=lambda: "patient-token-abcdef1234")

    weak = client.post("/auth/reset-password", json={"token": "patient-token-abcdef1234", "new_password": "short"})
    assert weak.status_code in {400, 422}
    strong = client.post("/auth/reset-password", json={"token": "patient-token-abcdef1234", "new_password": "strong-horse-44"})
    assert strong.status_code == 200, strong.text


def test_pre_version_tokens_work_until_password_change(api):
    import jwt as pyjwt

    client, _ = api
    fresh_token = _register(client, "alice")
    account_id = pyjwt.decode(fresh_token, TEST_JWT_SECRET, algorithms=["HS256"])["sub"]
    # Hand-craft a legacy token without the "tv" claim, for the immutable subject.
    legacy = pyjwt.encode({"sub": account_id, "jti": "legacy-jti-1"}, TEST_JWT_SECRET, algorithm="HS256")
    assert client.get("/dashboard/exercises", headers=_authed(legacy)).status_code == 200
    client.post(
        "/auth/change-password",
        json={"current_password": "correct-horse-1", "new_password": "rotated-horse-55"},
        headers=_authed(fresh_token),
    )
    assert client.get("/dashboard/exercises", headers=_authed(legacy)).status_code == 401


def test_admin_cli_resets_password_and_revokes_sessions(tmp_path: Path):
    """End-to-end CLI test that never touches the in-process DB singleton."""
    import sqlite3
    import subprocess
    import sys

    import bcrypt

    users_dir = tmp_path / "users"
    backups_dir = tmp_path / "backups"
    users_dir.mkdir(parents=True)
    backups_dir.mkdir(parents=True)
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute("CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT);")
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.commit()
    cat_conn.close()

    # Seed a v3 ledger for "erin" with raw SQL (no DatabaseManager import state).
    ledger = users_dir / "erin.db"
    conn = sqlite3.connect(ledger)
    conn.execute(
        "CREATE TABLE auth_credentials (id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),"
        " password_hash TEXT NOT NULL, token_version INTEGER NOT NULL DEFAULT 1,"
        " updated_at TEXT NOT NULL)"
    )
    old_hash = bcrypt.hashpw(b"original-horse-1", bcrypt.gensalt()).decode()
    conn.execute("INSERT INTO auth_credentials VALUES (1, ?, 1, '2026-01-01T00:00:00+00:00')", (old_hash,))
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()

    script = Path(__file__).resolve().parent.parent / "scripts" / "reset_password.py"
    env = dict(os.environ)
    env["SKIP_LLM_LOAD"] = "true"
    proc = subprocess.run(
        [sys.executable, str(script), "erin", "--password", "admin-set-horse-9", "--catalog", str(catalog_path), "--users-dir", str(users_dir), "--backups-dir", str(backups_dir)],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr

    conn = sqlite3.connect(ledger)
    try:
        row = conn.execute("SELECT password_hash, token_version FROM auth_credentials WHERE id = 1").fetchone()
    finally:
        conn.close()
    assert row is not None and row[0] != old_hash and row[0].startswith("$2")
    assert bcrypt.checkpw(b"admin-set-horse-9", row[0].encode())
    assert row[1] == 2


def test_admin_cli_revokes_enrolled_account_sessions(api):
    """CLI reset of an enrolled account must revoke its live registry API token."""
    import jwt as pyjwt
    import subprocess
    import sys

    client, db = api
    token = _register(client, "alice")
    account_id = pyjwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])["sub"]
    assert client.get("/dashboard/exercises", headers=_authed(token)).status_code == 200

    script = Path(__file__).resolve().parent.parent / "scripts" / "reset_password.py"
    env = dict(os.environ)
    env["SKIP_LLM_LOAD"] = "true"
    proc = subprocess.run(
        [
            sys.executable, str(script), "alice",
            "--password", "admin-set-horse-9",
            "--catalog", str(db.catalog_path),
            "--users-dir", str(db.users_dir),
            "--backups-dir", str(db.backups_dir),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "all sessions revoked" in proc.stdout.lower()

    # The enrolled account's registry epoch advanced, so the old token is dead.
    assert db.get_account(account_id)["session_epoch"] == 2
    assert client.get("/dashboard/exercises", headers=_authed(token)).status_code == 401

    # The new password works and reissues a token for the same immutable account.
    relogin = client.post("/auth/login", json={"trainee_id": "alice", "password": "admin-set-horse-9"})
    assert relogin.status_code == 200, relogin.text
    assert pyjwt.decode(relogin.json()["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])["sub"] == account_id


def test_fresh_catalog_boot_creates_account_tables(tmp_path: Path, monkeypatch):
    """A brand-new DatabaseManager() boot must provision recovery tables up front."""
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute("CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT);")
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.commit()
    cat_conn.close()

    # monkeypatch restores the singleton/thread-local after this test, so
    # module-level DatabaseManager() consumers in other test files stay intact.
    monkeypatch.setattr(DatabaseManager, "_instance", None)
    monkeypatch.setattr(DatabaseManager, "_local", threading.local())
    db = DatabaseManager(
        catalog_path=catalog_path, users_dir=tmp_path / "users", backups_dir=tmp_path / "backups", active_user="bootstrap"
    )
    try:
        tables = {
            row[0] for row in db.catalog_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"trainee_emails", "password_reset_tokens", "accounts"} <= tables
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()
