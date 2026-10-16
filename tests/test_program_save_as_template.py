"""Save a player's program as a template (ticket #307).

Drives the public FastAPI surface against a real temporary catalog and real
Training ledgers. Covers both sources (active program, open draft), the ADR 025
assignment gate before any ledger read, source-revision binding, reviewed-note
handling, and the guarantee that a template never carries player identity,
provenance or unreviewed free text.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import PersistedProgramSchema
from database.database_manager import DatabaseManager
from database.registry.coach_exercises import CoachExerciseCreate
from service import coach as coach_service
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"

# Distinct tokens planted in every copied free-text path. A template built from
# this program must never contain any of them: only reviewed decisions survive.
_SENTINELS = (
    "ZZNAME",
    "ZZINSTRUCTIONS",
    "ZZCARDIO",
    "ZZEXNAME",
    "ZZNOTE",
    "ZZBENCHNOTES",
    "ZZWARMUP",
    "ZZSQUAT",
)


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


def _make_coach(client, db, username, capacity=10):
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username, actor="cli")
    assert issued["ok"], issued
    assert (
        client.post(
            "/coach/invite/redeem", headers=headers, json={"token": issued["token"]}
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/coach/profile",
            headers=headers,
            json={
                "display_name": f"Coach {username}",
                "bio": "b",
                "specialization": "s",
                "capacity": capacity,
            },
        ).status_code
        == 200
    )
    return headers


def _assigned_player(api, player_name="p1"):
    client, db, _ = api
    coach_headers = _make_coach(client, db, "coach", capacity=5)
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    player = _register(client, player_name)
    player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": token, "consent": True},
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


def _program_with_player_notes() -> PersistedProgramSchema:
    """An active program whose free text names the player, as a real plan might."""
    return PersistedProgramSchema.model_validate(
        {
            "program_name": "ZZNAME Current block",
            "split_type": "Upper/Lower",
            "weekly_frequency": 1,
            "instructions": "ZZINSTRUCTIONS for p1",
            "days": [
                {
                    "day_name": "Upper A",
                    "day_order": 1,
                    "warmup_exercises": [
                        {
                            "exercise_id": "row",
                            "exercise_name": "Light row",
                            "notes": "ZZWARMUP Warm p1 up gently.",
                        }
                    ],
                    "exercises": [
                        {
                            "exercise_id": "bp",
                            "exercise_name": "ZZEXNAME Bench Press",
                            "target_sets": 4,
                            "target_reps_min": 6,
                            "target_reps_max": 8,
                            "target_rpe": 8.5,
                            "note": "ZZNOTE Cue written for p1.",
                            "notes": "ZZBENCHNOTES Pause for p1's shoulder.",
                        }
                    ],
                    "cardio": "ZZCARDIO ten minutes",
                },
                {
                    "day_name": "Lower A",
                    "day_order": 2,
                    "exercises": [
                        {
                            "exercise_id": "sq",
                            "exercise_name": "Squat",
                            "target_sets": 3,
                            "target_reps_min": 5,
                            "target_reps_max": 8,
                            "target_rpe": 8.0,
                            "notes": "ZZSQUAT p1's knee needs care.",
                        }
                    ],
                },
            ],
        }
    )


def _seed_active_program(
    db, player_account_id, *, published_by_coach_account_id=None
) -> None:
    player = db.get_account(player_account_id)
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.save_training_program(
            _program_with_player_notes().model_dump(),
            published_by_coach_account_id=published_by_coach_account_id,
        )


def _draft_body() -> dict:
    return {
        "program_name": "ZZNAME Draft block",
        "split_type": "Full Body",
        "weekly_frequency": 1,
        "instructions": "ZZINSTRUCTIONS draft",
        "days": [
            {
                "day_name": "Full A",
                "day_order": 1,
                "warmup_exercises": [],
                "exercises": [
                    {
                        "exercise_id": "sq",
                        "exercise_name": "ZZEXNAME Squat",
                        "target_sets": 3,
                        "target_reps_min": 5,
                        "target_reps_max": 8,
                        "target_rir": 2,
                        "notes": "ZZBENCHNOTES Keep this for p1.",
                    }
                ],
                "cardio": "ZZCARDIO draft finisher",
            }
        ],
    }


def _active_path(assignment_id: str) -> str:
    return f"/coach/assignments/{assignment_id}/program/save-as-template"


def _draft_path(assignment_id: str) -> str:
    return f"/coach/assignments/{assignment_id}/program-draft/save-as-template"


def _active_revision(client, headers, assignment_id) -> str:
    program = client.get(
        f"/coach/assignments/{assignment_id}/program", headers=headers
    ).json()["program"]
    return str(program["version"])


def _draft_revision(client, headers, assignment_id) -> str:
    return client.get(
        f"/coach/assignments/{assignment_id}/program-draft", headers=headers
    ).json()["updated_at"]


def _template_row(db, template_id):
    return db.catalog_conn.execute(
        "SELECT coach_account_id, program_json FROM program_templates WHERE template_id = ?",
        (template_id,),
    ).fetchone()


def _assert_no_sentinels(dumped: str) -> None:
    for sentinel in _SENTINELS:
        assert sentinel not in dumped, sentinel


# --------------------------------------------------------------------------
# Both sources
# --------------------------------------------------------------------------


@pytest.mark.parametrize("published_by", [None, "previous-coach"])
def test_saves_active_program_of_any_provenance(api, published_by):
    client, db, _ = api
    coach_headers, player_headers, assignment_id, coach_id, player_account_id = (
        _assigned_player(api)
    )
    previous_coach_id = None
    if published_by == "previous-coach":
        _make_coach(client, db, "previous-coach")
        previous_coach_id = db.get_active_account_by_username("previous-coach")[
            "account_id"
        ]
    _seed_active_program(
        db,
        player_account_id,
        published_by_coach_account_id=previous_coach_id,
    )
    active_before = client.get(
        f"/coach/assignments/{assignment_id}/program", headers=coach_headers
    ).json()["program"]

    saved = client.post(
        _active_path(assignment_id),
        headers=coach_headers,
        json={
            "name": "Reusable upper/lower",
            "description": "From a player's plan",
            "expected_source_revision": str(active_before["version"]),
            "notes": [
                {
                    "week_order": 1,
                    "day_order": 1,
                    "field": "exercise_notes",
                    "item_index": 0,
                    "value": "Cue written for a player.",
                }
            ],
        },
    )

    assert saved.status_code == 201, saved.text
    template = saved.json()
    program = template["program"]

    # The stored name is the coach's template name, never the player's.
    assert template["name"] == "Reusable upper/lower"
    assert program["program_name"] == "Reusable upper/lower"
    assert program["split_type"] == "Upper/Lower"
    assert len(program["weeks"]) == 1
    week = program["weeks"][0]
    assert [day["day_name"] for day in week["days"]] == ["Upper A", "Lower A"]

    # Prescriptions are copied; catalog metadata is re-derived, not copied.
    bench = week["days"][0]["exercises"][0]
    assert bench["exercise_id"] == "bp"
    assert bench["exercise_name"] == "Bench Press"
    assert bench["note"] is None
    assert bench["target_sets"] == 4
    assert bench["target_reps_min"] == 6
    assert bench["target_reps_max"] == 8
    assert bench["target_rir"] == pytest.approx(1.5)
    squat = week["days"][1]["exercises"][0]
    assert squat["exercise_id"] == "sq"

    # The reviewed note survived; every other note was dropped, never copied.
    assert bench["notes"] == "Cue written for a player."
    assert week["days"][0]["warmup_exercises"][0]["notes"] is None
    assert squat["notes"] is None

    # No provenance or server metadata is stored on the template.
    for metadata in ("version", "provenance", "active_since", "current_week", "week_count"):
        assert metadata not in program, metadata

    row = _template_row(db, template["template_id"])
    assert row is not None
    assert row[0] == coach_id
    stored = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    dumped = json.dumps(stored)
    _assert_no_sentinels(dumped)
    for identifier in ("p1", player_account_id, "provenance", "active_since", assignment_id):
        assert identifier not in dumped, identifier
    if previous_coach_id is not None:
        assert previous_coach_id not in dumped

    # The source active program is untouched.
    active_after = client.get(
        f"/coach/assignments/{assignment_id}/program", headers=coach_headers
    ).json()["program"]
    assert active_after["version"] == active_before["version"]
    assert active_after["weeks"][0]["days"][1]["exercises"][0]["notes"] == "ZZSQUAT p1's knee needs care."


def test_saves_open_program_draft(api):
    client, db, _ = api
    coach_headers, _, assignment_id, coach_id, _ = _assigned_player(api)
    created = client.post(
        f"/coach/assignments/{assignment_id}/program-draft",
        headers=coach_headers,
        json=_draft_body(),
    )
    assert created.status_code == 200, created.text

    saved = client.post(
        _draft_path(assignment_id),
        headers=coach_headers,
        json={
            "name": "From the draft",
            "expected_source_revision": created.json()["updated_at"],
            "notes": [
                {
                    "week_order": 1,
                    "day_order": 1,
                    "field": "exercise_notes",
                    "item_index": 0,
                    "value": "Keep this cue.",
                }
            ],
        },
    )

    assert saved.status_code == 201, saved.text
    template = saved.json()
    assert template["name"] == "From the draft"
    assert template["program"]["program_name"] == "From the draft"
    squat = template["program"]["weeks"][0]["days"][0]["exercises"][0]
    assert squat["exercise_id"] == "sq"
    assert squat["notes"] == "Keep this cue."
    assert _template_row(db, template["template_id"])[0] == coach_id
    row = _template_row(db, template["template_id"])
    stored = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    _assert_no_sentinels(json.dumps(stored))

    # The open draft still exists, unchanged.
    draft_after = client.get(
        f"/coach/assignments/{assignment_id}/program-draft", headers=coach_headers
    )
    assert draft_after.status_code == 200
    assert draft_after.json()["draft"]["days"][0]["exercises"][0]["notes"] == "ZZBENCHNOTES Keep this for p1."


@pytest.mark.parametrize("source", ["active", "draft"])
@pytest.mark.parametrize("decision", ["keep", "edit", "clear", "absent"])
def test_reviewed_instructions_and_cardio_are_preserved_only_by_decision(
    api, source, decision
):
    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    if source == "active":
        program = _program_with_player_notes().model_dump()
        program["instructions"] = "Progress steadily through the block."
        program["days"][0]["cardio"] = "Bike for ten minutes after lifting."
        player = db.get_account(player_account_id)
        with db.open_ledger(player["ledger_id"]) as ledger:
            ledger.save_training_program(
                program, published_by_coach_account_id=None
            )
        revision = _active_revision(client, coach_headers, assignment_id)
        endpoint = _active_path(assignment_id)
    else:
        program = _draft_body()
        program["instructions"] = "Progress steadily through the block."
        program["days"][0]["cardio"] = "Bike for ten minutes after lifting."
        created = client.post(
            f"/coach/assignments/{assignment_id}/program-draft",
            headers=coach_headers,
            json=program,
        )
        assert created.status_code == 200, created.text
        revision = created.json()["updated_at"]
        endpoint = _draft_path(assignment_id)

    decisions = []
    if decision != "absent":
        if decision == "keep":
            instruction_value = "Progress steadily through the block."
            cardio_value = "Bike for ten minutes after lifting."
        elif decision == "edit":
            instruction_value = "Coach-edited progression cue."
            cardio_value = "Cycle for twelve minutes after lifting."
        else:
            instruction_value = None
            cardio_value = None
        decisions = [
            {"field": "program_instructions", "value": instruction_value},
            {
                "week_order": 1,
                "day_order": 1,
                "field": "day_cardio",
                "value": cardio_value,
            },
        ]

    saved = client.post(
        endpoint,
        headers=coach_headers,
        json={
            "name": "Reviewed prescription",
            "expected_source_revision": revision,
            "notes": decisions,
        },
    )

    assert saved.status_code == 201, saved.text
    copied = saved.json()["program"]
    expected_instruction = {
        "keep": "Progress steadily through the block.",
        "edit": "Coach-edited progression cue.",
        "clear": "",
        "absent": "",
    }[decision]
    expected_cardio = {
        "keep": "Bike for ten minutes after lifting.",
        "edit": "Cycle for twelve minutes after lifting.",
        "clear": None,
        "absent": None,
    }[decision]
    assert copied["instructions"] == expected_instruction
    assert copied["days"][0]["cardio"] == expected_cardio


# --------------------------------------------------------------------------
# Source-revision binding
# --------------------------------------------------------------------------


def test_save_as_template_requires_the_reviewed_revision(api):
    client, db, _ = api
    coach_headers, _, assignment_id, coach_id, player_account_id = _assigned_player(api)
    _seed_active_program(db, player_account_id)

    response = client.post(
        _active_path(assignment_id), headers=coach_headers, json={"name": "No revision"}
    )

    assert response.status_code == 409, response.text
    assert "program.source_changed.v1" in response.text
    assert client.get("/coach/program-templates", headers=coach_headers).json()["templates"] == []


def test_save_as_template_refuses_a_stale_active_program(api):
    client, db, _ = api
    coach_headers, _, assignment_id, coach_id, player_account_id = _assigned_player(api)
    _seed_active_program(db, player_account_id)
    stale = _active_revision(client, coach_headers, assignment_id)
    # Another device republishes the active program between review and save.
    _seed_active_program(db, player_account_id)
    assert _active_revision(client, coach_headers, assignment_id) != stale

    response = client.post(
        _active_path(assignment_id),
        headers=coach_headers,
        json={"name": "Stale", "expected_source_revision": stale},
    )

    assert response.status_code == 409, response.text
    assert "program.source_changed.v1" in response.text
    assert client.get("/coach/program-templates", headers=coach_headers).json()["templates"] == []


def test_save_as_template_refuses_a_stale_draft(api):
    client, db, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)
    created = client.post(
        f"/coach/assignments/{assignment_id}/program-draft",
        headers=coach_headers,
        json=_draft_body(),
    )
    assert created.status_code == 200, created.text
    stale = created.json()["updated_at"]
    replaced = client.put(
        f"/coach/assignments/{assignment_id}/program-draft",
        headers=coach_headers,
        json=_draft_body(),
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["updated_at"] != stale

    response = client.post(
        _draft_path(assignment_id),
        headers=coach_headers,
        json={"name": "Stale", "expected_source_revision": stale},
    )

    assert response.status_code == 409, response.text
    assert "program.source_changed.v1" in response.text
    assert client.get("/coach/program-templates", headers=coach_headers).json()["templates"] == []


# --------------------------------------------------------------------------
# Foreign previous-coach exercise copy policy
# --------------------------------------------------------------------------


def test_saves_previous_coach_exercise_as_one_current_coach_copy(api):
    client, db, _ = api
    coach_headers, _, assignment_id, coach_id, player_account_id = _assigned_player(api)
    _make_coach(client, db, "previous-coach")
    previous_coach_id = db.get_active_account_by_username("previous-coach")["account_id"]
    foreign = db.create_coach_exercise(
        previous_coach_id,
        CoachExerciseCreate(
            name="Previous Coach Movement",
            body_part="chest",
            equipment="Dumbbell",
            note="Private note from previous coach",
            video_url="https://example.test/demo",
        ),
    )

    program = _program_with_player_notes().model_dump()
    program["days"][0]["exercises"] = [
        {
            "exercise_id": foreign["id"],
            "exercise_name": "Previous Coach Movement",
            "target_sets": 3,
            "target_reps_min": 5,
            "target_reps_max": 8,
            "target_rir": 2,
            "notes": "",
        },
        {
            "exercise_id": foreign["id"],
            "exercise_name": "Previous Coach Movement",
            "target_sets": 2,
            "target_reps_min": 8,
            "target_reps_max": 10,
            "target_rir": 2,
            "notes": "",
        },
    ]
    player = db.get_account(player_account_id)
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.save_training_program(
            program, published_by_coach_account_id=previous_coach_id
        )
    revision = _active_revision(client, coach_headers, assignment_id)

    response = client.post(
        _active_path(assignment_id),
        headers=coach_headers,
        json={"name": "Copied", "expected_source_revision": revision},
    )

    assert response.status_code == 201, response.text
    saved = response.json()
    copied = saved["program"]["days"][0]["exercises"]
    copied_ids = {exercise["exercise_id"] for exercise in copied[:2]}
    assert len(copied_ids) == 1
    copied_id = copied_ids.pop()
    assert copied_id != foreign["id"]
    assert copied_id.startswith("coach:")
    clone = db.get_coach_exercise(coach_id, copied_id)
    assert clone is not None
    assert clone["name"] == foreign["name"]
    assert clone["body_part"] == "chest"
    assert clone["equipment"] == "Dumbbell"
    assert clone["video_url"] == "https://example.test/demo"
    assert clone["note"] is None
    serialized = json.dumps(saved["program"])
    assert previous_coach_id not in serialized
    assert foreign["id"] not in serialized
    assert "Private note from previous coach" not in serialized
    assert db.get_coach_exercise(previous_coach_id, foreign["id"]) == foreign


@pytest.mark.parametrize("source_collection", ["exercise", "warmup_exercise"])
def test_open_draft_cannot_clone_foreign_exercise_without_player_history(
    api, source_collection
):
    client, db, _ = api
    coach_headers, _, assignment_id, coach_id, _ = _assigned_player(api)
    _make_coach(client, db, "unrelated-coach")
    previous_coach_id = db.get_active_account_by_username("unrelated-coach")[
        "account_id"
    ]
    foreign = db.create_coach_exercise(
        previous_coach_id,
        CoachExerciseCreate(
            name="Private unrelated movement",
            note="Definition that must not be disclosed",
        ),
    )
    draft = _draft_body()
    if source_collection == "exercise":
        draft["days"][0]["exercises"][0]["exercise_id"] = foreign["id"]
    else:
        draft["days"][0]["warmup_exercises"] = [
            {
                "exercise_id": foreign["id"],
                "exercise_name": "Untrusted client label",
                "sets": 2,
                "reps": 10,
                "rest_seconds": 30,
            }
        ]
    created = client.post(
        f"/coach/assignments/{assignment_id}/program-draft",
        headers=coach_headers,
        json=draft,
    )
    assert created.status_code == 200, created.text

    response = client.post(
        _draft_path(assignment_id),
        headers=coach_headers,
        json={
            "name": "Must not reveal foreign definition",
            "expected_source_revision": created.json()["updated_at"],
        },
    )

    assert response.status_code == 400, response.text
    assert "unknown_exercise" in {
        issue["code"] for issue in response.json()["detail"]["errors"]
    }
    assert foreign["name"] not in response.text
    assert foreign["note"] not in response.text
    assert db.get_coach_exercise(coach_id, foreign["id"]) is None
    assert client.get("/coach/program-templates", headers=coach_headers).json()[
        "templates"
    ] == []


def test_historical_foreign_exercise_in_open_draft_clones_once_for_exercise_and_warmup(
    api,
):
    client, db, _ = api
    coach_headers, _, assignment_id, coach_id, player_account_id = _assigned_player(api)
    _make_coach(client, db, "previous-coach")
    previous_coach_id = db.get_active_account_by_username("previous-coach")[
        "account_id"
    ]
    foreign = db.create_coach_exercise(
        previous_coach_id,
        CoachExerciseCreate(
            name="Historical Coach Movement",
            equipment="Cable",
            note="Private history note",
        ),
    )
    published = _program_with_player_notes().model_dump()
    published["days"][0]["exercises"][0]["exercise_id"] = foreign["id"]
    player = db.get_account(player_account_id)
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.save_training_program(
            published, published_by_coach_account_id=previous_coach_id
        )

    draft = _draft_body()
    draft["days"][0]["exercises"][0]["exercise_id"] = foreign["id"]
    draft["days"][0]["warmup_exercises"] = [
        {
            "exercise_id": foreign["id"],
            "exercise_name": "Stale label",
            "sets": 2,
            "reps": 10,
            "rest_seconds": 30,
        }
    ]
    created = client.post(
        f"/coach/assignments/{assignment_id}/program-draft",
        headers=coach_headers,
        json=draft,
    )
    assert created.status_code == 200, created.text
    response = client.post(
        _draft_path(assignment_id),
        headers=coach_headers,
        json={
            "name": "Visible historical copy",
            "expected_source_revision": created.json()["updated_at"],
        },
    )

    assert response.status_code == 201, response.text
    day = response.json()["program"]["days"][0]
    exercise_id = day["exercises"][0]["exercise_id"]
    warmup_id = day["warmup_exercises"][0]["exercise_id"]
    assert exercise_id == warmup_id
    assert exercise_id != foreign["id"]
    clone = db.get_coach_exercise(coach_id, exercise_id)
    assert clone is not None
    assert clone["name"] == "Historical Coach Movement"
    assert clone["equipment"] == "Cable"
    assert clone["note"] is None
    assert day["warmup_exercises"][0]["exercise_name"] == clone["name"]
    assert foreign["id"] not in json.dumps(response.json()["program"])


def test_invalid_source_does_not_leave_a_foreign_exercise_clone(api):
    client, db, _ = api
    coach_headers, _, assignment_id, coach_id, player_account_id = _assigned_player(api)
    _make_coach(client, db, "previous-coach")
    previous_coach_id = db.get_active_account_by_username("previous-coach")["account_id"]
    foreign = db.create_coach_exercise(
        previous_coach_id, CoachExerciseCreate(name="Previous Coach Movement")
    )
    program = _program_with_player_notes().model_dump()
    program["days"][0]["exercises"][0]["exercise_id"] = foreign["id"]
    program["days"][0]["exercises"].append(
        {
            "exercise_id": "coach:missing-source-exercise",
            "exercise_name": "Missing",
            "target_sets": 2,
            "target_reps_min": 8,
            "target_reps_max": 10,
            "target_rir": 2,
            "notes": "",
        }
    )
    player = db.get_account(player_account_id)
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.save_training_program(
            program, published_by_coach_account_id=previous_coach_id
        )

    response = client.post(
        _active_path(assignment_id),
        headers=coach_headers,
        json={
            "name": "Invalid copy",
            "expected_source_revision": _active_revision(
                client, coach_headers, assignment_id
            ),
        },
    )

    assert response.status_code == 400, response.text
    owned_exercises = db.catalog_conn.execute(
        "SELECT id FROM coach_exercises WHERE coach_account_id = ?", (coach_id,)
    ).fetchall()
    assert owned_exercises == []
    assert client.get("/coach/program-templates", headers=coach_headers).json()["templates"] == []


# --------------------------------------------------------------------------
# Authorization (ADR 025 gate)
# --------------------------------------------------------------------------


def test_save_as_template_denies_foreign_ended_and_unknown_assignments(api):
    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    _seed_active_program(db, player_account_id)
    other = _make_coach(client, db, "other-coach")

    foreign = client.post(
        _active_path(assignment_id), headers=other, json={"name": "Hijack"}
    )
    assert foreign.status_code == 403, foreign.text

    # Every denial is the one generic 403 for both sources.
    assert client.post(
        _draft_path(assignment_id), headers=other, json={"name": "Hijack"}
    ).status_code == 403
    assert client.post(
        _active_path("does-not-exist"), headers=coach_headers, json={"name": "Ghost"}
    ).status_code == 403
    assert client.post(
        _draft_path("does-not-exist"), headers=coach_headers, json={"name": "Ghost"}
    ).status_code == 403

    client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers)
    assert client.post(
        _active_path(assignment_id), headers=coach_headers, json={"name": "Ended"}
    ).status_code == 403
    assert client.post(
        _draft_path(assignment_id), headers=coach_headers, json={"name": "Ended"}
    ).status_code == 403

    # No template was created by any denied attempt.
    assert client.get("/coach/program-templates", headers=coach_headers).json()["templates"] == []
    assert client.get("/coach/program-templates", headers=other).json()["templates"] == []


def test_save_as_template_requires_a_source_program(api):
    client, db, _ = api
    coach_headers, _, assignment_id, _, _ = _assigned_player(api)

    no_active = client.post(
        _active_path(assignment_id), headers=coach_headers, json={"name": "Empty"}
    )
    assert no_active.status_code == 404, no_active.text

    no_draft = client.post(
        _draft_path(assignment_id), headers=coach_headers, json={"name": "Empty"}
    )
    assert no_draft.status_code == 404, no_draft.text


# --------------------------------------------------------------------------
# Request validation
# --------------------------------------------------------------------------


def test_save_as_template_rejects_unknown_note_location(api):
    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    _seed_active_program(db, player_account_id)
    revision = _active_revision(client, coach_headers, assignment_id)

    response = client.post(
        _active_path(assignment_id),
        headers=coach_headers,
        json={
            "name": "Bad note",
            "expected_source_revision": revision,
            "notes": [
                {
                    "week_order": 1,
                    "day_order": 1,
                    "field": "exercise_notes",
                    "item_index": 9,
                    "value": "Nowhere",
                }
            ],
        },
    )

    assert response.status_code == 400, response.text
    codes = {issue["code"] for issue in response.json()["detail"]["errors"]}
    assert "invalid_note_location" in codes
    assert client.get("/coach/program-templates", headers=coach_headers).json()["templates"] == []


def test_save_as_template_requires_a_non_blank_name(api):
    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    _seed_active_program(db, player_account_id)

    blank = client.post(
        _active_path(assignment_id), headers=coach_headers, json={"name": "   "}
    )
    assert blank.status_code == 422, blank.text


def test_save_as_template_rejects_unknown_payload_fields(api):
    client, db, _ = api
    coach_headers, _, assignment_id, _, player_account_id = _assigned_player(api)
    _seed_active_program(db, player_account_id)

    response = client.post(
        _active_path(assignment_id),
        headers=coach_headers,
        json={"name": "Nope", "player_id": "p1"},
    )
    assert response.status_code == 422, response.text


def test_save_as_template_requires_the_live_coach_capability(api):
    client, db, _ = api
    _, player_headers, assignment_id, _, _ = _assigned_player(api)
    assert client.post(
        _active_path(assignment_id), headers=player_headers, json={"name": "Nope"}
    ).status_code == 403
