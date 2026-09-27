"""Mobile password recovery: reset-link format, access-log redaction, App Link
statement, hosted page, and the full logged-out round trip against real JWTs
(issue #38, ADR 037)."""

import logging
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import email_sender
from service import password_reset as reset_service
from svc.app import RedactResetTokenFilter, create_app
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
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute("CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT);")
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.commit()
    cat_conn.close()
    db = DatabaseManager(
        catalog_path=catalog_path, ledgers_dir=tmp_path / "users", backups_dir=tmp_path / "backups", default_ledger_id="bootstrap"
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    limiter._storage.reset()
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(api_client, ledger_id, password="correct-horse-1"):
    resp = api_client.post("/auth/register", json={"trainee_id": ledger_id, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _reset_limiter():
    from svc.rate_limit import limiter

    limiter._storage.reset()


def _capture_reset_link(monkeypatch) -> dict[str, str]:
    """Patch the lowest-level mailer so the real composed email body is captured."""
    captured: dict[str, str] = {}

    def fake_deliver(to_email: str, subject: str, body: str) -> bool:
        captured["to"] = to_email
        captured["subject"] = subject
        captured["body"] = body
        return True

    monkeypatch.setattr(email_sender, "_deliver", fake_deliver)
    return captured


def _set_recovery_email(client, token, email="alice@example.com"):
    saved = client.post("/auth/email", json={"email": email}, headers=_authed(token))
    assert saved.status_code == 200, saved.text


def test_reset_link_uses_configured_base(monkeypatch):
    monkeypatch.setenv("RESET_LINK_BASE_URL", "https://mayos-api.fly.dev/")
    assert email_sender.build_reset_link("tok-123") == "https://mayos-api.fly.dev/reset-password?token=tok-123"


def test_reset_link_defaults_to_the_api_local_base(monkeypatch):
    monkeypatch.delenv("RESET_LINK_BASE_URL", raising=False)
    # No UI_BASE_URL fallback: the default is the API's own dev base.
    monkeypatch.setenv("UI_BASE_URL", "https://legacy.example.com/")
    assert email_sender.build_reset_link("tok-abc") == "http://localhost:8000/reset-password?token=tok-abc"


def test_access_log_filter_redacts_token_query():
    redacted = RedactResetTokenFilter()
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", "/reset-password?token=SECRET-XYZ", "1.1", 200),
        None,
    )
    assert redacted.filter(record) is True
    rendered = record.getMessage()
    assert "SECRET-XYZ" not in rendered
    assert "token=[REDACTED]" in rendered

    # A pre-rendered message is covered too, and unrelated paths are untouched.
    plain = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "GET /healthz token=none", (), None)
    redacted.filter(plain)
    assert plain.getMessage() == "GET /healthz token=[REDACTED]"
    keep = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "GET /healthz", (), None)
    redacted.filter(keep)
    assert keep.getMessage() == "GET /healthz"


def test_normalize_fingerprint_accepts_case_and_colons():
    from service.app_links import normalize_fingerprint

    colons_upper = "AA:" * 31 + "AA"
    assert normalize_fingerprint("aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99:"
                                 "aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99") == (
        "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:"
        "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99"
    )
    assert normalize_fingerprint(colons_upper) == colons_upper
    assert normalize_fingerprint("nope") is None
    assert normalize_fingerprint("AA:BB:CC") is None


def test_assetlinks_unconfigured_returns_404(api, monkeypatch):
    monkeypatch.delenv("ANDROID_APP_SHA256_CERT_FINGERPRINTS", raising=False)
    client, _ = api
    assert client.get("/.well-known/assetlinks.json").status_code == 404


def test_assetlinks_normalizes_and_skips_invalid(api, monkeypatch, caplog):
    client, _ = api
    monkeypatch.setenv("ANDROID_APP_PACKAGE", "com.mayos.mayos_mobile")
    valid_lower = "aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99:aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99"
    valid_no_colons = "AABBCCDDEEFF00112233445566778899AABBCCDDEEFF00112233445566778899"
    monkeypatch.setenv(
        "ANDROID_APP_SHA256_CERT_FINGERPRINTS",
        f"{valid_lower}, not-a-fingerprint ,{valid_no_colons}",
    )
    with caplog.at_level(logging.WARNING, logger="service.app_links"):
        resp = client.get("/.well-known/assetlinks.json")
    assert resp.status_code == 200
    target = resp.json()[0]["target"]
    assert target["package_name"] == "com.mayos.mayos_mobile"
    # Both valid entries normalise to the same uppercase, colon-separated form.
    expected = "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99"
    assert target["sha256_cert_fingerprints"] == [expected]
    assert "invalid Android cert fingerprint" in caplog.text

    # Only-invalid input is a 404, not an empty statement.
    monkeypatch.setenv("ANDROID_APP_SHA256_CERT_FINGERPRINTS", "bad, also-bad")
    assert client.get("/.well-known/assetlinks.json").status_code == 404


def test_hosted_reset_page_security_headers_and_script(api):
    client, _ = api
    secret_token = "SECRET-RESET-TOKEN-DO-NOT-ECHO"
    resp = client.get(f"/reset-password?token={secret_token}")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["x-content-type-options"] == "nosniff"
    csp = resp.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "script-src 'nonce-" in csp
    # The token is read from location in JS and never reflected into the page.
    assert secret_token not in resp.text
    assert "new_password" in resp.text
    # The URL is scrubbed immediately after reading the token.
    assert "history.replaceState(null, '', location.pathname)" in resp.text
    # Server strings are JSON-embedded, and a non-string detail falls back.
    assert 'var CONFIG = {"generic"' in resp.text
    assert "typeof detail === 'string'" in resp.text


def test_forgot_reset_round_trip_email_body_and_session_revocation(api, monkeypatch):
    client, _ = api
    old_token = _register(client, "alice")
    _set_recovery_email(client, old_token)
    assert client.get("/dashboard/exercises", headers=_authed(old_token)).status_code == 200

    monkeypatch.setenv("RESET_LINK_BASE_URL", "https://mayos-api.fly.dev")
    captured = _capture_reset_link(monkeypatch)
    _reset_limiter()
    forgot = client.post("/auth/forgot-password", json={"email": "alice@example.com"})
    assert forgot.status_code == 202
    assert captured["to"] == "alice@example.com"
    body = captured["body"]
    # The real composed email body carries the app/web wording and the TTL.
    assert "opens the app" in body
    assert "secure web page" in body
    assert "single-use" in body
    assert "expires in 30 minutes" in body
    link = re.search(r"https://mayos-api\.fly\.dev/reset-password\?token=\S+", body)
    assert link is not None, body
    token = link.group(0).split("token=", 1)[1]

    reset = client.post("/auth/reset-password", json={"token": token, "new_password": "reset-horse-33"})
    assert reset.status_code == 200, reset.text

    # The reset bumps the session epoch, so the prior session is dead.
    assert client.get("/dashboard/exercises", headers=_authed(old_token)).status_code == 401
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 401
    relogin = client.post("/auth/login", json={"trainee_id": "alice", "password": "reset-horse-33"})
    assert relogin.status_code == 200, relogin.text
    assert client.get("/dashboard/exercises", headers=_authed(relogin.json()["access_token"])).status_code == 200


def test_remember_me_session_is_rejected_after_reset(api):
    client, db = api
    _register(client, "alice")
    basic = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()["access_token"]
    remembered = client.post(
        "/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1", "remember_me": True}
    ).json()["access_token"]
    _set_recovery_email(client, basic)
    # Both sessions are live before the reset.
    assert client.get("/dashboard/exercises", headers=_authed(basic)).status_code == 200
    assert client.get("/dashboard/exercises", headers=_authed(remembered)).status_code == 200

    reset_service.request_password_reset(
        db, "alice@example.com", mailer=lambda to, link: True, token_factory=lambda: "remember-token-abcdef1234"
    )
    _reset_limiter()
    reset = client.post(
        "/auth/reset-password", json={"token": "remember-token-abcdef1234", "new_password": "remember-horse-9"}
    )
    assert reset.status_code == 200, reset.text

    # The long-lived remember-me token is revoked too (ADR 010), not just the short one.
    assert client.get("/dashboard/exercises", headers=_authed(basic)).status_code == 401
    assert client.get("/dashboard/exercises", headers=_authed(remembered)).status_code == 401


def test_coach_account_completes_forgot_reset_login(api, monkeypatch):
    client, db = api
    token = _register(client, "coachlet")
    _set_recovery_email(client, token, "coachlet@example.com")
    issued = coach_service.issue_coach_invite(db, "coachlet")
    assert issued["ok"], issued
    redeemed = client.post("/coach/invite/redeem", headers=_authed(token), json={"token": issued["token"]})
    assert redeemed.status_code == 200, redeemed.text
    assert client.get("/auth/me", headers=_authed(token)).json()["capabilities"]["coach"] is True

    captured = _capture_reset_link(monkeypatch)
    monkeypatch.setenv("RESET_LINK_BASE_URL", "https://mayos-api.fly.dev")
    _reset_limiter()
    forgot = client.post("/auth/forgot-password", json={"email": "coachlet@example.com"})
    assert forgot.status_code == 202
    token_in_email = re.search(r"/reset-password\?token=\S+", captured["body"]).group(0).split("token=", 1)[1]

    reset = client.post("/auth/reset-password", json={"token": token_in_email, "new_password": "coach-horse-77"})
    assert reset.status_code == 200, reset.text
    assert client.get("/dashboard/exercises", headers=_authed(token)).status_code == 401

    relogin = client.post("/auth/login", json={"trainee_id": "coachlet", "password": "coach-horse-77"})
    assert relogin.status_code == 200, relogin.text
    me = client.get("/auth/me", headers=_authed(relogin.json()["access_token"]))
    assert me.status_code == 200
    assert me.json()["capabilities"]["coach"] is True


def test_reset_token_failures_are_generic_and_change_nothing(api):
    client, db = api
    _register(client, "alice")
    alice_token = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).json()[
        "access_token"
    ]
    _set_recovery_email(client, alice_token)

    # Fabricated token.
    _reset_limiter()
    fabricated = client.post(
        "/auth/reset-password", json={"token": "no-such-token-zzzzzzzzzz", "new_password": "whatever-horse-1"}
    )
    assert fabricated.status_code == 400
    assert fabricated.json()["detail"] == reset_service.GENERIC_TOKEN_ERROR

    # Reused token: redeem once, then replay the same token.
    reset_service.request_password_reset(
        db, "alice@example.com", mailer=lambda to, link: True, token_factory=lambda: "one-time-token-abcdef1234"
    )
    _reset_limiter()
    first = client.post(
        "/auth/reset-password", json={"token": "one-time-token-abcdef1234", "new_password": "first-reset-11"}
    )
    assert first.status_code == 200
    _reset_limiter()
    reused = client.post(
        "/auth/reset-password", json={"token": "one-time-token-abcdef1234", "new_password": "second-reset-22"}
    )
    assert reused.status_code == 400
    assert reused.json() == fabricated.json()

    # Expired token: backdate the stored expiry, then redeem.
    reset_service.request_password_reset(
        db, "alice@example.com", mailer=lambda to, link: True, token_factory=lambda: "stale-token-abcdef1234"
    )
    account_id = db.get_active_account_by_username("alice")["account_id"]
    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE password_reset_tokens SET expires_at = ? WHERE trainee_id = ?",
            ("2000-01-01T00:00:00+00:00", account_id),
        )
        db.catalog_conn.commit()
    _reset_limiter()
    expired = client.post(
        "/auth/reset-password", json={"token": "stale-token-abcdef1234", "new_password": "whatever-horse-2"}
    )
    assert expired.status_code == 400
    assert expired.json() == fabricated.json()

    # Nothing changed: the latest password still logs in.
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "first-reset-11"}).status_code == 200


def test_forgot_password_is_anti_enumeration(api, monkeypatch):
    client, _ = api
    # The lowest-level mailer is stubbed so no SMTP is touched; there is no account.
    _capture_reset_link(monkeypatch)
    known = client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
    assert known.status_code == 202
    assert "reset link" in known.json()["message"]
