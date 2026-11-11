"""Build deterministic Food library rows from USDA sources and MAYOS curation."""

import csv
import math
import re
from pathlib import Path

from core.meal_setup import ALLERGENS, vegetarian_category
from database.shared import BASE_DIR

FOOD_PATH = BASE_DIR / "data" / "food_library.csv"
PORTION_PATH = BASE_DIR / "data" / "food_portions.csv"
CURATION_PATH = BASE_DIR / "data" / "food_curation.csv"
RECIPE_PATH = BASE_DIR / "data" / "food_recipes.csv"
ALLERGEN_PATH = BASE_DIR / "data" / "food_allergens.csv"
NUTRIENTS = (
    "energy_kcal", "protein_g", "carbohydrate_g", "fat_g", "fiber_g",
    "sugars_g", "saturated_fat_g", "sodium_mg",
)
_EXCLUDED_BRAND_TOKENS = {"NFS", "NS", "USDA", "DHA", "ARA", "USA", "UHT"}
_BRAND_TOKEN = re.compile(r"(?<![A-Za-z])[A-Z][A-Z'&-]*[A-Z](?![A-Za-z])")
_HALAL_EXCEPTIONS = re.compile(r"\b(?:turkey|beef|chicken|meatless|soy)\b", re.I)
_HALAL_NAME_TERMS = re.compile(r"\b(?:pork|ham|bacon|pepperoni|salami|prosciutto|lard|wine|beer|liquor|alcoholic)\b", re.I)
_FAST_FOOD_NAME = re.compile(r"\bfrom fast food\b|\brestaurant\b", re.I)


def _rows(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _number(value):
    return float(value) if value not in (None, "") else None


def _text(value):
    return (value or "").strip()


def _list(value):
    return [part.strip() for part in (value or "").replace(";", "|").split("|") if part.strip()]


def _meal_limit(fields, food_id, column):
    raw_grams = _text(fields.get(column))
    if not raw_grams:
        return None
    try:
        grams = float(raw_grams)
    except ValueError as error:
        raise ValueError(f"Food curation row {food_id!r}: {column} must be a finite number > 0") from error
    if not math.isfinite(grams) or grams <= 0:
        raise ValueError(f"Food curation row {food_id!r}: {column} must be a finite number > 0")
    return grams


def _meal_limits(fields, food_id):
    min_grams = _meal_limit(fields, food_id, "min_grams")
    max_grams = _meal_limit(fields, food_id, "max_grams")
    if min_grams is not None or max_grams is not None:
        if not _list(fields.get("staple_roles")):
            raise ValueError(f"Food curation row {food_id!r}: meal limits require Staple roles")
    if min_grams is not None and max_grams is not None and min_grams > max_grams:
        raise ValueError(f"Food curation row {food_id!r}: min_grams must be <= max_grams")
    return {"min_grams": min_grams, "max_grams": max_grams}


def _is_branded(name):
    return any(
        sum(character.isalpha() for character in token) >= 3
        and token not in _EXCLUDED_BRAND_TOKENS
        for token in _BRAND_TOKEN.findall(name)
    )


def _default_hidden(row):
    name = row["name"]
    folded_name = name.casefold()
    category = (row.get("category") or "").casefold()
    source = (row.get("source") or "").casefold()
    halal_exception = bool(_HALAL_EXCEPTIONS.search(name))
    alcohol_exemption = any(term in folded_name for term in ("nonalcoholic", "root beer", "vinegar"))
    halal_categories = {"beer", "wine", "liquor and cocktails", "pork", "pork products", "bacon"}
    fast_food_categories = {"fast foods", "restaurant foods"}
    category_hidden = (
        category in halal_categories and not halal_exception
    ) or category in fast_food_categories
    if category in {"beer", "wine", "liquor and cocktails"} and alcohol_exemption:
        category_hidden = False
    name_hidden = False
    if not alcohol_exemption:
        name_hidden = bool(_HALAL_NAME_TERMS.search(name)) or "ns as to fat" in folded_name
        if name_hidden and re.search(r"\bbacon\b", name, re.I) and halal_exception:
            name_hidden = False
    baby_hidden = category.startswith("baby") or "formula" in category or bool(
        re.match(r"^infant formula\b", name, re.I)
    )
    return (
        source in {"branded", "brand"}
        or _is_branded(name)
        or category_hidden
        or name_hidden
        or baby_hidden
        or bool(_FAST_FOOD_NAME.search(name))
    )

def _curated_food(source, curation, portions):
    food_id = str(source["id"])
    fields = curation.get(food_id, {})
    hidden_value = _text(fields.get("hidden")).casefold()
    if hidden_value not in {"", "true", "false"}:
        raise ValueError(f"Food curation row {food_id!r} has invalid hidden value {hidden_value!r}")
    hidden = hidden_value == "true" if hidden_value else _default_hidden(source)
    row = {
        "id": food_id,
        "category": _text(source.get("category")),
        "vegetarian": vegetarian_category(source.get("category")),
        "source_name": source["name"],
        "name": _text(fields.get("display_name")) or source["name"],
        "arabic_name": _text(fields.get("arabic_name")) or None,
        "aliases_en": _list(fields.get("aliases_en")),
        "aliases_ar": _list(fields.get("aliases_ar")),
        "hidden": hidden,
        "staple_roles": _list(fields.get("staple_roles")),
        "reviewed": _text(fields.get("reviewed")).casefold() == "true",
        "portions": sorted(portions.get(food_id, []), key=lambda part: (part["label"], part["grams"] or 0)),
        "portion_label": _text(fields.get("portion_label")) or None,
        "portion_grams": _number(fields.get("portion_grams")),
        "min_grams": fields.get("min_grams"),
        "max_grams": fields.get("max_grams"),
    }
    row.update({nutrient: _number(source.get(nutrient)) for nutrient in NUTRIENTS})
    return row


def _new_recipe(source, key):
    return {
        "id": f"mayos:{key}",
        "category": "MAYOS recipe",
        "source_name": _text(source.get("display_name")),
        "name": _text(source.get("display_name")),
        "arabic_name": _text(source.get("arabic_name")) or None,
        "aliases_en": [], "aliases_ar": [], "hidden": False,
        "staple_roles": [], "reviewed": _text(source.get("reviewed")).casefold() == "true",
        "portions": [], "portion_label": None, "portion_grams": None,
        "min_grams": None, "max_grams": None,
        "ingredients": [],
    }


def _append_recipe_ingredient(row, source):
    grams = float(source["grams"])
    if grams <= 0:
        raise ValueError(f"Recipe {row['id']!r} has non-positive ingredient grams")
    cooked_yield = _number(source.get("cooked_yield_g"))
    if cooked_yield is not None and cooked_yield <= 0:
        raise ValueError(f"Recipe {row['id']!r} has non-positive cooked yield")
    reviewed = _text(source.get("reviewed")).casefold() == "true"
    if row["ingredients"] and reviewed != row["reviewed"]:
        raise ValueError(f"Recipe {row['id']!r} has inconsistent reviewed flags")
    row["reviewed"] = reviewed
    row["ingredients"].append((_text(source["ingredient_fdc_id"]), grams, cooked_yield))


def _group_recipes(recipe_rows):
    recipes = {}
    for source in recipe_rows:
        key = _text(source["id"])
        if not key:
            raise ValueError("Recipe id must not be empty")
        row = recipes.get(key)
        if row is None:
            row = recipes[key] = _new_recipe(source, key)
        if row["name"] != _text(source.get("display_name")) or row["arabic_name"] != (_text(source.get("arabic_name")) or None):
            raise ValueError(f"Recipe {key!r} has inconsistent names across ingredient rows")
        _append_recipe_ingredient(row, source)
    return recipes

def _recipe_nutrients(row, source_by_id):
    yields = {yield_grams for _, _, yield_grams in row["ingredients"] if yield_grams is not None}
    if len(yields) > 1:
        raise ValueError(f"Recipe {row['id']!r} has inconsistent cooked yields")
    cooked_yield = next(iter(yields), None)
    weight = cooked_yield if cooked_yield is not None else sum(
        grams for _, grams, _ in row["ingredients"]
    )
    if weight <= 0:
        raise ValueError(f"Recipe {row['id']!r} has no positive cooked yield")
    for nutrient in NUTRIENTS:
        values = [source_by_id[fdc_id][nutrient] for fdc_id, _, _ in row["ingredients"]]
        row[nutrient] = None if any(value is None for value in values) else sum(
            source_by_id[fdc_id][nutrient] * grams / 100
            for fdc_id, grams, _ in row["ingredients"]
        ) * 100 / weight
    row["ingredients"] = [
        {"food_id": food_id, "grams": grams}
        for food_id, grams, _ in row["ingredients"]
    ]


def build_food_library(
    food_path=FOOD_PATH,
    portion_path=PORTION_PATH,
    curation_path=CURATION_PATH,
    recipe_path=RECIPE_PATH,
    allergen_path=ALLERGEN_PATH,
):
    foods, portions, curation_rows, recipe_rows = map(
        _rows, (food_path, portion_path, curation_path, recipe_path)
    )
    curation = {}
    for row in curation_rows:
        food_id = _text(row["id"])
        if food_id in curation:
            raise ValueError(f"Duplicate food curation id {food_id!r}")
        row.update(_meal_limits(row, food_id))
        curation[food_id] = row
    portions_by_id = {}
    for portion in portions:
        portions_by_id.setdefault(portion["food_id"], []).append({
            "label": portion["label"], "grams": _number(portion["gram_weight"]),
        })
    rows = [_curated_food(source, curation, portions_by_id) for source in foods]
    source_by_id = {row["id"]: row for row in rows}
    recipes = _group_recipes(recipe_rows)
    for recipe in recipes.values():
        for food_id, _, _ in recipe["ingredients"]:
            if food_id not in source_by_id:
                raise ValueError(f"Recipe {recipe['id']!r} references unknown FDC id {food_id!r}")
        _recipe_nutrients(recipe, source_by_id)
        recipe["vegetarian"] = all(source_by_id[part["food_id"]]["vegetarian"]
                                   for part in recipe["ingredients"])
    built_rows = sorted([*rows, *recipes.values()], key=lambda row: row["id"])
    annotations = _allergen_annotations(allergen_path)
    staple_order = {row["id"]: index for index, row in enumerate(curation_rows)}
    for row in built_rows:
        row["staple_order"] = staple_order.get(row["id"], len(curation_rows))
        row.update(annotations.get(row["id"], {"allergens": [], "allergens_reviewed": False}))
    return built_rows


def _allergen_annotations(path):
    annotations = {}
    for source in _rows(path):
        food_id = _text(source["id"])
        tags = _list(source.get("allergens"))
        reviewed = _text(source.get("reviewed")).casefold()
        if not food_id or food_id in annotations:
            raise ValueError(f"Empty or duplicate food allergen id {food_id!r}")
        if set(tags) - set(ALLERGENS):
            raise ValueError(f"Food {food_id!r} has unknown allergen tags")
        if reviewed not in {"", "true", "false"}:
            raise ValueError(f"Food {food_id!r} has invalid allergen reviewed flag")
        annotations[food_id] = {"allergens": list(dict.fromkeys(tags)),
                                "allergens_reviewed": reviewed == "true"}
    return annotations
