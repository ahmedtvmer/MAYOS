"""Owner admin login, session, alert, and audit behavior through HTTP."""

import base64
import hashlib
import hmac
import re
import sqlite3
import struct
from pathlib import Path

import bcrypt
import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from svc.app import create_app
from svc.dependencies import get_db
from svc.rate_limit import _client_ip, client_ip, limiter

ADMIN_PASSWORD = "owner-password-27"
ADMIN_USERNAME = "owner"
TOTP_SECRET = b"12345678901234567890"
TOTP_SECRET_BASE32 = base64.b32encode(TOTP_SECRET).decode("ascii").rstrip("=")
ADMIN_PASSWORD_HASH = bcrypt.hashpw(ADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode()


@pytest.fixture
def admin_api(tmp_path: Path, monkeypatch):
    limiter.reset()
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("FLY_APP_NAME", "admin-tests")
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USERNAME)
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", ADMIN_PASSWORD_HASH)
    monkeypatch.setenv("ADMIN_TOTP_SECRET", TOTP_SECRET_BASE32)
    monkeypatch.setenv("OWNER_ALERT_EMAIL", "owner@example.com")
    from service import email_sender

    sent_emails = []
    monkeypatch.setattr(email_sender, "_deliver", lambda *fields: sent_emails.append(fields) or True)
    catalog_path = tmp_path / "catalog.db"
    sqlite3.connect(catalog_path).close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    current_time = [1_700_000_000.0]
    app.state.admin_security.clock = lambda: current_time[0]
    client = TestClient(app, base_url="https://testserver")
    try:
        yield client, db, current_time, sent_emails
    finally:
        client.close()
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _totp(secret: bytes, timestamp: float) -> str:
    step = int(timestamp // 30)
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 1_000_000:06d}"


def _csrf(page: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', page)
    assert match, page
    return match.group(1)


def _login(
    client: TestClient,
    timestamp: float,
    *,
    password: str = ADMIN_PASSWORD,
    code: str | None = None,
    client_ip: str = "203.0.113.8",
):
    page = client.get("/admin/login")
    return client.post(
        "/admin/login",
        data={
            "csrf_token": _csrf(page.text),
            "username": ADMIN_USERNAME,
            "password": password,
            "totp_code": code if code is not None else _totp(TOTP_SECRET, timestamp),
        },
        headers={"Fly-Client-IP": client_ip, "User-Agent": "MAYOS admin test/1.0"},
        follow_redirects=False,
    )


def test_unconfigured_and_partially_configured_admin_routes_are_not_found(monkeypatch):
    for key in ("ADMIN_USERNAME", "ADMIN_PASSWORD_HASH", "ADMIN_TOTP_SECRET"):
        monkeypatch.delenv(key, raising=False)
    app = create_app()
    client = TestClient(app, base_url="https://testserver")
    assert client.get("/admin").status_code == 404
    assert client.get("/admin/login").status_code == 404
    assert client.post("/admin/login").status_code == 404
    client.close()
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USERNAME)
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", ADMIN_PASSWORD_HASH)
    app = create_app()
    client = TestClient(app, base_url="https://testserver")
    assert client.get("/admin/login").status_code == 404
    assert client.get("/admin/audit").status_code == 404
    client.close()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ADMIN_USERNAME", "owner@example.com"),
        ("ADMIN_PASSWORD_HASH", "not-a-bcrypt-hash"),
        ("ADMIN_TOTP_SECRET", "not-base32!"),
    ],
)
def test_malformed_admin_secret_disables_every_route(monkeypatch, key, value):
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USERNAME)
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", ADMIN_PASSWORD_HASH)
    monkeypatch.setenv("ADMIN_TOTP_SECRET", TOTP_SECRET_BASE32)
    monkeypatch.setenv(key, value)
    client = TestClient(create_app(), base_url="https://testserver")
    assert client.get("/admin/login").status_code == 404
    assert client.get("/admin").status_code == 404
    assert client.post("/admin/login").status_code == 404
    client.close()


def test_every_protected_path_is_the_same_404_before_login(admin_api):
    client, _, _, _ = admin_api
    home = client.get("/admin")
    audit = client.get("/admin/audit")
    unknown = client.get("/admin/accounts")
    assert home.status_code == audit.status_code == unknown.status_code == 404
    assert home.text == audit.text == unknown.text
    assert client.get("/admin/login").status_code == 200


@pytest.mark.parametrize(
    ("password", "code"),
    [("incorrect-password", None), (ADMIN_PASSWORD, "000000")],
)
def test_login_rejects_wrong_password_or_totp(admin_api, password, code):
    client, _, now, _ = admin_api
    rejected = _login(client, now[0], password=password, code=code)
    assert rejected.status_code == 401
    assert "Invalid username, password, or verification code" in rejected.text


def test_totp_replay_is_rejected(admin_api):
    client, _, now, _ = admin_api
    code = _totp(TOTP_SECRET, now[0])
    assert _login(client, now[0], code=code).status_code == 303
    client.post("/admin/logout", data={"csrf_token": _csrf(client.get("/admin").text)})
    replay = _login(client, now[0], code=code)
    assert replay.status_code == 401
    assert "Invalid username, password, or verification code" in replay.text


def test_login_lockout_applies_globally_and_expires(admin_api):
    client, _, now, _ = admin_api
    for octet in range(20, 24):
        for _ in range(5):
            assert _login(
                client,
                now[0],
                password="incorrect-password",
                client_ip=f"203.0.113.{octet}",
            ).status_code == 401
    locked = _login(client, now[0], client_ip="203.0.113.10")
    assert locked.status_code == 401
    now[0] += 15 * 60 + 1
    unlocked = _login(client, now[0], client_ip="203.0.113.10")
    assert unlocked.status_code == 303


def test_ip_lockout_last_full_fifteen_minutes_after_fifth_failure(admin_api):
    client, _, now, _ = admin_api
    from service.admin_auth import AdminLoginAttempt, AdminLoginResult

    security = client.app.state.admin_security
    attempt = AdminLoginAttempt(ADMIN_USERNAME, "incorrect-password", "000000", "203.0.113.8")
    for _ in range(4):
        assert security.verify_login(attempt) is AdminLoginResult.REJECTED
    now[0] += 14 * 60
    assert security.verify_login(attempt) is AdminLoginResult.LOCKOUT_STARTED
    now[0] += 60
    assert security.verify_login(attempt) is AdminLoginResult.LOCKED_OUT
    now[0] += 14 * 60
    fresh_attempt = AdminLoginAttempt(
        ADMIN_USERNAME,
        ADMIN_PASSWORD,
        _totp(TOTP_SECRET, now[0]),
        "203.0.113.8",
    )
    assert security.verify_login(fresh_attempt) is AdminLoginResult.SUCCESS


def test_per_ip_lockout_logs_once_and_does_not_block_another_ip(admin_api):
    client, _, now, _ = admin_api
    for _ in range(5):
        assert _login(client, now[0], password="incorrect-password").status_code == 401
    limiter.reset()
    assert _login(client, now[0]).status_code == 401
    assert _login(client, now[0], client_ip="203.0.113.9").status_code == 303
    audit = client.get("/admin/audit")
    assert audit.status_code == 200
    assert audit.text.count("<strong>Action:</strong> login_failed") == 4
    assert audit.text.count("<strong>Action:</strong> login_locked_out") == 1
    assert "203.0.113.8" in audit.text


def test_admin_login_is_rate_limited(admin_api):
    client, _, now, _ = admin_api
    results = [_login(client, now[0], password="incorrect-password").status_code for _ in range(6)]
    assert results[:5] == [401] * 5
    assert results[5] == 429


def test_admin_session_uses_secure_cookie_and_expires_after_idle_limit(admin_api):
    client, _, now, _ = admin_api
    response = _login(client, now[0])
    assert response.status_code == 303
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert "path=/admin" in cookie and "max-age=28800" in cookie
    assert client.get("/admin").status_code == 200
    now[0] += 30 * 60 + 1
    assert client.get("/admin").status_code == 404


def test_admin_session_expires_at_absolute_limit_even_when_active(admin_api):
    client, _, now, _ = admin_api
    assert _login(client, now[0]).status_code == 303
    for _ in range(17):
        now[0] += 1_600
        assert client.get("/admin").status_code == 200
    now[0] += 1_600
    assert client.get("/admin").status_code == 404


def test_logout_requires_csrf_and_revokes_session(admin_api):
    client, _, now, _ = admin_api
    assert _login(client, now[0]).status_code == 303
    home = client.get("/admin")
    missing = client.post("/admin/logout")
    wrong = client.post("/admin/logout", data={"csrf_token": "wrong-token"})
    assert missing.status_code == wrong.status_code == 403
    logout = client.post("/admin/logout", data={"csrf_token": _csrf(home.text)}, follow_redirects=False)
    assert logout.status_code == 303
    assert client.get("/admin").status_code == 404


def test_login_requires_csrf_token(admin_api):
    client, _, now, _ = admin_api
    client.get("/admin/login")
    fields = {
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD,
        "totp_code": _totp(TOTP_SECRET, now[0]),
    }
    assert client.post("/admin/login", data=fields).status_code == 403
    fields["csrf_token"] = "wrong-token"
    assert client.post("/admin/login", data=fields).status_code == 403


def test_login_alert_email_and_failed_delivery_banner_clear_on_later_success(admin_api, monkeypatch):
    from service import email_sender

    client, _, now, sent = admin_api
    responses = iter((False, True))
    monkeypatch.setattr(email_sender, "_deliver", lambda *fields: sent.append(fields) or next(responses))
    first = _login(client, now[0])
    assert first.status_code == 303
    assert len(sent) == 1
    assert sent[0][0] == "owner@example.com"
    assert sent[0][1] == "MAYOS owner dashboard login"
    assert "2023-11-14T22:13:20+00:00" in sent[0][2]
    assert "203.0.113.8" in sent[0][2] and "MAYOS admin test/1.0" in sent[0][2]
    home = client.get("/admin")
    assert "Login alert email could not be delivered" in home.text
    failed = client.get("/admin/audit").text
    assert "login_alert_failed" in failed and "login" in failed

    csrf = _csrf(home.text)
    client.post("/admin/logout", data={"csrf_token": csrf})
    now[0] += 30
    assert "Login alert email could not be delivered" in client.get("/admin/login").text
    assert _login(client, now[0]).status_code == 303
    assert len(sent) == 2
    assert "Login alert email could not be delivered" not in client.get("/admin").text


def test_unconfigured_login_alert_keeps_login_available_and_sets_banner(admin_api, monkeypatch):
    client, _, now, sent = admin_api
    monkeypatch.setenv("OWNER_ALERT_EMAIL", "")
    assert _login(client, now[0]).status_code == 303
    assert sent == []
    assert "Login alert email could not be delivered" in client.get("/admin").text
    assert "login_alert_failed" in client.get("/admin/audit").text


def test_audit_viewer_filters_actions_and_shows_login_events(admin_api):
    client, db, now, _ = admin_api
    assert _login(client, now[0], password="wrong-password").status_code == 401
    now[0] += 30
    assert _login(client, now[0]).status_code == 303
    client.post("/admin/logout", data={"csrf_token": _csrf(client.get("/admin").text)})
    audit = client.get("/admin/audit")
    assert audit.status_code == 404
    now[0] += 30
    assert _login(client, now[0]).status_code == 303
    audit = client.get("/admin/audit")
    assert audit.status_code == 200
    assert "login_failed" in audit.text and "login" in audit.text and "logout" in audit.text
    assert "203.0.113.8" in audit.text
    from service.audit_log import AuditEvent, write_audit_entry

    write_audit_entry(
        db,
        AuditEvent(
            actor="cli",
            action="password_reset_sent",
            target_account_id="acct-1",
            reason="Related account abcdefghijklmnopqrstuvwx on 2026-09-30, ref 12345678",
        ),
    )
    write_audit_entry(
        db,
        AuditEvent(actor="cli", action="coach_invite_revoked", target_account_id="acct-2"),
    )
    filtered = client.get("/admin/audit?action=password_reset_sent&account_id=acct-1")
    assert filtered.status_code == 200
    assert "password_reset_sent" in filtered.text and "Account id:</strong> acct-1" in filtered.text
    assert "coach_invite_revoked" not in filtered.text and "Account id:</strong> acct-2" not in filtered.text
    assert "2026-09-30" in filtered.text and "12345678" in filtered.text
    assert "owner@example.com" not in audit.text


def test_admin_responses_include_noindex_and_security_headers(admin_api):
    client, _, now, _ = admin_api
    before_login = client.get("/admin/audit")
    login_page = client.get("/admin/login")
    login = _login(client, now[0])
    for response in (before_login, login_page, login, client.get("/admin"), client.get("/admin/audit")):
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'name="robots" content="noindex"' in client.get("/admin").text


def test_totp_verifies_rfc_6238_sha1_vector():
    from service.admin_auth import verify_totp_code

    assert verify_totp_code(b"12345678901234567890", "287082", 59) == 1


def test_client_ip_is_normalized_and_private_alias_remains_available(monkeypatch):
    from starlette.requests import Request

    monkeypatch.setenv("FLY_APP_NAME", "admin-tests")
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [(b"fly-client-ip", b"2001:0db8:0:0::1")],
            "client": ("127.0.0.1", 54321),
            "server": ("test", 443),
        }
    )
    assert client_ip(request) == "2001:db8::1"
    assert _client_ip(request) == client_ip(request)


def test_credentials_script_outputs_credentials_accepted_by_admin_auth():
    from scripts.admin_credentials import generate_credentials
    from service.admin_auth import AdminConfig, AdminLoginAttempt, AdminSecurity, decode_totp_secret

    password_hash, secret, uri = generate_credentials(ADMIN_USERNAME, ADMIN_PASSWORD)
    assert uri.startswith("otpauth://totp/") and f"secret={secret}" in uri
    security = AdminSecurity(
        AdminConfig(ADMIN_USERNAME, password_hash, decode_totp_secret(secret)),
        clock=lambda: 1_700_000_000.0,
    )
    attempt = AdminLoginAttempt(
        ADMIN_USERNAME,
        ADMIN_PASSWORD,
        _totp(decode_totp_secret(secret), 1_700_000_000.0),
        "127.0.0.1",
    )
    from service.admin_auth import AdminLoginResult

    assert security.verify_login(attempt) is AdminLoginResult.SUCCESS
