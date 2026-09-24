"""Assignment lifecycle contract tests (ticket #24).

Exercises the public FastAPI surface against real temporary SQLite catalogs and
player ledgers with a mocked model. Covers expiry, replay, atomic single-use and
capacity races, self assignment, explicit consent, one-active-assignment-per-player,
notice/email privacy, revocation, and dual-capability continuity.
"""

import hashlib
import logging
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import assignments as assignment_service
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


def _login(client, username, password="correct-horse-1"):
    resp = client.post("/auth/login", json={"trainee_id": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _subject(token):
    return pyjwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])["sub"]


def _make_coach(client, db, username, capacity=10, email=None):
    """Registers a player, grants coach capability via an owner invite, sets capacity."""
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username)
    assert issued["ok"], issued
    assert client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code == 200
    assert (
        client.put(
            "/coach/profile",
            headers=headers,
            json={"display_name": f"Coach {username}", "bio": "b", "specialization": "s", "capacity": capacity},
        ).status_code
        == 200
    )
    if email:
        db.set_trainee_email(username, email)
    return headers, registered["access_token"], _subject(registered["access_token"])


def _issue(client, coach_headers):
    resp = client.post("/coach/assignments/invites", headers=coach_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _preview(client, player_headers, token):
    return client.post("/assignments/invites/preview", headers=player_headers, json={"token": token})


def _redeem(client, player_headers, token, consent=True):
    return client.post(
        "/assignments/invites/redeem", headers=player_headers, json={"token": token, "consent": consent}
    )


def _two_catalog_connections(tmp_path, monkeypatch):
    """Two independent DatabaseManager instances (and SQLite connections) over one catalog."""
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)

    def build():
        monkeypatch.setattr(DatabaseManager, "_instance", None)
        monkeypatch.setattr(DatabaseManager, "_local", threading.local())
        return DatabaseManager(
            catalog_path=tmp_path / "catalog.db",
            users_dir=tmp_path / "users",
            backups_dir=tmp_path / "backups",
            active_user="bootstrap",
        )

    return build(), build()


def _seed_coach_with_players(db, coach_name, capacity, invite_tokens, player_names):
    """Creates a live coach (with capacity) and players directly in the catalog."""
    coach_id = db.create_account(coach_name)
    assert coach_id is not None
    with db._catalog_lock:
        db.catalog_conn.execute("UPDATE accounts SET is_coach = 1 WHERE account_id = ?", (coach_id,))
        db.catalog_conn.commit()
    db.upsert_coach_profile(
        coach_id, {"display_name": coach_name, "bio": "", "specialization": "", "capacity": capacity}
    )
    expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    for token in invite_tokens:
        db.create_assignment_invite(hashlib.sha256(token.encode()).hexdigest(), coach_id, expires)
    player_ids = [db.create_account(name) for name in player_names]
    return coach_id, player_ids


# --------------------------------------------------------------------------
# Issuance
# --------------------------------------------------------------------------


def test_issue_requires_coach_capability(api):
    client, _, _ = api
    registered = _register(client, "bob")
    resp = client.post("/coach/assignments/invites", headers=_authed(registered["access_token"]))
    assert resp.status_code == 403


def test_issue_requires_authentication(api):
    client, _, _ = api
    assert client.post("/coach/assignments/invites").status_code == 401


def test_issued_code_is_capacity_bound_and_hashed_at_rest(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    issued = _issue(client, coach_headers)
    assert issued["capacity"] == 5
    assert issued["active_assignments"] == 0
    assert len(issued["token"]) > 20

    # Default expiry is three days (within a minute of issuance).
    expires = datetime.fromisoformat(issued["expires_at"])
    assert timedelta(days=3) - timedelta(minutes=1) <= expires - datetime.now(UTC) <= timedelta(days=3, minutes=1)

    with db._catalog_lock:
        rows = db.catalog_conn.execute("SELECT token_hash FROM assignment_invites").fetchall()
    stored = {row[0] for row in rows}
    assert issued["token"] not in stored
    assert hashlib.sha256(issued["token"].encode()).hexdigest() in stored


def test_issue_refused_when_roster_is_full(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=1)
    token = _issue(client, coach_headers)["token"]
    player = _register(client, "p1")
    assert _redeem(client, _authed(player["access_token"]), token).status_code == 200

    denied = client.post("/coach/assignments/invites", headers=coach_headers)
    assert denied.status_code == 400
    assert denied.json()["detail"] == assignment_service.ROSTER_FULL_ERROR


# --------------------------------------------------------------------------
# Preview (no consumption)
# --------------------------------------------------------------------------


def test_preview_reveals_coach_identity_and_access_without_consuming(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    token = _issue(client, coach_headers)["token"]
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    preview = _preview(client, headers, token)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["coach"]["display_name"] == "Coach coach"
    assert body["access"]["scope"] == assignment_service.ACCESS_SCOPE
    assert body["access"]["includes_current_history"] is True
    assert body["access"]["includes_historical_history"] is True
    assert body["access"]["active_while_assigned"] is True

    # Preview is read-only: the same code still previews and redeems.
    assert _preview(client, headers, token).status_code == 200
    assert _redeem(client, headers, token).status_code == 200


def test_preview_rejects_self_assignment(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    token = _issue(client, coach_headers)["token"]
    denied = _preview(client, coach_headers, token)
    assert denied.status_code == 400
    assert denied.json()["detail"] == assignment_service.SELF_ASSIGNMENT_ERROR


def test_redeem_rejects_self_assignment(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    token = _issue(client, coach_headers)["token"]
    denied = _redeem(client, coach_headers, token)
    assert denied.status_code == 400
    assert denied.json()["detail"] == assignment_service.SELF_ASSIGNMENT_ERROR


def test_preview_rejects_unknown_and_expired_codes(api):
    client, db, _ = api
    _make_coach(client, db, "coach", capacity=5)
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    assert _preview(client, headers, "z" * 24).status_code == 400

    raw = "expired-assignment-token-abc"
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    coach = db.get_active_account_by_username("coach")
    db.create_assignment_invite(hashlib.sha256(raw.encode()).hexdigest(), coach["account_id"], past)
    expired = _preview(client, headers, raw)
    assert expired.status_code == 400
    assert expired.json()["detail"] == assignment_service.GENERIC_INVITE_ERROR


def test_preview_rejected_when_coach_capability_is_revoked(api):
    client, db, _ = api
    coach_headers, _, coach_account = _make_coach(client, db, "coach", capacity=5)
    token = _issue(client, coach_headers)["token"]
    with db._catalog_lock:
        db.catalog_conn.execute("UPDATE accounts SET is_coach = 0 WHERE account_id = ?", (coach_account,))
        db.catalog_conn.commit()

    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    denied = _preview(client, headers, token)
    assert denied.status_code == 400
    assert denied.json()["detail"] == assignment_service.GENERIC_INVITE_ERROR


# --------------------------------------------------------------------------
# Consent + redemption
# --------------------------------------------------------------------------


def test_redeem_requires_explicit_consent(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    token = _issue(client, coach_headers)["token"]
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    denied = _redeem(client, headers, token, consent=False)
    assert denied.status_code == 400
    assert denied.json()["detail"] == assignment_service.CONSENT_REQUIRED_ERROR
    assert client.get("/assignments/me", headers=headers).json() is None
    # The code was not consumed and can still be redeemed with consent.
    assert _redeem(client, headers, token, consent=True).status_code == 200


def test_account_ids_in_body_are_ignored(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    token = _issue(client, coach_headers)["token"]
    player = _register(client, "p1")
    other = _register(client, "p2")
    headers = _authed(player["access_token"])

    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=headers,
        json={
            "token": token,
            "consent": True,
            "account_id": _subject(other["access_token"]),
            "player_account_id": "spoofed",
        },
    )
    assert redeemed.status_code == 200
    # The JWT account got the assignment; the spoofed account did not.
    assert client.get("/assignments/me", headers=headers).json()["status"] == "active"
    assert client.get("/assignments/me", headers=_authed(other["access_token"])).json() is None


def test_redeem_binds_immediately_and_creates_coach_notice(api, monkeypatch):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5, email="coach@example.com")
    token = _issue(client, coach_headers)["token"]
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    calls = []

    def _record(to_email, coach_display_name, player_username):
        calls.append((to_email, coach_display_name, player_username))
        return True

    monkeypatch.setattr(assignment_service, "send_assignment_redemption_email", _record)

    redeemed = _redeem(client, headers, token)
    assert redeemed.status_code == 200, redeemed.text
    body = redeemed.json()
    assert body["assignment"]["status"] == "active"
    assert body["assignment"]["coach"]["display_name"] == "Coach coach"
    assert body["notices_created"] == 1
    assert body["email_sent"] is True
    assert calls == [("coach@example.com", "Coach coach", "p1")]

    # Player sees the active assignment immediately.
    me = client.get("/assignments/me", headers=headers).json()
    assert me["assignment_id"] == body["assignment"]["assignment_id"]
    assert me["coach"]["display_name"] == "Coach coach"

    # Coach sees the in-app notice and the roster identity (no training data).
    notices = client.get("/coach/assignments/notices", headers=coach_headers).json()["notices"]
    assert len(notices) == 1
    assert notices[0]["kind"] == "assignment_redeemed"
    assert "p1" in notices[0]["message"]
    roster = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    assert roster == [
        {
            "assignment_id": body["assignment"]["assignment_id"],
            "player_username": "p1",
            "started_at": body["assignment"]["started_at"],
            "status": "active",
        }
    ]


def test_email_transport_failure_does_not_roll_back_assignment(api, monkeypatch):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5, email="coach@example.com")
    token = _issue(client, coach_headers)["token"]
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    def _boom(*_args, **_kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(assignment_service, "send_assignment_redemption_email", _boom)

    redeemed = _redeem(client, headers, token)
    assert redeemed.status_code == 200, redeemed.text
    assert redeemed.json()["email_sent"] is False
    assert client.get("/assignments/me", headers=headers).json()["status"] == "active"


def test_email_notice_is_generic_and_contains_no_training_data(caplog):
    from service.email_sender import send_assignment_redemption_email

    assert send_assignment_redemption_email("coach@example.com", "Coach Coach", "p1") is True
    with caplog.at_level(logging.INFO, logger="service.email_sender"):
        send_assignment_redemption_email("coach@example.com", "Coach Coach", "p1")
    text = caplog.text
    assert "p1" in text
    for leak in ("bench", "reps", "volume", "e1RM", "personal record", "session_id"):
        assert leak not in text


def test_used_code_cannot_be_replayed(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    token = _issue(client, coach_headers)["token"]
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    assert _redeem(client, headers, token).status_code == 200

    replay = _redeem(client, headers, token)
    assert replay.status_code == 400
    assert replay.json()["detail"] == assignment_service.GENERIC_INVITE_ERROR


def test_expired_code_cannot_be_redeemed(api):
    client, db, _ = api
    _make_coach(client, db, "coach", capacity=5)
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    raw = "expired-assignment-token-xyz"
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    coach = db.get_active_account_by_username("coach")
    db.create_assignment_invite(hashlib.sha256(raw.encode()).hexdigest(), coach["account_id"], past)
    denied = _redeem(client, headers, raw)
    assert denied.status_code == 400
    assert denied.json()["detail"] == assignment_service.GENERIC_INVITE_ERROR


def test_second_active_assignment_is_rejected(api):
    client, db, _ = api
    coach_a_headers, _, _ = _make_coach(client, db, "coacha", capacity=5)
    coach_b_headers, _, _ = _make_coach(client, db, "coachb", capacity=5)
    first = _issue(client, coach_a_headers)["token"]
    second = _issue(client, coach_b_headers)["token"]
    player = _register(client, "p1")
    headers = _authed(player["access_token"])

    assert _redeem(client, headers, first).status_code == 200

    preview = _preview(client, headers, second)
    assert preview.status_code == 400
    assert preview.json()["detail"] == assignment_service.ALREADY_ASSIGNED_ERROR

    denied = _redeem(client, headers, second)
    assert denied.status_code == 400
    assert denied.json()["detail"] == assignment_service.ALREADY_ASSIGNED_ERROR
    # The losing coach's code was not burned by the rejected attempt.
    assert _preview(client, headers, second).status_code == 400


# --------------------------------------------------------------------------
# Atomicity / races
# --------------------------------------------------------------------------


def test_single_use_claim_is_atomic_under_concurrency(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    token = _issue(client, coach_headers)["token"]
    player = _register(client, "p1")
    account_id = _subject(player["access_token"])
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(UTC).isoformat()

    results = []
    lock = threading.Lock()

    def worker():
        outcome = db.redeem_assignment_invite(token_hash, account_id, now)
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(1 for outcome in results if outcome["ok"]) == 1


def test_capacity_check_is_atomic_under_concurrency(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=1)
    first = _issue(client, coach_headers)["token"]
    second = _issue(client, coach_headers)["token"]
    p1 = _register(client, "p1")
    p2 = _register(client, "p2")
    now = datetime.now(UTC).isoformat()

    results = []
    lock = threading.Lock()

    def worker(token, account_id):
        outcome = db.redeem_assignment_invite(hashlib.sha256(token.encode()).hexdigest(), account_id, now)
        with lock:
            results.append(outcome)

    threads = [
        threading.Thread(target=worker, args=(first, _subject(p1["access_token"]))),
        threading.Thread(target=worker, args=(second, _subject(p2["access_token"]))),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [outcome for outcome in results if outcome["ok"]]
    losers = [outcome for outcome in results if not outcome["ok"]]
    assert len(winners) == 1
    assert len(losers) == 1
    assert losers[0]["reason"] == "capacity"


def test_capacity_is_enforced_across_two_catalog_connections(tmp_path, monkeypatch):
    """Two processes/connections cannot both fill the last roster slot (BEGIN IMMEDIATE)."""
    db1, db2 = _two_catalog_connections(tmp_path, monkeypatch)
    coach_id, (first_player, second_player) = _seed_coach_with_players(
        db1, "coach", 1, ["capacity-token-a-123456", "capacity-token-b-123456"], ["p1", "p2"]
    )
    now = datetime.now(UTC).isoformat()
    barrier = threading.Barrier(2)
    results = []
    lock = threading.Lock()

    def worker(manager, raw_token, player_id):
        barrier.wait()
        outcome = manager.redeem_assignment_invite(
            hashlib.sha256(raw_token.encode()).hexdigest(), player_id, now
        )
        with lock:
            results.append(outcome)

    threads = [
        threading.Thread(target=worker, args=(db1, "capacity-token-a-123456", first_player)),
        threading.Thread(target=worker, args=(db2, "capacity-token-b-123456", second_player)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len([outcome for outcome in results if outcome["ok"]]) == 1, results
    assert db1.count_active_assignments_for_coach(coach_id) == 1
    db1.catalog_conn.close()
    db2.catalog_conn.close()


def test_disable_and_redeem_cannot_leave_an_active_assignment(tmp_path, monkeypatch):
    """Disable is one transaction: no assignment stays active under a disabled coach."""
    db1, db2 = _two_catalog_connections(tmp_path, monkeypatch)
    now = datetime.now(UTC).isoformat()
    for index in range(10):
        raw_token = f"disable-token-{index}-1234567890"
        coach_id, (player_id,) = _seed_coach_with_players(
            db1, f"coach{index}", 5, [raw_token], [f"player{index}"]
        )
        barrier = threading.Barrier(2)
        outcomes = {}
        lock = threading.Lock()

        def redeem():
            barrier.wait()
            outcome = db2.redeem_assignment_invite(
                hashlib.sha256(raw_token.encode()).hexdigest(), player_id, now
            )
            with lock:
                outcomes["redeem"] = outcome

        def disable():
            barrier.wait()
            outcome = db1.disable_coach_account(coach_id, now, "coach_capability_disabled")
            with lock:
                outcomes["disable"] = outcome

        threads = [threading.Thread(target=redeem), threading.Thread(target=disable)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        account = db1.get_account(coach_id)
        assignment = db1.get_active_assignment_for_player(player_id)
        assert account["is_coach"] is False, (index, outcomes)
        assert assignment is None, (index, outcomes, assignment)
    db1.catalog_conn.close()
    db2.catalog_conn.close()


def test_raw_invite_token_is_never_logged(api, monkeypatch, caplog):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    with caplog.at_level(logging.DEBUG):
        token = _issue(client, coach_headers)["token"]
        assert _redeem(client, headers, token).status_code == 200
    assert token not in caplog.text


# --------------------------------------------------------------------------
# Ending an assignment
# --------------------------------------------------------------------------


def test_coach_can_revoke_and_access_ends_immediately(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    token = _issue(client, coach_headers)["token"]
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    redeemed = _redeem(client, headers, token).json()
    assignment_id = redeemed["assignment"]["assignment_id"]

    revoked = client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "ended"
    assert client.get("/assignments/me", headers=headers).json() is None
    assert client.get("/coach/assignments", headers=coach_headers).json()["assignments"] == []


def test_player_can_end_assignment(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    token = _issue(client, coach_headers)["token"]
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    assert _redeem(client, headers, token).status_code == 200

    ended = client.post("/assignments/me/end", headers=headers)
    assert ended.status_code == 200, ended.text
    assert ended.json()["status"] == "ended"
    assert client.get("/assignments/me", headers=headers).json() is None
    assert client.get("/coach/assignments", headers=coach_headers).json()["assignments"] == []


def test_non_participant_cannot_revoke(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    other_headers, _, _ = _make_coach(client, db, "intruder", capacity=5)
    token = _issue(client, coach_headers)["token"]
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    assignment_id = _redeem(client, headers, token).json()["assignment"]["assignment_id"]

    denied = client.post(f"/coach/assignments/{assignment_id}/revoke", headers=other_headers)
    assert denied.status_code == 403
    assert client.get("/assignments/me", headers=headers).json()["status"] == "active"


def test_player_cannot_end_someone_elses_assignment(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    token = _issue(client, coach_headers)["token"]
    player = _register(client, "p1")
    bystander = _register(client, "bystander")
    assert _redeem(client, _authed(player["access_token"]), token).status_code == 200

    denied = client.post("/assignments/me/end", headers=_authed(bystander["access_token"]))
    assert denied.status_code == 400
    assert client.get("/assignments/me", headers=_authed(player["access_token"])).json()["status"] == "active"


def test_end_requires_authentication(api):
    client, _, _ = api
    assert client.post("/assignments/me/end").status_code == 401
    assert client.get("/coach/assignments").status_code == 401
    assert client.get("/coach/assignments/notices").status_code == 401


# --------------------------------------------------------------------------
# Dual capability continuity
# --------------------------------------------------------------------------


def test_disabling_coach_capability_ends_assignments_and_preserves_player_data(api):
    client, db, users_dir = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    # The coach also trains; own player data must survive disabling coaching.
    assert client.put("/profile", json={"current_goal": "Strength"}, headers=coach_headers).status_code == 200
    assert (users_dir / "coach.db").exists()

    token = _issue(client, coach_headers)["token"]
    player = _register(client, "p1")
    headers = _authed(player["access_token"])
    assert _redeem(client, headers, token).status_code == 200

    disabled = client.post("/coach/capability/disable", headers=coach_headers)
    assert disabled.status_code == 200, disabled.text
    assert disabled.json() == {"coach": False, "ended_assignments": 1}

    # Assignment ended immediately for the player; coach surface now closed.
    assert client.get("/assignments/me", headers=headers).json() is None
    assert client.get("/coach/profile", headers=coach_headers).status_code == 403
    assert client.get("/coach/assignments", headers=coach_headers).status_code == 403

    # The account is still a player with its training data intact.
    me = client.get("/auth/me", headers=coach_headers).json()
    assert me["capabilities"] == {"player": True, "coach": False}
    assert client.get("/profile", headers=coach_headers).json()["current_goal"] == "Strength"


def test_being_assigned_does_not_remove_a_players_coach_capability(api):
    client, db, _ = api
    # "dual" is a coach who is also a player; another coach assigns dual as a player.
    dual_headers, _, _ = _make_coach(client, db, "dual", capacity=5)
    other_headers, _, _ = _make_coach(client, db, "other", capacity=5)
    token = _issue(client, other_headers)["token"]

    assert _redeem(client, dual_headers, token).status_code == 200
    assert client.get("/assignments/me", headers=dual_headers).json()["status"] == "active"
    # Dual retains its own coaching capability and can still list its own roster.
    me = client.get("/auth/me", headers=dual_headers).json()
    assert me["capabilities"] == {"player": True, "coach": True}
    assert client.get("/coach/assignments", headers=dual_headers).status_code == 200


def test_notices_can_be_marked_read(api):
    client, db, _ = api
    coach_headers, _, _ = _make_coach(client, db, "coach", capacity=5)
    token = _issue(client, coach_headers)["token"]
    player = _register(client, "p1")
    assert _redeem(client, _authed(player["access_token"]), token).status_code == 200

    marked = client.post("/coach/assignments/notices/read", headers=coach_headers)
    assert marked.status_code == 200
    assert marked.json()["marked_read"] == 1
    notices = client.get("/coach/assignments/notices", headers=coach_headers).json()["notices"]
    assert notices[0]["read_at"] is not None
