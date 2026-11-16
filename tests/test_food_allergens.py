"""Reviewed allergen metadata survives catalog builds without changing name review."""

import csv

import pytest

from core.meal_setup import ALLERGENS
from database.food_library.builder import ALLERGEN_PATH, CURATION_PATH, RECIPE_PATH, NUTRIENTS, build_food_library
from database.food_library.seeding import FoodLibraryPaths, seed_food_library
from tests.test_food_log_api import food_api  # noqa: F401
from tests.test_food_library_builder import _csv
from tests.test_nutrition_api import api  # noqa: F401


def _paths(tmp_path, reviewed):
    paths = FoodLibraryPaths(*(tmp_path / name for name in (
        "foods.csv", "portions.csv", "curation.csv", "recipes.csv", "allergens.csv")))
    _csv(paths.foods, ["id", "name", "category", *NUTRIENTS], [
        {"id": "egg", "name": "Egg", "category": "Dairy and Egg Products", **dict.fromkeys(NUTRIENTS, 1)},
        {"id": "chicken", "name": "Chicken", "category": "Poultry Products", **dict.fromkeys(NUTRIENTS, 2)},
    ])
    _csv(paths.portions, ["food_id", "label", "gram_weight"], [])
    _csv(paths.curation, ["id", "display_name", "reviewed"], [
        {"id": "egg", "display_name": "Reviewed egg name", "reviewed": "true"},
    ])
    _csv(paths.recipes, ["id", "display_name", "ingredient_fdc_id", "grams", "reviewed"], [
        {"id": "dish", "display_name": "Dish", "ingredient_fdc_id": "egg", "grams": "50", "reviewed": "false"},
        {"id": "dish", "display_name": "Dish", "ingredient_fdc_id": "chicken", "grams": "50", "reviewed": "false"},
    ])
    _csv(paths.allergens, ["id", "allergens", "reviewed"], [
        {"id": "egg", "allergens": "eggs;milk", "reviewed": reviewed},
        {"id": "mayos:dish", "allergens": "eggs", "reviewed": reviewed},
    ])
    return paths


@pytest.mark.parametrize("reviewed", ["false", "true"])
def test_builder_and_reseed_preserve_categories_and_independent_allergen_review(food_api, tmp_path, reviewed):
    _client, db, _headers, _today = food_api
    paths = _paths(tmp_path, reviewed)
    built = {food["id"]: food for food in build_food_library(
        paths.foods, paths.portions, paths.curation, paths.recipes, paths.allergens)}
    assert built["egg"]["allergens"] == ["eggs", "milk"]
    assert built["egg"]["allergens_reviewed"] is (reviewed == "true")
    assert built["egg"]["vegetarian"] is True
    assert built["chicken"]["vegetarian"] is False
    assert built["mayos:dish"]["vegetarian"] is False
    with db.catalog_locked() as connection:
        seed_food_library(connection, paths)
    egg = db.get_food_library_food("egg")
    assert egg["category"] == "Dairy and Egg Products"
    assert egg["name"] == "Reviewed egg name"
    assert egg["allergens"] == (["eggs", "milk"] if reviewed == "true" else [])
    assert egg["allergens_reviewed"] is (reviewed == "true")
    dish = db.get_food_library_food("mayos:dish")
    assert dish["vegetarian"] is False
    assert dish["reviewed"] is False
    assert dish["allergens"] == (["eggs"] if reviewed == "true" else [])


@pytest.mark.parametrize(("tags", "message"), [("gluten", "unknown allergen"), ("milk;walnuts", "unknown allergen")])
def test_builder_rejects_tags_outside_fixed_list(tmp_path, tags, message):
    paths = _paths(tmp_path, "false")
    _csv(paths.allergens, ["id", "allergens", "reviewed"], [{"id": "egg", "allergens": tags, "reviewed": "true"}])
    with pytest.raises(ValueError, match=message):
        build_food_library(paths.foods, paths.portions, paths.curation, paths.recipes, paths.allergens)


def test_tracked_allergen_annotations_use_known_curated_or_recipe_ids():
    def rows(path):
        with path.open(encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

    annotations = rows(ALLERGEN_PATH)
    known = {food["id"] for food in rows(CURATION_PATH)}
    known.update(f"mayos:{food['id']}" for food in rows(RECIPE_PATH))
    ids = [food["id"] for food in annotations]
    assert len(ids) == len(set(ids))
    assert set(ids) <= known
    assert all(set(food["allergens"].split(";")) - {""} <= set(ALLERGENS) for food in annotations)
