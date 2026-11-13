"""Per-meal amount rules shared by generated meals and Player Food swaps."""

import re
from math import ceil, floor, isfinite

# Counted ranges are converted using the curated household portion. The gram
# fallback is used only when that portion has not yet been curated.
CATEGORY_LIMITS = {
    "grains": (100, 300),
    "meat": (100, 250),
    "eggs": (100, 200),
    "bread": (50, 200),
    "oils": (5, 15),
    "nuts_tahini": (10, 30),
    "vegetables": (100, 300),
    "fruit": (150, 300),
}
COUNT_LIMITS = {"eggs": (2, 4), "bread": (.5, 2), "fruit": (1, 2)}


def limit_category(food):
    name = food["name"].casefold()
    category = (food.get("category") or "").casefold()
    label = (food.get("portion_label") or "").casefold()
    if re.search(r"\beggs?\b", name) and not re.search(r"\b(whites?|noodles?|pasta)\b", name):
        return "eggs"
    if re.search(r"\b(bread|pita|baladi|loaf)\b", name + " " + label):
        return "bread"
    if (any(word in category for word in ("meat", "poultry", "fish", "beef", "lamb"))
            or re.search(r"\b(chicken|turkey|beef|lamb|fish|tuna|salmon|sardines?|tilapia|shrimp|mackerel)\b", name)):
        return "meat"
    if re.search(r"\b(tahini|sesame|almonds?|walnuts?|peanuts?|cashews?|pistachios?|nuts?)\b", name + " " + category):
        return "nuts_tahini"
    if re.search(r"\boils?\b", name) or category in ("fats and oils", "oils"):
        return "oils"
    if "fruit" in category or re.search(r"\b(apple|banana|orange|pear|peach|mango|guava|tangerine|plum|apricot)\b", name):
        return "fruit"
    if "vegetable" in category:
        return "vegetables"
    role = food.get("role", "")
    if role == "protein":
        return "meat"
    return "grains" if role == "carb" else "vegetables"


def portion_limits(food):
    category = limit_category(food)
    lower, upper = CATEGORY_LIMITS[category]
    portion = food.get("portion_grams")
    if category in COUNT_LIMITS and portion and isfinite(portion) and portion > 0:
        lower, upper = (count * portion for count in COUNT_LIMITS[category])
    return (food.get("min_grams") if food.get("min_grams") is not None else lower,
            food.get("max_grams") if food.get("max_grams") is not None else upper)


def portion_step(food):
    portion = food.get("portion_grams")
    if portion is not None:
        return portion / 2 if limit_category(food) in COUNT_LIMITS else portion
    # A 25 g increment cannot represent an oil serving; these two small-amount
    # categories need finer gram increments inside their explicitly small limits.
    return {"oils": 5, "nuts_tahini": 10}.get(limit_category(food), 25)


def _portion_units(food):
    lower, upper = portion_limits(food)
    step = portion_step(food)
    if (not all(isfinite(value) for value in (lower, upper, step))
            or lower <= 0 or upper < lower or step <= 0):
        return None
    first, last = ceil(lower / step - 1e-9), floor(upper / step + 1e-9)
    if first > last:
        return None
    return first, last, step


def portion_grid(food):
    """Return first/last practical grams and step without expanding the interval."""
    units = _portion_units(food)
    if units is None:
        return None
    first, last, step = units
    return round(first * step, 6), round(last * step, 6), step


def portion_amounts(food):
    units = _portion_units(food)
    if units is None:
        return ()
    first, last, step = units
    return tuple(round(unit * step, 6)
                 for unit in range(first, last + 1))


def portion_normality(food, grams):
    lower, upper = portion_limits(food)
    normal = (lower + upper) / 2
    return ((grams - normal) / normal) ** 2
