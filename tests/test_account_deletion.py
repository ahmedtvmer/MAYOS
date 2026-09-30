"""Durable account deletion (issue #40, ADR 015/039).

Exercises the public FastAPI surface against real temporary SQLite catalogs and
player ledgers with a mocked model: password confirmation, revoke-all in the
registry, relationship teardown, ledger + backup removal, username reuse,
former-coach presentation, crash-safety, and restore replay.
"""

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import (
    GeneratedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
)
from database.database_manager import DatabaseManager, LedgerDeletedError
from database.migration_manager import create_atomic_backup, restore_atomic_backup
from service import account_deletion as deletion_service
from service import coach as coach_service
from service import password_reset as reset_service
from service import programs as programs_service
from svc.app import create_app
from svc.auth import create_access_token
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
    for exercise_id, name in (("sq", "Squat"), ("bp", "Bench Press"), ("row", "Row")):
        cat_conn.execute("INSERT INTO exercises (id, name) VALUES (?, ?)", (exercise_id, name))
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


def _register(client, username, password="correct-horse-1", remember_me=False):
    resp = client.post(
        "/auth/register",
        json={"trainee_id": username, "password": password, "remember_me": remember_me},
    )
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


def _make_coach(client, db, username, capacity=10):
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username, actor="cli")
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
    return headers, _subject(registered["access_token"])


def _assign(client, coach_headers, player_headers):
    issued = client.post("/coach/assignments/invites", headers=coach_headers)
    assert issued.status_code == 200, issued.text
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": issued.json()["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    return redeemed.json()["assignment"]["assignment_id"]


def _program(name: str = "Coach Plan") -> GeneratedProgramSchema:
    return GeneratedProgramSchema(
        program_name=name,
        split_type="Full Body",
        weekly_frequency=1,
        days=[
            ProgramDaySchema(
                day_name="Full A",
                day_order=1,
                exercises=[
                    ProgramExerciseSchema(
                        exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8
                    ),
                    ProgramExerciseSchema(
                        exercise_id="bp", exercise_name="Bench Press", target_reps_min=5, target_reps_max=8
                    ),
                    ProgramExerciseSchema(
                        exercise_id="row", exercise_name="Row", target_reps_min=5, target_reps_max=8
                    ),
                ],
            )
        ],
    )


def _fake_coach_generator(db):
    def fake(**kwargs):
        program = _program()
        kwargs["ledger"].save_training_program(
            program.model_dump(),
            published_by_coach_account_id=kwargs.get("published_by_coach_account_id"),
        )
        return program, "md"

    return fake


def _scalar(db, sql, params=()):
    with db._catalog_lock:
        return db.catalog_conn.execute(sql, params).fetchone()[0]


def _delete(client, token, password):
    return client.request("DELETE", "/auth/account", headers=_authed(token), json={"password": password})


# --------------------------------------------------------------------------
# 1. Password confirmation and success invariants
# --------------------------------------------------------------------------


def test_wrong_password_changes_nothing(api):
    client, db, ledgers_dir = api
    registered = _register(client, "alice")
    token = registered["access_token"]
    account_id = _subject(token)

    wrong = _delete(client, token, "definitely-wrong-1")
    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "Invalid credentials."
    assert db.is_live_account(db.get_account(account_id))
    assert not db.is_account_deleted(account_id)
    assert (ledgers_dir / "alice.db").exists()
    # The token still works: nothing was revoked.
    assert client.get("/dashboard/exercises", headers=_authed(token)).status_code == 200


def test_deletion_invalidates_all_sessions_and_removes_ledger(api):
    client, db, ledgers_dir = api
    registered = _register(client, "alice", remember_me=True)
    token = registered["access_token"]
    account_id = _subject(token)
    # Second live session: a fresh login (different jti, same epoch).
    second_token = _login(client, "alice")["access_token"]
    # Recovery email + a pending reset token.
    assert client.post("/auth/email", headers=_authed(token), json={"email": "alice@example.com"}).status_code == 200
    reset_service.request_password_reset(
        db, "alice@example.com", mailer=lambda to, link: True, token_factory=lambda: "reset-token-abcdef1234"
    )
    assert _scalar(db, "SELECT COUNT(*) FROM password_reset_tokens WHERE trainee_id = ?", (account_id,)) == 1

    deleted = _delete(client, token, "correct-horse-1")
    assert deleted.status_code == 200, deleted.text
    assert db.get_account(account_id)["deleted_at"] is not None
    assert db.is_account_deleted(account_id)

    # Every existing bearer/remember-me token now fails with the deleted signal.
    for stale in (token, second_token):
        resp = client.get("/auth/me", headers=_authed(stale))
        assert resp.status_code == 401
        assert resp.json() == {"error": "account_deleted"}

    # Ledger files (db + -wal + -shm) and the user-specific backup dir are gone.
    assert not (ledgers_dir / "alice.db").exists()
    assert not (ledgers_dir / "alice.db-wal").exists()
    assert not (ledgers_dir / "alice.db-shm").exists()
    assert not (db.backups_dir / "alice").exists()
    assert not db.ledger_exists("alice")

    # Recovery identity and reset tokens are cleared.
    assert db.get_account_email(account_id) is None
    assert _scalar(db, "SELECT COUNT(*) FROM password_reset_tokens WHERE trainee_id = ?", (account_id,)) == 0


def test_delete_account_holds_no_ledger_handle_while_removing_files(api, monkeypatch):
    """Deletion must not unlink the ledger while a handle to it is open (defect #3)."""
    client, db, ledgers_dir = api
    registered = _register(client, "alice")
    token = registered["access_token"]

    opened = []
    real_open = db.open_ledger

    def tracking_open(ledger_id):
        handle = real_open(ledger_id)
        opened.append(handle)
        return handle

    monkeypatch.setattr(db, "open_ledger", tracking_open)

    def is_open(handle):
        try:
            handle.conn
        except RuntimeError:
            return False
        return True

    observed = {}
    real_remove = db._remove_account_files

    def checking_remove(ledger_id, **kwargs):
        observed["open"] = [handle for handle in opened if is_open(handle)]
        return real_remove(ledger_id, **kwargs)

    monkeypatch.setattr(db, "_remove_account_files", checking_remove)

    assert _delete(client, token, "correct-horse-1").status_code == 200
    assert not (ledgers_dir / "alice.db").exists()
    assert observed["open"] == []


def test_username_reuse_creates_a_new_immutable_account(api):
    client, db, ledgers_dir = api
    first = _register(client, "alice")
    first_token = first["access_token"]
    first_id = _subject(first_token)
    assert _delete(client, first_token, "correct-horse-1").status_code == 200

    second = _register(client, "alice")
    second_id = _subject(second["access_token"])
    assert second_id != first_id
    assert db.get_active_account_by_username("alice")["account_id"] == second_id

    # The old token can never target the reused username's new account.
    stale = client.get("/auth/me", headers=_authed(first_token))
    assert stale.status_code == 401
    assert stale.json() == {"error": "account_deleted"}

    # The new account starts with an empty ledger (no profile, no password bleed).
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 200
    assert client.get("/profile", headers=_authed(second["access_token"])).status_code == 404
    assert db.get_account(first_id)["deleted_at"] is not None


def test_reapply_never_removes_a_reused_usernames_new_ledger(api):
    client, db, ledgers_dir = api
    first = _register(client, "alice")
    first_id = _subject(first["access_token"])
    assert _delete(client, first["access_token"], "correct-horse-1").status_code == 200

    second = _register(client, "alice")
    second_id = _subject(second["access_token"])
    assert second_id != first_id

    # A reused username gets a fresh ledger path, distinct from the deleted
    # account's, so it never aliases that account's ledger.
    second_ledger = db.get_account(second_id)["ledger_id"]
    first_ledger = db.get_account(first_id)["ledger_id"]
    assert second_ledger != first_ledger
    assert (ledgers_dir / f"{second_ledger}.db").exists()
    assert not (ledgers_dir / f"{first_ledger}.db").exists()

    # A later startup/restore replay of the old deletion record leaves the new
    # account's ledger untouched, and it remains fully usable.
    assert db.reapply_deletions() >= 1
    assert (ledgers_dir / f"{second_ledger}.db").exists()
    assert db.ledger_exists(second_ledger)
    assert db.get_account(second_id)["deleted_at"] is None
    assert client.get("/auth/me", headers=_authed(second["access_token"])).status_code == 200

    # The new account can still log a workout against its own ledger.
    db.switch_user(second_ledger)
    db.ledger.upsert_player_profile({"current_goal": "Strength"})
    db.ledger.save_training_program(_saved_split_payload())
    commit = client.post(
        "/workouts/sessions",
        headers=_authed(second["access_token"]),
        json={
            "day_order": 1,
            "readiness": 4,
            "session_notes": "",
            "sets": [
                {"exercise": _exercise_payload("sq", "Squat"), "sets": [{"weight_kg": 100.0, "reps": 5, "rpe": 8.0}]}
            ],
        },
    )
    assert commit.status_code == 201, commit.text

    # The old token remains rejected.
    stale = client.get("/auth/me", headers=_authed(first["access_token"]))
    assert stale.status_code == 401
    assert stale.json() == {"error": "account_deleted"}


def _exercise_payload(exercise_id, exercise_name):
    return {
        "exercise_id": exercise_id,
        "exercise_name": exercise_name,
        "target_sets": 3,
        "target_reps_min": 5,
        "target_reps_max": 8,
        "target_rpe": 8.5,
        "rest_seconds": 120,
        "notes": None,
    }


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


# --------------------------------------------------------------------------
# 2. Relationship teardown
# --------------------------------------------------------------------------


def test_player_deletion_ends_assignments_and_clears_relationships(api):
    client, db, ledgers_dir = api
    coach_headers, coach_id = _make_coach(client, db, "coach")
    player = _register(client, "alice")
    player_token = player["access_token"]
    player_headers = _authed(player_token)
    player_id = _subject(player_token)
    assignment_id = _assign(client, coach_headers, player_headers)

    # A pending program request, an alert, and a pending coach invite.
    db.create_program_request(
        "req-1", assignment_id, coach_id, player_id, "exercise_substitution", 1,
        "Full A", "sq", None, None, None, "knee", "2026-09-02T00:00:00+00:00",
    )
    db.insert_coach_alert("alert-1", assignment_id, coach_id, player_id, "missed_expected_days", "2026-09-01", {}, "2026-09-02T00:00:00+00:00")
    assert client.post("/coach/assignments/invites", headers=coach_headers).status_code == 200

    assert _delete(client, player_token, "correct-horse-1").status_code == 200

    # The assignment is ended (reason recorded) and the coach loses access.
    assert db.get_active_assignment_for_player(player_id) is None
    assert db.get_active_assignment_for_coach(coach_id, assignment_id) is None
    with db._catalog_lock:
        row = db.catalog_conn.execute(
            "SELECT status, ended_by FROM assignments WHERE assignment_id = ?", (assignment_id,)
        ).fetchone()
    assert row[0] == "ended"
    assert row[1] == "account_deleted"
    assert client.get(f"/coach/assignments/{assignment_id}/player/summary", headers=coach_headers).status_code == 403

    # Relationships keyed to the deleted account are gone.
    assert _scalar(db, "SELECT COUNT(*) FROM program_requests WHERE player_account_id = ?", (player_id,)) == 0
    assert _scalar(db, "SELECT COUNT(*) FROM coach_alerts WHERE assignment_id = ?", (assignment_id,)) == 0
    assert _scalar(db, "SELECT COUNT(*) FROM assignment_invites WHERE redeemed_by_account_id = ?", (player_id,)) == 0
    assert _scalar(db, "SELECT COUNT(*) FROM account_plans WHERE account_id = ?", (player_id,)) == 0


def test_deleted_coach_becomes_former_coach_and_returns_program_authority(api, monkeypatch):
    client, db, ledgers_dir = api
    coach_headers, coach_id = _make_coach(client, db, "coachx")
    player = _register(client, "bob")
    player_token = player["access_token"]
    player_headers = _authed(player_token)
    player_id = _subject(player_token)
    assignment_id = _assign(client, coach_headers, player_headers)

    # The coach records a check-in and publishes a program.
    assert client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": datetime.now(UTC).date().isoformat(), "channel": "phone"},
    ).status_code == 200
    monkeypatch.setattr("service.coach_programs.generate_program_pipeline", _fake_coach_generator(db))
    assert client.post(f"/coach/assignments/{assignment_id}/program", headers=coach_headers, json={}).status_code == 200

    # While assigned, the coach owns the program.
    with db.open_ledger("bob") as ledger:
        assert programs_service.player_controls_program(db, ledger, player_id) is False

    assert _delete(client, coach_headers["Authorization"].split(" ", 1)[1], "correct-horse-1").status_code == 200

    # Former coach is presented by name only as "Former coach" (no reusable username).
    check_ins = client.get("/assignments/me/check-ins", headers=player_headers).json()["check_ins"]
    assert len(check_ins) == 1
    assert check_ins[0]["coach_username"] == "Former coach"

    # Program provenance is retained, but authority has returned to the player.
    with db.open_ledger("bob") as ledger:
        active = ledger.get_active_program()
        assert active.published_by_coach_account_id == coach_id
        assert programs_service.player_controls_program(db, ledger, player_id) is True

    # The player can now regenerate self-service (no coach model call needed).
    def fake_player_generation(**kwargs):
        return _program("Player Plan"), "md"

    monkeypatch.setattr("svc.routers.programs.generate_program_pipeline", fake_player_generation)
    monkeypatch.setattr("service.programs.generate_program_pipeline", fake_player_generation)
    assert client.post("/programs/generate", headers=player_headers, json={}).status_code == 200


# --------------------------------------------------------------------------
# 3. Crash safety and restore replay
# --------------------------------------------------------------------------


def test_interrupted_deletion_fails_closed_and_completes_on_reapply(api, monkeypatch):
    client, db, ledgers_dir = api
    registered = _register(client, "alice")
    token = registered["access_token"]
    account_id = _subject(token)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash after the deletion record")

    original = db._force_delete_account_catalog
    monkeypatch.setattr(db, "_force_delete_account_catalog", boom)
    with pytest.raises(RuntimeError):
        deletion_service.delete_account(db, account_id, "correct-horse-1")

    # The durable record exists, so the account already fails closed even though
    # the catalog was never touched.
    assert db.is_account_deleted(account_id)
    resp = client.get("/auth/me", headers=_authed(token))
    assert resp.status_code == 401
    assert resp.json() == {"error": "account_deleted"}

    # An incremental replay (the startup/sweep path) finishes the deletion and
    # removes the ledger; a second incremental pass is a no-op.
    monkeypatch.setattr(db, "_force_delete_account_catalog", original)
    assert db.replay_deletions() >= 1
    assert db.get_account(account_id)["deleted_at"] is not None
    assert not db.ledger_exists("alice")
    assert db.replay_deletions() == 0


def test_full_replay_rechecks_applied_records(api):
    client, db, _ = api
    registered = _register(client, "alice")
    token = registered["access_token"]
    assert _delete(client, token, "correct-horse-1").status_code == 200
    # The normal replay skips the already-applied record; a full replay (the
    # restore path) re-checks it even though its marker is set.
    assert db.replay_deletions() == 0
    assert db.replay_deletions(full=True) >= 1


def test_restore_reapplies_durable_deletion(api):
    client, db, ledgers_dir = api
    registered = _register(client, "alice")
    token = registered["access_token"]
    account_id = _subject(token)

    # Snapshot the live catalog before deletion, as a disaster-recovery backup would.
    snapshot = ledgers_dir.parent / "catalog_snapshot.db"
    create_atomic_backup(db.catalog_conn, snapshot)

    assert _delete(client, token, "correct-horse-1").status_code == 200
    assert not (ledgers_dir / "alice.db").exists()

    # Restoring the pre-deletion catalog must not resurrect the account: the
    # durable record lives outside the snapshot and is reapplied.
    restore_atomic_backup(snapshot, db.catalog_conn)
    assert db.get_account(account_id)["deleted_at"] is None  # snapshot had it live
    assert db.reapply_deletions() >= 1
    assert db.get_account(account_id)["deleted_at"] is not None
    assert not db.ledger_exists("alice")
    assert client.get("/auth/me", headers=_authed(token)).json() == {"error": "account_deleted"}


# --------------------------------------------------------------------------
# 4. Ordinary expiry keeps the existing 401 shape
# --------------------------------------------------------------------------


def test_ordinary_expired_token_is_not_account_deleted(api):
    client, db, _ = api
    registered = _register(client, "alice")
    account_id = _subject(registered["access_token"])
    past = datetime.now(UTC) - timedelta(hours=3)
    expired = pyjwt.encode(
        {"sub": account_id, "jti": hashlib.md5(b"x").hexdigest(), "tv": 1, "iat": past, "exp": past},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    resp = client.get("/auth/me", headers=_authed(expired))
    assert resp.status_code == 401
    assert "error" not in resp.json()
    assert "detail" in resp.json()
    # A stale-epoch (revoked) token is likewise a plain 401, not account_deleted.
    changed = client.post(
        "/auth/change-password",
        headers=_authed(registered["access_token"]),
        json={"current_password": "correct-horse-1", "new_password": "brand-new-horse-2"},
    )
    assert changed.status_code == 200
    stale = client.get("/auth/me", headers=_authed(registered["access_token"]))
    assert stale.status_code == 401
    assert "error" not in stale.json()


def test_unknown_account_token_is_plain_401(api):
    client, _, _ = api
    ghost = create_access_token("a" * 32)
    resp = client.get("/auth/me", headers=_authed(ghost))
    assert resp.status_code == 401
    assert "error" not in resp.json()


# --------------------------------------------------------------------------
# 5. Safety: unsafe ledger ids, unknown accounts, in-flight mounts, reuse
# --------------------------------------------------------------------------


def test_delete_unknown_account_is_refused_and_not_recorded(api):
    _, db, _ = api
    result = db.delete_account("a" * 32)
    assert result["ok"] is False
    assert db.list_account_deletions() == []


def test_remove_account_files_refuses_unsafe_ledger_ids(api):
    _, db, ledgers_dir = api
    (ledgers_dir / "default.db").write_bytes(b"keep")
    (ledgers_dir / "Weird Name.db").write_bytes(b"keep")
    (ledgers_dir / "alice.db").write_bytes(b"keep")

    db._remove_account_files("")
    db._remove_account_files("   ")
    db._remove_account_files("default")
    db._remove_account_files("Weird Name")
    db._remove_account_files("Alice")  # non-canonical (uppercase) is refused

    assert (ledgers_dir / "default.db").exists()
    assert (ledgers_dir / "Weird Name.db").exists()
    assert (ledgers_dir / "alice.db").exists()


def test_binding_a_deleted_ledger_is_refused_and_not_recreated(api):
    client, db, ledgers_dir = api
    registered = _register(client, "alice")
    account_id = _subject(registered["access_token"])
    ledger_id = db.get_account(account_id)["ledger_id"]
    assert _delete(client, registered["access_token"], "correct-horse-1").status_code == 200
    assert not (ledgers_dir / f"{ledger_id}.db").exists()

    with pytest.raises(LedgerDeletedError):
        db.switch_user(ledger_id)
    assert not (ledgers_dir / f"{ledger_id}.db").exists()


def test_assignment_notices_for_the_deleted_account_assignments_are_removed(api):
    client, db, _ = api
    coach_headers, coach_id = _make_coach(client, db, "coach")
    player = _register(client, "alice")
    player_token = player["access_token"]
    player_id = _subject(player_token)
    assignment_id = _assign(client, coach_headers, _authed(player_token))

    now = datetime.now(UTC).isoformat()
    db.create_assignment_notice(coach_id, assignment_id, "assignment_redeemed", "alice accepted.", now)
    db.create_assignment_notice(player_id, assignment_id, "program_published", "Your coach published.", now)
    db.create_assignment_notice(coach_id, "other-assignment", "assignment_redeemed", "bob accepted.", now)

    assert _delete(client, player_token, "correct-horse-1").status_code == 200

    assert _scalar(db, "SELECT COUNT(*) FROM assignment_notices WHERE assignment_id = ?", (assignment_id,)) == 0
    assert _scalar(db, "SELECT COUNT(*) FROM assignment_notices WHERE assignment_id = 'other-assignment'") == 1


def test_replay_preserves_a_reused_usernames_recovery_rows(api):
    client, db, _ = api
    first = _register(client, "alice")
    first_headers = _authed(first["access_token"])
    assert client.post("/auth/email", headers=first_headers, json={"email": "first@example.com"}).status_code == 200
    assert _delete(client, first["access_token"], "correct-horse-1").status_code == 200

    second = _register(client, "alice")
    second_id = _subject(second["access_token"])
    assert client.post(
        "/auth/email", headers=_authed(second["access_token"]), json={"email": "second@example.com"}
    ).status_code == 200
    # A legacy username-keyed recovery row for the old account, present while the
    # new account owns the username.
    with db._catalog_lock:
        db.catalog_conn.execute(
            "INSERT OR REPLACE INTO trainee_emails (trainee_id, email, updated_at) VALUES ('alice', ?, ?)",
            ("legacy-alice@example.com", datetime.now(UTC).isoformat()),
        )
        db.catalog_conn.commit()

    # A full replay of the old record must not clear the new live account's
    # username-keyed rows.
    assert db.reapply_deletions() >= 1
    assert db.get_account_email(second_id) == "second@example.com"
    with db._catalog_lock:
        legacy = db.catalog_conn.execute("SELECT 1 FROM trainee_emails WHERE trainee_id = 'alice'").fetchone()
    assert legacy is not None
    assert db.get_account(second_id)["deleted_at"] is None
