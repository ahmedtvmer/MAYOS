"""Version-pinned meal snapshots and catalog inputs for the pure generator."""

import json

from core.meal_generator import MealGenerationInput, generate_meals
from core.meal_setup import restriction_reasons
from database.food_library.lookup import _food


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
    return all(food["id"] in current and not (
        set(restriction_reasons(current[food["id"]], restrictions)) - {"disliked"})
        for meal in meals for food in meal["foods"])


def generate_variants(ledger, targets, previous):
    setup = ledger.get_meal_setup()
    staples = reviewed_staples(ledger)
    options = targets if any(key in targets for key in ("daily", "training_day", "rest_day")) else {"daily": targets}
    variants = {}
    for day_type in ("training_day", "rest_day"):
        selected = options.get(day_type) or options.get("daily") or options.get("training_day") or options.get("rest_day")
        variants[day_type] = generate_meals(MealGenerationInput(
            targets=selected, setup=setup, training_day=day_type == "training_day", staples=staples,
            swaps=_swaps(previous.get("variants", {}).get(day_type, {})),
        ))
    return {"enabled": True, "variants": variants, "targets_changed": False}


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
