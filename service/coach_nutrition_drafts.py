"""Coach-only Nutrition draft lifecycle behind the active Assignment gate."""

import json

from database.ledger import nutrition_drafts as storage
from database.ledger.nutrition import NutritionPlanVersion
from database.ledger.nutrition_meals import generate_variants, resolve_variant, reviewed_staples
from core.meal_setup import MEAL_LAYOUTS
from service import nutrition
from service.assignments import authorized_player_ledger
from service.coach_nutrition_validation import evaluate, food_snapshot
from svc.nutrition_draft_schemas import NutritionDraftIn


class DraftConflict(ValueError):
    pass


class DraftNotFound(ValueError):
    pass


class DraftInvalid(ValueError):
    def __init__(self, evaluation):
        super().__init__("Review the Nutrition draft before publishing.")
        self.evaluation = evaluation


def _active_targets(ledger):
    active = ledger.get_active_nutrition_plan()
    return json.loads(active["targets_json"]) if active else {}


def _target_options(targets):
    if targets.get("training_day") and targets.get("rest_day"):
        return {day: targets[day] for day in ("training_day", "rest_day")}
    return {"daily": targets.get("daily") or targets} if targets else {"daily": {}}


def _blank_variants(ledger, targets):
    slots = MEAL_LAYOUTS[ledger.get_meal_setup()["meal_count"]]
    return {day: [{"slot": slot, "name": "", "note": "", "foods": [],
                   "log_label": "snack" if slot.endswith("_snack") else slot}
                  for slot in slots] for day in targets}


def _log_label(meal):
    if meal.get("log_label"):
        return meal["log_label"]
    if meal["slot"].endswith("_snack"):
        return "snack"
    return meal["slot"] if meal["slot"] in ("breakfast", "lunch", "dinner") else "lunch"


def _copied_variants(payload):
    variants = {}
    for day, variant in payload["variants"].items():
        if variant["status"] != "ready":
            raise ValueError("Generated meals are unavailable. Start from blank instead.")
        variants[day] = [{**meal, "log_label": _log_label(meal)} for meal in variant["meals"]]
    return variants


def _source_payload(ledger, active, source):
    if active is None:
        raise ValueError("The Player has no current Nutrition plan.")
    if source == "generated":
        payload = generate_variants(ledger, _active_targets(ledger), {})
    else:
        payload = json.loads(active["meals_json"]) if active["meals_json"] else None
    if payload and payload.get("enabled"):
        # The Coach editor displays both day types, so both are demanded here.
        payload["variants"] = {day: resolve_variant(ledger, active, payload, day)
                               for day in ("training_day", "rest_day")}
    return payload


def _starting_draft(ledger, source):
    active = ledger.get_active_nutrition_plan()
    targets = _target_options(_active_targets(ledger))
    draft = {"goal": active["goal"] if active else "maintain",
             "daily_activity": active["daily_activity"] if active else "mostly_sitting",
             "targets": targets, "variants": {}}
    if source == "blank":
        draft["variants"] = _blank_variants(ledger, targets)
    else:
        payload = _source_payload(ledger, active, source)
        if payload and payload.get("enabled"):
            # Preserve both variants even when the targets happen to be identical.
            draft["targets"] = {day: targets.get(day) or targets["daily"]
                                for day in ("training_day", "rest_day")}
            draft["variants"] = _copied_variants(payload)
    return NutritionDraftIn.model_validate(draft).model_dump()


def _record(ledger, assignment_id):
    record = storage.read_draft(ledger, assignment_id)
    if record is None:
        raise DraftNotFound("Nutrition draft not found.")
    source = record.pop("source_targets")
    active = ledger.get_active_nutrition_plan()
    payload = json.loads(active["meals_json"]) if active and active["meals_json"] else {}
    return {**record, "evaluation": evaluate(ledger, record["draft"]),
            "targets_changed": source != _active_targets(ledger) or payload.get("targets_changed", False)}


def _require_active(db, coach_id, assignment_id):
    if db.get_active_assignment_for_coach(coach_id, assignment_id) is None:
        raise DraftNotFound("No active assignment.")


def run(db, coach_id, assignment_id, operation):
    authorized = authorized_player_ledger(db, coach_id, assignment_id)
    if authorized is None:
        raise DraftNotFound("No active assignment.")
    ledger, _ = authorized
    with ledger:
        with ledger.ledger_transaction(immediate=True):
            response = operation(ledger)
            # A failed recheck rolls back a create, save or publish racing revocation.
            _require_active(db, coach_id, assignment_id)
            return response


def start(ledger, assignment_id, source):
    if storage.read_draft(ledger, assignment_id):
        raise DraftConflict("A Nutrition draft already exists. Open or discard it first.")
    storage.create_draft(ledger, assignment_id, _starting_draft(ledger, source), _active_targets(ledger))
    return _record(ledger, assignment_id)


def read(ledger, assignment_id):
    return _record(ledger, assignment_id)


def save(ledger, assignment_id, body):
    if not storage.save_draft(ledger, assignment_id, body["draft"], body["revision"]):
        raise DraftConflict("The draft changed. Reopen it before saving.")
    return _record(ledger, assignment_id)


def search(ledger, query):
    restrictions = ledger.get_meal_setup()["restrictions"]
    query = query.casefold().strip()
    foods = reviewed_staples(ledger)
    matches = [food for food in foods if not query or any(query in str(food.get(key) or "").casefold()
               for key in ("name", "arabic_name", "id"))]
    return {"foods": [food_snapshot(food, {"grams": 100}, restrictions) for food in matches[:50]]}


def publish(ledger, assignment_id, body):
    record = _record(ledger, assignment_id)
    if record["revision"] != body["revision"]:
        raise DraftConflict("The draft changed. Review it before publishing.")
    evaluation = record["evaluation"]
    if not evaluation["can_publish"]:
        raise DraftInvalid(evaluation)
    nutrition._require_coach_authority_confirmation(ledger, body, assignment_id)
    draft = record["draft"]
    targets = evaluation["targets"]
    payload = {"enabled": bool(draft["variants"]), "variants": {}, "targets_changed": False}
    for day in ("training_day", "rest_day"):
        if draft["variants"]:
            payload["variants"][day] = evaluation["variants"].get(day) or evaluation["variants"]["daily"]
    version = ledger.save_nutrition_plan(NutritionPlanVersion(
        goal=draft["goal"], reason={"code": "coach"}, intensity=None,
        daily_activity=draft["daily_activity"], targets=targets, author="Coach", provenance="coach",
        authority_assignment_id=assignment_id, meals=payload,
        goal_source_snapshot=nutrition._goal_source(ledger.get_nutrition_profile()),
    ))
    storage.discard_draft(ledger, assignment_id)
    return {"plan_version_id": version, "with_meals": payload["enabled"]}
