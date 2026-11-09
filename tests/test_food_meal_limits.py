"""Per-meal Staple limits survive curation, catalog upgrades and food lookups."""

import sqlite3
from contextlib import closing

import pytest

from database.food_library.builder import build_food_library
from database.food_library.seeding import FoodLibraryPaths, seed_food_library
from tests.test_food_library_builder import _csv


def _curate(paths, **overrides):
    row = dict(id="123", staple_roles="carb", reviewed="true", min_grams="", max_grams="")
    row.update(overrides)
    _csv(paths.curation, list(row), [row])


@pytest.fixture
def meal_limit_paths(tmp_path):
    paths = FoodLibraryPaths(*(tmp_path / name for name in (
        "foods.csv", "portions.csv", "curation.csv", "recipes.csv",
    )))
    _csv(paths.foods, ["id", "source", "name", "category", "energy_kcal"], [
        dict(id="123", source="sr_legacy", name="Rice, cooked", category="Grains", energy_kcal="100"),
    ])
    _csv(paths.portions, ["food_id", "label", "gram_weight"], [])
    _curate(paths)
    _csv(paths.recipes, ["id", "display_name", "ingredient_fdc_id", "grams"], [
        dict(id="rice-dish", display_name="Rice dish", ingredient_fdc_id="123", grams="100"),
    ])
    return paths


@pytest.mark.parametrize(("min_grams", "max_grams", "expected"), [
    ("", "", (None, None)),
    ("  ", " ", (None, None)),
    ("75.5", "300", (75.5, 300.0)),
    ("100", "100", (100.0, 100.0)),
    ("75", "", (75.0, None)),
    ("", "300", (None, 300.0)),
])
def test_builder_parses_optional_meal_limits(meal_limit_paths, min_grams, max_grams, expected):
    paths = meal_limit_paths
    _curate(paths, min_grams=min_grams, max_grams=max_grams)
    rows = build_food_library(paths.foods, paths.portions, paths.curation, paths.recipes)
    rice = next(row for row in rows if row["id"] == "123")
    assert (rice["min_grams"], rice["max_grams"]) == expected


@pytest.mark.parametrize(("overrides", "message"), [
    ({"min_grams": "301", "max_grams": "300"}, "min_grams must be <= max_grams"),
    ({"min_grams": "10", "staple_roles": ""}, "meal limits require Staple roles"),
    ({"max_grams": "10", "staple_roles": " | ; "}, "meal limits require Staple roles"),
    ({"min_grams": "0"}, "min_grams must be a finite number > 0"),
    ({"min_grams": "-1"}, "min_grams must be a finite number > 0"),
    ({"max_grams": "0"}, "max_grams must be a finite number > 0"),
    ({"max_grams": "-1"}, "max_grams must be a finite number > 0"),
    ({"min_grams": "NaN"}, "min_grams must be a finite number > 0"),
    ({"max_grams": "nan"}, "max_grams must be a finite number > 0"),
    ({"min_grams": "inf"}, "min_grams must be a finite number > 0"),
    ({"max_grams": "-inf"}, "max_grams must be a finite number > 0"),
    ({"max_grams": "1e999"}, "max_grams must be a finite number > 0"),
    ({"min_grams": "many"}, "min_grams must be a finite number > 0"),
])
def test_builder_rejects_invalid_limits_with_row_id(meal_limit_paths, overrides, message):
    paths = meal_limit_paths
    _curate(paths, **overrides)
    with pytest.raises(ValueError, match=f"Food curation row '123': {message}"):
        build_food_library(paths.foods, paths.portions, paths.curation, paths.recipes)


def test_empty_limits_are_allowed_without_staple_roles(meal_limit_paths):
    paths = meal_limit_paths
    _curate(paths, staple_roles="")
    rows = build_food_library(paths.foods, paths.portions, paths.curation, paths.recipes)
    assert all(row["min_grams"] is None and row["max_grams"] is None for row in rows)


def test_limits_are_validated_even_for_curation_rows_missing_from_source(meal_limit_paths):
    paths = meal_limit_paths
    _curate(paths, id="missing", min_grams="0")
    with pytest.raises(ValueError, match="Food curation row 'missing': min_grams"):
        build_food_library(paths.foods, paths.portions, paths.curation, paths.recipes)


def _open_catalog(path):
    from database.database_manager import DatabaseManager

    return DatabaseManager(catalog_path=path, ledgers_dir=path.parent / "users",
                           backups_dir=path.parent / "backups")


def test_seeding_round_trips_limits_through_catalog_lookups(tmp_path, meal_limit_paths):
    paths = meal_limit_paths
    _curate(paths, min_grams="75.5", max_grams="300")
    db = _open_catalog(tmp_path / "catalog.db")
    try:
        seed_food_library(db.catalog_conn, paths)
        rice = db.get_food_library_food("123")
        assert (rice["min_grams"], rice["max_grams"]) == (75.5, 300.0)
        found = db.search_food_library("rice")
        assert (found[0]["min_grams"], found[0]["max_grams"]) == (75.5, 300.0)
        recipe = db.get_food_library_food("mayos:rice-dish")
        assert recipe["min_grams"] is None and recipe["max_grams"] is None

        _curate(paths, min_grams="", max_grams="250")
        seed_food_library(db.catalog_conn, paths)
        updated = db.get_food_library_food("123")
        assert (updated["min_grams"], updated["max_grams"]) == (None, 250.0)
    finally:
        db.catalog_conn.close()
        db.deletions_conn.close()


@pytest.fixture
def legacy_catalog(tmp_path):
    path = tmp_path / "catalog.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("""CREATE TABLE foods (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, source_name TEXT NOT NULL,
            arabic_name TEXT, nutrients_json TEXT NOT NULL, portions_json TEXT NOT NULL,
            aliases_en_json TEXT NOT NULL, aliases_ar_json TEXT NOT NULL,
            staple_roles_json TEXT NOT NULL, hidden INTEGER NOT NULL,
            reviewed INTEGER NOT NULL, portion_label TEXT, portion_grams REAL,
            ingredients_json TEXT
        )""")
        connection.execute("""INSERT INTO foods VALUES (
            '123', 'Legacy rice', 'Rice, cooked', NULL, '{}', '[]', '[]', '[]',
            '["carb"]', 0, 1, NULL, NULL, '[]'
        )""")
        connection.commit()
    return path


def test_seeding_upgrades_legacy_catalog_before_upsert(legacy_catalog, meal_limit_paths):
    _curate(meal_limit_paths, min_grams="80", max_grams="250")
    with closing(sqlite3.connect(legacy_catalog)) as connection:
        seed_food_library(connection, meal_limit_paths)
        seed_food_library(connection, meal_limit_paths)
        row = connection.execute("SELECT name, min_grams, max_grams FROM foods WHERE id='123'").fetchone()
        assert row == ("Rice, cooked", 80.0, 250.0)


def test_startup_upgrades_legacy_catalog_without_reseeding(legacy_catalog):
    db = _open_catalog(legacy_catalog)
    try:
        db.create_catalog_schema()
        rice = db.get_food_library_food("123")
        assert rice["name"] == "Legacy rice"
        assert rice["min_grams"] is None and rice["max_grams"] is None
    finally:
        db.catalog_conn.close()
        db.deletions_conn.close()
