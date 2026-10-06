"""Exercise library display names and aliases (ADR 053, #225)."""

import csv
from pathlib import Path

import pytest

CURATION_COLUMNS = [
    "id",
    "source_name",
    "display_name",
    "aliases",
    "primary_action",
    "secondary_actions",
    "primary_muscle",
    "load_type",
    "hidden",
    "duplicate_of",
]


def _write_curation(path, rows):
    with path.open("w", newline="", encoding="utf-8") as curation_file:
        writer = csv.writer(curation_file)
        writer.writerow(CURATION_COLUMNS)
        for row in rows:
            exercise_id, source_name, display_name, aliases = row[:4]
            writer.writerow(
                [exercise_id, source_name, display_name, aliases, "", "", "", "", "", ""]
            )


def _write_curated_rows(path, rows):
    with path.open("w", newline="", encoding="utf-8") as curation_file:
        writer = csv.writer(curation_file)
        writer.writerow(CURATION_COLUMNS)
        writer.writerows(rows)


def _seed_minimal_library(store, path, curation_path=None):
    with path.open("w", newline="", encoding="utf-8") as seed_file:
        writer = csv.writer(seed_file)
        writer.writerow(
            ["id", "name", "bodyPart", "target", "equipment", "image_path", "gif_path", "instructions"]
        )
        writer.writerow(
            ["9001", "cable row", "back", "lats", "cable", None, None, "Pull the handle to your ribs."]
        )
    if curation_path is None:
        store.initialize_and_seed(path)
    else:
        store.initialize_and_seed(path, curation_path)


@pytest.fixture
def seed_store(tmp_path, monkeypatch):
    from database.database_manager import DatabaseManager
    from database.exercise_library import embeddings
    from database.schema.definitions import EMBEDDING_DIM

    fresh_store = DatabaseManager(
        catalog_path=tmp_path / "catalog.db",
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
    )

    class LocalEmbeddingStub:
        def embed_query(self, text):
            return [1.0] + [0.0] * (EMBEDDING_DIM - 1)

    monkeypatch.setattr(embeddings, "_load_embedding_model", lambda: LocalEmbeddingStub())
    try:
        yield fresh_store
    finally:
        if fresh_store.ledger_conn is not None:
            fresh_store.ledger_conn.close()
        fresh_store.catalog_conn.close()


def test_unique_exact_exercise_id_lookup_uses_names_and_rejects_ambiguity(seed_store, tmp_path):
    fresh_store = seed_store
    _seed_minimal_library(fresh_store, tmp_path / "seed.csv")

    assert fresh_store.find_unique_exercise_id_by_exact_name("Cable Row") == "9001"
    with fresh_store.catalog_locked() as conn:
        conn.execute(
            "UPDATE exercise_display_names SET display_name = ? WHERE exercise_id = ?",
            ("Cable Row Display", "9001"),
        )
        conn.execute(
            "INSERT INTO exercise_aliases (exercise_id, alias, normalized_alias) VALUES (?, ?, ?)",
            ("9001", "Cable Row Alias", "cable row alias"),
        )
        conn.execute(
            "INSERT INTO exercises (id, name, body_part, target_muscle, equipment) "
            "VALUES (?, ?, ?, ?, ?)",
            ("9002", "Another Row", "back", "lats", "cable"),
        )
        conn.commit()

    assert fresh_store.find_unique_exercise_id_by_exact_name("Cable Row Display") == "9001"
    assert fresh_store.find_unique_exercise_id_by_exact_name("Cable Row Alias") == "9001"
    with fresh_store.catalog_locked() as conn:
        conn.execute(
            "INSERT INTO exercise_aliases (exercise_id, alias, normalized_alias) VALUES (?, ?, ?)",
            ("9002", "Cable Row Alias", "cable row alias"),
        )
        conn.commit()
    assert fresh_store.find_unique_exercise_id_by_exact_name("Cable Row Alias") is None


#: Owner-supplied demo media for authored exercises (uploaded to the media store).
AUTHORED_MEDIA = {
    "mayos:2": ("images/mayos-2-bayesian-curl.jpg", "videos/mayos-2-bayesian-curl.gif"),
}


def test_mayos_authored_staples_are_searchable_and_have_reviewable_details(seed_store, tmp_path):
    from database.schema.definitions import EMBEDDING_DIM

    fresh_store = seed_store
    _seed_minimal_library(fresh_store, tmp_path / "seed.csv")

    # The cable Kelso shrug is hidden as a duplicate of the dumbbell Kelso shrug (305):
    # still readable by id for existing programs, never offered in search.
    kelso = fresh_store.get_exercise_library_detail("mayos:1")
    assert kelso["provenance"] == "MAYOS"
    assert fresh_store.is_exercise_library_exercise_visible("mayos:1") is False
    assert all(result["id"] != "mayos:1" for result in fresh_store.find_exercises_by_name("kelso shrug"))

    expected = {
        "mayos:2": ("Bayesian Curl", "bayesian curl", "upper arms", "biceps", ("forearms",), "cable"),
        "mayos:3": ("Cable Y-Raise", "cable y raise", "shoulders", "delts", ("traps",), "cable"),
        "mayos:4": ("Machine Hip Thrust", "machine hip thrust", "upper legs", "glutes", ("hamstrings",), "leverage machine"),
    }
    query_vector = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    for exercise_id, (display_name, alias, body_part, target, secondary, equipment) in expected.items():
        detail = fresh_store.get_exercise_library_detail(exercise_id)
        assert detail["name"] == display_name
        assert detail["body_part"] == body_part
        assert detail["primary_muscles"] == [target]
        assert tuple(detail["secondary_muscles"]) == secondary
        assert detail["equipment"] == equipment
        assert detail["instructions"]
        assert len(detail["instructions"].splitlines()) in (3, 4)
        expected_media = AUTHORED_MEDIA.get(exercise_id, (None, None))
        assert (detail["image_path"], detail["gif_path"]) == expected_media
        assert detail["provenance"] == "MAYOS"
        assert any(result["id"] == exercise_id for result in fresh_store.find_exercises_by_name(alias))

        assert any(
            result["id"] == exercise_id
            for result in fresh_store.search_similar_exercises(query_vector, limit=20)
        )


def test_curation_names_and_aliases_are_upserted_on_each_seed(seed_store, tmp_path):
    fresh_store = seed_store
    seed_path = tmp_path / "seed.csv"
    curation_path = tmp_path / "curation.csv"
    _write_curation(curation_path, [("mayos:1", "Kelso shrug", "Older Kelso", "older kelso")])
    _seed_minimal_library(fresh_store, seed_path, curation_path)

    assert fresh_store.get_exercise_library_entry("mayos:1")["name"] == "Older Kelso"
    assert any(match["id"] == "mayos:1" for match in fresh_store.find_exercises_by_name("older kelso"))

    _write_curation(curation_path, [("mayos:1", "Kelso shrug", "Kelso Shrug", "kelso shrug")])
    fresh_store.initialize_and_seed(seed_path, curation_path)

    assert fresh_store.get_exercise_library_entry("mayos:1")["name"] == "Kelso Shrug"
    assert any(
        match["id"] == "mayos:1"
        for match in fresh_store.find_exercises_by_name("kelso shrug", limit=10)
    )
    assert all(
        match["id"] != "mayos:1"
        for match in fresh_store.find_exercises_by_name("older kelso", limit=10)
    )


def test_hidden_duplicate_resolves_to_kept_display_name_and_is_not_searchable(seed_store, tmp_path):
    seed_path = tmp_path / "seed.csv"
    with seed_path.open("w", newline="", encoding="utf-8") as seed_file:
        writer = csv.writer(seed_file)
        writer.writerow(
            ["id", "name", "bodyPart", "target", "equipment", "image_path", "gif_path", "instructions"]
        )
        writer.writerows([
            ["9001", "cable row duplicate", "back", "lats", "cable", None, None, "Duplicate row."],
            ["9002", "seated cable row", "back", "lats", "cable", None, None, "Kept row."],
        ])
    curation_path = tmp_path / "curation.csv"
    _write_curated_rows(
        curation_path,
        [
            ["9001", "cable row duplicate", "", "duplicate cable row", "", "", "", "", "TRUE", "9002"],
            ["9002", "seated cable row", "Seated Cable Row", "", "", "", "", "", "False", ""],
        ],
    )

    seed_store.initialize_and_seed(seed_path, curation_path)

    assert seed_store.get_exercise_library_entry("9001")["name"] == "Seated Cable Row"
    assert seed_store.get_exercise_library_detail("9001")["name"] == "Seated Cable Row"
    assert seed_store.is_exercise_library_exercise_visible("9001") is False
    assert seed_store.is_exercise_library_exercise_visible("9002") is True
    assert all(match["id"] != "9001" for match in seed_store.find_exercises_by_name("duplicate cable row"))


@pytest.mark.parametrize(
    ("hidden", "duplicate_of", "extra_rows", "message"),
    [
        ("maybe", "", [], "invalid hidden value 'maybe'"),
        ("true", "missing-id", [], "missing duplicate_of value 'missing-id'"),
        ("", "9002", [], "while hidden is false"),
        (
            "true",
            "9002",
            [["9002", "other row", "", "", "", "", "", "", "true", "9001"]],
            "hidden duplicate_of target '9002'",
        ),
    ],
)
def test_invalid_hidden_duplicate_curation_fails_load(
    seed_store, tmp_path, hidden, duplicate_of, extra_rows, message
):
    seed_path = tmp_path / "seed.csv"
    _seed_minimal_library(seed_store, seed_path)
    seed_store.catalog_conn.execute(
        "INSERT INTO exercises (id, name, body_part, target_muscle, equipment) "
        "VALUES ('9002', 'other row', 'back', 'lats', 'cable')"
    )
    seed_store.catalog_conn.commit()
    curation_path = tmp_path / "curation.csv"
    _write_curated_rows(
        curation_path,
        [["9001", "cable row", "", "", "", "", "", "", hidden, duplicate_of], *extra_rows],
    )

    with pytest.raises(ValueError, match=message):
        seed_store.initialize_and_seed(seed_path, curation_path)


def test_loading_fails_when_a_staple_is_hidden(seed_store, tmp_path):
    seed_path = tmp_path / "seed.csv"
    _seed_minimal_library(seed_store, seed_path)
    curation_path = tmp_path / "curation.csv"
    _write_curated_rows(
        curation_path,
        [["mayos:2", "Bayesian curl", "", "", "", "", "", "", "true", ""]],
    )

    with pytest.raises(ValueError, match="line 2 id 'mayos:2'.*Staple exercise hidden"):
        seed_store.initialize_and_seed(seed_path, curation_path)


def test_semantic_search_excludes_hidden_exercises(seed_store, tmp_path, seed_exercise_curation):
    from database.schema.definitions import EMBEDDING_DIM

    _seed_minimal_library(seed_store, tmp_path / "seed.csv")
    query_vector = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    visible_results = seed_store.search_similar_exercises(query_vector, limit=20)
    assert "9001" in {result["id"] for result in visible_results}

    seed_exercise_curation(seed_store, {"9001": {"hidden": True}})

    results = seed_store.search_similar_exercises(query_vector, limit=20)

    assert "9001" not in {result["id"] for result in results}


def test_semantic_search_keeps_excluding_behind_the_neck_rows_with_display_names(seed_store, tmp_path):
    from database.schema.definitions import EMBEDDING_DIM

    seed_path = tmp_path / "seed.csv"
    with seed_path.open("w", newline="", encoding="utf-8") as seed_file:
        writer = csv.writer(seed_file)
        writer.writerow(
            ["id", "name", "bodyPart", "target", "equipment", "image_path", "gif_path", "instructions"]
        )
        writer.writerow(
            ["9201", "smith behind neck press", "shoulders", "delts", "smith machine", None, None, "Press."]
        )
    curation_path = tmp_path / "curation.csv"
    _write_curated_rows(
        curation_path,
        [["9201", "smith behind neck press", "Behind-the-Neck Press (Smith Machine)", "", "", "", "", "", "", ""]],
    )
    seed_store.initialize_and_seed(seed_path, curation_path)

    results = seed_store.search_similar_exercises([1.0] + [0.0] * (EMBEDDING_DIM - 1), limit=20)

    assert "9201" not in {result["id"] for result in results}


def test_primary_muscle_curation_is_searchable_and_returned_in_detail(
    seed_store, tmp_path, seed_exercise_curation
):
    from database.exercise_library.filters import ExerciseFilters

    seed_path = tmp_path / "seed.csv"
    _seed_minimal_library(seed_store, seed_path)
    seed_exercise_curation(seed_store, {"9001": {"primary_muscle": "Upper Back"}})

    matches = seed_store.find_exercises_by_name(
        "", filters=ExerciseFilters(primary_muscles=("Upper Back",))
    )

    assert [match["id"] for match in matches] == ["9001"]
    assert matches[0]["primary_muscle"] == "Upper Back"
    assert seed_store.get_exercise_library_detail("9001")["primary_muscle"] == "Upper Back"


def test_curation_rejects_primary_muscle_outside_vocabulary(
    seed_store, tmp_path, seed_exercise_curation
):
    _seed_minimal_library(seed_store, tmp_path / "seed.csv")
    with pytest.raises(ValueError, match="line 2 id '9001'.*'Middle Back'"):
        seed_exercise_curation(
            seed_store, {"9001": {"primary_muscle": "Middle Back"}}
        )


@pytest.mark.parametrize(
    "fields, invalid_action",
    [
        ({"primary_action": "Knee Curl"}, "Knee Curl"),
        ({"secondary_actions": ["Knee Curl"]}, "Knee Curl"),
    ],
)
def test_curation_rejects_action_outside_vocabulary(
    seed_store, tmp_path, seed_exercise_curation, fields, invalid_action
):
    _seed_minimal_library(seed_store, tmp_path / "seed.csv")

    with pytest.raises(
        ValueError,
        match=f"line 2 id '9001'.*{invalid_action!r}",
    ):
        seed_exercise_curation(seed_store, {"9001": fields})


def test_curation_rejects_unknown_load_type_with_source_row_context(seed_store, tmp_path):
    curation_path = tmp_path / "bad-load-type.csv"
    seed_path = tmp_path / "seed.csv"
    _write_curated_rows(
        curation_path,
        [["9001", "cable row", "", "", "", "", "", "hydraulic", "", ""]],
    )

    with pytest.raises(ValueError, match="line 2 id '9001'.*'hydraulic'"):
        _seed_minimal_library(seed_store, seed_path, curation_path)


def test_curation_rejects_load_type_for_non_machine_equipment(seed_store, tmp_path):
    curation_path = tmp_path / "non-machine-load-type.csv"
    seed_path = tmp_path / "seed.csv"
    _write_curated_rows(
        curation_path,
        [["9001", "cable row", "", "", "", "", "", "selectorized", "", ""]],
    )

    with pytest.raises(ValueError, match="line 2 id '9001'.*'selectorized'.*non-Machine"):
        _seed_minimal_library(seed_store, seed_path, curation_path)


def test_curation_rows_for_exercises_outside_the_library_are_ignored(seed_store, tmp_path):
    curation_path = tmp_path / "rows-outside-library.csv"
    _write_curated_rows(
        curation_path,
        [
            ["9101", "lever chest press", "Chest Press (Machine)", "", "", "", "", "selectorized", "", ""],
            ["9102", "lever chest press v. 2", "", "", "", "", "", "", "true", "9103"],
        ],
    )

    _seed_minimal_library(seed_store, tmp_path / "seed.csv", curation_path)

    assert seed_store.get_exercise_library_entry("9001")["name"] == "Cable Row"
    assert seed_store.get_exercise_library_entry("9101") is None


def test_machine_load_type_is_curated_and_returned_by_search_and_detail(seed_store, tmp_path):
    from database.exercise_library.filters import ExerciseFilters

    seed_path = tmp_path / "machine-seed.csv"
    with seed_path.open("w", newline="", encoding="utf-8") as seed_file:
        writer = csv.writer(seed_file)
        writer.writerow(
            ["id", "name", "bodyPart", "target", "equipment", "image_path", "gif_path", "instructions"]
        )
        writer.writerow(["9100", "Machine press", "Chest", "Chest", "Leverage Machine", "", "", ""])
    curation_path = tmp_path / "machine-curation.csv"
    _write_curated_rows(
        curation_path,
        [["9100", "Machine press", "", "", "", "", "", "plate_loaded", "", ""]],
    )
    seed_store.initialize_and_seed(seed_path, curation_path)

    matches = seed_store.find_exercises_by_name(
        "", filters=ExerciseFilters(load_types=("plate_loaded",))
    )

    assert [match["id"] for match in matches] == ["9100"]
    assert matches[0]["equipment_category"] == "Machine"
    assert matches[0]["load_type"] == "plate_loaded"
    detail = seed_store.get_exercise_library_detail("9100")
    assert detail["equipment_category"] == "Machine"
    assert detail["load_type"] == "plate_loaded"


def test_empty_curation_file_uses_title_case_source_names(seed_store, tmp_path):
    fresh_store = seed_store
    curation_path = tmp_path / "empty-curation.csv"
    _write_curation(curation_path, [])
    _seed_minimal_library(fresh_store, tmp_path / "seed.csv", curation_path)

    assert fresh_store.get_exercise_library_entry("9001")["name"] == "Cable Row"
    assert any(
        match["id"] == "9001" and match["name"] == "Cable Row"
        for match in fresh_store.find_exercises_by_name("cable row")
    )


def test_existing_vectors_backfill_tracking_without_loading_embedding_model(seed_store, monkeypatch, tmp_path):
    from database.exercise_library import embeddings

    fresh_store = seed_store
    _seed_minimal_library(fresh_store, tmp_path / "seed.csv")
    fresh_store.catalog_conn.execute("DROP TABLE exercise_embedding_sources")
    fresh_store.catalog_conn.commit()

    def unexpected_model_load():
        pytest.fail("Existing exercise vectors should not require the embedding model.")

    monkeypatch.setattr(embeddings, "_load_embedding_model", unexpected_model_load)
    fresh_store.initialize_and_seed(tmp_path / "seed.csv")

    assert fresh_store.get_exercise_library_entry("mayos:1")["name"] == "Kelso Shrug"


def test_existing_display_name_schema_is_upgraded_on_catalog_startup(tmp_path):
    import sqlite3

    from database.database_manager import DatabaseManager

    catalog_path = tmp_path / "old-catalog.db"
    conn = sqlite3.connect(catalog_path)
    conn.executescript("""
        CREATE TABLE exercises (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            body_part TEXT NOT NULL,
            target_muscle TEXT NOT NULL,
            equipment TEXT NOT NULL,
            image_path TEXT,
            gif_path TEXT,
            instructions TEXT
        );
        CREATE TABLE exercise_display_names (
            exercise_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL
        );
        INSERT INTO exercises (id, name, body_part, target_muscle, equipment)
        VALUES ('legacy', 'cable row', 'Back', 'lats', 'cable');
        INSERT INTO exercise_display_names (exercise_id, display_name)
        VALUES ('legacy', 'Legacy Display');
    """)
    conn.commit()
    conn.close()

    store = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
    )
    try:
        store.create_catalog_schema()
        assert store.get_exercise_library_entry("legacy")["name"] == "Cable Row"
    finally:
        if store.ledger_conn is not None:
            store.ledger_conn.close()
        store.catalog_conn.close()


@pytest.mark.parametrize(
    "query",
    ["frontal lat pulldown", "lat pull-down", "lat pulldown", "wide grip pulldown"],
)
def test_pulldown_aliases_return_display_names(fresh_store, query):
    fresh_store.initialize_and_seed()

    matches = fresh_store.find_exercises_by_name(
        query, limit=10, target_muscle="lats"
    )

    assert "150" in {match["id"] for match in matches}
    assert {match["name"] for match in matches if match["id"] == "150"} == {
        "Lat Pulldown (Cable)"
    }


@pytest.mark.parametrize("query", ["pendulum squat", "kelso shrug", "bayesian curl"])
def test_near_miss_names_do_not_resolve(fresh_store, query):
    fresh_store.initialize_and_seed()

    assert all(
        match["id"] not in {"744", "329", "190"}
        for match in fresh_store.find_exercises_by_name(query, limit=10)
    )


def test_confirmed_staples_use_display_names_in_library_reads(fresh_store):
    fresh_store.initialize_and_seed()
    expected = {
        "2330": ("Standing Cable Pulldown (Cable)", "standing cable pulldown"),
        "150": ("Lat Pulldown (Cable)", "frontal lat pulldown"),
        "596": ("Pec Deck (Machine)", "pec deck"),
        "602": ("Reverse Pec Deck (Machine)", "reverse pec deck"),
        "3562": ("Hip Thrust (Barbell)", "barbell hip thrust"),
        "757": ("Incline Bench Press (Smith Machine)", "smith incline press"),
        "175": ("Kneeling Crunch (Cable)", "cable crunch"),
        "3541": ("Incline Y-Raise (Dumbbell)", "incline db y raise"),
        "318": ("Incline Curl (Dumbbell)", "incline db curl"),
        "598": ("Hip Adduction (Machine)", "hip adduction"),
    }

    for exercise_id, (display_name, alias) in expected.items():
        entry = fresh_store.get_exercise_library_entry(exercise_id)
        matches = fresh_store.find_exercises_by_name(alias, limit=10)
        assert entry["name"] == display_name
        assert any(
            match["id"] == exercise_id and match["name"] == display_name
            for match in matches
        )


def test_curated_names_are_reapplied_on_catalog_startup(fresh_store, tmp_path: Path):
    exercise_ids = ("2330", "150", "596", "602", "3562", "757", "175", "3541", "318", "598")
    placeholders = ", ".join("?" for _ in exercise_ids)
    fresh_store.catalog_conn.execute(
        f"DELETE FROM exercise_aliases WHERE exercise_id IN ({placeholders})", exercise_ids
    )
    fresh_store.catalog_conn.execute(
        f"DELETE FROM exercise_display_names WHERE exercise_id IN ({placeholders})", exercise_ids
    )
    fresh_store.catalog_conn.commit()

    from database.database_manager import DatabaseManager

    startup_store = DatabaseManager(
        catalog_path=fresh_store.catalog_path,
        ledgers_dir=tmp_path / "startup-users",
        backups_dir=tmp_path / "startup-backups",
    )
    try:
        assert startup_store.get_exercise_library_entry("2330")["name"] == "Standing Cable Pulldown (Cable)"
        assert "150" in {match["id"] for match in startup_store.find_exercises_by_name("frontal lat pulldown")}
        assert "2330" in {
            match["id"] for match in startup_store.find_exercises_by_name("standing cable pulldown")
        }
    finally:
        if startup_store.ledger_conn is not None:
            startup_store.ledger_conn.close()
        startup_store.catalog_conn.close()


def test_program_and_coach_exercise_list_use_display_name(fresh_store):
    from service.dashboard import logged_exercises

    fresh_store.initialize_and_seed()
    fresh_store.ledger.save_training_program(
        {
            "program_name": "Name display test",
            "weekly_frequency": 1,
            "split_type": "custom",
            "days": [
                {
                    "day_name": "Day 1",
                    "day_order": 1,
                    "exercises": [
                        {"exercise_id": "2330"},
                        {"exercise_id": "150"},
                        {"exercise_id": "596"},
                    ],
                }
            ],
        }
    )
    fresh_store.ledger.conn.execute(
        "INSERT INTO workout_sessions (id, session_date, split_name, started_at) "
        "VALUES ('session', '2026-09-30', 'Day 1', '2026-09-30T09:00:00Z')"
    )
    fresh_store.ledger.conn.execute(
        "INSERT INTO workout_sets (id, session_id, exercise_id, set_index, weight_kg, reps, "
        "is_warmup, logged_at) VALUES ('set', 'session', '2330', 1, 40, 10, 0, '2026-09-30T09:10:00Z')"
    )
    fresh_store.ledger.conn.commit()

    assert fresh_store.ledger.get_active_program().days[0].exercises[0].exercise_name == (
        "Standing Cable Pulldown (Cable)"
    )
    assert logged_exercises(
        fresh_store, fresh_store.ledger.ledger_id, ledger=fresh_store.ledger
    ) == [{"id": "2330", "name": "Standing Cable Pulldown (Cable)"}]


def test_reseeding_upserts_source_rows_and_replaces_curated_aliases(fresh_store, tmp_path: Path):
    fresh_store.initialize_and_seed()
    original = fresh_store.catalog_conn.execute(
        "SELECT id, name, body_part, target_muscle, equipment, image_path, gif_path, instructions "
        "FROM exercises WHERE id = '2330'"
    ).fetchone()
    fresh_store.ledger.conn.execute(
        "INSERT INTO workout_sessions (id, session_date, split_name, started_at) "
        "VALUES ('seed-history', '2026-09-30', 'Pull', '2026-09-30T09:00:00Z')"
    )
    fresh_store.ledger.conn.execute(
        "INSERT INTO workout_sets (id, session_id, exercise_id, set_index, weight_kg, reps, "
        "is_warmup, logged_at) VALUES ('seed-set', 'seed-history', '2330', 1, 40, 10, 0, "
        "'2026-09-30T09:10:00Z')"
    )
    fresh_store.ledger.conn.commit()
    fresh_store.catalog_conn.execute(
        "INSERT INTO exercises VALUES ('keep', 'Keep row', 'Back', 'Lats', 'cable', NULL, NULL, '')"
    )
    fresh_store.catalog_conn.execute(
        "UPDATE exercises SET name = 'stale name' WHERE id = '2330'"
    )
    fresh_store.catalog_conn.execute(
        "UPDATE exercise_display_names SET display_name = 'Stale Display' WHERE exercise_id = '2330'"
    )
    fresh_store.catalog_conn.execute(
        "DELETE FROM exercise_aliases WHERE exercise_id = '2330'"
    )
    fresh_store.catalog_conn.commit()

    seed_path = tmp_path / "seed.csv"
    with seed_path.open("w", newline="", encoding="utf-8") as seed_file:
        writer = csv.writer(seed_file)
        writer.writerow(
            ["id", "name", "bodyPart", "target", "equipment", "image_path", "gif_path", "instructions"]
        )
        writer.writerow(original)

    fresh_store.initialize_and_seed(seed_path)
    first_alias_count = fresh_store.catalog_conn.execute(
        "SELECT COUNT(*) FROM exercise_aliases WHERE exercise_id = '2330'"
    ).fetchone()[0]
    fresh_store.initialize_and_seed(seed_path)

    restored = fresh_store.catalog_conn.execute(
        "SELECT id, name, image_path, gif_path FROM exercises WHERE id = '2330'"
    ).fetchone()
    assert restored == ("2330", original[1], original[5], original[6])
    assert fresh_store.catalog_conn.execute(
        "SELECT COUNT(*) FROM exercises WHERE id = 'keep'"
    ).fetchone()[0] == 1
    assert fresh_store.get_exercise_library_entry("2330")["name"] == "Standing Cable Pulldown (Cable)"
    assert "2330" in {
        match["id"] for match in fresh_store.find_exercises_by_name("standing cable pulldown")
    }
    assert fresh_store.ledger.conn.execute(
        "SELECT exercise_id FROM workout_sets WHERE id = 'seed-set'"
    ).fetchone()[0] == "2330"
    assert first_alias_count > 0
    assert fresh_store.catalog_conn.execute(
        "SELECT COUNT(*) FROM exercise_aliases WHERE exercise_id = '2330'"
    ).fetchone()[0] == first_alias_count


def test_seed_normalizes_source_names_and_preserves_ids_and_media(fresh_store, tmp_path: Path):
    fresh_store.initialize_and_seed()
    existing_media = fresh_store.catalog_conn.execute(
        "SELECT id, image_path, gif_path FROM exercises WHERE id = '2330'"
    ).fetchone()
    fresh_store.catalog_conn.executemany(
        "INSERT INTO exercises (id, name, body_part, target_muscle, equipment, image_path, gif_path) "
        "VALUES (?, ?, 'Back', 'Lats', 'cable', ?, ?)",
        [
            ("seed-lever", "old lever row", "old-lever-image", "old-lever-gif"),
            ("seed-version", "old version row", "old-version-image", "old-version-gif"),
        ],
    )
    fresh_store.catalog_conn.commit()

    seed_path = tmp_path / "normalized-seed.csv"
    with seed_path.open("w", newline="", encoding="utf-8") as seed_file:
        writer = csv.writer(seed_file)
        writer.writerow(
            ["id", "name", "bodyPart", "target", "equipment", "image_path", "gif_path", "instructions"]
        )
        writer.writerows(
            [
                ["seed-lever", "LeVeR seated row", "Back", "Lats", "cable", "lever-image", "lever-gif", "row"],
                ["seed-version", "Cable Fly v. 2", "Chest", "Pectorals", "cable", "version-image", "version-gif", "fly"],
            ]
        )

    count_before = fresh_store.catalog_conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0]
    fresh_store.initialize_and_seed(seed_path)
    first_rows = fresh_store.catalog_conn.execute(
        "SELECT id, name, image_path, gif_path FROM exercises WHERE id LIKE 'seed-%' ORDER BY id"
    ).fetchall()
    fresh_store.initialize_and_seed(seed_path)
    second_rows = fresh_store.catalog_conn.execute(
        "SELECT id, name, image_path, gif_path FROM exercises WHERE id LIKE 'seed-%' ORDER BY id"
    ).fetchall()

    assert first_rows == second_rows == [
        ("seed-lever", "machine seated row", "lever-image", "lever-gif"),
        ("seed-version", "Cable Fly", "version-image", "version-gif"),
    ]
    assert fresh_store.catalog_conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0] == count_before
    assert fresh_store.catalog_conn.execute(
        "SELECT id, image_path, gif_path FROM exercises WHERE id = '2330'"
    ).fetchone() == existing_media


def test_every_curation_file_id_exists_in_the_exercise_library():
    from database.exercise_library.authored import MAYOS_AUTHORED_EXERCISES
    from database.exercise_library.curation import load_exercise_curation
    from database.shared import DEFAULT_CSV_PATH

    with open(DEFAULT_CSV_PATH, newline="", encoding="utf-8") as seed_file:
        library_ids = {row["id"] for row in csv.DictReader(seed_file)}
    library_ids |= {exercise["id"] for exercise in MAYOS_AUTHORED_EXERCISES}

    assert set(load_exercise_curation()) - library_ids == set()


def test_saved_program_shows_current_names_for_substitutes_and_warmups(fresh_store):
    fresh_store.initialize_and_seed()
    fresh_store.ledger.save_training_program(
        {
            "program_name": "Snapshot names",
            "weekly_frequency": 1,
            "split_type": "custom",
            "days": [
                {
                    "day_name": "Day 1",
                    "day_order": 1,
                    "warmup_exercises": [
                        {"exercise_id": "276", "exercise_name": "dead bug"},
                        {"exercise_id": None, "exercise_name": "Arm circles"},
                    ],
                    "exercises": [
                        {
                            "exercise_id": "150",
                            "suggested_substitutes": [
                                {"exercise_id": "2330", "exercise_name": "Wide-Grip Lat Pulldown"},
                                {"exercise_id": "unknown-id", "exercise_name": "Kept as stored"},
                            ],
                        }
                    ],
                }
            ],
        }
    )

    day = fresh_store.ledger.get_active_program().days[0]

    assert [(s.exercise_id, s.exercise_name) for s in day.exercises[0].suggested_substitutes] == [
        ("2330", "Standing Cable Pulldown (Cable)"),
        ("unknown-id", "Kept as stored"),
    ]
    assert [w.exercise_name for w in day.warmup_exercises] == ["Dead Bug", "Arm circles"]
