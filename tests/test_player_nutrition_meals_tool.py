"""Saved Nutrition meals are available to Player inference without a write path (#486)."""

import json

import pytest

from agent.player_tools import MAX_TOOL_RESULT_BYTES, build_player_read_tools, run_player_tool_calls
from database.ledger.nutrition import NutritionPlanVersion
from service import nutrition
from tests.test_meals_api import _enable, _ledger_id, meals_api  # noqa: F401
from tests.test_nutrition_api import api  # noqa: F401


def _nutrition_tool(ledger):
    tools, _definitions = build_player_read_tools(ledger)
    return next(tool for tool in tools if tool.name == "get_player_nutrition")


def _plan_rows(ledger):
    return [tuple(row) for row in ledger.conn.execute("SELECT * FROM nutrition_plan_versions ORDER BY id")]


@pytest.mark.parametrize("training_day", [False, True])
@pytest.mark.parametrize("author", ["Player", "Coach"])
def test_tool_reads_the_saved_day_variant_on_a_read_only_connection(meals_api, training_day, author):
    client, db, headers, today = meals_api
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET arabic_name='جبنة قريش' WHERE id='protein'")
        connection.commit()
    with db.open_ledger(_ledger_id(db)) as ledger:
        weekday = today.isoweekday() if training_day else today.isoweekday() % 7 + 1
        ledger.append_training_schedule(ledger.ledger_id, [weekday], "UTC", today.isoformat(),
                                        "2026-01-01T00:00:00Z")
    _enable(client, headers)
    with db.open_ledger(_ledger_id(db)) as ledger:
        active = ledger.get_active_nutrition_plan()
        payload = json.loads(active["meals_json"])
        if author == "Coach":
            with ledger.ledger_transaction():
                ledger.save_nutrition_plan(NutritionPlanVersion(
                    goal="maintain", reason={"code": "coach"}, intensity=None,
                    daily_activity="mostly_sitting", targets=json.loads(active["targets_json"]),
                    author="Coach", provenance="coach", authority_assignment_id="assignment", meals=payload,
                ))
        before = _plan_rows(ledger)
        changes = ledger.conn.total_changes
        ledger.conn.execute("PRAGMA query_only=ON")
        response = json.loads(_nutrition_tool(ledger).invoke({}))
        assert _plan_rows(ledger) == before
        assert ledger.conn.total_changes == changes
    day_type = "training_day" if training_day else "rest_day"
    assert response["status"] == "ok" and response["author"] == author
    assert response["day_type"] == day_type
    assert response["meals_enabled"] and response["next_offset"] is None
    assert response["meals"] == [{"slot": meal["slot"], "foods": [
        {"name": food["name"], "grams": food["grams"],
         **({"arabic_name": food["arabic_name"]} if food["arabic_name"] else {})}
        for food in meal["foods"]]} for meal in payload["variants"][day_type]["meals"]]
    assert "screening" not in response and "authority_assignment_id" not in response


def test_tool_does_not_generate_or_enable_meals_during_a_lookup(meals_api):
    _client, db, _headers, _today = meals_api
    with db.open_ledger(_ledger_id(db)) as ledger:
        before = _plan_rows(ledger)
        ledger.conn.execute("PRAGMA query_only=ON")
        response = json.loads(_nutrition_tool(ledger).invoke({}))
        assert _plan_rows(ledger) == before
    assert response["status"] == "ok" and response["targets"]
    assert not response["meals_enabled"] and response["meals"] == []


@pytest.mark.parametrize("restriction", ["review_revoked", "allergy", "vegetarian"])
def test_tool_withholds_saved_foods_that_are_no_longer_allowed(meals_api, restriction):
    client, db, headers, _today = meals_api
    _enable(client, headers)
    with db.catalog_locked() as connection:
        if restriction == "review_revoked":
            connection.execute("UPDATE foods SET reviewed=0 WHERE id='protein'")
        elif restriction == "allergy":
            connection.execute("UPDATE foods SET allergens_json='[\"milk\"]', allergens_reviewed=1 WHERE id='protein'")
        else:
            connection.execute("UPDATE foods SET vegetarian=0 WHERE id='protein'")
        connection.commit()
    with db.open_ledger(_ledger_id(db)) as ledger:
        setup = ledger.get_meal_setup()
        if restriction != "review_revoked":
            setup["restrictions"].update(allergies=["milk"] if restriction == "allergy" else [],
                                         vegetarian=restriction == "vegetarian")
            with ledger.ledger_transaction():
                ledger.save_meal_setup(setup)
        ledger.conn.execute("PRAGMA query_only=ON")
        response = json.loads(_nutrition_tool(ledger).invoke({}))
    assert response["status"] == "ok" and response["targets"]
    assert response["meals"] == []


def test_long_bilingual_meals_page_without_losing_foods_or_exceeding_the_cap(meals_api):
    client, db, headers, today = meals_api
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET name=?, arabic_name=?", ("é" * 100, "ج" * 100))
        connection.commit()
    setup = client.put("/nutrition/meal-setup", headers=headers, json={
        "meal_count": 5, "training_time": "evening",
        "restrictions": {"allergies": [], "dislikes": [], "vegetarian": False}})
    assert setup.status_code == 200, setup.text
    _enable(client, headers)
    with db.open_ledger(_ledger_id(db)) as ledger:
        expected = nutrition.assistant_projection(ledger, today)["meals"]
        ledger.conn.execute("PRAGMA query_only=ON")
        tool = _nutrition_tool(ledger)
        offset, foods, pages = 0, [], []
        while True:
            rendered = tool.invoke({"offset": offset})
            assert len(rendered.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES
            page = json.loads(rendered)
            assert page["status"] == "ok"
            pages.append(page)
            foods.extend((meal["slot"], food) for meal in page["meals"] for food in meal["foods"])
            if page["next_offset"] is None:
                break
            assert offset < page["next_offset"] < page["food_count"]
            offset = page["next_offset"]
        beyond = json.loads(tool.invoke({"offset": page["food_count"]}))
    assert len(pages) > 1
    assert foods == [(meal["slot"], food) for meal in expected for food in meal["foods"]]
    assert all(food["name_truncated"] and food["arabic_name_truncated"] for _slot, food in foods)
    assert beyond["meals"] == [] and beyond["next_offset"] is None


def test_swap_tool_calls_cannot_write_a_nutrition_plan(meals_api):
    client, db, headers, _today = meals_api
    _enable(client, headers)
    with db.open_ledger(_ledger_id(db)) as ledger:
        before = _plan_rows(ledger)
        changes = ledger.conn.total_changes
        ledger.conn.execute("PRAGMA query_only=ON")
        tools, definitions = build_player_read_tools(ledger)
        messages, _telemetry = run_player_tool_calls([
            {"id": "read", "name": "get_player_nutrition", "args": {
                "slot": "breakfast", "food_id": "protein", "replacement_id": "alternative"}},
            {"id": "write", "name": "swap_food", "args": {
                "slot": "breakfast", "food_id": "protein", "replacement_id": "alternative"}},
        ], tools=tools, definitions=definitions, language="en")
        assert json.loads(messages[0].content)["status"] == "ok"
        assert json.loads(messages[1].content) == {"status": "unavailable"}
        assert _plan_rows(ledger) == before
        assert ledger.conn.total_changes == changes
