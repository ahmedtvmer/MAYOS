"""Player program request contract tests (ticket #28, ADR 018/027).

Exercises the public FastAPI surface against real temporary SQLite catalogs and
player ledgers. Covers exact-version/day/slot creation with no program mutation,
the direct-change refusal while the player controls the program, validation,
catalog-only coach queue listing, apply writing a NEW immutable version with
preserved provenance, stale revalidation, decline with a player-visible response,
player cancel, and the generic denial for every non-active assignment case.
"""

import sqlite3
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import (
    GeneratedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
)
from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import coach_history as coach_history_service
from service import program_requests as program_requests_service
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
    cat_conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.execute(
        "INSERT INTO exercises (id, name, body_part, target_muscle) VALUES"
        " ('sq', 'Squat', 'Upper Legs', 'Quads'), ('bp', 'Bench Press', 'Chest', 'Chest'),"
        " ('row', 'Row', 'Back', 'Back'), ('ohp', 'Overhead Press', 'Shoulders', 'Shoulders');"
    )
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


def _make_coach(client, db, username, capacity=10, email=None):
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
    return headers


def _assigned_player(api, player_name="p1"):
    client, db, _ = api
    coach_headers = _make_coach(client, db, "coach", capacity=5, email="coach@example.com")
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    player = _register(client, player_name)
    player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem", headers=player_headers, json={"token": token, "consent": True}
    )
    assert redeemed.status_code == 200, redeemed.text
    coach_account_id = db.get_active_account_by_username("coach")["account_id"]
    player_account_id = db.get_active_account_by_username(player_name)["account_id"]
    return (
        coach_headers,
        player_headers,
        redeemed.json()["assignment"]["assignment_id"],
        coach_account_id,
        player_account_id,
    )


def _program(frequency=1) -> GeneratedProgramSchema:
    days = []
    for idx in range(frequency):
        days.append(
            ProgramDaySchema(
                day_name=f"Full {chr(ord('A') + idx)}",
                day_order=idx + 1,
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
        )
    return GeneratedProgramSchema(
        program_name="Coach Plan",
        split_type="Full Body",
        weekly_frequency=frequency,
        days=days,
    )


def _coach_generation(db, monkeypatch):
    def fake(**kwargs):
        program = _program()
        db.save_training_program(
            program.model_dump(),
            published_by_coach_account_id=kwargs.get("published_by_coach_account_id"),
        )
        return program, "md"

    monkeypatch.setattr("service.coach_programs.generate_program_pipeline", fake)


def _request_generation(db, monkeypatch):
    """A split-change apply generation that honours the requested frequency and preference."""

    def fake(**kwargs):
        program = _program(frequency=kwargs.get("frequency_override") or 1)
        db.save_training_program(
            program.model_dump(),
            published_by_coach_account_id=kwargs.get("published_by_coach_account_id"),
        )
        return program, "md"

    monkeypatch.setattr("service.program_requests.generate_program_pipeline", fake)


def _publish(client, coach_headers, assignment_id, **body):
    return client.post(f"/coach/assignments/{assignment_id}/program", headers=coach_headers, json=body)


def _create(client, player_headers, **body):
    payload = {"reason": "prefer a variation", **body}
    return client.post("/assignments/me/program-requests", headers=player_headers, json=payload)


def _substitution(**overrides):
    body = {
        "kind": "exercise_substitution",
        "day_name": "Full A",
        "exercise_id": "sq",
        "replacement_exercise_id": "ohp",
    }
    body.update(overrides)
    return body


def _capture_email(monkeypatch):
    sent: list[tuple[str, str, str]] = []

    def fake(to_email, subject, body):
        sent.append((to_email, subject, body))
        return True

    monkeypatch.setattr("service.email_sender._deliver", fake)
    return sent


# --------------------------------------------------------------------------
# Create: exact target, no program mutation, notices
# --------------------------------------------------------------------------


def test_create_substitution_records_exact_target_and_leaves_program(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    sent = _capture_email(monkeypatch)

    created = _create(client, player_headers, **_substitution())
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["program_version"] == 1
    assert body["day_name"] == "Full A"
    assert body["exercise_id"] == "sq"
    assert body["replacement_exercise_id"] == "ohp"
    assert body["reason"] == "prefer a variation"
    assert body["status"] == "pending"

    # The program was not touched: same single version, same slot.
    db.switch_user("p1")
    assert db.get_active_program().version == 1
    rows = db.conn.execute("SELECT COUNT(*) FROM training_programs").fetchone()
    assert int(rows[0]) == 1

    # Generic coach notice, no training detail in the email.
    notices = client.get("/coach/assignments/notices", headers=coach_headers).json()["notices"]
    request_notices = [n for n in notices if n["kind"] == "program_request"]
    assert len(request_notices) == 1
    assert "p1" in request_notices[0]["message"]
    assert len(sent) == 1
    to_email, _subject, email_body = sent[0]
    assert to_email == "coach@example.com"
    assert "p1" in email_body
    for leaked in ("Squat", "Full A", "Bench Press", "Row", "sq", "ohp"):
        assert leaked not in email_body
        assert leaked not in request_notices[0]["message"]

    listed = client.get("/assignments/me/program-requests", headers=player_headers).json()["requests"]
    assert [row["request_id"] for row in listed] == [body["request_id"]]


def test_create_split_change_records_desired_fields(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    created = _create(
        client,
        player_headers,
        kind="split_change",
        desired_weekly_frequency=3,
        desired_split_preference="Upper/Lower",
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["kind"] == "split_change"
    assert body["program_version"] == 1
    assert body["desired_weekly_frequency"] == 3
    assert body["desired_split_preference"] == "Upper/Lower"
    assert body["day_name"] is None


def test_create_refused_when_player_controls_program(api, monkeypatch):
    client, db, _ = api
    _, player_headers, _, _, player_account_id = _assigned_player(api)
    _coach_generation(db, monkeypatch)

    refused = _create(client, player_headers, **_substitution())
    assert refused.status_code == 400
    assert refused.json()["detail"] == "You can change your own program directly."
    assert db.list_program_requests_for_player(player_account_id) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"day_name": "Leg Day"},
        {"exercise_id": "ghost"},
        {"replacement_exercise_id": "ghost"},
        {"replacement_exercise_id": "sq"},
    ],
)
def test_create_substitution_validation_failures(api, monkeypatch, overrides):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    refused = _create(client, player_headers, **_substitution(**overrides))
    assert refused.status_code == 400, refused.text


def test_create_missing_reason_and_bad_frequency_are_rejected(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    missing_reason = client.post(
        "/assignments/me/program-requests", headers=player_headers, json=_substitution(reason="")
    )
    assert missing_reason.status_code == 422

    bad_frequency = _create(
        client, player_headers, kind="split_change", desired_weekly_frequency=9
    )
    assert bad_frequency.status_code == 422


def test_coach_queue_listing_mounts_no_player_ledger(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    assert created.status_code == 200, created.text

    import service.assignments as assignments_service

    mounted: list[str] = []

    def spy(db_arg, ledger_id):
        mounted.append(str(ledger_id))
        return ledger_id

    monkeypatch.setattr(assignments_service, "bind_user", spy)

    listed = client.get(f"/coach/assignments/{assignment_id}/program-requests", headers=coach_headers)
    assert listed.status_code == 200, listed.text
    rows = listed.json()["requests"]
    assert len(rows) == 1
    assert rows[0]["request_id"] == created.json()["request_id"]
    assert "p1" not in mounted


# --------------------------------------------------------------------------
# Apply
# --------------------------------------------------------------------------


def test_apply_substitution_publishes_new_version_preserving_provenance(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    request_id = created.json()["request_id"]

    applied = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{request_id}/apply", headers=coach_headers
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    assert applied.json()["resolved_by"] == coach_account_id

    db.switch_user("p1")
    rows = db.conn.execute(
        "SELECT version, published_by_coach_account_id FROM training_programs ORDER BY version ASC"
    ).fetchall()
    assert [int(row[0]) for row in rows] == [1, 2]
    assert all(row[1] == coach_account_id for row in rows)
    active = db.get_active_program()
    assert active.version == 2
    slot_ids = [ex.exercise_id for day in active.days for ex in day.exercises]
    assert "ohp" in slot_ids and "sq" not in slot_ids

    notices = client.get("/assignments/notices", headers=player_headers).json()["notices"]
    applied_notices = [n for n in notices if n["kind"] == "program_request"]
    assert applied_notices and "version 2" in applied_notices[0]["message"]


def test_apply_split_change_publishes_desired_frequency(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(
        client,
        player_headers,
        kind="split_change",
        desired_weekly_frequency=3,
        desired_split_preference="Upper/Lower",
    )
    request_id = created.json()["request_id"]
    _request_generation(db, monkeypatch)

    applied = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{request_id}/apply", headers=coach_headers
    )
    assert applied.status_code == 200, applied.text

    db.switch_user("p1")
    active = db.get_active_program()
    assert active.version == 2
    assert active.weekly_frequency == 3


def test_apply_replacement_missing_after_creation_stays_pending(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    request_id = created.json()["request_id"]

    monkeypatch.setattr(db, "get_exercise_catalog_entry", lambda exercise_id: None)

    result = program_requests_service.apply_request(db, coach_account_id, assignment_id, request_id)
    assert result["ok"] is False
    assert result["error"] == program_requests_service.STALE_REQUEST_ERROR

    # The failed pre-claim validation leaves the request pending and the program untouched.
    assert db.get_program_request(request_id)["status"] == "pending"
    db.switch_user("p1")
    assert db.get_active_program().version == 1
    rows = db.conn.execute("SELECT COUNT(*) FROM training_programs").fetchone()
    assert int(rows[0]) == 1


def test_apply_write_failure_reverts_request_to_pending(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    request_id = created.json()["request_id"]

    def boom(*args, **kwargs):
        raise ValueError("No user profile found")

    monkeypatch.setattr(db, "save_training_program", boom)

    with pytest.raises(ValueError):
        program_requests_service.apply_request(db, coach_account_id, assignment_id, request_id)

    # The claim is reverted, so the request is pending again and the program is unchanged.
    reverted = db.get_program_request(request_id)
    assert reverted["status"] == "pending"
    assert reverted["resolved_at"] is None
    assert reverted["resolved_by"] is None
    db.switch_user("p1")
    assert db.get_active_program().version == 1
    rows = db.conn.execute("SELECT COUNT(*) FROM training_programs").fetchone()
    assert int(rows[0]) == 1


def test_apply_stale_request_after_new_publication(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    request_id = created.json()["request_id"]

    assert _publish(client, coach_headers, assignment_id).json()["version"] == 2

    applied = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{request_id}/apply", headers=coach_headers
    )
    assert applied.status_code == 400
    assert applied.json()["detail"] == "The program changed since this request was created. Ask the player to update it."

    listed = client.get("/assignments/me/program-requests", headers=player_headers).json()["requests"]
    assert listed[0]["status"] == "pending"

    db.switch_user("p1")
    active = db.get_active_program()
    assert active.version == 2
    slot_ids = [ex.exercise_id for day in active.days for ex in day.exercises]
    assert "sq" in slot_ids and "ohp" not in slot_ids


# --------------------------------------------------------------------------
# Decline and cancel
# --------------------------------------------------------------------------


def test_decline_records_response_and_leaves_program(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    request_id = created.json()["request_id"]

    declined = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{request_id}/decline",
        headers=coach_headers,
        json={"response": "Keep the squat; we will revisit next block."},
    )
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "declined"
    assert declined.json()["response"] == "Keep the squat; we will revisit next block."

    listed = client.get("/assignments/me/program-requests", headers=player_headers).json()["requests"]
    assert listed[0]["status"] == "declined"
    assert listed[0]["response"] == "Keep the squat; we will revisit next block."

    db.switch_user("p1")
    assert db.get_active_program().version == 1


def test_cancel_pending_then_apply_is_refused(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    request_id = created.json()["request_id"]

    cancelled = client.post(
        f"/assignments/me/program-requests/{request_id}/cancel", headers=player_headers
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["resolved_by"] == "player"

    applied = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{request_id}/apply", headers=coach_headers
    )
    assert applied.status_code == 400
    assert "no longer pending" in applied.json()["detail"]


def test_cancel_non_pending_request_is_refused(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    request_id = created.json()["request_id"]
    assert client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{request_id}/decline",
        headers=coach_headers,
        json={"response": "No."},
    ).status_code == 200

    again = client.post(f"/assignments/me/program-requests/{request_id}/cancel", headers=player_headers)
    assert again.status_code == 400
    assert "no longer pending" in again.json()["detail"]


# --------------------------------------------------------------------------
# Denial is generic; unassignment removes the request path
# --------------------------------------------------------------------------


def test_wrong_coach_and_unknown_assignment_are_indistinguishable(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    request_id = created.json()["request_id"]
    other_headers = _make_coach(client, db, "intruder", capacity=5)

    other_list = client.get(f"/coach/assignments/{assignment_id}/program-requests", headers=other_headers)
    unknown_list = client.get("/coach/assignments/does-not-exist/program-requests", headers=other_headers)
    assert other_list.status_code == unknown_list.status_code == 403
    assert other_list.json()["detail"] == unknown_list.json()["detail"] == coach_history_service.DENIED_ERROR

    other_apply = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{request_id}/apply", headers=other_headers
    )
    unknown_apply = client.post(
        "/coach/assignments/does-not-exist/program-requests/x/apply", headers=other_headers
    )
    assert other_apply.status_code == unknown_apply.status_code == 403
    assert other_apply.json()["detail"] == coach_history_service.DENIED_ERROR


def test_after_unassignment_create_is_direct_error_and_apply_denied(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    request_id = created.json()["request_id"]

    assert client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers).status_code == 200

    refused = _create(client, player_headers, **_substitution())
    assert refused.status_code == 400
    assert refused.json()["detail"] == "You can change your own program directly."

    denied = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{request_id}/apply", headers=coach_headers
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == coach_history_service.DENIED_ERROR


def test_program_request_routes_require_authentication(api):
    client, _, _ = api
    assert client.get("/assignments/me/program-requests").status_code == 401
    assert client.post("/assignments/me/program-requests", json=_substitution()).status_code == 401
    assert client.get("/coach/assignments/x/program-requests").status_code == 401
