import sqlite3
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import coach as coach_service
from svc.app import create_app
from svc.dependencies import get_db


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-0123456789abcdef")
    from svc.rate_limit import limiter

    limiter._storage.reset()
    catalog_path = tmp_path / "catalog.db"
    catalog = sqlite3.connect(catalog_path)
    catalog.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT)"
    )
    catalog.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT)")
    catalog.execute(
        "INSERT INTO exercises (id, name, body_part, target_muscle, equipment)"
        " VALUES ('sq', 'Squat', 'Upper Legs', 'Quads', 'barbell')"
    )
    catalog.commit()
    catalog.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(client, username):
    response = client.post(
        "/auth/register", json={"trainee_id": username, "password": "correct-horse-1"}
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _make_coach(client, db, username):
    headers = _register(client, username)
    issued = coach_service.issue_coach_invite(db, username, actor="cli")
    assert issued["ok"]
    assert client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code == 200
    assert client.put(
        "/coach/profile",
        headers=headers,
        json={"display_name": username, "bio": "", "specialization": "", "capacity": 5},
    ).status_code == 200
    return headers


def _assign(client, coach_headers, player_headers):
    invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert invite.status_code == 200, invite.text
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite.json()["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    return redeemed.json()["assignment"]["assignment_id"]


def _create_exercise(client, headers, name="Pin Squat"):
    response = client.post(
        "/coach/exercises",
        headers=headers,
        json={
            "name": name,
            "body_part": "Quads",
            "equipment": "Barbell",
            "note": "Pause on the pins.",
            "video_url": "https://example.com/pin-squat",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _one_exercise_draft(exercise_id):
    return {
        "program_name": "Pin Squat plan",
        "split_type": "custom",
        "weekly_frequency": 1,
        "days": [
            {
                "day_name": "Day 1",
                "day_order": 1,
                "exercises": [
                    {
                        "exercise_id": exercise_id,
                        "target_sets": 2,
                        "target_reps_min": 5,
                        "target_reps_max": 8,
                        "target_rir": 2,
                    }
                ],
            }
        ],
    }


def test_create_and_search_are_https_only_and_isolated_to_owner(api):
    client, _ = api
    first_coach = _make_coach(client, api[1], "first-coach")
    second_coach = _make_coach(client, api[1], "second-coach")

    rejected = client.post(
        "/coach/exercises",
        headers=first_coach,
        json={"name": "Unsafe link", "video_url": "http://example.com/video"},
    )
    assert rejected.status_code == 422

    created = _create_exercise(client, first_coach)
    assert created["id"].startswith("coach:")
    assert created["image_path"] is None and created["gif_path"] is None
    assert created["video_url"] == "https://example.com/pin-squat"

    first_results = client.get("/coach/exercises", headers=first_coach, params={"query": "pin squat"})
    assert first_results.status_code == 200, first_results.text
    assert [row["id"] for row in first_results.json()["exercises"]] == [created["id"]]
    assert first_results.json()["exercises"][0]["is_coach_exercise"] is True

    alongside_library = client.get("/coach/exercises", headers=first_coach, params={"query": "squat"})
    assert {row["id"] for row in alongside_library.json()["exercises"]} == {"sq", created["id"]}
    player_search = client.get("/workouts/exercises", headers=first_coach, params={"query": "pin squat"})
    assert created["id"] not in {row["id"] for row in player_search.json()["exercises"]}

    second_results = client.get("/coach/exercises", headers=second_coach, params={"query": "pin squat"})
    assert second_results.status_code == 200, second_results.text
    assert second_results.json()["exercises"] == []


@pytest.mark.parametrize(
    "video_url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "http://example.com/video",
    ],
)
def test_create_rejects_non_https_video_schemes(api, video_url):
    client, db = api
    coach_headers = _make_coach(client, db, "unsafe-video-coach")

    response = client.post(
        "/coach/exercises",
        headers=coach_headers,
        json={"name": "Unsafe link", "video_url": video_url},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "fields",
    [
        {"name": "x" * 121},
        {"name": "Pin Squat", "note": "n" * 1001},
        {"name": "Pin Squat", "video_url": "https://example.com/" + "v" * 2040},
    ],
)
def test_create_rejects_overlong_name_note_and_video_link(api, fields):
    client, db = api
    coach_headers = _make_coach(client, db, "long-field-coach")

    response = client.post("/coach/exercises", headers=coach_headers, json=fields)

    assert response.status_code == 422


def test_coach_exercise_search_escapes_like_wildcards(api):
    client, db = api
    coach_headers = _make_coach(client, db, "wildcard-search-coach")
    percent = _create_exercise(client, coach_headers, "Pin 100% Squat")
    underscore = _create_exercise(client, coach_headers, "Pin_Squat")
    ordinary = _create_exercise(client, coach_headers, "Pin Press")

    percent_results = client.get(
        "/coach/exercises", headers=coach_headers, params={"query": "%"}
    ).json()["exercises"]
    underscore_results = client.get(
        "/coach/exercises", headers=coach_headers, params={"query": "_"}
    ).json()["exercises"]

    assert percent["id"] in {row["id"] for row in percent_results}
    assert ordinary["id"] not in {row["id"] for row in percent_results}
    assert underscore["id"] in {row["id"] for row in underscore_results}
    assert ordinary["id"] not in {row["id"] for row in underscore_results}


def test_owner_can_publish_player_can_log_and_keep_coach_exercise_prs(api):
    client, db = api
    coach_headers = _make_coach(client, db, "program-coach")
    player_headers = _register(client, "program-player")
    assignment_id = _assign(client, coach_headers, player_headers)
    exercise = _create_exercise(client, coach_headers)

    draft_path = f"/coach/assignments/{assignment_id}/program-draft"
    assert client.post(draft_path, headers=coach_headers, json=_one_exercise_draft(exercise["id"])).status_code == 200
    published = client.post(f"{draft_path}/publish", headers=coach_headers)
    assert published.status_code == 200, published.text

    program = client.get("/programs/active", headers=player_headers).json()
    prescribed = program["days"][0]["exercises"][0]
    assert prescribed["exercise_id"] == exercise["id"]
    assert prescribed["exercise_name"] == "Pin Squat"
    assert prescribed["note"] == "Pause on the pins."
    assert prescribed["video_url"] == "https://example.com/pin-squat"
    assert prescribed["image_path"] is None and prescribed["gif_path"] is None

    payload = {
        "day_order": 1,
        "readiness": 4,
        "session_notes": "",
        "sets": [
            {
                "exercise": prescribed,
                "sets": [{"weight_kg": 60.0, "reps": 5, "rpe": 8.0}],
            }
        ],
    }
    baseline = client.post("/workouts/sessions", headers=player_headers, json=payload)
    assert baseline.status_code == 201, baseline.text
    assert baseline.json()["new_prs"] == []
    payload["sets"][0]["sets"][0]["weight_kg"] = 62.5
    record = client.post("/workouts/sessions", headers=player_headers, json=payload)
    assert record.status_code == 201, record.text
    assert {event["record_type"] for event in record.json()["new_prs"]} == {"max_weight", "max_e1rm"}
    assert all(event["name"] == "Pin Squat" for event in record.json()["new_prs"])
    assert "Pin Squat" in baseline.json()["debrief"]

    unknown_version = {
        **payload,
        "client_session_id": str(uuid.uuid4()),
        "performed_date": date.today().isoformat(),
        "performed_timezone": "UTC",
        "program_version": 999,
        "captured_at": "2026-10-04T08:00:00+00:00",
    }
    refused_version = client.post(
        "/workouts/sessions", headers=player_headers, json=unknown_version
    )
    assert refused_version.status_code == 409
    assert refused_version.json() == {"error": "program_version_mismatch", "active_version": 1}

    exported = client.get("/workouts/sessions/export.json", headers=player_headers)
    assert exported.status_code == 200, exported.text
    assert all(
        exercise_row["exercise_name"] == "Pin Squat"
        for session in exported.json()["sessions"]
        for exercise_row in session["exercises"]
        if exercise_row["exercise_id"] == exercise["id"]
    )
    with db.open_ledger("program-player") as ledger:
        assert ledger.get_latest_session_summary()["exercises"][0]["name"] == "Pin Squat"
        assert ledger.get_session_comparison_context()["exercises"][0]["name"] == "Pin Squat"
        assert "Top: Pin Squat" in ledger.get_compact_telemetry()

    history = client.get("/dashboard/exercises", headers=player_headers)
    assert any(row["id"] == exercise["id"] and row["name"] == "Pin Squat" for row in history.json())

    ended = client.post("/assignments/me/end", headers=player_headers)
    assert ended.status_code == 200, ended.text
    retained_program = client.get("/programs/active", headers=player_headers).json()
    assert retained_program["days"][0]["exercises"][0]["exercise_name"] == "Pin Squat"
    retained_history = client.get(
        f"/dashboard/exercises/{exercise['id']}/history", headers=player_headers
    ).json()
    assert retained_history["history"]
    personal_records = client.get("/dashboard/personal-records", headers=player_headers).json()
    assert any(row["exercise_id"] == exercise["id"] and row["name"] == "Pin Squat" for row in personal_records)


def test_another_coach_cannot_publish_foreign_coach_exercise(api):
    client, db = api
    owner_headers = _make_coach(client, db, "owner-coach")
    foreign_headers = _make_coach(client, db, "foreign-coach")
    player_headers = _register(client, "foreign-player")
    assignment_id = _assign(client, foreign_headers, player_headers)
    exercise = _create_exercise(client, owner_headers)

    draft_path = f"/coach/assignments/{assignment_id}/program-draft"
    assert client.post(draft_path, headers=foreign_headers, json=_one_exercise_draft(exercise["id"])).status_code == 200
    published = client.post(f"{draft_path}/publish", headers=foreign_headers)

    assert published.status_code == 400
    assert published.json()["detail"]["errors"][0]["code"] == "unknown_exercise"


def test_new_coach_can_reuse_exercise_already_in_player_program_history(api):
    client, db = api
    previous_coach = _make_coach(client, db, "previous-coach")
    new_coach = _make_coach(client, db, "new-coach")
    player_headers = _register(client, "handover-player")
    previous_assignment = _assign(client, previous_coach, player_headers)
    exercise = _create_exercise(client, previous_coach, "Previous Coach Pin Squat")
    previous_draft = f"/coach/assignments/{previous_assignment}/program-draft"
    assert client.post(
        previous_draft,
        headers=previous_coach,
        json=_one_exercise_draft(exercise["id"]),
    ).status_code == 200
    assert client.post(f"{previous_draft}/publish", headers=previous_coach).status_code == 200
    assert client.post("/assignments/me/end", headers=player_headers).status_code == 200

    new_assignment = _assign(client, new_coach, player_headers)
    new_draft = f"/coach/assignments/{new_assignment}/program-draft"
    assert client.post(
        new_draft,
        headers=new_coach,
        json=_one_exercise_draft(exercise["id"]),
    ).status_code == 200

    published = client.post(f"{new_draft}/publish", headers=new_coach)

    assert published.status_code == 200, published.text
    assert client.get("/programs/active", headers=player_headers).json()["days"][0]["exercises"][0]["exercise_name"] == exercise["name"]


def test_deleted_coach_keeps_exercise_identity_and_clears_authored_text(api):
    client, db = api
    coach_headers = _make_coach(client, db, "deleted-exercise-coach")
    player_headers = _register(client, "deleted-coach-player")
    assignment_id = _assign(client, coach_headers, player_headers)
    exercise = _create_exercise(client, coach_headers)
    draft_path = f"/coach/assignments/{assignment_id}/program-draft"
    assert client.post(
        draft_path,
        headers=coach_headers,
        json=_one_exercise_draft(exercise["id"]),
    ).status_code == 200
    assert client.post(f"{draft_path}/publish", headers=coach_headers).status_code == 200
    prescribed = client.get("/programs/active", headers=player_headers).json()["days"][0]["exercises"][0]
    logged = client.post(
        "/workouts/sessions",
        headers=player_headers,
        json={
            "day_order": 1,
            "readiness": 4,
            "sets": [{"exercise": prescribed, "sets": [{"weight_kg": 50, "reps": 5}]}],
        },
    )
    assert logged.status_code == 201, logged.text

    deleted = client.request(
        "DELETE",
        "/auth/account",
        headers=coach_headers,
        json={"password": "correct-horse-1"},
    )

    assert deleted.status_code == 200, deleted.text
    retained = db.get_coach_exercise_unscoped(exercise["id"])
    assert retained["name"] == "Pin Squat"
    assert retained["body_part"] == "Quads"
    assert retained["equipment"] == "Barbell"
    assert retained["note"] is None and retained["video_url"] is None
    program = client.get("/programs/active", headers=player_headers).json()
    historical = program["days"][0]["exercises"][0]
    assert historical["exercise_name"] == "Pin Squat"
    assert historical["note"] is None and historical["video_url"] is None
    assert any(
        row["id"] == exercise["id"] and row["name"] == "Pin Squat"
        for row in client.get("/dashboard/exercises", headers=player_headers).json()
    )
    exported = client.get("/workouts/sessions/export.json", headers=player_headers).json()
    assert exported["sessions"][0]["exercises"][0]["exercise_name"] == "Pin Squat"


def test_coach_exercise_cannot_be_a_substitution(api):
    client, db = api
    coach_headers = _make_coach(client, db, "substitution-coach")
    player_headers = _register(client, "substitution-player")
    assignment_id = _assign(client, coach_headers, player_headers)
    exercise = _create_exercise(client, coach_headers, "Unlisted Cable Press")

    draft_path = f"/coach/assignments/{assignment_id}/program-draft"
    assert client.post(draft_path, headers=coach_headers, json=_one_exercise_draft("sq")).status_code == 200
    assert client.post(f"{draft_path}/publish", headers=coach_headers).status_code == 200
    assert client.post("/assignments/me/end", headers=player_headers).status_code == 200

    search = client.get(
        "/workouts/exercises", headers=player_headers, params={"query": "Unlisted Cable Press"}
    )
    assert search.status_code == 200, search.text
    assert search.json()["exercises"] == []

    substitute = client.post(
        "/programs/active/substitutions",
        headers=player_headers,
        json={
            "day_name": "Day 1",
            "exercise_id": "sq",
            "replacement_exercise_id": exercise["id"],
            "expected_active_version": 1,
        },
    )
    assert substitute.status_code == 404
    assert substitute.json()["code"] == "replacement_not_found"


def test_generated_programs_never_use_coach_exercises(fresh_store):
    from agent.program_generator import generate_program_pipeline
    from database.registry.coach_exercises import CoachExerciseCreate

    db = fresh_store
    custom = db.create_coach_exercise(
        "generator-coach",
        CoachExerciseCreate("Barbell Bench Press", body_part="Chest", equipment="Barbell"),
    )
    db.switch_user("coach-exercise-generator")
    db.ledger.upsert_player_profile(
        {
            "gender": "male",
            "proportions": "balanced",
            "age": 28,
            "weight_kg": 80.0,
            "height_cm": 175.0,
            "rep_preference": "balanced",
            "current_goal": "hypertrophy",
            "long_term_goal": "progressive overload",
            "weekly_frequency": 3,
            "training_age_years": 3.0,
            "equipment_access": "Commercial gym",
            "injuries_or_limitations": "None",
            "stress_and_sleep": "normal",
        }
    )
    generated, _ = generate_program_pipeline(ledger=db.ledger)
    generated_ids = {
        exercise.exercise_id
        for day in generated.days
        for exercise in day.exercises
    }
    assert custom["id"] not in generated_ids


def test_progression_signals_include_coach_exercise_name(api):
    from agent.progression_engine import get_progression_signals
    from database.registry.coach_exercises import CoachExerciseCreate

    _, db = api
    exercise = db.create_coach_exercise(
        "progression-coach",
        CoachExerciseCreate("Pin Squat", body_part="Quads", equipment="Barbell"),
    )
    db.switch_user("progression-player")
    ledger = db.ledger
    for days_ago in (3, 2, 1):
        session_date = (date.today() - timedelta(days=days_ago)).isoformat()
        session_id = str(uuid.uuid4())
        started_at = f"{session_date}T12:00:00+00:00"
        ledger.log_workout_session(
            session_id=session_id,
            session_date=session_date,
            split_name="Lower A",
            started_at=started_at,
            completed_at=started_at,
        )
        ledger.log_workout_set(
            set_id=str(uuid.uuid4()),
            session_id=session_id,
            exercise_id=exercise["id"],
            set_index=1,
            weight_kg=50,
            reps=5,
            rpe=8,
        )

    signals = get_progression_signals(ledger)

    assert "Pin Squat: Stalled" in signals
