"""Nutrition template HTTP contracts against real catalog and Player ledgers."""

from copy import deepcopy
import json

import pytest

from core.meal_generator import TARGET_KEYS
from database.ledger.nutrition import NutritionPlanVersion
from tests.test_nutrition_api import api  # noqa: F401
from tests.test_meals_api import meals_api, _enable, _ledger_id  # noqa: F401
from tests.test_coach_nutrition_drafts import coach_draft_api, _start, _save, _publish  # noqa: F401
from tests.test_program_templates import _make_coach

LIBRARY = "/coach/nutrition-templates"


def _save_template(context, record, include_targets=False):
    client, _db, headers, _player, path = context
    response = client.post(path.removesuffix("/draft") + "/save-template", headers=headers, json={
        "name": "Reusable meals", "description": "Coach instructions", "source": "draft",
        "revision": record["revision"], "include_targets": include_targets,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _apply(context, template, revision=None):
    client, _db, headers, _player, path = context
    body = {"assignment_id": path.split("/")[3]}
    if revision is not None:
        body["revision"] = revision
    return client.post(f"{LIBRARY}/{template['template_id']}/apply", headers=headers, json=body)


def test_catalog_crud_is_owner_scoped_and_never_opens_a_player_ledger(coach_draft_api, monkeypatch):
    client, db, headers, player, path = coach_draft_api
    record = _start(coach_draft_api)
    template = _save_template(coach_draft_api, record)
    other = _make_coach(client, db, "other-template-coach")
    nutrition = template["nutrition"]
    body = {"name": "Renamed", "description": "Edited", "nutrition": nutrition}
    assert nutrition["targets"] == {}
    with db._catalog_lock:
        columns = {row[1] for row in db.catalog_conn.execute("PRAGMA table_info(nutrition_templates)")}
        saved_json = db.catalog_conn.execute("SELECT nutrition_json FROM nutrition_templates").fetchone()[0]
    assert not {"player_account_id", "assignment_id", "plan_version_id"} & columns
    assert not any(key in saved_json for key in ("restriction_reasons", "source_targets", "nutrients_per_100g"))

    original_open = db.open_ledger

    def forbidden_ledger(ledger_id, *args, **kwargs):
        assert ledger_id != _ledger_id(db), "Template catalog CRUD must not open the assigned Player ledger"
        return original_open(ledger_id, *args, **kwargs)

    monkeypatch.setattr(db, "open_ledger", forbidden_ledger)
    assert client.get(LIBRARY, headers=player).status_code == 403
    assert client.get(LIBRARY, headers=other).json()["templates"] == []
    for template_id in (template["template_id"], "missing"):
        foreign_path = f"{LIBRARY}/{template_id}"
        assert client.get(foreign_path, headers=other).status_code == 404
        assert client.put(foreign_path, headers=other, json=body).status_code == 404
        assert client.delete(foreign_path, headers=other).status_code == 404
        assert client.post(f"{foreign_path}/apply", headers=other,
                           json={"assignment_id": path.split("/")[3]}).status_code == 404
    listed = client.get(LIBRARY, headers=headers).json()["templates"]
    assert [entry["template_id"] for entry in listed] == [template["template_id"]]
    owned_path = f"{LIBRARY}/{template['template_id']}"
    assert client.get(owned_path, headers=headers).json()["nutrition"] == nutrition
    assert client.put(owned_path, headers=headers, json=body).json()["name"] == "Renamed"
    copied = client.post(LIBRARY, headers=headers, json=body)
    assert copied.status_code == 201 and copied.json()["template_id"] != template["template_id"]
    assert client.delete(owned_path, headers=headers).status_code == 204
    assert client.get(owned_path, headers=headers).status_code == 404


@pytest.mark.parametrize("source", ["draft", "current"])
def test_save_copies_reviewed_source_and_refuses_stale_versions(coach_draft_api, source):
    client, _db, headers, player, path = coach_draft_api
    record = _start(coach_draft_api)
    record["draft"]["variants"]["training_day"][0].update(name="Before training", note="Take your time")
    record = _save(coach_draft_api, record)
    if source == "current":
        assert _publish(coach_draft_api, record).status_code == 200
        preview = client.get(path.removesuffix("/draft") + "/template-source", headers=headers)
        assert preview.status_code == 200
        pin = {"plan_version_id": preview.json()["plan_version_id"]}
    else:
        pin = {"revision": record["revision"]}
    body = {"name": "Saved source", "source": source, "include_targets": True, **pin}
    before = client.get("/nutrition", headers=player).json()
    save_path = path.removesuffix("/draft") + "/save-template"
    saved = client.post(save_path, headers=headers, json=body)
    assert saved.status_code == 201, saved.text
    content = saved.json()["nutrition"]
    assert content["targets"]
    meal = content["variants"]["training_day"][0]
    assert (meal["name"], meal["note"]) == ("Before training", "Take your time")
    assert set(meal["foods"][0]) == {"id", "grams"}
    assert client.get("/nutrition", headers=player).json() == before
    body.update({key: number + 1 for key, number in pin.items()})
    assert client.post(save_path, headers=headers, json=body).status_code == 409
    assert len(client.get(LIBRARY, headers=headers).json()["templates"]) == 1


@pytest.mark.parametrize("include_targets", [False, True])
def test_applying_rescales_only_when_template_has_no_targets(coach_draft_api, include_targets):
    client, _db, headers, player, path = coach_draft_api
    record = _start(coach_draft_api)
    for meals in record["draft"]["variants"].values():
        for meal in meals:
            meal["note"] = "Reusable note"
            for food in meal["foods"]:
                food["grams"] *= .4
    record = _save(coach_draft_api, record)
    template = _save_template(coach_draft_api, record, include_targets)
    before = client.get("/nutrition", headers=player).json()
    assert _apply(coach_draft_api, template).status_code == 409
    applied = _apply(coach_draft_api, template, record["revision"])
    assert applied.status_code == 200, applied.text
    draft = applied.json()["draft"]
    assert draft["variants"]["training_day"][0]["note"] == "Reusable note"
    if include_targets:
        assert draft == template["nutrition"]
    else:
        assert draft["variants"] != template["nutrition"]["variants"]
        for variant in applied.json()["evaluation"]["variants"].values():
            for key in TARGET_KEYS:
                assert variant["totals"][key] == pytest.approx(variant["targets"][key], rel=.05)
    assert client.get("/nutrition", headers=player).json() == before
    assert _apply(coach_draft_api, template, record["revision"]).status_code == 409
    assert client.get(path, headers=headers).json()["draft"] == draft


@pytest.mark.parametrize("template_days", ["daily", "separate"])
def test_daily_template_expands_to_independent_player_day_variants(coach_draft_api, template_days):
    client, db, headers, player, path = coach_draft_api
    record = _start(coach_draft_api)
    template = _save_template(coach_draft_api, record)
    content = template["nutrition"]
    if template_days == "daily":
        content["variants"] = {"daily": content["variants"]["rest_day"]}
        updated = client.put(f"{LIBRARY}/{template['template_id']}", headers=headers,
                             json={"name": template["name"], "nutrition": content})
        assert updated.status_code == 200, updated.text
    target = record["draft"]["targets"]["rest_day"]
    with db.open_ledger(_ledger_id(db)) as ledger:
        ledger.save_nutrition_plan(NutritionPlanVersion(
            goal="maintain", reason={"code": "test"}, intensity=None, daily_activity="mostly_sitting",
            targets={"training_day": target, "rest_day": {key: amount * .9 if isinstance(amount, (int, float))
                                                           else amount for key, amount in target.items()}},
        ))
    before = client.get("/nutrition", headers=player).json()
    applied = _apply(coach_draft_api, template, record["revision"])
    assert applied.status_code == 200, applied.text
    response = applied.json()
    assert set(response["draft"]["targets"]) == {"training_day", "rest_day"}
    assert response["draft"]["variants"]["training_day"] != response["draft"]["variants"]["rest_day"]
    for variant in response["evaluation"]["variants"].values():
        assert variant["totals"]["calories"] == pytest.approx(variant["targets"]["calories"], rel=.05)
    assert client.get("/nutrition", headers=player).json() == before


@pytest.mark.parametrize("delete_at", ["draft", "published"])
def test_edit_delete_and_source_discard_never_change_copied_drafts_or_plans(coach_draft_api, delete_at):
    client, db, headers, player, path = coach_draft_api
    record = _start(coach_draft_api)
    template = _save_template(coach_draft_api, record, True)
    assert client.delete(path, headers=headers).status_code == 204
    applied = _apply(coach_draft_api, template)
    assert applied.status_code == 200
    snapshot = client.get(path, headers=headers).json()
    before = client.get("/nutrition", headers=player).json()
    content = deepcopy(template["nutrition"])
    content["variants"]["training_day"][0]["note"] = "Changed template only"
    template_path = f"{LIBRARY}/{template['template_id']}"
    assert client.put(template_path, headers=headers,
                      json={"name": "Edited", "nutrition": content}).status_code == 200
    assert client.get(path, headers=headers).json() == snapshot
    assert client.get("/nutrition", headers=player).json() == before
    if delete_at == "draft":
        assert client.delete(template_path, headers=headers).status_code == 204
        assert client.get(path, headers=headers).json() == snapshot
    assert _publish(coach_draft_api, applied.json()).status_code == 200
    published = client.get("/nutrition", headers=player).json()
    assert published != before
    if delete_at == "published":
        assert client.delete(template_path, headers=headers).status_code == 204
    assert client.get("/nutrition", headers=player).json() == published
    with db.open_ledger(_ledger_id(db)) as ledger:
        assert "Changed template only" not in ledger.get_active_nutrition_plan()["meals_json"]


def test_revoked_assignment_and_restricted_food_cannot_bypass_publication_checks(coach_draft_api):
    client, db, headers, player, path = coach_draft_api
    record = _start(coach_draft_api)
    template = _save_template(coach_draft_api, record, True)
    with db.catalog_locked() as connection:
        connection.execute("UPDATE foods SET allergens_json='[\"milk\"]', allergens_reviewed=1 WHERE id='protein'")
        connection.commit()
    with db.open_ledger(_ledger_id(db)) as ledger:
        setup = ledger.get_meal_setup()
        setup["restrictions"]["allergies"] = ["milk"]
        ledger.save_meal_setup(setup)
    applied = _apply(coach_draft_api, template, record["revision"])
    assert applied.status_code == 200
    assert not applied.json()["evaluation"]["can_publish"]
    assert _publish(coach_draft_api, applied.json()).status_code == 400
    assert client.post("/assignments/me/end", headers=player).status_code == 200
    assert _apply(coach_draft_api, template).status_code == 404
    assert client.get(f"{LIBRARY}/{template['template_id']}", headers=headers).status_code == 200


def test_template_analytics_use_allowlisted_properties_and_coach_opt_out(coach_draft_api, recording_analytics):
    from service.analytics import override_analytics_preference_reader

    client, db, headers, _player, _path = coach_draft_api
    override_analytics_preference_reader(db.analytics_preference_allows)
    record = _start(coach_draft_api)
    template = _save_template(coach_draft_api, record)
    assert _apply(coach_draft_api, template, record["revision"]).status_code == 200
    events = [event for event in recording_analytics.events if event["event"].startswith("nutrition_template_")]
    assert [event["event"] for event in events] == ["nutrition_template_saved", "nutrition_template_applied"]
    for event in events:
        assert set(event["properties"]) <= {"role", "platform", "app_version", "env"}
    # No targets, names, notes or other-account identity is copied to properties.
    assert "Reusable meals" not in json.dumps(events)
    assert client.put("/auth/analytics-preference", headers=headers,
                      json={"analytics_allowed": False}).status_code == 200
    latest = client.get(coach_draft_api[-1], headers=headers).json()
    _save_template(coach_draft_api, latest)
    assert _apply(coach_draft_api, template, latest["revision"]).status_code == 200
    assert [event for event in recording_analytics.events
            if event["event"].startswith("nutrition_template_")] == events


def test_revocation_during_apply_rolls_back_draft_replacement(coach_draft_api, monkeypatch):
    client, db, headers, _player, path = coach_draft_api
    record = _start(coach_draft_api)
    template = _save_template(coach_draft_api, record)
    original_gate = db.get_active_assignment_for_coach
    calls = 0

    def revoking_gate(coach_id, assignment_id):
        nonlocal calls
        calls += 1
        return original_gate(coach_id, assignment_id) if calls == 1 else None

    monkeypatch.setattr(db, "get_active_assignment_for_coach", revoking_gate)
    assert _apply(coach_draft_api, template, record["revision"]).status_code == 404
    monkeypatch.setattr(db, "get_active_assignment_for_coach", original_gate)
    assert client.get(path, headers=headers).json() == record
