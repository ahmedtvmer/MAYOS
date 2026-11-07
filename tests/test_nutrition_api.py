import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from svc.app import create_app
from svc.dependencies import get_db


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-0123456789abcdef")
    from svc.rate_limit import limiter
    limiter._storage.reset()
    path = tmp_path / "catalog.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT, equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT)")
    conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT)")
    conn.commit()
    conn.close()
    db = DatabaseManager(catalog_path=path, ledgers_dir=tmp_path / "users", backups_dir=tmp_path / "backups", default_ledger_id="bootstrap")
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def test_setup_persists_targets_and_returns_goal_reason(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "nutrition-player", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "nutrition-player", age=30, target=60)
    account = db.get_active_account_by_username("nutrition-player")
    today = _player_today(db, "nutrition-player")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.append_training_schedule(str(ledger.ledger_id), [today.isoweekday()], "UTC",
                                        today.isoformat(), "2026-10-25T00:00:00+00:00")
    response = client.post("/nutrition/setup", headers=headers, json={
        "sex": "female", "sex_confirmed": True,
        "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "ready"
    assert body["goal"] == "lose"
    assert body["goal_reason"]["code"] == "target_weight"
    assert body["goal_reason"]["target_weight_kg"] == 60
    assert body["targets"]["calories"] > 0
    assert body["targets"]["water_ml"] == 3000
    assert body["targets"]["fiber_g"] == round(body["targets"]["calories"] * 14 / 1000)
    assert body["targets"]["water_ml"] % 250 == 0
    with db.open_ledger(account["ledger_id"]) as ledger:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            ledger.conn.execute("UPDATE nutrition_plan_versions SET goal='gain'")
    active = client.get("/nutrition", headers=headers)
    assert active.json()["targets"] == body["targets"]
    with db.open_ledger(account["ledger_id"]) as ledger:
        stored_targets = json.loads(ledger.get_active_nutrition_plan()["targets_json"])
    assert stored_targets["water_ml"] == 2500
    assert stored_targets["training_day_water_ml"] == 3000
    assert stored_targets["fiber_g_source"] == "default"
    training_read = client.get("/nutrition", headers=headers).json()
    assert training_read["targets"]["water_ml"] == 3000
    arabic = client.get("/nutrition", headers={**headers, "Accept-Language": "ar"}).json()
    assert arabic["goal_reason"]["code"] == "target_weight"
    weight = client.post("/profile/weight", headers=headers, json={"weight_kg": 71})
    assert weight.status_code == 200
    assert client.get("/nutrition", headers=headers).json()["targets"]["water_ml"] == 3000


def test_weight_history_creates_version_pinned_pace_proposal(api, recording_analytics):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-player", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-player", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    account = db.get_active_account_by_username("pace-player")
    from datetime import timedelta
    with db.open_ledger(account["ledger_id"]) as ledger:
        start = _player_today(db, "pace-player") - timedelta(days=24)
        _seed_pace_weight_history(ledger, start, (70, 68.6, 67.2, 65.8))
        _backdate_active_nutrition_plan(ledger, start)
    from service.alert_sweep import run_sweep
    run_sweep(db)
    response = client.get("/nutrition", headers=headers)
    assert response.status_code == 200
    assert response.json()["pace_proposal"] is not None
    proposal = response.json()["pace_proposal"]
    assert proposal["plan_version_id"] == 1
    assert proposal["status"] == "pending"
    assert proposal["payload"]["calorie_change"] == 250
    accepted = client.post(f"/nutrition/pace-proposals/{proposal['id']}/decision",
                           headers=headers, json={"decision": "accepted"})
    assert accepted.status_code == 200, accepted.text
    assert any(event["event"] == "nutrition_pace_proposal_decided"
               and event["properties"].get("proposal_decision") == "accepted"
               and event["properties"].get("decision_actor") == "player"
               for event in recording_analytics.events), recording_analytics.events
    assert accepted.json()["pace_proposal"]["stale"] is True
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert int(ledger.get_active_nutrition_plan()["id"]) == 2
        assert ledger.get_nutrition_pace_proposal()["status"] == "accepted"
        active_plan = ledger.get_active_nutrition_plan()
        with ledger.ledger_transaction():
            stale_proposal_id = ledger.create_nutrition_pace_proposal(
                active_plan["id"], {"kind": "pace", "goal": "gain", "intensity": "light",
                    "actual_rate_pct": 0, "planned_rate_pct": 0.1,
                    "calorie_change": 100, "targets": proposal["payload"]["targets"]},
                "2026-10-25T00:00:00+00:00")
    changed = client.put("/nutrition/goal", headers=headers,
                         json={"goal": "gain", "intensity": "light"})
    assert changed.status_code == 200, changed.text
    stale_accept = client.post(f"/nutrition/pace-proposals/{stale_proposal_id}/decision",
                               headers=headers, json={"decision": "accepted"})
    assert stale_accept.status_code == 409
    kept = client.post(f"/nutrition/pace-proposals/{stale_proposal_id}/decision",
                       headers=headers, json={"decision": "kept"})
    assert kept.status_code == 200, kept.text


def test_target_weight_proximity_proposes_maintain(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-target", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-target", age=30, target=65)
    setup = client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    assert setup.json()["goal"] == "lose"
    account = db.get_active_account_by_username("pace-target")
    from datetime import timedelta
    with db.open_ledger(account["ledger_id"]) as ledger:
        start = _player_today(db, "pace-target") - timedelta(days=24)
        _seed_pace_weight_history(ledger, start, (70, 68, 66, 65.8))
        _backdate_active_nutrition_plan(ledger, start)
    weight_write = client.post("/profile/weight", headers=headers, json={"weight_kg": 65.8})
    assert weight_write.status_code == 200, weight_write.text
    proposal = client.get("/nutrition", headers=headers).json()["pace_proposal"]
    assert proposal["payload"]["kind"] == "maintain_at_target"
    assert proposal["payload"]["goal"] == "maintain"
    assert proposal["payload"]["targets"]["protein_g"] == setup.json()["targets"]["protein_g"]
    assert proposal["payload"]["targets"]["fat_g"] == setup.json()["targets"]["fat_g"]


def test_pace_proposal_respects_live_calorie_floor(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-floor", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-floor", age=30, target=60, current_goal="fat loss")
    client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    saved = client.put("/nutrition/goal", headers=headers,
                       json={"goal": "lose", "intensity": "aggressive"})
    assert saved.status_code == 200, saved.text
    account = db.get_active_account_by_username("pace-floor")
    from datetime import timedelta
    with db.open_ledger(account["ledger_id"]) as ledger:
        start = _player_today(db, "pace-floor") - timedelta(days=24)
        _seed_pace_weight_history(ledger, start, (70, 70.2, 70.4, 70.6))
        _backdate_active_nutrition_plan(ledger, start)
    weight_write = client.post("/profile/weight", headers=headers, json={"weight_kg": 70.6})
    assert weight_write.status_code == 200, weight_write.text
    proposal = client.get("/nutrition", headers=headers).json()["pace_proposal"]
    assert proposal["payload"]["floor_limited"] is True
    from math import ceil
    assert proposal["payload"]["targets"]["calories"] == ceil(proposal["payload"]["calorie_floor"])
    for macro in ("protein_g", "fat_g"):
        assert proposal["payload"]["targets"][macro] == saved.json()["targets"][macro]


def test_acceptance_rechecks_floor_after_profile_weight_changes(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-live-floor", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-live-floor", age=30, target=None)
    account = db.get_active_account_by_username("pace-live-floor")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.conn.execute("UPDATE user_profile SET height_cm=170 WHERE id=1")
        ledger.conn.commit()
    client.post("/nutrition/setup", headers=headers, json={
        "sex": "female", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    with db.open_ledger(account["ledger_id"]) as ledger:
        active = ledger.get_active_nutrition_plan()
        with ledger.ledger_transaction():
            proposal_id = ledger.create_nutrition_pace_proposal(active["id"], {
                "kind": "pace", "goal": "maintain", "intensity": "moderate",
                "calorie_change": -250, "targets": {"calories": 1500, "protein_g": 140,
                    "carbs_g": 150, "fat_g": 60}}, "2026-10-25T00:00:00+00:00")
        ledger.conn.execute("UPDATE user_profile SET weight_kg=80 WHERE id=1")
        ledger.conn.commit()
    response = client.post(f"/nutrition/pace-proposals/{proposal_id}/decision",
                           headers=headers, json={"decision": "accepted"})
    assert response.status_code == 409
    assert "Calorie floor" in response.json()["detail"]


def test_new_plan_version_allows_a_fresh_pace_proposal(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-superseded", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-superseded", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    account = db.get_active_account_by_username("pace-superseded")
    start = _player_today(db, "pace-superseded") - timedelta(days=24)
    with db.open_ledger(account["ledger_id"]) as ledger:
        _seed_pace_weight_history(ledger, start, (70, 68.6, 67.2, 65.8))
        _backdate_active_nutrition_plan(ledger, start)
        active = ledger.get_active_nutrition_plan()
        with ledger.ledger_transaction():
            ledger.create_nutrition_pace_proposal(active["id"], {
                "kind": "pace", "goal": "lose", "intensity": "moderate",
                "calorie_change": 100, "targets": {"calories": 2000, "protein_g": 140,
                    "carbs_g": 220, "fat_g": 70}}, "2026-10-25T00:00:00+00:00")
    changed = client.put("/nutrition/goal", headers=headers,
                         json={"goal": "gain", "intensity": "light"})
    assert changed.status_code == 200, changed.text
    with db.open_ledger(account["ledger_id"]) as ledger:
        stale = ledger.get_nutrition_pace_proposal()
        assert stale["status"] == "stale"
        _backdate_active_nutrition_plan(ledger, start)
    from service.nutrition import evaluate_pace_check
    with db.open_ledger(account["ledger_id"]) as ledger:
        proposal = evaluate_pace_check(ledger, _player_today(db, "pace-superseded"))
    assert proposal is not None
    assert proposal["plan_version_id"] == 2


def test_accepting_pace_proposal_preserves_training_and_rest_targets(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-split", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-split", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    account = db.get_active_account_by_username("pace-split")
    start = _player_today(db, "pace-split") - timedelta(days=24)
    with db.open_ledger(account["ledger_id"]) as ledger:
        _seed_pace_weight_history(ledger, start, (70, 68.6, 67.2, 65.8))
        _backdate_active_nutrition_plan(ledger, start)
        ledger.conn.execute("DROP TRIGGER nutrition_plan_versions_no_update")
        ledger.conn.execute("UPDATE nutrition_plan_versions SET targets_json=? WHERE id=1", (json.dumps({
            "daily": {"calories": 2600, "protein_g": 140, "carbs_g": 335, "fat_g": 80},
            "training_day": {"calories": 2600, "protein_g": 140, "carbs_g": 335, "fat_g": 80,
                              "fiber_g": 40, "fiber_g_source": "coach", "water_ml": 4000,
                              "water_ml_source": "coach"},
            "rest_day": {"calories": 2000, "protein_g": 140, "carbs_g": 185, "fat_g": 80,
                         "fiber_g": 40, "fiber_g_source": "coach", "water_ml": 4000,
                         "water_ml_source": "coach"},
        }),))
        ledger.conn.execute(
            "CREATE TRIGGER nutrition_plan_versions_no_update BEFORE UPDATE ON nutrition_plan_versions "
            "BEGIN SELECT RAISE(ABORT, 'Nutrition plan versions are immutable'); END")
        ledger.conn.commit()
    from service.nutrition import evaluate_pace_check
    with db.open_ledger(account["ledger_id"]) as ledger:
        proposal = evaluate_pace_check(ledger, _player_today(db, "pace-split"))
    assert proposal is not None
    split = proposal["payload"]["target_options"]
    delta = proposal["payload"]["calorie_change"]
    assert split["training_day"]["calories"] == 2600 + delta
    assert split["rest_day"]["calories"] == 2000 + delta
    assert split["training_day"]["fiber_g"] == 40
    assert split["training_day"]["water_ml"] == 4000
    response = client.post(f"/nutrition/pace-proposals/{proposal['id']}/decision",
                           headers=headers, json={"decision": "accepted"})
    assert response.status_code == 200, response.text
    with db.open_ledger(account["ledger_id"]) as ledger:
        targets = json.loads(ledger.get_active_nutrition_plan()["targets_json"])
    assert targets["training_day"]["calories"] == 2600 + delta
    assert targets["rest_day"]["calories"] == 2000 + delta
    assert targets["training_day"]["fiber_g"] == 40
    assert targets["training_day"]["water_ml"] == 4000


def test_pace_history_window_starts_on_player_local_plan_date(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-la-date", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-la-date", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    account = db.get_active_account_by_username("pace-la-date")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.append_training_schedule(account["ledger_id"], [1, 3, 5], "America/Los_Angeles",
            "2026-09-01", "2026-09-01T00:00:00+00:00")
        ledger.conn.execute("DROP TRIGGER nutrition_plan_versions_no_update")
        ledger.conn.execute("UPDATE nutrition_plan_versions SET created_at=? WHERE id=1",
                            ("2026-10-01T02:00:00+00:00",))
        ledger.conn.execute("CREATE TRIGGER nutrition_plan_versions_no_update BEFORE UPDATE ON nutrition_plan_versions "
                            "BEGIN SELECT RAISE(ABORT, 'Nutrition plan versions are immutable'); END")
        _seed_pace_weight_history(ledger, date(2026, 9, 30), (70, 68, 66, 64))
    from service.nutrition import evaluate_pace_check
    with db.open_ledger(account["ledger_id"]) as ledger:
        proposal = evaluate_pace_check(ledger, _player_today(db, "pace-la-date"))
    assert proposal is not None


def test_capped_reduction_keeps_proposal_macros_balanced(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-macro-cap", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-macro-cap", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    account = db.get_active_account_by_username("pace-macro-cap")
    start = _player_today(db, "pace-macro-cap") - timedelta(days=24)
    with db.open_ledger(account["ledger_id"]) as ledger:
        _backdate_active_nutrition_plan(ledger, start)
        ledger.conn.execute("DROP TRIGGER nutrition_plan_versions_no_update")
        ledger.conn.execute("UPDATE nutrition_plan_versions SET targets_json=? WHERE id=1", (json.dumps({
            "daily": {"calories": 2000, "protein_g": 200, "carbs_g": 30, "fat_g": 120},
        }),))
        ledger.conn.execute("CREATE TRIGGER nutrition_plan_versions_no_update BEFORE UPDATE ON nutrition_plan_versions "
                            "BEGIN SELECT RAISE(ABORT, 'Nutrition plan versions are immutable'); END")
        ledger.conn.commit()
        _seed_pace_weight_history(ledger, start, (70, 72, 74, 76))
    from service.nutrition import evaluate_pace_check
    with db.open_ledger(account["ledger_id"]) as ledger:
        proposal = evaluate_pace_check(ledger, _player_today(db, "pace-macro-cap"))
    assert proposal is not None
    proposed = proposal["payload"]["targets"]
    assert proposed["calories"] == 1750
    assert proposed["fat_g"] < 120
    assert proposed["protein_g"] == 200
    macro_calories = 4 * proposed["protein_g"] + 4 * proposed["carbs_g"] + 9 * proposed["fat_g"]
    assert abs(macro_calories - proposed["calories"]) <= proposed["calories"] * .05
    response = client.post(f"/nutrition/pace-proposals/{proposal['id']}/decision",
                           headers=headers, json={"decision": "accepted"})
    assert response.status_code == 200, response.text


def test_pace_check_waits_for_three_weeks_and_skips_small_pace_gap(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-threshold", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-threshold", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    account = db.get_active_account_by_username("pace-threshold")
    from datetime import timedelta
    threshold_weight = 70 / (1 - (0.1499 * 21) / (100 * 7))
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert ledger.get_last_nutrition_pace_check_date() is None
        start = _player_today(db, "pace-threshold") - timedelta(days=21)
        _backdate_active_nutrition_plan(ledger, start)
        for offset, weight in ((0, 70), (1, 70.05)):
            profile = ledger.get_player_profile()
            profile["weight_kg"] = weight
            ledger.upsert_player_profile_with_weight_history(
                profile, (start + timedelta(days=offset)).isoformat())
    first_weight = client.post("/profile/weight", headers=headers, json={"weight_kg": threshold_weight})
    assert first_weight.status_code == 200
    assert client.get("/nutrition", headers=headers).json()["pace_proposal"] is None
    with db.open_ledger(account["ledger_id"]) as ledger:
        profile = ledger.get_player_profile()
        profile["weight_kg"] = 70.15
        ledger.upsert_player_profile_with_weight_history(
            profile, (start + timedelta(days=7)).isoformat())
    second_weight = client.post("/profile/weight", headers=headers, json={"weight_kg": threshold_weight})
    assert second_weight.status_code == 200
    assert client.get("/nutrition", headers=headers).json()["pace_proposal"] is None
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert ledger.get_nutrition_pace_proposal() is None
        assert ledger.get_last_nutrition_pace_check_date() == _player_today(db, "pace-threshold").isoformat()


def test_pace_proposal_caps_gain_and_keeps_consented_metadata(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-gain-cap", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-gain-cap", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    client.put("/nutrition/goal", headers=headers, json={"goal": "gain", "intensity": "aggressive"})
    account = db.get_active_account_by_username("pace-gain-cap")
    start = _player_today(db, "pace-gain-cap") - timedelta(days=21)
    with db.open_ledger(account["ledger_id"]) as ledger:
        _backdate_active_nutrition_plan(ledger, start)
        _seed_pace_weight_history(ledger, start, (79.76, 79.84, 79.92, 80))
    from service.nutrition import evaluate_pace_check
    with db.open_ledger(account["ledger_id"]) as ledger:
        proposal = evaluate_pace_check(ledger, _player_today(db, "pace-gain-cap"))
    assert proposal is not None
    assert proposal["payload"]["targets"]["calories"] <= 2448.5 + 0.005 * 80 * 7700 / 7
    assert proposal["payload"]["targets"]["weekly_rate_pct"] <= 0.5
    accepted = client.post(f"/nutrition/pace-proposals/{proposal['id']}/decision", headers=headers,
                           json={"decision": "accepted"})
    assert accepted.status_code == 200, accepted.text
    with db.open_ledger(account["ledger_id"]) as ledger:
        plan = ledger.get_active_nutrition_plan()
    targets = json.loads(plan["targets_json"])["daily"]
    assert all(key in targets for key in ("weekly_rate_pct", "maintenance", "floor_applied", "calorie_floor"))
    assert plan["provenance"] == "player_consented"
    assert targets["weekly_rate_pct"] <= 0.5


def test_aggressive_lose_proposal_stays_within_one_percent_rate_cap(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-lose-cap", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-lose-cap", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    client.put("/nutrition/goal", headers=headers, json={"goal": "lose", "intensity": "aggressive"})
    account = db.get_active_account_by_username("pace-lose-cap")
    today = _player_today(db, "pace-lose-cap")
    start = today - timedelta(days=21)
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.conn.execute("DROP TRIGGER nutrition_plan_versions_no_update")
        ledger.conn.execute("UPDATE nutrition_plan_versions SET targets_json=? WHERE id=2", (json.dumps({
            "daily": {"calories": 1700, "protein_g": 140, "carbs_g": 135, "fat_g": 60,
                "weekly_rate_pct": 1.0}}),))
        ledger.conn.execute("CREATE TRIGGER nutrition_plan_versions_no_update BEFORE UPDATE ON nutrition_plan_versions "
                            "BEGIN SELECT RAISE(ABORT, 'Nutrition plan versions are immutable'); END")
        ledger.conn.commit()
        _backdate_active_nutrition_plan(ledger, start)
        _seed_pace_weight_history(ledger, start, (71.05, 70.7, 70.35, 70))
        from service.nutrition import evaluate_pace_check
        proposal = evaluate_pace_check(ledger, today)
    assert proposal is not None
    assert proposal["payload"]["targets"]["weekly_rate_pct"] <= 1.0


def test_twenty_one_day_window_with_only_two_iso_weeks_is_not_eligible(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-iso-weeks", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-iso-weeks", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    account = db.get_active_account_by_username("pace-iso-weeks")
    from service.nutrition import evaluate_pace_check
    from service.weight_history import player_local_date
    with db.open_ledger(account["ledger_id"]) as ledger:
        today = player_local_date(ledger, str(ledger.ledger_id))
        start = date(2026, 10, 5)  # Monday; both endpoints are in ISO weeks 41 and 44.
        _backdate_active_nutrition_plan(ledger, start)
        for when, weight in ((start, 70), (start + timedelta(days=21), 68)):
            profile = ledger.get_player_profile()
            profile["weight_kg"] = weight
            ledger.upsert_player_profile_with_weight_history(profile, when.isoformat())
        proposal = evaluate_pace_check(ledger, max(today, start + timedelta(days=21)))
    assert proposal is None


def test_pace_evaluation_is_recorded_without_eligible_history(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-cadence", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-cadence", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    account = db.get_active_account_by_username("pace-cadence")
    from service.nutrition import evaluate_pace_check
    from service.weight_history import player_local_date
    with db.open_ledger(account["ledger_id"]) as ledger:
        today = player_local_date(ledger, str(ledger.ledger_id))
        first = evaluate_pace_check(ledger, today)
        last_checked = ledger.get_last_nutrition_pace_check_date()
        second = evaluate_pace_check(ledger, today + timedelta(days=1))
    assert first is None and second is None
    assert last_checked == today.isoformat()


@pytest.mark.parametrize(("actual_rate", "creates"), [(0.1499, False), (0.1501, True)])
def test_pace_gap_threshold_uses_strictly_more_than_point_15(api, actual_rate, creates):
    client, db = api
    username = f"pace-gap-{str(actual_rate).replace('.', '')}"
    registered = client.post("/auth/register", json={"trainee_id": username, "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, username, age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    account = db.get_active_account_by_username(username)
    today = _player_today(db, username)
    start = today - timedelta(days=21)
    latest = 70.0
    first = latest * (1 + actual_rate * 3 / 100)
    with db.open_ledger(account["ledger_id"]) as ledger:
        _backdate_active_nutrition_plan(ledger, start)
        _seed_pace_weight_history(ledger, start, (first, latest + 2 * (first-latest)/3,
                                latest + (first-latest)/3, latest))
        from service.nutrition import evaluate_pace_check
        result = evaluate_pace_check(ledger, today)
    assert (result is not None) is creates


def test_uncapped_exact_gap_changes_calories_by_154(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-exact", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-exact", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    client.put("/nutrition/goal", headers=headers, json={"goal": "lose", "intensity": "moderate"})
    account = db.get_active_account_by_username("pace-exact")
    today = _player_today(db, "pace-exact")
    start = today - timedelta(days=21)
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.conn.execute("DROP TRIGGER nutrition_plan_versions_no_update")
        ledger.conn.execute("UPDATE nutrition_plan_versions SET goal='lose', intensity='moderate', targets_json=? WHERE id=1", (json.dumps({
            "daily": {"calories": 2400, "protein_g": 140, "carbs_g": 310, "fat_g": 80,
                "weekly_rate_pct": 0.5}}),))
        ledger.conn.execute("CREATE TRIGGER nutrition_plan_versions_no_update BEFORE UPDATE ON nutrition_plan_versions "
                            "BEGIN SELECT RAISE(ABORT, 'Nutrition plan versions are immutable'); END")
        ledger.conn.commit()
        _backdate_active_nutrition_plan(ledger, start)
        _seed_pace_weight_history(ledger, start, (70.63, 70.42, 70.21, 70))
        from service.nutrition import evaluate_pace_check
        proposal = evaluate_pace_check(ledger, today)
    assert proposal is not None
    assert proposal["payload"]["calorie_change"] == -154, proposal["payload"]
    assert proposal["payload"]["targets"]["calories"] == 2246


def test_coach_nutrition_requires_assignment_and_takeover_confirmation(api):
    client, db = api
    coach = client.post("/auth/register", json={"trainee_id": "nutrition-coach", "password": "correct-horse-1"}).json()
    coach_headers = {"Authorization": f"Bearer {coach['access_token']}"}
    from service import coach as coach_service
    issued = coach_service.issue_coach_invite(db, "nutrition-coach", actor="cli")
    assert client.post("/coach/invite/redeem", headers=coach_headers, json={"token": issued["token"]}).status_code == 200
    assert client.put("/coach/profile", headers=coach_headers, json={"display_name":"Coach", "bio":"b", "specialization":"s", "capacity":5}).status_code == 200
    player = client.post("/auth/register", json={"trainee_id": "nutrition-client", "password": "correct-horse-1"}).json()
    player_headers = {"Authorization": f"Bearer {player['access_token']}"}
    denied = client.get("/coach/assignments/nope/nutrition", headers=coach_headers)
    assert denied.status_code == 403
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    redeemed = client.post("/assignments/invites/redeem", headers=player_headers, json={"token":token,"consent":True}).json()
    assignment_id = redeemed["assignment"]["assignment_id"]
    _seed_profile(db, "nutrition-client", age=30, target=None)
    setup = client.post("/nutrition/setup", headers=player_headers, json={
        "sex":"male", "sex_confirmed":True, "daily_activity":"mostly_sitting",
        "screening":{"pregnant_or_breastfeeding":False,"medical_condition":False,"eating_disorder":False}})
    assert setup.status_code == 200
    from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema
    coach_account_id = db.get_active_account_by_username("nutrition-coach")["account_id"]
    player_account = db.get_active_account_by_username("nutrition-client")
    db.catalog_conn.executemany(
        "INSERT INTO exercises (id, name, body_part, target_muscle, equipment) VALUES (?, ?, 'Test', 'Test', 'Test')",
        [("sq", "Squat"), ("bp", "Bench Press"), ("row", "Row")],
    )
    db.catalog_conn.commit()
    program = GeneratedProgramSchema(
        program_name="Published training program", split_type="Full Body", weekly_frequency=4,
        days=[ProgramDaySchema(day_name="Full A", day_order=1, exercises=[
                ProgramExerciseSchema(exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8),
                ProgramExerciseSchema(exercise_id="bp", exercise_name="Bench Press", target_reps_min=5, target_reps_max=8),
                ProgramExerciseSchema(exercise_id="row", exercise_name="Row", target_reps_min=5, target_reps_max=8),
        ])],
    )
    with db.open_ledger(player_account["ledger_id"]) as ledger:
        ledger.save_training_program(program.model_dump())
    published = client.post(f"/coach/assignments/{assignment_id}/program/approve",
                            headers=coach_headers, json={"expected_active_version": 1})
    assert published.status_code == 200, published.text
    assert client.get("/nutrition", headers=player_headers).json()["authority"] == "player"
    payload = {"goal":"lose", "targets":{"calories":2000, "protein_g":126, "carbs_g":248,
                                              "fat_g":56, "fiber_g":35, "water_ml":4000}}
    path = f"/coach/assignments/{assignment_id}/nutrition"
    initial_read = client.get(path, headers=coach_headers)
    assert initial_read.json()["authority"] == "player"
    assert len(initial_read.json()["adherence_days"]) == 14
    charts_read = client.get(f"{path}?days=28", headers=coach_headers).json()
    assert len(charts_read["adherence_days"]) == 28
    assert isinstance(charts_read["weight_trend"], list)
    assert isinstance(initial_read.json()["weight_trend"], list)
    with db.open_ledger(player_account["ledger_id"]) as ledger:
        active_before_takeover = ledger.get_active_nutrition_plan()
        with ledger.ledger_transaction():
            player_held_proposal = ledger.create_nutrition_pace_proposal(
                active_before_takeover["id"], {"kind": "pace", "goal": "maintain", "intensity": None,
                    "actual_rate_pct": 0.2, "planned_rate_pct": 0,
                    "calorie_change": 0, "targets": setup.json()["targets"]}, "2026-10-25T00:00:00+00:00")
    coach_without_authority = client.post(
        f"/coach/assignments/{assignment_id}/nutrition/pace-proposals/{player_held_proposal}/decision",
        headers=coach_headers, json={"decision": "kept"})
    assert coach_without_authority.status_code == 403
    player_keeps = client.post(f"/nutrition/pace-proposals/{player_held_proposal}/decision",
                               headers=player_headers, json={"decision": "kept"})
    assert player_keeps.status_code == 200, player_keeps.text
    assert "weekly_rate_pct" in initial_read.json()["targets"]
    missing_confirmation = client.put(path, headers=coach_headers, json=payload)
    assert missing_confirmation.status_code == 400
    assert "confirm" in missing_confirmation.json()["detail"].lower()
    payload["confirm_takeover"] = True
    saved = client.put(path, headers=coach_headers, json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["authority"] == "coach"
    assert saved.json()["targets"]["fiber_g"] == 35
    assert saved.json()["targets"]["water_ml"] == 4000
    assert saved.json()["targets"]["water_ml_source"] == "coach"
    assert saved.json()["targets"]["training_day_water_ml"] == 4000
    assert saved.json()["targets"]["training_day_water_ml_source"] == "coach"
    invalid = client.put(path, headers=coach_headers, json={**payload,
        "targets": {**payload["targets"], "fiber_g": 81}})
    assert invalid.status_code == 400
    assert "fiber_g" in invalid.json()["detail"] and "80" in invalid.json()["detail"]
    invalid_water = client.put(path, headers=coach_headers, json={**payload,
        "targets": {**payload["targets"], "water_ml": 3125}})
    assert invalid_water.status_code == 400
    assert "water_ml" in invalid_water.json()["detail"]
    for amount, boundary in ((999, "1000"), (6250, "6000")):
        invalid_water = client.put(path, headers=coach_headers, json={**payload,
            "targets": {**payload["targets"], "water_ml": amount}})
        assert invalid_water.status_code == 400
        assert "water_ml" in invalid_water.json()["detail"]
        assert boundary in invalid_water.json()["detail"]
    blank_payload = {**payload, "targets": {key: value for key, value in payload["targets"].items()
                                            if key not in ("fiber_g", "water_ml")}}
    blank_saved = client.put(path, headers=coach_headers, json=blank_payload)
    assert blank_saved.status_code == 200, blank_saved.text
    with db.open_ledger(player_account["ledger_id"]) as ledger:
        persisted = json.loads(ledger.get_active_nutrition_plan()["targets_json"])["daily"]
    assert persisted["fiber_g"] == round(2000 * 14 / 1000)
    assert persisted["water_ml"] == 2500
    assert persisted["fiber_g_source"] == "default"
    assert persisted["water_ml_source"] == "default"
    with db.open_ledger(player_account["ledger_id"]) as ledger:
        ledger.conn.execute("UPDATE user_profile SET weight_kg=80 WHERE id=1")
        ledger.conn.commit()
    with db.open_ledger(player_account["ledger_id"]) as ledger:
        persisted_after_weight_change = json.loads(ledger.get_active_nutrition_plan()["targets_json"])["daily"]
        assert persisted_after_weight_change["water_ml"] == 2500
        ledger.conn.execute("UPDATE user_profile SET weight_kg=70 WHERE id=1")
        ledger.conn.commit()
    with db.open_ledger(player_account["ledger_id"]) as ledger:
        active_plan = ledger.get_active_nutrition_plan()
        proposal_targets = {key: setup.json()["targets"][key]
                            for key in ("calories", "protein_g", "carbs_g", "fat_g")}
        with ledger.ledger_transaction():
            pace_proposal_id = ledger.create_nutrition_pace_proposal(
                active_plan["id"], {"kind": "pace", "goal": "maintain", "intensity": None,
                    "actual_rate_pct": 0.3, "planned_rate_pct": 0,
                    "calorie_change": 0, "targets": proposal_targets}, "2026-10-25T00:00:00+00:00")
    player_cannot_decide = client.post(
        f"/nutrition/pace-proposals/{pace_proposal_id}/decision", headers=player_headers,
        json={"decision": "accepted"})
    assert player_cannot_decide.status_code == 403
    coach_decision = client.post(
        f"/coach/assignments/{assignment_id}/nutrition/pace-proposals/{pace_proposal_id}/decision",
        headers=coach_headers, json={"decision": "accepted"})
    assert coach_decision.status_code == 200, coach_decision.text
    assert coach_decision.json()["authority"] == "coach"
    assert coach_decision.json()["pace_proposal"]["status"] == "accepted"
    with db.open_ledger(player_account["ledger_id"]) as ledger:
        assert ledger.get_active_nutrition_plan()["provenance"] == "coach_consented"
    with db.open_ledger(player_account["ledger_id"]) as ledger:
        current = ledger.get_active_nutrition_plan()
        with ledger.ledger_transaction():
            coach_keep_id = ledger.create_nutrition_pace_proposal(
                current["id"], {"kind": "pace", "goal": "lose", "intensity": "light",
                    "actual_rate_pct": -0.1, "planned_rate_pct": -0.25,
                    "calorie_change": -50, "targets": proposal_targets}, "2026-10-25T00:00:00+00:00")
    coach_keep = client.post(
        f"/coach/assignments/{assignment_id}/nutrition/pace-proposals/{coach_keep_id}/decision",
        headers=coach_headers, json={"decision": "kept"})
    assert coach_keep.status_code == 200, coach_keep.text
    assert coach_keep.json()["pace_proposal"]["status"] == "kept"
    activity_change = client.put("/nutrition/activity", headers=player_headers,
                                 json={"daily_activity": "physical_job"})
    assert activity_change.status_code == 403
    payload["confirm_takeover"] = False
    repeated = client.put(path, headers=coach_headers, json=payload)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["authority"] == "coach"
    planned_read = client.get(f"{path}?days=28", headers=coach_headers).json()
    assert planned_read["planned_weekly_rate_pct"] < 0
    assert planned_read["planned_weekly_rate_pct"] == pytest.approx(-0.39, abs=0.03)
    string_targets = {key: str(value) for key, value in payload["targets"].items()}
    normalized = client.put(path, headers=coach_headers, json={**payload, "targets": string_targets})
    assert normalized.status_code == 200, normalized.text
    assert all(isinstance(normalized.json()["targets"][key], int) for key in
               ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "water_ml"))
    with db.open_ledger(db.get_active_account_by_username("nutrition-client")["ledger_id"]) as ledger:
        saved_targets = json.loads(ledger.get_active_nutrition_plan()["targets_json"])["daily"]
    assert all(isinstance(saved_targets[key], int) for key in
               ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "water_ml"))
    with db.open_ledger(db.get_active_account_by_username("nutrition-client")["ledger_id"]) as ledger:
        ledger.save_training_program(program.model_dump(), published_by_coach_account_id=coach_account_id)
    assert client.get(path, headers=coach_headers).json()["authority"] == "coach"
    assert client.get("/nutrition", headers=player_headers).json()["authority"] == "coach"
    assert client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers).status_code == 200
    returned = client.get("/nutrition", headers=player_headers).json()
    assert returned["authority"] == "player"


@pytest.mark.parametrize("goal", ["maintain", "gain"])
def test_coach_can_save_maintain_or_gain_targets_for_under_18_player(api, goal):
    client, db = api
    coach = client.post("/auth/register", json={"trainee_id": f"minor-coach-{goal}", "password": "correct-horse-1"}).json()
    coach_headers = {"Authorization": f"Bearer {coach['access_token']}"}
    from service import coach as coach_service
    issued = coach_service.issue_coach_invite(db, f"minor-coach-{goal}", actor="cli")
    assert client.post("/coach/invite/redeem", headers=coach_headers, json={"token": issued["token"]}).status_code == 200
    assert client.put("/coach/profile", headers=coach_headers, json={"display_name":"Coach", "bio":"b", "specialization":"s", "capacity":5}).status_code == 200
    player_name = f"minor-player-{goal}"
    player = client.post("/auth/register", json={"trainee_id": player_name, "password": "correct-horse-1"}).json()
    player_headers = {"Authorization": f"Bearer {player['access_token']}"}
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    assignment = client.post("/assignments/invites/redeem", headers=player_headers,
                             json={"token": token, "consent": True}).json()["assignment"]
    _seed_profile(db, player_name, age=17, target=None)
    target_calories = 2450 if goal == "gain" else 2000
    target_carbs = 362 if goal == "gain" else 250
    saved = client.put(f"/coach/assignments/{assignment['assignment_id']}/nutrition",
                       headers=coach_headers, json={"goal": goal, "confirm_takeover": True,
                       "targets": {"calories": target_calories, "protein_g": 100,
                                   "carbs_g": target_carbs, "fat_g": 67}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["goal"] == goal


@pytest.mark.parametrize(("case", "profile", "body", "expected"), [
    ("incomplete profile", None, {"goal": "maintain", "confirm_takeover": True,
     "targets": {"calories": 2000, "protein_g": 100, "carbs_g": 250, "fat_g": 67}}, "Training profile"),
    ("screening block", {"age": 30, "height_cm": 165, "weight_kg": 70, "gender": "male"},
     {"goal": "maintain", "confirm_takeover": True, "targets": {"calories": 2000, "protein_g": 100, "carbs_g": 250, "fat_g": 67}}, "dietitian"),
    ("under-18 loss", {"age": 17, "height_cm": 165, "weight_kg": 70, "gender": "male"},
     {"goal": "lose", "confirm_takeover": True, "targets": {"calories": 2000, "protein_g": 100, "carbs_g": 250, "fat_g": 67}}, "under 18"),
    ("missing confirmation", {"age": 30, "height_cm": 165, "weight_kg": 70, "gender": "male"},
     {"goal": "maintain", "targets": {"calories": 2000, "protein_g": 100, "carbs_g": 250, "fat_g": 67}}, "Confirm"),
    ("missing targets", {"age": 30, "height_cm": 165, "weight_kg": 70, "gender": "male"},
     {"goal": "maintain", "confirm_takeover": True}, "Set Nutrition targets"),
    ("calorie floor", {"age": 30, "height_cm": 165, "weight_kg": 70, "gender": "male"},
     {"goal": "maintain", "confirm_takeover": True,
      "targets": {"calories": 1500, "protein_g": 100, "carbs_g": 250, "fat_g": 67}}, "Calorie floor"),
    ("macro calories", {"age": 30, "height_cm": 165, "weight_kg": 70, "gender": "male"},
     {"goal": "maintain", "confirm_takeover": True,
      "targets": {"calories": 2000, "protein_g": 0, "carbs_g": 0, "fat_g": 0}}, "within 5%"),
    ("negative macro", {"age": 30, "height_cm": 165, "weight_kg": 70, "gender": "male"},
     {"goal": "maintain", "confirm_takeover": True,
      "targets": {"calories": 2000, "protein_g": -1, "carbs_g": 250, "fat_g": 67}}, "protein_g must be a whole number"),
    ("boolean calories", {"age": 30, "height_cm": 165, "weight_kg": 70, "gender": "male"},
     {"goal": "maintain", "confirm_takeover": True,
      "targets": {"calories": True, "protein_g": 100, "carbs_g": 250, "fat_g": 67}}, "calories must be a whole number"),
    ("gain rate cap", {"age": 30, "height_cm": 165, "weight_kg": 70, "gender": "male"},
     {"goal": "gain", "confirm_takeover": True,
      "targets": {"calories": 3000, "protein_g": 150, "carbs_g": 400, "fat_g": 89}}, "0.5% per week"),
    ("maintain surplus rate cap", {"age": 30, "height_cm": 165, "weight_kg": 70, "gender": "male"},
     {"goal": "maintain", "confirm_takeover": True,
      "targets": {"calories": 5000, "protein_g": 200, "carbs_g": 825, "fat_g": 100}}, "0.5% per week"),
    ("lose rate cap", {"age": 30, "height_cm": 165, "weight_kg": 70, "gender": "male"},
     {"goal": "lose", "daily_activity": "physical_job", "confirm_takeover": True,
      "targets": {"calories": 1600, "protein_g": 100, "carbs_g": 149, "fat_g": 67}}, "1% per week"),
])
def test_coach_nutrition_validation_rules(case, profile, body, expected, api):
    client, db = api
    suffix = case.lower().replace(" ", "-")
    coach = client.post("/auth/register", json={"trainee_id": f"coach-{suffix}", "password": "correct-horse-1"}).json()
    coach_headers = {"Authorization": f"Bearer {coach['access_token']}"}
    from service import coach as coach_service
    invite = coach_service.issue_coach_invite(db, f"coach-{suffix}", actor="cli")
    assert client.post("/coach/invite/redeem", headers=coach_headers, json={"token": invite["token"]}).status_code == 200
    assert client.put("/coach/profile", headers=coach_headers, json={
        "display_name": "Coach", "bio": "b", "specialization": "s", "capacity": 5,
    }).status_code == 200
    player_name = f"player-{suffix}"
    player = client.post("/auth/register", json={"trainee_id": player_name, "password": "correct-horse-1"}).json()
    player_headers = {"Authorization": f"Bearer {player['access_token']}"}
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    assignment = client.post("/assignments/invites/redeem", headers=player_headers,
                             json={"token": token, "consent": True}).json()["assignment"]
    if profile is not None:
        _seed_profile(db, player_name, age=profile["age"], target=None)
    if case == "screening block":
        client.post("/nutrition/setup", headers=player_headers, json={
            "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
            "screening": {"pregnant_or_breastfeeding": False, "medical_condition": True,
                          "eating_disorder": False},
        })
    response = client.put(
        f"/coach/assignments/{assignment['assignment_id']}/nutrition",
        headers=coach_headers, json=body,
    )
    assert response.status_code == 400, response.text
    assert expected.lower() in response.json()["detail"].lower()


def test_player_target_uses_training_or_rest_day_schedule_and_assignment_authority(api, monkeypatch):
    from datetime import date
    from database.ledger.nutrition import NutritionPlanVersion
    from svc.routers import nutrition as nutrition_router

    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "nutrition-day-type", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "nutrition-day-type", age=30, target=None)
    account = db.get_active_account_by_username("nutrition-day-type")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.save_nutrition_plan(NutritionPlanVersion(
            goal="maintain", reason={"code": "coach"}, intensity=None,
            daily_activity="mostly_sitting", author="Coach", provenance="coach",
            authority_assignment_id="prior-assignment",
            targets={
                "daily": None,
                "training_day": {"calories": 2200, "protein_g": 120, "carbs_g": 260, "fat_g": 71},
                "rest_day": {"calories": 1900, "protein_g": 120, "carbs_g": 185, "fat_g": 71},
            },
        ))
        ledger.append_training_schedule(account["ledger_id"], [1], "UTC", "2026-10-01", "2026-10-01T00:00:00Z")
    monkeypatch.setattr(nutrition_router, "player_local_date", lambda *_args, **_kwargs: date(2026, 10, 26))
    monkeypatch.setattr(db, "get_active_assignment_for_player", lambda _account: {"assignment_id": "new-assignment"})
    training = client.get("/nutrition", headers=headers).json()
    assert training["targets"]["calories"] == 2200
    assert training["target_day_type"] == "training_day"
    assert training["authority"] == "player"

    monkeypatch.setattr(nutrition_router, "player_local_date", lambda *_args, **_kwargs: date(2026, 10, 27))
    rest = client.get("/nutrition", headers=headers).json()
    assert rest["targets"]["calories"] == 1900
    assert rest["target_day_type"] == "rest_day"


def test_positive_rescreen_blocks_existing_plan_and_profileless_is_incomplete(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "rescreen-player", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "rescreen-player", age=30, target=None)
    payload = {"sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
               "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False}}
    assert client.post("/nutrition/setup", headers=headers, json=payload).json()["state"] == "ready"
    payload["screening"]["medical_condition"] = True
    assert client.post("/nutrition/setup", headers=headers, json=payload).json()["state"] == "blocked"
    assert client.get("/nutrition", headers=headers).json()["state"] == "blocked"
    fresh = client.post("/auth/register", json={"trainee_id": "no-profile", "password": "correct-horse-1"}).json()
    incomplete = client.get("/nutrition", headers={"Authorization": f"Bearer {fresh['access_token']}"}).json()
    assert incomplete["state"] == "incomplete"
    assert incomplete["message"]
    arabic = client.get("/nutrition", headers={"Authorization": f"Bearer {fresh['access_token']}",
                                               "Accept-Language": "ar"}).json()
    assert "الأهداف الغذائية" in arabic["message"]


def test_stored_female_gender_is_used_for_explicit_confirmation_and_no_silent_flip(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "female-player", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "female-player", age=30, target=None)
    account = db.get_active_account_by_username("female-player")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.conn.execute("UPDATE user_profile SET gender='female' WHERE id=1")
        ledger.conn.commit()
    assert client.get("/nutrition", headers=headers).json()["sex"] == "female"
    response = client.post("/nutrition/setup", headers=headers, json={
        "sex": "female", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    assert response.json()["targets"]["bmr"] == 1420.2
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert ledger.conn.execute("SELECT gender FROM user_profile").fetchone()[0] == "female"


def test_positive_screening_blocks_target_generation(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "screened-player", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "screened-player", age=30, target=None)
    response = client.post("/nutrition/setup", headers=headers, json={
        "sex": "female", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": True, "medical_condition": False, "eating_disorder": False},
    })
    assert response.status_code == 200
    assert response.json()["state"] == "blocked"
    assert "dietitian" in response.json()["message"].lower()
    assert client.get("/nutrition", headers=headers).json()["targets"] is None


def test_under_18_gets_explicit_no_targets_state(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "minor-player", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "minor-player", age=17, target=60)
    assert client.get("/nutrition", headers=headers).json()["state"] == "under_18"
    response = client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "on_feet",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    assert response.status_code == 200
    assert response.json()["state"] == "under_18"
    assert response.json()["targets"] is None
    assert client.get("/nutrition", headers=headers).json()["state"] == "under_18"


def test_target_weight_overrides_conflicting_current_goal(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "conflict-player", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "conflict-player", age=30, target=80, current_goal="fat loss")
    response = client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "on_feet",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    assert response.status_code == 200
    assert response.json()["goal"] == "gain"
    assert response.json()["goal_reason"]["code"] == "target_weight"


def test_silent_goal_without_target_starts_maintain_without_intensity(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "maintain-player", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "maintain-player", age=30, target=None)
    response = client.post("/nutrition/setup", headers=headers, json={
        "sex": "female", "sex_confirmed": True, "daily_activity": "physical_job",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    assert response.status_code == 200
    assert response.json()["goal"] == "maintain"
    assert response.json()["intensity"] is None
    assert response.json()["goal_reason"]["code"] == "default"


@pytest.mark.parametrize("target,goal", [(69.0, "maintain"), (71.0, "maintain"), (68.9, "lose"), (71.1, "gain")])
def test_target_weight_one_kg_band_resolves_goal(target, goal, api):
    client, db = api
    username = f"band-{target}"
    registered = client.post("/auth/register", json={"trainee_id": username, "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, username, age=30, target=target, current_goal="get stronger")
    response = client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    assert response.json()["goal"] == goal
    assert response.json()["goal_reason"]["code"] == "target_weight"


def test_goal_text_reason_is_structured_for_english_and_arabic(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "arabic-goal", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "arabic-goal", age=30, target=None, current_goal="خسارة الدهون")
    response = client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    assert response.json()["goal_reason"] == {"code": "current_goal", "goal_text": "خسارة الدهون"}
    for language in ("en", "ar"):
        saved = client.get("/nutrition", headers={**headers, "Accept-Language": language}).json()
        assert saved["goal_reason"]["goal_text"] == "خسارة الدهون"


def test_setup_analytics_event_excludes_screening_answers(api, recording_analytics):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "analytics-nutrition", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "analytics-nutrition", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={
        "sex": "female", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": True, "medical_condition": False, "eating_disorder": False},
    })
    events = [event for event in recording_analytics.events if event["event"] == "nutrition_setup_completed"]
    assert events[0]["properties"]["blocked"] is True
    assert "screening" not in events[0]["properties"]
    clear = client.post("/auth/register", json={"trainee_id": "analytics-clear", "password": "correct-horse-1"}).json()
    _seed_profile(db, "analytics-clear", age=30, target=None)
    client.post("/nutrition/setup", headers={"Authorization": f"Bearer {clear['access_token']}"}, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    assert [item["properties"]["blocked"] for item in recording_analytics.events
            if item["event"] == "nutrition_setup_completed"][-1] is False


def test_activity_save_creates_version_and_weight_entry_does_not_change_it(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "activity-plan", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "activity-plan", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    changed = client.put("/nutrition/activity", headers=headers, json={"daily_activity": "physical_job"})
    assert changed.json()["daily_activity"] == "physical_job"
    before = changed.json()["targets"]
    client.post("/profile/weight", headers=headers, json={"weight_kg": 71})
    assert client.get("/nutrition", headers=headers).json()["targets"] == before
    account = db.get_active_account_by_username("activity-plan")
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert ledger.conn.execute("SELECT COUNT(*) FROM nutrition_plan_versions").fetchone()[0] == 2


def test_pace_preview_does_not_save_and_goal_save_versions_and_rescreens_lose(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "pace-player", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "pace-player", age=30, target=None)
    setup = {"sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
             "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False}}
    client.post("/nutrition/setup", headers=headers, json=setup)
    account = db.get_active_account_by_username("pace-player")
    before = client.get("/nutrition", headers=headers).json()
    preview = client.post("/nutrition/preview", headers=headers,
                          json={"goal": "lose", "intensity": "aggressive"})
    assert preview.status_code == 200
    assert preview.json()["targets"]["calories"] >= preview.json()["targets"]["calorie_floor"]
    assert "reach_target_date" in preview.json()
    assert client.get("/nutrition", headers=headers).json() == before
    changed = client.put("/nutrition/goal", headers=headers,
                         json={"goal": "gain", "intensity": "light"})
    assert changed.status_code == 200
    assert changed.json()["goal_reason"] == {"code": "player_choice"}
    assert changed.json().get("pending_goal") is None
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert ledger.conn.execute("SELECT COUNT(*) FROM nutrition_plan_versions").fetchone()[0] == 2
    rescreen = client.put("/nutrition/goal", headers=headers,
                          json={"goal": "lose", "intensity": "moderate"})
    assert rescreen.status_code == 400
    assert "screening" in rescreen.json()["detail"].lower()


def test_nutrition_read_offers_goal_update_after_target_edit(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "offer-player", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "offer-player", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    account = db.get_active_account_by_username("offer-player")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.conn.execute("UPDATE user_profile SET target_weight_kg=60 WHERE id=1")
        ledger.conn.commit()
    assert client.get("/nutrition", headers=headers).json()["pending_goal"] == "lose"


def test_nutrition_read_adds_half_extra_cardio_to_carbs_only(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "cardio-target", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "cardio-target", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    account = db.get_active_account_by_username("cardio-target")
    today = _player_today(db, "cardio-target")
    with db.open_ledger(account["ledger_id"]) as ledger:
        session_id = "cardio-day-session"
        ledger.conn.execute("INSERT INTO workout_sessions (id,session_date,split_name,started_at,completed_at) VALUES (?,?,?,?,?)",
                            (session_id, today.isoformat(), "Day 1", "now", "now"))
        ledger.conn.execute("INSERT INTO session_cardio_entries (session_id,machine,minutes,calories_kcal,calories_are_estimate,logged_at) VALUES (?,?,?,?,?,?)",
                            (session_id, "bike", 30, 301, 0, "now"))
        prior_id = "cardio-before-local-midnight"
        ledger.conn.execute("INSERT INTO workout_sessions (id,session_date,split_name,started_at,completed_at) VALUES (?,?,?,?,?)",
                            (prior_id, (today - timedelta(days=1)).isoformat(), "Day 1", "now", "now"))
        ledger.conn.execute("INSERT INTO session_cardio_entries (session_id,machine,minutes,calories_kcal,calories_are_estimate,logged_at) VALUES (?,?,?,?,?,?)",
                            (prior_id, "bike", 30, 1200, 0, "now"))
        ledger.conn.commit()
        stored = ledger.get_active_nutrition_plan()
        saved_targets = json.loads(stored["targets_json"])
    response = client.get("/nutrition", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["cardio_burned_kcal"] == 301
    assert body["cardio_adjustment_kcal"] == 150
    assert body["targets"]["calories"] == saved_targets["calories"] + 150
    assert body["targets"]["carbs_g"] == saved_targets["carbs_g"] + 38
    for key in ("protein_g", "fat_g", "fiber_g", "water_ml"):
        assert body["targets"][key] == saved_targets[key]
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert int(ledger.get_active_nutrition_plan()["id"]) == 1
    adherence = client.put("/nutrition/adherence", headers=headers, json={"value": "roughly"})
    assert adherence.status_code == 200
    assert adherence.json()["targets"]["calories"] == saved_targets["calories"] + 150
    assert adherence.json()["today_adherence"] == "roughly"


def test_nutrition_read_does_not_adjust_prescribed_cardio(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "cardio-prescribed", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "cardio-prescribed", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    account = db.get_active_account_by_username("cardio-prescribed")
    today = _player_today(db, "cardio-prescribed")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.save_training_program({"program_name": "Cardio plan", "weekly_frequency": 1,
            "split_type": "custom", "days": [{"day_name": "Day 1", "day_order": 1,
                "cardio": {"machine": "bike", "minutes": 30},
                "exercises": [{"exercise_id": "unused", "target_sets": 1,
                    "target_reps_min": 8, "target_reps_max": 8}]}]})
        session_id = "prescribed-cardio-session"
        ledger.conn.execute("INSERT INTO workout_sessions (id,session_date,split_name,started_at,completed_at,program_version,program_day_order) VALUES (?,?,?,?,?,?,?)",
                            (session_id, today.isoformat(), "Day 1", "now", "now", 1, 1))
        ledger.conn.execute("INSERT INTO session_cardio_entries (session_id,machine,minutes,calories_kcal,calories_are_estimate,logged_at) VALUES (?,?,?,?,?,?)",
                            (session_id, "bike", 30, 203, 0, "now"))
        ledger.conn.commit()
    body = client.get("/nutrition", headers=headers).json()
    assert body["cardio_burned_kcal"] == 203
    assert body["cardio_adjustment_kcal"] == 0


def test_nutrition_read_parses_legacy_treadmill_settings_for_prescribed_calories(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "legacy-cardio-prescribed", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "legacy-cardio-prescribed", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    account = db.get_active_account_by_username("legacy-cardio-prescribed")
    today = _player_today(db, "legacy-cardio-prescribed")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.save_training_program({"program_name": "Legacy cardio", "weekly_frequency": 1,
            "split_type": "custom", "days": [{"day_name": "Day 1", "day_order": 1,
                "cardio": "20 min treadmill, 5 km/h, 10% incline",
                "exercises": [{"exercise_id": "unused", "target_sets": 1,
                    "target_reps_min": 8, "target_reps_max": 8}]}]})
        session_id = "legacy-prescribed-cardio-session"
        ledger.conn.execute("INSERT INTO workout_sessions (id,session_date,split_name,started_at,completed_at,program_version,program_day_order) VALUES (?,?,?,?,?,?,?)",
                            (session_id, today.isoformat(), "Day 1", "now", "now", 1, 1))
        ledger.conn.execute("INSERT INTO session_cardio_entries (session_id,machine,minutes,speed_kmh,incline_pct,calories_kcal,calories_are_estimate,logged_at) VALUES (?,?,?,?,?,?,?,?)",
                            (session_id, "treadmill", 20, 5, 10, 163, 0, "now"))
        ledger.conn.commit()
    body = client.get("/nutrition", headers=headers).json()
    assert body["cardio_adjustment_kcal"] == 0


def test_pace_proposal_keeps_the_final_target_above_the_calorie_floor(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "cardio-pace-floor", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "cardio-pace-floor", age=30, target=None)
    account = db.get_active_account_by_username("cardio-pace-floor")
    today = _player_today(db, "cardio-pace-floor")
    start = today - timedelta(days=21)
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.conn.execute("UPDATE user_profile SET height_cm=175 WHERE id=1")
        ledger.conn.commit()
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.conn.execute("DROP TRIGGER nutrition_plan_versions_no_update")
        plan = ledger.get_active_nutrition_plan()
        targets = json.loads(plan["targets_json"])
        target = targets.get("daily", targets)
        target["calories"] = 1650
        target["weekly_rate_pct"] = 1.0
        target["carbs_g"] = round((1650 - target["protein_g"] * 4 - target["fat_g"] * 9) / 4)
        ledger.conn.execute("UPDATE nutrition_plan_versions SET goal='lose', intensity='aggressive', targets_json=? WHERE id=?",
                            (json.dumps(targets), plan["id"]))
        ledger.conn.execute("CREATE TRIGGER nutrition_plan_versions_no_update BEFORE UPDATE ON nutrition_plan_versions BEGIN SELECT RAISE(ABORT, 'Nutrition plan versions are immutable'); END")
        session_id = "cardio-pace-floor-session"
        ledger.conn.execute("INSERT INTO workout_sessions (id,session_date,split_name,started_at,completed_at) VALUES (?,?,?,?,?)",
                            (session_id, today.isoformat(), "Extra Cardio", "now", "now"))
        ledger.conn.execute("INSERT INTO session_cardio_entries (session_id,machine,minutes,calories_kcal,calories_are_estimate,logged_at) VALUES (?,?,?,?,?,?)",
                            (session_id, "bike", 60, 600, 0, "now"))
        ledger.conn.commit()
        _seed_pace_weight_history(ledger, start, (70, 70, 70, 70))
        ledger.conn.execute("DROP TRIGGER nutrition_plan_versions_no_update")
        ledger.conn.execute("UPDATE nutrition_plan_versions SET created_at=? WHERE id=?",
                            (start.isoformat() + "T00:00:00+00:00", plan["id"]))
        ledger.conn.execute("CREATE TRIGGER nutrition_plan_versions_no_update BEFORE UPDATE ON nutrition_plan_versions BEGIN SELECT RAISE(ABORT, 'Nutrition plan versions are immutable'); END")
        ledger.conn.commit()
    weight_entry = client.post("/profile/weight", headers=headers, json={"weight_kg": 70})
    assert weight_entry.status_code == 200, weight_entry.text
    nutrition = client.get("/nutrition", headers=headers).json()
    pending = nutrition["pace_proposal"]
    assert pending is not None
    floor = pending["payload"]["targets"]["calorie_floor"]
    assert pending["payload"]["targets"]["calories"] >= int(floor + 0.999)
    accepted = client.post(f"/nutrition/pace-proposals/{pending['id']}/decision",
                            headers=headers, json={"decision": "accepted"})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["targets"]["calories"] >= int(floor + 0.999)


def test_goal_offer_dismissal_is_stored_until_another_profile_change(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "dismiss-offer", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "dismiss-offer", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    account = db.get_active_account_by_username("dismiss-offer")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.conn.execute("UPDATE user_profile SET target_weight_kg=60 WHERE id=1")
        ledger.conn.commit()
    assert client.get("/nutrition", headers=headers).json()["pending_goal"] == "lose"
    response = client.post("/nutrition/goal-offer/dismiss", headers=headers)
    assert response.status_code == 200
    assert client.get("/nutrition", headers=headers).json().get("pending_goal") is None
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.conn.execute("UPDATE user_profile SET target_weight_kg=80 WHERE id=1")
        ledger.conn.commit()
    assert client.get("/nutrition", headers=headers).json()["pending_goal"] == "gain"


def test_preview_requires_confirmed_sex_and_screening(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "preview-setup", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "preview-setup", age=30, target=60)
    response = client.post("/nutrition/preview", headers=headers,
                           json={"goal": "lose", "intensity": "aggressive"})
    assert response.status_code == 200
    assert response.json()["state"] == "setup_required"
    assert response.json()["targets"] is None


def test_reach_target_date_uses_real_player_schedule_timezone(api, monkeypatch):
    from datetime import datetime, timezone
    from service import weight_history

    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "tokyo-local-date", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "tokyo-local-date", age=30, target=60)
    account = db.get_active_account_by_username("tokyo-local-date")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.append_training_schedule(account["ledger_id"], [0, 1], "Asia/Tokyo", "2026-01-01", "2026-01-01T00:00:00Z")
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 24, 22, 30, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(weight_history, "datetime", FrozenDateTime)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    response = client.post("/nutrition/preview", headers=headers,
                           json={"goal": "lose", "intensity": "moderate"}).json()
    rate = response["targets"]["weekly_rate_pct"]
    days = round(abs(60 - 70) / (70 * rate / 100) * 7)
    assert response["reach_target_date"] == (date(2026, 10, 25) + timedelta(days=days)).isoformat()


def test_adherence_requires_active_unblocked_nutrition_plan(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "no-plan-adherence", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "no-plan-adherence", age=30, target=None)
    no_plan = client.put("/nutrition/adherence", headers=headers, json={"value": "off"})
    assert no_plan.status_code == 409
    assert "Nutrition plan" in no_plan.json()["detail"]
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": True,
        "medical_condition": False, "eating_disorder": False}})
    blocked = client.put("/nutrition/adherence", headers=headers, json={"value": "off"})
    assert blocked.status_code == 409
    assert "screening" in blocked.json()["detail"].lower()


def test_saving_unchanged_nutrition_goal_is_noop(api, recording_analytics):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "same-pace", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "same-pace", age=30, target=60)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    account = db.get_active_account_by_username("same-pace")
    with db.open_ledger(account["ledger_id"]) as ledger:
        before = ledger.conn.execute("SELECT COUNT(*) FROM nutrition_plan_versions").fetchone()[0]
    response = client.put("/nutrition/goal", headers=headers, json={"goal": "lose", "intensity": "moderate"})
    assert response.status_code == 200
    with db.open_ledger(account["ledger_id"]) as ledger:
        after = ledger.conn.execute("SELECT COUNT(*) FROM nutrition_plan_versions").fetchone()[0]
    events = [event for event in recording_analytics.events if event["event"] == "nutrition_goal_saved"]
    assert after == before
    assert events == []


def test_goal_save_analytics_uuid_tracks_each_plan_version(api, recording_analytics):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "goal-event", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "goal-event", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    for goal, intensity in (("gain", "light"), ("maintain", "moderate"), ("gain", "light")):
        response = client.put("/nutrition/goal", headers=headers,
                              json={"goal": goal, "intensity": intensity})
        assert response.status_code == 200
    events = [event for event in recording_analytics.events if event["event"] == "nutrition_goal_saved"]
    assert len(events) == 3
    assert len({event["uuid"] for event in events}) == 3


def test_coach_authored_plan_without_active_assignment_does_not_withhold_player_authority(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "coach-plan", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "coach-plan", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    account = db.get_active_account_by_username("coach-plan")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.conn.execute("DROP TRIGGER nutrition_plan_versions_no_update")
        ledger.conn.execute("UPDATE nutrition_plan_versions SET author='Coach' WHERE id=(SELECT MAX(id) FROM nutrition_plan_versions)")
        ledger.conn.commit()
    response = client.put("/nutrition/goal", headers=headers,
                          json={"goal": "gain", "intensity": "light"})
    assert response.status_code == 200, response.text
    assert response.json()["authority"] == "player"


def _seed_pace_weight_history(ledger, start, weights):
    from datetime import timedelta

    for offset, weight in zip((0, 7, 14, 21), weights, strict=True):
        profile = ledger.get_player_profile()
        profile["weight_kg"] = weight
        ledger.upsert_player_profile_with_weight_history(
            profile, (start + timedelta(days=offset)).isoformat())


def _player_today(db, username):
    from service.weight_history import player_local_date

    account = db.get_active_account_by_username(username)
    with db.open_ledger(account["ledger_id"]) as ledger:
        return player_local_date(ledger, str(ledger.ledger_id))


def _backdate_active_nutrition_plan(ledger, start):
    created_at = start.isoformat() + "T00:00:00+00:00"
    ledger.conn.execute("DROP TRIGGER nutrition_plan_versions_no_update")
    ledger.conn.execute("UPDATE nutrition_plan_versions SET created_at=?", (created_at,))
    ledger.conn.execute(
        "CREATE TRIGGER nutrition_plan_versions_no_update BEFORE UPDATE ON nutrition_plan_versions "
        "BEGIN SELECT RAISE(ABORT, 'Nutrition plan versions are immutable'); END")
    ledger.conn.commit()


def _seed_profile(db, username, *, age, target, current_goal="get stronger"):
    account = db.get_active_account_by_username(username)
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.conn.execute("""INSERT OR REPLACE INTO user_profile (
            id, gender, sex_confirmed, daily_activity, proportions, age, weight_kg,
            target_weight_kg, height_cm, rep_preference, current_goal, long_term_goal,
            weekly_frequency, training_age_years, equipment_access, injuries_or_limitations,
            stress_and_sleep, coach_tone, custom_instructions, created_at, updated_at
        ) VALUES (1, 'male', 0, NULL, 'average', ?, 70, ?, 165, 'balanced',
            ?, '', 4, 1, 'Commercial gym', 'None', '', '', '', 'now', 'now')""", (age, target, current_goal))
        ledger.conn.commit()


def test_adherence_write_replaces_today_and_returns_seven_day_state(api, recording_analytics):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "adherence-player", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "adherence-player", age=30, target=60)
    client.post("/nutrition/setup", headers=headers, json={
        "sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
        "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False},
    })
    first = client.put("/nutrition/adherence", headers=headers, json={"value": "off"})
    assert first.status_code == 200, first.text
    second = client.put("/nutrition/adherence", headers=headers, json={"value": "on_target"})
    assert second.status_code == 200, second.text
    state = client.get("/nutrition", headers=headers).json()
    assert state["today_adherence"] == "on_target"
    assert len(state["adherence_days"]) == 7
    assert sum(day["value"] == "on_target" for day in state["adherence_days"]) == 1
    account = db.get_active_account_by_username("adherence-player")
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert ledger.conn.execute("SELECT COUNT(*) FROM nutrition_adherence").fetchone()[0] == 1
    events = [event for event in recording_analytics.events if event["event"] == "nutrition_adherence_logged"]
    assert [event["properties"]["value"] for event in events] == ["off", "on_target"]
    assert events[0]["uuid"] != events[1]["uuid"]


def test_adherence_rejects_non_today_date(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "adherence-date", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    response = client.put("/nutrition/adherence", headers=headers, json={"value": "off", "date": "2000-01-01"})
    assert response.status_code == 422


def test_adherence_write_uses_real_player_schedule_timezone(api, monkeypatch):
    from datetime import datetime, timezone
    from service import weight_history

    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "tokyo-adherence", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "tokyo-adherence", age=30, target=None)
    account = db.get_active_account_by_username("tokyo-adherence")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.append_training_schedule(account["ledger_id"], [0, 1], "Asia/Tokyo", "2026-01-01", "2026-01-01T00:00:00Z")
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 24, 22, 30, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(weight_history, "datetime", FrozenDateTime)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    updated = client.put("/nutrition/adherence", headers=headers, json={"value": "on_target"})
    assert updated.status_code == 200
    assert updated.json()["today_adherence"] == "on_target"
    assert updated.json()["adherence_days"][-1] == {
        "date": "2026-10-25", "value": "on_target", "source": "answered",
    }
    with db.open_ledger(account["ledger_id"]) as ledger:
        assert ledger.conn.execute("SELECT entry_date FROM nutrition_adherence").fetchone()[0] == "2026-10-25"


def test_setup_and_activity_return_complete_assigned_nutrition_state(api, monkeypatch):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "complete-nutrition", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "complete-nutrition", age=30, target=65)
    monkeypatch.setattr(db, "get_active_assignment_for_player", lambda _account: {"assignment_id": "active"})
    payload = {"sex": "male", "sex_confirmed": True, "daily_activity": "mostly_sitting",
               "screening": {"pregnant_or_breastfeeding": False, "medical_condition": False, "eating_disorder": False}}
    setup = client.post("/nutrition/setup", headers=headers, json=payload).json()
    for state in (setup, client.put("/nutrition/activity", headers=headers,
                                    json={"daily_activity": "on_feet"}).json()):
        assert len(state["adherence_days"]) == 7
        assert state["latest_weight"] == 70
        assert state["target_weight"] == 65
        assert state["coach_sees_adherence"] is True


def test_water_log_increments_undoes_and_emits_count_only_events(api, recording_analytics):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "water-player", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "water-player", age=30, target=None)
    client.post("/nutrition/setup", headers=headers, json={"sex": "male", "sex_confirmed": True,
        "daily_activity": "mostly_sitting", "screening": {"pregnant_or_breastfeeding": False,
        "medical_condition": False, "eating_disorder": False}})
    first = client.post("/nutrition/water", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["today_water_glasses"] == 1
    assert client.post("/nutrition/water", headers=headers).json()["today_water_glasses"] == 2
    assert client.delete("/nutrition/water", headers=headers).json()["today_water_glasses"] == 1
    assert client.delete("/nutrition/water", headers=headers).json()["today_water_glasses"] == 0
    assert client.delete("/nutrition/water", headers=headers).status_code == 409
    events = [event for event in recording_analytics.events if event["event"] == "water_log_changed"]
    assert [event["properties"]["water_glasses"] for event in events] == [1, 2, 1, 0]
    assert all(set(event["properties"]) == {"role", "platform", "app_version", "env", "water_glasses"}
               for event in events)


def test_water_log_stops_at_thirty(api):
    client, db = api
    registered = client.post("/auth/register", json={"trainee_id": "water-bound", "password": "correct-horse-1"}).json()
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    _seed_profile(db, "water-bound", age=30, target=None)
    account = db.get_active_account_by_username("water-bound")
    today = _player_today(db, "water-bound")
    with db.open_ledger(account["ledger_id"]) as ledger:
        ledger.conn.execute(
            "INSERT INTO water_log(entry_date, glass_count, updated_at) VALUES(?, 29, 'seed')",
            (today.isoformat(),),
        )
        ledger.conn.commit()
    assert client.post("/nutrition/water", headers=headers).json()["today_water_glasses"] == 30
    assert client.post("/nutrition/water", headers=headers).status_code == 409


def test_water_rolls_over_in_player_timezone_and_is_assignment_gated(api, monkeypatch):
    from datetime import UTC, datetime
    from svc.routers import assignments as assignments_router
    from svc.routers import nutrition as nutrition_router
    from service.weight_history import player_local_date as resolve_player_local_date

    client, db = api
    coach = client.post("/auth/register", json={"trainee_id": "water-rollover-coach", "password": "correct-horse-1"}).json()
    coach_headers = {"Authorization": f"Bearer {coach['access_token']}"}
    from service import coach as coach_service
    coach_invite = coach_service.issue_coach_invite(db, "water-rollover-coach", actor="cli")
    assert client.post("/coach/invite/redeem", headers=coach_headers, json={"token": coach_invite["token"]}).status_code == 200
    assert client.put("/coach/profile", headers=coach_headers, json={
        "display_name": "Coach", "bio": "b", "specialization": "s", "capacity": 5,
    }).status_code == 200
    player = client.post("/auth/register", json={"trainee_id": "water-rollover-player", "password": "correct-horse-1"}).json()
    player_headers = {"Authorization": f"Bearer {player['access_token']}"}
    assignment_token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    assignment = client.post("/assignments/invites/redeem", headers=player_headers,
        json={"token": assignment_token, "consent": True}).json()["assignment"]
    peer = client.post("/auth/register", json={"trainee_id": "water-rollover-peer", "password": "correct-horse-1"}).json()
    peer_headers = {"Authorization": f"Bearer {peer['access_token']}"}
    peer_invite = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    client.post("/assignments/invites/redeem", headers=peer_headers,
        json={"token": peer_invite, "consent": True})
    _seed_profile(db, "water-rollover-player", age=30, target=None)
    _seed_profile(db, "water-rollover-peer", age=30, target=None)
    player_account = db.get_active_account_by_username("water-rollover-player")
    with db.open_ledger(player_account["ledger_id"]) as ledger:
        ledger.append_training_schedule(str(ledger.ledger_id), [1], "Pacific/Kiritimati",
            "2026-10-24", "2026-10-24T00:00:00+00:00")
        assert ledger.conn.execute("SELECT COUNT(*) FROM nutrition_adherence").fetchone()[0] == 0
    now = [datetime(2026, 10, 25, 9, 59, tzinfo=UTC)]
    def local_date(ledger, ledger_id):
        return resolve_player_local_date(ledger, ledger_id, now=now[0])
    monkeypatch.setattr(nutrition_router, "player_local_date", local_date)
    monkeypatch.setattr(assignments_router, "player_local_date", local_date)

    assert client.post("/nutrition/water", headers=player_headers).json()["today_water_glasses"] == 1
    now[0] = datetime(2026, 10, 25, 10, 1, tzinfo=UTC)
    assert client.get("/nutrition", headers=player_headers).json()["today_water_glasses"] == 0
    assert client.post("/nutrition/water", headers=player_headers).json()["today_water_glasses"] == 1
    player_state = client.get("/nutrition", headers=player_headers).json()
    coach_state = client.get(f"/coach/assignments/{assignment['assignment_id']}/nutrition", headers=coach_headers).json()
    counts = {day["date"]: day["glasses"] for day in coach_state["water_days"]}
    assert counts["2026-10-25"] == 1
    assert counts["2026-10-26"] == 1
    assert player_state["today_water_glasses"] == coach_state["today_water_glasses"] == 1
    outsider = client.post("/auth/register", json={"trainee_id": "water-outsider", "password": "correct-horse-1"}).json()
    outsider_headers = {"Authorization": f"Bearer {outsider['access_token']}"}
    outsider_invite = coach_service.issue_coach_invite(db, "water-outsider", actor="cli")
    assert client.post("/coach/invite/redeem", headers=outsider_headers,
        json={"token": outsider_invite["token"]}).status_code == 200
    assert client.get(f"/coach/assignments/{assignment['assignment_id']}/nutrition",
        headers=outsider_headers).status_code == 403

    with db.open_ledger(player_account["ledger_id"]) as ledger:
        assert ledger.conn.execute("SELECT COUNT(*) FROM nutrition_adherence").fetchone()[0] == 0
    alerts_before = db.catalog_conn.execute("SELECT COUNT(*) FROM coach_alerts").fetchone()[0]
    snapshot_before = client.get("/coach/roster/snapshot", headers=coach_headers).json()["snapshot"]
    mapping_before = client.get("/coach/roster/snapshot", headers=coach_headers).json()["client_mapping"]
    order_before = [item["player_display_name"] for item in mapping_before]
    assert len(order_before) == 2
    for _ in range(2):
        client.post("/nutrition/water", headers=player_headers)
    alerts_after = db.catalog_conn.execute("SELECT COUNT(*) FROM coach_alerts").fetchone()[0]
    snapshot_after = client.get("/coach/roster/snapshot", headers=coach_headers).json()["snapshot"]
    mapping_after = client.get("/coach/roster/snapshot", headers=coach_headers).json()["client_mapping"]
    assert alerts_after == alerts_before
    assert [item["player_display_name"] for item in mapping_after] == order_before
    assert [row["urgency_rank"] for row in snapshot_after["players"]] == [
        row["urgency_rank"] for row in snapshot_before["players"]]
    with db.open_ledger(player_account["ledger_id"]) as ledger:
        assert ledger.conn.execute("SELECT COUNT(*) FROM nutrition_adherence").fetchone()[0] == 0
