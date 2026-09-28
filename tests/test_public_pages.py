"""Public pages: privacy policy and the external deletion request (#43, ADR 046).

Exercises the unauthenticated HTML surface against a real temporary catalog:
the policy is served without auth, is cacheable, discloses what the code does,
and degrades to a placeholder contact when ``PRIVACY_CONTACT_EMAIL`` is unset;
the web deletion form runs the same password-confirmed deletion as the in-app
path, answers identically for unknown usernames and wrong passwords, and is
rate-limited with the password budget.
"""

import html
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from database.database_manager import DatabaseManager
from service import account_deletion as deletion_service
from service.privacy_policy import (
    POLICY_EFFECTIVE_DATE,
    POLICY_PATH,
    POLICY_VERSION,
    clear_policy_cache,
    contact_html,
    render_markdown,
)
from svc.app import create_app
from svc.dependencies import get_db
from svc.rate_limit import PASSWORD_LIMIT, _key, limiter
from svc.routers.public_pages import GENERIC_FAILURE_MESSAGE, SUCCESS_MESSAGE, UNCONFIRMED_MESSAGE

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.delenv("PRIVACY_CONTACT_EMAIL", raising=False)
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    limiter._storage.reset()
    clear_policy_cache()
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.commit()
    cat_conn.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(client: TestClient, username: str = "alice", password: str = "correct-horse-1") -> dict:
    response = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert response.status_code == 201, response.text
    return response.json()


def _delete_form(client: TestClient, username: str, password: str, confirm: bool = True):
    data = {"username": username, "password": password}
    if confirm:
        data["confirm"] = "yes"
    return client.post("/account/delete-request", data=data)


# --------------------------------------------------------------------------
# GET /privacy
# --------------------------------------------------------------------------


def test_privacy_page_is_public_and_cacheable(api):
    client, _db = api
    response = client.get("/privacy")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "public, max-age=3600"
    assert "MAYOS Privacy Policy" in response.text
    assert f"Effective date: {POLICY_EFFECTIVE_DATE}" in response.text
    assert f"Policy version {POLICY_VERSION}" in response.text


def test_privacy_page_discloses_coach_access_hosted_ai_and_retention(api):
    client, _db = api
    body = client.get("/privacy").text
    # Coach access: mutual consent, what a coach sees, and revocation.
    assert "you explicitly accept" in body
    assert "assistant chat is private" in body
    assert "Ending the assignment" in body
    # Hosted AI: features, and the free-text identifier warning.
    assert "hosted, OpenAI-compatible model provider" in body
    assert "Free text you type can contain identifying information" in body
    assert "never receives your assistant chat" in body
    # Retention: live data, the 30-day restricted snapshot, the deletion record.
    assert "at most **30 days**" not in body  # emphasis is rendered, not literal
    assert "30 days" in body
    assert "deletion record" in body
    # Deletion is offered in-app and at the external URL.
    assert 'href="/account/delete-request"' in body
    assert "Settings &rarr; Profile &rarr; Delete account" in body or "Settings → Profile → Delete account" in body
    # Analytics honesty: none are sent today.
    assert "does not send product analytics in this release" in body
    # Imported history (ADR 045) is disclosed where the collection is listed.
    assert "Imported history, only if you opt in" in body
    # Coach-visible fields from the coach history/roster schemas.
    assert "time zone" in body
    assert "performed-date corrections" in body
    assert "expected training weekdays" in body
    # Emails: the coach is emailed about a player's request; the player is
    # never emailed a coaching reply.
    assert "notice to your coach" in body
    assert "requested a program change" in body
    assert "do not email you about check-ins" in body
    # Program generation sends only split planning, and says exactly that.
    assert "weekly training frequency" in body
    assert "gender context" in body
    # Children: the repo states no age floor, so the page must say so plainly.
    assert "not directed at children under 16" in body


def test_privacy_contact_placeholder_and_warning_once_when_env_unset(api, caplog):
    client, _db = api
    with caplog.at_level("WARNING", logger="service.privacy_policy"):
        body = client.get("/privacy").text
        first = [r for r in caplog.records if "PRIVACY_CONTACT_EMAIL is not set" in r.message]
        caplog.clear()
        client.get("/privacy")
        second = [r for r in caplog.records if "PRIVACY_CONTACT_EMAIL is not set" in r.message]
    assert "PRIVACY_CONTACT_EMAIL is unset" in body
    assert "mailto:" not in body
    assert len(first) == 1
    # The body is cached, so a crawl logs the warning once, not per request.
    assert second == []


def test_privacy_contact_uses_env_when_configured(api, monkeypatch):
    client, _db = api
    monkeypatch.setenv("PRIVACY_CONTACT_EMAIL", "owner@example.com")
    assert 'href="mailto:owner@example.com"' in client.get("/privacy").text
    assert "owner@example.com" in contact_html()


def test_privacy_page_style_is_hash_scoped(api):
    """The publicly cacheable page uses a style hash, not a per-response nonce.

    A nonce would be minted per response while the cached copy outlives it, so
    the CSP source must be a stable hash of the static CSS instead.
    """
    client, _db = api
    response = client.get("/privacy")
    csp = response.headers["content-security-policy"]
    assert "style-src 'sha256-" in csp
    assert "nonce" not in csp
    assert "default-src 'none'" in csp
    # The chrome has no dead links: there is no / route.
    assert 'href="/"' not in response.text


def test_policy_source_file_exists_and_every_section_is_served(api):
    """``docs/PRIVACY_POLICY.md`` ships in the image and drives the page.

    The Fly image is built with ``COPY . .`` and does not dockerignore
    ``docs/``, so the Markdown master copy is present next to the code; this
    pins both halves of that contract — the file exists, and every section it
    declares is what ``GET /privacy`` renders.
    """
    client, _db = api
    assert POLICY_PATH.is_file(), f"privacy policy source is missing: {POLICY_PATH}"

    source = POLICY_PATH.read_text(encoding="utf-8")
    headings = [
        line.lstrip("#").strip()
        for line in source.splitlines()
        if line.startswith("## ") or line.startswith("### ")
    ]
    assert headings, "the policy declares no sections"

    body = client.get("/privacy").text
    for heading in headings:
        assert html.escape(heading) in body, f"section not served: {heading!r}"

    # The required disclosures live in the source file itself, so editing the
    # file (not the renderer) is what changes the published policy. Compared
    # with whitespace and emphasis markers normalised away, because the prose
    # wraps across lines and bolds its lead-ins.
    flat = " ".join(source.split()).replace("**", "")
    for phrase in (
        "assignment you explicitly accept",
        "Free text you type can contain identifying information",
        "at most 30 days",
        "/account/delete-request",
        "Imported history, only if you opt in",
    ):
        assert phrase in flat, f"missing from {POLICY_PATH.name}: {phrase!r}"


# --------------------------------------------------------------------------
# GET /account/delete-request (form)
# --------------------------------------------------------------------------


def test_delete_request_form_renders_without_a_session(api):
    client, _db = api
    response = client.get("/account/delete-request")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert 'method="post"' in response.text
    assert 'name="username"' in response.text
    assert 'name="password"' in response.text
    assert 'name="confirm"' in response.text
    assert 'type="checkbox"' in response.text
    # Lost-password guidance and the privacy policy link are on the page.
    assert "Forgot password" in response.text
    assert 'href="/privacy"' in response.text
    assert "form-action 'self'" in response.headers["content-security-policy"]


def test_delete_request_form_is_nonce_scoped_and_states_what_is_kept(api):
    client, _db = api
    body = client.get("/account/delete-request").text
    # One privacy link, no inline style the nonce CSP would block, no dead /.
    assert body.count('href="/privacy"') == 1
    assert 'style="' not in body
    assert 'href="/"' not in body
    # The page that deletes says what survives the deletion, matching the policy.
    assert "What is kept" in body
    assert "deletion record" in body
    assert "model-usage rows keyed only by an opaque id" in body
    assert "<strong>30 days</strong>" in body


# --------------------------------------------------------------------------
# POST /account/delete-request
# --------------------------------------------------------------------------


def test_delete_request_success_deletes_the_account(api):
    client, db = api
    _register(client, "alice")
    assert db.get_active_account_by_username("alice") is not None

    response = _delete_form(client, "alice", "correct-horse-1")
    assert response.status_code == 200
    assert html.escape(SUCCESS_MESSAGE) in response.text
    assert db.get_active_account_by_username("alice") is None
    # The in-app session path sees the same deletion.
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 401


def test_delete_request_wrong_password_and_unknown_username_are_identical(api):
    client, db = api
    _register(client, "alice")

    wrong = _delete_form(client, "alice", "not-the-password")
    unknown = _delete_form(client, "nobody-here", "correct-horse-1")
    assert wrong.status_code == unknown.status_code == 200
    expected_failure = html.escape(GENERIC_FAILURE_MESSAGE)
    assert expected_failure in wrong.text
    assert expected_failure in unknown.text
    # Neither answer mentions the account, the username, or why it failed.
    for body in (wrong.text, unknown.text):
        assert "alice" not in body
        assert "no account" not in body.lower()
        assert "not found" not in body.lower()
    # Nothing changed for the live account.
    assert db.get_active_account_by_username("alice") is not None
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 200


def test_delete_request_requires_the_confirmation_checkbox(api):
    client, db = api
    _register(client, "alice")
    response = _delete_form(client, "alice", "correct-horse-1", confirm=False)
    assert response.status_code == 200
    assert html.escape(UNCONFIRMED_MESSAGE) in response.text
    assert db.get_active_account_by_username("alice") is not None


def test_delete_request_is_rate_limited_with_the_password_budget(api):
    client, _db = api
    limit_per_minute = int(PASSWORD_LIMIT.split("/")[0])
    statuses = [
        _delete_form(client, "nobody-here", "correct-horse-1").status_code
        for _ in range(limit_per_minute + 3)
    ]
    assert statuses.count(200) == limit_per_minute
    assert statuses.count(429) == 3


def test_delete_account_by_username_never_reveals_existence(api):
    """Service-level pin: every refusal shares one error string."""
    client, db = api
    _register(client, "alice")
    unknown = deletion_service.delete_account_by_username(db, "nobody-here", "correct-horse-1")
    wrong = deletion_service.delete_account_by_username(db, "alice", "not-the-password")
    assert unknown == wrong
    assert unknown["ok"] is False
    assert deletion_service.delete_account_by_username(db, "alice", "correct-horse-1")["ok"] is True


# --------------------------------------------------------------------------
# Timing: every refusal spends exactly one bcrypt verification (#43)
# --------------------------------------------------------------------------


def _spy_verify(monkeypatch) -> list:
    """Counts bcrypt verifications; a refusal that skips one is an oracle."""
    calls: list = []
    real = deletion_service.verify_password

    def spy(password, password_hash):
        calls.append(password)
        return real(password, password_hash)

    monkeypatch.setattr(deletion_service, "verify_password", spy)
    return calls


def _passwordless_account(db, username: str) -> str:
    """An imported-but-unclaimed style account (ADR 045): ledger, no hash."""
    account_id = db.create_account(username)
    assert account_id is not None
    ledger_id = db.get_account(account_id)["ledger_id"]
    with db.open_ledger(ledger_id):
        pass
    assert db.ledger_exists(ledger_id)
    return account_id


def test_missing_password_hash_spends_one_bcrypt(api, monkeypatch):
    """The no-hash path (imported, never claimed) must cost the same as a wrong one."""
    client, db = api
    account_id = _passwordless_account(db, "ghost")

    calls = _spy_verify(monkeypatch)
    refused = deletion_service.delete_account(db, account_id, "whatever")
    assert refused["ok"] is False
    assert calls == ["whatever"], "the missing-hash path skipped the bcrypt verification"

    calls.clear()
    refused = deletion_service.delete_account_by_username(db, "ghost", "whatever")
    assert refused["ok"] is False
    assert calls == ["whatever"]
    assert db.get_active_account_by_username("ghost") is not None


def test_every_other_refusal_spends_one_bcrypt(api, monkeypatch):
    client, db = api
    _register(client, "alice")
    calls = _spy_verify(monkeypatch)

    assert deletion_service.delete_account_by_username(db, "nobody-here", "pw")["ok"] is False
    assert calls == ["pw"], "unknown username must still cost one bcrypt verification"

    calls.clear()
    # A non-string password is coerced to "" and verified, never skipped.
    assert deletion_service.delete_account_by_username(db, "nobody-here", None)["ok"] is False
    assert calls == [""]

    calls.clear()
    assert deletion_service.delete_account_by_username(db, "alice", "wrong-password")["ok"] is False
    assert len(calls) == 1, "wrong password must cost exactly one bcrypt verification"

    calls.clear()
    # The in-app path refuses an unknown account id the same way.
    assert deletion_service.delete_account(db, "missing-account-id", "pw")["ok"] is False
    assert calls == ["pw"]


# --------------------------------------------------------------------------
# Rate-limit key: one bucket per client, on and off Fly (#43)
# --------------------------------------------------------------------------


def _rate_request(headers: dict | None = None, client=("203.0.113.9", 51000)) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "scheme": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "client": client,
        }
    )


def test_rate_limit_key_uses_the_socket_address_off_fly(monkeypatch):
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    # A forgeable header must not move the bucket when we are not behind Fly.
    assert _key(_rate_request(headers={"fly-client-ip": "198.51.100.7"})) == "203.0.113.9"
    assert _key(_rate_request()) == "203.0.113.9"


def test_rate_limit_key_uses_fly_client_ip_on_fly(monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "mayos-api")
    assert _key(_rate_request(headers={"fly-client-ip": "198.51.100.7"})) == "198.51.100.7"
    # Two callers behind one proxy address must not share a bucket.
    assert _key(_rate_request(headers={"fly-client-ip": "198.51.100.8"})) == "198.51.100.8"
    # No header (direct connection): fall back to the socket address.
    assert _key(_rate_request()) == "203.0.113.9"


def test_rate_limit_key_keeps_the_bearer_suffix_on_fly(monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "mayos-api")
    token = "Bearer " + "a" * 40
    key = _key(_rate_request(headers={"fly-client-ip": "198.51.100.7", "authorization": token}))
    assert key == f"198.51.100.7:{token[-12:]}"


# --------------------------------------------------------------------------
# Renderer unit checks
# --------------------------------------------------------------------------


def test_render_markdown_escapes_html_and_keeps_safe_links():
    rendered = render_markdown("# Title\n\n- A **bold** <script>alert(1)</script>\n- [x](/privacy) [y](javascript:alert(1))\n")
    assert "<h1>Title</h1>" in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<strong>bold</strong>" in rendered
    assert '<a href="/privacy">x</a>' in rendered
    assert "<a href=\"javascript" not in rendered
