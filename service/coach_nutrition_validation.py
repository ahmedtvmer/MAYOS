"""Authoritative food snapshots and publish checks for Coach Nutrition drafts."""

from math import isfinite

from core.meal_generator import NUTRIENT_KEYS, TARGET_KEYS, meal_totals
from core.meal_setup import ALLERGENS, restriction_reasons
from database.nutrition_meals import reviewed_staples
from service import nutrition


def target_validation(ledger, draft):
    profile = nutrition._coach_profile(ledger, draft["goal"])
    baseline = nutrition._coach_target_baseline(ledger, profile, draft["goal"], draft["daily_activity"])
    if not draft["targets"]:
        raise ValueError("Set Nutrition targets.")
    fields = {"daily": "targets", "training_day": "training_day_targets", "rest_day": "rest_day_targets"}
    normalized = {day: nutrition._validate_coach_target(fields[day], target, profile, baseline)
                  for day, target in draft["targets"].items()}
    return normalized, baseline.calorie_floor


def food_snapshot(food, portion, restrictions):
    reasons = restriction_reasons(food, restrictions)
    if restrictions["allergies"] and not food["allergens_reviewed"]:
        reasons.append("allergens_unreviewed")
    nutrients = {key: food["nutrients"].get(key) for key in NUTRIENT_KEYS}
    if any(amount is None or not isfinite(amount) or amount < 0 for amount in nutrients.values()):
        raise ValueError("Food needs complete calorie and Macro information.")
    return {key: food.get(key) for key in ("id", "name", "arabic_name", "portion_label", "portion_grams")} | {
        "grams": portion["grams"], "nutrients_per_100g": nutrients, "restriction_reasons": reasons,
    }


def _meal_snapshot(meal, catalog, restrictions):
    foods = []
    errors = []
    for portion in meal["foods"]:
        food = catalog.get(portion["id"])
        if food is None:
            errors.append("Use reviewed Staple foods only.")
            continue
        try:
            snapshot = food_snapshot(food, portion, restrictions)
        except ValueError as error:
            errors.append(str(error))
            continue
        if portion["grams"] <= 0:
            errors.append("Food grams must be greater than zero.")
        if set(snapshot["restriction_reasons"]) & {*ALLERGENS, "vegetarian", "allergens_unreviewed"}:
            errors.append("A food conflicts with an allergy or vegetarian restriction, or has unreviewed allergens.")
        foods.append(snapshot)
    if not foods:
        errors.append("Add at least one food to each Meal slot.")
    return {**meal, "foods": foods, "totals": meal_totals(foods)}, errors


def _deviations(totals, targets):
    # Zero targets only match zero consumption; exact 5%/15% boundaries are allowed.
    return {key: (abs(totals[key] - targets[key]) / targets[key] if targets[key] > 0
                  else 0 if totals[key] == 0 else 1)
            for key in TARGET_KEYS}


def _meal_comparisons(snapshots, target):
    if not snapshots:
        return snapshots
    share = {key: target[key] / len(snapshots) for key in TARGET_KEYS}
    return [{**meal, "targets": share, "deviations": _deviations(meal["totals"], share)}
            for meal in snapshots]


def evaluate(ledger, draft):
    errors = []
    warnings = []
    targets = draft["targets"]
    floor = None
    try:
        targets, floor = target_validation(ledger, draft)
    except ValueError as error:
        errors.append(str(error))
    catalog = {food["id"]: food for food in reviewed_staples(ledger)}
    restrictions = ledger.get_meal_setup()["restrictions"]
    variants = {}
    for day_type, meals in draft["variants"].items():
        snapshots = []
        for meal in meals:
            snapshot, meal_errors = _meal_snapshot(meal, catalog, restrictions)
            snapshots.append(snapshot)
            errors.extend(f"{day_type} / {meal['name'] or meal['slot']}: {error}" for error in meal_errors)
            if any(food["restriction_reasons"] for food in snapshot["foods"]):
                warnings.append(f"{day_type} / {meal['name'] or meal['slot']}: restricted food.")
        totals = {key: sum(meal["totals"][key] for meal in snapshots) for key in TARGET_KEYS}
        target = targets.get(day_type, {})
        if floor is not None:
            snapshots = _meal_comparisons(snapshots, target)
        deviations = _deviations(totals, target) if floor is not None else {}
        if any(deviation > .05 + 1e-9 for deviation in deviations.values()):
            warnings.append(f"{day_type}: totals differ from targets by more than 5%.")
        if any(deviation > .15 + 1e-9 for deviation in deviations.values()):
            errors.append(f"{day_type}: totals must be within 15% of every target.")
        if floor is not None and totals["calories"] < floor:
            errors.append(f"{day_type}: meals are below the Calorie floor of {floor:g} kcal.")
        variants[day_type] = {"status": "ready", "meals": snapshots, "totals": totals,
                              "targets": target, "deviations": deviations}
    return {"targets": targets, "calorie_floor": floor, "variants": variants,
            "errors": list(dict.fromkeys(errors)), "warnings": list(dict.fromkeys(warnings)),
            "can_publish": not errors}
