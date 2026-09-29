"""Sign-in methods (#114): connect, disconnect, first password, delete via Google.

Fake verifier throughout — the ``sub``/``iat`` pair is picked by the test, so
fresh/stale/wrong-sub tokens are exact and nothing reaches Google's network.
"""

import sqlite3
import time
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import auth as auth_service
from service import password_reset as reset_service
from svc.app import create_app
from svc.dependencies import GoogleIdentity, GoogleIdentityError, get_db, get_google_verifier

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
TEST_WEB_CLIENT_ID = "1234567890-testapps.googleusercontent.com"
#: The exact conflict message #114 pins down — never which account holds it.
LINKED_ELSEWHERE = "This Google account is already connected to another MAYOS account"
#: Backdated well outside the 5-minute window deletion requires.
STALE_SECONDS = -600


class FakeVerifier:
    """``token:Given Name`` ⇒ ``sub-token``; ``bad*`` fails; ``stale*`` ages the iat.

    A fresh identity carries ``iat`` = now, so it passes deletion's 5-minute
    check; ``stale-*`` backdates the issue time beyond that window.
    """

    def __init__(self):
        self.seen: list[str] = []

    def __call__(self, id_token: str) -> GoogleIdentity:
        self.seen.append(id_token)
        if id_token.startswith("bad"):
            raise GoogleIdentityError("Google rejected the ID token.")
        token, _, given_name = id_token.partition(":")
        iat = int(time.time()) + (STALE_SECONDS if token.startswith("stale") else 0)
        return GoogleIdentity(sub=f"sub-{token}", iat=iat, given_name=given_name or None)


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("GOOGLE_WEB_CLIENT_ID", TEST_WEB_CLIENT_ID)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute("CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT);")
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.commit()
    cat_conn.close()
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


def _authed(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _claims(token: str) -> dict:
    return pyjwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])


def _subject(token: str) -> str:
    return str(_claims(token)["sub"])


def _epoch(token: str) -> int:
    """The session-epoch claim an epoch bump must (or must not) change."""
    return int(_claims(token)["tv"])


def _link_rows(db) -> list:
    with db.catalog_locked() as conn:
        return conn.execute("SELECT provider, subject, account_id FROM linked_sign_ins").fetchall()


def _google_account(client, id_token: str, username: str) -> tuple[str, str]:
    """A signed-in Google-only account: ``(access_token, account_id)``."""
    signup = client.post("/auth/google", json={"id_token": id_token})
    assert signup.status_code == 200, signup.text
    body = signup.json()
    assert "signup_ticket" in body, body
    completed = client.post(
        "/auth/google/complete",
        json={"signup_ticket": body["signup_ticket"], "username": username},
    )
    assert completed.status_code == 200, completed.text
    token = completed.json()["access_token"]
    return token, _subject(token)


def _password_account(client, username: str, password: str = "correct-horse-1") -> str:
    created = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert created.status_code == 201, created.text
    return created.json()["access_token"]


def _me(client, token: str) -> dict:
    response = client.get("/auth/me", headers=_authed(token))
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------
# GET /auth/me reports how the account can sign in.


def test_auth_me_reports_has_password_and_linked_sign_ins(api):
    client, db, _verifier = api
    google_token, _ = _google_account(client, "ana-token:Ana", "ana")
    me = _me(client, google_token)
    assert me["has_password"] is False
    assert me["linked_sign_ins"] == ["google"]

    password_token = _password_account(client, "bob")
    me = _me(client, password_token)
    assert me["has_password"] is True
    assert me["linked_sign_ins"] == []

    # Provider names travel, never the subject.
    assert "sub-ana-token" not in str(me)


# --------------------------------------------------------------------------
# POST /auth/google/link


def test_link_connects_and_is_idempotent(api):
    client, db, _verifier = api
    token = _password_account(client, "alice")
    account_id = _subject(token)
    assert _link_rows(db) == []

    first = client.post("/auth/google/link", json={"id_token": "alice-google:Alice"}, headers=_authed(token))
    assert first.status_code == 200, first.text
    assert _link_rows(db) == [("google", "sub-alice-google", account_id)]
    assert _me(client, token)["linked_sign_ins"] == ["google"]

    again = client.post("/auth/google/link", json={"id_token": "alice-google:Alice"}, headers=_authed(token))
    assert again.status_code == 200, again.text  # already connected: no error, no second row
    assert _link_rows(db) == [("google", "sub-alice-google", account_id)]

    # A Google-only account linking the subject it already owns is the same idempotence.
    google_token, google_id = _google_account(client, "ana-token:Ana", "ana")
    assert client.post(
        "/auth/google/link", json={"id_token": "ana-token:Ana"}, headers=_authed(google_token)
    ).status_code == 200
    assert _link_rows(db) == [
        ("google", "sub-alice-google", account_id),
        ("google", "sub-ana-token", google_id),
    ]


def test_link_is_refused_when_the_google_account_belongs_to_another_account(api):
    client, db, _verifier = api
    alice_token = _password_account(client, "alice")
    bob_token = _password_account(client, "bob")

    connected = client.post("/auth/google/link", json={"id_token": "shared-token:S"}, headers=_authed(bob_token))
    assert connected.status_code == 200, connected.text
    bob_id = _link_rows(db)[0][2]

    refused = client.post("/auth/google/link", json={"id_token": "shared-token:S"}, headers=_authed(alice_token))
    assert refused.status_code == 409, refused.text
    # The pinned message, and nothing about *which* account holds it.
    assert refused.json()["detail"] == LINKED_ELSEWHERE
    assert "bob" not in refused.json()["detail"]
    assert bob_id not in refused.json()["detail"]
    assert _subject(alice_token) not in refused.json()["detail"]
    # Bob keeps the link; Alice gained nothing.
    assert _link_rows(db) == [("google", "sub-shared-token", bob_id)]
    assert _me(client, alice_token)["linked_sign_ins"] == []


def test_link_is_refused_when_the_caller_already_has_a_different_google(api):
    client, db, _verifier = api
    token, account_id = _google_account(client, "ana-token:Ana", "ana")

    second = client.post("/auth/google/link", json={"id_token": "second-token:S"}, headers=_authed(token))
    assert second.status_code == 409, second.text
    assert "Disconnect it first" in second.json()["detail"]
    # The original link is untouched.
    assert _link_rows(db) == [("google", "sub-ana-token", account_id)]


def test_link_requires_a_session_a_valid_token_and_configuration(api, monkeypatch):
    client, db, _verifier = api
    token, account_id = _google_account(client, "ana-token:Ana", "ana")

    assert client.post("/auth/google/link", json={"id_token": "x-token"}).status_code == 401
    bad = client.post("/auth/google/link", json={"id_token": "bad-audience"}, headers=_authed(token))
    assert bad.status_code == 401
    assert bad.json() == {"detail": "Invalid Google credentials."}
    assert _link_rows(db) == [("google", "sub-ana-token", account_id)]

    # The same single 503 gate as the rest of the /auth/google* family (#113).
    monkeypatch.delenv("GOOGLE_WEB_CLIENT_ID")
    assert client.post("/auth/google/link", json={"id_token": "x-token"}, headers=_authed(token)).status_code == 503
    assert client.delete("/auth/google/link", headers=_authed(token)).status_code == 503


def test_constraint_violation_on_connect_maps_to_its_own_conflict(api, monkeypatch):
    """Both unique constraints name their own 409, and neither leaks who holds what."""
    client, db, _verifier = api

    # UNIQUE(account_id, provider): Alice already connected one identity, and
    # the pre-check is blinded so only the constraint can refuse the second.
    alice_token = _password_account(client, "alice")
    alice_id = _subject(alice_token)
    assert client.post(
        "/auth/google/link", json={"id_token": "first-token:F"}, headers=_authed(alice_token)
    ).status_code == 200

    real_subject = DatabaseManager.get_linked_sign_in_subject
    blind = {"armed": True}

    def hidden_from_the_pre_check(self, account_id, provider):
        if blind["armed"]:
            blind["armed"] = False
            return None
        return real_subject(self, account_id, provider)

    monkeypatch.setattr(DatabaseManager, "get_linked_sign_in_subject", hidden_from_the_pre_check)
    own_slot = client.post(
        "/auth/google/link", json={"id_token": "second-token:S"}, headers=_authed(alice_token)
    )
    assert own_slot.status_code == 409, own_slot.text
    assert "Disconnect it first" in own_slot.json()["detail"]
    # Alice's first link is untouched.
    assert ("google", "sub-first-token", alice_id) in _link_rows(db)

    # UNIQUE(provider, subject): Bob holds the identity, hidden from the
    # pre-check so only the constraint can refuse Carol — and the answer must
    # still be the "another MAYOS account" message, never Bob's.
    bob_token = _password_account(client, "bob")
    assert client.post(
        "/auth/google/link", json={"id_token": "shared-token:S"}, headers=_authed(bob_token)
    ).status_code == 200
    bob_id = [row[2] for row in _link_rows(db) if row[1] == "sub-shared-token"][0]
    carol_token = _password_account(client, "carol")

    real_holder = DatabaseManager.get_linked_sign_in_account_id
    seen = {"calls": 0}

    def hidden_holder(self, provider, subject):
        seen["calls"] += 1
        if seen["calls"] == 1:
            return None
        return real_holder(self, provider, subject)

    monkeypatch.setattr(DatabaseManager, "get_linked_sign_in_account_id", hidden_holder)
    foreign = client.post(
        "/auth/google/link", json={"id_token": "shared-token:S"}, headers=_authed(carol_token)
    )
    assert foreign.status_code == 409, foreign.text
    assert foreign.json()["detail"] == LINKED_ELSEWHERE
    assert "bob" not in foreign.json()["detail"]
    assert bob_id not in foreign.json()["detail"]
    assert _me(client, carol_token)["linked_sign_ins"] == []


def test_link_schema_enforces_one_link_per_provider_and_migrates_duplicates(api):
    client, db, _verifier = api
    db.ensure_account_schema()

    # A fresh catalog refuses a second identity for one provider in the schema.
    with db.catalog_locked() as conn:
        unique_coverings = set()
        for index in conn.execute("PRAGMA index_list(linked_sign_ins)").fetchall():
            if not bool(index[2]):
                continue
            columns = {str(row[2]) for row in conn.execute(f'PRAGMA index_info("{index[1]}")').fetchall()}
            unique_coverings.add(frozenset(columns))
        assert frozenset({"account_id", "provider"}) in unique_coverings
        conn.execute(
            "INSERT INTO linked_sign_ins (provider, subject, account_id, linked_at)"
            " VALUES ('google', 'sub-1', 'acct-1', 't0')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO linked_sign_ins (provider, subject, account_id, linked_at)"
                " VALUES ('google', 'sub-2', 'acct-1', 't1')"
            )
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM linked_sign_ins").fetchone()[0] == 0

    # A catalog from before the constraint, holding a duplicate: the additive
    # migration keeps the earliest link, drops the rest, and enforces the rule.
    with db.catalog_transaction():
        conn = db.catalog_conn
        conn.execute("DROP TABLE linked_sign_ins")
        conn.execute(
            "CREATE TABLE linked_sign_ins (provider TEXT NOT NULL, subject TEXT NOT NULL,"
            " account_id TEXT NOT NULL, linked_at TEXT NOT NULL, UNIQUE(provider, subject))"
        )
        conn.execute("INSERT INTO linked_sign_ins VALUES ('google', 'sub-a', 'acct-1', 't0')")
        conn.execute("INSERT INTO linked_sign_ins VALUES ('google', 'sub-b', 'acct-1', 't1')")
        conn.execute("INSERT INTO linked_sign_ins VALUES ('google', 'sub-c', 'acct-2', 't2')")

    db._account_schema_ready = False
    db.ensure_account_schema()

    with db.catalog_locked() as conn:
        rows = conn.execute(
            "SELECT subject, account_id FROM linked_sign_ins ORDER BY account_id, linked_at"
        ).fetchall()
        assert rows == [("sub-a", "acct-1"), ("sub-c", "acct-2")]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO linked_sign_ins (provider, subject, account_id, linked_at)"
                " VALUES ('google', 'sub-d', 'acct-2', 't3')"
            )
        conn.rollback()


# --------------------------------------------------------------------------
# DELETE /auth/google/link


def test_disconnect_is_refused_without_a_password(api):
    client, db, _verifier = api
    token, account_id = _google_account(client, "ana-token:Ana", "ana")

    refused = client.delete("/auth/google/link", headers=_authed(token))
    assert refused.status_code == 409, refused.text
    assert "password" in refused.json()["detail"].lower()
    # Nothing changed: still Google-only, still exactly one way to sign in.
    assert _link_rows(db) == [("google", "sub-ana-token", account_id)]
    me = _me(client, token)
    assert me["has_password"] is False
    assert me["linked_sign_ins"] == ["google"]
    assert client.post("/auth/google", json={"id_token": "ana-token:Ana"}).status_code == 200


def test_disconnect_works_once_a_password_exists_and_is_idempotent(api):
    client, db, _verifier = api
    token, _ = _google_account(client, "ana-token:Ana", "ana")

    set_password = client.post(
        "/auth/set-password", json={"new_password": "correct-horse-1"}, headers=_authed(token)
    )
    assert set_password.status_code == 200, set_password.text
    removed = client.delete("/auth/google/link", headers=_authed(token))
    assert removed.status_code == 200, removed.text
    assert _link_rows(db) == []
    me = _me(client, token)
    assert me["has_password"] is True
    assert me["linked_sign_ins"] == []

    # Now it is a plain password account: Google sign-in offers a fresh signup.
    again = client.post("/auth/google", json={"id_token": "ana-token:Ana"})
    assert again.status_code == 200 and "signup_ticket" in again.json()
    # …and a second disconnect is an idempotent no-op, not an error.
    assert client.delete("/auth/google/link", headers=_authed(token)).status_code == 200
    assert _link_rows(db) == []


# --------------------------------------------------------------------------
# POST /auth/set-password


def test_set_password_gives_a_passwordless_account_a_password(api):
    client, db, _verifier = api
    token, _account_id = _google_account(client, "ana-token:Ana", "ana")

    set_once = client.post("/auth/set-password", json={"new_password": "correct-horse-1"}, headers=_authed(token))
    assert set_once.status_code == 200, set_once.text
    me = _me(client, token)
    assert me["has_password"] is True
    with db.open_ledger(me["trainee_id"]) as ledger:
        assert ledger.get_password_hash() is not None

    # The password signs in beside Google.
    login = client.post("/auth/login", json={"trainee_id": "ana", "password": "correct-horse-1"})
    assert login.status_code == 200, login.text

    # Only the *first* password: a second attempt points at change-password.
    twice = client.post("/auth/set-password", json={"new_password": "another-horse-2"}, headers=_authed(token))
    assert twice.status_code == 409, twice.text
    assert "change-password" in twice.json()["detail"]
    # …and the stored password is still the first one.
    assert client.post("/auth/login", json={"trainee_id": "ana", "password": "another-horse-2"}).status_code == 401
    assert client.post("/auth/login", json={"trainee_id": "ana", "password": "correct-horse-1"}).status_code == 200


def test_set_password_uses_the_existing_password_validation(api):
    client, db, _verifier = api
    token, account_id = _google_account(client, "ana-token:Ana", "ana")

    # The API refuses the same inputs the other password bodies refuse…
    assert client.post("/auth/set-password", json={"new_password": "short"}, headers=_authed(token)).status_code == 422
    assert client.post("/auth/set-password", json={"new_password": ""}, headers=_authed(token)).status_code == 422
    assert client.post(
        "/auth/set-password", json={"new_password": "x" * 129}, headers=_authed(token)
    ).status_code == 422
    # …and the service applies validate_password itself for a skipped-validation caller.
    refused = auth_service.set_initial_password(db, account_id, "short")
    assert refused == {
        "ok": False,
        "error": "Password must be 8–128 characters.",
        "code": "weak_new",
    }
    assert _me(client, token)["has_password"] is False
    assert client.post("/auth/set-password", json={"new_password": "correct-horse-1"}).status_code == 401


def test_set_password_race_loses_to_the_hash_that_got_there_first(api, monkeypatch):
    """Two concurrent first-sets: one winner, and the loser's refusal is the usual 409."""
    from database.ledger.handle import TrainingLedger

    client, _db, _verifier = api
    token, _ = _google_account(client, "ana-token:Ana", "ana")

    real_get = TrainingLedger.get_password_hash
    real_set = TrainingLedger.set_password_hash
    raced = {"armed": True}

    def racing_get(self):
        if raced["armed"]:
            raced["armed"] = False
            # Another first-set request commits right between our "no password
            # yet" read and our write; it returns the pre-race answer all the
            # same, exactly as two requests racing through the old check would.
            real_set(self, auth_service.hash_password("racing-horse-99"))
            return None
        return real_get(self)

    monkeypatch.setattr(TrainingLedger, "get_password_hash", racing_get)

    lost = client.post("/auth/set-password", json={"new_password": "correct-horse-1"}, headers=_authed(token))
    assert lost.status_code == 409, lost.text
    assert "change-password" in lost.json()["detail"]
    assert _me(client, token)["has_password"] is True

    # The first password stands; the loser wrote nothing over it.
    assert client.post("/auth/login", json={"trainee_id": "ana", "password": "racing-horse-99"}).status_code == 200
    assert client.post("/auth/login", json={"trainee_id": "ana", "password": "correct-horse-1"}).status_code == 401


def test_connect_disconnect_and_first_password_do_not_bump_the_epoch_but_change_does(api):
    client, _db, _verifier = api

    # Connect and disconnect on an account that already has a password.
    pw_token = _password_account(client, "alice")
    before = _epoch(pw_token)
    linked = client.post("/auth/google/link", json={"id_token": "alice-google:A"}, headers=_authed(pw_token))
    assert linked.status_code == 200, linked.text
    assert _epoch(pw_token) == before
    assert client.delete("/auth/google/link", headers=_authed(pw_token)).status_code == 200
    assert _epoch(pw_token) == before

    # First password (and its disconnect) on a Google-only account.
    g_token, _ = _google_account(client, "ana-token:Ana", "ana")
    g_before = _epoch(g_token)
    assert client.post(
        "/auth/set-password", json={"new_password": "correct-horse-1"}, headers=_authed(g_token)
    ).status_code == 200
    assert _epoch(g_token) == g_before
    assert client.delete("/auth/google/link", headers=_authed(g_token)).status_code == 200
    assert _epoch(g_token) == g_before
    # Every session that performed those changes is still valid…
    assert client.get("/auth/me", headers=_authed(g_token)).status_code == 200

    # …while changing an existing password still revokes all sessions, as today.
    changed = client.post(
        "/auth/change-password",
        json={"current_password": "correct-horse-1", "new_password": "brand-new-horse-2"},
        headers=_authed(pw_token),
    )
    assert changed.status_code == 200, changed.text
    assert client.get("/auth/me", headers=_authed(pw_token)).status_code == 401


# --------------------------------------------------------------------------
# DELETE /auth/account with a Google proof


def test_delete_account_via_google_frees_the_subject_for_a_new_account(api):
    client, db, _verifier = api
    token, account_id = _google_account(client, "ana-token:Ana", "ana")

    deleted = client.request(
        "DELETE", "/auth/account", headers=_authed(token), json={"google_id_token": "ana-token:Ana"}
    )
    assert deleted.status_code == 200, deleted.text
    # The link went in the same catalog transaction as the account.
    assert _link_rows(db) == []
    assert client.get("/auth/me", headers=_authed(token)).json() == {"error": "account_deleted"}

    # The same Google identity can now create a brand-new MAYOS account.
    again = client.post("/auth/google", json={"id_token": "ana-token:Ana"})
    assert again.status_code == 200, again.text
    assert "signup_ticket" in again.json()
    completed = client.post(
        "/auth/google/complete",
        json={"signup_ticket": again.json()["signup_ticket"], "username": "ana"},
    )
    assert completed.status_code == 200, completed.text
    new_id = _subject(completed.json()["access_token"])
    assert new_id != account_id  # a new immutable account, never the deleted one
    assert _link_rows(db) == [("google", "sub-ana-token", new_id)]


def test_a_reused_username_never_inherits_a_link(api):
    client, db, _verifier = api
    token, account_id = _google_account(client, "ana-token:Ana", "ana")
    assert client.request(
        "DELETE", "/auth/account", headers=_authed(token), json={"google_id_token": "ana-token:Ana"}
    ).status_code == 200

    # Password registration takes the freed username as a fresh account.
    reused = _password_account(client, "ana")
    reused_id = _subject(reused)
    assert reused_id != account_id
    me = _me(client, reused)
    assert me["has_password"] is True
    assert me["linked_sign_ins"] == []
    assert _link_rows(db) == []
    # The Google subject still has no account: it must sign up again.
    assert "signup_ticket" in client.post("/auth/google", json={"id_token": "ana-token:Ana"}).json()


def test_deletion_via_google_refuses_stale_wrong_and_unverifiable_tokens(api):
    client, db, _verifier = api
    token, account_id = _google_account(client, "ana-token:Ana", "ana")
    headers = _authed(token)

    for id_token in ("stale-ana-token:Ana", "other-token:Other", "bad-signature"):
        attempt = client.request("DELETE", "/auth/account", headers=headers, json={"google_id_token": id_token})
        assert attempt.status_code == 400, (id_token, attempt.status_code, attempt.text)
        # Byte-identical to a wrong password: no hint about link, sub, or freshness.
        assert attempt.json() == {"detail": auth_service.INVALID_CREDENTIALS}

    wrong_password = client.request(
        "DELETE", "/auth/account", headers=headers, json={"password": "not-the-password"}
    )
    assert wrong_password.status_code == 400
    assert wrong_password.json() == {"detail": auth_service.INVALID_CREDENTIALS}

    # Everything survived every refusal.
    assert _me(client, token)["linked_sign_ins"] == ["google"]
    assert _link_rows(db) == [("google", "sub-ana-token", account_id)]
    assert client.app.state.test_db.list_account_deletions() == []


def test_delete_account_accepts_exactly_one_proof(api):
    client, _db, _verifier = api
    token, _ = _google_account(client, "ana-token:Ana", "ana")
    headers = _authed(token)

    assert client.request("DELETE", "/auth/account", headers=headers, json={}).status_code == 422
    both = client.request(
        "DELETE",
        "/auth/account",
        headers=headers,
        json={"password": "correct-horse-1", "google_id_token": "ana-token:Ana"},
    )
    assert both.status_code == 422
    assert client.get("/auth/me", headers=headers).status_code == 200  # nothing happened


def test_deletion_replay_also_clears_links(api):
    client, db, _verifier = api
    token, account_id = _google_account(client, "ana-token:Ana", "ana")
    assert client.request(
        "DELETE", "/auth/account", headers=_authed(token), json={"google_id_token": "ana-token:Ana"}
    ).status_code == 200

    # A restored catalog snapshot brings the row back; the durable record wins.
    db.link_sign_in("google", "sub-ana-token", account_id)
    assert len(_link_rows(db)) == 1
    db.reapply_deletions()
    assert _link_rows(db) == []


# --------------------------------------------------------------------------
# Password reset on a Google-only account


def test_password_reset_gives_a_google_only_account_a_password(api):
    client, db, _verifier = api
    token, _ = _google_account(client, "ana-token:Ana", "ana")

    assert _me(client, token)["has_password"] is False
    emailed = client.post("/auth/email", json={"email": "ana@example.com"}, headers=_authed(token))
    assert emailed.status_code == 200, emailed.text

    reset_service.request_password_reset(
        db,
        "ana@example.com",
        mailer=lambda to, link: True,
        token_factory=lambda: "recovery-token-abcdef123",
    )
    reset = client.post(
        "/auth/reset-password",
        json={"token": "recovery-token-abcdef123", "new_password": "brand-new-horse-2"},
    )
    assert reset.status_code == 200, reset.text

    login = client.post("/auth/login", json={"trainee_id": "ana", "password": "brand-new-horse-2"})
    assert login.status_code == 200, login.text
    # The Google link survived: the account kept both ways to sign in.
    fresh = client.post("/auth/google", json={"id_token": "ana-token:Ana"})
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["trainee_id"] == "ana"
    me = _me(client, fresh.json()["access_token"])
    assert me["has_password"] is True
    assert me["linked_sign_ins"] == ["google"]


# --------------------------------------------------------------------------
# Rate limits


def test_sign_in_method_mutations_share_the_password_rate_limit(api):
    client, _db, _verifier = api
    token, _ = _google_account(client, "ana-token:Ana", "ana")
    from svc.rate_limit import PASSWORD_LIMIT, limiter

    per_window = int(PASSWORD_LIMIT.split("/")[0])

    # Give it a password first, so every set-password below is a 409 and only
    # the limiter can stop the loop.
    assert client.post(
        "/auth/set-password", json={"new_password": "correct-horse-1"}, headers=_authed(token)
    ).status_code == 200
    limiter._storage.reset()

    statuses = [
        client.post("/auth/set-password", json={"new_password": "correct-horse-1"}, headers=_authed(token)).status_code
        for _ in range(per_window + 1)
    ]
    assert statuses.count(409) == per_window, statuses
    assert statuses[per_window] == 429, statuses

    # Disconnect shares the same budget rather than getting a free one.
    limiter._storage.reset()
    disconnect_statuses = [
        client.delete("/auth/google/link", headers=_authed(token)).status_code for _ in range(per_window + 1)
    ]
    assert disconnect_statuses.count(200) == per_window, disconnect_statuses
    assert disconnect_statuses[per_window] == 429
