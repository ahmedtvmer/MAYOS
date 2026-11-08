"""Table-driven tests of the pure generator, using reviewed fixture Staples."""

from copy import deepcopy
from dataclasses import replace

import pytest

from core.meal_generator import MealGenerationInput, generate_meals, portion_step
from core.meal_setup import MEAL_LAYOUTS


def _food(food_id, role, protein=0, carbs=0, fat=0, **curation):
    return {"id": food_id, "name": food_id, "reviewed": True, "vegetarian": True,
            "allergens": [], "allergens_reviewed": True, "staple_roles": [role],
            "portion_label": None, "portion_grams": None,
            "nutrients": {"energy_kcal": 4 * protein + 4 * carbs + 9 * fat,
                          "protein_g": protein, "carbohydrate_g": carbs, "fat_g": fat}, **curation}


def _request(count=3, time="evening", training=False):
    return MealGenerationInput(
        targets={"calories": 2610, "protein_g": 150, "carbs_g": 300, "fat_g": 90},
        setup={"meal_count": count, "training_time": time,
               "restrictions": {"allergies": [], "dislikes": [], "vegetarian": False}},
        training_day=training, staples=[_food("protein", "protein", protein=30),
                                      _food("carb", "carb", carbs=50),
                                      _food("fat", "vegetable_fat", fat=100,
                                            portion_label="local portion", portion_grams=1)],
    )


@pytest.mark.parametrize("count", [3, 4, 5])
@pytest.mark.parametrize("time", ["morning", "afternoon", "evening"])
@pytest.mark.parametrize("training", [False, True])
def test_layouts_timing_rounding_and_all_nutrients_meet_slot_and_day_limits(count, time, training):
    request = _request(count, time, training)
    untouched = deepcopy(request)
    generated = generate_meals(request)
    assert generated["status"] == "ready"
    assert [meal["slot"] for meal in generated["meals"]] == list(MEAL_LAYOUTS[count])
    for meal in generated["meals"]:
        assert meal["targets"]["protein_g"] == pytest.approx(150 / count)
        assert meal["targets"]["calories"] == pytest.approx(2610 / count)
        for key, target in meal["targets"].items():
            assert target * .95 - 1e-8 <= meal["totals"][key] <= target * 1.05 + 1e-8
        for food, staple in zip(meal["foods"], request.staples):
            assert food["grams"] % portion_step(staple) == pytest.approx(0)
    for key, target in request.targets.items():
        assert target * .95 <= generated["totals"][key] <= target * 1.05
    assert generate_meals(request) == generated
    assert request == untouched


@pytest.mark.parametrize(("count", "time", "higher"), [
    (3, "morning", {"breakfast", "lunch"}),
    (4, "afternoon", {"lunch", "afternoon_snack"}),
    (5, "evening", {"afternoon_snack", "dinner"}),
])
def test_training_carb_shift_brackets_usual_training_time(count, time, higher):
    meals = generate_meals(_request(count, time, True))["meals"]
    near = [meal for meal in meals if meal["slot"] in higher]
    far = [meal for meal in meals if meal["slot"] not in higher]
    assert min(meal["totals"]["carbs_g"] for meal in near) > max(meal["totals"]["carbs_g"] for meal in far)
    assert max(meal["targets"]["fat_g"] for meal in near) < min(meal["targets"]["fat_g"] for meal in far)


def test_foods_are_selected_from_the_correct_meal_type_list():
    request = _request(5)
    protein = request.staples.pop(0)
    request.staples[:0] = [{**protein, "id": meal_type, "staple_roles": [f"{meal_type}_protein"]}
                          for meal_type in ("main", "snack", "breakfast")]
    generated = generate_meals(request)
    assert [meal["foods"][0]["id"] for meal in generated["meals"]] == [
        "breakfast", "snack", "main", "snack", "main"]


def test_whole_eggs_half_loaves_and_local_portions_are_solved_together():
    request = replace(_request(), targets={"calories": 2655, "protein_g": 90, "carbs_g": 337.5, "fat_g": 105},
        staples=[_food("Boiled egg", "protein", protein=12, fat=10, portion_label="large egg", portion_grams=50),
                 _food("Baladi bread", "carb", carbs=50, portion_label="loaf", portion_grams=90),
                 _food("Oil", "vegetable_fat", fat=100)])
    generated = generate_meals(request)
    assert generated["status"] == "ready"
    for meal in generated["meals"]:
        assert [food["grams"] for food in meal["foods"]] == [250, 225, 10]


@pytest.mark.parametrize(("name", "label", "grams", "expected"), [
    ("Egg, whole, raw", None, None, 50), ("Boiled eggs", None, None, 50),
    ("Egg white", None, None, 10), ("Eggplant", None, None, 10),
    ("Baladi bread", "loaf", 90, 45), ("Ful", "bowl", 200, 200),
    ("Rice", None, None, 10),
])
def test_food_units_distinguish_whole_eggs_loaves_local_portions_and_grams(name, label, grams, expected):
    assert portion_step({"name": name, "portion_label": label, "portion_grams": grams}) == expected


@pytest.mark.parametrize(("restriction", "draft", "expected"), [
    ({"allergies": ["milk"]}, False, "allowed"),
    ({"allergies": ["milk"]}, True, "first"),
    ({"vegetarian": True}, False, "allowed"),
    ({"dislikes": ["first"]}, False, "allowed"),
    ({}, False, "first"),
])
def test_selection_uses_order_and_restrictions_with_reviewed_allergens_only(restriction, draft, expected):
    request = _request()
    first = {**request.staples[0], "id": "first", "vegetarian": False,
             "allergens": ["milk"], "allergens_reviewed": not draft}
    allowed = {**request.staples[0], "id": "allowed"}
    request.staples[:1] = [{**first, "id": "unreviewed", "reviewed": False}, first, allowed]
    request.setup["restrictions"].update(restriction)
    generated = generate_meals(request)
    assert generated["status"] == "ready"
    assert {meal["foods"][0]["id"] for meal in generated["meals"]} == {expected}


@pytest.mark.parametrize("case", ["empty", "unreviewed", "missing_role", "zero", "unknown_nutrient"])
def test_missing_reviewed_roles_or_invalid_portions_never_return_partial_meals(case):
    request = _request()
    if case == "empty":
        request.staples.clear()
    elif case == "unreviewed":
        for food in request.staples:
            food["reviewed"] = False
    elif case == "missing_role":
        request.staples.pop()
    elif case == "unknown_nutrient":
        request.staples[0]["nutrients"]["fat_g"] = None
    else:
        request.targets.update(dict.fromkeys(request.targets, 0))
    generated = generate_meals(request)
    assert generated["status"] == "unavailable"
    assert generated["meals"] == []


@pytest.mark.parametrize("role_index", [0, 1, 2])
def test_impractical_first_staple_tries_the_next_allowed_food_in_role_order(role_index):
    request = _request()
    original = request.staples[role_index]
    request.staples[role_index:role_index + 1] = [
        {**original, "id": "too_large", "portion_grams": 10000},
        {**original, "id": "unreviewed", "reviewed": False},
        {**original, "id": "hidden", "hidden": True},
        {**original, "id": "allergic", "allergens": ["milk"]},
        {**original, "id": "meat", "vegetarian": False},
        {**original, "id": "disliked"},
        {**original, "id": "next_allowed"},
        {**original, "id": "later_allowed"},
    ]
    request.setup["restrictions"].update(allergies=["milk"], vegetarian=True, dislikes=["disliked"])
    generated = generate_meals(request)
    assert generated["status"] == "ready"
    assert {meal["foods"][role_index]["id"] for meal in generated["meals"]} == {"next_allowed"}
    for meal in generated["meals"]:
        for key, target in meal["targets"].items():
            assert target * .95 <= meal["totals"][key] <= target * 1.05


def test_small_portion_units_do_not_skip_a_feasible_first_staple():
    request = _request()
    request.staples[-1]["portion_grams"] = .001
    request.staples.append(_food("later_fat", "vegetable_fat", fat=100, portion_grams=1))
    generated = generate_meals(request)
    assert generated["status"] == "ready"
    for meal in generated["meals"]:
        assert meal["foods"][2]["id"] == "fat"
        assert 28.5 <= meal["foods"][2]["grams"] <= 31.5


def test_no_combination_fits_returns_the_closest_meal_with_each_slots_deviation():
    request = _request()
    request.staples[0]["portion_grams"] = 100
    request.staples.insert(1, _food("closer", "protein", protein=27.5, portion_grams=100))
    generated = generate_meals(request)
    assert generated["status"] == "ready"
    assert generate_meals(request) == generated
    for meal in generated["meals"]:
        assert meal["foods"][0]["id"] == "closer"
        assert meal["foods"][0]["grams"] == 200
        assert meal["totals"]["protein_g"] == 55
        assert meal["target_deviation"]["protein_g"] == 5
        for key, target in meal["targets"].items():
            assert meal["target_deviation"][key] == pytest.approx(meal["totals"][key] - target)


@pytest.mark.parametrize("revoked", [False, True])
def test_explicit_swap_stays_pinned_for_approximation_unless_its_review_is_revoked(revoked):
    request = _request()
    request.swap_foods["chosen"] = {**request.staples[0], "id": "chosen",
                                     "reviewed": not revoked, "portion_grams": 100}
    request.swaps["breakfast"] = {"protein": "chosen"}
    generated = generate_meals(request)
    breakfast = generated["meals"][0]
    assert breakfast["foods"][0]["id"] == ("protein" if revoked else "chosen")
    if not revoked:
        assert abs(breakfast["target_deviation"]["protein_g"]) > breakfast["targets"]["protein_g"] * .05


@pytest.mark.parametrize(("restriction", "expected"), [
    ({}, "swap"), ({"dislikes": ["swap"]}, "swap"),
    ({"allergies": ["milk"]}, "protein"), ({"vegetarian": True}, "protein"),
])
def test_regeneration_keeps_explicit_allowed_swaps_but_removes_strictly_restricted_ones(restriction, expected):
    request = _request()
    request.staples.append({**request.staples[0], "id": "swap", "allergens": ["milk"], "vegetarian": False})
    request.setup["restrictions"].update(restriction)
    request.swaps["breakfast"] = {"protein": "swap"}
    assert generate_meals(request)["meals"][0]["foods"][0]["id"] == expected
