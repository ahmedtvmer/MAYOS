"""Permanent Player-authored Food swaps; Food log writes never enter this path."""

import json
from dataclasses import dataclass

from core.food_swap import swap_meal
from core.meal_generator import role_matches
from core.meal_setup import restriction_reasons
from database.nutrition_meals import _swaps, meals_still_allowed, reviewed_staples
from database.nutrition_swap_foods import library_food, swap_allowed
from service.meals import _save_player_meals


@dataclass(frozen=True)
class SwapTarget:
    plan_version_id: int
    day_type: str
    slot: str
    role: str


@dataclass(frozen=True)
class SwapCommand:
    target: SwapTarget
    food_id: str


def _context(ledger, target):
    active = ledger.get_active_nutrition_plan()
    if active is None or active["author"] != "Player":
        raise PermissionError("Food swaps require your own Nutrition plan and Nutrition authority.")
    if active["id"] != target.plan_version_id:
        raise ValueError("The Nutrition plan changed. Refresh meals and try again.")
    payload = json.loads(active["meals_json"]) if active["meals_json"] else {}
    variant = payload.get("variants", {}).get(target.day_type, {})
    if not payload.get("enabled") or variant.get("status") != "ready":
        raise ValueError("Meals aren't available yet.")
    meal = _target_meal(variant, target)
    if not meals_still_allowed(ledger, variant["meals"]):
        raise ValueError("Food restrictions or the Food library changed. Refresh meals and try again.")
    return active, payload, meal


def _target_meal(variant, target):
    meal = next((meal for meal in variant.get("meals", []) if meal["slot"] == target.slot), None)
    if meal is None or not any(food["role"] == target.role for food in meal["foods"]):
        raise ValueError("This food or Meal slot is unavailable.")
    return meal


def _next_staples(staples, meal, role):
    current = next(food["id"] for food in meal["foods"] if food["role"] == role)
    ordered = [food for food in staples if role_matches(food, meal["slot"], role)]
    index = next((index for index, food in enumerate(ordered) if food["id"] == current), -1)
    return [food for food in ordered[index + 1:] + ordered[:index + 1] if food["id"] != current]


def _candidate(food, meal, role, restrictions):
    reasons = restriction_reasons(food, restrictions)
    preview = None
    if swap_allowed(food, restrictions):
        try:
            preview = swap_meal(meal, role, food)
        except ValueError:
            # Incomplete catalog nutrients are visible in search but cannot
            # produce a safe, finite portion preview or a plan snapshot.
            pass
    portion = next((food for food in preview["foods"] if food["role"] == role), None) if preview else None
    return {"food": {**food, "restriction_reasons": reasons}, "allowed": preview is not None,
            "grams": portion["grams"] if portion else None, "totals": preview["totals"] if preview else None}


def candidates(db, ledger, target, query):
    with ledger.ledger_transaction():
        _active, _payload, meal = _context(ledger, target)
        restrictions = ledger.get_meal_setup()["restrictions"]
        staples = [_candidate(food, meal, target.role, restrictions)
                   for food in _next_staples(reviewed_staples(ledger), meal, target.role)
                   if not restriction_reasons(food, restrictions)]
        current = next(food["id"] for food in meal["foods"] if food["role"] == target.role)
        searched = db.search_food_library(query) if query.strip() else []
        search = [_candidate(food, meal, target.role, restrictions)
                  for food in searched if food["id"] != current]
    return {"staples": [food for food in staples if food["allowed"]], "search": search}


def _replace_variants(payload, command, replacement):
    for day_type, variant in payload["variants"].items():
        if variant["status"] != "ready":
            raise ValueError("Meals must be available for training and rest days before swapping.")
        meal = _target_meal(variant, command.target)
        updated = swap_meal(meal, command.target.role, replacement)
        variant["meals"] = [updated if other["slot"] == meal["slot"] else other for other in variant["meals"]]
        variant["totals"] = {key: sum(meal["totals"][key] for meal in variant["meals"])
                             for key in updated["totals"]}
        payload.setdefault("swaps", {})[day_type] = _swaps(variant)


def make_swap(ledger, command):
    with ledger.ledger_transaction(immediate=True):
        active, payload, meal = _context(ledger, command.target)
        replacement = library_food(ledger, command.food_id)
        if not swap_allowed(replacement, ledger.get_meal_setup()["restrictions"]):
            raise ValueError("This food is restricted, hidden, or is not a reviewed Staple food.")
        current = next(food for food in meal["foods"] if food["role"] == command.target.role)
        if current["id"] == command.food_id:
            raise ValueError("Choose a different food for the Food swap.")
        _replace_variants(payload, command, replacement)
        version_id = _save_player_meals(ledger, active, payload)
    return {"plan_version_id": version_id}
