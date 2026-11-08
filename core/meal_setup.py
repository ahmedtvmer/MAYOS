"""Meal slot layouts and Food restriction matching, independent of storage."""

ALLERGENS = (
    "milk", "eggs", "wheat_gluten", "peanuts", "tree_nuts", "fish",
    "shellfish", "sesame", "soy",
)
MEAL_LAYOUTS = {
    3: ("breakfast", "lunch", "dinner"),
    4: ("breakfast", "lunch", "afternoon_snack", "dinner"),
    5: ("breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner"),
}
# SR Legacy/Foundation food groups and FNDDS categories, kept together so
# category-based exclusions do not depend on translated or curated food names.
NON_VEGETARIAN_CATEGORIES = frozenset({
    "poultry products", "beef products", "pork products", "lamb, veal, and game products",
    "finfish and shellfish products", "sausages and luncheon meats",
    "meat", "meats", "poultry", "fish", "shellfish", "seafood", "beef", "pork",
    "chicken", "turkey", "lamb", "goat", "organ meats", "bacon", "cold cuts and cured meats",
    "frankfurters", "sausages", "chicken, whole pieces", "chicken patties, nuggets and tenders",
    "other poultry", "fish and shellfish", "fish, finfish", "shrimp", "other seafood",
    "meat mixed dishes", "poultry mixed dishes", "seafood mixed dishes",
})
SLOT_MINUTES = {"breakfast": 8 * 60, "morning_snack": 10 * 60,
                "lunch": 13 * 60, "afternoon_snack": 16 * 60, "dinner": 20 * 60}


def vegetarian_category(category):
    return (category or "").strip().casefold() not in NON_VEGETARIAN_CATEGORIES


def meal_slot(meal_label, logged_time, meal_count):
    slots = MEAL_LAYOUTS[meal_count]
    if meal_label in slots:
        return meal_label
    minutes = int(logged_time[:2]) * 60 + int(logged_time[3:5])
    snacks = [slot for slot in slots if slot.endswith("_snack")]
    # With three meals there is no Snack slot: keep every entry visible by
    # mapping it to the nearest main meal. Ties go to the earlier slot.
    return min(snacks or slots, key=lambda slot: abs(SLOT_MINUTES[slot] - minutes))


def restriction_reasons(food, restrictions):
    allergens = food.get("allergens", []) if food.get("allergens_reviewed", False) else []
    reasons = [tag for tag in ALLERGENS
               if tag in restrictions["allergies"] and tag in allergens]
    if restrictions["vegetarian"] and not food.get("vegetarian", True):
        reasons.append("vegetarian")
    if food["id"] in restrictions["dislikes"]:
        reasons.append("disliked")
    return reasons
