"""Player program request contract tests (ticket #28, ADR 018/027).

Exercises the public FastAPI surface against real temporary SQLite catalogs and
player ledgers. Covers exact-version/day/slot creation with no program mutation,
the direct-change refusal while the player controls the program, validation,
catalog-only coach queue listing, apply writing a NEW immutable version with
preserved provenance, stale revalidation, decline with a player-visible response,
player cancel, and the generic denial for every non-active assignment case.
"""

import sqlite3
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
    cat_conn.execute(
        "UPDATE exercises SET instructions = 'Press overhead with control', image_path = 'ohp.png',"
        " gif_path = 'ohp.gif' WHERE id = 'ohp'"
    )
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
        db.set_account_email(db.get_active_account_by_username(username)["account_id"], email)
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
                    ProgramExerciseSchema(exercise_id="row", exercise_name="Row", target_reps_min=5, target_reps_max=8),
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
        kwargs["ledger"].save_training_program(
            program.model_dump(),
            published_by_coach_account_id=kwargs.get("published_by_coach_account_id"),
        )
        return program, "md"

    monkeypatch.setattr("service.coach_programs.generate_program_pipeline", fake)


def _request_generation(db, monkeypatch):
    """A split-change apply generation that honours the requested frequency and preference."""

    def fake(**kwargs):
        program = _program(frequency=kwargs.get("frequency_override") or 1)
        kwargs["ledger"].save_training_program(
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
    assert db.ledger.get_active_program().version == 1
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


def test_program_request_email_looks_up_by_account_id_not_ledger_id(api, monkeypatch):
    client, db, _ = api
    coach_headers = _make_coach(client, db, "coach", capacity=5)
    coach = db.get_active_account_by_username("coach")
    assert coach["account_id"] != coach["ledger_id"]

    saved = client.post("/auth/email", headers=coach_headers, json={"email": "coach@example.com"})
    assert saved.status_code == 200, saved.text

    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    player = _register(client, "p1")
    player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem", headers=player_headers, json={"token": token, "consent": True}
    )
    assert redeemed.status_code == 200, redeemed.text
    assignment_id = redeemed.json()["assignment"]["assignment_id"]

    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    calls = []

    def _record(to_email, coach_display_name, player_username):
        calls.append((to_email, coach_display_name, player_username))
        return True

    monkeypatch.setattr(program_requests_service, "send_program_request_email", _record)

    created = _create(client, player_headers, **_substitution())
    assert created.status_code == 200, created.text
    assert calls == [("coach@example.com", "Coach coach", "p1")]


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
    assert refused.json()["code"] == "player_controls_program"
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

    bad_frequency = _create(client, player_headers, kind="split_change", desired_weekly_frequency=9)
    assert bad_frequency.status_code == 422


def test_coach_queue_listing_mounts_no_player_ledger(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    assert created.status_code == 200, created.text

    opened: list[str] = []
    real_open_ledger = db.open_ledger

    def spy(ledger_id):
        opened.append(str(ledger_id))
        return real_open_ledger(ledger_id)

    monkeypatch.setattr(db, "open_ledger", spy)

    listed = client.get(f"/coach/assignments/{assignment_id}/program-requests", headers=coach_headers)
    assert listed.status_code == 200, listed.text
    rows = listed.json()["requests"]
    assert len(rows) == 1
    assert rows[0]["request_id"] == created.json()["request_id"]
    assert "p1" not in opened


# --------------------------------------------------------------------------
# Apply
# --------------------------------------------------------------------------


def test_apply_substitution_publishes_new_version_preserving_provenance(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    db.switch_user("p1")
    original = db.ledger.get_active_program()
    program_data = original.model_dump()
    program_data.pop("created_at", None)
    program_data["days"][0]["exercises"][0].update(
        warmup_sets=2,
        target_sets=3,
        target_reps_min=6,
        target_reps_max=9,
        target_rpe=8.0,
        rest_seconds=120,
        notes="Original cue",
    )
    program_data["days"][0]["warmup_exercises"] = [
        {"exercise_id": "warmup", "exercise_name": "Dead Bug", "sets": 2, "reps": 10}
    ]
    second_day = {**program_data["days"][0], "day_name": "Full B", "day_order": 2}
    program_data["days"].append(second_day)
    db.ledger.save_training_program(program_data, published_by_coach_account_id=coach_account_id)

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
    assert [int(row[0]) for row in rows] == [1, 2, 3]
    assert all(row[1] == coach_account_id for row in rows)
    active = db.ledger.get_active_program()
    assert active.version == 3
    full_a = active.days[0]
    full_b = active.days[1]
    assert full_a.exercises[0].exercise_id == "ohp"
    assert full_a.exercises[0].exercise_name == "Overhead Press"
    assert full_a.exercises[0].notes == "Press overhead with control"
    assert full_a.exercises[0].image_path == "ohp.png"
    assert full_a.exercises[0].gif_path == "ohp.gif"
    assert full_a.warmup_exercises[0].exercise_name == "Dead Bug"
    assert (
        full_a.exercises[0].warmup_sets,
        full_a.exercises[0].target_sets,
        full_a.exercises[0].target_reps_min,
        full_a.exercises[0].target_reps_max,
        full_a.exercises[0].target_rpe,
        full_a.exercises[0].rest_seconds,
    ) == (2, 3, 6, 9, 8.0, 120)
    assert full_b.exercises[0].exercise_id == "sq"

    notices = client.get("/assignments/notices", headers=player_headers).json()["notices"]
    applied_notices = [n for n in notices if n["kind"] == "program_request"]
    assert applied_notices and "version 3" in applied_notices[0]["message"]


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
    active = db.ledger.get_active_program()
    assert active.version == 2
    assert active.weekly_frequency == 3


def test_apply_replacement_missing_after_creation_stays_pending(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    request_id = created.json()["request_id"]

    monkeypatch.setattr(db, "get_exercise_library_entry", lambda exercise_id: None)

    result = program_requests_service.apply_request(db, coach_account_id, assignment_id, request_id)
    assert result["ok"] is False
    assert result["error"] == program_requests_service.STALE_REQUEST_ERROR

    # The shared service validation leaves the request pending and the program untouched.
    assert db.get_program_request(request_id)["status"] == "pending"
    db.switch_user("p1")
    assert db.ledger.get_active_program().version == 1
    rows = db.conn.execute("SELECT COUNT(*) FROM training_programs").fetchone()
    assert int(rows[0]) == 1


def test_apply_refuses_replacement_already_on_target_day(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    db.switch_user("p1")
    program = db.ledger.get_active_program().model_dump()
    program.pop("created_at", None)
    program["days"] = [
        {
            "day_name": "Full A",
            "day_order": 1,
            "exercises": [
                {"exercise_id": exercise_id, "target_sets": 3, "target_reps_min": 8, "target_reps_max": 12}
                for exercise_id in ("sq", "ohp", "row")
            ],
        }
    ]
    db.ledger.save_training_program(program, published_by_coach_account_id=coach_account_id)

    created = _create(client, player_headers, **_substitution())
    request_id = created.json()["request_id"]
    result = program_requests_service.apply_request(db, coach_account_id, assignment_id, request_id)

    assert result["ok"] is False
    assert result["error"] == "That replacement exercise is already on the target day."
    assert db.get_program_request(request_id)["status"] == "pending"
    db.switch_user("p1")
    active = db.ledger.get_active_program()
    assert active.version == 2
    assert [exercise.exercise_id for exercise in active.days[0].exercises] == ["sq", "ohp", "row"]


def test_apply_write_failure_reverts_request_to_pending(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    request_id = created.json()["request_id"]

    def boom(*args, **kwargs):
        raise ValueError("No user profile found")

    from database.ledger.handle import TrainingLedger

    monkeypatch.setattr(TrainingLedger, "save_training_program", boom)

    with pytest.raises(ValueError):
        program_requests_service.apply_request(db, coach_account_id, assignment_id, request_id)

    # The claim is reverted, so the request is pending again and the program is unchanged.
    reverted = db.get_program_request(request_id)
    assert reverted["status"] == "pending"
    assert reverted["resolved_at"] is None
    assert reverted["resolved_by"] is None
    db.switch_user("p1")
    assert db.ledger.get_active_program().version == 1
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
    assert (
        applied.json()["detail"] == "The program changed since this request was created. Ask the player to update it."
    )

    listed = client.get("/assignments/me/program-requests", headers=player_headers).json()["requests"]
    assert listed[0]["status"] == "pending"

    db.switch_user("p1")
    active = db.ledger.get_active_program()
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
    assert db.ledger.get_active_program().version == 1


def test_cancel_pending_then_apply_is_refused(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    request_id = created.json()["request_id"]

    cancelled = client.post(f"/assignments/me/program-requests/{request_id}/cancel", headers=player_headers)
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
    assert (
        client.post(
            f"/coach/assignments/{assignment_id}/program-requests/{request_id}/decline",
            headers=coach_headers,
            json={"response": "No."},
        ).status_code
        == 200
    )

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
    unknown_apply = client.post("/coach/assignments/does-not-exist/program-requests/x/apply", headers=other_headers)
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
    assert client.get("/coach/program-requests").status_code == 401


# --------------------------------------------------------------------------
# Cross-roster listing (ticket #118)
# --------------------------------------------------------------------------


def _assign_player_to(client, coach_headers, player_name):
    """Assigns another player to an already-created coach; returns headers and assignment id."""
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    player = _register(client, player_name)
    player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem", headers=player_headers, json={"token": token, "consent": True}
    )
    assert redeemed.status_code == 200, redeemed.text
    return player_headers, redeemed.json()["assignment"]["assignment_id"]


def _pin_request_times(db, request_id, created_at, resolved_at=None):
    db.catalog_conn.execute(
        "UPDATE program_requests SET created_at = ?, resolved_at = COALESCE(?, resolved_at) WHERE request_id = ?",
        (created_at, resolved_at, request_id),
    )
    db.catalog_conn.commit()


def _cross_roster(client, coach_headers):
    response = client.get("/coach/program-requests", headers=coach_headers)
    assert response.status_code == 200, response.text
    return response.json()["requests"]


def test_cross_roster_listing_orders_pending_then_answered(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api, "p1")
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    second_headers, second_assignment_id = _assign_player_to(client, coach_headers, "p2")
    assert _publish(client, coach_headers, second_assignment_id).status_code == 200

    first = _create(client, player_headers, **_substitution()).json()
    other = _create(client, second_headers, **_substitution()).json()
    third = _create(client, player_headers, **_substitution()).json()
    _pin_request_times(db, first["request_id"], "2026-09-01T10:00:00+00:00")
    _pin_request_times(db, other["request_id"], "2026-09-02T10:00:00+00:00")
    _pin_request_times(db, third["request_id"], "2026-09-03T10:00:00+00:00")

    rows = _cross_roster(client, coach_headers)
    assert [row["request_id"] for row in rows] == [
        first["request_id"],
        other["request_id"],
        third["request_id"],
    ]
    # Each row carries the per-assignment fields plus assignment and player.
    expected = (
        (assignment_id, "p1"),
        (second_assignment_id, "p2"),
        (assignment_id, "p1"),
    )
    for row, (row_assignment, username) in zip(rows, expected):
        assert row["assignment_id"] == row_assignment
        assert row["player_username"] == username
        assert row["status"] == "pending"
        assert row["kind"] == "exercise_substitution"
        assert row["reason"] == "prefer a variation"
        assert row["program_version"] == 1
        assert row["created_at"]

    # The row's own ids drive resolution through the per-assignment endpoints.
    declined = client.post(
        f"/coach/assignments/{other['assignment_id']}/program-requests/{other['request_id']}/decline",
        headers=coach_headers,
        json={"response": "Not now."},
    )
    assert declined.status_code == 200, declined.text
    _pin_request_times(db, other["request_id"], "2026-09-02T10:00:00+00:00", "2026-09-10T10:00:00+00:00")

    declined = client.post(
        f"/coach/assignments/{first['assignment_id']}/program-requests/{first['request_id']}/decline",
        headers=coach_headers,
        json={"response": "Keep it."},
    )
    assert declined.status_code == 200, declined.text
    _pin_request_times(db, first["request_id"], "2026-09-01T10:00:00+00:00", "2026-09-05T10:00:00+00:00")

    rows = _cross_roster(client, coach_headers)
    # Pending oldest-first, then answered most-recently-first.
    assert [row["request_id"] for row in rows] == [
        third["request_id"],
        other["request_id"],
        first["request_id"],
    ]
    assert [row["status"] for row in rows] == ["pending", "declined", "declined"]


def test_cross_roster_listing_keeps_player_cancelled_requests_visible(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api, "p1")
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    pending = _create(client, player_headers, **_substitution()).json()
    cancelled = _create(client, player_headers, **_substitution()).json()
    assert (
        client.post(
            f"/assignments/me/program-requests/{cancelled['request_id']}/cancel",
            headers=player_headers,
        ).status_code
        == 200
    )

    rows = _cross_roster(client, coach_headers)
    assert [row["request_id"] for row in rows] == [pending["request_id"], cancelled["request_id"]]
    assert [row["status"] for row in rows] == ["pending", "cancelled"]


def test_cross_roster_listing_hides_other_coaches_and_ended_assignments(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api, "p1")
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    mine = _create(client, player_headers, **_substitution()).json()

    intruder_headers = _make_coach(client, db, "intruder", capacity=5)
    intruder_player, intruder_assignment_id = _assign_player_to(client, intruder_headers, "p2")
    assert _publish(client, intruder_headers, intruder_assignment_id).status_code == 200
    theirs = _create(client, intruder_player, **_substitution()).json()

    rows = _cross_roster(client, coach_headers)
    assert [row["request_id"] for row in rows] == [mine["request_id"]]
    assert rows[0]["player_username"] == "p1"
    assert [row["request_id"] for row in _cross_roster(client, intruder_headers)] == [theirs["request_id"]]

    # Ending the assignment removes its requests from the listing entirely.
    assert client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers).status_code == 200
    assert _cross_roster(client, coach_headers) == []
    assert [row["request_id"] for row in _cross_roster(client, intruder_headers)] == [theirs["request_id"]]


def test_cross_roster_listing_requires_the_coach_capability(api):
    client, _, _ = api
    player = _register(client, "p1")
    response = client.get("/coach/program-requests", headers=_authed(player["access_token"]))
    assert response.status_code == 403
    assert response.json()["detail"] == "Coach capability required."


def test_cross_roster_listing_mounts_no_player_ledger(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api, "p1")
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200
    created = _create(client, player_headers, **_substitution())
    assert created.status_code == 200, created.text

    opened: list[str] = []
    real_open_ledger = db.open_ledger

    def spy(ledger_id):
        opened.append(str(ledger_id))
        return real_open_ledger(ledger_id)

    monkeypatch.setattr(db, "open_ledger", spy)

    rows = _cross_roster(client, coach_headers)
    assert [row["request_id"] for row in rows] == [created.json()["request_id"]]
    assert "p1" not in opened
