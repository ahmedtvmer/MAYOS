"""Meal setup persistence, private restrictions and visible search warnings (#480)."""

import json
import sqlite3

import pytest

from core.meal_setup import ALLERGENS, MEAL_LAYOUTS, meal_slot, restriction_reasons, vegetarian_category
from database.migration_manager import apply_lazy_migrations, get_ledger_schema_version, set_ledger_schema_version
from tests.test_food_log_api import _add, _personal, food_api  # noqa: F401
from tests.test_nutrition_api import api  # noqa: F401


def _setup(count=5):
    return {"meal_count": count, "training_time": "morning",
            "restrictions": {"allergies": ["eggs", "milk"], "vegetarian": True, "dislikes": ["rice"]}}


@pytest.mark.parametrize("count", [3, 4, 5])
def test_setup_round_trips_in_private_ledger_without_changing_targets(food_api, count):
    client, db, headers, _today = food_api
    before = client.get("/nutrition", headers=headers).json()
    saved = client.put("/nutrition/meal-setup", headers=headers, json=_setup(count))
    assert saved.status_code == 200, saved.text
    assert saved.json()["slots"] == list(MEAL_LAYOUTS[count])
    assert saved.json()["restrictions"] == _setup(count)["restrictions"]
    assert saved.json()["disliked_foods"] == [{"id": "rice", "name": "Rice", "arabic_name": "أرز"}]
    assert client.get("/nutrition/meal-setup", headers=headers).json() == saved.json()
    after = client.get("/nutrition", headers=headers).json()
    assert after["targets"] == before["targets"]
    assert after["authority"] == before["authority"]
    account = db.get_active_account_by_username("food-player")
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert ledger.get_meal_setup() == _setup(count)
        assert get_ledger_schema_version(ledger.conn) >= 58
    assert db.catalog_conn.execute("SELECT 1 FROM sqlite_master WHERE name='meal_setup'").fetchone() is None
    other = client.post("/auth/register", json={"trainee_id": "other-meals", "password": "correct-horse-1"}).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get("/nutrition/meal-setup", headers=other_headers).json()["restrictions"] == {
        "allergies": [], "dislikes": [], "vegetarian": False}


def test_search_keeps_restricted_foods_with_all_reasons_and_ignores_drafts(food_api):
    client, db, headers, today = food_api
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET allergens_json=?, allergens_reviewed=1 WHERE id='egg'",
                           (json.dumps(["eggs", "milk"]),))
        connection.execute("UPDATE foods SET vegetarian=0 WHERE id='staple'")
        connection.execute("UPDATE foods SET allergens_json='[\"milk\"]', allergens_reviewed=0 WHERE id='rice'")
        connection.commit()
    assert client.put("/nutrition/meal-setup", headers=headers, json=_setup()).status_code == 200
    for query, food_id, reasons in (("egg", "egg", ["milk", "eggs"]),
                                     ("chicken", "staple", ["vegetarian"]),
                                     ("rice", "rice", ["disliked"])):
        foods = client.get("/nutrition/foods", headers=headers, params={"q": query}).json()["foods"]
        assert next(food for food in foods if food["id"] == food_id)["restriction_reasons"] == reasons
    assert _add(client, headers, today, food="egg").status_code == 201
    recent = client.get("/nutrition/foods", headers=headers).json()["foods"]
    assert recent[0]["restriction_reasons"] == ["milk", "eggs"]
    unknown = _setup()
    unknown["restrictions"]["dislikes"] = ["missing-food"]
    assert client.put("/nutrition/meal-setup", headers=headers, json=unknown).status_code == 400
    assert client.get("/nutrition/meal-setup", headers=headers).json()["restrictions"] == _setup()["restrictions"]


def test_dislike_is_a_specific_owned_food_and_can_be_removed(food_api):
    client, _db, headers, _today = food_api
    food = _personal(client, headers).json()
    setup = _setup()
    setup["restrictions"] = {"allergies": [], "vegetarian": False, "dislikes": [food["id"]]}
    response = client.put("/nutrition/meal-setup", headers=headers, json=setup)
    assert response.status_code == 200, response.text
    assert response.json()["disliked_foods"][0]["name"] == food["name"]
    foods = client.get("/nutrition/foods?q=chicken", headers=headers).json()["foods"]
    assert next(row for row in foods if row["id"] == food["id"])["restriction_reasons"] == ["disliked"]
    assert next(row for row in foods if row["id"] == "exact")["restriction_reasons"] == []
    setup["restrictions"]["dislikes"] = []
    assert client.put("/nutrition/meal-setup", headers=headers, json=setup).status_code == 200
    foods = client.get("/nutrition/foods?q=chicken", headers=headers).json()["foods"]
    assert next(row for row in foods if row["id"] == food["id"])["restriction_reasons"] == []


@pytest.mark.parametrize(("count", "time", "expected"), [
    (5, "09:00", "morning_snack"), (5, "13:00", "morning_snack"),
    (5, "13:01", "afternoon_snack"), (5, "23:59", "afternoon_snack"),
    (4, "09:00", "afternoon_snack"), (3, "09:00", "breakfast"),
    (3, "15:00", "lunch"), (3, "23:59", "dinner"),
])
def test_food_log_maps_snack_to_nearest_available_slot(food_api, count, time, expected):
    client, _db, headers, today = food_api
    assert client.put("/nutrition/meal-setup", headers=headers, json=_setup(count)).status_code == 200
    assert _add(client, headers, today, meal_label="snack", logged_time=time).status_code == 201
    day = client.get("/nutrition/food-log", headers=headers).json()
    assert day["entries"][0]["meal_slot"] == expected
    assert day["entries"][0]["meal_label"] == "snack"
    assert day["meal_slots"] == list(MEAL_LAYOUTS[count])
    assert meal_slot("lunch", time, count) == "lunch"


@pytest.mark.parametrize("tag", ALLERGENS)
def test_each_fixed_allergen_matches_only_reviewed_tags(tag):
    restrictions = {"allergies": [tag], "vegetarian": False, "dislikes": []}
    food = {"id": "food", "allergens": [tag], "allergens_reviewed": True}
    assert restriction_reasons(food, restrictions) == [tag]
    assert restriction_reasons({**food, "allergens_reviewed": False}, restrictions) == []


@pytest.mark.parametrize(("category", "allowed"), [
    ("Poultry Products", False), ("Beef Products", False),
    ("Finfish and Shellfish Products", False), ("Chicken", False),
    ("Dairy and Egg Products", True), ("Legumes and Legume Products", True),
])
def test_vegetarian_uses_source_category(category, allowed):
    assert vegetarian_category(category) is allowed


def test_lazy_v58_migration_preserves_existing_food_log(tmp_path):
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE food_log_entries(id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO food_log_entries VALUES('existing')")
        set_ledger_schema_version(connection, 57)
        connection.commit()
        apply_lazy_migrations(connection, "meals", tmp_path / "users", tmp_path / "backups")
        apply_lazy_migrations(connection, "meals", tmp_path / "users", tmp_path / "backups")
        connection.execute("INSERT INTO meal_setup VALUES(1,4,'afternoon','{}')")
        assert connection.execute("SELECT meal_count FROM meal_setup").fetchone() == (4,)
        assert connection.execute("SELECT id FROM food_log_entries").fetchone() == ("existing",)
