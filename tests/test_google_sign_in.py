"""Google linked sign-in API tests (#113): fake verifier, no network, no real tokens."""

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import google_sign_in as google_service
from svc.app import create_app
from svc.auth import SIGNUP_TICKET_AUDIENCE, SIGNUP_TICKET_TYPE, create_signup_ticket, token_claims
from svc.dependencies import GoogleIdentity, GoogleIdentityError, GOOGLE_CLOCK_SKEW_SECONDS, get_db, get_google_verifier

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
TEST_WEB_CLIENT_ID = "1234567890-testapps.googleusercontent.com"


class FakeVerifier:
    """Stand-in for the production seam: the id_token string picks the identity.

    ``"token:Given Name"`` mints ``sub-token`` with that given name; anything
    starting with ``bad`` fails verification the way a wrong audience, wrong
    issuer, bad signature, or expired token would.
    """

    def __init__(self):
        self.seen: list[str] = []
        self.identities: dict[str, GoogleIdentity] = {}

    def __call__(self, id_token: str) -> GoogleIdentity:
        self.seen.append(id_token)
        if id_token.startswith("bad"):
            raise GoogleIdentityError("Google rejected the ID token.")
        if id_token in self.identities:
            return self.identities[id_token]
        token, _, given_name = id_token.partition(":")
        return GoogleIdentity(sub=f"sub-{token}", iat=1_700_000_000, given_name=given_name or None)


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("GOOGLE_WEB_CLIENT_ID", TEST_WEB_CLIENT_ID)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    catalog_path = tmp_path / "catalog.db"
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    verifier = FakeVerifier()
    app = create_app()
    app.state.test_db = db
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_google_verifier] = lambda: verifier
    with TestClient(app) as client:
        yield client, db, verifier
    if db.ledger_conn is not None:
        db.ledger_conn.close()
    db.catalog_conn.close()


def _reset_limits() -> None:
    """Fresh rate-limit buckets for a test that needs more than five on one route."""
    from svc.rate_limit import limiter

    limiter._storage.reset()


def _lifetime_hours(token: str) -> float:
    claims = pyjwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])
    return (claims["exp"] - claims["iat"]) / 3600


def _link_rows(db) -> list:
    with db.catalog_locked() as conn:
        return conn.execute("SELECT provider, subject, account_id, linked_at FROM linked_sign_ins").fetchall()


def _accounts(client) -> list:
    db = client.app.state.test_db
    with db.catalog_locked() as conn:
        return conn.execute("SELECT account_id FROM accounts WHERE deleted_at IS NULL").fetchall()


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _sign_in_for_ticket(client, id_token: str = "alice-token:Alfred") -> dict:
    response = client.post("/auth/google", json={"id_token": id_token})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"signup_ticket", "suggested_username", "existing_account_hint"}
    return body


def _create_account_with_recovery_email(client, db, username: str, email: str):
    registered = client.post(
        "/auth/register",
        json={"trainee_id": username, "password": "StrongPass123"},
    )
    assert registered.status_code == 201, registered.text
    updated = client.post(
        "/auth/email",
        json={"email": email},
        headers=_headers(registered.json()["access_token"]),
    )
    assert updated.status_code == 200, updated.text
    return db.get_active_account_by_username(username)


def _recovery_state(db):
    with db.catalog_locked() as conn:
        return (
            conn.execute(
                "SELECT account_id, username, ledger_id FROM accounts ORDER BY account_id"
            ).fetchall(),
            conn.execute(
                "SELECT provider, subject, account_id FROM linked_sign_ins ORDER BY subject"
            ).fetchall(),
            conn.execute(
                "SELECT trainee_id, email FROM trainee_emails ORDER BY trainee_id"
            ).fetchall(),
        )


def test_first_sign_in_creates_account_only_after_the_username_is_picked(api):
    client, db, _verifier = api

    signup = _sign_in_for_ticket(client)
    assert signup["suggested_username"] == "alfred"

    # Nothing exists yet: no account, no link (issue #113 — abandoning is free).
    assert db.get_active_account_by_username("alfred") is None
    assert _link_rows(db) == []

    ticket = signup["signup_ticket"]
    availability = client.get(
        "/auth/username-available",
        params={"username": "alfred"},
        headers=_headers(ticket),
    )
    assert availability.status_code == 200
    assert availability.json() == {"available": True}

    completed = client.post(
        "/auth/google/complete",
        json={"signup_ticket": ticket, "username": signup["suggested_username"]},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["trainee_id"] == "alfred"

    account = db.get_active_account_by_username("alfred")
    assert account is not None and account["is_player"] is True
    # Like registration: its own ledger, and no password hash ever written.
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert ledger.get_password_hash() is None

    rows = _link_rows(db)
    assert len(rows) == 1
    assert rows[0][0] == "google" and rows[0][1] == "sub-alice-token" and rows[0][2] == account["account_id"]
    with db.catalog_locked() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(linked_sign_ins)")}
    assert columns == {"provider", "subject", "account_id", "linked_at"}

    # The session this returns works like any other.
    session = client.get("/auth/me", headers=_headers(completed.json()["access_token"]))
    assert session.status_code == 200
    assert session.json()["trainee_id"] == "alfred"
    assert session.json()["capabilities"] == {"player": True, "coach": False}


def test_returning_google_sign_in_goes_straight_in_with_remember_me(api):
    client, db, verifier = api
    signup = _sign_in_for_ticket(client, "bob-token:Bob")
    completed = client.post(
        "/auth/google/complete",
        json={"signup_ticket": signup["signup_ticket"], "username": "bob"},
    )
    assert completed.status_code == 200

    again = client.post("/auth/google", json={"id_token": "bob-token:Bob"})
    assert again.status_code == 200
    body = again.json()
    assert set(body) == {"access_token", "token_type", "trainee_id"}
    assert body["trainee_id"] == "bob"
    assert _lifetime_hours(body["access_token"]) == 720
    assert client.get("/auth/me", headers=_headers(body["access_token"])).status_code == 200
    assert len(verifier.seen) == 2

    # Two sign-ins, one account, one link.
    assert len(_link_rows(db)) == 1
    assert len(_accounts(client)) == 1


def test_verified_recovery_email_match_returns_only_a_nudge_and_writes_nothing(api, caplog):
    client, db, verifier = api
    existing = _create_account_with_recovery_email(
        client, db, "existing-owner", "You@Gmail.com"
    )
    verifier.identities["verified-match"] = GoogleIdentity(
        sub="unlinked-google-sub",
        iat=1_700_000_000,
        given_name="New Person",
        email="  YOU@gmail.com ",
        email_verified=True,
    )
    before = _recovery_state(db)

    response = client.post("/auth/google", json={"id_token": "verified-match"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["existing_account_hint"] is True
    assert body["suggested_username"] == "newperson"
    assert "existing-owner" not in response.text
    assert "YOU@gmail.com" not in response.text
    payload = pyjwt.decode(
        body["signup_ticket"],
        TEST_JWT_SECRET,
        algorithms=["HS256"],
        audience=SIGNUP_TICKET_AUDIENCE,
    )
    assert set(payload) == {"sub", "type", "aud", "iat", "nbf", "exp"}
    assert _recovery_state(db) == before
    assert db.get_account_email(existing["account_id"]) == "you@gmail.com"
    # The verified Google email must not cross the logging boundary either.
    assert "YOU@gmail.com" not in caplog.text


def test_verified_recovery_email_match_hints_for_a_coach_only_account(api):
    client, db, verifier = api
    existing = _create_account_with_recovery_email(
        client, db, "coach-owner", "coach@gmail.com"
    )
    with db.catalog_locked() as conn:
        conn.execute(
            "UPDATE accounts SET is_player = 0, is_coach = 1 WHERE account_id = ?",
            (existing["account_id"],),
        )
        conn.commit()
    before = _recovery_state(db)
    verifier.identities["coach-match"] = GoogleIdentity(
        sub="unlinked-coach-sub",
        iat=1_700_000_000,
        email="COACH@gmail.com",
        email_verified=True,
    )

    response = client.post("/auth/google", json={"id_token": "coach-match"})

    assert response.status_code == 200, response.text
    assert response.json()["existing_account_hint"] is True
    assert "coach-owner" not in response.text
    assert _recovery_state(db) == before


@pytest.mark.parametrize(
    ("verified", "google_email"),
    [(False, "owner@gmail.com"), (True, "another@gmail.com"), (True, None)],
)
def test_unverified_missing_or_unmatched_email_does_not_return_hint(api, verified, google_email):
    client, db, verifier = api
    _create_account_with_recovery_email(client, db, "email-owner", "owner@gmail.com")
    verifier.identities["no-hint"] = GoogleIdentity(
        sub="unlinked-no-hint",
        iat=1_700_000_000,
        given_name="New Person",
        email=google_email,
        email_verified=verified,
    )

    response = client.post("/auth/google", json={"id_token": "no-hint"})

    assert response.status_code == 200, response.text
    assert response.json()["existing_account_hint"] is False


def test_deleted_recovery_account_does_not_return_hint(api):
    client, db, verifier = api
    existing = _create_account_with_recovery_email(
        client, db, "deleted-owner", "deleted@gmail.com"
    )
    with db.catalog_locked() as conn:
        conn.execute(
            "UPDATE accounts SET status = 'deleted', deleted_at = ? WHERE account_id = ?",
            (datetime.now(UTC).isoformat(), existing["account_id"]),
        )
        conn.commit()
    verifier.identities["deleted-match"] = GoogleIdentity(
        sub="unlinked-deleted-match",
        iat=1_700_000_000,
        email="deleted@gmail.com",
        email_verified=True,
    )

    response = client.post("/auth/google", json={"id_token": "deleted-match"})

    assert response.status_code == 200, response.text
    assert response.json()["existing_account_hint"] is False


def test_signup_ticket_carries_only_the_subject_and_fifteen_minutes(api):
    client, _, _verifier = api
    signup = _sign_in_for_ticket(client, "carol-token:Carol")

    payload = pyjwt.decode(
        signup["signup_ticket"],
        TEST_JWT_SECRET,
        algorithms=["HS256"],
        audience=SIGNUP_TICKET_AUDIENCE,
    )
    assert set(payload) == {"sub", "type", "aud", "iat", "nbf", "exp"}
    assert payload["sub"] == "sub-carol-token"
    assert payload["type"] == SIGNUP_TICKET_TYPE
    assert payload["aud"] == SIGNUP_TICKET_AUDIENCE
    assert payload["exp"] - payload["iat"] == 15 * 60
    # No email or name travels in the ticket.
    assert "email" not in payload
    assert "given_name" not in payload
    assert "name" not in payload
    # …and it is refused where a session token is expected.
    with pytest.raises(pyjwt.PyJWTError):
        token_claims(signup["signup_ticket"])


def test_expired_tampered_and_wrong_audience_tickets_are_refused(api):
    client, db, _verifier = api
    ticket = _sign_in_for_ticket(client)["signup_ticket"]

    now = datetime.now(UTC)
    expired = pyjwt.encode(
        {
            "sub": "sub-alice-token",
            "type": SIGNUP_TICKET_TYPE,
            "aud": SIGNUP_TICKET_AUDIENCE,
            "iat": now - timedelta(hours=1),
            "nbf": now - timedelta(hours=1),
            "exp": now - timedelta(minutes=1),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    wrong_audience = pyjwt.encode(
        {
            "sub": "sub-alice-token",
            "type": SIGNUP_TICKET_TYPE,
            "aud": "some-other-audience",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=15),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    tampered = ticket[:-4] + ("AAAA" if not ticket.endswith("AAAA") else "BBBB")
    # A correctly signed ticket with its lifetime stripped must still be
    # refused: exp/aud/sub are required claims, not optional ones.
    missing_exp = pyjwt.encode(
        {
            "sub": "sub-alice-token",
            "type": SIGNUP_TICKET_TYPE,
            "aud": SIGNUP_TICKET_AUDIENCE,
            "iat": now,
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )

    for bad in (expired, wrong_audience, missing_exp, tampered, "not-a-jwt"):
        complete = client.post("/auth/google/complete", json={"signup_ticket": bad, "username": "alice"})
        assert complete.status_code == 401, complete.text
        availability = client.get(
            "/auth/username-available",
            params={"username": "alice"},
            headers=_headers(bad),
        )
        assert availability.status_code == 401

    # A refused ticket never created anything, and a ticketless check is refused too.
    assert _accounts(client) == []
    assert client.get("/auth/username-available", params={"username": "alice"}).status_code == 401


def test_signup_ticket_is_never_a_session_token(api):
    client, _, _verifier = api
    ticket = _sign_in_for_ticket(client)["signup_ticket"]

    assert client.get("/auth/me", headers=_headers(ticket)).status_code == 401
    assert client.post("/auth/logout", headers=_headers(ticket)).status_code == 401
    with pytest.raises(pyjwt.PyJWTError):
        token_claims(ticket)


def test_session_token_is_not_a_signup_ticket(api):
    client, _, _verifier = api
    session_token = client.post(
        "/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"}
    ).json()["access_token"]

    availability = client.get(
        "/auth/username-available",
        params={"username": "alice"},
        headers=_headers(session_token),
    )
    assert availability.status_code == 401
    complete = client.post(
        "/auth/google/complete",
        json={"signup_ticket": session_token, "username": "bob"},
    )
    assert complete.status_code == 401
    assert len(_accounts(client)) == 1


def test_username_available_reports_taken_and_refuses_invalid_input(api):
    client, _, _verifier = api
    client.post("/auth/register", json={"trainee_id": "taken-name", "password": "correct-horse-1"})
    ticket = _sign_in_for_ticket(client)["signup_ticket"]

    taken = client.get(
        "/auth/username-available",
        params={"username": "taken-name"},
        headers=_headers(ticket),
    )
    assert taken.status_code == 200
    assert taken.json() == {"available": False, "reason": "taken"}

    _reset_limits()
    for invalid in ("ab", "a" * 31, "no space", "", "Ünicode"):
        response = client.get(
            "/auth/username-available",
            params={"username": invalid},
            headers=_headers(ticket),
        )
        assert response.status_code == 400, (invalid, response.status_code)
        assert "3–30" in response.json()["detail"]


def test_complete_refuses_invalid_username_with_a_clear_error(api):
    client, db, _verifier = api
    ticket = _sign_in_for_ticket(client)["signup_ticket"]

    for invalid in ("ab", "a" * 31, "no spaces", "punct!"):
        response = client.post("/auth/google/complete", json={"signup_ticket": ticket, "username": invalid})
        assert response.status_code == 400, (invalid, response.status_code)
        assert "3–30" in response.json()["detail"]
    assert _accounts(client) == []
    assert _link_rows(db) == []

    _reset_limits()
    # Only lowercasing is applied; the account is created exactly as picked.
    completed = client.post(
        "/auth/google/complete",
        json={"signup_ticket": ticket, "username": "MiXeD-Name_2"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["trainee_id"] == "mixed-name_2"
    assert len(_accounts(client)) == 1


def test_taken_username_returns_conflict(api):
    client, db, _verifier = api
    client.post("/auth/register", json={"trainee_id": "busy", "password": "correct-horse-1"})
    ticket = _sign_in_for_ticket(client)["signup_ticket"]

    response = client.post("/auth/google/complete", json={"signup_ticket": ticket, "username": "busy"})
    assert response.status_code == 409
    # The refused completion created no account and no link.
    assert len(_accounts(client)) == 1
    assert _link_rows(db) == []


def _break_next_ledger_creation(monkeypatch) -> dict:
    """Arms a one-shot fault: the next attempt to create a missing ledger fails.

    Models a completion whose catalog transaction committed (account + link)
    but whose ledger file was never created — the "stuck account" case (#113).
    """
    from database.database_manager import DatabaseManager

    real_open = DatabaseManager.open_ledger
    state = {"armed": True}

    def flaky_open_ledger(self, ledger_id):
        if state["armed"] and not self.ledger_exists(ledger_id):
            state["armed"] = False
            raise RuntimeError("injected: ledger creation failed")
        return real_open(self, ledger_id)

    monkeypatch.setattr(DatabaseManager, "open_ledger", flaky_open_ledger)
    return state


def _account_without_ledger(api, id_token: str, username: str) -> dict:
    """Runs a completion through the fault, leaving a committed account with no ledger."""
    client, db, _verifier = api
    ticket = _sign_in_for_ticket(client, id_token)["signup_ticket"]
    # Server-side failures return 502; the TestClient default re-raises them.
    faulty = TestClient(client.app, raise_server_exceptions=False)
    response = faulty.post("/auth/google/complete", json={"signup_ticket": ticket, "username": username})
    assert response.status_code == 502, response.text
    account = db.get_active_account_by_username(username)
    assert account is not None
    assert not db.ledger_exists(account["ledger_id"])
    assert len(_link_rows(db)) == 1
    return {"ticket": ticket, "account": account}


def test_retry_of_complete_self_heals_an_account_whose_ledger_never_materialised(api, monkeypatch):
    client, db, _verifier = api
    _break_next_ledger_creation(monkeypatch)
    state = _account_without_ledger(api, "heal-token:Helen", "helen")

    # The retry must not answer 409: it materialises the ledger and issues the
    # session for the already-linked account, creating nothing new.
    retry = client.post(
        "/auth/google/complete",
        json={"signup_ticket": state["ticket"], "username": "helen"},
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["trainee_id"] == "helen"
    assert db.ledger_exists(state["account"]["ledger_id"])
    assert len(_accounts(client)) == 1 and len(_link_rows(db)) == 1
    assert client.get("/auth/me", headers=_headers(retry.json()["access_token"])).status_code == 200


def test_next_google_sign_in_self_heals_an_account_whose_ledger_never_materialised(api, monkeypatch):
    client, db, _verifier = api
    _break_next_ledger_creation(monkeypatch)
    state = _account_without_ledger(api, "heal2-token:Hana", "hana")

    signin = client.post("/auth/google", json={"id_token": "heal2-token:Hana"})
    assert signin.status_code == 200, signin.text
    assert signin.json()["trainee_id"] == "hana"
    assert db.ledger_exists(state["account"]["ledger_id"])
    assert len(_accounts(client)) == 1 and len(_link_rows(db)) == 1
    # The issued session passes the registry's ledger gate instead of 401.
    assert client.get("/auth/me", headers=_headers(signin.json()["access_token"])).status_code == 200


def test_suggestion_is_suffixed_when_taken_and_is_never_stored(api):
    client, db, _verifier = api
    client.post("/auth/register", json={"trainee_id": "alfred", "password": "correct-horse-1"})

    signup = _sign_in_for_ticket(client, "dave-token:Alfred")
    assert signup["suggested_username"] == "alfred-2"
    # The suggestion is only a suggestion: nothing was written for it.
    assert _link_rows(db) == []
    assert len(_accounts(client)) == 1

    # No given name, or one too short to stand alone, still yields a valid guess.
    assert _sign_in_for_ticket(client, "eve-token")["suggested_username"] == "player"
    assert _sign_in_for_ticket(client, "frank-token:Li")["suggested_username"] == "player"


def test_concurrent_completion_creates_one_account_and_one_link(api):
    client, db, _verifier = api
    _sign_in_for_ticket(client, "race-token:Racer")

    outcomes: list[object] = []
    barrier = threading.Barrier(2)

    def complete(username: str) -> None:
        barrier.wait(timeout=5)
        try:
            outcomes.append(google_service.complete_signup(db, "sub-race-token", username))
        except Exception as exc:  # the loser's failure mode is the assertion
            outcomes.append(exc)

    threads = [threading.Thread(target=complete, args=(name,)) for name in ("racer-one", "racer-two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    winners = [outcome for outcome in outcomes if isinstance(outcome, dict) and outcome.get("ok")]
    losers = [outcome for outcome in outcomes if isinstance(outcome, google_service.SignUpConflictError)]
    assert len(winners) == 1, outcomes
    assert len(losers) == 1, outcomes

    assert len(_accounts(client)) == 1
    assert len(_link_rows(db)) == 1
    # The loser's username never became an account.
    winner_name = winners[0]["trainee_id"]
    loser_name = "racer-one" if winner_name == "racer-two" else "racer-two"
    assert db.get_active_account_by_username(loser_name) is None

    # The subject resolves to the single account, so no second one is reachable.
    again = client.post("/auth/google", json={"id_token": "race-token:Racer"})
    assert again.json()["trainee_id"] == winner_name


def test_link_row_is_unique_per_provider_and_subject(api):
    _, db, _verifier = api
    first = db.create_account("linker")
    second = db.create_account("linker-two")
    db.link_sign_in("google", "sub-unique", first)
    with pytest.raises(sqlite3.IntegrityError):
        db.link_sign_in("google", "sub-unique", second)


def test_password_login_for_google_only_account_is_refused(api):
    client, db, _verifier = api
    signup = _sign_in_for_ticket(client, "gina-token:Gina")
    assert client.post(
        "/auth/google/complete", json={"signup_ticket": signup["signup_ticket"], "username": "gina"}
    ).status_code == 200
    account = db.get_active_account_by_username("gina")
    assert account is not None

    # Password login for a Google-only account has no local password.
    login = client.post("/auth/login", json={"trainee_id": "gina", "password": "correct-horse-1"})
    assert login.status_code == 401
    assert login.json() == {"detail": "Invalid credentials."}

    with db.open_ledger(account["ledger_id"]) as ledger:
        assert ledger.get_password_hash() is None
    assert client.post("/auth/login", json={"trainee_id": "gina", "password": "new-horse-22"}).status_code == 401


def test_verifier_rejections_are_reported_as_invalid_credentials(api):
    client, _, _verifier = api
    for bad_token in ("bad-audience", "bad-issuer", "bad-signature"):
        response = client.post("/auth/google", json={"id_token": bad_token})
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid Google credentials."}


def test_google_endpoints_are_rate_limited_like_login(api):
    client, _, _verifier = api
    _sign_in_for_ticket(client)
    statuses = [client.post("/auth/google", json={"id_token": "alice-token:Alfred"}).status_code for _ in range(7)]
    assert sum(1 for code in statuses if code == 200) == 4
    assert statuses.count(429) == 3

    _reset_limits()
    ticket = _sign_in_for_ticket(client)["signup_ticket"]
    # The picker is a debounced as-you-type check, so it has its own 30/min
    # budget (RATE_LIMIT_USERNAME_CHECK) instead of login's 5/min.
    availability = [
        client.get(
            "/auth/username-available",
            params={"username": f"check-{index}"},
            headers=_headers(ticket),
        ).status_code
        for index in range(31)
    ]
    assert availability[:30] == [200] * 30
    assert availability[30] == 429
    assert availability.count(429) == 1


def test_google_endpoints_return_503_when_unconfigured_and_nothing_else_changes(api, monkeypatch):
    client, _db, _verifier = api
    monkeypatch.delenv("GOOGLE_WEB_CLIENT_ID")

    assert client.post("/auth/google", json={"id_token": "alice-token:Alfred"}).status_code == 503

    ticket = create_signup_ticket("sub-alice-token")
    assert client.get(
        "/auth/username-available",
        params={"username": "alice"},
        headers=_headers(ticket),
    ).status_code == 503
    assert client.post(
        "/auth/google/complete",
        json={"signup_ticket": ticket, "username": "alice"},
    ).status_code == 503
    assert _accounts(client) == []

    # Everything else keeps working exactly as before.
    assert client.post("/auth/register", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 201
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 200

    # Exactly one place decides "unconfigured → 503": the routes' shared gate.
    # The verifier seam itself fails closed rather than raising a second 503.
    from svc.dependencies import _verify_google_id_token

    with pytest.raises(GoogleIdentityError):
        _verify_google_id_token("raw-google-token")


def test_production_verifier_uses_configured_audience_and_rejects_bad_issuer(monkeypatch):
    from google.auth import exceptions as google_auth_exceptions
    from google.oauth2 import id_token as google_id_token

    from svc.dependencies import _verify_google_id_token

    monkeypatch.setenv("GOOGLE_WEB_CLIENT_ID", TEST_WEB_CLIENT_ID)
    seen: dict[str, object] = {}
    transports: list[object] = []

    def fake_verify(raw_id_token, request, audience=None, clock_skew_in_seconds=0, **kwargs):
        seen["token"] = raw_id_token
        seen["audience"] = audience
        seen["clock_skew"] = clock_skew_in_seconds
        transports.append(request)
        return {
            "iss": "https://accounts.google.com",
            "sub": "sub-123",
            "iat": 1_700_000_000,
            "given_name": "Ada",
            "email": "ada@example.com",
            "email_verified": True,
        }

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", fake_verify)
    identity = _verify_google_id_token("raw-google-token")
    assert identity.sub == "sub-123"
    assert identity.iat == 1_700_000_000
    assert identity.given_name == "Ada"
    assert identity.email == "ada@example.com"
    assert identity.email_verified is True
    assert seen["token"] == "raw-google-token"
    assert seen["audience"] == TEST_WEB_CLIENT_ID
    # A little clock skew is allowed so drift does not refuse a fresh token.
    assert seen["clock_skew"] == GOOGLE_CLOCK_SKEW_SECONDS == 10
    assert type(transports[0]).__name__ == "Request"
    # One cached transport over a shared session: never a fresh one per sign-in.
    _verify_google_id_token("raw-google-token-2")
    assert transports[1] is transports[0]

    def unverified_email(*args, **kwargs):
        return {
            "iss": "https://accounts.google.com",
            "sub": "sub-123",
            "email": "ada@example.com",
            "email_verified": "true",
        }

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", unverified_email)
    identity = _verify_google_id_token("raw-google-token")
    assert identity.email == "ada@example.com"
    assert identity.email_verified is False

    def wrong_issuer(*args, **kwargs):
        return {"iss": "https://accounts.example.com", "sub": "sub-123", "iat": 1_700_000_000}

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", wrong_issuer)
    with pytest.raises(GoogleIdentityError):
        _verify_google_id_token("raw-google-token")

    def no_subject(*args, **kwargs):
        return {"iss": "https://accounts.google.com", "iat": 1_700_000_000}

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", no_subject)
    with pytest.raises(GoogleIdentityError):
        _verify_google_id_token("raw-google-token")

    def rejected(*args, **kwargs):
        raise google_auth_exceptions.GoogleAuthError("Wrong issuer.")

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", rejected)
    with pytest.raises(GoogleIdentityError):
        _verify_google_id_token("raw-google-token")

    def bad_audience(*args, **kwargs):
        raise ValueError("Token has wrong audience")

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", bad_audience)
    with pytest.raises(GoogleIdentityError):
        _verify_google_id_token("raw-google-token")
