"""Deterministic meals from reviewed Staples and explicit Food swaps; no I/O or clock.

Score realistic portions, then choose meals together against daily targets.
"""

from dataclasses import dataclass, field
from math import floor, isfinite

from core.meal_portions import portion_step as portion_step
from core.meal_search import TOLERANCES, choose_day, meal_candidates
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


def _nutrient_vector(food):
    return tuple(float(food["nutrients"][key]) for key in NUTRIENT_KEYS)


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


def _day_gaps(totals, targets):
    gaps = []
    labels = (("kcal", "سعرة"), ("g protein", "غ بروتين"),
              ("g carbs", "غ كربوهيدرات"), ("g fat", "غ دهون"))
    for key, tolerance, (english, arabic) in zip(TARGET_KEYS, TOLERANCES, labels):
        delta = totals[key] - targets[key]
        if abs(delta) <= targets[key] * tolerance + 1e-8:
            continue
        step = 10 if key == "calories" else 5
        amount = max(step, floor(abs(delta) / step + .5) * step)
        gaps.append((f"{amount} {english} {'over' if delta > 0 else 'under'}",
                     f"{'زيادة' if delta > 0 else 'نقص'} {amount} {arabic}", delta))
    return gaps


def day_gap_note(totals, targets):
    """Only out-of-tolerance nutrients are named, rounded to 10 kcal / 5 g."""
    gaps = _day_gaps(totals, targets)
    if not gaps:
        return None
    under, over = any(gap[2] < 0 for gap in gaps), any(gap[2] > 0 for gap in gaps)
    advice_en = ("Add a snack or a bigger portion." if under and not over else
                 "Try a smaller portion or a different food." if over and not under else
                 "Try different foods or adjust portions.")
    advice_ar = ("أضف وجبة خفيفة أو حصة أكبر." if under and not over else
                 "جرّب حصة أصغر أو طعامًا مختلفًا." if over and not under else
                 "جرّب أطعمة مختلفة أو عدّل الحصص.")
    return {"en": "About " + " and ".join(gap[0] for gap in gaps) + ". " + advice_en,
            "ar": "تقريبًا: " + " و".join(gap[1] for gap in gaps) + ". " + advice_ar}


def _day_candidates(request, shares):
    candidates = []
    cache = {}
    for slot, share in shares.items():
        choices = _candidate_foods(request, slot)
        if choices is None:
            return [], "staples"
        targets = tuple(share[key] for key in TARGET_KEYS)
        cache_key = (tuple(tuple((food["id"], food["swapped"]) for food in foods) for foods in choices), targets)
        if cache_key not in cache:
            cache[cache_key] = meal_candidates(choices, targets, NUTRIENT_KEYS)
        meals = cache[cache_key]
        if not meals:
            return [], "portions"
        candidates.append(meals)
    return candidates, None


def generate_meals(request):
    """Keep limits inviolable; evaluate fit on the day, never require a slot fit."""
    if any(not isfinite(request.targets[key]) or request.targets[key] < 0 for key in TARGET_KEYS):
        raise ValueError("Meal targets must be finite and non-negative.")
    if not any(request.targets[key] for key in TARGET_KEYS[1:]):
        return {"status": "unavailable", "reason": "portions", "meals": []}
    shares = slot_targets(request)
    candidates, reason = _day_candidates(request, shares)
    if reason:
        return {"status": "unavailable", "reason": reason, "meals": []}
    selected = choose_day(candidates, tuple(request.targets[key] for key in TARGET_KEYS),
                          [tuple(share[key] for key in TARGET_KEYS) for share in shares.values()])
    meals = [_portioned_meal(slot, share, [food for food, _grams in candidate.choices],
                            [grams for _food, grams in candidate.choices])
             for (slot, share), candidate in zip(shares.items(), selected.choices)]
    totals = {key: sum(meal["totals"][key] for meal in meals) for key in TARGET_KEYS}
    return {"status": "ready", "meals": meals, "totals": totals,
            "gap_note": day_gap_note(totals, request.targets)}
