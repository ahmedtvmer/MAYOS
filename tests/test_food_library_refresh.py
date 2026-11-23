"""Startup Food library refresh and reviewed-staple readiness (#844).

An old catalog only re-applies Exercise curation at startup; the Food library
and ``data/food_curation.csv`` loaded once through the initializer never
picked up newly reviewed staples. These tests pin the shipped-input seam so
the startup refresh is exercised against temp inputs.
"""

import csv
import logging

import pytest

from database.database_manager import DatabaseManager
from database.food_library import seeding
from database.food_library.seeding import FoodLibraryPaths

FOOD_FIELDS = ["id", "source", "name", "category", "energy_kcal", "protein_g",
               "carbohydrate_g", "fat_g", "fiber_g", "sugars_g", "saturated_fat_g", "sodium_mg"]
PORTION_FIELDS = ["food_id", "seq", "label", "gram_weight"]
CURATION_FIELDS = ["id", "display_name", "arabic_name", "aliases_en", "aliases_ar",
                   "hidden", "staple_roles", "portion_label", "portion_grams", "reviewed"]
RECIPE_FIELDS = ["id", "display_name", "arabic_name", "ingredient_fdc_id", "grams", "cooked_yield_g"]
EXERCISE_FIELDS = ["id", "name", "bodyPart", "target", "equipment", "image_path", "gif_path", "instructions"]
EXERCISE_CURATION_FIELDS = ["id", "source_name", "display_name", "aliases", "primary_action",
                            "secondary_actions", "primary_muscle", "load_type", "hidden", "duplicate_of"]
STAPLE_ID = "1"


def _csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_food_inputs(directory, reviewed):
    """A minimal shipped-input set holding one carb staple reviewed per ``reviewed``."""
    directory.mkdir(parents=True, exist_ok=True)
    foods = directory / "foods.csv"
    portions = directory / "food-portions.csv"
    curation = directory / "food-curation.csv"
    recipes = directory / "food-recipes.csv"
    _csv(foods, FOOD_FIELDS, [dict(
        id=STAPLE_ID, source="sr_legacy", name="Rice", category="Grains",
        energy_kcal="100", protein_g="2", carbohydrate_g="20", fat_g="1",
        fiber_g="2", sugars_g="1", saturated_fat_g="0.2", sodium_mg="10")])
    _csv(portions, PORTION_FIELDS, [dict(food_id=STAPLE_ID, seq="1", label="cup", gram_weight="150")])
    _csv(curation, CURATION_FIELDS, [dict(
        id=STAPLE_ID, display_name="Rice", arabic_name="أرز", aliases_en="rice|white rice",
        aliases_ar="رز", hidden="", staple_roles="carb", portion_label="bowl",
        portion_grams="300", reviewed="true" if reviewed else "false")])
    _csv(recipes, RECIPE_FIELDS, [])
    return FoodLibraryPaths(foods=foods, portions=portions, curation=curation, recipes=recipes)


def _write_exercise_inputs(directory):
    """Empty Exercise inputs: curation re-apply stays exercised but content-free."""
    directory.mkdir(parents=True, exist_ok=True)
    exercise_csv = directory / "exercises.csv"
    _csv(exercise_csv, EXERCISE_FIELDS, [])
    exercise_curation = directory / "exercise-curation.csv"
    _csv(exercise_curation, EXERCISE_CURATION_FIELDS, [])
    return exercise_csv, exercise_curation


def _build_store(directory, curation_path=None):
    return DatabaseManager(
        catalog_path=directory / "catalog.db",
        ledgers_dir=directory / "users",
        backups_dir=directory / "backups",
        curation_path=curation_path,
    )


def _seed(store, exercise_csv, exercise_curation, food_paths):
    store.initialize_and_seed(
        exercise_csv, exercise_curation,
        food_path=food_paths.foods, portion_path=food_paths.portions,
        food_curation_path=food_paths.curation, recipe_path=food_paths.recipes,
    )


@pytest.fixture
def stub_exercise_embeddings(monkeypatch):
    from database.exercise_library import embeddings
    from database.schema.definitions import EMBEDDING_DIM

    class LocalEmbeddingStub:
        def embed_query(self, _text):
            return [1.0] + [0.0] * (EMBEDDING_DIM - 1)

    monkeypatch.setattr(embeddings, "_load_embedding_model", lambda: LocalEmbeddingStub())


def test_next_start_picks_up_a_newly_reviewed_staple(tmp_path, monkeypatch, stub_exercise_embeddings):
    old_inputs = _write_food_inputs(tmp_path / "old-inputs", reviewed=False)
    exercise_csv, exercise_curation = _write_exercise_inputs(tmp_path / "exercise-inputs")
    store = _build_store(tmp_path, curation_path=exercise_curation)
    try:
        _seed(store, exercise_csv, exercise_curation, old_inputs)
        assert store.catalog_conn.execute(
            "SELECT reviewed, staple_roles_json FROM foods WHERE id = ?", (STAPLE_ID,)
        ).fetchone() == (0, '["carb"]')
        stored = store.catalog_conn.execute(
            "SELECT input_hash FROM food_library_meta WHERE id = 1"
        ).fetchone()[0]
        assert stored == seeding.food_library_input_hash(old_inputs)
    finally:
        store.catalog_conn.close()

    # Deploy a new curation review and start again with the shipped inputs.
    current_inputs = _write_food_inputs(tmp_path / "current-inputs", reviewed=True)
    monkeypatch.setattr(seeding, "shipped_food_library_paths", lambda: current_inputs)
    restarted = _build_store(tmp_path, curation_path=exercise_curation)
    try:
        assert restarted.catalog_conn.execute(
            "SELECT reviewed, staple_roles_json FROM foods WHERE id = ?", (STAPLE_ID,)
        ).fetchone() == (1, '["carb"]')
        assert restarted.catalog_conn.execute(
            "SELECT input_hash FROM food_library_meta WHERE id = 1"
        ).fetchone()[0] == seeding.food_library_input_hash(current_inputs)
    finally:
        restarted.catalog_conn.close()


def test_unchanged_inputs_do_no_work_on_next_start(tmp_path, monkeypatch, stub_exercise_embeddings):
    inputs = _write_food_inputs(tmp_path / "inputs", reviewed=True)
    exercise_csv, exercise_curation = _write_exercise_inputs(tmp_path / "exercise-inputs")
    store = _build_store(tmp_path, curation_path=exercise_curation)
    try:
        _seed(store, exercise_csv, exercise_curation, inputs)
    finally:
        store.catalog_conn.close()

    calls = []
    real_seed = seeding.seed_food_library

    def spy(connection, *args):
        calls.append(args)
        return real_seed(connection, *args)

    monkeypatch.setattr(seeding, "seed_food_library", spy)
    monkeypatch.setattr(seeding, "shipped_food_library_paths", lambda: inputs)
    restarted = _build_store(tmp_path, curation_path=exercise_curation)
    try:
        assert calls == []
        assert restarted.catalog_conn.execute(
            "SELECT reviewed FROM foods WHERE id = ?", (STAPLE_ID,)
        ).fetchone()[0] == 1
    finally:
        restarted.catalog_conn.close()


def test_missing_shipped_inputs_are_skipped_with_a_warning(
        tmp_path, monkeypatch, stub_exercise_embeddings, caplog):
    inputs = _write_food_inputs(tmp_path / "inputs", reviewed=True)
    monkeypatch.setattr(seeding, "shipped_food_library_paths", lambda: FoodLibraryPaths(
        foods=tmp_path / "missing" / "foods.csv", portions=inputs.portions,
        curation=inputs.curation, recipes=inputs.recipes))
    with caplog.at_level(logging.WARNING):
        store = _build_store(tmp_path)
    try:
        # Startup never crashes on a partial deployment and does no rebuild work.
        assert store.catalog_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'foods'"
        ).fetchone() is None
        assert store.catalog_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'food_library_meta'"
        ).fetchone() is None
        assert any(
            record.levelno == logging.WARNING and "missing" in record.getMessage()
            for record in caplog.records
        )
        # No foods table is not a staples problem: there is nothing half-loaded.
        assert seeding.food_staples_status(store.catalog_conn) == "ok"
    finally:
        store.catalog_conn.close()


def test_food_staples_status_reports_missing_and_ok(tmp_path, monkeypatch, stub_exercise_embeddings):
    exercise_csv, exercise_curation = _write_exercise_inputs(tmp_path / "exercise-inputs")
    for reviewed, expected in ((False, "missing"), (True, "ok")):
        directory = tmp_path / ("reviewed" if reviewed else "unreviewed")
        inputs = _write_food_inputs(directory, reviewed=reviewed)
        store = _build_store(directory, curation_path=exercise_curation)
        try:
            _seed(store, exercise_csv, exercise_curation, inputs)
            assert seeding.food_staples_status(store.catalog_conn) == expected
        finally:
            store.catalog_conn.close()


def test_readyz_reports_missing_staples_but_stays_ready(
        tmp_path, monkeypatch, stub_exercise_embeddings, caplog):
    from svc import app as api

    inputs = _write_food_inputs(tmp_path, reviewed=False)
    exercise_csv, exercise_curation = _write_exercise_inputs(tmp_path / "exercise-inputs")
    store = _build_store(tmp_path, curation_path=exercise_curation)
    try:
        _seed(store, exercise_csv, exercise_curation, inputs)
        monkeypatch.setattr(api, "storage_status", lambda: (True, "ok"))
        monkeypatch.setitem(api._ready, "model", True)
        monkeypatch.setitem(api._ready, "catalog", True)
        monkeypatch.setitem(api._ready, "draining", False)
        monkeypatch.setitem(api._ready, "food_staples", "ok")
        with caplog.at_level(logging.WARNING, logger="svc.app"):
            api.record_food_staples_readiness(store)
        status, details = api.readiness_snapshot()
        assert details["food_staples"] == "missing"
        # A missing staple never fails deploy readiness; it only explains why
        # planned meals stay unavailable for Players.
        assert status == "ready"
        assert any("staples" in record.getMessage() for record in caplog.records)
    finally:
        store.catalog_conn.close()


def test_readyz_reports_ok_when_reviewed_staples_exist(tmp_path, monkeypatch, stub_exercise_embeddings):
    from svc import app as api

    inputs = _write_food_inputs(tmp_path, reviewed=True)
    exercise_csv, exercise_curation = _write_exercise_inputs(tmp_path / "exercise-inputs")
    store = _build_store(tmp_path, curation_path=exercise_curation)
    try:
        _seed(store, exercise_csv, exercise_curation, inputs)
        monkeypatch.setattr(api, "storage_status", lambda: (True, "ok"))
        monkeypatch.setitem(api._ready, "model", True)
        monkeypatch.setitem(api._ready, "catalog", True)
        monkeypatch.setitem(api._ready, "draining", False)
        monkeypatch.setitem(api._ready, "food_staples", "ok")
        api.record_food_staples_readiness(store)
        status, details = api.readiness_snapshot()
        assert details["food_staples"] == "ok"
        assert status == "ready"
    finally:
        store.catalog_conn.close()
