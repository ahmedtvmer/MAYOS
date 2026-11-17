"""Enable Nutrition plan meals and copy their snapshots into the Food log."""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

from core.meal_generator import meals_with_food_macros
from core.meal_setup import SLOT_MINUTES
from database.ledger.nutrition_meals import (
    cached_variants_for_plan,
    generate_variants,
    meal_switch_enabled,
    resolve_variant,
    save_meal_version,
)
from service import nutrition
from service.food_log_adherence import recompute_day
from service.weight_history import player_local_date


def read(ledger, today):
    state = nutrition.read(ledger, today=today)
    if state["state"] != "ready":
        active = ledger.get_active_nutrition_plan()
        payload = json.loads(active["meals_json"]) if active and active["meals_json"] else None
        return {
            "status": "unavailable", "reason": "targets", "meals": [],
            "enabled": meal_switch_enabled(ledger, active, payload) if active else False,
            "plan_version_id": active["id"] if active else None,
            "author": active["author"] if active else None,
        }
    active = ledger.get_active_nutrition_plan()
    payload = json.loads(active["meals_json"]) if active["meals_json"] else None
    enabled = meal_switch_enabled(ledger, active, payload)
    context = {"date": today.isoformat(), "plan_version_id": active["id"], "author": active["author"],
               "day_type": state["target_day_type"], "enabled": enabled,
               "targets": state["targets"],
               "can_swap": active["author"] == "Player"}
    if not enabled:
        if active["author"] == "Coach":
            return {**context, "status": "unavailable", "reason": "coach", "meals": []}
        available = cached_variants_for_plan(ledger, active, today, state["target_day_type"])
        variant = available["variants"][state["target_day_type"]]
        return {**variant, **context, "status": "disabled" if variant["status"] == "ready" else "unavailable", "meals": []}
    if payload and payload.get("enabled"):
        variant = resolve_variant(ledger, active, payload, state["target_day_type"])
    else:
        available = cached_variants_for_plan(ledger, active, today, state["target_day_type"])
        variant = available["variants"][state["target_day_type"]]
    if variant["status"] == "ready" and not state.get("meals"):
        variant = {"status": "unavailable", "reason": "staples", "meals": []}
    result = {**variant, **context, "targets_changed": bool(payload and payload.get("targets_changed", False))}
    result["meals"] = meals_with_food_macros(result["meals"])
    result["day_totals"] = variant.get("totals")
    return result


def _save_player_meals(ledger, active, payload):
    return save_meal_version(ledger, {**dict(active), "provenance": "player_consented"}, payload)


def enable(ledger, today):
    with ledger.ledger_transaction(immediate=True):
        state = read(ledger, today)
        if state.get("enabled"):
            if ledger.get_nutrition_meal_preference() is None:
                ledger.set_nutrition_meal_preference(True)
            return state
        if state["status"] != "disabled":
            raise ValueError("Meals aren't available yet. Reviewed Staple foods and practical portions are needed.")
        active = ledger.get_active_nutrition_plan()
        day_type = state["day_type"]
        available = cached_variants_for_plan(ledger, active, today, day_type)
        if available["variants"][day_type]["status"] != "ready":
            raise ValueError("Meals aren't available yet. Reviewed Staple foods and practical portions are needed.")
        payload = generate_variants(ledger, json.loads(active["targets_json"]), {})
        payload["variants"] = available["variants"]
        _save_player_meals(ledger, active, payload)
        ledger.set_nutrition_meal_preference(True)
    return read(ledger, today)


def disable(ledger, today):
    with ledger.ledger_transaction(immediate=True):
        active = ledger.get_active_nutrition_plan()
        if active is not None and active["author"] != "Player":
            raise ValueError("Your Coach sets your meals.")
        state = read(ledger, today)
        if not state.get("enabled"):
            if ledger.get_nutrition_meal_preference() is None:
                ledger.set_nutrition_meal_preference(False)
            return state
        _save_player_meals(ledger, active, {"enabled": False})
        ledger.set_nutrition_meal_preference(False)
    return read(ledger, today)


def refresh_setup(ledger):
    active = ledger.get_active_nutrition_plan()
    if active is None or active["author"] != "Player":
        return
    previous = json.loads(active["meals_json"]) if active["meals_json"] else None
    if not meal_switch_enabled(ledger, active, previous):
        return
    payload = generate_variants(ledger, json.loads(active["targets_json"]), previous or {})
    today = player_local_date(ledger, str(ledger.ledger_id))
    day_type = "training_day" if nutrition._is_training_day(ledger, today) else "rest_day"
    payload["variants"][day_type] = resolve_variant(ledger, active, payload, day_type)
    _save_player_meals(ledger, active, payload)


@dataclass(frozen=True)
class LogMealCommand:
    slot: str
    plan_version_id: int
    entry_date: date
    today: date


def _entry(food, meal, today):
    label = meal.get("log_label") or ("snack" if meal["slot"].endswith("_snack") else meal["slot"])
    minutes = SLOT_MINUTES.get(meal["slot"], SLOT_MINUTES.get(label, 16 * 60 if label == "snack" else 13 * 60))
    return {"id": str(uuid4()), "entry_date": today.isoformat(), "kind": "library_food",
            "food_id": food["id"], "name": food["name"], "arabic_name": food["arabic_name"],
            "grams": food["grams"], "quantity": food["grams"], "unit": "grams",
            "portion_label": food["portion_label"], "portion_grams": food["portion_grams"],
            "nutrients_per_100g": food["nutrients_per_100g"],
            "nutrients": {key: round(amount * food["grams"] / 100, 2)
                          for key, amount in food["nutrients_per_100g"].items()},
            "meal_label": label,
            # Snack times retain the chosen slot when the Food log groups it.
            "logged_time": f"{minutes // 60:02d}:{minutes % 60:02d}",
            "created_at": datetime.now(UTC).isoformat(timespec="microseconds")}


def log_meal(ledger, command):
    with ledger.ledger_transaction(immediate=True):
        state = read(ledger, command.today)
        if (command.entry_date != command.today or state.get("plan_version_id") != command.plan_version_id):
            raise ValueError("The day or Nutrition plan changed. Refresh meals and try again.")
        if state["status"] != "ready":
            raise ValueError("Meals aren't available yet.")
        meal = next((meal for meal in state["meals"] if meal["slot"] == command.slot), None)
        if meal is None:
            raise ValueError("This Meal slot is unavailable.")
        entries = [_entry(food, meal, command.today) for food in meal["foods"]]
        for entry in entries:
            ledger.insert_food_log_entry(entry)
        recompute_day(ledger, command.today, command.today)
    return entries
