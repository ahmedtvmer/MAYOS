"""Player Food swap requests and Assignment-gated Coach decisions (ADR 027)."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from database import food_swap_requests as queue
from database.ledger.nutrition import NutritionPlanVersion
from service.assignments import authorized_player_ledger
from service.coach_nutrition_validation import evaluate


class RequestNotFound(ValueError):
    pass


class RequestConflict(ValueError):
    pass


@dataclass(frozen=True)
class Decision:
    coach_id: str
    assignment_id: str
    request_id: str
    body: dict
    status: str

    @property
    def applies(self):
        return self.status == "applied"


@dataclass(frozen=True)
class Replacement:
    target: dict
    food_id: str
    grams: float


def _now():
    return datetime.now(UTC).isoformat()


def _coach_plan(ledger, assignment_id, target):
    active = ledger.get_active_nutrition_plan()
    if (active is None or active["author"] != "Coach"
            or active["authority_assignment_id"] != assignment_id):
        raise PermissionError("Food swap requests require a Nutrition plan set by your current Coach.")
    if active["id"] != target["plan_version_id"]:
        raise RequestConflict("The Nutrition plan changed. Refresh meals before requesting or applying a swap.")
    payload = json.loads(active["meals_json"]) if active["meals_json"] else {}
    variant = payload.get("variants", {}).get(target["day_type"], {})
    meal = next((meal for meal in variant.get("meals", []) if meal["slot"] == target["slot"]), None)
    index = target["food_index"]
    if (not payload.get("enabled") or variant.get("status") != "ready" or meal is None
            or index >= len(meal["foods"]) or meal["foods"][index]["id"] != target["food_id"]):
        raise RequestConflict("This food or Meal slot changed. Refresh meals before continuing.")
    return active, payload, meal


def _request_target(ledger, assignment, body):
    # An index disambiguates a Meal slot that repeats the same Food library row.
    target = {key: body[key] for key in ("plan_version_id", "day_type", "slot", "food_index", "food_id")}
    _active, _payload, meal = _coach_plan(ledger, assignment["assignment_id"], target)
    food = meal["foods"][target["food_index"]]
    return {**target, "food_name": food["name"], "food_name_ar": food.get("arabic_name"),
            "meal_name": meal.get("name") or meal["slot"]}


def _create_record(db, assignment, target, reason):
    # A retry of an unanswered request must not add another pending queue entry.
    for existing in queue.for_player(db, assignment["player_account_id"]):
        if (existing["assignment_id"] == assignment["assignment_id"]
                and existing["status"] == "pending" and existing["food_swap"] == target):
            return existing, False
    request_id = uuid4().hex
    queue.insert(db, {**assignment, "request_id": request_id, "food_swap": target,
                      "reason": reason.strip(), "created_at": _now()})
    return queue.get(db, assignment["coach_account_id"], assignment["assignment_id"], request_id), True


def create(db, ledger, player_id, body):
    db.ensure_account_schema()
    with ledger.ledger_transaction(immediate=True):
        with db.catalog_transaction(immediate=True):
            assignment = db.get_active_assignment_for_player(player_id)
            if assignment is None:
                raise PermissionError("Food swap requests need an active Assignment.")
            target = _request_target(ledger, assignment, body)
            return _create_record(db, assignment, target, body["reason"])


def _current_draft(active, payload):
    targets = json.loads(active["targets_json"])
    day_targets = {day: targets.get(day) or targets.get("daily") or targets
                   for day in payload["variants"]}
    return {"goal": active["goal"], "daily_activity": active["daily_activity"], "targets": day_targets,
            "variants": {day: variant["meals"] for day, variant in payload["variants"].items()}}


def _replacement_payload(ledger, active, payload, replacement):
    target = replacement.target
    draft = _current_draft(active, payload)
    meals = draft["variants"][target["day_type"]]
    meal = next(meal for meal in meals if meal["slot"] == target["slot"])
    if replacement.food_id == target["food_id"]:
        raise ValueError("Choose a different replacement food.")
    meal["foods"][target["food_index"]] = {"id": replacement.food_id, "grams": replacement.grams}
    validation = evaluate(ledger, draft)
    if not validation["can_publish"]:
        raise ValueError(" ".join(validation["errors"]))
    payload["variants"] = validation["variants"]
    return payload


def _application_reply(db, record, payload, response):
    if response:
        return response
    target = record["food_swap"]
    meals = payload["variants"][target["day_type"]]["meals"]
    meal = next(meal for meal in meals if meal["slot"] == target["slot"])
    food = meal["foods"][target["food_index"]]
    player = db.get_account(record["player_account_id"])
    if player["display_language"] == "ar":
        return f"بدّل مدربك الطعام إلى {food.get('arabic_name') or food['name']} ({food['grams']:g} جم)."
    return f"Your coach replaced the food with {food['name']} ({food['grams']:g} g)."


def _save_plan(ledger, active, payload):
    snapshot = ledger.get_nutrition_goal_offer_snapshot(active["id"])
    ledger.save_nutrition_plan(NutritionPlanVersion(
        goal=active["goal"], reason=json.loads(active["goal_reason_data_json"]),
        intensity=active["intensity"], daily_activity=active["daily_activity"],
        targets=json.loads(active["targets_json"]), author="Coach", provenance=active["provenance"],
        authority_assignment_id=active["authority_assignment_id"], meals=payload,
        goal_source_snapshot=json.loads(snapshot[0]) if snapshot else None,
    ))


def _pending_request(db, coach_id, assignment_id, request_id):
    _require_assignment(db, coach_id, assignment_id)
    record = queue.get(db, coach_id, assignment_id, request_id)
    if record is None:
        raise RequestNotFound("Food swap request not found.")
    if record["status"] != "pending":
        raise RequestConflict("This Food swap request has already been answered or closed.")
    return record


def _require_assignment(db, coach_id, assignment_id):
    if db.get_active_assignment_for_coach(coach_id, assignment_id) is None:
        raise RequestNotFound("No active assignment.")


@contextmanager
def _decision_transaction(db, ledger):
    claimed_ids = []
    try:
        with ledger.ledger_transaction(immediate=True):
            yield claimed_ids
    except sqlite3.Error:
        # Catalog claims commit before the ledger transaction exits. Compensate
        # for an INSERT or COMMIT failure, including an Assignment ended meanwhile.
        for request_id in claimed_ids:
            queue.reopen_failed_apply(db, request_id)
        raise


def _apply(ledger, record, body):
    active, payload, _meal = _coach_plan(ledger, record["assignment_id"], record["food_swap"])
    replacement = Replacement(record["food_swap"], body["food_id"], body["grams"])
    return active, _replacement_payload(ledger, active, payload, replacement)


def _claim_decision(db, command, record, payload):
    response = command.body["response"].strip()
    if command.applies:
        response = _application_reply(db, record, payload, response)
    resolution = {"request_id": command.request_id, "status": command.status,
                  "response": response, "resolved_by": command.coach_id, "resolved_at": _now()}
    if not queue.claim(db, resolution):
        raise RequestConflict("This Food swap request has already been answered or closed.")


def _resolve(db, ledger, command, claimed_ids):
    record = _pending_request(db, command.coach_id, command.assignment_id, command.request_id)
    active, payload = _apply(ledger, record, command.body) if command.applies else (None, None)
    _claim_decision(db, command, record, payload)
    if command.applies:
        claimed_ids.append(command.request_id)
        _save_plan(ledger, active, payload)
    _require_assignment(db, command.coach_id, command.assignment_id)
    return queue.get(db, command.coach_id, command.assignment_id, command.request_id)


def decide(db, command):
    db.ensure_account_schema()
    authorized = authorized_player_ledger(db, command.coach_id, command.assignment_id)
    if authorized is None:
        raise RequestNotFound("No active assignment.")
    ledger, _context = authorized
    with ledger:
        with _decision_transaction(db, ledger) as claimed_ids:
            # The catalog claim serializes decisions with Assignment ending. Keep it
            # pending on validation/write failure, like the Program request queue.
            with db.catalog_transaction(immediate=True):
                return _resolve(db, ledger, command, claimed_ids)
