"""Food swap portions follow the shared practical-unit rules."""

import pytest

from core.food_swap import swap_meal


@pytest.mark.parametrize("name,grams,portion,expected", [
    ("Areesh", 134, {}, 125),
    ("Egg", 78, {}, 100),
    ("Baladi", 130, {"portion_label": "baladi loaf", "portion_grams": 90}, 135),
    ("Local", 65, {"portion_label": "cup", "portion_grams": 40}, 120),
])
def test_replacement_uses_closest_practical_portion(name, grams, portion, expected):
    nutrients = {"energy_kcal": 120, "protein_g": 30, "carbohydrate_g": 0, "fat_g": 0}
    original = {"id": "before", "role": "protein", "grams": grams, "nutrients_per_100g": nutrients}
    replacement = {"id": "after", "name": name, "nutrients": nutrients, **portion}
    meal = {"slot": "breakfast", "foods": [original], "targets": {"calories": 180, "protein_g": 45},
            "target_deviation": {"calories": 999, "protein_g": 999}}
    swapped = swap_meal(meal, "protein", replacement)
    assert swapped["foods"][0]["grams"] == expected
    assert swapped["foods"][0]["swapped"]
    assert swapped["target_deviation"] == {"calories": pytest.approx(expected * 1.2 - 180),
                                          "protein_g": pytest.approx(expected * .3 - 45)}
    assert meal["foods"] == [original]


def test_replacement_balances_meal_calories_and_protein_instead_of_matching_calories_alone():
    original = {"id": "before", "role": "protein", "grams": 100,
                "nutrients_per_100g": {"energy_kcal": 200, "protein_g": 30, "carbohydrate_g": 0, "fat_g": 0}}
    carb = {"id": "rice", "role": "carb", "grams": 200,
            "nutrients_per_100g": {"energy_kcal": 200, "protein_g": 1, "carbohydrate_g": 50, "fat_g": 0}}
    replacement = {"id": "after", "name": "New protein",
                   "nutrients": {"energy_kcal": 180, "protein_g": 30, "carbohydrate_g": 0, "fat_g": 0}}
    swapped = swap_meal({"foods": [original, carb]}, "protein", replacement)
    assert swapped["foods"][0]["grams"] == 100
    assert swapped["foods"][1] == carb
    assert swapped["totals"]["calories"] == 580
    assert swapped["totals"]["protein_g"] == 32


@pytest.mark.parametrize("name,role,portion,expected", [
    ("Chicken", "protein", {}, 250),
    ("Atlantic sardines in oil", "protein", {"category": "Finfish and Shellfish Products"}, 250),
    ("Cooked rice", "carb", {}, 300),
    ("Egg noodles, cooked", "carb", {"category": "Cereal Grains and Pasta"}, 300),
    ("Boiled egg", "protein", {"portion_grams": 50}, 200),
    ("White pita", "carb", {"portion_grams": 90}, 180),
    ("Banana", "carb", {"portion_grams": 120}, 240),
    ("Olive oil", "vegetable_fat", {}, 15),
    ("Tahini", "vegetable_fat", {}, 30),
    ("Zucchini", "vegetable_fat", {}, 300),
    ("Chicken", "protein", {"min_grams": 75, "max_grams": 125}, 125),
])
def test_swap_never_exceeds_category_or_curated_maximum_even_for_extreme_targets(name, role, portion, expected):
    nutrients = {"energy_kcal": 120, "protein_g": 30, "carbohydrate_g": 0, "fat_g": 0}
    meal = {"foods": [{"id": "before", "role": role, "grams": 10000, "nutrients_per_100g": nutrients}]}
    swapped = swap_meal(meal, role, {"id": "after", "name": name, "nutrients": nutrients, **portion})
    assert swapped["foods"][0]["grams"] == expected


def test_swap_refuses_an_override_interval_without_a_practical_step():
    nutrients = {"energy_kcal": 120, "protein_g": 30, "carbohydrate_g": 0, "fat_g": 0}
    meal = {"foods": [{"id": "before", "role": "protein", "grams": 150, "nutrients_per_100g": nutrients}]}
    with pytest.raises(ValueError, match="practical portion"):
        swap_meal(meal, "protein", {"id": "after", "name": "Chicken", "nutrients": nutrients,
                                     "min_grams": 101, "max_grams": 124})
