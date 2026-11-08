"""Version-pinned meal snapshots and catalog inputs for the pure generator."""

import json

from core.meal_generator import MealGenerationInput, generate_meals
from core.meal_setup import restriction_reasons
from database.food_library.lookup import _food
from database.nutrition_swap_foods import library_food, swap_allowed


def reviewed_staples(ledger):
    # An unseeded catalog is a supported deployment state, not an error fallback.
    if not ledger.conn.execute(
        "SELECT 1 FROM catalog.sqlite_master WHERE type='table' AND name='foods'"
    ).fetchone():
        return []
    rows = ledger.conn.execute(
        "SELECT * FROM catalog.foods WHERE reviewed=1 AND hidden=0 "
        "AND staple_roles_json<>'[]' ORDER BY staple_order, id"
    ).fetchall()
    return [_food(row) for row in rows]


def _swaps(variant):
    return {meal["slot"]: {food["role"]: food["id"] for food in meal["foods"] if food.get("swapped")}
            for meal in variant.get("meals", [])}


def meals_still_allowed(ledger, meals):
    current = {food["id"]: food for food in reviewed_staples(ledger)}
    restrictions = ledger.get_meal_setup()["restrictions"]
    return all(swap_allowed(library_food(ledger, food["id"]), restrictions) if food.get("swapped")
               else food["id"] in current and not (
                   set(restriction_reasons(current[food["id"]], restrictions)) - {"disliked"})
               for meal in meals for food in meal["foods"])


def _allowed_swaps(ledger, previous, day_type):
    variant = previous.get("variants", {}).get(day_type, {})
    saved = (_swaps(variant) if variant.get("meals")
             else previous.get("swaps", {}).get(day_type, {}))
    restrictions = ledger.get_meal_setup()["restrictions"]
    foods = {food_id: library_food(ledger, food_id)
             for roles in saved.values() for food_id in roles.values()}
    allowed = {food_id: food for food_id, food in foods.items() if swap_allowed(food, restrictions)}
    return {slot: {role: food_id for role, food_id in roles.items() if food_id in allowed}
            for slot, roles in saved.items()}, allowed


def generate_variants(ledger, targets, previous):
    setup = ledger.get_meal_setup()
    staples = reviewed_staples(ledger)
    options = targets if any(key in targets for key in ("daily", "training_day", "rest_day")) else {"daily": targets}
    variants = {}
    swaps = {}
    for day_type in ("training_day", "rest_day"):
        selected = options.get(day_type) or options.get("daily") or options.get("training_day") or options.get("rest_day")
        swaps[day_type], swap_foods = _allowed_swaps(ledger, previous, day_type)
        variants[day_type] = generate_meals(MealGenerationInput(
            targets=selected, setup=setup, training_day=day_type == "training_day", staples=staples,
            swaps=swaps[day_type], swap_foods=swap_foods,
        ))
    return {"enabled": True, "variants": variants, "swaps": swaps, "targets_changed": False}


def meals_for_version(ledger, plan):
    if plan.meals is not None:
        return plan.meals
    active = ledger.get_active_nutrition_plan()
    previous = json.loads(active["meals_json"]) if active is not None and active["meals_json"] else None
    if not previous or not previous.get("enabled"):
        return None
    if active["author"] == "Coach":
        return {**previous, "targets_changed": previous.get("targets_changed", False)
                or json.loads(active["targets_json"]) != plan.targets}
    return generate_variants(ledger, plan.targets, previous)
