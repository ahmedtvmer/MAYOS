"""Coach program publication contract tests (ticket #26).

Exercises the public FastAPI surface against real temporary SQLite catalogs and
player ledgers. Covers assignment-gated publication with coach provenance and a
stable version, the player's in-app notice, program authority transfer (player
self-service before publication, refused after), retention and authority return
on unassignment, version increments, and the generic denial for every
non-active assignment case.
"""

import copy
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
    PersistedProgramSchema,
)
from database.database_manager import DatabaseManager
from database.registry.coach_exercises import CoachExerciseCreate
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
    from service.analytics import override_analytics_preference_reader

    override_analytics_preference_reader(db.analytics_preference_allows)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db, tmp_path / "users"
    finally:
        override_analytics_preference_reader(None)
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


def _coach_generation(monkeypatch):
    """Replaces the generator while leaving draft persistence to the real service."""

    def fake(request, *, inference_call=None, ledger):
        source = _program()
        frequency = request.frequency_override or source.weekly_frequency
        day = source.days[0]
        days = [
            day.model_copy(
                update={
                    "day_name": f"Full {index}",
                    "day_order": index,
                    "exercises": [
                        exercise.model_copy(update={"target_rpe": 8.0, "notes": "Catalog execution steps."})
                        for exercise in day.exercises
                    ],
                }
            )
            for index in range(1, frequency + 1)
        ]
        program = source.model_copy(
            update={"weekly_frequency": frequency, "days": days}
        )
        return program, "md"

    monkeypatch.setattr("service.coach_programs.generate_program_draft_pipeline", fake)


def _player_generation(db, monkeypatch):
    """Replaces the pipeline at the player service seam (self-service, no provenance)."""

    def fake(**kwargs):
        program = _program()
        kwargs["ledger"].save_training_program(program.model_dump())
        return program, "md"

    monkeypatch.setattr("service.programs.generate_program_pipeline", fake)


def _generate_draft(client, coach_headers, assignment_id, **body):
    return client.post(
        f"/coach/assignments/{assignment_id}/program-draft/generate",
        headers=coach_headers,
        json=body,
    )


def _publish(client, coach_headers, assignment_id, **body):
    generated = _generate_draft(client, coach_headers, assignment_id, **body)
    if generated.status_code != 200:
        return generated
    return client.post(
        f"/coach/assignments/{assignment_id}/program-draft/publish",
        headers=coach_headers,
    )


# --------------------------------------------------------------------------
# Publication, provenance, version, notice
# --------------------------------------------------------------------------


def test_publish_activates_immediately_with_provenance_and_notice(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(monkeypatch)

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


def test_approving_active_program_publishes_next_version_and_keeps_workouts(api, recording_analytics):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, player_account_id = _assigned_player(api)
    _seed_complete_active_program(db, player_account_id)
    initial = client.get(
        f"/coach/assignments/{assignment_id}/program", headers=coach_headers
    ).json()["program"]
    draft_path = _program_draft_path(assignment_id)
    existing_draft = client.post(
        draft_path, headers=coach_headers, json=_one_day_draft("row")
    ).json()["draft"]

    committed = client.post(
        "/workouts/sessions",
        headers=player_headers,
        json={
            "day_order": 1,
            "readiness": 4,
            "session_notes": "Completed before the new version.",
            "sets": [
                {
                    "exercise": {
                        "exercise_id": "bp",
                        "exercise_name": "Bench Press",
                        "target_sets": 4,
                        "target_reps_min": 6,
                        "target_reps_max": 8,
                        "target_rpe": 8.5,
                        "rest_seconds": 150,
                        "notes": "Pause on the chest.",
                    },
                    "sets": [{"weight_kg": 60, "reps": 6, "rpe": 8}],
                }
            ],
        },
    )
    assert committed.status_code == 201, committed.text
    player = db.get_account(player_account_id)
    with db.open_ledger(player["ledger_id"]) as ledger:
        workouts_before = [
            tuple(row)
            for row in ledger.conn.execute("SELECT * FROM workout_sessions ORDER BY id")
        ]
        sets_before = [
            tuple(row)
            for row in ledger.conn.execute("SELECT * FROM workout_sets ORDER BY id")
        ]

    published = client.post(
        f"/coach/assignments/{assignment_id}/program/approve",
        headers=coach_headers,
        json={"expected_active_version": initial["version"]},
    )

    assert published.status_code == 200, published.text
    assert published.json()["version"] == 2
    assert published.json()["published_by_coach_account_id"] == coach_account_id
    for field in ("program_name", "split_type", "weekly_frequency", "instructions", "days"):
        assert published.json()[field] == initial[field]
    assert client.get("/programs/active", headers=player_headers).json()["version"] == 2
    assert client.get(draft_path, headers=coach_headers).json()["draft"] == existing_draft
    refused = client.post("/programs/generate", headers=player_headers, json={})
    assert refused.status_code == 403
    assert refused.json()["detail"] == programs_service.COACH_CONTROLLED_ERROR

    republished = client.post(
        f"/coach/assignments/{assignment_id}/program/approve",
        headers=coach_headers,
        json={"expected_active_version": 2},
    )
    assert republished.status_code == 200, republished.text
    assert republished.json()["version"] == 3
    assert republished.json()["published_by_coach_account_id"] == coach_account_id
    assert client.get(draft_path, headers=coach_headers).json()["draft"] == existing_draft

    with db.open_ledger(player["ledger_id"]) as ledger:
        assert [
            tuple(row)
            for row in ledger.conn.execute("SELECT * FROM workout_sessions ORDER BY id")
        ] == workouts_before
        assert [
            tuple(row)
            for row in ledger.conn.execute("SELECT * FROM workout_sets ORDER BY id")
        ] == sets_before
    events = [
        event for event in recording_analytics.events
        if event["event"] == "coach_program_published"
    ]
    assert len(events) == 2
    assert all(event["properties"]["is_coaching_action"] for event in events)


def test_approve_active_program_rejects_stale_version_without_changes(api, recording_analytics):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, player_account_id = _assigned_player(api)
    _seed_complete_active_program(db, player_account_id)
    substitution = client.post(
        "/programs/active/substitutions",
        headers=player_headers,
        json={
            "day_name": "Upper A",
            "exercise_id": "bp",
            "replacement_exercise_id": "row",
            "expected_active_version": 1,
        },
    )
    assert substitution.status_code == 200, substitution.text
    draft_path = _program_draft_path(assignment_id)
    draft = client.post(draft_path, headers=coach_headers, json=_one_day_draft()).json()["draft"]
    player = db.get_account(player_account_id)

    refused = client.post(
        f"/coach/assignments/{assignment_id}/program/approve",
        headers=coach_headers,
        json={"expected_active_version": 1},
    )

    assert refused.status_code == 409
    assert refused.json() == {"error": "program_version_mismatch", "active_version": 2}
    assert client.get(draft_path, headers=coach_headers).json()["draft"] == draft
    with db.open_ledger(player["ledger_id"]) as ledger:
        assert [row[0] for row in ledger.conn.execute(
            "SELECT version FROM training_programs ORDER BY version"
        )] == [1, 2]
    assert client.get("/assignments/notices", headers=player_headers).json()["notices"] == []
    assert not [event for event in recording_analytics.events if event["event"] == "coach_program_published"]


def test_approve_active_program_without_program_returns_not_found(api):
    client, _, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)

    response = client.post(
        f"/coach/assignments/{assignment_id}/program/approve",
        headers=coach_headers,
        json={"expected_active_version": 1},
    )

    assert response.status_code == 404


def test_approve_active_program_denies_foreign_unknown_and_ended_assignments_identically(api):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    other_headers = _make_coach(client, db, "other")
    path = f"/coach/assignments/{assignment_id}/program/approve"
    body = {"expected_active_version": 1}

    foreign = client.post(path, headers=other_headers, json=body)
    unknown = client.post(
        "/coach/assignments/missing/program/approve", headers=other_headers, json=body
    )
    assert client.post("/assignments/me/end", headers=player_headers).status_code == 200
    ended = client.post(path, headers=coach_headers, json=body)

    assert [response.status_code for response in (foreign, unknown, ended)] == [403, 403, 403]
    assert foreign.json() == unknown.json() == ended.json()


def test_second_publish_increments_version_and_keeps_first_stable(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, _ = _assigned_player(api)
    _coach_generation(monkeypatch)

    assert _publish(client, coach_headers, assignment_id).json()["version"] == 1
    assert _publish(client, coach_headers, assignment_id).json()["version"] == 2

    assert client.get("/programs/active", headers=player_headers).json()["version"] == 2

    db.switch_user("p1")
    rows = db.conn.execute(
        "SELECT version, published_by_coach_account_id FROM training_programs ORDER BY version ASC"
    ).fetchall()
    assert [int(row[0]) for row in rows] == [1, 2]
    assert all(row[1] == coach_account_id for row in rows)


def test_generate_draft_preserves_active_program_profile_and_authority(api, monkeypatch):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, player_account_id = _assigned_player(api)
    _coach_generation(monkeypatch)
    player = db.get_account(player_account_id)
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.save_training_program(_program().model_dump())
        original = ledger.get_active_program()
        original_profile = ledger.get_player_profile()

    response = _generate_draft(
        client,
        coach_headers,
        assignment_id,
        frequency_override=2,
        rep_preference_override="high",
    )

    assert response.status_code == 200, response.text
    draft = response.json()["draft"]
    assert draft["weekly_frequency"] == 2
    assert draft["days"][0]["exercises"][0]["notes"] is None
    assert client.get("/programs/active", headers=player_headers).json()["version"] == original.version
    with db.open_ledger(player["ledger_id"]) as ledger:
        assert ledger.get_active_program().model_dump() == original.model_dump()
        assert ledger.get_player_profile() == original_profile
        assert ledger.get_program_draft(assignment_id)["draft"]["weekly_frequency"] == 2
        assert db.get_active_assignment_for_player(player_account_id)["coach_account_id"] == coach_account_id
        assert ledger.get_program_draft(assignment_id)["draft"]["days"][0]["exercises"][0]["target_rir"] == 2


def test_generated_draft_can_be_edited_and_published(api, monkeypatch):
    client, _, _ = api
    coach_headers, player_headers, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(monkeypatch)

    generated = _generate_draft(client, coach_headers, assignment_id)
    assert generated.status_code == 200, generated.text
    assert client.get("/programs/active", headers=player_headers).json() is None

    draft = generated.json()["draft"]
    draft["days"][0]["day_name"] = "Coach edited day"
    saved = client.put(
        _program_draft_path(assignment_id),
        headers=coach_headers,
        json=draft,
    )
    assert saved.status_code == 200, saved.text
    assert client.get("/programs/active", headers=player_headers).json() is None

    published = client.post(
        f"{_program_draft_path(assignment_id)}/publish",
        headers=coach_headers,
    )
    assert published.status_code == 200, published.text
    assert published.json()["version"] == 1
    assert published.json()["days"][0]["day_name"] == "Coach edited day"


def test_generate_draft_requires_confirmation_to_replace_existing_draft(api, monkeypatch):
    client, db, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(monkeypatch)
    path = _program_draft_path(assignment_id)
    original = _one_day_draft()
    assert client.post(path, headers=coach_headers, json=original).status_code == 200

    refused = _generate_draft(client, coach_headers, assignment_id, frequency_override=2)

    assert refused.status_code == 409
    untouched = client.get(path, headers=coach_headers).json()["draft"]
    assert untouched["program_name"] == original["program_name"]
    assert untouched["days"][0]["exercises"][0]["exercise_id"] == "sq"
    assert untouched["days"][0]["exercises"][0]["target_sets"] == 3

    replaced = client.post(
        f"{path}/generate?replace=true",
        headers=coach_headers,
        json={"frequency_override": 2},
    )

    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["draft"]["program_name"] == "Coach Plan"
    assert client.get(path, headers=coach_headers).json()["draft"]["program_name"] == "Coach Plan"


def test_old_direct_publish_route_is_removed(api):
    client, _, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)

    response = client.post(f"/coach/assignments/{assignment_id}/program", headers=coach_headers, json={})

    assert response.status_code == 405


def _program_draft_path(assignment_id):
    return f"/coach/assignments/{assignment_id}/program-draft"


def _seed_complete_active_program(db, player_account_id):
    old_coach_exercise = db.create_coach_exercise(
        "previous-coach",
        CoachExerciseCreate(
            "Pin Squat",
            body_part="Quads",
            equipment="Barbell",
            note="Pause on the pins.",
            video_url="https://example.com/pin-squat",
        ),
    )
    program = PersistedProgramSchema.model_validate(
        {
            "program_name": "Strength and conditioning",
            "split_type": "Upper/Lower",
            "weekly_frequency": 2,
            "instructions": "Leave one rep in reserve.",
            "days": [
                {
                    "day_name": "Upper A",
                    "day_order": 1,
                    "warmup_exercises": [
                        {
                            "exercise_id": "row",
                            "equipment": "Cable",
                            "exercise_name": "Light cable row",
                            "sets": 2,
                            "reps": 12,
                            "rest_seconds": 30,
                            "notes": "Keep this easy.",
                            "image_path": "warmup.png",
                            "gif_path": "warmup.gif",
                        }
                    ],
                    "exercises": [
                        {
                            "exercise_id": "bp",
                            "exercise_name": "Bench Press",
                            "target_sets": 4,
                            "target_reps_min": 6,
                            "target_reps_max": 8,
                            "target_rpe": 8.5,
                            "rest_seconds": 150,
                            "warmup_sets": 3,
                            "tempo": "3-1-1",
                            "notes": "Pause on the chest.",
                            "slot_key": "horizontal_press",
                            "suggested_substitutes": [
                                {"exercise_id": "sq", "exercise_name": "Squat"}
                            ],
                        }
                    ],
                    "cardio": "Cycle for 10 minutes.",
                },
                {
                    "day_name": "Lower A",
                    "day_order": 2,
                    "exercises": [
                        {
                            "exercise_id": old_coach_exercise["id"],
                            "exercise_name": old_coach_exercise["name"],
                            "target_sets": 3,
                            "target_reps_min": 5,
                            "target_reps_max": 8,
                            "target_rpe": 8.0,
                            "rest_seconds": 180,
                            "warmup_sets": 2,
                            "notes": "Control the descent.",
                        }
                    ],
                },
            ],
        }
    )
    player = db.get_account(player_account_id)
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.save_training_program(program.model_dump())


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


def test_copy_active_program_to_draft_preserves_the_complete_program(api):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, _, player_account_id = _assigned_player(api)
    _seed_complete_active_program(db, player_account_id)
    active = client.get(
        f"/coach/assignments/{assignment_id}/program", headers=coach_headers
    ).json()["program"]

    copied = client.post(
        f"{_program_draft_path(assignment_id)}/copy-active",
        headers=coach_headers,
    )

    assert copied.status_code == 200, copied.text
    expected_draft = copy.deepcopy(active)
    for metadata in ("version", "provenance", "active_since"):
        expected_draft.pop(metadata, None)
    for day in expected_draft["days"]:
        for exercise in day["exercises"]:
            exercise["target_rir"] = 10 - exercise.pop("target_rpe")
    assert copied.json()["draft"] == expected_draft
    active_after = client.get("/programs/active", headers=player_headers).json()
    assert active_after["version"] == 1
    assert active_after["published_by_coach_account_id"] is None


def test_copy_active_program_requires_confirmation_and_an_active_program(api):
    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    copy_path = f"{_program_draft_path(assignment_id)}/copy-active"

    no_program = client.post(copy_path, headers=coach_headers)
    assert no_program.status_code == 404

    _seed_complete_active_program(db, player_account_id)
    original = _one_day_draft()
    draft_path = _program_draft_path(assignment_id)
    created = client.post(draft_path, headers=coach_headers, json=original)
    assert created.status_code == 200, created.text

    refused = client.post(copy_path, headers=coach_headers)
    assert refused.status_code == 409
    assert client.get(draft_path, headers=coach_headers).json()["draft"] == created.json()["draft"]

    replaced = client.post(f"{copy_path}?replace=true", headers=coach_headers)
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["draft"]["program_name"] == "Strength and conditioning"


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
    _coach_generation(monkeypatch)
    assert _publish(client, coach_headers, assignment_id).status_code == 200

    refused = client.post("/programs/generate", headers=player_headers, json={})
    assert refused.status_code == 403
    assert refused.json()["detail"] == programs_service.COACH_CONTROLLED_ERROR


def test_assistant_swap_refused_when_coach_controls_program(api, monkeypatch):
    from agent import assistant_graph

    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_account_id, player_account_id = _assigned_player(api)
    _coach_generation(monkeypatch)
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
    _coach_generation(monkeypatch)
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
    _coach_generation(monkeypatch)
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
    _coach_generation(monkeypatch)
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
    _coach_generation(monkeypatch)

    denied = _publish(client, player_headers, assignment_id)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Coach capability required."


def test_unknown_and_other_coach_assignments_are_indistinguishable(api, monkeypatch):
    client, db, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(monkeypatch)
    other_headers = _make_coach(client, db, "intruder", capacity=5)

    other = _publish(client, other_headers, assignment_id)
    unknown = _publish(client, other_headers, "does-not-exist")
    assert other.status_code == unknown.status_code == 403
    assert other.json()["detail"] == unknown.json()["detail"] == coach_history_service.DENIED_ERROR


def test_publish_requires_authentication(api):
    client, _, _ = api
    assert client.post("/coach/assignments/x/program-draft/generate", json={}).status_code == 401


def test_coach_reads_active_program_without_account_ids(api):
    client, db, _ = api
    coach_headers, _, assignment_id, coach_account_id, player_account_id = _assigned_player(api)
    player = db.get_account(player_account_id)
    with db.open_ledger(player["ledger_id"]) as ledger:
        program_data = _program().model_dump()
        exercise = program_data["days"][0]["exercises"][0]
        exercise.update(
            target_sets=4,
            target_reps_min=6,
            target_reps_max=8,
            target_rpe=8.0,
            rest_seconds=150,
            tempo="3-1-1",
            notes="Brace before each rep.",
        )
        ledger.save_training_program(program_data)
        active = ledger.get_active_program()

    response = client.get(f"/coach/assignments/{assignment_id}/program", headers=coach_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["has_draft"] is False
    assert "edited_by_player" not in body
    assert body["program"]["version"] == active.version
    assert body["program"]["provenance"] == "automatic"
    assert body["program"]["active_since"] == active.created_at
    prescribed = body["program"]["days"][0]["exercises"][0]
    assert prescribed["target_sets"] == 4
    assert (prescribed["target_reps_min"], prescribed["target_reps_max"]) == (6, 8)
    assert prescribed["target_rpe"] == 8.0
    assert prescribed["rest_seconds"] == 150
    assert prescribed["tempo"] == "3-1-1"
    assert prescribed["notes"] == "Brace before each rep."
    serialized = response.text
    assert coach_account_id not in serialized
    assert player_account_id not in serialized
    assert "published_by_coach_account_id" not in serialized


def test_coach_reads_program_as_published_by_current_coach(api, monkeypatch):
    client, _, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)
    _coach_generation(monkeypatch)
    published = _publish(client, coach_headers, assignment_id)
    assert published.status_code == 200, published.text

    response = client.get(f"/coach/assignments/{assignment_id}/program", headers=coach_headers)

    assert response.status_code == 200, response.text
    assert response.json()["program"]["provenance"] == "coach"


def test_active_program_read_is_not_recorded_as_a_coaching_action(api, recording_analytics):
    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    player = db.get_account(player_account_id)
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.save_training_program(_program().model_dump())
    event_count = len(recording_analytics.events)

    response = client.get(f"/coach/assignments/{assignment_id}/program", headers=coach_headers)

    assert response.status_code == 200, response.text
    assert len(recording_analytics.events) == event_count


def test_previous_coach_provenance_is_reported_without_identity(api):
    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    player = db.get_account(player_account_id)
    previous_coach_id = "previous-coach-account-id"
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.save_training_program(_program().model_dump(), published_by_coach_account_id=previous_coach_id)

    response = client.get(f"/coach/assignments/{assignment_id}/program", headers=coach_headers)

    assert response.status_code == 200, response.text
    assert response.json()["program"]["provenance"] == "automatic"
    assert previous_coach_id not in response.text


def test_empty_active_program_and_pending_draft_are_returned(api):
    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    player = db.get_account(player_account_id)
    with db.open_ledger(player["ledger_id"]) as ledger:
        assert ledger.get_active_program() is None

    empty = client.get(f"/coach/assignments/{assignment_id}/program", headers=coach_headers)
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"program": None, "has_draft": False}

    created = client.post(f"/coach/assignments/{assignment_id}/program-draft", headers=coach_headers, json={})
    assert created.status_code == 200, created.text
    pending = client.get(f"/coach/assignments/{assignment_id}/program", headers=coach_headers)
    assert pending.status_code == 200, pending.text
    assert pending.json() == {"program": None, "has_draft": True}


def test_active_program_read_uses_generic_assignment_denial(api):
    client, db, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)
    intruder_headers = _make_coach(client, db, "intruder", capacity=5)

    foreign = client.get(f"/coach/assignments/{assignment_id}/program", headers=intruder_headers)
    unknown = client.get("/coach/assignments/does-not-exist/program", headers=intruder_headers)
    ended_response = client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers)
    ended = client.get(f"/coach/assignments/{assignment_id}/program", headers=coach_headers)

    assert ended_response.status_code == 200
    assert foreign.status_code == unknown.status_code == ended.status_code == 403
    assert foreign.json()["detail"] == unknown.json()["detail"] == ended.json()["detail"]
    assert foreign.json()["detail"] == coach_history_service.DENIED_ERROR
