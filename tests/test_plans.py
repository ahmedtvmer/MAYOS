"""Server-owned Lifter/Coach plan states (issue #56).

Exercises the public FastAPI contract against a temporary real catalog and real
player ledgers. Covers single- and dual-capability defaults, independence, the
immutable-account key, capability gating, and data preservation across a
server-verified plan change. `service.plans.set_plan` stands in for the later
subscription tickets' internal grant; there is no public plan-change route and
no billing path.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import plans as plans_service
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
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.execute("INSERT INTO exercises (id, name) VALUES ('sq', 'Squat'), ('bp', 'Bench Press'), ('row', 'Row')")
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
            yield client, db, tmp_path / "users"
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(client, username, password="correct-horse-1"):
    resp = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _subject(token):
    return pyjwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])["sub"]


def _plans(client, headers):
    resp = client.get("/auth/me", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["plans"]


def _make_coach(client, db, username):
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username)
    assert issued["ok"], issued
    resp = client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]})
    assert resp.status_code == 200, resp.text
    return headers, registered["access_token"], resp.json()


def _saved_split_payload():
    return {
        "program_name": "Saved Split",
        "weekly_frequency": 3,
        "split_type": "Full Body",
        "days": [
            {
                "day_name": "Full A",
                "day_order": 1,
                "exercises": [
                    {"exercise_id": "sq", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                    {"exercise_id": "bp", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                    {"exercise_id": "row", "target_sets": 3, "target_reps_min": 5, "target_reps_max": 8, "target_rpe": 8.5},
                ],
            }
        ],
    }


def _session_payload():
    return {
        "day_order": 1,
        "readiness": 4,
        "session_notes": "",
        "sets": [
            {
                "exercise": {
                    "exercise_id": "sq",
                    "exercise_name": "Squat",
                    "target_sets": 3,
                    "target_reps_min": 5,
                    "target_reps_max": 8,
                    "target_rpe": 8.5,
                    "rest_seconds": 120,
                    "notes": None,
                },
                "sets": [{"weight_kg": 100.0, "reps": 5, "rpe": 8.0}],
            }
        ],
    }


def test_single_capability_player_defaults_to_lifter_free(api):
    client, _, _ = api
    alice = _register(client, "alice")

    body = client.get("/auth/me", headers=_authed(alice["access_token"])).json()
    assert body["capabilities"] == {"player": True, "coach": False}
    assert body["plans"]["lifter"] == {"plan": "free", "status": "active"}
    assert body["plans"]["coach"] is None


def test_dual_capability_account_holds_independent_free_plans(api):
    client, db, _ = api
    headers, _, redeemed = _make_coach(client, db, "alice")

    # The redemption response carries the same account contract as /auth/me.
    assert redeemed["capabilities"] == {"player": True, "coach": True}
    assert redeemed["plans"]["lifter"] == {"plan": "free", "status": "active"}
    assert redeemed["plans"]["coach"] == {"plan": "free", "status": "active"}

    assert _plans(client, headers) == {
        "lifter": {"plan": "free", "status": "active"},
        "coach": {"plan": "free", "status": "active"},
    }


def test_plan_state_is_keyed_to_the_immutable_account(api):
    client, db, _ = api
    alice = _register(client, "alice")
    bob = _register(client, "bob")
    alice_headers = _authed(alice["access_token"])
    bob_headers = _authed(bob["access_token"])

    result = plans_service.set_plan(db, _subject(alice["access_token"]), "lifter", "pro")
    assert result["ok"], result

    assert _plans(client, alice_headers)["lifter"]["plan"] == "pro"
    assert _plans(client, bob_headers)["lifter"]["plan"] == "free"


def test_reused_username_does_not_inherit_deleted_accounts_plan(api):
    client, db, ledgers_dir = api
    original = _register(client, "alice")
    original_id = _subject(original["access_token"])
    assert plans_service.set_plan(db, original_id, "lifter", "pro")["ok"]

    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE accounts SET status = 'deleted', deleted_at = ? WHERE account_id = ?",
            (datetime.now(UTC).isoformat(), original_id),
        )
        db.catalog_conn.commit()
    (ledgers_dir / "alice.db").unlink(missing_ok=True)

    replacement = _register(client, "alice")
    replacement_id = _subject(replacement["access_token"])
    assert replacement_id != original_id
    assert plans_service.read_plans(db, replacement_id)["lifter"] == {
        "plan": "free",
        "status": "active",
    }
    assert client.get("/auth/me", headers=_authed(original["access_token"])).status_code == 401


def test_plan_grant_requires_the_matching_capability(api):
    client, db, _ = api
    alice = _register(client, "alice")
    headers = _authed(alice["access_token"])

    result = plans_service.set_plan(db, _subject(alice["access_token"]), "coach", "pro")
    assert result["ok"] is False
    assert _plans(client, headers)["coach"] is None


def test_plan_change_preserves_account_program_history_and_assignment(api):
    client, db, _ = api
    alice_headers, _, _ = _make_coach(client, db, "alice")
    alice_id = db.get_active_account_by_username("alice")["account_id"]
    bob = _register(client, "bob")
    bob_headers = _authed(bob["access_token"])

    # Alice's own program and committed training history.
    db.switch_user("alice")
    db.ledger.upsert_player_profile({"current_goal": "Strength"})
    db.ledger.save_training_program(_saved_split_payload())
    commit = client.post("/workouts/sessions", headers=alice_headers, json=_session_payload())
    assert commit.status_code == 201, commit.text
    # The first session is the exercise's baseline, so a heavier second session
    # is what puts a personal record on the shelf (ADR 042).
    heavier = _session_payload()
    heavier["sets"][0]["sets"] = [{"weight_kg": 102.5, "reps": 5, "rpe": 8.0}]
    assert client.post("/workouts/sessions", headers=alice_headers, json=heavier).status_code == 201

    # Alice coaches Bob through an active, consented assignment.
    invite = client.post("/coach/assignments/invites", headers=alice_headers).json()
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=bob_headers,
        json={"token": invite["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    assert client.get("/assignments/me", headers=bob_headers).json()["status"] == "active"

    # A server-verified plan change on both capabilities.
    assert plans_service.set_plan(db, alice_id, "lifter", "pro")["ok"]
    assert plans_service.set_plan(db, alice_id, "coach", "pro")["ok"]
    plans = _plans(client, alice_headers)
    assert plans["lifter"]["plan"] == "pro"
    assert plans["coach"]["plan"] == "pro"

    # Account, program, history, and assignment all survive the plan change.
    assert client.get("/auth/me", headers=alice_headers).status_code == 200
    program = client.get("/programs/active", headers=alice_headers)
    assert program.status_code == 200, program.text
    assert program.json()["program_name"] == "Saved Split"
    records = client.get("/dashboard/personal-records", headers=alice_headers).json()
    assert any(record["exercise_id"] == "sq" for record in records)
    assert client.get("/assignments/me", headers=bob_headers).json()["status"] == "active"
    roster = client.get("/coach/assignments", headers=alice_headers).json()["assignments"]
    assert any(entry["player_username"] == "bob" for entry in roster)

    # Returning to Free is equally non-destructive.
    assert plans_service.set_plan(db, alice_id, "lifter", "free")["ok"]
    assert plans_service.set_plan(db, alice_id, "coach", "free")["ok"]
    assert _plans(client, alice_headers) == {
        "lifter": {"plan": "free", "status": "active"},
        "coach": {"plan": "free", "status": "active"},
    }
    assert client.get("/programs/active", headers=alice_headers).json()["program_name"] == "Saved Split"
    assert client.get("/assignments/me", headers=bob_headers).json()["status"] == "active"
