"""Read-only exercise library detail contract tests (ticket #53).

The exercise-detail screen is backed by `GET /workouts/exercises/{exercise_id}`:
an authenticated, read-only endpoint that returns the real catalog fields
(name, category == body_part, equipment, primary + secondary muscles,
instructions, and the stored media paths) without bundling or serving media.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from svc.app import create_app
from svc.dependencies import get_db
from utils.equipment_access import BODYWEIGHT_ONLY, COMMERCIAL_GYM, HOME_GYM

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
        "INSERT INTO exercises (id, name, body_part, target_muscle, equipment, instructions, image_path, gif_path)"
        " VALUES ('bp', 'Bench Press', 'Chest', 'Chest', 'barbell',"
        " 'Lie on a bench and press the bar up.', 'images/bp.jpg', 'videos/bp.gif');"
    )
    cat_conn.execute(
        "INSERT INTO exercise_secondary_muscles (exercise_id, muscle) VALUES ('bp', 'triceps'), ('bp', 'shoulders');"
    )
    # More muscles so the Replace search's pre-filter (#162) can be exercised.
    cat_conn.execute(
        "INSERT INTO exercises (id, name, body_part, target_muscle, equipment, instructions, image_path, gif_path)"
        " VALUES ('ib', 'Incline Bench Press', 'Chest', 'Chest', 'barbell', '', 'images/ib.jpg', NULL),"
        " ('sq', 'Back Squat', 'Upper Legs', 'Quads', 'barbell', '', 'images/sq.jpg', NULL),"
        " ('lp', 'Leg Press', 'Upper Legs', 'Quads', 'leverage machine', '', 'images/lp.jpg', NULL),"
        " ('op', 'Overhead Press', 'Shoulders', 'Shoulders', 'barbell', '', 'images/op.jpg', NULL);"
    )
    cat_conn.executemany(
        "INSERT INTO exercises (id, name, body_part, target_muscle, equipment, instructions) "
        "VALUES (?, ?, ?, ?, ?, '')",
        [
            ("raw-cable", "cable row", "Back", "lats", "cable"),
            ("raw-situp", "3/4 sit-up", "Abs", "abs", "body weight"),
            ("raw-shrug", "lever gripless shrug v. 2", "Back", "traps", "cable"),
            ("raw-parenthetical", "cable seated shrug (male)", "Back", "traps", "cable"),
            ("mayos:1", "Kelso shrug", "Back", "traps", "cable"),
        ],
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
            yield client, db
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


def test_exercise_detail_returns_real_catalog_fields(api):
    client, _ = api
    token = _register(client, "player")["access_token"]
    resp = client.get("/workouts/exercises/bp", headers=_authed(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "id": "bp",
        "name": "Bench Press",
        "category": "Chest",
        "body_part": "Chest",
        "equipment": "barbell",
        "equipment_category": "Free weight",
        "load_type": None,
        "primary_muscles": ["Chest"],
        "primary_muscle": None,
        "primary_action": None,
        "secondary_actions": [],
        "secondary_muscles": ["shoulders", "triceps"],
        "instructions": "Lie on a bench and press the bar up.",
        "image_path": "images/bp.jpg",
        "gif_path": "videos/bp.gif",
        "provenance": "ExerciseDB",
    }


def test_unreviewed_exercises_use_title_case_names_in_search_and_detail(api):
    client, _ = api
    token = _register(client, "unreviewed")["access_token"]

    expected_names = (
        ("raw-cable", "cable row", "Cable Row"),
        ("raw-situp", "3/4 sit-up", "3/4 Sit-Up"),
        ("raw-shrug", "lever gripless shrug v. 2", "Lever Gripless Shrug V. 2"),
        ("raw-parenthetical", "cable seated shrug (male)", "Cable Seated Shrug (Male)"),
    )
    for exercise_id, source_name, display_name in expected_names:
        search = client.get(
            "/workouts/exercises",
            headers=_authed(token),
            params={"query": source_name},
        )
        assert search.status_code == 200, search.text
        match = next(
            exercise
            for exercise in search.json()["exercises"]
            if exercise["id"] == exercise_id
        )
        assert match["name"] == display_name
        assert match["primary_muscle"] is None
        assert match["primary_action"] is None
        assert match["secondary_actions"] == []

        detail = client.get(f"/workouts/exercises/{exercise_id}", headers=_authed(token))
        assert detail.status_code == 200, detail.text
        assert detail.json()["name"] == display_name


def test_exercise_detail_unknown_id_is_404(api):
    client, _ = api
    token = _register(client, "player2")["access_token"]
    resp = client.get("/workouts/exercises/nope", headers=_authed(token))
    assert resp.status_code == 404


def test_hidden_duplicate_stays_readable_by_id_but_is_absent_from_search_and_program(
    api, seed_exercise_curation
):
    client, db = api
    token = _register(client, "hidden-duplicate-player")["access_token"]
    seed_exercise_curation(
        db,
        {
            "bp": {"hidden": True, "duplicate_of": "ib", "aliases": ["hidden bench alias"]},
            "ib": {"display_name": "Incline Bench Press"},
        },
    )

    for query in ("Bench Press", "hidden bench alias"):
        response = client.get(
            "/workouts/exercises", headers=_authed(token), params={"query": query}
        )
        assert response.status_code == 200, response.text
        assert "bp" not in {exercise["id"] for exercise in response.json()["exercises"]}

    browse = client.get(
        "/workouts/exercises",
        headers=_authed(token),
        params={"target_muscle": "Chest"},
    )
    assert browse.status_code == 200, browse.text
    assert "bp" not in {exercise["id"] for exercise in browse.json()["exercises"]}

    detail = client.get("/workouts/exercises/bp", headers=_authed(token))
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == "bp"
    assert detail.json()["name"] == "Incline Bench Press"

    db.switch_user("hidden-duplicate-player")
    db.ledger.save_training_program(
        {
            "program_name": "Existing program",
            "weekly_frequency": 1,
            "split_type": "custom",
            "days": [
                {
                    "day_name": "Day 1",
                    "day_order": 1,
                    "exercises": [{"exercise_id": "bp", "exercise_name": "Bench Press"}],
                }
            ],
        }
    )
    program = client.get("/programs/active", headers=_authed(token))
    assert program.status_code == 200, program.text
    assert program.json()["days"][0]["exercises"][0]["exercise_name"] == "Incline Bench Press"


def test_exercise_detail_requires_auth(api):
    client, _ = api
    resp = client.get("/workouts/exercises/bp")
    assert resp.status_code == 401


def test_catalog_search_returns_the_image_path_for_added_exercise_pictures(api):
    """`GET /workouts/exercises?query=` carries `image_path` so an exercise
    added from this search gets its card's catalog picture like a planned one
    (#53/#161): the client builds the public `/media` URL from it."""
    client, _ = api
    token = _register(client, "searcher")["access_token"]

    resp = client.get("/workouts/exercises", headers=_authed(token), params={"query": "bench"})
    assert resp.status_code == 200, resp.text
    matches = resp.json()["exercises"]
    assert matches, "expected the fixture's Bench Press"
    assert matches[0]["id"] == "bp"
    assert matches[0]["image_path"] == "images/bp.jpg"
    assert matches[0]["equipment"] == "barbell"
    # The client's own thumbnail URL builder is fed from this field alone.
    assert matches[0]["image_path"].startswith("images/")


def test_catalog_search_by_muscle_lists_that_muscle_without_a_name_query(api):
    """`GET /workouts/exercises?target_muscle=` lists one muscle's exercises
    (#162): the logger's Replace search opens pre-filtered before the player
    types, and every row still carries the fields the client renders."""
    client, _ = api
    token = _register(client, "muscle")["access_token"]

    resp = client.get(
        "/workouts/exercises", headers=_authed(token), params={"target_muscle": "Chest"}
    )
    assert resp.status_code == 200, resp.text
    matches = resp.json()["exercises"]
    assert [m["id"] for m in matches] == ["bp", "ib"]
    assert matches[0]["target_muscle"] == "Chest"
    assert matches[0]["image_path"] == "images/bp.jpg"

    # The match is case-insensitive, like the rest of the catalog's text.
    resp = client.get(
        "/workouts/exercises", headers=_authed(token), params={"target_muscle": "quads"}
    )
    assert resp.status_code == 200, resp.text
    assert [m["id"] for m in resp.json()["exercises"]] == ["sq", "lp"]


def test_catalog_search_filters_by_primary_muscles_with_or_and_name(api, seed_exercise_curation):
    client, db = api
    token = _register(client, "primary-muscle-filter")['access_token']
    seed_exercise_curation(
        db,
        {
            "bp": {"primary_muscle": "Chest"},
            "ib": {"primary_muscle": "Upper Chest"},
            "sq": {"primary_muscle": "Quads"},
            "lp": {"primary_muscle": "Quads"},
        },
    )

    browsed = client.get(
        "/workouts/exercises",
        headers=_authed(token),
        params=[("primary_muscle", "Chest"), ("primary_muscle", "Quads")],
    )
    assert browsed.status_code == 200, browsed.text
    assert {row["id"] for row in browsed.json()["exercises"]} == {"bp", "sq", "lp"}
    assert {row["primary_muscle"] for row in browsed.json()["exercises"]} == {
        "Chest",
        "Quads",
    }

    queried = client.get(
        "/workouts/exercises",
        headers=_authed(token),
        params={"query": "press", "primary_muscle": "Upper Chest"},
    )
    assert queried.status_code == 200, queried.text
    assert [row["id"] for row in queried.json()["exercises"]] == ["ib"]
    assert queried.json()["exercises"][0]["primary_muscle"] == "Upper Chest"

    combined = client.get(
        "/workouts/exercises",
        headers=_authed(token),
        params={"target_muscle": "Quads", "primary_muscle": "Chest"},
    )
    assert combined.status_code == 200, combined.text
    assert combined.json()["exercises"] == []

    detail = client.get("/workouts/exercises/bp", headers=_authed(token))
    assert detail.json()["primary_muscle"] == "Chest"
    uncurated = client.get("/workouts/exercises/raw-cable", headers=_authed(token))
    assert uncurated.json()["primary_muscle"] is None


def test_catalog_search_rejects_unknown_primary_muscle(api):
    client, _ = api
    token = _register(client, "unknown-primary-muscle")['access_token']

    response = client.get(
        "/workouts/exercises",
        headers=_authed(token),
        params={"primary_muscle": "Middle Back"},
    )

    assert response.status_code == 422


def test_catalog_search_filters_by_primary_action_and_returns_actions(
    api, seed_exercise_curation
):
    client, db = api
    token = _register(client, "primary-action-filter")["access_token"]
    seed_exercise_curation(
        db,
        {
            "bp": {
                "primary_action": "Shoulder Horizontal Adduction",
                "secondary_actions": ["Shoulder Flexion"],
                "primary_muscle": "Chest",
            },
            "ib": {
                "primary_action": "Shoulder Flexion",
                "secondary_actions": ["Elbow Extension"],
                "primary_muscle": "Upper Chest",
            },
            "sq": {
                "primary_action": "Knee Extension",
                "secondary_actions": ["Hip Extension"],
                "primary_muscle": "Quads",
            },
        },
    )
    action = client.get(
        "/workouts/exercises", headers=_authed(token),
        params={"primary_action": "Shoulder Flexion"},
    )
    assert action.status_code == 200, action.text
    assert [row["id"] for row in action.json()["exercises"]] == ["ib"]
    assert action.json()["exercises"][0]["primary_action"] == "Shoulder Flexion"
    assert action.json()["exercises"][0]["secondary_actions"] == ["Elbow Extension"]

    multiple = client.get(
        "/workouts/exercises", headers=_authed(token),
        params=[("primary_action", "Shoulder Flexion"), ("primary_action", "Knee Extension")],
    )
    assert {row["id"] for row in multiple.json()["exercises"]} == {"ib", "sq"}
    combined = client.get(
        "/workouts/exercises", headers=_authed(token),
        params={"primary_action": "Shoulder Flexion", "primary_muscle": "Upper Chest"},
    )
    assert [row["id"] for row in combined.json()["exercises"]] == ["ib"]
    queried = client.get(
        "/workouts/exercises", headers=_authed(token),
        params={"query": "incline", "primary_action": "Shoulder Flexion"},
    )
    assert [row["id"] for row in queried.json()["exercises"]] == ["ib"]
    detail = client.get("/workouts/exercises/bp", headers=_authed(token))
    assert detail.json()["primary_action"] == "Shoulder Horizontal Adduction"
    assert detail.json()["secondary_actions"] == ["Shoulder Flexion"]


def test_catalog_search_rejects_unknown_primary_action(api):
    client, _ = api
    token = _register(client, "unknown-primary-action")["access_token"]
    response = client.get(
        "/workouts/exercises", headers=_authed(token),
        params={"primary_action": "Knee Curl"},
    )
    assert response.status_code == 422


def test_catalog_search_filters_by_equipment_category_and_load_type(api, seed_exercise_curation):
    client, db = api
    token = _register(client, "equipment-filters")["access_token"]
    seed_exercise_curation(db, {"lp": {"primary_muscle": "Quads", "load_type": "selectorized"}})

    category = client.get(
        "/workouts/exercises", headers=_authed(token),
        params=[("equipment_category", "Free weight"), ("equipment_category", "Machine")],
    )
    assert category.status_code == 200, category.text
    category_rows = category.json()["exercises"]
    assert {row["equipment_category"] for row in category_rows} <= {"Free weight", "Machine"}
    assert "lp" in {row["id"] for row in category_rows}
    assert next(row for row in category_rows if row["id"] == "lp")["equipment_category"] == "Machine"

    load_type = client.get(
        "/workouts/exercises", headers=_authed(token), params={"load_type": "selectorized"}
    )
    assert load_type.status_code == 200, load_type.text
    assert [row["id"] for row in load_type.json()["exercises"]] == ["lp"]
    assert load_type.json()["exercises"][0]["load_type"] == "selectorized"
    combined = client.get(
        "/workouts/exercises", headers=_authed(token),
        params={
            "query": "press", "target_muscle": "Quads", "primary_muscle": "Quads",
            "equipment_category": "Machine", "load_type": "selectorized",
        },
    )
    assert combined.status_code == 200, combined.text
    assert [row["id"] for row in combined.json()["exercises"]] == ["lp"]
    detail = client.get("/workouts/exercises/lp", headers=_authed(token))
    assert detail.status_code == 200, detail.text
    assert detail.json()["equipment_category"] == "Machine"
    assert detail.json()["load_type"] == "selectorized"


@pytest.mark.parametrize(
    "params", [{"equipment_category": "Garage"}, {"load_type": "hydraulic"}]
)
def test_catalog_search_rejects_unknown_equipment_filters(api, params):
    client, _ = api
    token = _register(client, "unknown-equipment-filter")["access_token"]
    response = client.get("/workouts/exercises", headers=_authed(token), params=params)
    assert response.status_code == 422


def test_replace_browse_with_load_type_keeps_equipment_access_filter(api, seed_exercise_curation):
    client, db = api
    token = _register(client, "load-filter-bodyweight-only")["access_token"]
    seed_exercise_curation(db, {"lp": {"primary_muscle": "Quads", "load_type": "plate_loaded"}})
    with db.open_ledger("load-filter-bodyweight-only") as ledger:
        ledger.upsert_player_profile({"equipment_access": BODYWEIGHT_ONLY})
    response = client.get(
        "/workouts/exercises", headers=_authed(token), params={"load_type": "plate_loaded"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["exercises"] == []


@pytest.mark.parametrize(
    ("equipment", "expected"),
    [
        ("barbell", "Free weight"), ("dumbbell", "Free weight"),
        ("EZ barbell", "Free weight"), ("kettlebell", "Free weight"),
        ("trap bar", "Free weight"), ("Olympic barbell", "Free weight"),
        ("leverage machine", "Machine"), ("sled machine", "Machine"),
        ("smith machine", "Machine"), ("cable", "Cable"),
        ("body weight", "Bodyweight"), ("assisted", "Bodyweight"),
        ("weighted", "Bodyweight"), ("band", "Band"),
        ("resistance band", "Band"), ("stability ball", "Other"),
        ("medicine ball", "Other"), ("rope", "Other"), ("roller", "Other"),
        ("bosu ball", "Other"), ("wheel roller", "Other"),
        ("upper body ergometer", "Other"), ("tire", "Other"),
        ("stepmill machine", "Other"), ("stationary bike", "Other"),
        ("skierg machine", "Other"), ("hammer", "Other"),
        ("elliptical machine", "Other"),
    ],
)
def test_equipment_category_mapping_covers_source_equipment(equipment, expected):
    from database.exercise_library.vocabulary import equipment_category_for
    assert equipment_category_for(equipment) == expected
    assert equipment_category_for(equipment.upper()) == expected


@pytest.mark.parametrize("equipment", ["", None, "unknown equipment"])
def test_equipment_category_unknown_values_are_other(equipment):
    from database.exercise_library.vocabulary import equipment_category_for
    assert equipment_category_for(equipment) == "Other"


def test_replace_browse_ranks_display_named_exercises_and_returns_every_match(api):
    """Replace's muscle browse puts exercises with Exercise display names first and does not
    truncate the Exercise library at the old page size (#226)."""
    client, db = api
    token = _register(client, "lat-browse")["access_token"]
    rows = [
        ("2330", "cable lat pulldown full range of motion", "cable"),
        ("150", "cable lateral pulldown", "cable"),
    ] + [
        (f"lat-{index}", f"Long Name {index:02d} for Lats Exercise", "cable")
        for index in range(30)
    ]
    db.catalog_conn.executemany(
        "INSERT INTO exercises (id, name, body_part, target_muscle, equipment) "
        "VALUES (?, ?, 'Back', 'lats', ?)",
        rows,
    )
    db.catalog_conn.executemany(
        "INSERT INTO exercise_display_names (exercise_id, display_name, is_reviewed) "
        "VALUES (?, ?, 1)",
        [("2330", "Standing Cable Pulldown (Cable)"), ("150", "Lat Pulldown")],
    )
    db.catalog_conn.commit()

    resp = client.get(
        "/workouts/exercises",
        headers=_authed(token),
        params={"target_muscle": "lats"},
    )
    assert resp.status_code == 200, resp.text
    matches = resp.json()["exercises"]
    ids = [match["id"] for match in matches]
    assert ids[:2] == ["150", "2330"]
    assert len(matches) == 33
    assert "lat-29" in ids


def test_replace_browse_ranks_case_only_reviewed_staple_first(api):
    client, _ = api
    token = _register(client, "reviewed-traps")["access_token"]

    resp = client.get(
        "/workouts/exercises",
        headers=_authed(token),
        params={"target_muscle": "traps"},
    )

    assert resp.status_code == 200, resp.text
    matches = resp.json()["exercises"]
    assert matches[0]["id"] == "mayos:1"
    assert matches[0]["name"] == "Kelso Shrug"


def test_catalog_search_combines_a_name_query_with_the_muscle(api):
    """A name query stays optional and narrows within the muscle: the Replace
    search's pill keeps the catalog browsable (#162)."""
    client, _ = api
    token = _register(client, "narrow")["access_token"]

    resp = client.get(
        "/workouts/exercises",
        headers=_authed(token),
        params={"query": "press", "target_muscle": "Shoulders"},
    )
    assert resp.status_code == 200, resp.text
    assert [m["id"] for m in resp.json()["exercises"]] == ["op"]

    # The same query without a muscle still searches the whole catalog.
    resp = client.get(
        "/workouts/exercises", headers=_authed(token), params={"query": "press"}
    )
    assert resp.status_code == 200, resp.text
    assert "op" in [m["id"] for m in resp.json()["exercises"]]
    assert "bp" in [m["id"] for m in resp.json()["exercises"]]


def test_catalog_search_requires_a_query_or_a_muscle(api):
    """Neither parameter is the only refused shape: an unfiltered dump of the
    shared catalog is not what this endpoint is for."""
    client, _ = api
    token = _register(client, "empty")["access_token"]

    resp = client.get("/workouts/exercises", headers=_authed(token))
    assert resp.status_code == 400, resp.text
    resp = client.get(
        "/workouts/exercises",
        headers=_authed(token),
        params={"query": "", "target_muscle": ""},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.parametrize(
    "access,expected",
    [
        (COMMERCIAL_GYM, {"machine-chest", "dumbbell-chest", "bp", "ib"}),
        (HOME_GYM, {"dumbbell-chest", "band-chest", "pullup-chest", "weighted-chest", "bp", "ib"}),
        (BODYWEIGHT_ONLY, {"pullup-chest"}),
    ],
)
def test_logger_muscle_browse_suggests_only_equipment_access_options(api, access, expected):
    client, db = api
    username = f"browse-{access.lower().replace(' ', '-')}"
    token = _register(client, username)["access_token"]
    db.catalog_conn.executemany(
        "INSERT INTO exercises (id, name, body_part, target_muscle, equipment) VALUES (?, ?, 'Chest', 'Chest', ?)",
        [
            ("machine-chest", "Machine Chest Press", "leverage machine"),
            ("dumbbell-chest", "Dumbbell Chest Press", "dumbbell"),
            ("band-chest", "Band Chest Press", "band"),
            ("pullup-chest", "Pull-up", "body weight"),
            ("weighted-chest", "Weighted Dip", "weighted"),
        ],
    )
    db.catalog_conn.commit()
    with db.open_ledger(username) as ledger:
        ledger.upsert_player_profile({"equipment_access": access})

    browse = client.get(
        "/workouts/exercises",
        headers=_authed(token),
        params={"target_muscle": "Chest"},
    )
    assert browse.status_code == 200, browse.text
    assert {item["id"] for item in browse.json()["exercises"]} == expected

    # A typed name is the player's explicit Exercise library search, so it can
    # still find a bodyweight movement and use it as an Unplanned exercise.
    explicit = client.get(
        "/workouts/exercises",
        headers=_authed(token),
        params={"query": "pull-up"},
    )
    assert explicit.status_code == 200, explicit.text
    assert "pullup-chest" in {item["id"] for item in explicit.json()["exercises"]}

    # The Commercial gym player can choose that explicit result and record it.
    planned = [
        {"exercise_id": exercise_id, "exercise_name": name, "target_reps_min": 8, "target_reps_max": 12}
        for exercise_id, name in (
            ("pullup-chest", "Pull-up"),
            ("dumbbell-chest", "Dumbbell Chest Press"),
            ("machine-chest", "Machine Chest Press"),
        )
    ]
    with db.open_ledger(username) as ledger:
        ledger.save_training_program({
            "program_name": "Explicit choice",
            "weekly_frequency": 1,
            "split_type": "Custom",
            "days": [{"day_name": "Day 1", "day_order": 1, "exercises": planned}],
        })
    logged = client.post(
        "/workouts/sessions",
        headers=_authed(token),
        json={
            "day_order": 1,
            "readiness": 3,
            "sets": [{
                "exercise": {
                    "exercise_id": "pullup-chest",
                    "exercise_name": "Pull-up",
                    "target_reps_min": 8,
                    "target_reps_max": 12,
                },
                "sets": [{"weight_kg": 0, "reps": 5}],
            }],
        },
    )
    assert logged.status_code == 201, logged.text
