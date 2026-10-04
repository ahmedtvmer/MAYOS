"""Password change, recovery-email, and forgot/reset flows against real JWTs."""

import os
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import email_sender
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
GENERIC_VERIFICATION_ERROR = "Invalid or expired verification code."


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("RESET_TOKEN_TTL_MINUTES", "30")
    monkeypatch.setenv("EMAIL_VERIFICATION_CODE_TTL_MINUTES", "10")
    from svc.rate_limit import limiter

    limiter._storage.reset()
    catalog_path = tmp_path / "catalog.db"
    db = DatabaseManager(
        catalog_path=catalog_path, ledgers_dir=tmp_path / "users", backups_dir=tmp_path / "backups", default_ledger_id="bootstrap"
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    from svc.rate_limit import limiter as _limiter

    _limiter._storage.reset()
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(api_client, ledger_id, password="correct-horse-1", *, display_language="en"):
    resp = api_client.post(
        "/auth/register",
        json={
            "trainee_id": ledger_id,
            "password": password,
            "display_language": display_language,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _set_recovery_email(api_client, token, email="alice@example.com"):
    saved = api_client.post("/auth/email", json={"email": email}, headers=_authed(token))
    assert saved.status_code == 200, saved.text


def _capture_verification_deliveries(monkeypatch):
    deliveries = []

    def capture(to_email, subject, body, *, delivery):
        deliveries.append((to_email, subject, body, delivery))
        return True

    monkeypatch.setattr(email_sender, "_deliver", capture)
    return deliveries


def _verification_code(delivery):
    match = re.search(r"(?<!\d)\d{6}(?!\d)", delivery[2])
    assert match is not None
    return match.group()


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
    assert client.get("/auth/email", headers=_authed(alice)).json() == {
        "email": None,
        "verified": False,
    }
    saved = client.post("/auth/email", json={"email": "Alice@Example.com"}, headers=_authed(alice))
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"email": "alice@example.com", "verified": False}
    assert client.get("/auth/email", headers=_authed(alice)).json() == {
        "email": "alice@example.com",
        "verified": False,
    }
    assert client.post("/auth/email", json={"email": "not-an-email"}, headers=_authed(alice)).status_code == 400
    clash = client.post("/auth/email", json={"email": "alice@example.com"}, headers=_authed(_register(client, "carol")))
    assert clash.status_code == 400


def test_forgot_password_is_generic_and_reset_roundtrip(api, monkeypatch, verify_recovery_email):
    from service import password_reset as reset_service

    client, db = api
    _register(client, "alice")
    alice_token = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()["access_token"]
    client.post("/auth/email", json={"email": "alice@example.com"}, headers=_authed(alice_token))
    verify_recovery_email(client, alice_token, monkeypatch)

    known = client.post("/auth/forgot-password", json={"email": "alice@example.com"})
    unknown = client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert "reset link" in known.json()["message"]

    # Issue a deterministic token through the service (mailer captured, nothing sent).
    sent = []
    reset_service.request_password_reset(
        db, "alice@example.com", mailer=lambda to, link, *, account_id=None: sent.append((to, link)) or True, token_factory=lambda: "fixed-reset-token-1234567890"
    )
    assert sent and sent[0][0] == "alice@example.com" and "fixed-reset-token-1234567890" in sent[0][1]

    done = client.post("/auth/reset-password", json={"token": "fixed-reset-token-1234567890", "new_password": "reset-horse-33"})
    assert done.status_code == 200, done.text
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "reset-horse-33"}).status_code == 200
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 401


def test_reset_token_single_use_expiry_and_generic_errors(api, monkeypatch, verify_recovery_email):
    from service import password_reset as reset_service

    client, db = api
    _register(client, "alice")
    alice_token = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()["access_token"]
    client.post("/auth/email", json={"email": "alice@example.com"}, headers=_authed(alice_token))
    verify_recovery_email(client, alice_token, monkeypatch)

    reset_service.request_password_reset(db, "alice@example.com", mailer=lambda to, link, *, account_id=None: True, token_factory=lambda: "one-time-token-abcdef1234")
    assert client.post("/auth/reset-password", json={"token": "one-time-token-abcdef1234", "new_password": "first-reset-11"}).status_code == 200
    reuse = client.post("/auth/reset-password", json={"token": "one-time-token-abcdef1234", "new_password": "second-reset-22"})
    assert reuse.status_code == 400
    assert reuse.json()["detail"] == reset_service.GENERIC_TOKEN_ERROR

    garbage = client.post("/auth/reset-password", json={"token": "no-such-token-zzzzzzzzzz", "new_password": "whatever-horse-1"})
    assert garbage.status_code == 400
    assert garbage.json() == reuse.json()

    # Expired token: backdate the stored expiry, then redeem. Tokens are keyed by account id.
    reset_service.request_password_reset(db, "alice@example.com", mailer=lambda to, link, *, account_id=None: True, token_factory=lambda: "stale-token-abcdef1234")
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


def test_reset_weak_password_does_not_consume_token(api, monkeypatch, verify_recovery_email):
    from service import password_reset as reset_service

    client, db = api
    _register(client, "alice")
    login_token = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()["access_token"]
    client.post("/auth/email", json={"email": "alice@example.com"}, headers=_authed(login_token))
    verify_recovery_email(client, login_token, monkeypatch)
    reset_service.request_password_reset(db, "alice@example.com", mailer=lambda to, link, *, account_id=None: True, token_factory=lambda: "patient-token-abcdef1234")

    weak = client.post("/auth/reset-password", json={"token": "patient-token-abcdef1234", "new_password": "short"})
    assert weak.status_code in {400, 422}
    strong = client.post("/auth/reset-password", json={"token": "patient-token-abcdef1234", "new_password": "strong-horse-44"})
    assert strong.status_code == 200, strong.text


def test_recovery_email_code_verifies_catalog_address_and_me_status(api, monkeypatch, caplog):
    client, db = api
    caplog.set_level("INFO")
    token = _register(client, "alice")
    headers = _authed(token)
    _set_recovery_email(client, token)
    account_id = db.get_active_account_by_username("alice")["account_id"]
    deliveries = _capture_verification_deliveries(monkeypatch)

    sent = client.post("/auth/email/verification-code", headers=headers)

    assert sent.status_code == 200, sent.text
    assert db.is_recovery_email_verified(account_id) is False
    code = _verification_code(deliveries[0])
    with db._catalog_lock:
        stored = db.catalog_conn.execute(
            "SELECT code_hash, address_hash, purpose FROM email_verification_codes"
        ).fetchone()
    assert stored[0] != code
    assert "alice@example.com" not in str(tuple(stored))
    assert "alice@example.com" not in caplog.text
    assert code not in caplog.text
    assert client.get("/auth/me", headers=headers).json()["recovery_email_verified"] is False

    verified = client.post("/auth/email/verify", json={"code": code}, headers=headers)

    assert verified.status_code == 200, verified.text
    assert db.is_recovery_email_verified(account_id) is True
    assert client.get("/auth/me", headers=headers).json()["recovery_email_verified"] is True


def test_recovery_code_email_uses_display_language(api, monkeypatch):
    client, _ = api
    token = _register(client, "alice", display_language="ar")
    _set_recovery_email(client, token)
    deliveries = _capture_verification_deliveries(monkeypatch)

    sent = client.post("/auth/email/verification-code", headers=_authed(token))

    assert sent.status_code == 200, sent.text
    assert deliveries[0][1] == "رمز تأكيد البريد الإلكتروني للاسترداد في MAYOS"
    assert "استخدم الرمز التالي" in deliveries[0][2]


def test_console_sender_logs_code_without_recovery_address(api, monkeypatch, caplog):
    _, db = api
    monkeypatch.delenv("SMTP_HOST", raising=False)
    caplog.set_level("INFO", logger="service.email_sender")

    delivered = email_sender.send_recovery_email_verification_code(
        "private@example.com", "654321", "en", account_id="account-alice"
    )

    assert delivered is True
    assert "654321" in caplog.text
    assert "private@example.com" not in caplog.text
    assert db.catalog_conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_wrong_recovery_code_has_generic_error(api, monkeypatch):
    from service import email_verification

    client, _ = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    _capture_verification_deliveries(monkeypatch)
    monkeypatch.setattr(email_verification.secrets, "randbelow", lambda _: 222222)
    client.post("/auth/email/verification-code", headers=_authed(token))

    wrong = client.post("/auth/email/verify", json={"code": "111111"}, headers=_authed(token))

    assert wrong.status_code == 400
    assert wrong.json() == {"detail": GENERIC_VERIFICATION_ERROR}


def test_expired_recovery_code_has_generic_error(api, monkeypatch):
    client, db = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    deliveries = _capture_verification_deliveries(monkeypatch)
    client.post("/auth/email/verification-code", headers=_authed(token))
    code = _verification_code(deliveries[0])
    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE email_verification_codes SET expires_at = ?",
            ("2000-01-01T00:00:00+00:00",),
        )
        db.catalog_conn.commit()

    expired = client.post("/auth/email/verify", json={"code": code}, headers=_authed(token))

    assert expired.status_code == 400
    assert expired.json() == {"detail": GENERIC_VERIFICATION_ERROR}


def test_reused_recovery_code_has_generic_error(api, monkeypatch):
    client, _ = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    deliveries = _capture_verification_deliveries(monkeypatch)
    client.post("/auth/email/verification-code", headers=_authed(token))
    code = _verification_code(deliveries[0])

    assert client.post("/auth/email/verify", json={"code": code}, headers=_authed(token)).status_code == 200
    reused = client.post("/auth/email/verify", json={"code": code}, headers=_authed(token))

    assert reused.status_code == 400
    assert reused.json() == {"detail": GENERIC_VERIFICATION_ERROR}


def test_resending_recovery_code_invalidates_previous_code(api, monkeypatch):
    from service import email_verification

    client, _ = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    deliveries = _capture_verification_deliveries(monkeypatch)
    codes = iter((123456, 234567))
    monkeypatch.setattr(email_verification.secrets, "randbelow", lambda _: next(codes))
    headers = _authed(token)
    assert client.post("/auth/email/verification-code", headers=headers).status_code == 200
    first_code = _verification_code(deliveries[0])
    assert client.post("/auth/email/verification-code", headers=headers).status_code == 200
    second_code = _verification_code(deliveries[1])

    invalidated = client.post("/auth/email/verify", json={"code": first_code}, headers=headers)
    accepted = client.post("/auth/email/verify", json={"code": second_code}, headers=headers)

    assert invalidated.status_code == 400
    assert invalidated.json() == {"detail": GENERIC_VERIFICATION_ERROR}
    assert accepted.status_code == 200


def test_stale_recovery_code_send_does_not_invalidate_current_address_code(api, monkeypatch):
    from service import email_verification, password_reset

    client, db = api
    token = _register(client, "alice")
    headers = _authed(token)
    _set_recovery_email(client, token, "old@example.com")
    deliveries = _capture_verification_deliveries(monkeypatch)
    codes = iter((123456, 234567, 345678))
    monkeypatch.setattr(email_verification.secrets, "randbelow", lambda _: next(codes))
    account_id = db.get_active_account_by_username("alice")["account_id"]

    assert client.post("/auth/email/verification-code", headers=headers).status_code == 200
    old_code = _verification_code(deliveries[0])
    _set_recovery_email(client, token, "new@example.com")
    assert client.post("/auth/email/verification-code", headers=headers).status_code == 200
    new_code = _verification_code(deliveries[1])

    original_get_email = db.get_account_email
    stale_read = True

    def get_stale_once(current_account_id):
        nonlocal stale_read
        if stale_read and current_account_id == account_id:
            stale_read = False
            return "old@example.com"
        return original_get_email(current_account_id)

    monkeypatch.setattr(db, "get_account_email", get_stale_once)
    stale_send = password_reset.issue_recovery_email_verification_code(db, account_id)
    monkeypatch.setattr(db, "get_account_email", original_get_email)

    assert stale_send is False
    assert len(deliveries) == 2
    assert client.post("/auth/email/verify", json={"code": old_code}, headers=headers).status_code == 400
    accepted = client.post("/auth/email/verify", json={"code": new_code}, headers=headers)
    assert accepted.status_code == 200, accepted.text


def test_recovery_code_verification_and_mark_roll_back_together_when_nested(api, monkeypatch):
    from service import password_reset

    client, db = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    deliveries = _capture_verification_deliveries(monkeypatch)
    assert client.post("/auth/email/verification-code", headers=_authed(token)).status_code == 200
    code = _verification_code(deliveries[0])
    account_id = db.get_active_account_by_username("alice")["account_id"]

    with pytest.raises(RuntimeError, match="force outer rollback"):
        with db.catalog_transaction(immediate=True):
            assert password_reset.verify_recovery_email_code(db, account_id, code) is True
            raise RuntimeError("force outer rollback")

    assert db.is_recovery_email_verified(account_id) is False
    row = db.catalog_conn.execute(
        "SELECT used_at FROM email_verification_codes WHERE account_id = ?", (account_id,)
    ).fetchone()
    assert row[0] is None


def test_five_wrong_recovery_code_attempts_persist_across_tokens_and_ips(api, monkeypatch):
    from service import email_verification

    client, db = api
    token_one = _register(client, "alice")
    _set_recovery_email(client, token_one)
    deliveries = _capture_verification_deliveries(monkeypatch)
    monkeypatch.setattr(email_verification.secrets, "randbelow", lambda _: 123456)
    assert client.post("/auth/email/verification-code", headers=_authed(token_one)).status_code == 200
    correct_code = _verification_code(deliveries[0])
    wrong = {"code": "654321"}

    for _ in range(3):
        response = client.post("/auth/email/verify", json=wrong, headers=_authed(token_one))
        assert response.status_code == 400
        assert response.json() == {"detail": GENERIC_VERIFICATION_ERROR}

    login = client.post(
        "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}
    )
    assert login.status_code == 200, login.text
    token_two = login.json()["access_token"]
    for _ in range(2):
        response = client.post("/auth/email/verify", json=wrong, headers=_authed(token_two))
        assert response.status_code == 400

    with TestClient(client.app, client=("198.51.100.44", 10044)) as alternate_ip:
        login = alternate_ip.post(
            "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}
        )
        assert login.status_code == 200, login.text
        response = alternate_ip.post(
            "/auth/email/verify",
            json={"code": correct_code},
            headers=_authed(login.json()["access_token"]),
        )

    assert response.status_code == 400
    assert response.json() == {"detail": GENERIC_VERIFICATION_ERROR}
    account_id = db.get_active_account_by_username("alice")["account_id"]
    failed_attempts, used_at = db.catalog_conn.execute(
        "SELECT failed_attempts, used_at FROM email_verification_codes WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    assert failed_attempts == 5
    assert used_at is not None


def test_recovery_code_send_limit_persists_across_logins_and_ips(api, monkeypatch):
    client, _ = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    deliveries = _capture_verification_deliveries(monkeypatch)
    tokens_and_clients = [(client, token)]

    with (
        TestClient(client.app, client=("198.51.100.51", 10051)) as first_ip,
        TestClient(client.app, client=("198.51.100.52", 10052)) as second_ip,
    ):
        for index in range(5):
            login_client = first_ip if index % 2 == 0 else second_ip
            login = login_client.post(
                "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}
            )
            assert login.status_code == 200, login.text
            tokens_and_clients.append((login_client, login.json()["access_token"]))

        results = [
            api_client.post("/auth/email/verification-code", headers=_authed(session_token))
            for api_client, session_token in tokens_and_clients
        ]

    assert [response.status_code for response in results] == [200, 200, 200, 200, 200, 400]
    assert results[-1].json() == {"detail": GENERIC_VERIFICATION_ERROR}
    assert len(deliveries) == 5


def test_malformed_recovery_code_bodies_return_generic_error_without_echo(api, monkeypatch):
    client, _ = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    headers = _authed(token)

    responses = [
        client.post("/auth/email/verify", json={"code": ["123456"]}, headers=headers),
        client.post("/auth/email/verify", json={}, headers=headers),
        client.post(
            "/auth/email/verify",
            content='{"code": ' + "9" * 5000 + "}",
            headers={**headers, "Content-Type": "application/json"},
        ),
    ]

    assert all(response.status_code == 400 for response in responses)
    assert all(response.json() == {"detail": GENERIC_VERIFICATION_ERROR} for response in responses)
    assert all("123456" not in response.text for response in responses)


def test_sending_recovery_code_is_rate_limited(api, monkeypatch):
    client, _ = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    _capture_verification_deliveries(monkeypatch)
    headers = _authed(token)

    responses = [client.post("/auth/email/verification-code", headers=headers) for _ in range(4)]

    assert [response.status_code for response in responses] == [200, 200, 200, 429]


def test_recovery_code_verification_is_rate_limited(api, monkeypatch):
    from service import email_verification

    client, _ = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    _capture_verification_deliveries(monkeypatch)
    monkeypatch.setattr(email_verification.secrets, "randbelow", lambda _: 222222)
    headers = _authed(token)
    assert client.post("/auth/email/verification-code", headers=headers).status_code == 200

    responses = [client.post("/auth/email/verify", json={"code": "111111"}, headers=headers) for _ in range(11)]

    assert [response.status_code for response in responses] == [400] * 10 + [429]
    assert all(response.json() == {"detail": GENERIC_VERIFICATION_ERROR} for response in responses[:10])


def test_catalog_upgrade_marks_existing_recovery_addresses_unverified(tmp_path: Path):
    catalog_path = tmp_path / "catalog.db"
    with sqlite3.connect(catalog_path) as old_catalog:
        old_catalog.execute(
            "CREATE TABLE trainee_emails (trainee_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, updated_at TEXT NOT NULL)"
        )
        old_catalog.execute(
            "INSERT INTO trainee_emails VALUES (?, ?, ?)",
            ("legacy-account", "legacy@example.com", "2020-01-01T00:00:00+00:00"),
        )

    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )

    assert db.is_recovery_email_verified("legacy-account") is False
    verified = db.catalog_conn.execute(
        "SELECT verified FROM trainee_emails WHERE trainee_id = ?", ("legacy-account",)
    ).fetchone()[0]
    assert verified == 0
    assert "CHECK (verified IN (0, 1))" in db.catalog_conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'trainee_emails'"
    ).fetchone()[0]
    db.catalog_conn.close()


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

    ledgers_dir = tmp_path / "users"
    backups_dir = tmp_path / "backups"
    ledgers_dir.mkdir(parents=True)
    backups_dir.mkdir(parents=True)
    catalog_path = tmp_path / "catalog.db"

    # Seed a v3 ledger for "erin" with raw SQL (no DatabaseManager import state).
    ledger = ledgers_dir / "erin.db"
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
        [sys.executable, str(script), "erin", "--password", "admin-set-horse-9", "--catalog", str(catalog_path), "--users-dir", str(ledgers_dir), "--backups-dir", str(backups_dir)],
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

    # Seed an already-expired revocation row: the CLI must prune it for an
    # enrolled account too, not only for a bare local ledger.
    ledger_path = db.ledgers_dir / "alice.db"
    seed = sqlite3.connect(ledger_path)
    seed.execute(
        "INSERT INTO revoked_tokens (jti, expires_at, revoked_at) VALUES (?, ?, ?)",
        ("expired-jti", "2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00"),
    )
    seed.commit()
    seed.close()

    script = Path(__file__).resolve().parent.parent / "scripts" / "reset_password.py"
    env = dict(os.environ)
    env["SKIP_LLM_LOAD"] = "true"
    proc = subprocess.run(
        [
            sys.executable, str(script), "alice",
            "--password", "admin-set-horse-9",
            "--catalog", str(db.catalog_path),
            "--users-dir", str(db.ledgers_dir),
            "--backups-dir", str(db.backups_dir),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "all sessions revoked" in proc.stdout.lower()

    checked = sqlite3.connect(ledger_path)
    try:
        remaining = checked.execute(
            "SELECT COUNT(*) FROM revoked_tokens WHERE jti = 'expired-jti'"
        ).fetchone()[0]
    finally:
        checked.close()
    assert remaining == 0  # prune_revoked_tokens ran for the enrolled account

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
    # monkeypatch restores the singleton/thread-local after this test, so
    # module-level DatabaseManager() consumers in other test files stay intact.
    db = DatabaseManager(
        catalog_path=catalog_path, ledgers_dir=tmp_path / "users", backups_dir=tmp_path / "backups", default_ledger_id="bootstrap"
    )
    try:
        tables = {
            row[0] for row in db.catalog_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"trainee_emails", "password_reset_tokens", "accounts"} <= tables
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()
