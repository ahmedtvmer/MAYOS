"""Coach Food log reads use the live Assignment gate and stored day snapshots."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from database.ledger.nutrition import NutritionPlanVersion
from tests.test_coach_alerts_api import _assign, _make_coach
from tests.test_nutrition_api import api, _player_today, _seed_profile  # noqa: F401


@pytest.fixture
def coach_log(api):  # noqa: F811
    client, db = api
    coach_headers, player_headers, assignment_id, _coach_id = _assign(api)
    _seed_profile(db, "p1", age=30, target=None)
    account = db.get_active_account_by_username("p1")
    today = _player_today(db, "p1")
    return client, db, coach_headers, player_headers, assignment_id, today, account["ledger_id"]


def _insert_entry(ledger, day, entry_id, kind, **changes):
    entry = {
        "id": entry_id, "entry_date": day.isoformat(), "logged_time": "12:00",
        "meal_label": "lunch", "kind": kind, "food_id": "mayos:koshari",
        "name": "Koshari snapshot", "arabic_name": "كشري", "grams": 100,
        "unit": "grams", "quantity": 100, "portion_label": None, "portion_grams": None,
        "nutrients_per_100g": {"energy_kcal": 200, "protein_g": 10, "carbohydrate_g": 30, "fat_g": 4},
        "nutrients": {"energy_kcal": 200, "protein_g": 10, "carbohydrate_g": 30, "fat_g": 4},
        "created_at": datetime.now(UTC).isoformat(), **changes,
    }
    ledger.insert_food_log_entry(entry)


def test_coach_reads_every_kind_null_macros_totals_day_targets_and_stored_adherence(coach_log):
    client, db, headers, _player, assignment_id, today, ledger_id = coach_log
    day = today - timedelta(days=10)
    with db.open_ledger(ledger_id) as ledger:
        ledger.append_training_schedule(str(ledger_id), [day.isoweekday()], "UTC",
                                        (day - timedelta(days=1)).isoformat(), datetime.now(UTC).isoformat())
        with ledger.ledger_transaction():
            ledger.save_nutrition_plan(NutritionPlanVersion(
                goal="maintain", reason={"code": "coach"}, intensity=None,
                daily_activity="mostly_sitting", author="Coach", authority_assignment_id=assignment_id,
                targets={"daily": None,
                         "training_day": {"calories": 2300, "protein_g": 150, "carbs_g": 280, "fat_g": 64},
                         "rest_day": {"calories": 2000, "protein_g": 140, "carbs_g": 225, "fat_g": 60}},
                created_at=(day - timedelta(days=1)).isoformat() + "T00:00:00+00:00",
            ))
            _insert_entry(ledger, day, "recipe", "library_food")
            _insert_entry(ledger, day, "personal", "personal_food", food_id="personal:1",
                          name="My saved cake", arabic_name=None, logged_time="12:15")
            # Schema 54 permits a Quick add with no food, amount or macro values.
            ledger.conn.execute(
                "INSERT INTO food_log_entries(id, entry_date, logged_time, meal_label, kind, name, "
                "nutrients_json, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                ("quick", day.isoformat(), "13:00", "snack", "quick_add", "Stored in another language",
                 json.dumps({"energy_kcal": 210, "protein_g": None, "carbohydrate_g": None, "fat_g": None}),
                 datetime.now(UTC).isoformat()),
            )
            _insert_entry(ledger, today, "different-day", "library_food")
        ledger.replace_computed_nutrition_adherence(day, "off")
    path = f"/coach/assignments/{assignment_id}/nutrition/food-log"
    response = client.get(path, headers=headers, params={"day": day.isoformat()})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["date"] == day.isoformat()
    assert body["today"] == today.isoformat()
    assert [entry["id"] for entry in body["entries"]] == ["recipe", "personal", "quick"]
    assert [entry["kind"] for entry in body["entries"]] == ["library_food", "personal_food", "quick_add"]
    assert body["entries"][0]["food_id"] == "mayos:koshari"
    assert body["entries"][1]["name"] == "My saved cake"
    quick = body["entries"][2]
    assert all(quick[key] is None for key in ("food_id", "grams", "unit", "quantity", "nutrients_per_100g"))
    assert quick["nutrients"]["protein_g"] is None
    assert body["totals"] == {"energy_kcal": 610, "protein_g": 20, "carbohydrate_g": 60, "fat_g": 8}
    assert body["targets"]["calories"] == 2300
    assert body["targets"]["carbs_g"] == 280
    assert body["adherence"] == {"value": "off", "source": "computed"}
    with db.open_ledger(ledger_id) as ledger:
        ledger.upsert_nutrition_adherence(day, "roughly")
    assert client.get(path, headers=headers, params={"day": day.isoformat()}).json()["adherence"] == {
        "value": "roughly", "source": "answered"}


def test_empty_day_preserves_answer_without_targets_and_future_day_is_refused(coach_log):
    client, db, headers, _player, assignment_id, _today, ledger_id = coach_log
    with db.open_ledger(ledger_id) as ledger:
        ledger.append_training_schedule(str(ledger_id), [1], "Pacific/Kiritimati",
                                        "2020-01-01", datetime.now(UTC).isoformat())
    today = _player_today(db, "p1")
    with db.open_ledger(ledger_id) as ledger:
        ledger.upsert_nutrition_adherence(today, "on_target")
    path = f"/coach/assignments/{assignment_id}/nutrition/food-log"
    response = client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "date": today.isoformat(), "today": today.isoformat(), "entries": [],
        "totals": {"energy_kcal": 0, "protein_g": 0, "carbohydrate_g": 0, "fat_g": 0},
        "targets": None, "adherence": {"value": "on_target", "source": "answered"},
    }
    future = client.get(path, headers=headers, params={"day": (today + timedelta(days=1)).isoformat()})
    assert future.status_code == 400
    assert future.json()["detail"] == "Future Food log days are not available."
    past = client.get(path, headers=headers, params={"day": "2001-01-01"})
    assert past.status_code == 200
    assert past.json()["adherence"] is None


def test_unknown_foreign_and_ended_assignments_deny_identically_before_ledger_mount(coach_log, monkeypatch):
    client, db, headers, player, assignment_id, _today, player_ledger_id = coach_log
    foreign = _make_coach(client, db, "other-coach")
    path = f"/coach/assignments/{assignment_id}/nutrition/food-log"
    assert client.get(path, headers=headers).status_code == 200
    assert client.get(path, headers=player).status_code == 403
    unknown = client.get("/coach/assignments/unknown/nutrition", headers=headers)

    real_open_ledger = db.open_ledger

    def forbidden_mount(ledger_id, *args, **kwargs):
        # The token check opens the Coach's own ledger; only the Player's is forbidden.
        if str(ledger_id) == str(player_ledger_id):
            pytest.fail("An unauthorized Coach read must never mount a Player ledger")
        return real_open_ledger(ledger_id, *args, **kwargs)

    with monkeypatch.context() as guard:
        guard.setattr(db, "open_ledger", forbidden_mount)
        denied = client.get(path, headers=foreign)
        assert denied.status_code == unknown.status_code == 403
        assert denied.json() == unknown.json()
    assert client.post(f"/coach/assignments/{assignment_id}/revoke", headers=headers).status_code == 200
    monkeypatch.setattr(db, "open_ledger", forbidden_mount)
    for denied_path, auth in ((path, headers), (path, foreign),
                              ("/coach/assignments/unknown/nutrition/food-log", headers)):
        denied = client.get(denied_path, headers=auth)
        assert denied.status_code == unknown.status_code == 403
        assert denied.json() == unknown.json()
