"""Food swap rules through HTTP, real catalog rows and immutable plan versions."""

import json

import pytest

from database.ledger.nutrition import NutritionPlanVersion
from service import analytics
from tests.test_meals_api import _enable, _ledger_id, meals_api  # noqa: F401
from tests.test_nutrition_api import api  # noqa: F401


def _target(plan):
    return {"plan_version_id": plan["plan_version_id"], "day_type": plan["day_type"],
            "slot": "breakfast", "role": "protein"}


def _swap(client, headers, plan, food_id="alternative"):
    return client.post("/nutrition/meals/swap", headers=headers,
                       json={**_target(plan), "food_id": food_id})


def _candidates(client, headers, plan, query=""):
    response = client.get("/nutrition/meals/swap-candidates", headers=headers,
                          params={**_target(plan), "q": query})
    assert response.status_code == 200, response.text
    return response.json()


def _add_search_food(db):
    with db.catalog_locked() as connection:
        cursor = connection.execute("SELECT * FROM foods WHERE id='alternative'")
        food = dict(zip([column[0] for column in cursor.description], cursor.fetchone()))
        food.update(id="searched", name="Searched food", source_name="Searched food",
                    staple_roles_json="[]")
        columns = ",".join(food)
        placeholders = ",".join("?" for _ in food)
        connection.execute(f"INSERT INTO foods ({columns}) VALUES ({placeholders})", list(food.values()))
        connection.commit()


def test_swap_versions_both_day_types_preserves_other_slots_and_never_logs(meals_api, recording_analytics):
    client, db, headers, _today = meals_api
    before = _enable(client, headers)
    assert before["can_swap"]
    candidates = _candidates(client, headers, before)
    assert [candidate["food"]["id"] for candidate in candidates["staples"]] == ["alternative"]
    response = _swap(client, headers, before)
    assert response.status_code == 201, response.text
    after = client.get("/nutrition/meals", headers=headers).json()
    assert after["plan_version_id"] == before["plan_version_id"] + 1
    assert after["meals"][0]["foods"][0]["id"] == "alternative"
    assert after["meals"][0]["totals"] == before["meals"][0]["totals"]
    assert after["meals"][1:] == before["meals"][1:]
    assert after["meals"][0]["foods"][1:] == before["meals"][0]["foods"][1:]
    assert _candidates(client, headers, after)["staples"][0]["food"]["id"] == "protein"
    assert client.get("/nutrition/food-log", headers=headers).json()["entries"] == []
    with db.open_ledger(_ledger_id(db)) as ledger:
        rows = ledger.conn.execute("SELECT meals_json FROM nutrition_plan_versions WHERE id IN (?,?) ORDER BY id",
                                   (before["plan_version_id"], after["plan_version_id"])).fetchall()
        for variant in json.loads(rows[0][0])["variants"].values():
            assert variant["meals"][0]["foods"][0]["id"] == "protein"
        for variant in json.loads(rows[1][0])["variants"].values():
            assert variant["meals"][0]["foods"][0]["id"] == "alternative"
    events = [event for event in recording_analytics.events if event["event"] == "nutrition_food_swapped"]
    assert len(events) == 1
    assert set(events[0]["properties"]) == {"role", "platform", "app_version", "env"}
    assert _swap(client, headers, before).status_code == 409
    assert _swap(client, headers, after).status_code == 409
    assert len([event for event in recording_analytics.events if event["event"] == "nutrition_food_swapped"]) == 1


@pytest.mark.parametrize("restriction,allowed", [("allergy", False), ("vegetarian", False), ("dislike", True)])
def test_restrictions_hide_suggestions_warn_in_search_and_enforce_strict_swaps(meals_api, restriction, allowed):
    client, db, headers, _today = meals_api
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET allergens_json='[\"milk\"]', allergens_reviewed=1, vegetarian=0 WHERE id='alternative'")
        connection.commit()
    restrictions = {"allergies": ["milk"] if restriction == "allergy" else [],
                    "vegetarian": restriction == "vegetarian",
                    "dislikes": ["alternative"] if restriction == "dislike" else []}
    saved = client.put("/nutrition/meal-setup", headers=headers,
                       json={"meal_count": 3, "training_time": "evening", "restrictions": restrictions})
    assert saved.status_code == 200, saved.text
    plan = _enable(client, headers)
    choices = _candidates(client, headers, plan, "Alternative")
    assert choices["staples"] == []
    searched = next(candidate for candidate in choices["search"] if candidate["food"]["id"] == "alternative")
    expected = {"allergy": "milk", "vegetarian": "vegetarian", "dislike": "disliked"}[restriction]
    assert searched["food"]["restriction_reasons"] == [expected]
    assert searched["allowed"] is allowed
    response = _swap(client, headers, plan)
    assert response.status_code == (201 if allowed else 409), response.text
    if not allowed:
        assert client.get("/nutrition/meals", headers=headers).json()["plan_version_id"] == plan["plan_version_id"]
    else:
        regenerated = client.put("/nutrition/activity", headers=headers, json={"daily_activity": "on_feet"})
        assert regenerated.status_code == 200, regenerated.text
        assert client.get("/nutrition/meals", headers=headers).json()["meals"][0]["foods"][0]["id"] == "alternative"


def test_search_swap_survives_target_regeneration_and_is_removed_when_strictly_restricted(meals_api):
    client, db, headers, _today = meals_api
    _add_search_food(db)
    plan = _enable(client, headers)
    choices = _candidates(client, headers, plan, "Searched")
    assert choices["staples"][0]["food"]["id"] == "alternative"
    assert choices["search"][0]["food"]["id"] == "searched"
    assert _swap(client, headers, plan, "searched").status_code == 201
    changed = client.put("/nutrition/activity", headers=headers, json={"daily_activity": "on_feet"})
    assert changed.status_code == 200, changed.text
    regenerated = client.get("/nutrition/meals", headers=headers).json()
    assert regenerated["status"] == "ready"
    assert regenerated["meals"][0]["foods"][0]["id"] == "searched"
    assert regenerated["meals"][0]["foods"][0]["swapped"]
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET vegetarian=0 WHERE id='searched'")
        connection.commit()
    changed = client.put("/nutrition/meal-setup", headers=headers, json={"meal_count": 3, "training_time": "evening",
        "restrictions": {"allergies": [], "dislikes": [], "vegetarian": True}})
    assert changed.status_code == 200, changed.text
    assert client.get("/nutrition/meals", headers=headers).json()["meals"][0]["foods"][0]["id"] == "protein"


def test_allowed_swap_survives_temporarily_unavailable_generation(meals_api):
    client, db, headers, _today = meals_api
    plan = _enable(client, headers)
    assert _swap(client, headers, plan).status_code == 201
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET reviewed=0 WHERE id='carb'")
        connection.commit()
    changed = client.put("/nutrition/activity", headers=headers, json={"daily_activity": "on_feet"})
    assert changed.status_code == 200, changed.text
    assert client.get("/nutrition/meals", headers=headers).json()["status"] == "unavailable"
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET reviewed=1 WHERE id='carb'")
        connection.commit()
    changed = client.put("/nutrition/activity", headers=headers, json={"daily_activity": "mostly_sitting"})
    assert changed.status_code == 200, changed.text
    restored = client.get("/nutrition/meals", headers=headers).json()
    assert restored["status"] == "ready"
    assert restored["meals"][0]["foods"][0]["id"] == "alternative"


@pytest.mark.parametrize("override", [
    {"hidden": 1}, {"reviewed": 0}, {"nutrients_json": '{"energy_kcal":120,"protein_g":null}'},
])
def test_hidden_unreviewed_staples_and_incomplete_nutrients_never_create_swap_versions(meals_api, override):
    client, db, headers, _today = meals_api
    plan = _enable(client, headers)
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET " + ",".join(f"{key}=?" for key in override) + " WHERE id='alternative'",
                           list(override.values()))
        connection.commit()
    assert _swap(client, headers, plan).status_code == 409
    assert client.get("/nutrition/meals", headers=headers).json()["plan_version_id"] == plan["plan_version_id"]


def test_coach_authored_plan_blocks_swap_reads_and_writes(meals_api):
    client, db, headers, _today = meals_api
    _enable(client, headers)
    with db.open_ledger(_ledger_id(db)) as ledger:
        active = ledger.get_active_nutrition_plan()
        coach_plan = NutritionPlanVersion(goal="maintain", reason={"code": "coach"}, intensity=None,
            daily_activity="mostly_sitting", targets=json.loads(active["targets_json"]),
            author="Coach", provenance="coach", authority_assignment_id="assignment",
            meals=json.loads(active["meals_json"]))
        with ledger.ledger_transaction():
            ledger.save_nutrition_plan(coach_plan)
    plan = client.get("/nutrition/meals", headers=headers).json()
    assert not plan["can_swap"]
    assert _swap(client, headers, plan).status_code == 403
    assert client.get("/nutrition/meals/swap-candidates", headers=headers, params=_target(plan)).status_code == 403
    assert client.get("/nutrition/meals", headers=headers).json()["plan_version_id"] == plan["plan_version_id"]


def test_food_swap_analytics_respects_opt_out(meals_api, recording_analytics):
    client, db, headers, _today = meals_api
    plan = _enable(client, headers)
    analytics.override_analytics_preference_reader(db.analytics_preference_allows)
    disabled = client.put("/auth/analytics-preference", headers=headers, json={"analytics_allowed": False})
    assert disabled.status_code == 200, disabled.text
    assert _swap(client, headers, plan).status_code == 201
    assert not [event for event in recording_analytics.events if event["event"] == "nutrition_food_swapped"]


def test_swap_preview_and_saved_day_share_curated_limits_and_refresh_gap_note(meals_api):
    client, db, headers, _today = meals_api
    plan = _enable(client, headers)
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET min_grams=75, max_grams=75 WHERE id='alternative'")
        connection.commit()
    preview = _candidates(client, headers, plan)["staples"][0]
    assert preview["allowed"] and preview["grams"] == 75
    assert _swap(client, headers, plan).status_code == 201
    saved = client.get("/nutrition/meals", headers=headers).json()
    assert saved["meals"][0]["foods"][0]["grams"] == preview["grams"]
    with db.open_ledger(_ledger_id(db)) as ledger:
        payload = json.loads(ledger.get_active_nutrition_plan()["meals_json"])
    for variant in payload["variants"].values():
        assert variant["meals"][0]["foods"][0]["grams"] == 75
        assert set(variant["gap_note"]) == {"en", "ar"}


def test_swap_candidates_without_any_amount_inside_limits_are_disabled(meals_api):
    client, db, headers, _today = meals_api
    plan = _enable(client, headers)
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET min_grams=101, max_grams=124 WHERE id='alternative'")
        connection.commit()
    choices = _candidates(client, headers, plan, "Alternative")
    assert choices["staples"] == []
    assert choices["search"][0]["allowed"] is False
    assert choices["search"][0]["grams"] is None
    assert _swap(client, headers, plan).status_code == 409
    assert client.get("/nutrition/meals", headers=headers).json()["plan_version_id"] == plan["plan_version_id"]
