"""Coach program publication contract tests (ticket #26).

Exercises the public FastAPI surface against real temporary SQLite catalogs and
player ledgers. Covers assignment-gated publication with coach provenance and a
stable version, the player's in-app notice, program authority transfer (player
self-service before publication, refused after), retention and authority return
on unassignment, version increments, and the generic denial for every
non-active assignment case.
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import jwt as pyjwt
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
from service import programs as programs_service
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
        " ('row', 'Row', 'Back', 'Back');"
    )
    cat_conn.commit()
    cat_conn.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    from service.analytics import register_analytics_preference_reader

    register_analytics_preference_reader(db.analytics_preference_allows)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db, tmp_path / "users"
    finally:
        register_analytics_preference_reader(None)
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
    return headers


def _assigned_player(api, player_name="p1"):
    """Coach "coach" is actively assigned "p1"; returns headers, assignment id, accounts."""
    client, db, _ = api
    coach_headers = _make_coach(client, db, "coach", capacity=5)
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


def _program() -> GeneratedProgramSchema:
    return GeneratedProgramSchema(
        program_name="Coach Plan",
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


def _coach_generation(db, monkeypatch):
    """Replaces the LLM-free pipeline at the coach service seam, saving through the real ledger."""

    def fake(**kwargs):
        program = _program()
        kwargs["ledger"].save_training_program(
            program.model_dump(),
            published_by_coach_account_id=kwargs.get("published_by_coach_account_id"),
        )
        return program, "md"

    monkeypatch.setattr("service.coach_programs.generate_program_pipeline", fake)


def _player_generation(db, monkeypatch):
    """Replaces the pipeline at the player service seam (self-service, no provenance)."""

    def fake(**kwargs):
        program = _program()
        kwargs["ledger"].save_training_program(program.model_dump())
        return program, "md"

    monkeypatch.setattr("service.programs.generate_program_pipeline", fake)


def _publish(client, coach_headers, assignment_id, **body):
    return client.post(f"/coach/assignments/{assignment_id}/program", headers=coach_headers, json=body)


# --------------------------------------------------------------------------
# Publication, provenance, version, notice
# --------------------------------------------------------------------------


def test_publish_activates_immediately_with_provenance_and_notice(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)

    published = _publish(client, coach_headers, assignment_id, frequency_override=3)
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["version"] == 1
    assert body["published_by_coach_account_id"] == coach_account_id

    active = client.get("/programs/active", headers=player_headers).json()
    assert active["version"] == 1
    assert active["published_by_coach_account_id"] == coach_account_id

    notices = client.get("/assignments/notices", headers=player_headers).json()["notices"]
    assert len(notices) == 1
    assert notices[0]["kind"] == "program_published"
    assert "version 1" in notices[0]["message"]
    assert notices[0]["read_at"] is None

    marked = client.post("/assignments/notices/read", headers=player_headers)
    assert marked.status_code == 200
    assert marked.json()["marked_read"] == 1
    assert client.get("/assignments/notices", headers=player_headers).json()["notices"][0]["read_at"] is not None


def test_second_publish_increments_version_and_keeps_first_stable(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)

    assert _publish(client, coach_headers, assignment_id).json()["version"] == 1
    assert _publish(client, coach_headers, assignment_id).json()["version"] == 2

    assert client.get("/programs/active", headers=player_headers).json()["version"] == 2

    db.switch_user("p1")
    rows = db.conn.execute(
        "SELECT version, published_by_coach_account_id FROM training_programs ORDER BY version ASC"
    ).fetchall()
    assert [int(row[0]) for row in rows] == [1, 2]
    assert all(row[1] == coach_account_id for row in rows)


def _program_draft_path(assignment_id):
    return f"/coach/assignments/{assignment_id}/program-draft"


def _one_day_draft(exercise_id="sq", **exercise_fields):
    exercise = {
        "exercise_id": exercise_id,
        "target_sets": 3,
        "target_reps_min": 6,
        "target_reps_max": 8,
        "target_rir": 2,
        **exercise_fields,
    }
    return {
        "program_name": "Handwritten plan",
        "split_type": "Full Body",
        "weekly_frequency": 1,
        "instructions": "Keep the reps controlled.",
        "days": [{"day_name": "Full A", "day_order": 1, "exercises": [exercise]}],
    }


def test_program_draft_is_assignment_gated_and_one_per_assignment(api):
    client, _, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    path = _program_draft_path(assignment_id)

    created = client.post(path, headers=coach_headers, json=_one_day_draft())
    repeated = client.post(path, headers=coach_headers, json=_one_day_draft("bp"))
    assert created.status_code == 200, created.text
    assert repeated.status_code == 409, repeated.text
    assert "already exists" in repeated.json()["detail"]
    assert client.get(path, headers=coach_headers).status_code == 200
    assert client.get("/programs/active", headers=player_headers).json() is None

    replaced = client.put(path, headers=coach_headers, json=_one_day_draft("row"))
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["draft"]["days"][0]["exercises"][0]["exercise_id"] == "row"
    assert client.get(path, headers=player_headers).status_code == 403

    discarded = client.delete(path, headers=coach_headers)
    assert discarded.status_code == 204
    assert client.get(path, headers=coach_headers).status_code == 404


def test_program_draft_can_be_created_empty(api):
    client, _, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)

    created = client.post(_program_draft_path(assignment_id), headers=coach_headers)

    assert created.status_code == 200, created.text
    assert created.json()["draft"]["days"] == []


def test_program_draft_strips_draft_level_publication_metadata(api):
    client, _, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)
    supplied = _one_day_draft()
    supplied.update(version=99)
    supplied["published_by_coach_account_id"] = "foreign-coach"

    created = client.post(_program_draft_path(assignment_id), headers=coach_headers, json=supplied)

    assert created.status_code == 200, created.text
    response = created.json()
    assert "version" not in response["draft"]
    assert "published_by_coach_account_id" not in response["draft"]


def test_program_draft_rejects_nested_server_metadata(api):
    client, _, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)
    supplied = _one_day_draft()
    supplied["id"] = "old-program"
    supplied["days"][0]["exercises"][0]["id"] = "old-exercise"
    supplied["days"][0]["exercises"][0]["version"] = 12

    response = client.post(_program_draft_path(assignment_id), headers=coach_headers, json=supplied)

    assert response.status_code == 422
    locations = [issue["loc"][1:] for issue in response.json()["detail"]]
    assert ["id"] in locations
    assert ["days", 0, "exercises", 0, "id"] in locations
    assert ["days", 0, "exercises", 0, "version"] in locations


def test_program_draft_rejects_fields_outside_the_program_shape(api):
    client, _, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)
    supplied = _one_day_draft()
    supplied["unrecognized_program_field"] = "unexpected"

    response = client.post(
        _program_draft_path(assignment_id),
        headers=coach_headers,
        json=supplied,
    )

    assert response.status_code == 422
    assert any(
        issue["loc"][-1] == "unrecognized_program_field"
        for issue in response.json()["detail"]
    )


def test_program_draft_write_that_races_assignment_end_is_discarded(api, monkeypatch):
    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    original_lookup = db.get_active_assignment_for_coach
    lookups = 0

    def end_after_authorization(coach_account_id, requested_assignment_id):
        nonlocal lookups
        lookups += 1
        if lookups == 1:
            return original_lookup(coach_account_id, requested_assignment_id)
        return None

    monkeypatch.setattr(db, "get_active_assignment_for_coach", end_after_authorization)

    response = client.post(
        _program_draft_path(assignment_id), headers=coach_headers, json=_one_day_draft()
    )

    assert response.status_code == 403
    player = db.get_account(player_account_id)
    with db.open_ledger(player["ledger_id"]) as ledger:
        assert ledger.get_program_draft(assignment_id) is None


def test_program_draft_denies_unknown_foreign_and_ended_assignments_identically(api):
    client, _, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    other_headers = _make_coach(client, api[1], "other")
    path = _program_draft_path(assignment_id)
    foreign = client.get(path, headers=other_headers)
    unknown = client.get(_program_draft_path("missing"), headers=other_headers)
    ended = client.post("/assignments/me/end", headers=player_headers)
    assert ended.status_code == 200
    revoked = client.get(path, headers=coach_headers)
    assert [response.status_code for response in (foreign, unknown, revoked)] == [403, 403, 403]
    assert foreign.json() == unknown.json() == revoked.json()


@pytest.mark.parametrize(
    ("draft", "code", "field"),
    [
        ({"days": []}, "no_days", "days"),
        (_one_day_draft("missing"), "unknown_exercise", "exercise_id"),
        (_one_day_draft(target_sets=0), "invalid_sets", "target_sets"),
        (_one_day_draft(target_reps_min=31, target_reps_max=31), "invalid_reps", "target_reps_min"),
        (_one_day_draft(target_reps_min=10, target_reps_max=8), "invalid_reps", "target_reps_min"),
        (_one_day_draft(target_rir=6), "invalid_rir", "target_rir"),
        (
            {
                **_one_day_draft(),
                "days": [
                    {
                        "day_name": "Full A",
                        "day_order": 1,
                        "exercises": [
                            _one_day_draft()["days"][0]["exercises"][0] for _ in range(15)
                        ],
                    }
                ],
            },
            "too_many_exercises",
            "exercises",
        ),
    ],
)
def test_program_draft_publish_rejects_invalid_structure(api, draft, code, field):
    client, _, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)
    path = _program_draft_path(assignment_id)
    assert client.post(path, headers=coach_headers, json=draft).status_code == 200

    published = client.post(f"{path}/publish", headers=coach_headers)

    assert published.status_code == 400
    issues = published.json()["detail"]["errors"]
    assert any(issue["code"] == code for issue in issues)
    matching = next(issue for issue in issues if issue["code"] == code)
    assert matching["location"]["field"] == field
    assert matching["message"]


@pytest.mark.parametrize(
    ("field", "value", "expected_location"),
    [
        ("warmup_sets", 5, ["days", 0, "exercises", 0, "warmup_sets"]),
        ("tempo", "x" * 51, ["days", 0, "exercises", 0, "tempo"]),
        ("notes", "x" * 2001, ["days", 0, "exercises", 0, "notes"]),
    ],
)
def test_program_draft_save_validates_exercise_ranges_and_lengths(
    api, field, value, expected_location
):
    client, _, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)
    path = _program_draft_path(assignment_id)
    created = client.post(path, headers=coach_headers, json=_one_day_draft())
    assert created.status_code == 200, created.text
    draft = created.json()["draft"]
    draft["days"][0]["exercises"][0][field] = value

    response = client.put(path, headers=coach_headers, json=draft)

    assert response.status_code == 422
    issue = next(
        issue for issue in response.json()["detail"] if issue["loc"][1:] == expected_location
    )
    assert issue["type"] in {"less_than_equal", "string_too_long"}


def test_program_draft_save_validation_locates_warmup_movement(api):
    client, _, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)
    path = _program_draft_path(assignment_id)
    created = client.post(path, headers=coach_headers, json=_one_day_draft())
    draft = created.json()["draft"]
    draft["days"][0]["warmup_exercises"] = [
        {"exercise_name": "Band pull apart", "sets": 4}
    ]

    response = client.put(path, headers=coach_headers, json=draft)

    assert response.status_code == 422
    issue = response.json()["detail"][0]
    assert issue["loc"] == ["body", "days", 0, "warmup_exercises", 0, "sets"]


def test_coach_publication_loads_broader_prescription_range(api):
    client, _, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    path = _program_draft_path(assignment_id)
    draft = _one_day_draft(target_sets=5)

    assert client.post(path, headers=coach_headers, json=draft).status_code == 200
    published = client.post(f"{path}/publish", headers=coach_headers)

    assert published.status_code == 200, published.text
    assert published.json()["days"][0]["exercises"][0]["target_sets"] == 5
    active = client.get("/programs/active", headers=player_headers)
    assert active.status_code == 200, active.text
    assert active.json()["days"][0]["exercises"][0]["target_sets"] == 5


def test_manual_program_publish_records_one_coach_publication_event(api, recording_analytics):
    client, _, _ = api
    coach_headers, _, assignment_id, coach_account_id, _ = _assigned_player(api)
    path = _program_draft_path(assignment_id)
    assert client.post(path, headers=coach_headers, json=_one_day_draft()).status_code == 200

    published = client.post(
        f"{path}/publish", headers={**coach_headers, "X-MAYOS-Client": "web/1.4.0"}
    )

    assert published.status_code == 200, published.text
    events = [event for event in recording_analytics.events if event["event"] == "coach_program_published"]
    assert len(events) == 1
    assert events[0]["distinct_id"] == coach_account_id
    assert events[0]["properties"] | {"env": "test"} == {
        "role": "coach",
        "platform": "web",
        "app_version": "1.4.0",
        "env": "test",
        "day_count": 1,
        "first_for_assignment": True,
        "is_coaching_action": True,
    }


def test_manual_program_publish_sets_rir_provenance_version_notice_and_authority(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    path = _program_draft_path(assignment_id)
    assert client.post(path, headers=coach_headers, json=_one_day_draft(target_rir=5)).status_code == 200
    before_usage = db.catalog_conn.execute(
        "SELECT COUNT(*) FROM model_usage WHERE account_id = ?", (coach_account_id,)
    ).fetchone()[0]
    monkeypatch.setattr("svc.llm.run_inference_sync", lambda *args, **kwargs: pytest.fail("AI called"))

    published = client.post(f"{path}/publish", headers=coach_headers)

    assert published.status_code == 200, published.text
    assert published.json()["version"] == 1
    assert published.json()["published_by_coach_account_id"] == coach_account_id
    exercise = published.json()["days"][0]["exercises"][0]
    assert exercise["target_rpe"] == 5
    assert client.get(path, headers=coach_headers).status_code == 404
    active = client.get("/programs/active", headers=player_headers).json()
    assert active["version"] == 1
    assert active["player_controls_program"] is False
    active_exercise = active["days"][0]["exercises"][0]
    assert active_exercise["exercise_id"] == "sq"
    assert active_exercise["target_sets"] == 3
    assert active_exercise["target_reps_min"] == 6
    assert active_exercise["target_reps_max"] == 8
    assert active_exercise["target_rpe"] == 5
    notices = client.get("/assignments/notices", headers=player_headers).json()["notices"]
    assert notices[0]["kind"] == "program_published"
    assert db.catalog_conn.execute(
        "SELECT COUNT(*) FROM model_usage WHERE account_id = ?", (coach_account_id,)
    ).fetchone()[0] == before_usage


def test_program_draft_preserves_fractional_rir_as_target_rpe(api):
    client, _, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)
    path = _program_draft_path(assignment_id)
    assert client.post(path, headers=coach_headers, json=_one_day_draft(target_rir=1.5)).status_code == 200

    published = client.post(f"{path}/publish", headers=coach_headers)

    assert published.status_code == 200, published.text
    assert published.json()["days"][0]["exercises"][0]["target_rpe"] == 8.5


def test_multi_day_program_draft_round_trips_every_field_through_publish(api):
    client, _, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    path = _program_draft_path(assignment_id)
    draft = {
        "program_name": "Four day strength plan",
        "split_type": "Upper/Lower",
        "weekly_frequency": 2,
        "instructions": "Keep all reps controlled.",
        "days": [
            {
                "day_name": "Upper A",
                "day_order": 1,
                "warmup_exercises": [
                    {
                        "exercise_id": "band_pull_apart",
                        "equipment": "Band",
                        "exercise_name": "Band Pull Apart",
                        "sets": 2,
                        "reps": 12,
                        "rest_seconds": 30,
                        "notes": "Easy pace",
                        "image_path": "warmup.png",
                        "gif_path": "warmup.gif",
                    }
                ],
                "exercises": [
                    {
                        "exercise_id": "bp",
                        "target_sets": 4,
                        "target_reps_min": 6,
                        "target_reps_max": 8,
                        "target_rir": 1.5,
                        "slot_key": "horizontal_press",
                        "warmup_sets": 3,
                        "rest_seconds": 150,
                        "tempo": "3-1-1",
                        "notes": "Pause on the chest",
                        "suggested_substitutes": [
                            {"exercise_id": "incline_bp", "exercise_name": "Incline Bench Press"}
                        ],
                    }
                ],
                "cardio": "Cycle for 10 minutes",
            },
            {
                "day_name": "Lower A",
                "day_order": 2,
                "warmup_exercises": [
                    {
                        "exercise_name": "Bodyweight squat",
                        "sets": 1,
                        "reps": 10,
                        "rest_seconds": 20,
                        "notes": "Smooth range",
                    }
                ],
                "exercises": [
                    {
                        "exercise_id": "sq",
                        "target_sets": 3,
                        "target_reps_min": 8,
                        "target_reps_max": 10,
                        "target_rir": 2,
                        "warmup_sets": 1,
                        "rest_seconds": 210,
                        "tempo": None,
                        "notes": None,
                    }
                ],
                "cardio": None,
            },
        ],
    }

    created = client.post(path, headers=coach_headers, json=draft)
    assert created.status_code == 200, created.text
    saved = client.put(path, headers=coach_headers, json=created.json()["draft"])
    assert saved.status_code == 200, saved.text
    reopened = client.get(path, headers=coach_headers)
    assert reopened.status_code == 200
    saved_days = reopened.json()["draft"]["days"]
    assert [day["day_name"] for day in saved_days] == ["Upper A", "Lower A"]
    assert [day["day_order"] for day in saved_days] == [1, 2]
    assert saved_days[0]["warmup_exercises"][0]["notes"] == "Easy pace"
    assert saved_days[0]["warmup_exercises"][0]["image_path"] == "warmup.png"
    assert saved_days[0]["warmup_exercises"][0]["gif_path"] == "warmup.gif"
    assert saved_days[0]["exercises"][0]["target_rir"] == 1.5
    assert saved_days[0]["exercises"][0]["slot_key"] == "horizontal_press"
    assert saved_days[0]["exercises"][0]["warmup_sets"] == 3
    assert saved_days[0]["exercises"][0]["rest_seconds"] == 150
    assert saved_days[0]["exercises"][0]["tempo"] == "3-1-1"
    assert saved_days[0]["exercises"][0]["notes"] == "Pause on the chest"
    assert saved_days[0]["exercises"][0]["suggested_substitutes"] == [
        {"exercise_id": "incline_bp", "exercise_name": "Incline Bench Press"}
    ]
    assert saved_days[0]["cardio"] == "Cycle for 10 minutes"
    assert saved_days[1]["warmup_exercises"][0]["notes"] == "Smooth range"
    assert saved_days[1]["cardio"] is None

    published = client.post(f"{path}/publish", headers=coach_headers)

    assert published.status_code == 200, published.text
    days = published.json()["days"]
    assert len(days) == 2
    assert [day["day_name"] for day in days] == ["Upper A", "Lower A"]
    assert days[0]["warmup_exercises"][0]["notes"] == "Easy pace"
    assert days[0]["warmup_exercises"][0]["image_path"] == "warmup.png"
    assert days[0]["warmup_exercises"][0]["gif_path"] == "warmup.gif"
    assert days[0]["cardio"] == "Cycle for 10 minutes"
    upper_exercise = days[0]["exercises"][0]
    assert upper_exercise["target_rpe"] == 8.5
    assert upper_exercise["warmup_sets"] == 3
    assert upper_exercise["rest_seconds"] == 150
    assert upper_exercise["tempo"] == "3-1-1"
    assert upper_exercise["notes"] == "Pause on the chest"
    assert upper_exercise["slot_key"] == "horizontal_press"
    assert upper_exercise["suggested_substitutes"] == [
        {"exercise_id": "incline_bp", "exercise_name": "Incline Bench Press"}
    ]
    assert days[1]["warmup_exercises"][0]["notes"] == "Smooth range"
    assert days[1]["cardio"] is None

    active = client.get("/programs/active", headers=player_headers)
    assert active.status_code == 200, active.text
    assert active.json()["days"] == days


def test_ending_assignment_discards_program_draft(api):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, player_account_id = _assigned_player(api)
    path = _program_draft_path(assignment_id)
    assert client.post(path, headers=coach_headers, json=_one_day_draft()).status_code == 200

    assert client.post("/assignments/me/end", headers=player_headers).status_code == 200
    player = db.get_account(player_account_id)
    with db.open_ledger(player["ledger_id"]) as ledger:
        assert ledger.get_program_draft(assignment_id) is None


def test_assignment_end_succeeds_when_post_commit_draft_cleanup_fails(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    assert client.post(
        _program_draft_path(assignment_id), headers=coach_headers, json=_one_day_draft()
    ).status_code == 200

    original_open_ledger = db.open_ledger
    open_calls = 0

    def fail_cleanup_open_ledger(ledger_id):
        nonlocal open_calls
        open_calls += 1
        if open_calls == 1:
            return original_open_ledger(ledger_id)
        raise OSError("temporary player ledger failure")

    monkeypatch.setattr(db, "open_ledger", fail_cleanup_open_ledger)
    ended = client.post("/assignments/me/end", headers=player_headers)

    assert ended.status_code == 200, ended.text
    assignment = db.catalog_conn.execute(
        "SELECT status FROM assignments WHERE assignment_id = ?", (assignment_id,)
    ).fetchone()
    assert assignment[0] == "ended"


def test_disabling_coach_capability_discards_assignment_program_drafts(api):
    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    path = _program_draft_path(assignment_id)
    assert client.post(path, headers=coach_headers, json=_one_day_draft()).status_code == 200

    disabled = client.post("/coach/capability/disable", headers=coach_headers)

    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["ended_assignments"] == 1
    player = db.get_account(player_account_id)
    with db.open_ledger(player["ledger_id"]) as ledger:
        assert ledger.get_program_draft(assignment_id) is None


# --------------------------------------------------------------------------
# Program authority
# --------------------------------------------------------------------------


def test_player_self_service_works_while_assigned_before_first_publication(api, monkeypatch):
    client, db, _ = api
    _, player_headers, assignment_id, _, _ = _assigned_player(api)
    _player_generation(db, monkeypatch)

    generated = client.post("/programs/generate", headers=player_headers, json={})
    assert generated.status_code == 200, generated.text

    active = client.get("/programs/active", headers=player_headers).json()
    assert active["published_by_coach_account_id"] is None


def test_player_generate_refused_after_publication(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    refused = client.post("/programs/generate", headers=player_headers, json={})
    assert refused.status_code == 403
    assert refused.json()["detail"] == programs_service.COACH_CONTROLLED_ERROR


def test_assistant_swap_refused_when_coach_controls_program(api, monkeypatch):
    from agent import assistant_graph

    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, player_account_id = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    db.switch_user("p1")
    swap = MagicMock(return_value=True)
    monkeypatch.setattr(assistant_graph, "substitute_program_exercise", swap)

    from langchain_core.messages import HumanMessage

    state = {
        "messages": [HumanMessage(content="swap squat for bench press")],
        "trainee_id": "p1",
        "player_account_id": player_account_id,
        "intent": "exercise_substitution",
        "intent_metadata": {"mode": "direct_swap", "source_exercise": "Squat", "target_exercise": "Bench Press"},
    }
    result = assistant_graph.exercise_substitution_node(
        state, {"configurable": {"ledger": db.ledger, "store": db}}
    )
    assert result["response_content"] == programs_service.COACH_CONTROLLED_REQUEST_ERROR
    swap.assert_not_called()


def test_assistant_mutation_refused_when_coach_controls_program(api, monkeypatch):
    from agent import assistant_graph
    from langchain_core.messages import HumanMessage

    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    pipeline = MagicMock(return_value=(_program(), "md"))
    monkeypatch.setattr(assistant_graph, "generate_program_pipeline", pipeline)
    db.switch_user("p1")

    state = {
        "messages": [HumanMessage(content="rebuild my program")],
        "trainee_id": "p1",
        "player_account_id": player_account_id,
        "intent": "program_mutation",
        "intent_metadata": {"target_frequency": None},
    }
    result = assistant_graph.program_mutation_node(
        state, {"configurable": {"ledger": db.ledger, "store": db}}
    )
    assert result["response_content"] == programs_service.COACH_CONTROLLED_REQUEST_ERROR
    pipeline.assert_not_called()


# --------------------------------------------------------------------------
# Unassignment retains content and returns authority
# --------------------------------------------------------------------------


@pytest.mark.parametrize("ended_by", ["coach", "player"])
def test_unassignment_retains_program_and_returns_authority(api, monkeypatch, ended_by):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    if ended_by == "coach":
        ended = client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers)
    else:
        ended = client.post("/assignments/me/end", headers=player_headers)
    assert ended.status_code == 200, ended.text

    retained = client.get("/programs/active", headers=player_headers).json()
    assert retained["version"] == 1
    assert retained["published_by_coach_account_id"] == coach_account_id

    _player_generation(db, monkeypatch)
    assert client.post("/programs/generate", headers=player_headers, json={}).status_code == 200

    denied = _publish(client, coach_headers, assignment_id)
    assert denied.status_code == 403
    assert denied.json()["detail"] == coach_history_service.DENIED_ERROR


def test_fresh_assignment_before_publication_keeps_self_service(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    assert client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers).status_code == 200

    new_token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    redeemed = client.post(
        "/assignments/invites/redeem", headers=player_headers, json={"token": new_token, "consent": True}
    )
    assert redeemed.status_code == 200, redeemed.text

    retained = client.get("/programs/active", headers=player_headers).json()
    assert retained["version"] == 1
    assert retained["published_by_coach_account_id"] == coach_account_id

    _player_generation(db, monkeypatch)
    generated = client.post("/programs/generate", headers=player_headers, json={})
    assert generated.status_code == 200, generated.text


# --------------------------------------------------------------------------
# Denial is generic
# --------------------------------------------------------------------------


def test_non_coach_cannot_publish(api, monkeypatch):
    client, db, _ = api
    _, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)

    denied = _publish(client, player_headers, assignment_id)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Coach capability required."


def test_unknown_and_other_coach_assignments_are_indistinguishable(api, monkeypatch):
    client, db, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(db, monkeypatch)
    other_headers = _make_coach(client, db, "intruder", capacity=5)

    other = _publish(client, other_headers, assignment_id)
    unknown = _publish(client, other_headers, "does-not-exist")
    assert other.status_code == unknown.status_code == 403
    assert other.json()["detail"] == unknown.json()["detail"] == coach_history_service.DENIED_ERROR


def test_publish_requires_authentication(api):
    client, _, _ = api
    assert client.post("/coach/assignments/x/program").status_code == 401
