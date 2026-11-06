"""Food log behavior through authenticated HTTP and real catalog/ledger storage."""

import csv
import json
from datetime import UTC, datetime, timedelta

import pytest

from database.food_library.builder import NUTRIENTS
from database.food_library.seeding import FoodLibraryPaths, seed_food_library
from service import analytics
from tests.test_nutrition_api import api, _player_today, _seed_profile  # noqa: F401


def _csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def food_api(api, tmp_path):  # noqa: F811
    client, db = api
    names = {
        "staple": "Chicken thigh", "exact": "Chicken", "prefix": "Chicken breast",
        "alias": "Poultry cooked", "contains": "Roast chicken", "raw": "Chicken raw",
        "hidden": "Chicken hidden", "egg": "Egg", "rice": "Rice",
        **{f"extra-{index}": f"Food item {index}" for index in range(11)},
    }
    sources = [{"id": key, "name": name, "source": "SR Legacy", "category": "Food",
                **dict.fromkeys(NUTRIENTS, 0), "energy_kcal": 200, "protein_g": 20,
                "carbohydrate_g": 10, "fat_g": 5} for key, name in names.items()]
    curated = [{"id": key, "display_name": name, "reviewed": "true", "hidden": "false"}
               for key, name in names.items()]
    for row in curated:
        if row["id"] == "staple":
            row["staple_roles"] = "dinner_protein"
        elif row["id"] == "alias":
            row["aliases_en"] = "chicken pieces"
        elif row["id"] == "hidden":
            row["hidden"] = "true"
        elif row["id"] == "raw":
            row.update(reviewed="false", arabic_name="دجاج سري", aliases_ar="دجاج مخفي")
        elif row["id"] == "egg":
            row.update(arabic_name="بيضة", aliases_en="hen egg", aliases_ar="بيض بلدى",
                       portion_label="large egg", portion_grams=50)
        elif row["id"] == "rice":
            row.update(arabic_name="أرز", aliases_ar="رُز بلدى")
    paths = FoodLibraryPaths(*(tmp_path / name for name in ("foods.csv", "portions.csv", "curation.csv", "recipes.csv")))
    _csv(paths.foods, ["id", "name", "source", "category", *NUTRIENTS], sources)
    _csv(paths.portions, ["food_id", "label", "gram_weight"], [])
    _csv(paths.curation, ["id", "display_name", "arabic_name", "aliases_en", "aliases_ar", "hidden",
                          "staple_roles", "portion_label", "portion_grams", "reviewed"], curated)
    _csv(paths.recipes, ["id", "display_name", "ingredient_fdc_id", "grams"], [])
    seed_food_library(db.catalog_conn, paths)
    registered = client.post("/auth/register", json={"trainee_id": "food-player", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "food-player", age=30, target=None)
    response = client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    assert response.status_code == 200, response.text
    return client, db, headers, _player_today(db, "food-player")


def _add(client, headers, day, food="egg", **changes):
    return client.post("/nutrition/food-log", headers=headers, json={
        "entry_date": day.isoformat(), "food_id": food, "quantity": 100,
        "unit": "grams", "meal_label": "breakfast", "logged_time": "08:10", **changes,
    })


def test_search_orders_staples_reviewed_and_match_quality_and_excludes_hidden(food_api):
    client, _db, headers, _today = food_api
    response = client.get("/nutrition/foods", headers=headers, params={"q": "chicken"})
    assert response.status_code == 200
    assert [food["id"] for food in response.json()["foods"]] == [
        "staple", "exact", "prefix", "alias", "contains", "raw",
    ]
    assert client.get("/nutrition/foods?q=hidden", headers=headers).json()["foods"] == []


def test_reseed_refreshes_cached_names_aliases_hidden_rows_and_recents(food_api, tmp_path):
    client, db, headers, today = food_api
    assert _add(client, headers, today).status_code == 201
    assert client.get("/nutrition/foods?q=hen%20egg", headers=headers).json()["foods"][0]["name"] == "Egg"
    assert client.get("/nutrition/foods?q=chicken", headers=headers).json()["foods"][0]["id"] == "staple"
    assert client.get("/nutrition/foods", headers=headers).json()["foods"][0]["name"] == "Egg"
    paths = FoodLibraryPaths(*(tmp_path / name for name in ("foods.csv", "portions.csv", "curation.csv", "recipes.csv")))
    with paths.curation.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    for row in rows:
        if row["id"] == "egg":
            row.update(display_name="Omelette", aliases_en="pan breakfast", arabic_name="عجة")
        elif row["id"] == "staple":
            row["hidden"] = "true"
    _csv(paths.curation, fields, rows)
    with db.catalog_locked() as connection:
        seed_food_library(connection, paths)
    assert client.get("/nutrition/foods?q=hen%20egg", headers=headers).json()["foods"] == []
    renamed = client.get("/nutrition/foods?q=pan%20breakfast", headers=headers).json()["foods"]
    assert [(food["id"], food["name"]) for food in renamed] == [("egg", "Omelette")]
    assert [food["id"] for food in client.get("/nutrition/foods?q=chicken", headers=headers).json()["foods"]] == [
        "exact", "prefix", "alias", "contains", "raw",
    ]
    assert client.get("/nutrition/foods", headers=headers).json()["foods"][0]["name"] == "Omelette"


@pytest.mark.parametrize(("query", "food_id"), [
    ("EGG", "egg"), ("hen egg", "egg"), ("بيضه", "egg"), ("بيض بلدي", "egg"),
    ("ارز", "rice"), ("إرز", "rice"), ("رز بلدي", "rice"),
])
def test_search_matches_display_arabic_and_aliases_with_letter_normalization(food_api, query, food_id):
    client, _db, headers, _today = food_api
    foods = client.get("/nutrition/foods", headers=headers, params={"q": query}).json()["foods"]
    assert [food["id"] for food in foods] == [food_id]


def test_unreviewed_arabic_names_and_aliases_do_not_match(food_api):
    client, _db, headers, _today = food_api
    for query in ("دجاج سري", "دجاج مخفي"):
        assert client.get("/nutrition/foods", headers=headers, params={"q": query}).json()["foods"] == []


def test_empty_query_returns_private_recent_and_frequent_visible_foods(food_api):
    client, db, headers, today = food_api
    assert client.get("/nutrition/foods", headers=headers).json()["foods"] == []
    for index in range(3):
        assert _add(client, headers, today, "rice", logged_time=f"09:0{index}").status_code == 201
    assert _add(client, headers, today, logged_time="10:00").status_code == 201
    foods = client.get("/nutrition/foods", headers=headers).json()["foods"]
    assert [(food["id"], food["logged_count"]) for food in foods] == [("egg", 1), ("rice", 3)]
    for index in range(11):
        assert _add(client, headers, today, f"extra-{index}", logged_time=f"11:{index:02d}").status_code == 201
    foods = client.get("/nutrition/foods", headers=headers).json()["foods"]
    assert foods[0]["id"] == "extra-10"
    # Rice is outside the ten recent foods, but returns as the most frequent.
    assert foods[10]["id"] == "rice"
    assert foods[10]["logged_count"] == 3
    with db.catalog_transaction():
        db.catalog_conn.execute("UPDATE foods SET hidden=1 WHERE id='egg'")
    assert "egg" not in [food["id"] for food in client.get("/nutrition/foods", headers=headers).json()["foods"]]
    registered = client.post("/auth/register", json={"trainee_id": "other-food-player", "password": "correct-horse-1"}).json()
    other = {"Authorization": f"Bearer {registered['access_token']}"}
    assert client.get("/nutrition/foods", headers=other).json()["foods"] == []
    assert client.get("/nutrition/food-log", headers=other).json()["entries"] == []


@pytest.mark.parametrize(("offset", "status"), [(-2, 403), (-1, 201), (0, 201), (1, 403)])
def test_add_enforces_today_and_yesterday_only(food_api, offset, status):
    client, _db, headers, today = food_api
    response = _add(client, headers, today + timedelta(days=offset))
    assert response.status_code == status, response.text


def test_portions_snapshot_nutrients_and_names_and_edits_keep_original_density(food_api, recording_analytics):
    client, db, headers, today = food_api
    added = _add(client, headers, today, quantity=2, unit="portion").json()
    assert added["grams"] == 100
    assert added["nutrients"] == {"energy_kcal": 200, "protein_g": 20, "carbohydrate_g": 10, "fat_g": 5}
    with db.catalog_transaction():
        db.catalog_conn.execute("UPDATE foods SET name='Changed', hidden=1, portion_grams=90, "
                                "nutrients_json=? WHERE id='egg'", (json.dumps({"energy_kcal": 999}),))
    read = client.get("/nutrition/food-log", headers=headers).json()
    assert read["entries"][0]["name"] == "Egg"
    assert read["entries"][0]["nutrients"] == added["nutrients"]
    assert read["remaining"]["energy_kcal"] == read["targets"]["calories"] - 200
    edited = client.put(f"/nutrition/food-log/{added['id']}", headers=headers, json={
        "quantity": 3, "unit": "portion", "meal_label": "lunch", "logged_time": "12:30",
    })
    assert edited.status_code == 200, edited.text
    assert edited.json()["grams"] == 150
    assert edited.json()["nutrients"]["energy_kcal"] == 300
    event = [event for event in recording_analytics.events if event["event"] == "food_logged"]
    assert len(event) == 1
    properties = event[0]["properties"]
    assert properties["food_kind"] == "library_food"
    assert properties["meal_label"] == "breakfast"
    assert set(properties) == {"role", "platform", "app_version", "env", "food_kind", "meal_label"}
    assert client.delete(f"/nutrition/food-log/{added['id']}", headers=headers).status_code == 204
    assert client.get("/nutrition/food-log", headers=headers).json()["entries"] == []


def test_old_entries_are_read_only_and_other_players_cannot_mutate_them(food_api):
    client, db, headers, today = food_api
    added = _add(client, headers, today - timedelta(days=1)).json()
    account = db.get_active_account_by_username("food-player")
    old_date = today - timedelta(days=2)
    with db.open_ledger(account["ledger_id"]) as ledger, ledger.ledger_transaction():
        ledger.conn.execute("UPDATE food_log_entries SET entry_date=? WHERE id=?", (old_date.isoformat(), added["id"]))
    read = client.get("/nutrition/food-log", headers=headers, params={"day": old_date.isoformat()}).json()
    assert read["editable"] is False
    assert len(read["entries"]) == 1
    body = {"quantity": 200, "unit": "grams", "meal_label": "dinner"}
    assert client.put(f"/nutrition/food-log/{added['id']}", headers=headers, json=body).status_code == 403
    assert client.delete(f"/nutrition/food-log/{added['id']}", headers=headers).status_code == 403
    registered = client.post("/auth/register", json={"trainee_id": "food-intruder", "password": "correct-horse-1"}).json()
    other = {"Authorization": f"Bearer {registered['access_token']}"}
    assert client.put(f"/nutrition/food-log/{added['id']}", headers=other, json=body).status_code == 404
    assert client.delete(f"/nutrition/food-log/{added['id']}", headers=other).status_code == 404


def test_yesterdays_entries_can_be_edited_and_deleted_and_day_entries_sort_by_time(food_api):
    client, _db, headers, today = food_api
    late = _add(client, headers, today - timedelta(days=1), logged_time="20:00").json()
    early = _add(client, headers, today - timedelta(days=1), "rice", logged_time="07:00").json()
    day = client.get("/nutrition/food-log", headers=headers, params={"day": (today - timedelta(days=1)).isoformat()}).json()
    assert day["editable"] is True
    assert [entry["id"] for entry in day["entries"]] == [early["id"], late["id"]]
    assert day["totals"]["energy_kcal"] == 400
    assert client.put(f"/nutrition/food-log/{late['id']}", headers=headers, json={
        "quantity": 50, "meal_label": "snack", "unit": "grams",
    }).status_code == 200
    assert client.delete(f"/nutrition/food-log/{late['id']}", headers=headers).status_code == 204


def test_hidden_food_and_missing_portion_cannot_be_logged_and_opt_out_suppresses_event(food_api, recording_analytics):
    client, _db, headers, today = food_api
    assert _add(client, headers, today, "hidden").status_code == 404
    assert _add(client, headers, today, "rice", unit="portion", quantity=1).status_code == 400
    analytics.override_analytics_preference_reader(lambda _account_id: False)
    assert _add(client, headers, today).status_code == 201
    assert not [event for event in recording_analytics.events if event["event"] == "food_logged"]


def test_write_window_uses_player_timezone_instead_of_server_date(food_api, monkeypatch):
    client, db, headers, _today = food_api
    from service import weight_history

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 5, 23, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(weight_history, "datetime", FrozenDatetime)
    account = db.get_active_account_by_username("food-player")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.append_training_schedule(str(ledger.ledger_id), [1], "Pacific/Kiritimati",
                                        "2026-01-01", "2026-01-01T00:00:00+00:00")
    response = client.get("/nutrition/food-log", headers=headers)
    assert response.json()["today"] == "2026-11-06"
    assert _add(client, headers, datetime(2026, 11, 6).date()).status_code == 201
    assert _add(client, headers, datetime(2026, 11, 4).date()).status_code == 403


@pytest.mark.parametrize("language", ["en", "ar"])
def test_logged_day_returns_cardio_burned_from_the_selected_days_nutrition(food_api, language):
    client, db, headers, today = food_api
    assert _add(client, headers, today).status_code == 201
    assert client.get("/nutrition/food-log", headers=headers).json()["cardio_burned_kcal"] == 0
    account = db.get_active_account_by_username("food-player")
    with db.open_ledger(account["ledger_id"]) as ledger, ledger.ledger_transaction():
        for session_id, day, calories in (
            ("food-cardio-today", today, 301),
            ("food-cardio-yesterday", today - timedelta(days=1), 1200),
        ):
            ledger.conn.execute(
                "INSERT INTO workout_sessions(id,session_date,split_name,started_at,completed_at) VALUES(?,?,?,?,?)",
                (session_id, day.isoformat(), "Day 1", "now", "now"),
            )
            ledger.conn.execute(
                "INSERT INTO session_cardio_entries(session_id,machine,minutes,calories_kcal,calories_are_estimate,logged_at) "
                "VALUES(?,?,?,?,?,?)", (session_id, "bike", 30, calories, 0, "now"),
            )
    localized = {**headers, "Accept-Language": language}
    nutrition = client.get("/nutrition", headers=localized).json()
    day = client.get("/nutrition/food-log", headers=localized).json()
    assert day["cardio_burned_kcal"] == nutrition["cardio_burned_kcal"] == 301
    assert day["remaining"]["energy_kcal"] == nutrition["targets"]["calories"] - 200
    yesterday = client.get("/nutrition/food-log", headers=localized,
                           params={"day": (today - timedelta(days=1)).isoformat()}).json()
    assert yesterday["cardio_burned_kcal"] == 1200


def _personal(client, headers, **changes):
    return client.post("/nutrition/personal-foods", headers=headers, json={
        "name": "Chicken bowl", "basis": "100g", "energy_kcal": 300,
        "protein_g": 30, "carbohydrate_g": 20, "fat_g": 10, **changes,
    })


def _quick(client, headers, day, **changes):
    return client.post("/nutrition/food-log/quick-add", headers=headers, json={
        "entry_date": day.isoformat(), "energy_kcal": 300, "meal_label": "breakfast", **changes,
    })


@pytest.mark.parametrize("basis", ["100g", "portion"])
def test_personal_food_is_owner_only_searchable_and_logs_a_density_snapshot(food_api, basis):
    client, db, headers, today = food_api
    options = {"basis": basis}
    if basis == "portion":
        options.update(portion_label="bowl", portion_grams=200)
    response = _personal(client, headers, **options)
    assert response.status_code == 201, response.text
    food = response.json()
    assert food["id"].startswith("personal:")
    expected_kcal = 300 if basis == "100g" else 150
    assert food["nutrients"]["energy_kcal"] == expected_kcal
    foods = client.get("/nutrition/foods?q=CHICKEN", headers=headers).json()["foods"]
    assert foods[0]["id"] == food["id"]
    assert foods[0]["kind"] == "personal_food"
    logged = _add(client, headers, today, food["id"]).json()
    assert logged["kind"] == "personal_food"
    assert logged["nutrients"]["energy_kcal"] == expected_kcal
    if basis == "portion":
        portion = _add(client, headers, today, food["id"], quantity=2, unit="portion").json()
        assert portion["grams"] == 400
        assert portion["nutrients"]["energy_kcal"] == 600
    assert client.get("/nutrition/foods", headers=headers).json()["foods"][0]["id"] == food["id"]
    registered = client.post("/auth/register", json={
        "trainee_id": "personal-food-outsider", "password": "correct-horse-1",
    }).json()
    other = {"Authorization": f"Bearer {registered['access_token']}"}
    others_foods = client.get("/nutrition/foods?q=CHICKEN", headers=other).json()["foods"]
    assert others_foods and all(item["id"] != food["id"] for item in others_foods)
    assert _add(client, other, today, food["id"]).status_code == 404
    assert client.get("/nutrition/foods", headers=other).json()["foods"] == []
    account = db.get_active_account_by_username("food-player")
    with db.open_ledger(account["ledger_id"]) as ledger, ledger.ledger_transaction():
        ledger.conn.execute("UPDATE personal_foods SET nutrients_json=? WHERE id=?",
                            (json.dumps(dict.fromkeys(NUTRIENTS, 999)), food["id"]))
    edited = client.put(f"/nutrition/food-log/{logged['id']}", headers=headers, json={
        "quantity": 200, "unit": "grams", "meal_label": "lunch",
    })
    assert edited.status_code == 200, edited.text
    assert edited.json()["nutrients"]["energy_kcal"] == expected_kcal * 2
    assert client.delete(f"/nutrition/food-log/{logged['id']}", headers=headers).status_code == 204


def test_personal_food_search_uses_the_library_arabic_normalization(food_api):
    client, _db, headers, _today = food_api
    food = _personal(client, headers, name="أَرْز خاص").json()
    found = client.get("/nutrition/foods", headers=headers, params={"q": "ارز خاص"}).json()["foods"]
    assert [item["id"] for item in found] == [food["id"]]


@pytest.mark.parametrize("portion", [
    {"portion_label": "bowl"}, {"portion_grams": 200},
    {"portion_label": "bowl", "portion_grams": 1e-320},
    {"portion_label": "bowl", "portion_grams": 1e-300},
])
def test_personal_portions_require_a_complete_finite_density(food_api, portion):
    client, _db, headers, _today = food_api
    response = _personal(client, headers, basis="portion", **portion)
    assert response.status_code == 422, response.text
    assert client.get("/nutrition/foods?q=Chicken%20bowl", headers=headers).json()["foods"] == []


def test_personal_matches_rank_first_and_usage_does_not_collide_with_library(food_api):
    client, _db, headers, today = food_api
    personal = [_personal(client, headers, name=name).json() for name in (
        "Roast chicken", "Chicken bowl", "Chicken",
    )]
    matches = client.get("/nutrition/foods?q=chicken", headers=headers).json()["foods"]
    assert [food["id"] for food in matches[:4]] == [
        personal[2]["id"], personal[1]["id"], personal[0]["id"], "staple",
    ]
    egg = _personal(client, headers, name="Egg").json()
    for index in range(3):
        assert _add(client, headers, today, egg["id"], logged_time=f"09:0{index}").status_code == 201
    assert _add(client, headers, today, "egg", logged_time="10:00").status_code == 201
    recent = client.get("/nutrition/foods", headers=headers).json()["foods"]
    assert [(food["id"], food["logged_count"]) for food in recent] == [("egg", 1), (egg["id"], 3)]


def test_quick_add_keeps_blank_macros_null_and_counts_towards_totals(food_api, recording_analytics):
    client, _db, headers, today = food_api
    assert _add(client, headers, today).status_code == 201
    response = _quick(client, headers, today, fat_g=0)
    assert response.status_code == 201, response.text
    entry = response.json()
    assert entry["kind"] == "quick_add" and entry["name"] == "quick_add"
    assert entry["food_id"] is None and entry["nutrients_per_100g"] is None
    expected = {"energy_kcal": 300, "protein_g": None, "carbohydrate_g": None, "fat_g": 0}
    assert entry["nutrients"] == expected
    day = client.get("/nutrition/food-log", headers=headers).json()
    assert next(item for item in day["entries"] if item["id"] == entry["id"])["nutrients"] == expected
    assert day["totals"] == {"energy_kcal": 500, "protein_g": 20, "carbohydrate_g": 10, "fat_g": 5}
    assert day["remaining"]["energy_kcal"] == day["targets"]["calories"] - 500
    edited = client.put(f"/nutrition/food-log/quick-add/{entry['id']}", headers=headers, json={
        "energy_kcal": 400, "protein_g": 15, "meal_label": "dinner",
    })
    assert edited.status_code == 200, edited.text
    assert edited.json()["nutrients"]["fat_g"] is None
    assert edited.json()["meal_label"] == "dinner"
    totals = client.get("/nutrition/food-log", headers=headers).json()["totals"]
    assert totals == {"energy_kcal": 600, "protein_g": 35, "carbohydrate_g": 10, "fat_g": 5}
    events = [event for event in recording_analytics.events if event["event"] == "food_logged"]
    assert len(events) == 2
    assert events[-1]["properties"]["food_kind"] == "quick_add"
    assert client.delete(f"/nutrition/food-log/{entry['id']}", headers=headers).status_code == 204


@pytest.mark.parametrize("kind", ["quick_add", "personal_food"])
def test_new_entry_kinds_share_the_write_window_and_private_mutations(food_api, kind):
    client, db, headers, today = food_api
    food_id = _personal(client, headers).json()["id"] if kind == "personal_food" else None
    add = (lambda day: _quick(client, headers, day)) if kind == "quick_add" else (
        lambda day: _add(client, headers, day, food_id))
    assert add(today - timedelta(days=2)).status_code == 403
    assert add(today + timedelta(days=1)).status_code == 403
    entry = add(today - timedelta(days=1)).json()
    path = f"/nutrition/food-log/{'quick-add/' if kind == 'quick_add' else ''}{entry['id']}"
    body = ({"energy_kcal": 200, "meal_label": "lunch"} if kind == "quick_add" else
            {"quantity": 200, "unit": "grams", "meal_label": "lunch"})
    assert client.put(path, headers=headers, json=body).status_code == 200
    registered = client.post("/auth/register", json={
        "trainee_id": "new-kind-outsider", "password": "correct-horse-1",
    }).json()
    other = {"Authorization": f"Bearer {registered['access_token']}"}
    assert client.put(path, headers=other, json=body).status_code == 404
    assert client.delete(f"/nutrition/food-log/{entry['id']}", headers=other).status_code == 404
    account = db.get_active_account_by_username("food-player")
    with db.open_ledger(account["ledger_id"]) as ledger, ledger.ledger_transaction():
        ledger.conn.execute("UPDATE food_log_entries SET entry_date=? WHERE id=?",
                            ((today - timedelta(days=2)).isoformat(), entry["id"]))
    assert client.put(path, headers=headers, json=body).status_code == 403
    assert client.delete(f"/nutrition/food-log/{entry['id']}", headers=headers).status_code == 403


def test_copy_meal_copies_all_kinds_as_new_snapshots_without_catalog_reads(food_api, recording_analytics, monkeypatch):
    client, db, headers, today = food_api
    from service import food_log

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(today.year, today.month, today.day, 17, 41, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(food_log, "datetime", FrozenDatetime)
    yesterday = today - timedelta(days=1)
    food = _personal(client, headers).json()
    originals = [_add(client, headers, yesterday).json(),
                 _add(client, headers, yesterday, food["id"], logged_time="09:10").json(),
                 _quick(client, headers, yesterday).json()]
    assert _add(client, headers, yesterday, "rice", meal_label="lunch").status_code == 201
    assert _add(client, headers, today, "rice", meal_label="dinner").status_code == 201
    with db.catalog_transaction():
        db.catalog_conn.execute("UPDATE foods SET hidden=1 WHERE id='egg'")
    meals = client.get("/nutrition/food-log/yesterday-meals", headers=headers).json()
    assert meals == {"today": today.isoformat(), "meal_labels": ["breakfast", "lunch"]}
    response = client.post("/nutrition/food-log/copy-meal", headers=headers, json={"meal_label": "breakfast"})
    assert response.status_code == 201, response.text
    copied = response.json()["entries"]
    assert len(copied) == 3
    assert {entry["id"] for entry in copied}.isdisjoint(entry["id"] for entry in originals)
    for original, new in zip(originals, copied):
        assert new["entry_date"] == today.isoformat()
        assert new["logged_time"] == "17:41"
        assert new["meal_label"] == "breakfast"
        for key in ("kind", "name", "food_id", "nutrients", "nutrients_per_100g", "grams", "quantity", "unit"):
            assert new[key] == original[key]
    day = client.get("/nutrition/food-log", headers=headers).json()
    assert len(day["entries"]) == 4
    assert day["totals"]["energy_kcal"] == 1000
    assert len(client.get("/nutrition/food-log", headers=headers,
                          params={"day": yesterday.isoformat()}).json()["entries"]) == 4
    events = [event for event in recording_analytics.events if event["event"] == "food_logged"]
    assert len(events) == 8
    assert {event["properties"]["food_kind"] for event in events[-3:]} == {
        "library_food", "personal_food", "quick_add"}
    assert all(set(event["properties"]) == {
        "role", "platform", "app_version", "env", "food_kind", "meal_label"} for event in events)
    assert client.post("/nutrition/food-log/copy-meal", headers=headers,
                       json={"meal_label": "snack"}).status_code == 400


def test_copy_meal_rolls_back_every_insert_on_failure_and_cannot_read_another_player(food_api, recording_analytics):
    client, db, headers, today = food_api
    assert _add(client, headers, today - timedelta(days=1)).status_code == 201
    assert _add(client, headers, today - timedelta(days=1), "rice").status_code == 201
    registered = client.post("/auth/register", json={
        "trainee_id": "copy-outsider", "password": "correct-horse-1",
    }).json()
    other = {"Authorization": f"Bearer {registered['access_token']}"}
    assert client.get("/nutrition/food-log/yesterday-meals", headers=other).json()["meal_labels"] == []
    assert client.post("/nutrition/food-log/copy-meal", headers=other,
                       json={"meal_label": "breakfast"}).status_code == 400
    account = db.get_active_account_by_username("food-player")
    with db.open_ledger(account["ledger_id"]) as ledger, ledger.ledger_transaction():
        # Fail the second destination write, after the first has already succeeded.
        ledger.conn.execute(
            "CREATE TRIGGER reject_second_copy BEFORE INSERT ON food_log_entries "
            f"WHEN NEW.entry_date='{today.isoformat()}' AND "
            "EXISTS(SELECT 1 FROM food_log_entries WHERE entry_date=NEW.entry_date) "
            "BEGIN SELECT RAISE(ABORT,'copy interrupted'); END"
        )
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError, match="copy interrupted"):
        client.post("/nutrition/food-log/copy-meal", headers=headers, json={"meal_label": "breakfast"})
    assert client.get("/nutrition/food-log", headers=headers).json()["entries"] == []
    events = [event for event in recording_analytics.events if event["event"] == "food_logged"]
    assert len(events) == 2
