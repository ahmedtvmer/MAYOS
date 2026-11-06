"""Player Food log write window, immutable food snapshots and day totals."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from core.food_search import food_match_rank, normalize_food_query
from service import nutrition
from service.food_log_adherence import recompute_day
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
    totals = {key: round(sum(entry["nutrients"].get(key) or 0 for entry in entries), 2) for key in NUTRIENT_KEYS}
    nutrition_state = nutrition.read(ledger, today=entry_date)
    targets = (nutrition.targets_for_day(ledger, entry_date) if entry_date < today
               else nutrition_state.get("targets"))
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
    food = (ledger.get_personal_food(body["food_id"]) if body["food_id"].startswith("personal:")
            else db.get_food_library_food(body["food_id"]))
    if food is None:
        raise FoodLogNotFound("Food is unavailable.")
    entry = _apply_amount({
        "id": str(uuid4()), "entry_date": entry_date.isoformat(), "kind": food.get("kind", "library_food"),
        "food_id": food["id"], "name": food["name"],
        "arabic_name": food["arabic_name"] if food["reviewed"] else None,
        "portion_label": food["portion_label"], "portion_grams": food["portion_grams"],
        "nutrients_per_100g": {key: float(food["nutrients"].get(key) or 0) for key in NUTRIENT_KEYS},
        "created_at": datetime.now(UTC).isoformat(timespec="microseconds"),
    }, {**body, "logged_time": body["logged_time"] or local_time})
    with ledger.ledger_transaction():
        ledger.insert_food_log_entry(entry)
        recompute_day(ledger, entry_date, today)
    return entry


def edit_entry(ledger, entry_id, body, today):
    with ledger.ledger_transaction(immediate=True):
        entry = ledger.get_food_log_entry(entry_id)
        if entry is None:
            raise FoodLogNotFound("Food log entry not found.")
        require_write_day(date.fromisoformat(entry["entry_date"]), today)
        if entry["kind"] == "quick_add":
            raise ValueError("Use the Quick add editor for this entry.")
        updated = _apply_amount(entry, {**body, "logged_time": body["logged_time"] or entry["logged_time"]})
        ledger.update_food_log_entry(updated)
        recompute_day(ledger, date.fromisoformat(entry["entry_date"]), today)
    return updated


def delete_entry(ledger, entry_id, today):
    with ledger.ledger_transaction(immediate=True):
        entry = ledger.get_food_log_entry(entry_id)
        if entry is None:
            raise FoodLogNotFound("Food log entry not found.")
        require_write_day(date.fromisoformat(entry["entry_date"]), today)
        ledger.delete_food_log_entry(entry_id)
        recompute_day(ledger, date.fromisoformat(entry["entry_date"]), today)


def local_time(ledger, player_id):
    timezone = timezone_for_versions(ledger.list_training_schedules(player_id), "UTC")
    return datetime.now(UTC).astimezone(ZoneInfo(timezone)).strftime("%H:%M")


def _matching_personal_foods(foods, query):
    matches = []
    for food in foods:
        name = normalize_food_query(food["name"])
        rank = food_match_rank((name,), (), query)
        if rank is not None:
            matches.append((rank, name, food["id"], food))
    return [item[-1] for item in sorted(matches)]


def _recent_foods(foods, usage):
    used = {key: value for key, value in usage.items() if key in foods}
    recent = sorted(used, key=lambda key: (used[key]["last_logged"], key), reverse=True)[:10]
    frequent = sorted(used, key=lambda key: (-used[key]["count"], key))[:10]
    return [{**foods[key], "kind": foods[key].get("kind", "library_food"),
             "logged_count": used[key]["count"]} for key in dict.fromkeys([*recent, *frequent])]


def search_foods(db, ledger, query):
    usage = ledger.food_log_usage()
    personal = ledger.list_personal_foods()
    normalized = normalize_food_query(query)
    library = db.search_food_library(query, usage)
    if normalized:
        personal = _matching_personal_foods(personal, normalized)
        return ([{**food, "logged_count": usage.get(food["id"], {}).get("count", 0)}
                 for food in personal] + [{**food, "kind": "library_food"} for food in library])[:50]
    return _recent_foods({food["id"]: food for food in [*personal, *library]}, usage)


def create_personal_food(ledger, body):
    portion_grams = body["portion_grams"]
    food = {"id": f"personal:{uuid4()}", "name": body["name"],
            "nutrients": {key: (body[key] / portion_grams * 100 if body["basis"] == "portion" else body[key])
                          for key in NUTRIENT_KEYS},
            "portion_label": body["portion_label"], "portion_grams": portion_grams,
            "created_at": datetime.now(UTC).isoformat(timespec="microseconds")}
    with ledger.ledger_transaction():
        ledger.insert_personal_food(food)
    return {**food, "kind": "personal_food", "reviewed": True, "arabic_name": None}


def add_quick_entry(ledger, body, today, current_time):
    require_write_day(body["entry_date"], today)
    entry = {"id": str(uuid4()), "entry_date": body["entry_date"].isoformat(),
             "kind": "quick_add", "food_id": None, "name": "quick_add", "arabic_name": None,
             "grams": None, "unit": None, "quantity": None, "portion_label": None,
             "portion_grams": None, "nutrients_per_100g": None,
             "nutrients": {key: body[key] for key in NUTRIENT_KEYS},
             "meal_label": body["meal_label"], "logged_time": body["logged_time"] or current_time,
             "created_at": datetime.now(UTC).isoformat(timespec="microseconds")}
    with ledger.ledger_transaction():
        ledger.insert_food_log_entry(entry)
    return entry


def edit_quick_entry(ledger, entry_id, body, today):
    with ledger.ledger_transaction(immediate=True):
        entry = ledger.get_food_log_entry(entry_id)
        if entry is None:
            raise FoodLogNotFound("Food log entry not found.")
        require_write_day(date.fromisoformat(entry["entry_date"]), today)
        if entry["kind"] != "quick_add":
            raise ValueError("This entry is not a Quick add.")
        updated = {**entry, "nutrients": {key: body[key] for key in NUTRIENT_KEYS},
                   "meal_label": body["meal_label"], "logged_time": body["logged_time"] or entry["logged_time"]}
        ledger.update_food_log_entry(updated)
    return updated


def yesterday_meals(ledger, today):
    entries = ledger.list_food_log_entries(today - timedelta(days=1))
    return [label for label in ("breakfast", "lunch", "dinner", "snack")
            if any(entry["meal_label"] == label for entry in entries)]


def copy_meal(ledger, meal_label, today, current_time):
    with ledger.ledger_transaction(immediate=True):
        entries = [entry for entry in ledger.list_food_log_entries(today - timedelta(days=1))
                   if entry["meal_label"] == meal_label]
        if not entries:
            raise ValueError("Yesterday has no entries for this meal.")
        copied = []
        for entry in entries:
            new_entry = {**entry, "id": str(uuid4()), "entry_date": today.isoformat(),
                         "logged_time": current_time,
                         "created_at": datetime.now(UTC).isoformat(timespec="microseconds")}
            ledger.insert_food_log_entry(new_entry)
            copied.append(new_entry)
    return copied
