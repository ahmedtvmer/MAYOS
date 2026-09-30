"""Owner admin login, session, alert, and audit behavior through HTTP."""

import base64
import hashlib
import hmac
import html
import json
import os
import re
import sqlite3
import struct
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bcrypt
import pytest
from fastapi.testclient import TestClient

from database.backup import daily_backups_root
from database.database_manager import DatabaseManager
from service.periodic_status import (
    ALERT_SWEEP_JOB,
    DAILY_BACKUP_JOB,
    configured_interval_seconds,
    get as get_periodic_run,
    record_run,
    reset as reset_periodic_status,
)
from svc.app import create_app
from svc.dependencies import get_db
from svc.rate_limit import client_ip, limiter

ADMIN_PASSWORD = "owner-password-27"
ADMIN_USERNAME = "owner"
TOTP_SECRET = b"12345678901234567890"
TOTP_SECRET_BASE32 = base64.b32encode(TOTP_SECRET).decode("ascii").rstrip("=")
ADMIN_PASSWORD_HASH = bcrypt.hashpw(ADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode()
TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"


@pytest.fixture
def admin_api(tmp_path: Path, monkeypatch):
    limiter.reset()
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
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
    app.state.db = db
    app.dependency_overrides[get_db] = lambda: db
    reset_periodic_status()
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


def _admin_home(client: TestClient, timestamp: float) -> str:
    assert _login(client, timestamp).status_code == 303
    response = client.get("/admin")
    assert response.status_code == 200
    return response.text


def _prepare_healthy_readiness(monkeypatch) -> None:
    details = {"model": True, "catalog": True, "storage": True, "draining": False}
    monkeypatch.setattr("svc.app.readiness_snapshot", lambda: ("ready", details))
    monkeypatch.setattr("service.periodic_status.process_started_at", lambda: datetime.now(UTC))


def _create_snapshot(db: DatabaseManager, created_at: datetime) -> Path:
    snapshot = daily_backups_root(db.backups_dir) / created_at.strftime("%Y%m%d")
    snapshot.mkdir(parents=True)
    (snapshot / "catalog.db").touch()
    os.utime(snapshot, (created_at.timestamp(), created_at.timestamp()))
    return snapshot


def _health_row(page: str, key: str) -> str:
    match = re.search(rf'<div class="health-row" data-health="{key}">(.*?)</div>', page)
    assert match, page
    return match.group(1)


def test_unconfigured_and_partially_configured_admin_routes_are_not_found(monkeypatch):
    for key in ("ADMIN_USERNAME", "ADMIN_PASSWORD_HASH", "ADMIN_TOTP_SECRET"):
        monkeypatch.delenv(key, raising=False)
    app = create_app()
    client = TestClient(app, base_url="https://testserver")
    assert client.get("/admin").status_code == 404
    assert client.get("/admin/login").status_code == 404
    assert client.post("/admin/login").status_code == 404
    assert client.get("/admin/assets/admin.css").status_code == 404
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


@pytest.mark.parametrize(
    ("asset_name", "content_type"),
    [
        ("admin.css", "text/css"),
        ("Inter-Variable.ttf", "font/ttf"),
        ("PlayfairDisplay-Variable.ttf", "font/ttf"),
        ("mayos-logo-blue.png", "image/png"),
        ("mayos-logo-white.png", "image/png"),
        ("favicon.png", "image/png"),
        ("apple-touch-icon.png", "image/png"),
        ("OFL-Inter.txt", "text/plain"),
        ("OFL-PlayfairDisplay.txt", "text/plain"),
    ],
)
def test_admin_brand_assets_are_available_before_login_with_immutable_cache(admin_api, asset_name, content_type):
    client, _, _, _ = admin_api
    response = client.get(f"/admin/assets/{asset_name}?v=test")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert response.content


def test_admin_pages_reference_brand_assets_with_strict_self_only_csp(admin_api):
    client, _, now, _ = admin_api
    login_page = client.get("/admin/login")
    assert login_page.status_code == 200
    assert 'class="login-card"' in login_page.text
    assert 'href="/admin/assets/admin.css?v=' in login_page.text
    assert 'href="/admin/assets/favicon.png?v=' in login_page.text
    assert 'href="/admin/assets/apple-touch-icon.png?v=' in login_page.text
    assert "/admin/assets/mayos-logo-blue.png?v=" in login_page.text
    assert "/admin/assets/mayos-logo-white.png?v=" in login_page.text
    assert "<style" not in login_page.text and "style=\"" not in login_page.text
    expected_csp = (
        "default-src 'none'; style-src 'self'; img-src 'self'; font-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    assert login_page.headers["content-security-policy"] == expected_csp
    assert "unsafe-inline" not in login_page.headers["content-security-policy"]

    stylesheet_url = re.search(r'href="([^"]*admin\.css\?v=[^"]+)', login_page.text).group(1)
    stylesheet = client.get(stylesheet_url)
    assert stylesheet.status_code == 200
    assert stylesheet_url.endswith(f"?v={hashlib.sha256(stylesheet.content).hexdigest()[:12]}")
    assert "font-family: \"Inter\"" in stylesheet.text
    assert "font-family: \"Playfair Display\"" in stylesheet.text
    assert "/admin/assets/Inter-Variable.ttf?v=" in stylesheet.text
    assert "/admin/assets/PlayfairDisplay-Variable.ttf?v=" in stylesheet.text
    assert "font-display: swap" in stylesheet.text
    assert "@media (prefers-color-scheme: dark)" in stylesheet.text
    assert "--color-accent: #2F6BFF" in stylesheet.text
    assert "--color-canvas: #0A1422" in stylesheet.text
    link_rule = re.search(r"(?m)^a\s*\{([^}]*)\}", stylesheet.text)
    assert link_rule and "text-decoration: none;" in link_rule.group(1)
    assert re.search(r"a:hover,\s*a:focus-visible\s*\{[^}]*text-decoration: underline;", stylesheet.text)
    brand_rule = re.search(
        r"\.brand-link,\s*\.brand-link:hover,\s*\.brand-link:focus-visible\s*\{([^}]*)\}",
        stylesheet.text,
    )
    assert brand_rule and "text-decoration: none;" in brand_rule.group(1)
    assert ".admin-nav-main" in stylesheet.text and "flex-wrap: wrap;" in stylesheet.text
    assert '.admin-nav-links .nav-link[aria-current="page"]' in stylesheet.text
    for brand_token in (
        "#F6F5F2", "#FFFFFF", "#F1F3F7", "#E2E4E9", "#CFD4DC", "#0E1B2E", "#4B5A70",
        "#2F6BFF", "#2257DE", "#DC2626", "#0A1422", "#101D2E", "#16263B", "#0D1826",
        "#22344C", "#324A69", "#F3F6FB", "#A7B6CB", "#F87171",
    ):
        assert brand_token in stylesheet.text
    for font_url in re.findall(r'url\("([^"]+\.ttf\?v=[^"]+)"\)', stylesheet.text):
        font = client.get(font_url)
        assert font.status_code == 200
        assert font_url.endswith(f"?v={hashlib.sha256(font.content).hexdigest()[:12]}")

    assert _login(client, now[0]).status_code == 303
    home = client.get("/admin")
    assert home.status_code == 200
    assert 'href="/admin/assets/admin.css?v=' in home.text
    assert 'href="/admin/assets/favicon.png?v=' in home.text
    assert 'href="/admin/assets/apple-touch-icon.png?v=' in home.text
    assert "/admin/assets/mayos-logo-blue.png?v=" in home.text
    assert "/admin/assets/mayos-logo-white.png?v=" in home.text
    assert home.headers["content-security-policy"] == expected_csp
    assert 'class="brand-link" href="/admin" aria-label="MAYOS owner dashboard" aria-current="page"' in home.text
    assert "The owner dashboard is ready" not in home.text
    assert home.text.count('class="dashboard-card"') == 3
    assert "Review accounts, plans, and activity." in home.text
    assert "Review model usage, limits, and spend." in home.text
    assert "Review owner actions and sign-ins." in home.text
    assert '<div class="admin-nav-links">' in home.text

    accounts = client.get("/admin/accounts")
    assert 'class="nav-link" href="/admin/accounts" aria-current="page">Accounts</a>' in accounts.text
    usage = client.get("/admin/usage")
    assert 'class="nav-link" href="/admin/usage" aria-current="page">Usage</a>' in usage.text
    audit = client.get("/admin/audit")
    assert 'class="nav-link" href="/admin/audit" aria-current="page">Audit log</a>' in audit.text


def test_home_health_panel_matches_readyz_and_shows_healthy_values(admin_api, monkeypatch):
    client, db, now, _ = admin_api
    _prepare_healthy_readiness(monkeypatch)
    _create_snapshot(db, datetime.now(UTC) - timedelta(hours=2))
    db.offsite_backup = object()
    from service.coach_ai import GateStatus

    monkeypatch.setattr(
        "service.coach_ai.resolve_enable_gate",
        lambda: GateStatus(requested=True, enabled=True, reason="flag on and report accepted"),
    )

    ready = client.get("/readyz")
    page = _admin_home(client, now[0])

    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert "System health" in page
    assert "Ready" in _health_row(page, "readiness")
    assert "UTC" in _health_row(page, "backup")
    assert "Configured" in _health_row(page, "offsite")
    assert "On" in _health_row(page, "coach-ai")
    assert all(
        "health-warning" not in _health_row(page, key)
        for key in ("readiness", "backup", "backup-job", "offsite", "alert-sweep", "coach-ai")
    )


def test_not_ready_health_panel_matches_readyz(admin_api):
    client, _, now, _ = admin_api

    ready = client.get("/readyz")
    page = _admin_home(client, now[0])
    readiness_row = _health_row(page, "readiness")

    assert ready.status_code == 503
    assert ready.json()["status"] == "not_ready"
    assert "Not ready" in readiness_row
    assert "health-warning" in readiness_row


def test_missing_backup_is_never_and_highlighted(admin_api):
    client, _, now, _ = admin_api

    page = _admin_home(client, now[0])
    backup_row = _health_row(page, "backup")

    assert "Never" in backup_row
    assert "health-warning" in backup_row
    assert "Not configured" in _health_row(page, "offsite")


@pytest.mark.parametrize(("hours_ago", "highlighted"), [(30, True), (2, False)])
def test_backup_age_controls_warning_highlight(admin_api, hours_ago, highlighted):
    client, db, now, _ = admin_api
    _create_snapshot(db, datetime.now(UTC) - timedelta(hours=hours_ago))

    page = _admin_home(client, now[0])
    backup_row = _health_row(page, "backup")

    assert "UTC" in backup_row
    assert ("health-warning" in backup_row) is highlighted


def test_unrun_job_rows_warn_only_after_two_intervals(admin_api, monkeypatch):
    client, _, now, _ = admin_api
    monkeypatch.setenv("MAYOS_ALERT_SWEEP_INTERVAL_SECONDS", "3600")
    monkeypatch.setenv("MAYOS_DAILY_BACKUP_INTERVAL_SECONDS", "3600")
    monkeypatch.setattr(
        "service.periodic_status.process_started_at",
        lambda: datetime.now(UTC) - timedelta(hours=1),
    )

    page = _admin_home(client, now[0])
    for key in ("alert-sweep", "backup-job"):
        row = _health_row(page, key)
        assert "Not run since restart" in row
        assert "health-warning" not in row

    monkeypatch.setattr(
        "service.periodic_status.process_started_at",
        lambda: datetime.now(UTC) - timedelta(hours=3),
    )
    stale_page = client.get("/admin").text
    for key in ("alert-sweep", "backup-job"):
        assert "health-warning" in _health_row(stale_page, key)


def test_periodic_job_status_uses_run_interval_and_highlights_failures(admin_api, monkeypatch):
    client, _, now, _ = admin_api
    monkeypatch.setenv("MAYOS_DAILY_BACKUP_INTERVAL_SECONDS", "3600")
    record_run(ALERT_SWEEP_JOB, 3600, True, None)
    record_run(DAILY_BACKUP_JOB, 0.01, True, None)
    assert get_periodic_run(ALERT_SWEEP_JOB).ok is True
    assert get_periodic_run(DAILY_BACKUP_JOB).interval_seconds == 0.01

    time.sleep(0.03)
    _admin_home(client, now[0])
    page = client.get("/admin").text
    assert "ok" in _health_row(page, "alert-sweep")
    assert "health-warning" not in _health_row(page, "alert-sweep")
    assert "health-warning" in _health_row(page, "backup-job")
    assert configured_interval_seconds(DAILY_BACKUP_JOB) == 3600

    record_run(ALERT_SWEEP_JOB, 3600, False, "RuntimeError")
    failed_sweep = _health_row(client.get("/admin").text, "alert-sweep")
    assert "RuntimeError" in failed_sweep
    assert "health-warning" in failed_sweep

    record_run(DAILY_BACKUP_JOB, 3600, False, "OSError")
    failed_backup = _health_row(client.get("/admin").text, "backup-job")
    assert "OSError" in failed_backup
    assert "health-warning" in failed_backup


def test_coach_ai_off_reason_is_shown(admin_api, monkeypatch):
    client, _, now, _ = admin_api
    from service.coach_ai import GateStatus

    gate = [GateStatus(requested=True, enabled=True, reason="flag on and report accepted")]
    monkeypatch.setattr("service.coach_ai.resolve_enable_gate", lambda: gate[0])
    _admin_home(client, now[0])
    assert "On" in _health_row(client.get("/admin").text, "coach-ai")

    gate[0] = GateStatus(requested=True, enabled=False, reason="evaluation report is missing")
    off_row = _health_row(client.get("/admin").text, "coach-ai")
    assert "Off" in off_row
    assert "evaluation report is missing" in off_row


def test_backup_source_error_renders_unknown_without_failing_the_page(admin_api, monkeypatch):
    client, _, now, _ = admin_api
    _admin_home(client, now[0])

    def fail_backup_listing(_):
        raise OSError("private path details")

    monkeypatch.setattr("database.backup.list_daily_backups", fail_backup_listing)
    page = client.get("/admin")
    assert page.status_code == 200
    unknown_backup = _health_row(page.text, "backup")
    assert "Unknown" in unknown_backup
    assert "OSError" in unknown_backup
    assert "private path details" not in page.text


def test_every_protected_path_is_the_same_404_before_login(admin_api):
    client, _, _, _ = admin_api
    home = client.get("/admin")
    audit = client.get("/admin/audit")
    unknown = client.get("/admin/accounts")
    assert home.status_code == audit.status_code == unknown.status_code == 404
    assert home.text == audit.text == unknown.text
    assert "System health" not in home.text
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
    assert "path=/admin" in cookie and "max-age=43200" in cookie
    home = client.get("/admin")
    assert home.status_code == 200
    assert 'href="/admin/accounts"' in home.text
    now[0] += 2 * 60 * 60 + 1
    assert client.get("/admin").status_code == 404


def test_admin_session_expires_at_absolute_limit_even_when_active(admin_api):
    client, _, now, _ = admin_api
    assert _login(client, now[0]).status_code == 303
    for _ in range(26):
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
    for response in (
        before_login,
        login_page,
        login,
        client.get("/admin"),
        client.get("/admin/usage"),
        client.get("/admin/audit"),
    ):
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'name="robots" content="noindex"' in client.get("/admin").text


def test_totp_verifies_rfc_6238_sha1_vector():
    from service.admin_auth import verify_totp_code

    assert verify_totp_code(b"12345678901234567890", "287082", 59) == 1


def test_client_ip_is_normalized(monkeypatch):
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


def _register_account(client, db, username):
    limiter.reset()
    response = client.post(
        "/auth/register",
        json={"trainee_id": username, "password": "correct-horse-1"},
    )
    assert response.status_code == 201, response.text
    account = db.get_active_account_by_username(username)
    assert account is not None
    return account, {"Authorization": f"Bearer {response.json()['access_token']}"}


def _accounts_page(client, now, **params):
    assert _login(client, now).status_code == 303
    return client.get("/admin/accounts", params=params)


def test_account_pages_are_404_before_admin_login(admin_api):
    client, _, now, _ = admin_api
    pages = [client.get("/admin/accounts"), client.get("/admin/accounts/invalid")]
    assert [page.status_code for page in pages] == [404, 404]
    assert pages[0].text == pages[1].text
    lookup = client.post("/admin/accounts/email", data={"csrf_token": "invalid", "email": "person@example.com"})
    logout = client.post("/admin/logout", data={"csrf_token": "invalid"})
    assert lookup.status_code == logout.status_code == 404
    assert _login(client, now[0]).status_code == 303
    malformed = client.get("/admin/accounts/invalid")
    unknown = client.get(f"/admin/accounts/{'f' * 32}")
    assert malformed.status_code == unknown.status_code == 404
    assert malformed.text == unknown.text


def test_account_search_matches_live_usernames_case_insensitively(admin_api):
    client, db, now, _ = admin_api
    matching, _ = _register_account(client, db, "AliceStrong")
    other, _ = _register_account(client, db, "bobstrong")

    response = _accounts_page(client, now[0], q="iCeSt")

    assert response.status_code == 200
    assert matching["account_id"] in response.text
    assert other["account_id"] not in response.text


def test_recovery_email_lookup_is_exact_masked_and_audited_without_email(admin_api):
    client, db, now, _ = admin_api
    account, _ = _register_account(client, db, "emailowner")
    db.set_account_email(account["account_id"], "alice@example.com")
    page = _accounts_page(client, now[0])
    csrf = _csrf(page.text)
    bad_csrf = client.post(
        "/admin/accounts/email",
        data={"csrf_token": "wrong-token", "email": "alice@example.com"},
    )
    assert bad_csrf.status_code == 403

    found = client.post(
        "/admin/accounts/email",
        data={"csrf_token": csrf, "email": " ALICE@EXAMPLE.COM "},
        headers={"Fly-Client-IP": "203.0.113.9"},
        follow_redirects=False,
    )
    assert found.status_code == 303
    assert found.headers["location"] == f"/admin/accounts/{account['account_id']}"
    detail = client.get(found.headers["location"])
    assert "a***@example.com" in detail.text
    assert "alice@example.com" not in detail.text

    csrf = _csrf(detail.text)
    partial = client.post(
        "/admin/accounts/email",
        data={"csrf_token": csrf, "email": "alice@exa"},
        headers={"Fly-Client-IP": "203.0.113.9"},
        follow_redirects=False,
    )
    assert partial.status_code == 303
    assert partial.headers["location"] == "/admin/accounts?lookup=not_found"
    no_match = client.get(partial.headers["location"])
    assert "alice@exa" not in no_match.text
    assert "No account found for that recovery email" in no_match.text

    audit = client.get("/admin/audit?action=account_lookup_by_email")
    assert audit.status_code == 200
    assert audit.text.count("<strong>Action:</strong> account_lookup_by_email") == 2
    assert f"Account id:</strong> {account['account_id']}" in audit.text
    assert audit.text.count("<strong>Account id:</strong>") == 1
    assert "203.0.113.9" in audit.text
    assert "alice@example.com" not in audit.text


def test_account_list_filters_coach_not_onboarded_inactive_and_deleted(admin_api):
    client, db, now, _ = admin_api
    coach, _ = _register_account(client, db, "coachfilter")
    onboarded, _ = _register_account(client, db, "onboardedfilter")
    never_seen, _ = _register_account(client, db, "neverseen")
    never_active, _ = _register_account(client, db, "neveractive")
    older, _ = _register_account(client, db, "inactiveold")
    recent, _ = _register_account(client, db, "inactiverecent")
    with db.open_ledger(onboarded["ledger_id"]) as ledger:
        ledger.upsert_player_profile({"current_goal": "PROFILE_MUST_NOT_BE_SHOWN"})

    today = datetime.now(UTC).date()
    with db.catalog_locked() as conn:
        conn.execute("UPDATE accounts SET is_coach = 1 WHERE account_id = ?", (coach["account_id"],))
        conn.execute(
            "UPDATE accounts SET last_seen_at = ? WHERE account_id = ?",
            ((today - timedelta(days=10)).isoformat(), older["account_id"]),
        )
        conn.execute(
            "UPDATE accounts SET last_seen_at = ? WHERE account_id = ?",
            ((today - timedelta(days=2)).isoformat(), recent["account_id"]),
        )
        conn.execute(
            "UPDATE accounts SET status = 'deleted', deleted_at = ? WHERE account_id = ?",
            ("2026-09-01T12:00:00+00:00", never_seen["account_id"]),
        )
        conn.commit()

    coach_page = _accounts_page(client, now[0], coach="1")
    assert coach["account_id"] in coach_page.text
    assert onboarded["account_id"] not in coach_page.text

    not_onboarded_page = client.get("/admin/accounts", params={"not_onboarded": "1"})
    assert not_onboarded_page.status_code == 200
    assert coach["account_id"] in not_onboarded_page.text
    assert onboarded["account_id"] not in not_onboarded_page.text
    assert "PROFILE_MUST_NOT_BE_SHOWN" not in not_onboarded_page.text

    inactive_page = client.get("/admin/accounts", params={"inactive_days": "7"})
    assert older["account_id"] in inactive_page.text
    assert recent["account_id"] not in inactive_page.text
    assert never_seen["account_id"] not in inactive_page.text
    assert never_active["account_id"] in inactive_page.text

    deleted_page = client.get(
        "/admin/accounts",
        params={
            "show_deleted": "1",
            "q": "no-match",
            "coach": "1",
            "not_onboarded": "1",
            "inactive_days": "7",
        },
    )
    assert deleted_page.status_code == 200
    assert "do not apply to deleted accounts" in deleted_page.text
    assert never_seen["account_id"] in deleted_page.text
    assert "neverseen" in deleted_page.text
    assert "2026-09-01T12:00:00+00:00" in deleted_page.text
    assert coach["account_id"] not in deleted_page.text
    assert 'href="/admin/accounts/' not in deleted_page.text

    deleted_detail = client.get(f"/admin/accounts/{never_seen['account_id']}")
    assert deleted_detail.status_code == 200
    assert "neverseen" in deleted_detail.text
    assert "2026-09-01T12:00:00+00:00" in deleted_detail.text
    for forbidden in ("Capabilities", "Recovery email", "Model usage", "Onboarded", "last_seen_at"):
        assert forbidden not in deleted_detail.text


def test_account_page_shows_metadata_usage_limits_and_never_training_content(admin_api):
    client, db, now, _ = admin_api
    account, _ = _register_account(client, db, "detailowner")
    player, _ = _register_account(client, db, "assignedplayer")
    other_coach, _ = _register_account(client, db, "othercoach")
    db.set_account_email(account["account_id"], "a@sample.test")
    db.set_plan(account["account_id"], "lifter", "pro")
    with db.catalog_locked() as conn:
        conn.execute("UPDATE accounts SET is_coach = 1 WHERE account_id = ?", (account["account_id"],))
        conn.execute("UPDATE accounts SET is_coach = 1 WHERE account_id = ?", (other_coach["account_id"],))
        conn.execute(
            "INSERT INTO assignments (assignment_id, coach_account_id, player_account_id, status, started_at)"
            " VALUES ('assign-coach', ?, ?, 'active', '2026-09-01T00:00:00+00:00')",
            (account["account_id"], player["account_id"]),
        )
        conn.execute(
            "INSERT INTO assignments (assignment_id, coach_account_id, player_account_id, status, started_at)"
            " VALUES ('assign-player', ?, ?, 'active', '2026-09-01T00:00:00+00:00')",
            (other_coach["account_id"], account["account_id"]),
        )
        conn.commit()

    db.record_model_usage(
        account["account_id"], "player", "model-x", 100, 20, 0.12, False,
        created_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    )
    db.record_model_usage(
        account["account_id"], "coach", "model-y", 50, 30, 0.08, True,
        created_at="2024-01-01T00:00:00+00:00",
    )
    db.record_model_limit_hit(account["account_id"], "rate", created_at=datetime.now(UTC).isoformat())
    db.record_model_limit_hit(account["account_id"], "daily_tokens", created_at=datetime.now(UTC).isoformat())
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.upsert_player_profile({"current_goal": "PRIVATE_PROFILE_SENTINEL"})
        ledger.conn.execute(
            "INSERT INTO workout_sessions (id, session_date, split_name, started_at, session_notes)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                "private-session",
                "2026-09-01",
                "PRIVATE_WORKOUT_SENTINEL",
                "2026-09-01T10:00:00+00:00",
                "PRIVATE_NOTE_SENTINEL",
            ),
        )
        ledger.conn.commit()

    assert _login(client, now[0]).status_code == 303
    response = client.get(f"/admin/accounts/{account['account_id']}")

    assert response.status_code == 200
    for expected in (
        "detailowner",
        account["account_id"],
        "Capabilities",
        "Player",
        "Coach",
        "Pro",
        "Coach: Free",
        "Onboarded",
        "Yes",
        "Coach of 1 active player",
        "Has an active coach",
        "*@sample.test",
        "This UTC month",
        "All time",
        "2 calls",
        "150",
        "120",
        "$0.12",
        "$0.20",
        "Daily token cap hits: 1",
        "Rate limit hits: 1",
    ):
        assert expected in response.text
    for forbidden in ("PRIVATE_PROFILE_SENTINEL", "PRIVATE_WORKOUT_SENTINEL", "PRIVATE_NOTE_SENTINEL"):
        assert forbidden not in response.text
    missing_email = client.get(f"/admin/accounts/{other_coach['account_id']}")
    assert "Not set" in missing_email.text


def test_accounts_pages_paginate_at_fifty_rows(admin_api):
    client, db, now, _ = admin_api
    accounts = [db.create_account(f"pageuser{number:02d}") for number in range(51)]
    assert all(accounts)
    first = _accounts_page(client, now[0])
    second = client.get("/admin/accounts", params={"page": "2"})
    assert first.status_code == second.status_code == 200
    assert "Page 1 of 2" in first.text
    assert "Page 2 of 2" in second.text
    assert first.text.count("<li>") == 50
    assert second.text.count("<li>") == 1


def test_authenticated_activity_updates_last_seen_once_per_utc_day(admin_api, monkeypatch):
    from svc import dependencies

    client, db, _, _ = admin_api
    account, headers = _register_account(client, db, "lastseen")
    day = ["2026-09-30"]
    db.catalog_conn.executescript(
        "CREATE TABLE last_seen_writes (account_id TEXT, seen_day TEXT);"
        "CREATE TRIGGER observe_last_seen_write AFTER UPDATE OF last_seen_at ON accounts "
        "BEGIN INSERT INTO last_seen_writes VALUES (NEW.account_id, NEW.last_seen_at); END;"
    )
    monkeypatch.setattr(dependencies, "_utc_day", lambda: day[0])
    assert client.get("/auth/me", headers=headers).status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 200
    writes = db.catalog_conn.execute("SELECT account_id, seen_day FROM last_seen_writes").fetchall()
    assert writes == [(account["account_id"], "2026-09-30")]
    assert db.get_account(account["account_id"])["last_seen_at"] == "2026-09-30"

    day[0] = "2026-10-01"
    assert client.get("/auth/me", headers=headers).status_code == 200
    writes = db.catalog_conn.execute("SELECT account_id, seen_day FROM last_seen_writes ORDER BY rowid").fetchall()
    assert writes == [
        (account["account_id"], "2026-09-30"),
        (account["account_id"], "2026-10-01"),
    ]
    assert set(dependencies._last_seen_retry_after_by_account) == {account["account_id"]}


def test_last_seen_write_failure_does_not_fail_authenticated_request(admin_api, monkeypatch):
    from svc import dependencies

    client, db, _, _ = admin_api
    _, headers = _register_account(client, db, "lastseenfailure")
    monkeypatch.setattr(dependencies, "_utc_day", lambda: "2026-09-30")

    attempts = []

    def fail_write(*args):
        attempts.append(args)
        raise OSError("catalog unavailable")

    monkeypatch.setattr(db, "set_account_last_seen_at", fail_write)
    response = client.get("/auth/me", headers=headers)
    repeated = client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    assert repeated.status_code == 200
    assert len(attempts) == 1


def test_last_seen_catalog_write_does_not_hold_process_lock(monkeypatch):
    from svc import dependencies

    started = threading.Event()
    release = threading.Event()
    second_done = threading.Event()

    class BlockingStore:
        def set_account_last_seen_at(self, account_id, seen_day):
            if account_id == "slow":
                started.set()
                assert release.wait(5)
            else:
                second_done.set()

    monkeypatch.setattr(dependencies, "_utc_day", lambda: "2099-01-01")
    store = BlockingStore()
    first = threading.Thread(target=dependencies._record_last_seen, args=(store, "slow"))
    second = threading.Thread(target=dependencies._record_last_seen, args=(store, "fast"))
    first.start()
    assert started.wait(2)
    second.start()
    second_finished_while_first_blocked = second_done.wait(1)
    release.set()
    first.join(5)
    second.join(5)

    assert second_finished_while_first_blocked
    assert not first.is_alive() and not second.is_alive()


def test_failed_last_seen_write_waits_for_retry_backoff(monkeypatch):
    from svc import dependencies

    now = [100.0]
    attempts = []

    class FailingStore:
        def set_account_last_seen_at(self, account_id, seen_day):
            attempts.append((account_id, seen_day))
            raise OSError("catalog unavailable")

    monkeypatch.setattr(dependencies, "_utc_day", lambda: "2099-01-02")
    monkeypatch.setattr(dependencies, "_monotonic", lambda: now[0])
    store = FailingStore()
    dependencies._record_last_seen(store, "backoff")
    dependencies._record_last_seen(store, "backoff")
    assert len(attempts) == 1

    now[0] += dependencies._LAST_SEEN_RETRY_BACKOFF_SECONDS
    dependencies._record_last_seen(store, "backoff")
    assert len(attempts) == 2


def test_existing_catalog_gets_nullable_last_seen_column(tmp_path):
    catalog_path = tmp_path / "legacy-catalog.db"
    connection = sqlite3.connect(catalog_path)
    connection.execute(
        "CREATE TABLE accounts (account_id TEXT PRIMARY KEY, username TEXT NOT NULL, ledger_id TEXT NOT NULL,"
        " status TEXT NOT NULL DEFAULT 'active', is_player INTEGER NOT NULL DEFAULT 1,"
        " is_coach INTEGER NOT NULL DEFAULT 0, session_epoch INTEGER NOT NULL DEFAULT 1,"
        " created_at TEXT NOT NULL, deleted_at TEXT)"
    )
    connection.execute(
        "INSERT INTO accounts (account_id, username, ledger_id, created_at) VALUES (?, ?, ?, ?)",
        ("legacy-account", "legacy", "legacy", "2026-01-01T00:00:00+00:00"),
    )
    connection.commit()
    connection.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
    )
    try:
        assert db.get_account("legacy-account")["last_seen_at"] is None
    finally:
        db.catalog_conn.close()


def test_usage_page_requires_login_and_shows_empty_catalog_state(admin_api, monkeypatch):
    client, _, now, _ = admin_api
    from svc.routers import admin as admin_router

    fixed_now = datetime(2026, 9, 15, 12, tzinfo=UTC)
    monkeypatch.setattr(admin_router, "_utc_now", lambda: fixed_now)
    assert client.get("/admin/usage").status_code == 404
    assert _login(client, now[0]).status_code == 303

    page = client.get("/admin/usage")

    assert page.status_code == 200
    assert "No usage recorded yet" in page.text
    assert 'data-period="today"' in page.text
    assert 'data-period="this-month"' in page.text
    assert 'data-period="last-month"' in page.text
    assert "Monthly alert: Not fired" in page.text
    assert "No limit hits recorded this month." in page.text
    assert "No account usage recorded this month." in page.text
    assert "<meter" in page.text
    assert "style=" not in page.text and "<script" not in page.text


def _seed_ranked_usage_rows(db, account_ids, created_at):
    for index, account_id in enumerate(account_ids):
        db.record_model_usage(
            account_id=account_id,
            role=("player", "coach", "judge")[index % 3],
            purpose="admin usage test",
            model=f"model-{index % 2}",
            input_tokens=1000,
            output_tokens=500,
            estimated=False,
            cost_usd=float(21 - index),
            created_at=created_at,
        )


def _seed_estimated_usage_row(db, account_id, created_at):
    db.record_model_usage(
        account_id=account_id,
        role="judge",
        purpose="admin usage test",
        model="estimated-model",
        input_tokens=1500,
        output_tokens=700,
        estimated=True,
        cost_usd=0.25,
        created_at=created_at,
    )


def _seed_unattributed_usage_row(db, created_at):
    db.record_model_usage(
        account_id=None,
        role="judge",
        purpose="unattributed test",
        model="unattributed-model",
        input_tokens=300,
        output_tokens=100,
        estimated=True,
        cost_usd=0.5,
        created_at=created_at,
    )


def _seed_previous_month_usage_row(db, account_id, month_start):
    db.record_model_usage(
        account_id=account_id,
        role="coach",
        purpose="admin usage test",
        model="last-month-model",
        input_tokens=250,
        output_tokens=125,
        estimated=False,
        cost_usd=1.25,
        created_at=(month_start + timedelta(days=1)).isoformat(),
    )


def _seed_limit_hits(db, account_ids, created_at):
    for kind in ("daily_tokens", "daily_tokens", "rate"):
        db.record_model_limit_hit(account_ids[0], kind, created_at)
    for _ in range(2):
        db.record_model_limit_hit(account_ids[2], "rate", created_at)
    db.record_model_limit_hit(account_ids[3], "daily_tokens", created_at)
    for _ in range(2):
        db.record_model_limit_hit("orphan-limit-hit-account", "rate", created_at)


def _delete_usage_account(db, account_id, deleted_at):
    account = db.get_account(account_id)
    assert account
    return db.delete_account(account_id, deleted_at, ledger_id=account["ledger_id"])


def _seed_usage_dashboard(db, moment):
    from service import model_metering

    month_start, _ = model_metering.month_bounds(moment)
    prior_month_start, _ = model_metering.month_bounds(month_start - timedelta(microseconds=1))
    account_ids = [db.create_account(f"usageuser{index:02d}") for index in range(21)]
    assert all(account_ids)
    current_at = moment.isoformat()
    _seed_ranked_usage_rows(db, account_ids, current_at)
    _seed_estimated_usage_row(db, account_ids[0], current_at)
    _seed_unattributed_usage_row(db, current_at)
    _seed_previous_month_usage_row(db, account_ids[0], prior_month_start)
    _seed_limit_hits(db, account_ids, current_at)
    _delete_usage_account(db, account_ids[2], current_at)
    db.catalog_conn.execute("UPDATE accounts SET status = 'disabled' WHERE account_id = ?", (account_ids[3],))
    db.catalog_conn.commit()
    return moment, account_ids


def _usage_period_html(page, period):
    match = re.search(rf'<section class="health-panel usage-panel" data-period="{period}">(.*?)</section>', page, re.S)
    assert match
    return match.group(1)


def _usage_metric_value(page, period, metric):
    markup = _usage_period_html(page, period)
    match = re.search(rf'<div data-metric="{metric}"><dt>.*?</dt><dd>(.*?)</dd>', markup)
    assert match
    return match.group(1)


def _assert_usage_period_totals(page):
    for period in ("today", "this-month"):
        assert _usage_metric_value(page, period, "calls") == "23"
        assert _usage_metric_value(page, period, "input-tokens") == "22,800"
        assert _usage_metric_value(page, period, "output-tokens") == "11,300"
        assert _usage_metric_value(page, period, "cost") == "$231.75"
    assert _usage_metric_value(page, "last-month", "calls") == "1"
    assert _usage_metric_value(page, "last-month", "input-tokens") == "250"
    assert _usage_metric_value(page, "last-month", "output-tokens") == "125"
    assert _usage_metric_value(page, "last-month", "cost") == "$1.25"


def _assert_usage_breakdowns(page):
    today = _usage_period_html(page, "today")
    assert "model-0" in today and "model-1" in today
    assert "last-month-model" not in today
    assert "<td>judge</td><td>9</td>" in today
    assert "estimated-model" in today and "Estimated tokens" in today
    assert "Unattributed usage" in today and "unattributed-model" in today


def _assert_usage_top_accounts(page, account_ids):
    top = re.search(r'<section class="health-panel usage-panel" data-top-accounts>(.*?)</section>', page, re.S)
    assert top
    ranked_ids = re.findall(r'href="/admin/accounts/([0-9a-f]{32})"', top.group(1))
    assert ranked_ids == account_ids[:20]
    assert f'<a href="/admin/accounts/{account_ids[0]}">usageuser00</a>' in top.group(1)
    assert f'<a href="/admin/accounts/{account_ids[2]}">Deleted account</a>' in top.group(1)
    assert account_ids[20] not in ranked_ids


def _assert_usage_limit_hits(page, account_ids):
    limits = re.search(r'<section class="health-panel usage-panel" data-limit-hits>(.*?)</section>', page, re.S)
    assert limits
    hit_account_ids = re.findall(r'href="/admin/accounts/([^"]+)"', limits.group(1))
    assert hit_account_ids == [account_ids[0], account_ids[2], "orphan-limit-hit-account", account_ids[3]]
    assert f'<a href="/admin/accounts/{account_ids[2]}">Deleted account</a>' in limits.group(1)
    assert f'<a href="/admin/accounts/{account_ids[3]}">Deleted account</a>' in limits.group(1)
    assert '<a href="/admin/accounts/orphan-limit-hit-account">Deleted account</a>' in limits.group(1)


def _assert_usage_spend_alert(page):
    assert "Fired and notified at" in page
    assert 'max="50.00" value="50.00"' in page
    assert "Actual: $231.75" in page


def _freeze_metering_clock(monkeypatch, moment):
    from service import model_metering

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

    monkeypatch.setattr(model_metering, "datetime", FrozenDateTime)


def _usage_breakdown_rows(page, period, breakdown):
    markup = _usage_period_html(page, period)
    table = re.search(rf'<table class="usage-table" data-breakdown="{breakdown}">(.*?)</table>', markup, re.S)
    assert table
    rows = re.findall(r"<tr>(.*?)</tr>", table.group(1), re.S)[1:]
    return [
        [html.unescape(re.sub(r"<[^>]*>", "", cell)).strip() for cell in re.findall(r"<td>(.*?)</td>", row, re.S)]
        for row in rows
    ]


def _cli_breakdown_rows(report, dimensions):
    groups = {}
    for row in report["rows"]:
        if dimensions == ("role", "model") and row["account_id"] is not None:
            continue
        key = tuple(row[dimension] for dimension in dimensions)
        totals = groups.setdefault(key, {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "estimated_calls": 0})
        for field in totals:
            totals[field] += row[field]
    result = []
    for key in sorted(groups):
        totals = groups[key]
        estimate = "—"
        if totals["estimated_calls"]:
            calls = totals["estimated_calls"]
            estimate = f"Estimated tokens · {calls:,} {'call' if calls == 1 else 'calls'}"
        result.append(
            [
                *key,
                f"{totals['requests']:,}",
                f"{totals['input_tokens']:,}",
                f"{totals['output_tokens']:,}",
                f"${totals['cost_usd']:,.2f}",
                estimate,
            ]
        )
    return result


def _assert_cli_usage_parity(db, page, capsys, monkeypatch, moment):
    from scripts import model_usage_report

    _freeze_metering_clock(monkeypatch, moment)
    assert model_usage_report.main(["--catalog", str(db.catalog_path), "--json"]) == 0
    cli_report = json.loads(capsys.readouterr().out)
    assert _usage_metric_value(page, "this-month", "calls") == f'{cli_report["total_requests"]:,}'
    assert _usage_metric_value(page, "this-month", "input-tokens") == f'{cli_report["total_input_tokens"]:,}'
    assert _usage_metric_value(page, "this-month", "output-tokens") == f'{cli_report["total_output_tokens"]:,}'
    assert _usage_metric_value(page, "this-month", "cost") == f'${cli_report["total_cost_usd"]:,.2f}'
    assert _usage_breakdown_rows(page, "this-month", "model") == _cli_breakdown_rows(cli_report, ("model",))
    assert _usage_breakdown_rows(page, "this-month", "role") == _cli_breakdown_rows(cli_report, ("role",))
    assert _usage_breakdown_rows(page, "this-month", "unattributed") == _cli_breakdown_rows(
        cli_report, ("role", "model")
    )
    unattributed = _usage_breakdown_rows(page, "this-month", "unattributed")
    assert ["judge", "unattributed-model", "1", "300", "100", "$0.50", "Estimated tokens · 1 call"] in unattributed
    assert page.count('data-spend-alert') == 1
    spend_panel = re.search(r'<section class="health-panel usage-panel" data-spend-alert ([^>]*)>', page)
    assert spend_panel
    assert f'data-actual-usd="{cli_report["mtd_actual_usd"]:.2f}"' in spend_panel.group(1)
    assert f'data-projected-usd="{cli_report["mtd_projected_usd"]:.2f}"' in spend_panel.group(1)
    cli_alert = cli_report["alert"]
    assert f'data-alert-fired="{str(bool(cli_alert and cli_alert.get("fired_at"))).lower()}"' in spend_panel.group(1)
    assert f'data-alert-notified="{str(bool(cli_alert and cli_alert.get("notified_at"))).lower()}"' in spend_panel.group(1)


def test_usage_page_reports_periods_accounts_limits_alert_and_cli_totals(admin_api, monkeypatch, capsys):
    from service import model_metering
    from svc.routers import admin as admin_router

    client, db, now, _ = admin_api
    assert _login(client, now[0]).status_code == 303
    moment = datetime(2026, 9, 15, 12, tzinfo=UTC)
    monkeypatch.setattr(admin_router, "_utc_now", lambda: moment)
    moment, account_ids = _seed_usage_dashboard(db, moment)
    monkeypatch.setenv("MODEL_SPEND_ALERT_USD", "50")
    alert = model_metering.evaluate_spend_alert(db, now=moment)
    assert alert["fired"] is True and alert["notified"] is True
    page = client.get("/admin/usage")

    assert page.status_code == 200
    _assert_usage_period_totals(page.text)
    _assert_usage_breakdowns(page.text)
    _assert_usage_top_accounts(page.text, account_ids)
    _assert_usage_limit_hits(page.text, account_ids)
    assert "Daily token cap: 3 · Rate limit: 5" in page.text
    _assert_usage_spend_alert(page.text)
    assert not re.search(r'href="[^"]+\.csv', page.text)
    assert "style=" not in page.text and "<script" not in page.text
    _assert_cli_usage_parity(db, page.text, capsys, monkeypatch, moment)
