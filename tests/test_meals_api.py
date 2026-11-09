"""Enable, regenerate and log meals through HTTP and real migrated ledgers."""

import json
import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest

from database.food_library.builder import NUTRIENTS
from database.food_library.seeding import FoodLibraryPaths, seed_food_library
from database.ledger.nutrition import NutritionPlanVersion
from database.migration_manager import apply_lazy_migrations, set_ledger_schema_version
from service import meals, nutrition
from tests.test_food_log_api import _csv
from tests.test_nutrition_api import api, _player_today, _seed_profile  # noqa: F401


@pytest.fixture
def meals_api(api, tmp_path):
    client, db = api
    paths = FoodLibraryPaths(*(tmp_path / name for name in ("meal_foods.csv", "meal_portions.csv", "meal_curation.csv", "meal_recipes.csv", "meal_allergens.csv")))
    sources = [
        {"id": "protein", "name": "Areesh", "protein_g": 30, "energy_kcal": 120},
        {"id": "alternative", "name": "Alternative protein", "protein_g": 30, "energy_kcal": 120},
        {"id": "carb", "name": "Rice", "carbohydrate_g": 50, "energy_kcal": 200},
        {"id": "fat", "name": "Olive oil", "fat_g": 100, "energy_kcal": 900},
    ]
    _csv(paths.foods, ["id", "name", "category", "source", *NUTRIENTS], [
        {**dict.fromkeys(NUTRIENTS, 0), "category": "Food", "source": "SR Legacy", **row} for row in sources])
    curation = [{"id": row["id"], "display_name": row["name"], "reviewed": "true", "hidden": "false",
                 "staple_roles": "protein" if row["id"] in ("protein", "alternative") else "carb" if row["id"] == "carb" else "vegetable_fat"}
                for row in sources]
    curation[-1].update(portion_label="local portion", portion_grams=1)
    _csv(paths.curation, ["id", "display_name", "reviewed", "hidden", "staple_roles", "portion_label", "portion_grams"], curation)
    _csv(paths.portions, ["food_id", "label", "gram_weight"], [])
    _csv(paths.recipes, ["id", "display_name", "ingredient_fdc_id", "grams"], [])
    _csv(paths.allergens, ["id", "allergens", "reviewed"], [])
    with db.catalog_locked() as connection:
        seed_food_library(connection, paths)
    registered = client.post("/auth/register", json={"trainee_id": "meal-player", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "meal-player", age=30, target=None)
    setup = client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False}})
    assert setup.status_code == 200, setup.text
    return client, db, headers, _player_today(db, "meal-player")


def _ledger_id(db):
    return db.get_active_account_by_username("meal-player")["ledger_id"]


def _enable(client, headers):
    response = client.post("/nutrition/meals/enable", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _disable(client, headers):
    response = client.post("/nutrition/meals/disable", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_disable_versions_the_plan_keeps_logged_food_and_regenerates_when_enabled(meals_api, recording_analytics):
    client, db, headers, today = meals_api
    enabled = _enable(client, headers)
    logged = client.post("/nutrition/meals/log", headers=headers, json={
        "slot": "breakfast", "entry_date": today.isoformat(), "plan_version_id": enabled["plan_version_id"]})
    assert logged.status_code == 201, logged.text
    entries = client.get("/nutrition/food-log", headers=headers).json()["entries"]
    targets = client.get("/nutrition", headers=headers).json()["targets"]

    disabled = _disable(client, headers)
    assert disabled["status"] == "disabled" and disabled["enabled"] is False
    assert disabled["meals"] == [] and disabled["plan_version_id"] > enabled["plan_version_id"]
    assert client.get("/nutrition/meals", headers=headers).json() == disabled
    nutrition_state = client.get("/nutrition", headers=headers).json()
    assert nutrition_state["meals"] == []
    assert nutrition_state["targets"] == targets and nutrition_state["authority"] == "player"
    assert client.get("/nutrition/food-log", headers=headers).json()["entries"] == entries
    with db.open_ledger(_ledger_id(db)) as ledger:
        active = ledger.get_active_nutrition_plan()
        assert active["author"] == "Player" and json.loads(active["meals_json"])["enabled"] is False

    # Saving setup while off must not silently turn meals on (#676).
    changed = client.put("/nutrition/meal-setup", headers=headers, json={
        "meal_count": 4, "training_time": "evening",
        "restrictions": {"allergies": [], "dislikes": [], "vegetarian": False}})
    assert changed.status_code == 200, changed.text
    assert client.get("/nutrition/meals", headers=headers).json()["status"] == "disabled"
    regenerated = _enable(client, headers)
    assert regenerated["plan_version_id"] > disabled["plan_version_id"]
    assert regenerated["enabled"] and len(regenerated["meals"]) == 4
    assert client.get("/nutrition/food-log", headers=headers).json()["entries"] == entries
    assert len([event for event in recording_analytics.events if event["event"] == "nutrition_meals_turned_off"]) == 1


@pytest.mark.parametrize("previously_enabled", [False, True])
def test_disable_when_already_off_creates_no_version_or_event(meals_api, recording_analytics, previously_enabled):
    client, db, headers, _today = meals_api
    if previously_enabled:
        _enable(client, headers)
        _disable(client, headers)
    before = client.get("/nutrition/meals", headers=headers).json()
    off_events = [event for event in recording_analytics.events if event["event"] == "nutrition_meals_turned_off"]
    with db.open_ledger(_ledger_id(db)) as ledger:
        versions_before = ledger.conn.execute("SELECT count(*) FROM nutrition_plan_versions").fetchone()[0]
    assert _disable(client, headers) == before
    with db.open_ledger(_ledger_id(db)) as ledger:
        assert ledger.conn.execute("SELECT count(*) FROM nutrition_plan_versions").fetchone()[0] == versions_before
    assert [event for event in recording_analytics.events if event["event"] == "nutrition_meals_turned_off"] == off_events


def test_coach_authored_meals_cannot_be_disabled_without_an_active_assignment(meals_api):
    client, db, headers, _today = meals_api
    _enable(client, headers)
    with db.open_ledger(_ledger_id(db)) as ledger, ledger.ledger_transaction():
        active = ledger.get_active_nutrition_plan()
        ledger.save_nutrition_plan(NutritionPlanVersion(
            goal="maintain", reason={"code": "coach"}, intensity=None, daily_activity="mostly_sitting",
            targets=json.loads(active["targets_json"]), author="Coach", provenance="coach",
            meals=json.loads(active["meals_json"])))
    before = client.get("/nutrition/meals", headers=headers).json()
    refused = client.post("/nutrition/meals/disable", headers=headers)
    assert refused.status_code == 400
    assert client.get("/nutrition/meals", headers=headers).json() == before


def test_enable_versions_the_plan_once_and_emits_allowlisted_analytics(meals_api, recording_analytics):
    client, db, headers, _today = meals_api
    before = client.get("/nutrition", headers=headers).json()
    assert client.get("/nutrition/meals", headers=headers).json()["status"] == "disabled"
    enabled = _enable(client, headers)
    assert enabled["enabled"] and enabled["status"] == "ready"
    assert enabled["plan_version_id"] == 2
    assert enabled["meals"][0]["foods"][0]["id"] == "protein"  # Curation order, not id order.
    assert _enable(client, headers)["plan_version_id"] == enabled["plan_version_id"]
    after = client.get("/nutrition", headers=headers).json()
    assert after["targets"] == before["targets"] and after["authority"] == before["authority"]
    assert after["meals"] == enabled["meals"]
    with db.open_ledger(_ledger_id(db)) as ledger:
        rows = ledger.conn.execute("SELECT meals_json FROM nutrition_plan_versions ORDER BY id").fetchall()
        assert len(rows) == 2 and rows[0][0] is None
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            ledger.conn.execute("UPDATE nutrition_plan_versions SET meals_json='{}'")
    events = [event for event in recording_analytics.events if event["event"] == "nutrition_meals_turned_on"]
    assert len(events) == 1


def test_no_reviewed_staples_means_no_enable_or_new_version(meals_api):
    client, db, headers, _today = meals_api
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET reviewed=0")
        connection.commit()
    state = client.get("/nutrition/meals", headers=headers).json()
    assert state["status"] == "unavailable" and state["reason"] == "staples" and not state["meals"]
    refused = client.post("/nutrition/meals/enable", headers=headers)
    assert refused.status_code == 400 and "aren't available yet" in refused.json()["detail"]
    with db.open_ledger(_ledger_id(db)) as ledger:
        assert ledger.get_active_nutrition_plan()["id"] == 1


def test_training_schedule_selects_the_stored_day_variant_and_snacks_log_to_their_slot(meals_api):
    client, db, headers, today = meals_api
    saved = client.put("/nutrition/meal-setup", headers=headers, json={
        "meal_count": 5, "training_time": "evening",
        "restrictions": {"allergies": [], "dislikes": [], "vegetarian": False}})
    assert saved.status_code == 200, saved.text
    with db.open_ledger(_ledger_id(db)) as ledger:
        ledger.append_training_schedule(ledger.ledger_id, [today.isoweekday()], "UTC", today.isoformat(),
                                        "2026-01-01T00:00:00Z")
    plan = _enable(client, headers)
    assert plan["day_type"] == "training_day"
    near = [meal["targets"]["carbs_g"] for meal in plan["meals"] if meal["slot"] in ("afternoon_snack", "dinner")]
    far = [meal["targets"]["carbs_g"] for meal in plan["meals"] if meal["slot"] not in ("afternoon_snack", "dinner")]
    assert min(near) > max(far)
    logged = client.post("/nutrition/meals/log", headers=headers, json={
        "slot": "morning_snack", "entry_date": today.isoformat(), "plan_version_id": plan["plan_version_id"]})
    assert logged.status_code == 201, logged.text
    day = client.get("/nutrition/food-log", headers=headers).json()
    assert {entry["meal_slot"] for entry in day["entries"]} == {"morning_snack"}


def test_revoked_review_blocks_logging_saved_meals(meals_api):
    client, db, headers, today = meals_api
    plan = _enable(client, headers)
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET reviewed=0 WHERE id='protein'")
        connection.commit()
    state = client.get("/nutrition/meals", headers=headers).json()
    assert state["status"] == "unavailable" and state["meals"] == []
    assert client.get("/nutrition", headers=headers).json()["meals"] == []
    refused = client.post("/nutrition/meals/log", headers=headers, json={
        "slot": "breakfast", "entry_date": today.isoformat(), "plan_version_id": plan["plan_version_id"]})
    assert refused.status_code == 409
    assert client.get("/nutrition/food-log", headers=headers).json()["entries"] == []


def test_player_assistant_receives_meals_within_the_tool_result_cap(meals_api):
    from agent.player_tools import MAX_TOOL_RESULT_BYTES

    client, db, headers, today = meals_api
    plan = _enable(client, headers)
    with db.open_ledger(_ledger_id(db)) as ledger:
        projection = nutrition.assistant_projection(ledger, today)
    assert projection["meals"][0] == {"slot": "breakfast", "foods": [
        {"name": food["name"], "grams": food["grams"],
         **({"arabic_name": food["arabic_name"]} if food["arabic_name"] else {})}
        for food in plan["meals"][0]["foods"]]}
    assert len(json.dumps(projection, ensure_ascii=False).encode("utf8")) < MAX_TOOL_RESULT_BYTES


def test_logging_copies_food_snapshots_without_changing_the_plan(meals_api):
    client, _db, headers, today = meals_api
    plan = _enable(client, headers)
    planned = plan["meals"][0]
    response = client.post("/nutrition/meals/log", headers=headers, json={
        "slot": planned["slot"], "entry_date": today.isoformat(), "plan_version_id": plan["plan_version_id"]})
    assert response.status_code == 201, response.text
    copied = response.json()["entries"]
    assert [(food["food_id"], food["grams"], food["nutrients_per_100g"]) for food in copied] == [
        (food["id"], food["grams"], food["nutrients_per_100g"]) for food in planned["foods"]]
    day = client.get("/nutrition/food-log", headers=headers).json()
    assert len(day["entries"]) == 3
    assert day["totals"]["energy_kcal"] == pytest.approx(planned["totals"]["calories"], abs=.02)
    entry = copied[0]
    edited = client.put(f"/nutrition/food-log/{entry['id']}", headers=headers, json={
        "quantity": entry["grams"] + 10, "unit": "grams", "meal_label": "breakfast", "logged_time": "08:00"})
    assert edited.status_code == 200, edited.text
    assert client.get("/nutrition/meals", headers=headers).json() == plan


@pytest.mark.parametrize("stale", ["day", "version"])
def test_logging_rejects_stale_day_or_plan_without_partial_entries(meals_api, stale):
    client, _db, headers, today = meals_api
    plan = _enable(client, headers)
    response = client.post("/nutrition/meals/log", headers=headers, json={
        "slot": "breakfast", "entry_date": (today - timedelta(days=1) if stale == "day" else today).isoformat(),
        "plan_version_id": plan["plan_version_id"] - (stale == "version")})
    assert response.status_code == 409
    assert client.get("/nutrition/food-log", headers=headers).json()["entries"] == []


@pytest.mark.parametrize("change", ["goal", "activity", "proposal"])
def test_every_target_write_regenerates_enabled_player_meals(meals_api, change):
    client, db, headers, today = meals_api
    before = _enable(client, headers)
    if change == "goal":
        response = client.put("/nutrition/goal", headers=headers, json={
            "goal": "lose", "intensity": "light", "screening": {
                "pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False}})
    elif change == "activity":
        response = client.put("/nutrition/activity", headers=headers, json={"daily_activity": "on_feet"})
    else:
        with db.open_ledger(_ledger_id(db)) as ledger:
            active = ledger.get_active_nutrition_plan()
            targets = json.loads(active["targets_json"])
            with ledger.ledger_transaction():
                proposal_id = ledger.create_nutrition_pace_proposal(active["id"], {
                    "goal": "maintain", "intensity": None, "targets": {**targets, "calories": targets["calories"] + 100},
                }, today.isoformat())
        response = client.post(f"/nutrition/pace-proposals/{proposal_id}/decision", headers=headers, json={"decision": "accepted"})
    assert response.status_code == 200, response.text
    after = client.get("/nutrition/meals", headers=headers).json()
    assert after["plan_version_id"] > before["plan_version_id"] and after["status"] == "ready"
    assert after["meals"][0]["targets"] != before["meals"][0]["targets"]


def test_swaps_survive_target_changes_until_strictly_restricted(meals_api):
    client, db, headers, _today = meals_api
    _enable(client, headers)
    with db.open_ledger(_ledger_id(db)) as ledger:
        active = ledger.get_active_nutrition_plan()
        payload = json.loads(active["meals_json"])
        for variant in payload["variants"].values():
            variant["meals"][0]["foods"][0].update(id="alternative", swapped=True)
        with ledger.ledger_transaction():
            meals._save_player_meals(ledger, active, payload)
    changed = client.put("/nutrition/activity", headers=headers, json={"daily_activity": "on_feet"})
    assert changed.status_code == 200, changed.text
    assert client.get("/nutrition/meals", headers=headers).json()["meals"][0]["foods"][0]["id"] == "alternative"
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET allergens_json='[\"milk\"]', allergens_reviewed=1 WHERE id='alternative'")
        connection.commit()
    saved = client.put("/nutrition/meal-setup", headers=headers, json={"meal_count": 3, "training_time": "evening",
        "restrictions": {"allergies": ["milk"], "dislikes": [], "vegetarian": False}})
    assert saved.status_code == 200, saved.text
    assert client.get("/nutrition/meals", headers=headers).json()["meals"][0]["foods"][0]["id"] == "protein"


def test_coach_target_edits_preserve_coach_meals_with_notice_and_gate_enable(meals_api, monkeypatch):
    client, db, headers, today = meals_api
    _enable(client, headers)
    with db.open_ledger(_ledger_id(db)) as ledger:
        active = ledger.get_active_nutrition_plan()
        plan = NutritionPlanVersion(goal="maintain", reason={"code": "coach"}, intensity=None,
            daily_activity="mostly_sitting", targets=json.loads(active["targets_json"]),
            author="Coach", provenance="coach", authority_assignment_id="assignment")
        with ledger.ledger_transaction():
            ledger.save_nutrition_plan(plan)
        before = json.loads(ledger.get_active_nutrition_plan()["meals_json"])
        with ledger.ledger_transaction():
            ledger.save_nutrition_plan(replace(plan, targets={**plan.targets, "calories": plan.targets["calories"] + 100}))
        after = json.loads(ledger.get_active_nutrition_plan()["meals_json"])
        assert after["variants"] == before["variants"] and after["targets_changed"]
        assert nutrition.coach_read(ledger, today, "assignment")["meals_targets_changed"]
    monkeypatch.setattr(db, "get_active_assignment_for_player", lambda _account: {"assignment_id": "assignment"})
    assert client.post("/nutrition/meals/enable", headers=headers).status_code == 403
    assert client.post("/nutrition/meals/disable", headers=headers).status_code == 403
    assert client.get("/nutrition/meals", headers=headers).json()["targets_changed"]


def test_lazy_v57_adds_meals_without_rewriting_existing_versions(tmp_path):
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE nutrition_plan_versions(id INTEGER PRIMARY KEY, targets_json TEXT)")
        connection.execute("INSERT INTO nutrition_plan_versions VALUES(1,'{\"calories\":2000}')")
        set_ledger_schema_version(connection, 56)
        connection.commit()
        apply_lazy_migrations(connection, "meal-player", tmp_path / "users", tmp_path / "backups")
        assert connection.execute("SELECT targets_json, meals_json FROM nutrition_plan_versions").fetchone() == ('{"calories":2000}', None)
