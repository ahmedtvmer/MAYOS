"""Password change, recovery-email, and forgot/reset flows against real JWTs."""

import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import email_sender
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
GENERIC_VERIFICATION_ERROR = "Invalid or expired verification code."
GENERIC_VERIFICATION_ERROR_BODY = {
    "detail": GENERIC_VERIFICATION_ERROR,
    "message_code": "recovery.invalid_or_expired_code.v1",
    "message_params": {},
    "message_fallback": GENERIC_VERIFICATION_ERROR,
}
RECOVERY_CODE_SEND_LIMIT_BODY = {
    "detail": GENERIC_VERIFICATION_ERROR,
    "message_code": "recovery.code_send_limit.v1",
    "message_params": {},
    "message_fallback": GENERIC_VERIFICATION_ERROR,
}


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("RESET_TOKEN_TTL_MINUTES", "30")
    monkeypatch.setenv("EMAIL_VERIFICATION_CODE_TTL_MINUTES", "10")
    monkeypatch.setenv("MYOS_CREDENTIAL_LOCK_DIR", str(tmp_path / "credential-locks"))
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


def test_change_password_invalidates_outstanding_reset_link(api, monkeypatch, verify_recovery_email):
    from service import password_reset as reset_service

    client, db = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    verify_recovery_email(client, token, monkeypatch)
    reset_links = []
    reset_service.request_password_reset(
        db,
        "alice@example.com",
        mailer=lambda to, link, display_language, *, account_id=None: reset_links.append(link) or True,
        token_factory=lambda: "old-reset-token-abcdef1234",
    )
    assert len(reset_links) == 1
    match = re.search(r"[?&]token=([^&]+)", reset_links[0])
    assert match is not None
    reset_token = match.group(1)

    changed = client.post(
        "/auth/change-password",
        json={"current_password": "correct-horse-1", "new_password": "brand-new-horse-2"},
        headers=_authed(token),
    )
    assert changed.status_code == 200, changed.text
    rejected = client.post(
        "/auth/reset-password",
        json={"token": reset_token, "new_password": "attacker-horse-99"},
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == reset_service.GENERIC_TOKEN_ERROR
    assert client.post(
        "/auth/login", json={"trainee_id": "alice", "password": "brand-new-horse-2"}
    ).status_code == 200


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
    assert saved.json() == {
        "email": "alice@example.com",
        "verified": False,
    }
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
        db, "alice@example.com", mailer=lambda to, link, display_language, *, account_id=None: sent.append((to, link)) or True, token_factory=lambda: "fixed-reset-token-1234567890"
    )
    assert sent and sent[0][0] == "alice@example.com" and "fixed-reset-token-1234567890" in sent[0][1]

    done = client.post("/auth/reset-password", json={"token": "fixed-reset-token-1234567890", "new_password": "reset-horse-33"})
    assert done.status_code == 200, done.text
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "reset-horse-33"}).status_code == 200
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 401


@pytest.mark.parametrize(
    ("account_language", "request_language", "reset_subject", "reset_body", "notice_subject"),
    [
        (
            "en",
            "ar",
            "Myos Engine password reset",
            "A password reset was requested",
            "لا يوجد حساب في MYOS يستخدم هذا البريد الإلكتروني",
        ),
        (
            "ar",
            "en",
            "إعادة تعيين كلمة مرور MYOS",
            "تم طلب إعادة تعيين كلمة المرور",
            "No MYOS account uses this email",
        ),
        (
            "ar",
            "fr",
            "إعادة تعيين كلمة مرور MYOS",
            "تم طلب إعادة تعيين كلمة المرور",
            "No MYOS account uses this email",
        ),
        (
            "en",
            None,
            "Myos Engine password reset",
            "A password reset was requested",
            "No MYOS account uses this email",
        ),
    ],
)
def test_forgot_emails_use_account_or_selected_language_and_keep_prepared_copy(
    api,
    monkeypatch,
    verify_recovery_email,
    account_language,
    request_language,
    reset_subject,
    reset_body,
    notice_subject,
):
    client, db = api
    token = _register(client, "alice", display_language=account_language)
    _set_recovery_email(client, token)
    verify_recovery_email(client, token, monkeypatch)
    account_id = db.get_active_account_by_username("alice")["account_id"]
    deliveries = []

    def capture(to_email, subject, body, *, delivery):
        deliveries.append((to_email, subject, body, delivery))
        if delivery.purpose == email_sender.PURPOSE_PASSWORD_RESET:
            changed_language = "ar" if account_language == "en" else "en"
            assert db.set_account_display_language(account_id, changed_language)
        return True

    monkeypatch.setattr(email_sender, "_deliver", capture)
    request_body = {"email": "alice@example.com"}
    if request_language is not None:
        request_body["display_language"] = request_language

    known = client.post("/auth/forgot-password", json=request_body)
    no_account_body = {"email": "nobody@example.com"}
    if request_language is not None:
        no_account_body["display_language"] = request_language
    unknown = client.post("/auth/forgot-password", json=no_account_body)

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [delivery[3].purpose for delivery in deliveries] == [
        email_sender.PURPOSE_PASSWORD_RESET,
        email_sender.PURPOSE_NO_ACCOUNT_NOTICE,
    ]
    assert deliveries[0][1] == reset_subject
    assert reset_body in deliveries[0][2]
    assert "/reset-password?token=" in deliveries[0][2]
    assert deliveries[1][1] == notice_subject
    assert "nobody@example.com" not in deliveries[1][2]
    assert "Squat" not in deliveries[0][2] + deliveries[1][2]


def test_injected_reset_mailer_receives_account_display_language(
    api, monkeypatch, verify_recovery_email
):
    from service import password_reset as reset_service

    client, db = api
    token = _register(client, "alice", display_language="ar")
    _set_recovery_email(client, token)
    verify_recovery_email(client, token, monkeypatch)
    account_id = db.get_active_account_by_username("alice")["account_id"]
    calls = []

    def capture(to_email, reset_link, display_language, *, account_id):
        calls.append((to_email, reset_link, display_language, account_id))
        return True

    reset_service.request_password_reset(
        db,
        "alice@example.com",
        mailer=capture,
        token_factory=lambda: "owner-reset-test-token-123456",
    )

    assert len(calls) == 1
    assert calls[0][0] == "alice@example.com"
    assert "/reset-password?token=owner-reset-test-token-123456" in calls[0][1]
    assert calls[0][2:] == ("ar", account_id)


def test_password_reset_clears_login_lockout(api, monkeypatch, verify_recovery_email):
    from service import password_reset as reset_service

    client, db = api
    token = _register(client, "alice")
    client.post("/auth/email", json={"email": "alice@example.com"}, headers=_authed(token))
    verify_recovery_email(client, token, monkeypatch)
    reset_service.request_password_reset(
        db,
        "alice@example.com",
        mailer=lambda *args, **kwargs: True,
        token_factory=lambda: "lockout-reset-token-123456",
    )
    monkeypatch.setenv("LOGIN_LOCKOUT_THRESHOLD", "1")
    assert client.post(
        "/auth/login", json={"trainee_id": "alice", "password": "wrong-password"}
    ).status_code == 401
    account = db.get_active_account_by_username("alice")
    assert db.catalog_conn.execute(
        "SELECT 1 FROM account_login_failures WHERE account_id = ?", (account["account_id"],)
    ).fetchone()
    reset = client.post(
        "/auth/reset-password",
        json={"token": "lockout-reset-token-123456", "new_password": "reset-horse-33"},
    )
    assert reset.status_code == 200, reset.text
    assert client.post(
        "/auth/login", json={"trainee_id": "alice", "password": "reset-horse-33"}
    ).status_code == 200


def test_login_waits_for_reset_password_write(api, monkeypatch, verify_recovery_email):
    from service import password_reset as reset_service

    client, db = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    verify_recovery_email(client, token, monkeypatch)
    reset_service.request_password_reset(
        db, "alice@example.com", mailer=lambda *args, **kwargs: True,
        token_factory=lambda: "paused-reset-token-123456",
    )
    entered_write = threading.Event()
    finish_write = threading.Event()
    ledger_type = type(db.open_ledger("alice"))
    original_set = ledger_type.set_password_hash

    def paused_write(ledger, value):
        entered_write.set()
        assert finish_write.wait(10)
        return original_set(ledger, value)

    monkeypatch.setattr(ledger_type, "set_password_hash", paused_write)
    reset_result = {}
    worker = threading.Thread(target=lambda: reset_result.update(
        reset_service.reset_password_with_token(db, "paused-reset-token-123456", "new-password-333")
    ))
    worker.start()
    assert entered_write.wait(5)
    login_results = []
    login_lock_requested = threading.Event()
    from service import auth as auth_service
    original_lock = auth_service.account_credential_lock

    @contextmanager
    def signal_login_lock(account_id, catalog_path=None):
        if threading.current_thread().name == "login-attempt":
            login_lock_requested.set()
        with original_lock(account_id, catalog_path):
            yield

    monkeypatch.setattr(auth_service, "account_credential_lock", signal_login_lock)
    login = threading.Thread(
        name="login-attempt",
        target=lambda: login_results.append(
            auth_service.login_player(db, "alice", "correct-horse-1")
        ),
    )
    login.start()
    try:
        assert login_lock_requested.wait(5)
        assert login.is_alive()
    finally:
        finish_write.set()
        worker.join(10)
        login.join(10)
    assert reset_result["ok"]
    assert login_results == [{"ok": False, "error": auth_service.INVALID_CREDENTIALS}]
    assert client.post(
        "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}
    ).status_code == 401


def test_failures_spaced_across_lockout_window_do_not_accumulate(api, monkeypatch):
    client, db = api
    _register(client, "alice")
    monkeypatch.setenv("LOGIN_LOCKOUT_THRESHOLD", "3")
    monkeypatch.setenv("LOGIN_LOCKOUT_WINDOW_SECONDS", "10")
    from service import auth as auth_service
    now = [datetime.now(UTC)]
    clock_type = type("Clock", (), {
        "now": staticmethod(lambda tz=None: now[0]),
        "fromisoformat": staticmethod(datetime.fromisoformat),
    })
    monkeypatch.setattr(auth_service, "datetime", clock_type)
    for _ in range(3):
        assert client.post("/auth/login", json={"trainee_id": "alice", "password": "wrong-password"}).status_code == 401
        now[0] += timedelta(seconds=5.1)
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 200


def test_reset_token_single_use_expiry_and_generic_errors(api, monkeypatch, verify_recovery_email):
    from service import password_reset as reset_service

    client, db = api
    _register(client, "alice")
    alice_token = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()["access_token"]
    client.post("/auth/email", json={"email": "alice@example.com"}, headers=_authed(alice_token))
    verify_recovery_email(client, alice_token, monkeypatch)

    reset_service.request_password_reset(db, "alice@example.com", mailer=lambda to, link, display_language, *, account_id=None: True, token_factory=lambda: "one-time-token-abcdef1234")
    assert client.post("/auth/reset-password", json={"token": "one-time-token-abcdef1234", "new_password": "first-reset-11"}).status_code == 200
    reuse = client.post("/auth/reset-password", json={"token": "one-time-token-abcdef1234", "new_password": "second-reset-22"})
    assert reuse.status_code == 400
    assert reuse.json() == {
        "detail": reset_service.GENERIC_TOKEN_ERROR,
        "message_code": "recovery.invalid_or_expired_token.v1",
        "message_params": {},
        "message_fallback": reset_service.GENERIC_TOKEN_ERROR,
    }

    garbage = client.post("/auth/reset-password", json={"token": "no-such-token-zzzzzzzzzz", "new_password": "whatever-horse-1"})
    assert garbage.status_code == 400
    assert garbage.json() == reuse.json()

    # Expired token: backdate the stored expiry, then redeem. Tokens are keyed by account id.
    reset_service.request_password_reset(db, "alice@example.com", mailer=lambda to, link, display_language, *, account_id=None: True, token_factory=lambda: "stale-token-abcdef1234")
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


def test_redeeming_one_reset_invalidates_other_outstanding_link(api, monkeypatch, verify_recovery_email):
    from service import password_reset as reset_service

    client, db = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    verify_recovery_email(client, token, monkeypatch)
    for reset_token in ("first-reset-token-abcdef", "second-reset-token-abcdef"):
        reset_service.request_password_reset(
            db,
            "alice@example.com",
            mailer=lambda to, link, display_language, *, account_id=None: True,
            token_factory=lambda reset_token=reset_token: reset_token,
        )

    first = client.post(
        "/auth/reset-password", json={"token": "first-reset-token-abcdef", "new_password": "first-reset-horse-1"}
    )
    second = client.post(
        "/auth/reset-password", json={"token": "second-reset-token-abcdef", "new_password": "second-reset-horse-2"}
    )
    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["detail"] == reset_service.GENERIC_TOKEN_ERROR


def test_verified_recovery_email_change_invalidates_reset_link(api, monkeypatch, verify_recovery_email):
    from service import password_reset as reset_service

    client, db = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    verify_recovery_email(client, token, monkeypatch)
    reset_service.request_password_reset(
        db,
        "alice@example.com",
        mailer=lambda to, link, display_language, *, account_id=None: True,
        token_factory=lambda: "old-email-reset-token-123456",
    )
    deliveries = _capture_verification_deliveries(monkeypatch)
    requested = client.post(
        "/auth/email/change", json={"email": "new@example.com"}, headers=_authed(token)
    )
    assert requested.status_code == 200, requested.text
    verified = client.post(
        "/auth/email/change/verify",
        json={"code": _verification_code(deliveries[-1])},
        headers=_authed(token),
    )
    assert verified.status_code == 200, verified.text
    rejected = client.post(
        "/auth/reset-password",
        json={"token": "old-email-reset-token-123456", "new_password": "attacker-horse-99"},
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == reset_service.GENERIC_TOKEN_ERROR


def test_change_password_catalog_failure_leaves_old_password_usable(api, monkeypatch):
    from service import auth as auth_service

    client, db = api
    _register(client, "alice")
    account_id = db.get_active_account_by_username("alice")["account_id"]

    def fail_epoch_update(_account_id):
        raise RuntimeError("catalog update failed")

    monkeypatch.setattr(db, "bump_account_session_epoch", fail_epoch_update)
    with pytest.raises(RuntimeError, match="catalog update failed"):
        auth_service.change_password(db, account_id, "correct-horse-1", "new-horse-password-2")

    old_password_login = client.post(
        "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}
    )
    assert old_password_login.status_code == 200


def test_change_password_ledger_failure_revokes_reset_links_but_keeps_old_password(
    api, monkeypatch, verify_recovery_email
):
    from database.ledger.handle import TrainingLedger
    from service import auth as auth_service
    from service import password_reset as reset_service

    client, db = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    verify_recovery_email(client, token, monkeypatch)
    reset_service.request_password_reset(
        db,
        "alice@example.com",
        mailer=lambda to, link, display_language, *, account_id=None: True,
        token_factory=lambda: "reset-before-ledger-error-1234",
    )
    account_id = db.get_active_account_by_username("alice")["account_id"]

    def fail_ledger_write(_ledger, _password_hash):
        raise RuntimeError("ledger write failed")

    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(TrainingLedger, "set_password_hash", fail_ledger_write)
        with pytest.raises(RuntimeError, match="ledger write failed"):
            auth_service.change_password(db, account_id, "correct-horse-1", "new-horse-password-2")

    assert client.post(
        "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}
    ).status_code == 200
    stale_link = client.post(
        "/auth/reset-password",
        json={"token": "reset-before-ledger-error-1234", "new_password": "attacker-horse-99"},
    )
    assert stale_link.status_code == 400


def test_reset_catalog_failure_keeps_old_password_and_reset_token(api, monkeypatch, verify_recovery_email):
    from service import password_reset as reset_service

    client, db = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    verify_recovery_email(client, token, monkeypatch)
    reset_service.request_password_reset(
        db,
        "alice@example.com",
        mailer=lambda to, link, display_language, *, account_id=None: True,
        token_factory=lambda: "reset-catalog-failure-token-1234",
    )

    def fail_epoch_update(_account_id):
        raise RuntimeError("catalog update failed")

    monkeypatch.setattr(db, "bump_account_session_epoch", fail_epoch_update)
    with pytest.raises(RuntimeError, match="catalog update failed"):
        reset_service.reset_password_with_token(
            db, "reset-catalog-failure-token-1234", "new-reset-password-22"
        )

    assert client.post(
        "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}
    ).status_code == 200


def test_reset_ledger_failure_consumes_links_but_keeps_old_password(api, monkeypatch, verify_recovery_email):
    from database.ledger.handle import TrainingLedger
    from service import password_reset as reset_service

    client, db = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    verify_recovery_email(client, token, monkeypatch)
    reset_service.request_password_reset(
        db,
        "alice@example.com",
        mailer=lambda to, link, display_language, *, account_id=None: True,
        token_factory=lambda: "reset-ledger-failure-token-1234",
    )

    def fail_ledger_write(_ledger, _password_hash):
        raise RuntimeError("ledger write failed")

    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(TrainingLedger, "set_password_hash", fail_ledger_write)
        with pytest.raises(RuntimeError, match="ledger write failed"):
            reset_service.reset_password_with_token(
                db, "reset-ledger-failure-token-1234", "new-reset-password-22"
            )

    assert client.post(
        "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}
    ).status_code == 200
    stale_link = client.post(
        "/auth/reset-password",
        json={"token": "reset-ledger-failure-token-1234", "new_password": "attacker-horse-99"},
    )
    assert stale_link.status_code == 400


def test_forgot_password_does_not_issue_link_after_recovery_email_changes(api, monkeypatch, verify_recovery_email):
    from service import password_reset as reset_service

    client, db = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    verify_recovery_email(client, token, monkeypatch)
    account_id = db.get_active_account_by_username("alice")["account_id"]
    deliveries = _capture_verification_deliveries(monkeypatch)
    change_request = client.post(
        "/auth/email/change", json={"email": "new@example.com"}, headers=_authed(token)
    )
    assert change_request.status_code == 200
    change_code = _verification_code(deliveries[-1])
    original_store = reset_service._store_requested_reset_token

    def rotate_email_before_token_store(*args, **kwargs):
        assert reset_service.verify_recovery_email_change_code(db, account_id, change_code)
        return original_store(*args, **kwargs)

    monkeypatch.setattr(reset_service, "_store_requested_reset_token", rotate_email_before_token_store)
    monkeypatch.setattr(
        reset_service.secrets, "token_urlsafe", lambda _byte_count: "stale-address-reset-token-1234"
    )
    response = client.post("/auth/forgot-password", json={"email": "alice@example.com"})

    assert response.status_code == 202
    assert not any(delivery[3].purpose == email_sender.PURPOSE_PASSWORD_RESET for delivery in deliveries)
    stale_link = client.post(
        "/auth/reset-password",
        json={"token": "stale-address-reset-token-1234", "new_password": "attacker-horse-99"},
    )
    assert stale_link.status_code == 400


def test_owner_reset_email_does_not_issue_link_after_recovery_email_changes(
    api, monkeypatch, verify_recovery_email
):
    from service import password_reset as reset_service

    client, db = api
    token = _register(client, "alice")
    _set_recovery_email(client, token)
    verify_recovery_email(client, token, monkeypatch)
    account_id = db.get_active_account_by_username("alice")["account_id"]
    deliveries = _capture_verification_deliveries(monkeypatch)
    change_request = client.post(
        "/auth/email/change", json={"email": "new@example.com"}, headers=_authed(token)
    )
    assert change_request.status_code == 200
    change_code = _verification_code(deliveries[-1])
    original_store = reset_service._store_requested_reset_token

    def rotate_email_before_token_store(*args, **kwargs):
        assert reset_service.verify_recovery_email_change_code(db, account_id, change_code)
        return original_store(*args, **kwargs)

    monkeypatch.setattr(reset_service, "_store_requested_reset_token", rotate_email_before_token_store)
    result = reset_service.owner_send_reset_email(db, account_id, "owner", None)

    assert result["outcome"] == "send_failed"
    assert db.get_account_email(account_id) == "new@example.com"
    assert db.catalog_conn.execute(
        "SELECT COUNT(*) FROM password_reset_tokens WHERE trainee_id = ?", (account_id,)
    ).fetchone()[0] == 0


def test_owner_password_catalog_failure_keeps_old_password(api, monkeypatch):
    from service import password_reset as reset_service

    client, db = api
    _register(client, "alice")

    def fail_epoch_update(_account_id):
        raise RuntimeError("catalog update failed")

    monkeypatch.setattr(db, "bump_account_session_epoch", fail_epoch_update)
    with pytest.raises(RuntimeError, match="catalog update failed"):
        reset_service.owner_set_password(db, "alice", "new-owner-password-22", actor="cli")

    assert client.post(
        "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}
    ).status_code == 200


def test_owner_password_ledger_failure_revokes_links_but_keeps_old_password(api, monkeypatch):
    from database.ledger.handle import TrainingLedger
    from service import password_reset as reset_service
    from service._tokens import hash_token

    client, db = api
    _register(client, "alice")
    account_id = db.get_active_account_by_username("alice")["account_id"]
    reset_token = "owner-reset-before-ledger-error-1234"
    db.store_reset_token(hash_token(reset_token), account_id, "2099-01-01T00:00:00+00:00")

    def fail_ledger_write(_ledger, _password_hash):
        raise RuntimeError("ledger write failed")

    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(TrainingLedger, "set_password_hash", fail_ledger_write)
        with pytest.raises(RuntimeError, match="ledger write failed"):
            reset_service.owner_set_password(
                db, "alice", "new-owner-password-22", actor="cli"
            )

    assert client.post(
        "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}
    ).status_code == 200
    stale_link = client.post(
        "/auth/reset-password",
        json={"token": reset_token, "new_password": "attacker-horse-99"},
    )
    assert stale_link.status_code == 400


def test_password_hashing_for_one_account_does_not_lock_other_accounts(api, monkeypatch):
    import threading

    import bcrypt

    from service import auth as auth_service

    client, db = api
    _register(client, "alice")
    _register(client, "bob")
    alice_id = db.get_active_account_by_username("alice")["account_id"]
    bob_id = db.get_active_account_by_username("bob")["account_id"]
    hash_started = threading.Event()
    release_hash = threading.Event()
    bob_finished = threading.Event()
    results = {}
    real_hashpw = bcrypt.hashpw

    def pause_alice_hash(password, salt):
        if password == b"alice-new-password-22":
            hash_started.set()
            if not release_hash.wait(10):
                raise TimeoutError("test did not release the paused bcrypt call")
        return real_hashpw(password, salt)

    monkeypatch.setattr(bcrypt, "hashpw", pause_alice_hash)

    def change_alice_password():
        try:
            results["alice"] = auth_service.change_password(
                db, alice_id, "correct-horse-1", "alice-new-password-22"
            )
        except Exception as exc:
            results["alice_error"] = exc

    def change_bob_password():
        try:
            results["bob"] = auth_service.change_password(
                db, bob_id, "correct-horse-1", "bob-new-password-22"
            )
        except Exception as exc:
            results["bob_error"] = exc
        finally:
            bob_finished.set()

    alice_thread = threading.Thread(target=change_alice_password)
    alice_thread.start()
    if not hash_started.wait(5):
        release_hash.set()
        alice_thread.join(10)
        pytest.fail("Alice's password hash did not reach bcrypt")
    bob_thread = threading.Thread(target=change_bob_password)
    bob_thread.start()
    try:
        bob_completed_before_release = bob_finished.wait(3)
    finally:
        release_hash.set()
        alice_thread.join(10)
        bob_thread.join(10)

    assert bob_completed_before_release
    assert "bob_error" not in results
    assert "alice_error" not in results
    assert results["alice"]["ok"] is True
    assert results["bob"]["ok"] is True


def test_reset_weak_password_does_not_consume_token(api, monkeypatch, verify_recovery_email):
    from service import password_reset as reset_service

    client, db = api
    _register(client, "alice")
    login_token = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()["access_token"]
    client.post("/auth/email", json={"email": "alice@example.com"}, headers=_authed(login_token))
    verify_recovery_email(client, login_token, monkeypatch)
    reset_service.request_password_reset(db, "alice@example.com", mailer=lambda to, link, display_language, *, account_id=None: True, token_factory=lambda: "patient-token-abcdef1234")

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
    assert deliveries[0][1] == "رمز تأكيد البريد الإلكتروني للاسترداد في MYOS"
    assert "استخدم الرمز التالي" in deliveries[0][2]


def test_console_sender_logs_code_without_recovery_address(api, monkeypatch, caplog):
    _, db = api
    monkeypatch.delenv("SMTP_HOST", raising=False)
    caplog.set_level("INFO", logger="service.email_sender")

    delivered = email_sender.send_recovery_email_verification_code(
        "private@example.com", "654321", "en", account_id="account-alice"
    )
    notice_delivered = email_sender.send_recovery_email_changed_notice(
        "private@example.com", "n***@example.com", "en", account_id="account-alice"
    )

    assert delivered is notice_delivered is True
    assert "654321" in caplog.text
    assert "private@example.com" not in caplog.text
    assert "n***@example.com" not in caplog.text
    assert db.catalog_conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def _set_and_verify_recovery_email(client, token, deliveries, email="old@example.com"):
    _set_recovery_email(client, token, email)
    sent = client.post("/auth/email/verification-code", headers=_authed(token))
    assert sent.status_code == 200, sent.text
    code = _verification_code(deliveries[-1])
    verified = client.post("/auth/email/verify", json={"code": code}, headers=_authed(token))
    assert verified.status_code == 200, verified.text


@pytest.mark.parametrize(
    ("display_language", "notice_copy"),
    [
        ("en", "The recovery email for your MYOS account was changed."),
        ("ar", "تم تغيير البريد الإلكتروني للاسترداد"),
    ],
)
def test_recovery_email_change_keeps_old_address_until_verified_and_notifies_in_display_language(
    api, monkeypatch, display_language, notice_copy
):
    client, db = api
    token = _register(client, "alice", display_language=display_language)
    deliveries = _capture_verification_deliveries(monkeypatch)
    _set_and_verify_recovery_email(client, token, deliveries)
    account_id = db.get_active_account_by_username("alice")["account_id"]
    headers = _authed(token)

    requested = client.post(
        "/auth/email/change", json={"email": "x@example.com"}, headers=headers
    )

    assert requested.status_code == 200, requested.text
    code = _verification_code(deliveries[-1])
    assert deliveries[-1][0] == "x@example.com"
    current = client.get("/auth/email", headers=headers)
    assert current.json() == {
        "email": "old@example.com",
        "verified": True,
        "pending_email": "x@example.com",
    }

    reset = client.post("/auth/forgot-password", json={"email": "old@example.com"})
    assert reset.status_code == 202
    reset_delivery = next(item for item in deliveries if item[3].purpose == "password_reset")
    assert reset_delivery[0] == "old@example.com"

    verified = client.post(
        "/auth/email/change/verify", json={"code": code}, headers=headers
    )
    assert verified.status_code == 200, verified.text
    assert client.get("/auth/email", headers=headers).json() == {
        "email": "x@example.com",
        "verified": True,
    }
    notice = next(item for item in deliveries if item[3].purpose == "recovery_email_changed_notice")
    assert notice[0] == "old@example.com"
    assert notice_copy in notice[2]
    assert "*@example.com" in notice[2]
    assert "x@example.com" not in notice[2]
    assert db.get_pending_recovery_email(account_id) is None
    assert db.catalog_conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_forgot_password_does_not_send_to_a_pending_recovery_address(api, monkeypatch):
    from service import password_reset

    client, _ = api
    token = _register(client, "alice")
    deliveries = _capture_verification_deliveries(monkeypatch)
    _set_and_verify_recovery_email(client, token, deliveries)
    requested = client.post(
        "/auth/email/change",
        json={"email": "pending@example.com"},
        headers=_authed(token),
    )
    assert requested.status_code == 200, requested.text
    sent_before_forgot = len(deliveries)

    forgot = client.post(
        "/auth/forgot-password", json={"email": "pending@example.com"}
    )

    assert forgot.status_code == 202
    assert forgot.json() == {"message": password_reset.GENERIC_REQUEST_MESSAGE}
    assert len(deliveries) == sent_before_forgot


def test_expired_pending_address_forgot_password_uses_unknown_address_notice(api, monkeypatch):
    client, db = api
    token = _register(client, "alice")
    deliveries = _capture_verification_deliveries(monkeypatch)
    _set_and_verify_recovery_email(client, token, deliveries)
    change = client.post(
        "/auth/email/change",
        json={"email": "expired-pending@example.com"},
        headers=_authed(token),
    )
    assert change.status_code == 200, change.text
    db.catalog_conn.execute(
        "UPDATE email_verification_codes SET expires_at = ? WHERE purpose = ?",
        ("2000-01-01T00:00:00+00:00", "recovery_email_change"),
    )
    db.catalog_conn.commit()

    forgot = client.post(
        "/auth/forgot-password", json={"email": "expired-pending@example.com"}
    )

    assert forgot.status_code == 202
    assert forgot.json() == {
        "message": "If this email is linked to a ledger, a reset link is on its way."
    }
    notice = next(
        item for item in deliveries if item[3].purpose == "no_account_notice"
    )
    assert notice[0] == "expired-pending@example.com"


def test_recovery_email_change_wrong_expired_and_reused_codes_are_generic_and_atomic(api, monkeypatch):
    client, db = api
    token = _register(client, "alice")
    deliveries = _capture_verification_deliveries(monkeypatch)
    _set_and_verify_recovery_email(client, token, deliveries)
    headers = _authed(token)

    requested = client.post(
        "/auth/email/change", json={"email": "new@example.com"}, headers=headers
    )
    assert requested.status_code == 200, requested.text
    code = _verification_code(deliveries[-1])
    wrong = client.post(
        "/auth/email/change/verify", json={"code": "000000"}, headers=headers
    )
    assert wrong.status_code == 400
    assert wrong.json() == GENERIC_VERIFICATION_ERROR_BODY
    assert client.get("/auth/email", headers=headers).json() == {
        "email": "old@example.com",
        "verified": True,
        "pending_email": "new@example.com",
    }

    db.catalog_conn.execute(
        "UPDATE email_verification_codes SET expires_at = '2000-01-01T00:00:00+00:00'"
    )
    db.catalog_conn.commit()
    expired = client.post(
        "/auth/email/change/verify", json={"code": code}, headers=headers
    )
    assert expired.status_code == 400
    assert expired.json() == GENERIC_VERIFICATION_ERROR_BODY
    assert wrong.json() == expired.json()
    assert client.get("/auth/email", headers=headers).json()["email"] == "old@example.com"

    replacement = client.post(
        "/auth/email/change", json={"email": "fresh@example.com"}, headers=headers
    )
    assert replacement.status_code == 200, replacement.text
    fresh_code = _verification_code(deliveries[-1])
    accepted = client.post(
        "/auth/email/change/verify", json={"code": fresh_code}, headers=headers
    )
    assert accepted.status_code == 200, accepted.text
    reused = client.post(
        "/auth/email/change/verify", json={"code": fresh_code}, headers=headers
    )
    assert reused.status_code == 400
    assert reused.json() == GENERIC_VERIFICATION_ERROR_BODY
    assert wrong.json() == expired.json() == reused.json()
    assert client.get("/auth/email", headers=headers).json() == {
        "email": "fresh@example.com",
        "verified": True,
    }


def test_new_recovery_email_change_replaces_pending_code(api, monkeypatch):
    from service import email_verification

    client, _ = api
    token = _register(client, "alice")
    deliveries = _capture_verification_deliveries(monkeypatch)
    _set_and_verify_recovery_email(client, token, deliveries)
    codes = iter((111111, 222222))
    monkeypatch.setattr(email_verification.secrets, "randbelow", lambda _: next(codes))
    headers = _authed(token)

    first = client.post(
        "/auth/email/change", json={"email": "first@example.com"}, headers=headers
    )
    first_code = _verification_code(deliveries[-1])
    second = client.post(
        "/auth/email/change", json={"email": "second@example.com"}, headers=headers
    )
    second_code = _verification_code(deliveries[-1])

    assert first.status_code == second.status_code == 200
    stale = client.post(
        "/auth/email/change/verify", json={"code": first_code}, headers=headers
    )
    assert stale.status_code == 400
    assert stale.json() == GENERIC_VERIFICATION_ERROR_BODY
    assert client.get("/auth/email", headers=headers).json() == {
        "email": "old@example.com",
        "verified": True,
        "pending_email": "second@example.com",
    }
    accepted = client.post(
        "/auth/email/change/verify", json={"code": second_code}, headers=headers
    )
    assert accepted.status_code == 200, accepted.text
    assert client.get("/auth/email", headers=headers).json()["email"] == "second@example.com"


def test_recovery_email_change_refuses_address_linked_to_another_account_without_sending(
    api, monkeypatch
):
    client, _ = api
    alice = _register(client, "alice")
    bob = _register(client, "bob")
    deliveries = _capture_verification_deliveries(monkeypatch)
    _set_and_verify_recovery_email(client, alice, deliveries, "alice@example.com")
    _set_and_verify_recovery_email(client, bob, deliveries, "bob@example.com")
    sent_before = len(deliveries)

    refused = client.post(
        "/auth/email/change",
        json={"email": "bob@example.com"},
        headers=_authed(alice),
    )

    assert refused.status_code == 400
    assert len(deliveries) == sent_before
    assert client.get("/auth/email", headers=_authed(alice)).json() == {
        "email": "alice@example.com",
        "verified": True,
    }


def test_two_accounts_can_pending_the_same_address_but_only_one_can_verify(api, monkeypatch):
    client, _ = api
    alice = _register(client, "alice")
    bob = _register(client, "bob")
    deliveries = _capture_verification_deliveries(monkeypatch)
    _set_and_verify_recovery_email(client, alice, deliveries, "alice@example.com")
    _set_and_verify_recovery_email(client, bob, deliveries, "bob@example.com")
    alice_headers = _authed(alice)
    bob_headers = _authed(bob)

    alice_request = client.post(
        "/auth/email/change",
        json={"email": "shared@example.com"},
        headers=alice_headers,
    )
    alice_code = _verification_code(deliveries[-1])
    bob_request = client.post(
        "/auth/email/change",
        json={"email": "shared@example.com"},
        headers=bob_headers,
    )
    bob_code = _verification_code(deliveries[-1])

    assert alice_request.status_code == bob_request.status_code == 200
    assert client.post(
        "/auth/email/change/verify", json={"code": alice_code}, headers=alice_headers
    ).status_code == 200
    bob_verify = client.post(
        "/auth/email/change/verify", json={"code": bob_code}, headers=bob_headers
    )

    assert bob_verify.status_code == 400
    assert bob_verify.json() == GENERIC_VERIFICATION_ERROR_BODY
    assert client.get("/auth/email", headers=alice_headers).json() == {
        "email": "shared@example.com",
        "verified": True,
    }
    assert client.get("/auth/email", headers=bob_headers).json() == {
        "email": "bob@example.com",
        "verified": True,
        "pending_email": "shared@example.com",
    }


def test_existing_pending_email_unique_constraint_is_removed(api):
    _, db = api
    with db.catalog_transaction(immediate=True):
        db.catalog_conn.execute("DROP TABLE pending_recovery_emails")
        db.catalog_conn.execute(
            "CREATE TABLE pending_recovery_emails ("
            "account_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, updated_at TEXT NOT NULL)"
        )
        db.catalog_conn.execute(
            "INSERT INTO pending_recovery_emails VALUES (?, ?, ?)",
            ("account-a", "shared@example.com", "2026-10-04T00:00:00+00:00"),
        )

    db._account_schema_ready = False
    db.ensure_account_schema()

    indexes = db.catalog_conn.execute(
        "PRAGMA index_list(pending_recovery_emails)"
    ).fetchall()
    unique_email_indexes = []
    for index in indexes:
        if index[2]:
            columns = db.catalog_conn.execute(
                f"PRAGMA index_info({index[1]})"
            ).fetchall()
            if [str(column[2]) for column in columns] == ["email"]:
                unique_email_indexes.append(index[1])
    assert unique_email_indexes == []
    assert db.get_pending_recovery_email("account-a") == "shared@example.com"
    with db.catalog_transaction(immediate=True):
        db.catalog_conn.execute(
            "INSERT INTO pending_recovery_emails VALUES (?, ?, ?)",
            ("account-b", "shared@example.com", "2026-10-04T00:00:00+00:00"),
        )


def test_gate_writer_rechecks_verified_address_after_concurrent_swap(api, monkeypatch):
    from service import password_reset

    client, db = api
    token = _register(client, "alice")
    deliveries = _capture_verification_deliveries(monkeypatch)
    _set_and_verify_recovery_email(client, token, deliveries)
    change = client.post(
        "/auth/email/change",
        json={"email": "new@example.com"},
        headers=_authed(token),
    )
    assert change.status_code == 200, change.text
    change_code = _verification_code(deliveries[-1])
    write_email = db.set_account_email

    def swap_before_gate_write(account_id, email):
        assert password_reset.verify_recovery_email_change_code(
            db, account_id, change_code
        )
        return write_email(account_id, email)

    monkeypatch.setattr(db, "set_account_email", swap_before_gate_write)
    refused = client.post(
        "/auth/email", json={"email": "old@example.com"}, headers=_authed(token)
    )

    assert refused.status_code == 400
    assert client.get("/auth/email", headers=_authed(token)).json() == {
        "email": "new@example.com",
        "verified": True,
    }


def test_change_notice_targets_address_replaced_inside_verification_transaction(api, monkeypatch):
    client, db = api
    token = _register(client, "alice")
    deliveries = _capture_verification_deliveries(monkeypatch)
    _set_and_verify_recovery_email(client, token, deliveries)
    change = client.post(
        "/auth/email/change",
        json={"email": "new@example.com"},
        headers=_authed(token),
    )
    assert change.status_code == 200, change.text
    change_code = _verification_code(deliveries[-1])
    consume = db._consume_email_verification_code_with_previous_address

    def interleave_address_change(check):
        with db.catalog_transaction(immediate=True):
            db.catalog_conn.execute(
                "UPDATE trainee_emails SET email = ? WHERE trainee_id = ?",
                ("interleaved@example.com", check.identity.account_id),
            )
        return consume(check)

    monkeypatch.setattr(
        db,
        "_consume_email_verification_code_with_previous_address",
        interleave_address_change,
    )
    verified = client.post(
        "/auth/email/change/verify",
        json={"code": change_code},
        headers=_authed(token),
    )

    assert verified.status_code == 200, verified.text
    notice = next(item for item in deliveries if item[3].purpose == "recovery_email_changed_notice")
    assert notice[0] == "interleaved@example.com"
    assert client.get("/auth/email", headers=_authed(token)).json()["email"] == "new@example.com"


def test_verified_recovery_email_cannot_be_replaced_through_gate_endpoint(api, monkeypatch):
    client, _ = api
    token = _register(client, "alice")
    deliveries = _capture_verification_deliveries(monkeypatch)
    _set_and_verify_recovery_email(client, token, deliveries)

    refused = client.post(
        "/auth/email", json={"email": "bypass@example.com"}, headers=_authed(token)
    )

    assert refused.status_code == 400
    assert client.get("/auth/email", headers=_authed(token)).json()["email"] == "old@example.com"


def test_recovery_email_change_uses_reset_rate_limit(api, monkeypatch):
    client, _ = api
    token = _register(client, "alice")
    deliveries = _capture_verification_deliveries(monkeypatch)
    _set_and_verify_recovery_email(client, token, deliveries)
    headers = _authed(token)

    statuses = [
        client.post(
            "/auth/email/change",
            json={"email": f"new-{index}@example.com"},
            headers=headers,
        ).status_code
        for index in range(4)
    ]

    assert statuses == [200, 200, 200, 429]
    assert len(deliveries) == 4


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
    assert wrong.json() == GENERIC_VERIFICATION_ERROR_BODY


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
    assert expired.json() == GENERIC_VERIFICATION_ERROR_BODY


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
    assert reused.json() == GENERIC_VERIFICATION_ERROR_BODY


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
    assert invalidated.json() == GENERIC_VERIFICATION_ERROR_BODY
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
        assert response.json() == GENERIC_VERIFICATION_ERROR_BODY

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
    assert response.json() == GENERIC_VERIFICATION_ERROR_BODY
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
    assert results[-1].json() == RECOVERY_CODE_SEND_LIMIT_BODY
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
    assert all(response.json() == GENERIC_VERIFICATION_ERROR_BODY for response in responses)
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
    assert all(response.json() == GENERIC_VERIFICATION_ERROR_BODY for response in responses[:10])


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
    from service._tokens import hash_token

    cli_reset_token = "cli-reset-removal-token-123456"
    db.store_reset_token(
        hash_token(cli_reset_token),
        account_id,
        "2099-01-01T00:00:00+00:00",
    )

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
    stale_reset = client.post(
        "/auth/reset-password",
        json={"token": cli_reset_token, "new_password": "attacker-horse-99"},
    )
    assert stale_reset.status_code == 400
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
