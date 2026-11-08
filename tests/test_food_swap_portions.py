"""Food swap portions follow the shared practical-unit rules."""

import pytest

from core.food_swap import swap_meal


@pytest.mark.parametrize("name,grams,portion,expected", [
    ("Areesh", 134, {}, 130),
    ("Egg", 78, {}, 100),
    ("Baladi", 130, {"portion_label": "baladi loaf", "portion_grams": 90}, 135),
    ("Local", 65, {"portion_label": "cup", "portion_grams": 40}, 80),
])
def test_replacement_uses_closest_practical_portion(name, grams, portion, expected):
    nutrients = {"energy_kcal": 120, "protein_g": 30, "carbohydrate_g": 0, "fat_g": 0}
    original = {"id": "before", "role": "protein", "grams": grams, "nutrients_per_100g": nutrients}
    replacement = {"id": "after", "name": name, "nutrients": nutrients, **portion}
    meal = {"slot": "breakfast", "foods": [original]}
    swapped = swap_meal(meal, "protein", replacement)
    assert swapped["foods"][0]["grams"] == expected
    assert swapped["foods"][0]["swapped"]
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
