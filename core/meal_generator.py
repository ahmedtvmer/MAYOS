"""Deterministic meals from reviewed Staples and explicit Food swaps; no I/O or clock.

Try allowed Staples in curation order before returning the closest practical
portions with a per-slot deviation. Missing reviewed roles remain unavailable.
"""

import re
from dataclasses import dataclass, field
from itertools import product
from math import ceil, floor, isfinite, sqrt

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
    swap_foods: dict = field(default_factory=dict)


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


def role_matches(food, slot, role):
    meal_type = "breakfast" if slot == "breakfast" else "snack" if slot.endswith("_snack") else "main"
    return bool({role, f"{meal_type}_{role}"} & set(food["staple_roles"]))


def _food_allowed(food, restrictions):
    return (food["reviewed"] and not food.get("hidden", False)
            and not set(restriction_reasons(food, restrictions)) - {"disliked"})


def _role_candidates(request, slot, role):
    restrictions = request.setup["restrictions"]
    allowed = [food for food in request.staples
               if role_matches(food, slot, role) and _food_allowed(food, restrictions)]
    swap_id = request.swaps.get(slot, {}).get(role)
    swap = next((food for food in allowed if food["id"] == swap_id), None)
    explicit = request.swap_foods.get(swap_id)
    if swap is None and explicit and _food_allowed(explicit, restrictions):
        swap = explicit
    selected = [swap] if swap is not None else [food for food in allowed if food["id"] not in restrictions["dislikes"]]
    return [{**food, "role": role, "swapped": food["id"] == swap_id} for food in selected]


def _candidate_foods(request, slot):
    choices = [_role_candidates(request, slot, role) for role in ROLES]
    return choices if all(choices) else None


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


def _last_unit_interval(partial, vector, bounds):
    lower, upper = 1, float("inf")
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


def _rounded_portions(foods, share, search):
    targets = tuple(share[key] for key in TARGET_KEYS)
    steps = [portion_step(food) for food in foods]
    vectors = [_nutrient_vector(food) for food in foods]
    if any(not isfinite(step) or step <= 0 for step in steps):
        return None
    if any(not isfinite(amount) or amount < 0 for vector in vectors for amount in vector):
        return None
    if any(not any(vector) for vector in vectors):
        return None
    return _portion_solution(steps, vectors, targets, search)


def _portion_solution(steps, vectors, targets, search):
    unit_vectors = [tuple(amount * step / 100 for amount in vector) for vector, step in zip(vectors, steps)]
    caps = [floor(10000 / step) for step in steps]
    limits = _bounded_units(unit_vectors, [target * 1.05 for target in targets], caps)
    order = sorted(range(3), key=lambda index: (limits[index], index))
    units = search([unit_vectors[index] for index in order], [caps[index] for index in order], targets)
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


def _portion_error(totals, targets):
    return sum(((amount - target) / max(target, 1)) ** 2 for amount, target in zip(totals, targets))


def _best_units(vectors, targets, candidates):
    best = None
    for units in candidates:
        totals = tuple(sum(vector[index] * count for vector, count in zip(vectors, units))
                       for index in range(len(targets)))
        error = _portion_error(totals, targets)
        candidate = (error, *units)
        if best is None or candidate < best:
            best = candidate
    return best[1:] if best else None


def _bounded_units(vectors, ceilings, caps):
    return [min(cap, max(0, floor(min(
        ceiling / amount for amount, ceiling in zip(vector, ceilings) if amount > 0
    ) + 1e-9))) for vector, cap in zip(vectors, caps)]


def _search_portions(vectors, limits, targets):
    limits = _bounded_units(vectors, [target * 1.05 for target in targets], limits)
    return _best_units(vectors, targets, _feasible_units(vectors, limits, targets))


def _closest_units(vectors, limits, targets):
    for first, second in product(range(1, limits[0] + 1), range(1, limits[1] + 1)):
        partial = tuple(a * first + b * second for a, b in zip(vectors[0], vectors[1]))
        for last in _best_last_units(partial, vectors[2], targets, (1, limits[2])):
            yield first, second, last


def _search_closest_portions(vectors, limits, targets):
    if not all(limits):
        return None
    baseline = tuple(sum(vector[index] for vector in vectors) for index in range(len(targets)))
    radius = sqrt(_portion_error(baseline, targets))
    # Nonnegative nutrients cannot improve on the one-unit baseline outside
    # these bounds, so the closest search stays finite without losing optima.
    ceilings = [target + radius * max(target, 1) for target in targets]
    limits = _bounded_units(vectors, ceilings, limits)
    return _best_units(vectors, targets, _closest_units(vectors, limits, targets))


def _meal_food(food, grams):
    return {key: food.get(key) for key in (
        "id", "name", "arabic_name", "portion_label", "portion_grams", "role", "swapped",
    )} | {"grams": grams, "nutrients_per_100g": dict(zip(NUTRIENT_KEYS, _nutrient_vector(food)))}


def meal_totals(foods):
    return {target: sum(food["nutrients_per_100g"][nutrient] * food["grams"] / 100 for food in foods)
            for target, nutrient in zip(TARGET_KEYS, NUTRIENT_KEYS)}


def meal_target_deviation(totals, targets):
    return {key: totals[key] - target for key, target in targets.items()}


def _portioned_meal(slot, share, foods, grams):
    portions = [_meal_food(food, amount) for food, amount in zip(foods, grams)]
    totals = meal_totals(portions)
    return {"slot": slot, "targets": share, "foods": portions, "totals": totals,
            "target_deviation": meal_target_deviation(totals, share)}


def _closest_meal(choices, slot, share):
    closest = None
    for foods in product(*choices):
        grams = _rounded_portions(foods, share, _search_closest_portions)
        if grams is None:
            continue
        meal = _portioned_meal(slot, share, foods, grams)
        error = _portion_error(tuple(meal["totals"][key] for key in TARGET_KEYS), tuple(share[key] for key in TARGET_KEYS))
        if closest is None or error < closest[0]:
            closest = (error, meal)
    if closest is None:
        return {"status": "unavailable", "reason": "portions", "meals": []}
    return closest[1]


def _generated_meal(request, slot, share):
    choices = _candidate_foods(request, slot)
    if choices is None:
        return {"status": "unavailable", "reason": "staples", "meals": []}
    for foods in product(*choices):
        grams = _rounded_portions(foods, share, _search_portions)
        if grams is not None:
            return _portioned_meal(slot, share, foods, grams)
    return _closest_meal(choices, slot, share)


def generate_meals(request):
    """Prefer meals within ±5%; otherwise return the closest practical portions.

    Boundary cases: empty/missing roles; blocked foods; zero targets; no feasible
    positive portions. Allowed explicit swaps stay pinned during regeneration.
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
