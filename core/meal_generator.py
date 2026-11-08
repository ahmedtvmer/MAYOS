"""Deterministic meals from ordered, reviewed Staples; no I/O or clock.

Missing roles and infeasible practical portions produce an unavailable result,
never an approximate prescription or a fallback to another unreviewed food.
"""

import re
from dataclasses import dataclass, field
from itertools import product
from math import ceil, floor, isfinite

from core.meal_setup import MEAL_LAYOUTS, SLOT_MINUTES, restriction_reasons

TARGET_KEYS = ("calories", "protein_g", "carbs_g", "fat_g")
NUTRIENT_KEYS = ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g")
ROLES = ("protein", "carb", "vegetable_fat")
TRAINING_MINUTES = {"morning": 9 * 60, "afternoon": 15 * 60, "evening": 18 * 60}


@dataclass(frozen=True)
class MealGenerationInput:
    targets: dict
    setup: dict
    training_day: bool
    staples: list[dict]
    swaps: dict = field(default_factory=dict)


def _carb_weights(request):
    slots = MEAL_LAYOUTS[request.setup["meal_count"]]
    weights = dict.fromkeys(slots, 1)
    if request.training_day:
        minutes = TRAINING_MINUTES[request.setup["training_time"]]
        before = [slot for slot in slots if SLOT_MINUTES[slot] <= minutes]
        after = [slot for slot in slots if SLOT_MINUTES[slot] > minutes]
        for slot in (before[-1:] + after[:1]):
            weights[slot] = 1.5
    return weights


def slot_targets(request):
    slots = MEAL_LAYOUTS[request.setup["meal_count"]]
    weights = _carb_weights(request)
    macro_calories = (4 * request.targets["protein_g"] + 4 * request.targets["carbs_g"]
                      + 9 * request.targets["fat_g"])
    return {slot: {
        "protein_g": request.targets["protein_g"] / len(slots),
        "carbs_g": request.targets["carbs_g"] * weights[slot] / sum(weights.values()),
        "fat_g": (macro_calories / len(slots) - 4 * request.targets["protein_g"] / len(slots)
                  - 4 * request.targets["carbs_g"] * weights[slot] / sum(weights.values())) / 9,
        "calories": request.targets["calories"] / len(slots),
    } for slot in slots}


def _role_matches(food, slot, role):
    meal_type = "breakfast" if slot == "breakfast" else "snack" if slot.endswith("_snack") else "main"
    return bool({role, f"{meal_type}_{role}"} & set(food["staple_roles"]))


def _selected_foods(request, slot):
    foods = []
    for role in ROLES:
        allowed = [food for food in request.staples
                      if food["reviewed"] and not food.get("hidden", False)
                      and _role_matches(food, slot, role)
                      and not set(restriction_reasons(food, request.setup["restrictions"])) - {"disliked"}]
        swap_id = request.swaps.get(slot, {}).get(role)
        swap = next((food for food in allowed if food["id"] == swap_id), None)
        candidates = [food for food in allowed if food["id"] not in request.setup["restrictions"]["dislikes"]]
        if swap is None and not candidates:
            return None
        selected = swap if swap is not None else candidates[0]
        foods.append({**selected, "role": role, "swapped": selected["id"] == swap_id})
    return foods


def portion_step(food):
    label = (food.get("portion_label") or "").casefold()
    portion = food.get("portion_grams")
    if portion:
        return portion / 2 if label in ("loaf", "baladi loaf") else portion
    # Whole eggs are practical even when the owner did not add a local portion.
    name = food["name"].casefold()
    if re.search(r"\beggs?\b", name) and "white" not in name and "scrambled" not in name:
        return 50
    return 10


def _nutrient_vector(food):
    return tuple(float(food["nutrients"][key]) if food["nutrients"].get(key) is not None else float("nan")
                 for key in NUTRIENT_KEYS)


def _unit_limit(vector, targets, step):
    limits = [target * 1.05 / (amount * step / 100)
              for amount, target in zip(vector, targets) if amount > 0]
    return max(0, floor(min([10000 / step, *limits]) + 1e-9))


def _last_unit_interval(partial, vector, bounds):
    lower, upper = 1, 10000
    for consumed, amount, target in zip(partial, vector, bounds):
        if amount == 0:
            if not target * .95 - 1e-9 <= consumed <= target * 1.05 + 1e-9:
                return None
        else:
            lower = max(lower, ceil((target * .95 - consumed) / amount - 1e-9))
            upper = min(upper, floor((target * 1.05 - consumed) / amount + 1e-9))
    return (lower, upper) if lower <= upper else None


def _best_last_units(partial, vector, targets, interval):
    scales = [max(target, 1) ** 2 for target in targets]
    denominator = sum(amount ** 2 / scale for amount, scale in zip(vector, scales))
    ideal = sum(amount * (target - consumed) / scale
                for amount, target, consumed, scale in zip(vector, targets, partial, scales)) / denominator
    lower, upper = interval
    return sorted({max(lower, min(upper, floor(ideal))), max(lower, min(upper, ceil(ideal)))})


def _rounded_portions(foods, share):
    targets = tuple(share[key] for key in TARGET_KEYS)
    steps = [portion_step(food) for food in foods]
    vectors = [_nutrient_vector(food) for food in foods]
    if any(not isfinite(step) or step <= 0 for step in steps):
        return None
    if any(not isfinite(amount) or amount < 0 for vector in vectors for amount in vector):
        return None
    limits = [_unit_limit(vector, targets, step) for vector, step in zip(vectors, steps)]
    if not all(limits) or any(not any(vector) for vector in vectors):
        return None
    order = sorted(range(3), key=lambda index: (limits[index], index))
    unit_vectors = [tuple(amount * steps[index] / 100 for amount in vectors[index]) for index in order]
    units = _search_portions(unit_vectors, [limits[index] for index in order], targets)
    if units is None:
        return None
    grams = [0., 0., 0.]
    for index, amount in zip(order, units):
        grams[index] = round(amount * steps[index], 6)
    return grams


def _feasible_units(vectors, limits, targets):
    # Enumerate the two smallest practical-unit ranges. The final food has a
    # convex error function; its feasible integer optimum is floor/ceil(ideal).
    for first, second in product(range(1, limits[0] + 1), range(1, limits[1] + 1)):
        partial = tuple(a * first + b * second for a, b in zip(vectors[0], vectors[1]))
        interval = _last_unit_interval(partial, vectors[2], targets)
        if interval is None:
            continue
        interval = (interval[0], min(interval[1], limits[2]))
        if interval[0] > interval[1]:
            continue
        for last in _best_last_units(partial, vectors[2], targets, interval):
            yield first, second, last


def _search_portions(vectors, limits, targets):
    best = None
    for units in _feasible_units(vectors, limits, targets):
        totals = tuple(sum(vector[index] * count for vector, count in zip(vectors, units))
                       for index in range(len(targets)))
        error = sum(((amount - target) / max(target, 1)) ** 2 for amount, target in zip(totals, targets))
        candidate = (error, *units)
        if best is None or candidate < best:
            best = candidate
    return best[1:] if best else None


def _meal_food(food, grams):
    return {key: food.get(key) for key in (
        "id", "name", "arabic_name", "portion_label", "portion_grams", "role", "swapped",
    )} | {"grams": grams, "nutrients_per_100g": dict(zip(NUTRIENT_KEYS, _nutrient_vector(food)))}


def meal_totals(foods):
    return {target: sum(food["nutrients_per_100g"][nutrient] * food["grams"] / 100 for food in foods)
            for target, nutrient in zip(TARGET_KEYS, NUTRIENT_KEYS)}


def _generated_meal(request, slot, share):
    foods = _selected_foods(request, slot)
    if foods is None:
        return {"status": "unavailable", "reason": "staples", "meals": []}
    grams = _rounded_portions(foods, share)
    if grams is None:
        return {"status": "unavailable", "reason": "portions", "meals": []}
    portions = [_meal_food(food, amount) for food, amount in zip(foods, grams)]
    return {"slot": slot, "targets": share, "foods": portions, "totals": meal_totals(portions)}


def generate_meals(request):
    """Return ready meals or a reason; all four nutrients meet ±5%, or no meals.

    Boundary cases: empty/missing roles; blocked foods; zero targets; no feasible
    positive portions. Selection never skips the first allowed food to fit numbers.
    """
    if any(not isfinite(request.targets[key]) or request.targets[key] < 0 for key in TARGET_KEYS):
        raise ValueError("Meal targets must be finite and non-negative.")
    if not any(request.targets[key] for key in TARGET_KEYS[1:]):
        return {"status": "unavailable", "reason": "portions", "meals": []}
    meals = []
    for slot, share in slot_targets(request).items():
        meal = _generated_meal(request, slot, share)
        if meal.get("status") == "unavailable":
            return meal
        meals.append(meal)
    totals = {key: sum(meal["totals"][key] for meal in meals) for key in TARGET_KEYS}
    return {"status": "ready", "meals": meals, "totals": totals}
