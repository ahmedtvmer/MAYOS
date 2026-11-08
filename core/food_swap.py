"""Practical single-food replacements, preserving the meal's calories and protein."""

from math import ceil, floor, isfinite

from core.meal_generator import NUTRIENT_KEYS, _meal_food, meal_totals, portion_step


def replacement_portion(meal, role, replacement):
    """Minimize squared relative meal calorie/protein error on practical units.

    Other foods stay fixed. Missing/invalid nutrients and zero-energy foods
    cannot yield a usable replacement; ties choose the smaller portion.
    """
    nutrients = [replacement["nutrients"].get(key) for key in NUTRIENT_KEYS]
    step = portion_step(replacement)
    if (any(amount is None or not isfinite(amount) or amount < 0 for amount in nutrients)
            or not isfinite(step) or step <= 0 or step > 10000 or nutrients[0] <= 0):
        raise ValueError("This food needs complete nutrients and a practical portion before it can be swapped.")
    others = [food for food in meal["foods"] if food["role"] != role]
    targets = meal_totals(meal["foods"])
    consumed = meal_totals(others)
    units = _closest_units(nutrients[:2], step, targets, consumed)
    return _meal_food({**replacement, "role": role, "swapped": True}, round(units * step, 6))


def _closest_units(nutrients, step, targets, consumed):
    keys = ("calories", "protein_g")
    vector = [amount * step / 100 for amount in nutrients]
    scales = [max(targets[key], 1) ** 2 for key in keys]
    denominator = sum(amount ** 2 / scale for amount, scale in zip(vector, scales))
    ideal = sum(amount * (targets[key] - consumed[key]) / scale
                for amount, key, scale in zip(vector, keys, scales)) / denominator
    limit = floor(10000 / step)
    # The convex optimum lies at one of its two adjacent practical portions,
    # including when the unconstrained optimum falls outside the portion range.
    candidates = {max(1, min(limit, floor(ideal))), max(1, min(limit, ceil(ideal)))}
    return min(candidates, key=lambda units: (
        sum((consumed[key] + amount * units - targets[key]) ** 2 / scale
            for key, amount, scale in zip(keys, vector, scales)), units))


def swap_meal(meal, role, replacement):
    portion = replacement_portion(meal, role, replacement)
    foods = [portion if food["role"] == role else food for food in meal["foods"]]
    return {**meal, "foods": foods, "totals": meal_totals(foods)}
