"""Coach capability: owner issuance, authenticated redemption, and profile authz.

The issue's core guarantees: only an owner invitation enables coaching during
the closed trial; the invite is single-use, expiring, and bound to one immutable
account; the client body can never set ``is_coach``; and adding the capability
leaves the player's existing ledger and capability intact.
"""

import hashlib
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import coach as coach_service
from svc.app import create_app
from svc.dependencies import get_db

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


def _issue(db, username, **kwargs):
    result = coach_service.issue_coach_invite(db, username, **kwargs)
    assert result["ok"], result
    return result


def test_redeem_requires_authentication(api):
    client, db, _ = api
    _register(client, "alice")
    issued = _issue(db, "alice")
    assert client.post("/coach/invite/redeem", json={"token": issued["token"]}).status_code == 401


def test_public_self_upgrade_is_denied(api):
    """A player cannot acquire coaching without an owner invite."""
    client, db, _ = api
    registered = _register(client, "alice")
    headers = _authed(registered["access_token"])

    me = client.get("/auth/me", headers=headers)
    assert me.json()["capabilities"] == {"player": True, "coach": False}

    # Coach surfaces are closed to a non-coach, and the body cannot promote.
    assert client.get("/coach/profile", headers=headers).status_code == 403
    assert (
        client.put(
            "/coach/profile",
            headers=headers,
            json={"display_name": "Coach Alice", "bio": "", "specialization": "", "capacity": 5},
        ).status_code
        == 403
    )
    assert client.get("/auth/me", headers=headers).json()["capabilities"]["coach"] is False

    # Issuance is deliberately CLI-only: no public HTTP endpoint mints invites.
    assert client.post("/coach/invite", headers=headers, json={"trainee_id": "alice"}).status_code == 404
    assert client.post("/coach/invite", json={"trainee_id": "alice"}).status_code == 404


def test_coach_gate_checks_registry_before_mounting_ledger(api, monkeypatch):
    """ADR 015: a valid non-coach is refused 403 without its ledger being opened."""
    import svc.dependencies as dependencies

    client, db, _ = api
    mounted: list[str] = []
    real_bind_user = dependencies.bind_user

    def spy(db_arg, trainee_id):
        mounted.append(str(trainee_id))
        return real_bind_user(db_arg, trainee_id)

    monkeypatch.setattr(dependencies, "bind_user", spy)

    registered = _register(client, "alice")
    headers = _authed(registered["access_token"])
    assert client.get("/coach/profile", headers=headers).status_code == 403
    assert mounted == []

    issued = _issue(db, "alice")
    assert client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code == 200
    mounted.clear()
    assert client.get("/coach/profile", headers=headers).status_code == 200
    assert mounted == ["alice"]


def test_coach_route_still_rejects_a_revoked_token(api):
    """The registry gate must not skip the ledger-side jti revocation check."""
    client, db, _ = api
    registered = _register(client, "alice")
    headers = _authed(registered["access_token"])
    issued = _issue(db, "alice")
    assert client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code == 200
    assert client.get("/coach/profile", headers=headers).status_code == 200

    assert client.post("/auth/logout", headers=headers).status_code == 204
    assert client.get("/coach/profile", headers=headers).status_code == 401


def test_owner_issued_invite_grants_capability_without_reissuing_token(api):
    client, db, _ = api
    registered = _register(client, "alice")
    token = registered["access_token"]
    headers = _authed(token)
    account_id = _subject(token)

    issued = _issue(db, "alice")
    assert issued["account_id"] == account_id

    redeemed = client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]})
    assert redeemed.status_code == 200, redeemed.text
    assert redeemed.json() == {
        "account_id": account_id,
        "trainee_id": "alice",
        "capabilities": {"player": True, "coach": True},
    }

    # The same bearer token now sees the live capability (registry-driven).
    me = client.get("/auth/me", headers=headers)
    assert me.json()["capabilities"] == {"player": True, "coach": True}


def test_invite_is_bound_to_the_invited_account(api):
    client, db, _ = api
    _register(client, "alice")
    bob = _register(client, "bob")
    issued = _issue(db, "alice")

    # Bob's valid session cannot redeem Alice's code, and the attempt must not
    # burn it: Alice can still redeem.
    bob_headers = _authed(bob["access_token"])
    denied = client.post("/coach/invite/redeem", headers=bob_headers, json={"token": issued["token"]})
    assert denied.status_code == 400
    assert client.get("/auth/me", headers=bob_headers).json()["capabilities"]["coach"] is False

    alice_headers = _authed(_login(client, "alice")["access_token"])
    redeemed = client.post("/coach/invite/redeem", headers=alice_headers, json={"token": issued["token"]})
    assert redeemed.status_code == 200, redeemed.text


def _login(client, username, password="correct-horse-1"):
    resp = client.post("/auth/login", json={"trainee_id": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_expired_invite_is_rejected(api):
    client, db, _ = api
    registered = _register(client, "alice")
    headers = _authed(registered["access_token"])
    account_id = _subject(registered["access_token"])

    raw = "expired-invite-token-abcdef"
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    db.create_coach_invite(hashlib.sha256(raw.encode()).hexdigest(), account_id, past)

    denied = client.post("/coach/invite/redeem", headers=headers, json={"token": raw})
    assert denied.status_code == 400
    assert denied.json()["detail"] == coach_service.GENERIC_INVITE_ERROR
    assert client.get("/auth/me", headers=headers).json()["capabilities"]["coach"] is False


def test_used_invite_cannot_be_replayed(api):
    client, db, _ = api
    registered = _register(client, "alice")
    headers = _authed(registered["access_token"])
    issued = _issue(db, "alice")

    assert client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code == 200
    replay = client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]})
    assert replay.status_code == 400
    assert replay.json()["detail"] == coach_service.GENERIC_INVITE_ERROR


def test_redeem_is_atomic_under_concurrency(api):
    _, db, _ = api
    _register_for(db, "alice")
    account = db.get_active_account_by_username("alice")
    issued = _issue(db, "alice")
    token_hash = hashlib.sha256(issued["token"].encode()).hexdigest()
    now = datetime.now(UTC).isoformat()

    results = []
    lock = threading.Lock()

    def worker():
        outcome = db.redeem_coach_invite(token_hash, account["account_id"], now, coach_service.DEFAULT_CAPACITY)
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(1 for outcome in results if outcome is not None) == 1


def _register_for(db, username):
    """Creates a registry account + ledger without going through HTTP."""
    account_id = db.create_account(username)
    assert account_id is not None
    db.switch_user(username)


def test_player_data_is_retained_when_coach_capability_is_added(api):
    client, db, users_dir = api
    registered = _register(client, "alice")
    headers = _authed(registered["access_token"])
    account_id = _subject(registered["access_token"])

    assert client.put("/profile", json={"current_goal": "Strength"}, headers=headers).status_code == 200
    ledger_before = (users_dir / "alice.db").read_bytes()

    issued = _issue(db, "alice")
    assert client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code == 200

    # Same immutable account, still a player, and the ledger is untouched.
    account = db.get_account(account_id)
    assert account["is_player"] is True and account["is_coach"] is True
    assert client.get("/profile", headers=headers).json()["current_goal"] == "Strength"
    assert (users_dir / "alice.db").read_bytes() == ledger_before


def test_coach_profile_defaults_and_roundtrip(api):
    client, db, _ = api
    registered = _register(client, "alice")
    headers = _authed(registered["access_token"])
    issued = _issue(db, "alice")
    client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]})

    profile = client.get("/coach/profile", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["display_name"] == "alice"
    assert profile.json()["capacity"] == coach_service.DEFAULT_CAPACITY

    updated = client.put(
        "/coach/profile",
        headers=headers,
        json={
            "display_name": "Coach Alice",
            "bio": "Strength and conditioning.",
            "specialization": "Powerlifting",
            "capacity": 12,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json() == {
        "account_id": _subject(registered["access_token"]),
        "display_name": "Coach Alice",
        "bio": "Strength and conditioning.",
        "specialization": "Powerlifting",
        "capacity": 12,
    }
    assert client.get("/coach/profile", headers=headers).json()["capacity"] == 12


def test_coach_profile_validation_bounds(api):
    client, db, _ = api
    registered = _register(client, "alice")
    headers = _authed(registered["access_token"])
    issued = _issue(db, "alice")
    client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]})

    def put(**overrides):
        body = {"display_name": "Coach", "bio": "", "specialization": "", "capacity": 5}
        body.update(overrides)
        return client.put("/coach/profile", headers=headers, json=body)

    assert put(capacity=0).status_code == 422
    assert put(capacity=coach_service.MAX_CAPACITY + 1).status_code == 422
    assert put(display_name="").status_code == 422
    assert put(display_name="   ").status_code == 400
    assert put(bio="x" * (coach_service.MAX_BIO + 1)).status_code == 422
    assert put(specialization="x" * (coach_service.MAX_SPECIALIZATION + 1)).status_code == 422


def test_coach_profile_revocation_fails_closed(api):
    client, db, _ = api
    registered = _register(client, "alice")
    headers = _authed(registered["access_token"])
    account_id = _subject(registered["access_token"])
    issued = _issue(db, "alice")
    client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]})
    assert client.get("/coach/profile", headers=headers).status_code == 200

    with db._catalog_lock:
        db.catalog_conn.execute("UPDATE accounts SET is_coach = 0 WHERE account_id = ?", (account_id,))
        db.catalog_conn.commit()
    assert client.get("/coach/profile", headers=headers).status_code == 403


def test_invite_store_keeps_only_a_hash(api):
    client, db, _ = api
    _register(client, "alice")
    issued = _issue(db, "alice")

    with db._catalog_lock:
        rows = db.catalog_conn.execute("SELECT token_hash FROM coach_invites").fetchall()
    stored = {row[0] for row in rows}
    assert issued["token"] not in stored
    assert hashlib.sha256(issued["token"].encode()).hexdigest() in stored


def test_invite_for_deleted_account_is_refused(api):
    client, db, _ = api
    registered = _register(client, "alice")
    account_id = _subject(registered["access_token"])
    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE accounts SET deleted_at = ? WHERE account_id = ?",
            (datetime.now(UTC).isoformat(), account_id),
        )
        db.catalog_conn.commit()
    result = coach_service.issue_coach_invite(db, "alice")
    assert result["ok"] is False


def test_invite_ttl_rejects_nonpositive_values(api):
    _, db, _ = api
    _register_for(db, "alice")
    for bad in (0, -1, -1440):
        result = coach_service.issue_coach_invite(db, "alice", ttl_minutes=bad)
        assert result["ok"] is False, bad
        assert "positive" in result["error"]


def test_invite_ttl_is_clamped_to_documented_bounds(api):
    _, db, _ = api
    _register_for(db, "alice")
    now = datetime.now(UTC)
    low = coach_service.issue_coach_invite(db, "alice", ttl_minutes=1)
    high = coach_service.issue_coach_invite(db, "alice", ttl_minutes=10**9)
    assert low["ok"] and high["ok"]
    assert datetime.fromisoformat(low["expires_at"]) >= now + timedelta(
        minutes=coach_service.MIN_INVITE_TTL_MINUTES - 1
    )
    assert datetime.fromisoformat(high["expires_at"]) <= now + timedelta(
        minutes=coach_service.MAX_INVITE_TTL_MINUTES + 1
    )


@pytest.mark.parametrize("value", ["0", "-5"])
def test_cli_rejects_nonpositive_ttl(value):
    from scripts.issue_coach_invite import main

    with pytest.raises(SystemExit) as exc:
        main(["alice", f"--ttl-minutes={value}"])
    assert exc.value.code == 2
