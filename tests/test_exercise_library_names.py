"""Exercise library display names and aliases (ADR 053, #225)."""

import csv
from pathlib import Path

import pytest


def _seed_minimal_library(store, path):
    with path.open("w", newline="", encoding="utf-8") as seed_file:
        writer = csv.writer(seed_file)
        writer.writerow(
            ["id", "name", "bodyPart", "target", "equipment", "image_path", "gif_path", "instructions"]
        )
        writer.writerow(
            ["9001", "cable row", "back", "lats", "cable", None, None, "Pull the handle to your ribs."]
        )
    store.initialize_and_seed(path)


def test_mayos_authored_staples_are_searchable_and_have_reviewable_details(tmp_path, monkeypatch):
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
    _seed_minimal_library(fresh_store, tmp_path / "seed.csv")

    expected = {
        "mayos:1": ("Kelso Shrug", "kelso shrug", "back", "traps", ("lats", "rhomboids"), "cable"),
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
        assert detail["image_path"] is None
        assert detail["gif_path"] is None
        assert detail["provenance"] == "MAYOS"
        assert any(result["id"] == exercise_id for result in fresh_store.find_exercises_by_name(alias))

        assert any(
            result["id"] == exercise_id
            for result in fresh_store.search_similar_exercises(query_vector, limit=20)
        )
    fresh_store.catalog_conn.close()


def test_mayos_authored_staples_are_upserted_and_keep_their_exercise_ids(tmp_path, monkeypatch):
    from database.database_manager import DatabaseManager
    from database.exercise_library import authored
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
    current_seed = authored.MAYOS_AUTHORED_EXERCISES
    older_seed = tuple(
        {
            **exercise,
            "name": "kelso shrug old wording" if exercise["id"] == "mayos:1" else exercise["name"],
            "display_name": "Old Kelso Shrug" if exercise["id"] == "mayos:1" else exercise["display_name"],
            "aliases": ("old kelso shrug",) if exercise["id"] == "mayos:1" else exercise["aliases"],
        }
        for exercise in current_seed
    )
    monkeypatch.setattr(authored, "MAYOS_AUTHORED_EXERCISES", older_seed)
    _seed_minimal_library(fresh_store, tmp_path / "seed.csv")
    assert fresh_store.get_exercise_library_entry("mayos:1")["name"] == "Old Kelso Shrug"

    monkeypatch.setattr(authored, "MAYOS_AUTHORED_EXERCISES", current_seed)
    fresh_store.initialize_and_seed(tmp_path / "seed.csv")

    assert fresh_store.get_exercise_library_entry("mayos:1")["name"] == "Kelso Shrug"
    assert any(
        match["id"] == "mayos:1"
        for match in fresh_store.find_exercises_by_name("kelso shrug", limit=10)
    )
    assert all(
        match["id"] != "mayos:1"
        for match in fresh_store.find_exercises_by_name("old kelso shrug", limit=10)
    )
    fresh_store.catalog_conn.close()


def test_existing_vectors_backfill_tracking_without_loading_embedding_model(tmp_path, monkeypatch):
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
    _seed_minimal_library(fresh_store, tmp_path / "seed.csv")
    fresh_store.catalog_conn.execute("DROP TABLE exercise_embedding_sources")
    fresh_store.catalog_conn.commit()

    def unexpected_model_load():
        pytest.fail("Existing exercise vectors should not require the embedding model.")

    monkeypatch.setattr(embeddings, "_load_embedding_model", unexpected_model_load)
    fresh_store.initialize_and_seed(tmp_path / "seed.csv")

    assert fresh_store.get_exercise_library_entry("mayos:1")["name"] == "Kelso Shrug"
    fresh_store.catalog_conn.close()


@pytest.mark.parametrize(
    "query",
    ["frontal lat pulldown", "lat pull-down", "lat pulldown", "wide grip pulldown"],
)
def test_pulldown_aliases_return_display_names(fresh_store, query):
    fresh_store.initialize_and_seed()

    matches = fresh_store.find_exercises_by_name(
        query, limit=10, target_muscle="lats"
    )

    assert {match["id"] for match in matches} >= {"2330", "150"}
    assert {match["name"] for match in matches if match["id"] == "2330"} == {
        "Wide-Grip Lat Pulldown"
    }
    assert {match["name"] for match in matches if match["id"] == "150"} == {
        "Lat Pulldown"
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
        "2330": ("Wide-Grip Lat Pulldown", "frontal lat pulldown"),
        "150": ("Lat Pulldown", "frontal lat pulldown"),
        "596": ("Pec Deck", "pec deck"),
        "602": ("Reverse Pec Deck", "reverse pec deck"),
        "3562": ("Barbell Hip Thrust", "barbell hip thrust"),
        "757": ("Smith Incline Press", "smith incline press"),
        "175": ("Cable Crunch", "cable crunch"),
        "3541": ("Incline DB Y-Raise", "incline db y raise"),
        "318": ("Incline DB Curl", "incline db curl"),
        "598": ("Hip Adduction", "hip adduction"),
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
        assert startup_store.get_exercise_library_entry("2330")["name"] == "Wide-Grip Lat Pulldown"
        assert {match["id"] for match in startup_store.find_exercises_by_name("frontal lat pulldown")} >= {
            "2330",
            "150",
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
        "Wide-Grip Lat Pulldown"
    )
    assert logged_exercises(
        fresh_store, fresh_store.ledger.ledger_id, ledger=fresh_store.ledger
    ) == [{"id": "2330", "name": "Wide-Grip Lat Pulldown"}]


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
    assert fresh_store.get_exercise_library_entry("2330")["name"] == "Wide-Grip Lat Pulldown"
    assert "2330" in {
        match["id"] for match in fresh_store.find_exercises_by_name("frontal lat pulldown")
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
