"""Practical single-food replacements, preserving the meal's calories and protein."""

from math import isfinite

from core.meal_generator import NUTRIENT_KEYS, _meal_food, meal_target_deviation, meal_totals
from core.meal_portions import portion_amounts, portion_normality


def replacement_portion(meal, role, replacement):
    """Minimize squared relative meal calorie/protein error on practical units.

    Other foods stay fixed. Missing/invalid nutrients and zero-energy foods
    cannot yield a usable replacement; ties prefer normal amounts, then smaller.
    """
    nutrients = [replacement["nutrients"].get(key) for key in NUTRIENT_KEYS]
    replacement = {**replacement, "role": role}
    amounts = portion_amounts(replacement)
    if (any(amount is None or not isfinite(amount) or amount < 0 for amount in nutrients)
            or not amounts or nutrients[0] <= 0):
        raise ValueError("This food needs complete nutrients and a practical portion before it can be swapped.")
    others = [food for food in meal["foods"] if food["role"] != role]
    targets = meal_totals(meal["foods"])
    consumed = meal_totals(others)
    keys = ("calories", "protein_g")
    grams = min(amounts, key=lambda grams: (
        sum(((consumed[key] + amount * grams / 100 - targets[key]) / max(targets[key], 1)) ** 2
            for key, amount in zip(keys, nutrients[:2])), portion_normality(replacement, grams), grams))
    return _meal_food({**replacement, "swapped": True}, grams)


def swap_meal(meal, role, replacement):
    portion = replacement_portion(meal, role, replacement)
    foods = [portion if food["role"] == role else food for food in meal["foods"]]
    totals = meal_totals(foods)
    return {**meal, "foods": foods, "totals": totals,
            "target_deviation": meal_target_deviation(totals, meal.get("targets", {}))}
