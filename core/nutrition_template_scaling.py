"""Deterministic portion fitting, preserving foods and their distribution across meals."""

from copy import deepcopy

from core.meal_generator import NUTRIENT_KEYS, TARGET_KEYS


def _fit_portions(portions, vectors, target):
    scales = [max(target[key], 1) for key in TARGET_KEYS]
    columns = [[amount / scale for amount, scale in zip(vector, scales)] for vector in vectors]
    desired = [target[key] / scale for key, scale in zip(TARGET_KEYS, scales)]
    calories = sum(grams * vector[0] for grams, vector in zip(portions, vectors))
    if calories <= 0:
        raise ValueError("Template meals need foods with calories to rescale portions.")
    fitted = [min(10000, max(.01, grams * target["calories"] / calories)) for grams in portions]
    residual = [sum(grams * column[k] for grams, column in zip(fitted, columns)) - desired[k]
                for k in range(4)]
    for _ in range(1000):
        largest_change = _fit_sweep(fitted, columns, residual)
        if largest_change < .000001:
            break
    return fitted


def _fit_sweep(fitted, columns, residual):
    largest_change = 0
    for index, column in enumerate(columns):
        norm = sum(amount * amount for amount in column)
        if not norm:
            continue
        adjustment = sum(amount * error for amount, error in zip(column, residual)) / norm
        updated = min(10000, max(.01, fitted[index] - adjustment))
        change = updated - fitted[index]
        fitted[index] = updated
        largest_change = max(largest_change, abs(change))
        for k in range(4):
            residual[k] += change * column[k]
    return largest_change


def rescale_meals(meals, target, catalog):
    """Fit each food's daily grams, retaining its relative portions between Meal slots.

    Infeasible combinations remain drafts with ordinary deviation warnings and
    publish blocks; fitting never swaps foods or silently changes the targets.
    """
    copied = deepcopy(meals)
    daily_grams = {}
    for meal in copied:
        for food in meal["foods"]:
            daily_grams[food["id"]] = daily_grams.get(food["id"], 0) + food["grams"]
    food_ids = list(daily_grams)
    vectors = [[catalog[food_id]["nutrients"][key] / 100 for key in NUTRIENT_KEYS]
               for food_id in food_ids]
    fitted = _fit_portions(list(daily_grams.values()), vectors, target)
    factors = {food_id: grams / daily_grams[food_id] for food_id, grams in zip(food_ids, fitted)}
    for meal in copied:
        for food in meal["foods"]:
            food["grams"] = max(.01, round(food["grams"] * factors[food["id"]], 2))
    return copied
