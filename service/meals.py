"""Enable Nutrition plan meals and copy their snapshots into the Food log."""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

from core.meal_setup import SLOT_MINUTES
from database.ledger.nutrition import NutritionPlanVersion
from database.nutrition_meals import generate_variants
from service import nutrition
from service.food_log_adherence import recompute_day


def read(ledger, today):
    state = nutrition.read(ledger, today=today)
    if state["state"] != "ready":
        return {"status": "unavailable", "reason": "targets", "meals": [], "enabled": False}
    active = ledger.get_active_nutrition_plan()
    payload = json.loads(active["meals_json"]) if active["meals_json"] else None
    context = {"date": today.isoformat(), "plan_version_id": active["id"], "author": active["author"],
               "day_type": state["target_day_type"], "enabled": bool(payload and payload["enabled"])}
    if not payload:
        available = generate_variants(ledger, json.loads(active["targets_json"]), {})
        variant = available["variants"][state["target_day_type"]]
        return {**variant, **context, "status": "disabled" if variant["status"] == "ready" else "unavailable", "meals": []}
    variant = payload["variants"][state["target_day_type"]]
    if variant["status"] == "ready" and not state.get("meals"):
        variant = {"status": "unavailable", "reason": "staples", "meals": []}
    return {**variant, **context, "targets_changed": payload.get("targets_changed", False)}


def _save_player_meals(ledger, active, payload):
    snapshot = ledger.get_nutrition_goal_offer_snapshot(active["id"])
    return ledger.save_nutrition_plan(NutritionPlanVersion(
        goal=active["goal"], reason=json.loads(active["goal_reason_data_json"]),
        intensity=active["intensity"], daily_activity=active["daily_activity"],
        targets=json.loads(active["targets_json"]), author="Player", provenance="player_consented", meals=payload,
        goal_source_snapshot=json.loads(snapshot[0]) if snapshot else None,
    ))


def enable(ledger, today):
    with ledger.ledger_transaction(immediate=True):
        state = read(ledger, today)
        if state.get("enabled"):
            return state
        if state["status"] != "disabled":
            raise ValueError("Meals aren't available yet. Reviewed Staple foods and practical portions are needed.")
        active = ledger.get_active_nutrition_plan()
        payload = generate_variants(ledger, json.loads(active["targets_json"]), {})
        if any(variant["status"] != "ready" for variant in payload["variants"].values()):
            raise ValueError("Meals aren't available yet for both training and rest days.")
        _save_player_meals(ledger, active, payload)
    return read(ledger, today)


def refresh_setup(ledger):
    active = ledger.get_active_nutrition_plan()
    if active is None or active["author"] != "Player" or not active["meals_json"]:
        return
    previous = json.loads(active["meals_json"])
    payload = generate_variants(ledger, json.loads(active["targets_json"]), previous)
    _save_player_meals(ledger, active, payload)


@dataclass(frozen=True)
class LogMealCommand:
    slot: str
    plan_version_id: int
    entry_date: date
    today: date


def _entry(food, meal, today):
    minutes = SLOT_MINUTES[meal["slot"]]
    return {"id": str(uuid4()), "entry_date": today.isoformat(), "kind": "library_food",
            "food_id": food["id"], "name": food["name"], "arabic_name": food["arabic_name"],
            "grams": food["grams"], "quantity": food["grams"], "unit": "grams",
            "portion_label": food["portion_label"], "portion_grams": food["portion_grams"],
            "nutrients_per_100g": food["nutrients_per_100g"],
            "nutrients": {key: round(amount * food["grams"] / 100, 2)
                          for key, amount in food["nutrients_per_100g"].items()},
            "meal_label": "snack" if meal["slot"].endswith("_snack") else meal["slot"],
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
