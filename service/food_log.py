"""Player Food log write window, immutable food snapshots and day totals."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from service import nutrition
from service.schedule import timezone_for_versions

NUTRIENT_KEYS = ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g")
TARGET_KEYS = dict(zip(NUTRIENT_KEYS, ("calories", "protein_g", "carbs_g", "fat_g")))


class FoodLogNotFound(ValueError):
    pass


class FoodLogReadOnly(ValueError):
    pass


def require_write_day(entry_date: date, today: date):
    if entry_date not in (today, today - timedelta(days=1)):
        raise FoodLogReadOnly("Food log entries can only be changed for today and yesterday.")


def read_day(ledger, entry_date, today):
    if entry_date > today:
        raise ValueError("Future Food log days are not available.")
    entries = ledger.list_food_log_entries(entry_date)
    totals = {key: round(sum(entry["nutrients"][key] for entry in entries), 2) for key in NUTRIENT_KEYS}
    nutrition_state = nutrition.read(ledger, today=entry_date)
    targets = nutrition_state.get("targets")
    remaining = {key: round(float(targets[TARGET_KEYS[key]]) - totals[key], 2)
                 for key in NUTRIENT_KEYS} if targets else None
    return {"date": entry_date.isoformat(), "today": today.isoformat(),
            "editable": entry_date in (today, today - timedelta(days=1)),
            "entries": entries, "totals": totals, "targets": targets, "remaining": remaining,
            "cardio_burned_kcal": nutrition_state.get("cardio_burned_kcal", 0)}


def _apply_amount(entry, body):
    quantity = body["quantity"]
    if body["unit"] == "portion" and not entry["portion_grams"]:
        raise ValueError("This food has no local portion. Choose grams.")
    grams = quantity if body["unit"] == "grams" else quantity * entry["portion_grams"]
    if not 0 < grams <= 10000:
        raise ValueError("Choose an amount above zero and at most 10,000 g.")
    return {**entry, "unit": body["unit"], "quantity": quantity, "grams": grams,
            "meal_label": body["meal_label"], "logged_time": body["logged_time"],
            "nutrients": {key: round(entry["nutrients_per_100g"][key] * grams / 100, 2)
                          for key in NUTRIENT_KEYS}}


def add_entry(db, ledger, body, today, local_time):
    entry_date = body["entry_date"]
    require_write_day(entry_date, today)
    food = db.get_food_library_food(body["food_id"])
    if food is None:
        raise FoodLogNotFound("Food is unavailable.")
    entry = _apply_amount({
        "id": str(uuid4()), "entry_date": entry_date.isoformat(), "kind": "library_food",
        "food_id": food["id"], "name": food["name"],
        "arabic_name": food["arabic_name"] if food["reviewed"] else None,
        "portion_label": food["portion_label"], "portion_grams": food["portion_grams"],
        "nutrients_per_100g": {key: float(food["nutrients"].get(key) or 0) for key in NUTRIENT_KEYS},
        "created_at": datetime.now(UTC).isoformat(timespec="microseconds"),
    }, {**body, "logged_time": body["logged_time"] or local_time})
    with ledger.ledger_transaction():
        ledger.insert_food_log_entry(entry)
    return entry


def edit_entry(ledger, entry_id, body, today):
    with ledger.ledger_transaction(immediate=True):
        entry = ledger.get_food_log_entry(entry_id)
        if entry is None:
            raise FoodLogNotFound("Food log entry not found.")
        require_write_day(date.fromisoformat(entry["entry_date"]), today)
        updated = _apply_amount(entry, {**body, "logged_time": body["logged_time"] or entry["logged_time"]})
        ledger.update_food_log_entry(updated)
    return updated


def delete_entry(ledger, entry_id, today):
    with ledger.ledger_transaction(immediate=True):
        entry = ledger.get_food_log_entry(entry_id)
        if entry is None:
            raise FoodLogNotFound("Food log entry not found.")
        require_write_day(date.fromisoformat(entry["entry_date"]), today)
        ledger.delete_food_log_entry(entry_id)


def local_time(ledger, player_id):
    timezone = timezone_for_versions(ledger.list_training_schedules(player_id), "UTC")
    return datetime.now(UTC).astimezone(ZoneInfo(timezone)).strftime("%H:%M")
