"""Nutrition draft lifecycle and safety checks through real HTTP and ledgers."""

from copy import deepcopy
import json

import pytest

from database.migration_manager import apply_lazy_migrations, set_ledger_schema_version
from service import coach as coach_service
from tests.test_nutrition_api import api  # noqa: F401
from tests.test_meals_api import meals_api, _enable, _ledger_id  # noqa: F401


@pytest.fixture
def coach_draft_api(meals_api):
    client, db, player_headers, _today = meals_api
    registered = client.post("/auth/register", json={
        "trainee_id": "nutrition-coach", "password": "correct-horse-1"}).json()
    coach_headers = {"Authorization": f"Bearer {registered['access_token']}"}
    invitation = coach_service.issue_coach_invite(db, "nutrition-coach", actor="cli")
    assert client.post("/coach/invite/redeem", headers=coach_headers,
                       json={"token": invitation["token"]}).status_code == 200
    client.put("/coach/profile", headers=coach_headers,
               json={"display_name": "Coach", "bio": "", "specialization": "", "capacity": 5})
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    assignment = client.post("/assignments/invites/redeem", headers=player_headers,
                             json={"token": token, "consent": True}).json()["assignment"]
    path = f"/coach/assignments/{assignment['assignment_id']}/nutrition/draft"
    return client, db, coach_headers, player_headers, path


def _start(context, source="generated"):
    client, _db, coach_headers, _player_headers, path = context
    response = client.post(path, headers=coach_headers, json={"source": source})
    assert response.status_code == 201, response.text
    return response.json()


def _save(context, record):
    client, _db, coach_headers, _player_headers, path = context
    response = client.put(path, headers=coach_headers,
                          json={"draft": record["draft"], "revision": record["revision"]})
    assert response.status_code == 200, response.text
    return response.json()


def _publish(context, record):
    client, _db, coach_headers, _player_headers, path = context
    return client.post(f"{path}/publish", headers=coach_headers,
                       json={"revision": record["revision"], "confirm_takeover": True})


def test_draft_autosaves_without_changing_player_plan_and_rejects_stale_saves(coach_draft_api):
    client, db, headers, player, path = coach_draft_api
    record = _start(coach_draft_api, "blank")
    assert client.post(path, headers=headers, json={"source": "current"}).status_code == 409
    before = client.get("/nutrition", headers=player).json()
    record["draft"]["variants"]["daily"][0]["note"] = "Private coach note"
    saved = _save(coach_draft_api, record)
    assert saved["revision"] == record["revision"] + 1
    assert client.get(path, headers=headers).json()["draft"] == saved["draft"]
    assert client.get("/nutrition", headers=player).json() == before
    assert client.put(path, headers=headers,
                      json={"draft": record["draft"], "revision": record["revision"]}).status_code == 409
    assert client.get(path, headers=player).status_code == 403
    with db.open_ledger(_ledger_id(db)) as ledger:
        assert ledger.get_active_nutrition_plan()["id"] == 1


def test_draft_is_private_and_discarded_when_assignment_ends(coach_draft_api):
    client, db, headers, player, path = coach_draft_api
    _start(coach_draft_api)
    stranger = client.post("/auth/register", json={"trainee_id": "other-nutrition-coach", "password": "correct-horse-1"}).json()
    other_headers = {"Authorization": f"Bearer {stranger['access_token']}"}
    token = coach_service.issue_coach_invite(db, "other-nutrition-coach", actor="cli")["token"]
    client.post("/coach/invite/redeem", headers=other_headers, json={"token": token})
    assert client.get(path, headers=other_headers).status_code == 404
    ended = client.post("/assignments/me/end", headers=player)
    assert ended.status_code == 200, ended.text
    assert client.get(path, headers=headers).status_code == 404
    with db.open_ledger(_ledger_id(db)) as ledger:
        assert ledger.conn.execute("SELECT COUNT(*) FROM nutrition_plan_drafts").fetchone()[0] == 0


@pytest.mark.parametrize("source", ["blank", "current", "generated"])
def test_start_sources_copy_only_the_requested_content(coach_draft_api, source):
    client, _db, _headers, player, _path = coach_draft_api
    current = _enable(client, player)
    record = _start(coach_draft_api, source)
    variants = record["draft"]["variants"]
    if source == "blank":
        assert all(not meal["foods"] for meal in variants["daily"])
        assert not record["evaluation"]["can_publish"]
    else:
        copied = variants[current["day_type"]]
        assert [meal["slot"] for meal in copied] == [meal["slot"] for meal in current["meals"]]
        assert copied[0]["foods"][0]["grams"] == current["meals"][0]["foods"][0]["grams"]


def test_publish_versions_plan_moves_only_nutrition_authority_and_exposes_meal_notes(coach_draft_api, recording_analytics):
    client, db, headers, player, path = coach_draft_api
    record = _start(coach_draft_api)
    for meals in record["draft"]["variants"].values():
        meals[0]["slot"] = "coach_custom_slot"
        meals[0]["name"] = "Coach breakfast"
        meals[0]["note"] = "Eat before training"
    record = _save(coach_draft_api, record)
    assert record["evaluation"]["can_publish"], record["evaluation"]
    published = _publish(coach_draft_api, record)
    assert published.status_code == 200, published.text
    assert client.get(path, headers=headers).status_code == 404
    state = client.get("/nutrition", headers=player).json()
    assert state["authority"] == "coach" and state["author"] == "Coach"
    meals = client.get("/nutrition/meals", headers=player).json()
    assert meals["status"] == "ready" and meals["author"] == "Coach"
    assert meals["meals"][0]["name"] == "Coach breakfast"
    assert meals["meals"][0]["note"] == "Eat before training"
    logged = client.post("/nutrition/meals/log", headers=player, json={
        "slot": "coach_custom_slot", "plan_version_id": meals["plan_version_id"], "entry_date": meals["date"]})
    assert logged.status_code == 201, logged.text
    with db.open_ledger(_ledger_id(db)) as ledger:
        assert ledger.get_active_nutrition_plan()["provenance"] == "coach"
    events = [event for event in recording_analytics.events if event["event"] == "coach_nutrition_plan_published"]
    assert len(events) == 1 and events[0]["properties"]["with_meals"] is True
    assert client.post("/assignments/me/end", headers=player).status_code == 200
    assert client.get("/nutrition", headers=player).json()["authority"] == "player"


@pytest.mark.parametrize(("scale", "warning", "blocked"), [(1.10, True, False), (1.25, True, True), (.60, True, True)])
def test_totals_warn_at_five_percent_and_block_at_fifteen_or_floor(coach_draft_api, scale, warning, blocked):
    record = _start(coach_draft_api)
    for meal in record["draft"]["variants"]["rest_day"]:
        for food in meal["foods"]:
            food["grams"] *= scale
    record = _save(coach_draft_api, record)
    assert bool(record["evaluation"]["warnings"]) == warning
    assert record["evaluation"]["can_publish"] != blocked
    published = _publish(coach_draft_api, record)
    assert published.status_code == (400 if blocked else 200), published.text


@pytest.mark.parametrize("restriction", ["allergy", "vegetarian", "dislike", "unreviewed_allergens"])
def test_live_restrictions_warn_and_strict_restrictions_block_publish(coach_draft_api, restriction):
    client, db, headers, _player, path = coach_draft_api
    record = _start(coach_draft_api)
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET allergens_reviewed=1")
        if restriction == "allergy":
            connection.execute("UPDATE foods SET allergens_json='[\"milk\"]' WHERE id='protein'")
        if restriction == "vegetarian":
            connection.execute("UPDATE foods SET vegetarian=0 WHERE id='protein'")
        if restriction == "unreviewed_allergens":
            connection.execute("UPDATE foods SET allergens_reviewed=0 WHERE id='protein'")
        connection.commit()
    with db.open_ledger(_ledger_id(db)) as ledger:
        setup = ledger.get_meal_setup()
        setup["restrictions"] = {"allergies": ["milk"] if restriction in ("allergy", "unreviewed_allergens") else [],
                                 "vegetarian": restriction == "vegetarian",
                                 "dislikes": ["protein"] if restriction == "dislike" else []}
        ledger.save_meal_setup(setup)
        ledger.conn.commit()
    foods = client.get(f"{path}/foods", headers=headers, params={"q": "Areesh"}).json()["foods"]
    assert foods and foods[0]["restriction_reasons"]
    published = _publish(coach_draft_api, record)
    assert published.status_code == (200 if restriction == "dislike" else 400), published.text


@pytest.mark.parametrize("change", ["floor", "rate", "macros", "minor_lose", "screening", "review_revoked"])
def test_publish_rechecks_spec_a_and_catalog_safety(coach_draft_api, change):
    client, db, _headers, _player, _path = coach_draft_api
    record = _start(coach_draft_api)
    if change in ("floor", "rate", "macros"):
        target = record["draft"]["targets"]["rest_day"]
        if change == "macros":
            target["protein_g"] = 0
        else:
            target["calories"] = 1000 if change == "floor" else 9000
            target.update(protein_g=100, fat_g=40, carbs_g=(target["calories"] - 760) // 4)
        record = _save(coach_draft_api, record)
    elif change == "review_revoked":
        with db.catalog_locked() as connection:
            connection.execute("UPDATE foods SET reviewed=0 WHERE id='protein'")
            connection.commit()
    else:
        with db.open_ledger(_ledger_id(db)) as ledger:
            if change == "minor_lose":
                ledger.conn.execute("UPDATE user_profile SET age=17 WHERE id=1")
            else:
                ledger.conn.execute("UPDATE nutrition_screening SET answers_json=? WHERE id=1",
                                    (json.dumps({"medical_condition": True}),))
            ledger.conn.commit()
        if change == "minor_lose":
            record["draft"]["goal"] = "lose"
            record = _save(coach_draft_api, record)
    assert _publish(coach_draft_api, record).status_code == 400
    with db.open_ledger(_ledger_id(db)) as ledger:
        assert ledger.get_active_nutrition_plan()["id"] == 1


def test_targets_only_publish_removes_existing_meals_and_requires_takeover_confirmation(coach_draft_api):
    client, _db, headers, player, path = coach_draft_api
    _enable(client, player)
    record = _start(coach_draft_api, "current")
    record["draft"]["variants"] = {}
    record = _save(coach_draft_api, record)
    unconfirmed = client.post(f"{path}/publish", headers=headers, json={"revision": record["revision"]})
    assert unconfirmed.status_code == 400
    assert _publish(coach_draft_api, record).status_code == 200
    state = client.get("/nutrition", headers=player).json()
    assert state["authority"] == "coach" and not state["meals_enabled"]
    assert client.get("/nutrition/meals", headers=player).json()["meals"] == []


def test_stale_publish_does_not_discard_or_publish_newer_edits(coach_draft_api):
    record = _start(coach_draft_api)
    stale = deepcopy(record)
    record["draft"]["variants"]["rest_day"][0]["note"] = "Updated"
    saved = _save(coach_draft_api, record)
    assert _publish(coach_draft_api, stale).status_code == 409
    client, db, headers, _player, path = coach_draft_api
    assert client.get(path, headers=headers).json()["revision"] == saved["revision"]
    with db.open_ledger(_ledger_id(db)) as ledger:
        assert ledger.get_active_nutrition_plan()["id"] == 1


def test_revocation_during_publication_rolls_back_plan_and_draft_deletion(coach_draft_api, monkeypatch):
    client, db, headers, _player, path = coach_draft_api
    record = _start(coach_draft_api)
    original_gate = db.get_active_assignment_for_coach
    calls = 0

    def revoking_gate(coach_id, assignment_id):
        nonlocal calls
        calls += 1
        return original_gate(coach_id, assignment_id) if calls == 1 else None

    monkeypatch.setattr(db, "get_active_assignment_for_coach", revoking_gate)
    assert _publish(coach_draft_api, record).status_code == 404
    monkeypatch.setattr(db, "get_active_assignment_for_coach", original_gate)
    assert client.get(path, headers=headers).json()["revision"] == record["revision"]
    with db.open_ledger(_ledger_id(db)) as ledger:
        assert ledger.get_active_nutrition_plan()["id"] == 1


def test_v59_ledger_migrates_to_draft_storage_without_changing_plans(coach_draft_api, tmp_path):
    _client, db, _headers, _player, _path = coach_draft_api
    with db.open_ledger(_ledger_id(db)) as ledger:
        before = dict(ledger.get_active_nutrition_plan())
        ledger.conn.execute("DROP TABLE nutrition_plan_drafts")
        set_ledger_schema_version(ledger.conn, 59)
        ledger.conn.commit()
        apply_lazy_migrations(ledger.conn, "meal-player", tmp_path, tmp_path)
        assert ledger.conn.execute("SELECT COUNT(*) FROM nutrition_plan_drafts").fetchone()[0] == 0
        assert dict(ledger.get_active_nutrition_plan()) == before
