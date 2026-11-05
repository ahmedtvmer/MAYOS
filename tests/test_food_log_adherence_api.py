"""Computed Nutrition adherence through HTTP and the real hourly sweep (#476)."""

import json
from datetime import UTC, datetime, time, timedelta

import pytest

from database.ledger.nutrition import NutritionPlanVersion
from service.alert_sweep import run_sweep
from tests.test_food_log_api import _add, food_api  # noqa: F401
from tests.test_missed_day_alerts import _make_coach
from tests.test_nutrition_api import api  # noqa: F401


@pytest.fixture
def adherence_api(food_api, monkeypatch):
    client, db, headers, today = food_api
    clock = [datetime.combine(today, time(12), tzinfo=UTC)]
    from service import weight_history

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz)

    monkeypatch.setattr(weight_history, "datetime", FrozenDatetime)
    account = db.get_active_account_by_username("food-player")
    with db.open_ledger(account["ledger_id"]) as ledger, ledger.ledger_transaction():
        ledger.save_nutrition_plan(NutritionPlanVersion(
            "maintain", {"code": "default"}, None, "mostly_sitting",
            {"calories": 2000, "protein_g": 100, "carbs_g": 250, "fat_g": 67},
            created_at=(today - timedelta(days=10)).isoformat() + "T00:00:00+00:00",
        ))
    return client, db, headers, clock, account["ledger_id"]


def _food_density(db, calories, protein):
    with db.catalog_transaction():
        db.catalog_conn.execute("UPDATE foods SET nutrients_json=? WHERE id='egg'", (
            json.dumps({"energy_kcal": calories, "protein_g": protein,
                        "carbohydrate_g": 0, "fat_g": 0}),
        ))


def _day(client, headers, entry_date):
    response = client.get("/nutrition", headers=headers)
    assert response.status_code == 200, response.text
    return next(day for day in response.json()["adherence_days"] if day["date"] == entry_date.isoformat())


def _answer(client, headers, entry_date, verdict):
    response = client.put("/nutrition/adherence", headers=headers, json={
        "entry_date": entry_date.isoformat(), "value": verdict,
    })
    assert response.status_code == 200, response.text


# Each inclusive kcal edge and protein floor is exercised just below, at and above it.
@pytest.mark.parametrize(("calories", "protein", "expected"), [
    (1799.99, 100, "roughly"), (1800, 100, "on_target"), (1800.01, 100, "on_target"),
    (2199.99, 100, "on_target"), (2200, 100, "on_target"), (2200.01, 100, "roughly"),
    (1599.99, 100, "off"), (1600, 100, "roughly"), (1600.01, 100, "roughly"),
    (2399.99, 100, "roughly"), (2400, 100, "roughly"), (2400.01, 100, "off"),
    (2000, 89.99, "roughly"), (2000, 90, "on_target"), (2000, 90.01, "on_target"),
    (2000, 74.99, "off"), (2000, 75, "roughly"), (2000, 75.01, "roughly"),
    (2300, 89.99, "roughly"), (2300, 74.99, "off"),
])
def test_sweep_applies_inclusive_thresholds_only_after_the_day_ends(adherence_api, calories, protein, expected):
    client, db, headers, clock, _ledger_id = adherence_api
    logged_day = clock[0].date()
    _food_density(db, calories, protein)
    added = _add(client, headers, logged_day)
    assert added.status_code == 201, added.text
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert _day(client, headers, logged_day)["value"] is None
    clock[0] += timedelta(days=1)
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert _day(client, headers, logged_day) == {
        "date": logged_day.isoformat(), "value": expected, "source": "computed",
    }


def test_sweep_retries_leave_the_same_value_and_timestamp_and_emit_no_player_event(adherence_api, recording_analytics):
    client, db, headers, clock, ledger_id = adherence_api
    logged_day = clock[0].date()
    assert _add(client, headers, logged_day).status_code == 201
    clock[0] += timedelta(days=1)
    assert run_sweep(db, now=clock[0])["errors"] == 0
    with db.open_ledger(ledger_id) as ledger:
        first = tuple(ledger.conn.execute("SELECT * FROM nutrition_adherence").fetchone())
    assert run_sweep(db, now=clock[0])["errors"] == 0
    with db.open_ledger(ledger_id) as ledger:
        assert tuple(ledger.conn.execute("SELECT * FROM nutrition_adherence").fetchone()) == first
    assert not [event for event in recording_analytics.events if event["event"] == "nutrition_adherence_logged"]


def test_yesterday_add_edit_and_last_delete_recompute_without_waiting_for_sweep(adherence_api):
    client, db, headers, clock, _ledger_id = adherence_api
    yesterday = clock[0].date() - timedelta(days=1)
    _food_density(db, 2000, 100)
    added = _add(client, headers, yesterday)
    assert added.status_code == 201, added.text
    assert _day(client, headers, yesterday)["value"] == "on_target"
    entry_id = added.json()["id"]
    edited = client.put(f"/nutrition/food-log/{entry_id}", headers=headers, json={
        "quantity": 120, "unit": "grams", "meal_label": "dinner",
    })
    assert edited.status_code == 200, edited.text
    assert _day(client, headers, yesterday)["value"] == "roughly"
    second = _add(client, headers, yesterday)
    assert second.status_code == 201, second.text
    assert _day(client, headers, yesterday)["value"] == "off"
    assert client.delete(f"/nutrition/food-log/{second.json()['id']}", headers=headers).status_code == 204
    assert _day(client, headers, yesterday)["value"] == "roughly"
    assert client.delete(f"/nutrition/food-log/{entry_id}", headers=headers).status_code == 204
    assert _day(client, headers, yesterday)["value"] is None
    assert _day(client, headers, yesterday)["source"] is None
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert _day(client, headers, yesterday)["value"] is None


def test_editing_yesterday_before_its_first_sweep_creates_adherence(adherence_api):
    client, db, headers, clock, _ledger_id = adherence_api
    logged_day = clock[0].date()
    _food_density(db, 2000, 100)
    added = _add(client, headers, logged_day)
    assert added.status_code == 201, added.text
    clock[0] += timedelta(days=1)
    assert _day(client, headers, logged_day)["value"] is None
    edited = client.put(f"/nutrition/food-log/{added.json()['id']}", headers=headers, json={
        "quantity": 120, "unit": "grams", "meal_label": "dinner",
    })
    assert edited.status_code == 200, edited.text
    assert _day(client, headers, logged_day)["value"] == "roughly"
    assert _day(client, headers, logged_day)["source"] == "computed"


@pytest.mark.parametrize("answer_first", [True, False])
def test_answer_overrides_computation_in_both_orders_and_survives_log_changes(adherence_api, answer_first):
    client, db, headers, clock, _ledger_id = adherence_api
    logged_day = clock[0].date()
    _food_density(db, 2000, 100)
    added = _add(client, headers, logged_day)
    assert added.status_code == 201, added.text
    if answer_first:
        _answer(client, headers, logged_day, "off")
    clock[0] += timedelta(days=1)
    assert run_sweep(db, now=clock[0])["errors"] == 0
    if not answer_first:
        assert _day(client, headers, logged_day)["value"] == "on_target"
        _answer(client, headers, logged_day, "off")
    entry_id = added.json()["id"]
    assert client.put(f"/nutrition/food-log/{entry_id}", headers=headers, json={
        "quantity": 120, "unit": "grams", "meal_label": "dinner",
    }).status_code == 200
    assert client.delete(f"/nutrition/food-log/{entry_id}", headers=headers).status_code == 204
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert _day(client, headers, logged_day) == {
        "date": logged_day.isoformat(), "value": "off", "source": "answered",
    }
    _answer(client, headers, logged_day, "roughly")
    assert _day(client, headers, logged_day)["value"] == "roughly"


@pytest.mark.parametrize("offset", [-2, 1])
def test_answer_cannot_write_outside_the_player_local_window(adherence_api, offset):
    client, _db, headers, clock, _ledger_id = adherence_api
    response = client.put("/nutrition/adherence", headers=headers, json={
        "entry_date": (clock[0].date() + timedelta(days=offset)).isoformat(), "value": "on_target",
    })
    assert response.status_code == 409, response.text


@pytest.mark.parametrize("targets", [
    {}, {"calories": 0, "protein_g": 100}, {"calories": 2000, "protein_g": 0},
    {"calories": 2000}, {"protein_g": 100},
])
def test_missing_or_zero_targets_leave_no_computed_value(adherence_api, targets):
    client, db, headers, clock, ledger_id = adherence_api
    yesterday = clock[0].date() - timedelta(days=1)
    with db.open_ledger(ledger_id) as ledger, ledger.ledger_transaction():
        ledger.save_nutrition_plan(NutritionPlanVersion(
            "maintain", {"code": "default"}, None, "mostly_sitting", targets,
        ))
    assert _add(client, headers, yesterday).status_code == 201
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert _day(client, headers, yesterday)["value"] is None


def test_recompute_uses_logged_days_targets_including_training_day_selection(adherence_api):
    client, db, headers, clock, ledger_id = adherence_api
    yesterday = clock[0].date() - timedelta(days=1)
    with db.open_ledger(ledger_id) as ledger, ledger.ledger_transaction():
        ledger.append_training_schedule(ledger_id, [yesterday.isoweekday()], "UTC",
                                        (yesterday - timedelta(days=1)).isoformat(), clock[0].isoformat())
        ledger.save_nutrition_plan(NutritionPlanVersion(
            "maintain", {"code": "default"}, None, "mostly_sitting", {
                "training_day": {"calories": 2200, "protein_g": 150, "carbs_g": 250, "fat_g": 67},
                "rest_day": {"calories": 1800, "protein_g": 80, "carbs_g": 250, "fat_g": 67},
            },
        ))
    _food_density(db, 2200, 150)
    assert _add(client, headers, yesterday).status_code == 201
    assert _day(client, headers, yesterday)["value"] == "on_target"
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert _day(client, headers, yesterday)["value"] == "on_target"


@pytest.mark.parametrize("timezone", ["Pacific/Kiritimati", "Pacific/Honolulu"])
def test_sweep_waits_for_player_local_midnight_and_catches_up_later(adherence_api, timezone):
    client, db, headers, clock, ledger_id = adherence_api
    # Both offsets cross midnight at 10:00 UTC, on opposite sides of the UTC date.
    utc_day = clock[0].date()
    clock[0] = datetime.combine(utc_day, time(9, 59), tzinfo=UTC)
    with db.open_ledger(ledger_id) as ledger:
        ledger.append_training_schedule(ledger_id, [1], timezone,
                                        (utc_day - timedelta(days=30)).isoformat(), clock[0].isoformat())
    from service.weight_history import player_local_date
    with db.open_ledger(ledger_id) as ledger:
        logged_day = player_local_date(ledger, ledger_id, now=clock[0])
    assert _add(client, headers, logged_day).status_code == 201
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert _day(client, headers, logged_day)["value"] is None
    # Miss the midnight sweep; the last hour of the next local day still catches up.
    clock[0] += timedelta(hours=23, minutes=1)
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert _day(client, headers, logged_day)["source"] == "computed"


def test_sweep_does_not_compute_days_outside_the_write_window(adherence_api):
    client, db, headers, clock, _ledger_id = adherence_api
    logged_day = clock[0].date()
    assert _add(client, headers, logged_day).status_code == 201
    clock[0] += timedelta(days=2)
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert _day(client, headers, logged_day)["value"] is None


def _coach_for_player(client, db, headers):
    coach_headers = _make_coach(client, db, "adherence-coach")
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    response = client.post("/assignments/invites/redeem", headers=headers, json={"token": token, "consent": True})
    assert response.status_code == 200, response.text
    return coach_headers


def _nutrition_alerts(client, coach_headers, state="new"):
    response = client.get("/coach/alerts", headers=coach_headers, params={"state": state})
    assert response.status_code == 200, response.text
    return [alert for alert in response.json()["alerts"] if alert["kind"].startswith("nutrition_")]


def test_mixed_answered_and_computed_off_days_create_only_the_off_streak_alert(adherence_api):
    client, db, headers, clock, _ledger_id = adherence_api
    coach_headers = _coach_for_player(client, db, headers)
    _answer(client, headers, clock[0].date(), "off")
    clock[0] += timedelta(days=1)
    assert _add(client, headers, clock[0].date()).status_code == 201
    clock[0] += timedelta(days=1)
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert _nutrition_alerts(client, coach_headers) == []
    _answer(client, headers, clock[0].date(), "off")
    alerts = _nutrition_alerts(client, coach_headers)
    assert [alert["kind"] for alert in alerts] == ["nutrition_off_streak"]
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert [alert["alert_id"] for alert in _nutrition_alerts(client, coach_headers)] == [alerts[0]["alert_id"]]
    _answer(client, headers, clock[0].date(), "on_target")
    assert _nutrition_alerts(client, coach_headers) == []


@pytest.mark.parametrize("kind", ["library_food", "personal_food", "quick_add"])
def test_any_food_entry_prevents_unlogged_alert_without_a_stored_verdict(adherence_api, kind):
    client, db, headers, clock, ledger_id = adherence_api
    coach_headers = _coach_for_player(client, db, headers)
    today = clock[0].date()
    added = _add(client, headers, today)
    assert added.status_code == 201, added.text
    # Persist a prior-day snapshot; kind and nullable nutrients are #475's storage contract.
    with db.open_ledger(ledger_id) as ledger, ledger.ledger_transaction():
        ledger.conn.execute(
            "UPDATE food_log_entries SET entry_date=?, kind=?, nutrients_json=? WHERE id=?",
            ((today - timedelta(days=2)).isoformat(), kind, json.dumps({
                "energy_kcal": 2000, "protein_g": None, "carbohydrate_g": None, "fat_g": None,
            }), added.json()["id"]),
        )
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert _day(client, headers, today - timedelta(days=2))["value"] is None
    assert _nutrition_alerts(client, coach_headers) == []


def test_food_with_null_protein_resolves_unlogged_episode_but_can_compute_off(adherence_api):
    client, db, headers, clock, ledger_id = adherence_api
    coach_headers = _coach_for_player(client, db, headers)
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert [alert["kind"] for alert in _nutrition_alerts(client, coach_headers)] == ["nutrition_unlogged"]
    logged_day = clock[0].date()
    added = _add(client, headers, logged_day)
    assert added.status_code == 201, added.text
    with db.open_ledger(ledger_id) as ledger, ledger.ledger_transaction():
        ledger.conn.execute("UPDATE food_log_entries SET kind='quick_add', food_id=NULL, grams=NULL, "
                            "unit=NULL, quantity=NULL, nutrients_per_100g_json=NULL, nutrients_json=? WHERE id=?", (
            json.dumps({"energy_kcal": 2000, "protein_g": None, "carbohydrate_g": None, "fat_g": None}),
            added.json()["id"],
        ))
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert _day(client, headers, logged_day)["value"] is None
    assert _nutrition_alerts(client, coach_headers) == []
    clock[0] += timedelta(days=1)
    assert run_sweep(db, now=clock[0])["errors"] == 0
    assert _day(client, headers, logged_day)["value"] == "off"
    assert _day(client, headers, logged_day)["source"] == "computed"
    assert _nutrition_alerts(client, coach_headers) == []
