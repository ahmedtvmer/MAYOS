"""Table-driven tests of the pure generator, using reviewed fixture Staples."""

import json
from copy import deepcopy
from dataclasses import replace
from math import prod
from pathlib import Path
from random import Random
from time import perf_counter

import pytest

from core.meal_generator import MealGenerationInput, NUTRIENT_KEYS, ROLES, generate_meals, role_matches
from core.meal_portions import portion_amounts
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
                                      _food("Oil", "vegetable_fat", fat=100,
                                            portion_label="local portion", portion_grams=1)],
    )


@pytest.mark.parametrize("count", [2, 3, 4, 5])
@pytest.mark.parametrize("time", ["morning", "afternoon", "evening"])
@pytest.mark.parametrize("training", [False, True])
def test_layouts_targets_and_inputs_stay_deterministic(count, time, training):
    request = _request(count, time, training)
    untouched = deepcopy(request)
    generated = generate_meals(request)
    assert generated["status"] == "ready"
    assert [meal["slot"] for meal in generated["meals"]] == list(MEAL_LAYOUTS[count])
    for meal in generated["meals"]:
        assert len(meal["foods"]) == 3
        assert meal["targets"]["protein_g"] == pytest.approx(150 / count)
        assert meal["targets"]["calories"] == pytest.approx(2610 / count)
    assert sum(meal["targets"]["carbs_g"] for meal in generated["meals"]) == pytest.approx(300)
    assert sum(meal["targets"]["fat_g"] for meal in generated["meals"]) == pytest.approx(90)
    assert generate_meals(request) == generated
    assert request == untouched


@pytest.mark.parametrize(("count", "time", "higher"), [
    (3, "morning", {"breakfast", "lunch"}),
    (4, "afternoon", {"lunch", "afternoon_snack"}),
    (5, "evening", {"afternoon_snack", "dinner"}),
])
def test_training_carb_targets_bracket_usual_training_time(count, time, higher):
    meals = generate_meals(_request(count, time, True))["meals"]
    near = [meal for meal in meals if meal["slot"] in higher]
    far = [meal for meal in meals if meal["slot"] not in higher]
    assert min(meal["targets"]["carbs_g"] for meal in near) > max(meal["targets"]["carbs_g"] for meal in far)
    assert max(meal["targets"]["fat_g"] for meal in near) < min(meal["targets"]["fat_g"] for meal in far)


def test_foods_are_selected_from_the_correct_meal_type_list():
    request = _request(5)
    protein = request.staples.pop(0)
    request.staples[:0] = [{**protein, "id": meal_type, "staple_roles": [f"{meal_type}_protein"]}
                          for meal_type in ("main", "snack", "breakfast")]
    generated = generate_meals(request)
    assert [meal["foods"][0]["id"] for meal in generated["meals"]] == [
        "breakfast", "snack", "main", "snack", "main"]


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


@pytest.mark.parametrize("count", [2, 3, 4, 5])
def test_seeded_target_grid_never_breaks_food_limits_and_explains_day_gaps(count):
    random = Random(682)
    staples = [
        _food("Chicken", "protein", protein=30),
        _food("Boiled egg", "protein", protein=12, fat=10, portion_grams=50),
        _food("Rice", "carb", carbs=28),
        _food("White pita", "carb", carbs=50, portion_grams=90),
        _food("Banana", "carb", carbs=23, portion_grams=120),
        _food("Oil", "vegetable_fat", fat=100),
        _food("Tahini", "vegetable_fat", protein=17, carbs=21, fat=54),
        _food("Zucchini", "vegetable_fat", protein=1, carbs=3),
    ]
    expected = {"Chicken": (100, 250, 25), "Boiled egg": (100, 200, 25),
                "Rice": (100, 300, 25), "White pita": (45, 180, 45),
                "Banana": (120, 240, 60), "Oil": (5, 15, 5),
                "Tahini": (10, 30, 10), "Zucchini": (100, 300, 25)}
    for calories in range(1400, 3501, 300):
        protein, fat = random.randint(100, 190), calories * .25 / 9
        targets = {"calories": calories, "protein_g": protein,
                   "carbs_g": (calories - 4 * protein - 9 * fat) / 4, "fat_g": fat}
        generated = generate_meals(replace(_request(count), targets=targets, staples=staples))
        assert generated["status"] == "ready"
        for meal in generated["meals"]:
            assert len(meal["foods"]) == 3
            for food in meal["foods"]:
                lower, upper, step = expected[food["id"]]
                assert lower <= food["grams"] <= upper
                assert food["grams"] / step == pytest.approx(round(food["grams"] / step))
        outside = [key for key, tolerance in zip(targets, (.05, .05, .10, .10))
                   if abs(generated["totals"][key] - targets[key]) > targets[key] * tolerance + 1e-8]
        assert bool(generated["gap_note"]) == bool(outside)
        if outside:
            assert set(generated["gap_note"]) == {"en", "ar"}


@pytest.mark.parametrize("count", [2, 3, 4, 5])
def test_known_realistic_days_land_inside_all_four_day_tolerances(count):
    random = Random(682 + count)
    for _ in range(6):
        # Construct a feasible witness independently of the generator's search.
        protein_grams = sum(random.choice(range(100, 251, 25)) for _ in range(count))
        carb_grams = sum(random.choice(range(100, 301, 25)) for _ in range(count))
        oil_grams = sum(random.choice((5, 10, 15)) for _ in range(count))
        targets = {"protein_g": protein_grams * .3, "carbs_g": carb_grams * .5, "fat_g": oil_grams}
        targets["calories"] = 4 * targets["protein_g"] + 4 * targets["carbs_g"] + 9 * oil_grams
        request = replace(_request(count), targets=targets)
        generated = generate_meals(request)
        assert generated["status"] == "ready"
        assert generated["gap_note"] is None
        for key, tolerance in (("calories", .05), ("protein_g", .05), ("carbs_g", .10), ("fat_g", .10)):
            assert abs(generated["totals"][key] - targets[key]) <= targets[key] * tolerance + 1e-8


def test_complementary_meals_fit_the_day_even_when_slots_cannot_fit():
    request = replace(_request(), targets={"calories": 2470, "protein_g": 100, "carbs_g": 450, "fat_g": 30},
        staples=[_food("breakfast", "breakfast_protein", protein=20, min_grams=100, max_grams=100),
                 _food("main", "main_protein", protein=20, min_grams=200, max_grams=200),
                 _food("Rice", "carb", carbs=50, min_grams=300, max_grams=300),
                 _food("Oil", "vegetable_fat", fat=100, min_grams=10, max_grams=10)])
    generated = generate_meals(request)
    assert generated["totals"] == request.targets
    assert generated["gap_note"] is None
    assert all(abs(meal["target_deviation"]["protein_g"]) > meal["targets"]["protein_g"] * .05
               for meal in generated["meals"])


def test_better_food_in_the_shortlist_wins_instead_of_stopping_at_first_fit():
    request = replace(_request(), targets={"calories": 2310, "protein_g": 135, "carbs_g": 375, "fat_g": 30},
        staples=[_food("first", "protein", protein=29, min_grams=150, max_grams=150),
                 _food("exact", "protein", protein=30, min_grams=150, max_grams=150),
                 _food("Rice", "carb", carbs=50, min_grams=250, max_grams=250),
                 _food("Oil", "vegetable_fat", fat=100, min_grams=10, max_grams=10)])
    generated = generate_meals(request)
    assert generated["gap_note"] is None
    assert {meal["foods"][0]["id"] for meal in generated["meals"]} == {"exact"}


@pytest.mark.parametrize("portion_grams", [None, .001])
def test_synthetic_food_grid_generates_a_full_day_within_three_seconds(portion_grams):
    staples = []
    for index in range(12):
        staples.append(_food(f"protein-{index}", "protein", protein=12 + index,
                             fat=2 + index / 4))
        staples.append(_food(f"carb-{index}", "carb", carbs=35 + index * 2))
        staples.append(_food(f"vegetable-fat-{index}", "vegetable_fat",
                             protein=index / 10, fat=5 + index * 1.5))
    if portion_grams is not None:
        # #678: tiny curated steps must not expand the full portion grid.
        staples = [{**food, "portion_grams": portion_grams} for food in staples]
    request = replace(_request(training=True), staples=staples)

    started = perf_counter()
    generated = generate_meals(request)
    elapsed = perf_counter() - started

    assert elapsed < 3
    assert generated["status"] == "ready"
    assert len(generated["meals"]) == 3
    if portion_grams is not None:
        for meal in generated["meals"]:
            for food in meal["foods"]:
                assert 100 <= food["grams"] <= (250 if food["role"] == "protein" else 300)
                units = food["grams"] / portion_grams
                assert units == pytest.approx(round(units))


@pytest.fixture(scope="module")
def real_staples():
    from database.food_library.builder import build_food_library

    folder = Path(__file__).resolve().parents[1] / "data"
    paths = [folder / name for name in (
        "food_library.csv", "food_portions.csv", "food_curation.csv", "food_recipes.csv", "food_allergens.csv",
    )]
    missing = [str(path.relative_to(folder.parent)) for path in paths if not path.is_file()]
    if missing:
        pytest.skip("Real meal-generation benchmark needs local CSVs: " + ", ".join(missing))
    rows = build_food_library(*paths)
    return [{**row, "nutrients": {key: row[key] for key in NUTRIENT_KEYS}}
            for row in sorted(rows, key=lambda row: (row["staple_order"], row["id"]))
            if row["reviewed"] and not row["hidden"] and row["staple_roles"]]


@pytest.mark.parametrize(("count", "training"), [(2, False), (3, False), (3, True)])
def test_real_food_library_day_generates_within_two_seconds(real_staples, count, training, record_property):
    request = replace(_request(count, training=training), staples=real_staples,
                      targets={"calories": 2520, "protein_g": 150, "carbs_g": 300, "fat_g": 80})
    census = {}
    for slot in MEAL_LAYOUTS[count]:
        foods = [[{**food, "role": role} for food in real_staples if role_matches(food, slot, role)]
                 for role in ROLES]
        steps = [{food["id"]: len(portion_amounts(food)) for food in role} for role in foods]
        census[slot] = {"roles": ROLES, "foods_per_role": [len(role) for role in foods], "steps_per_food": steps,
                        "full_portion_combinations": prod(sum(role.values()) for role in steps)}
    record_property("unpruned_search_size", json.dumps(census, sort_keys=True))

    # CSV loading and the census are deliberately outside the per-day CPU work.
    started = perf_counter()
    generated = generate_meals(request)
    elapsed = perf_counter() - started

    assert generated["status"] == "ready"
    assert len(generated["meals"]) == count
    assert elapsed < 2, f"Real-library meal day took {elapsed:.3f}s (budget 2s)"


def test_normal_amounts_win_before_curation_order_for_equal_nutrient_fit():
    request = replace(_request(), targets={"calories": 1140, "protein_g": 90, "carbs_g": 150, "fat_g": 20},
        staples=[_food("first", "protein", protein=30, portion_grams=100, min_grams=100, max_grams=300),
                 _food("normal", "protein", protein=15, portion_grams=200, min_grams=100, max_grams=300),
                 _food("Rice", "carb", carbs=50, min_grams=100, max_grams=100),
                 _food("Oil", "vegetable_fat", fat=100, min_grams=5, max_grams=10)])
    generated = generate_meals(request)
    assert {meal["foods"][0]["id"] for meal in generated["meals"]} == {"normal"}
    assert all(meal["foods"][0]["grams"] == 200 for meal in generated["meals"])


@pytest.mark.parametrize(("targets", "english", "arabic"), [
    ({"calories": 1954, "protein_g": 106, "carbs_g": 300, "fat_g": 30},
     "About 120 kcal under and 15 g protein under. Add a snack or a bigger portion.",
     "تقريبًا: نقص 120 سعرة ونقص 15 غ بروتين. أضف وجبة خفيفة أو حصة أكبر."),
    ({"calories": 1830, "protein_g": 90, "carbs_g": 280, "fat_g": 28}, None, None),
    ({"calories": 1700, "protein_g": 80, "carbs_g": 300, "fat_g": 30},
     "About 130 kcal over and 10 g protein over. Try a smaller portion or a different food.",
     "تقريبًا: زيادة 130 سعرة وزيادة 10 غ بروتين. جرّب حصة أصغر أو طعامًا مختلفًا."),
    ({"calories": 1954, "protein_g": 80, "carbs_g": 300, "fat_g": 30},
     "About 120 kcal under and 10 g protein over. Try different foods or adjust portions.",
     "تقريبًا: نقص 120 سعرة وزيادة 10 غ بروتين. جرّب أطعمة مختلفة أو عدّل الحصص."),
])
def test_fixed_day_gaps_name_only_outside_nutrients_with_rounded_bilingual_advice(targets, english, arabic):
    request = replace(_request(), targets=targets,
        staples=[_food("Chicken", "protein", protein=30, min_grams=100, max_grams=100),
                 _food("Rice", "carb", carbs=50, min_grams=200, max_grams=200),
                 _food("Oil", "vegetable_fat", fat=100, min_grams=10, max_grams=10)])
    generated = generate_meals(request)
    assert generated["totals"] == {"calories": 1830, "protein_g": 90, "carbs_g": 300, "fat_g": 30}
    assert generated["gap_note"] == ({"en": english, "ar": arabic} if english else None)


@pytest.mark.parametrize(("name", "role", "portion", "expected"), [
    ("Boiled eggs", "protein", 50, {100, 125, 150, 175, 200}),
    ("White pita", "carb", 90, {45, 90, 135, 180}),
    ("Banana", "carb", 120, {120, 180, 240}),
    ("Whole-wheat bread", "carb", None, set(range(50, 201, 25))),
    ("Boiled egg", "protein", None, set(range(100, 201, 25))),
    ("Banana", "carb", None, set(range(150, 301, 25))),
    ("Chicken", "protein", 80, {160, 240}),
])
def test_household_portions_count_in_halves_and_uncurated_counted_foods_use_grams(name, role, portion, expected):
    request = _request()
    index = 0 if role == "protein" else 1
    request.staples[index] = _food(name, role, protein=30 if index == 0 else 0,
                                  carbs=50 if index == 1 else 0, portion_grams=portion)
    generated = generate_meals(request)
    assert generated["status"] == "ready"
    assert all(meal["foods"][index]["grams"] in expected for meal in generated["meals"])


@pytest.mark.parametrize(("bounds", "expected"), [
    ({"min_grams": 175}, {175, 200, 225, 250, 275, 300}),
    ({"max_grams": 125}, {100, 125}),
    ({"min_grams": 75, "max_grams": 75}, {75}),
    ({"min_grams": 101, "max_grams": 124}, set()),
])
def test_each_curated_bound_overrides_only_its_category_default(bounds, expected):
    request = _request()
    request.staples[1].update(bounds)
    generated = generate_meals(request)
    if expected:
        assert generated["status"] == "ready"
        assert all(meal["foods"][1]["grams"] in expected for meal in generated["meals"])
    else:
        assert generated == {"status": "unavailable", "reason": "portions", "meals": []}
