"""Coach-owned templates copy into private drafts; they never publish a plan."""

from copy import deepcopy

from core.nutrition_template_scaling import rescale_meals
from database.ledger import nutrition_drafts
from database.ledger.nutrition_meals import reviewed_staples
from database.registry import nutrition_templates as storage
from service import coach_nutrition_drafts as drafts
from service.coach_nutrition_validation import food_snapshot
from svc.nutrition_draft_schemas import NutritionDraftIn
from svc.nutrition_template_schemas import NutritionTemplateContent


NO_RESTRICTIONS = {"allergies": [], "vegetarian": False, "dislikes": []}


def read(db, coach_id, template_id):
    template = storage.read(db, coach_id, template_id)
    if template is None:
        raise drafts.DraftNotFound("Nutrition template not found.")
    return template


def editor_template(db, coach_id, template_id):
    template = read(db, coach_id, template_id)
    food_ids = {portion["id"] for meals in template["nutrition"]["variants"].values()
                for meal in meals for portion in meal["foods"]}
    return {**template, "foods": [food_snapshot(food, {"grams": 100}, NO_RESTRICTIONS)
                                  for food in storage.foods(db) if food["id"] in food_ids]}


def food_options(db, query):
    query = query.strip().casefold()
    return {"foods": [food_snapshot(food, {"grams": 100}, NO_RESTRICTIONS)
                      for food in storage.foods(db)
                      if not query or any(query in str(food.get(key) or "").casefold()
                                          for key in ("id", "name", "arabic_name"))][:50]}


def _validated_content(db, content):
    normalized = NutritionTemplateContent.model_validate(content).model_dump()
    catalog = {food["id"]: food for food in storage.foods(db)}
    for meals in normalized["variants"].values():
        for meal in meals:
            for portion in meal["foods"]:
                if portion["id"] not in catalog:
                    raise ValueError("Use reviewed Staple foods only.")
                food_snapshot(catalog[portion["id"]], portion, NO_RESTRICTIONS)
    for target in normalized["targets"].values():
        for key in ("calories", "protein_g", "carbs_g", "fat_g"):
            if target[key] is None or target[key] < 0 or (key == "calories" and target[key] == 0):
                raise ValueError("Set positive calories and nonnegative Macros for each template day type.")
    return normalized


def create(db, coach_id, body):
    return storage.create(db, coach_id, {**body, "nutrition": _validated_content(db, body["nutrition"])})


def update(db, coach_id, template_id, body):
    read(db, coach_id, template_id)
    updated = storage.update(db, coach_id, template_id,
                             {**body, "nutrition": _validated_content(db, body["nutrition"])})
    if updated is None:
        raise drafts.DraftNotFound("Nutrition template not found.")
    return updated


def delete(db, coach_id, template_id):
    if not storage.delete(db, coach_id, template_id):
        raise drafts.DraftNotFound("Nutrition template not found.")


def _reviewed_source(ledger, assignment_id, body):
    if body["source"] == "draft":
        record = nutrition_drafts.read_draft(ledger, assignment_id)
        if record is None:
            raise drafts.DraftNotFound("Nutrition draft not found.")
        if record["revision"] != body["revision"]:
            raise drafts.DraftConflict("The draft changed. Reopen it before saving a template.")
        source = record["draft"]
    else:
        active = ledger.get_active_nutrition_plan()
        if active is None or active["id"] != body["plan_version_id"]:
            raise drafts.DraftConflict("The Nutrition plan changed. Reopen it before saving a template.")
        source = drafts._starting_draft(ledger, "current")
    if not body["include_targets"]:
        source = {**source, "targets": {}}
    return source


def save_from_assignment(db, coach_id, assignment_id, body):
    content = drafts.run(db, coach_id, assignment_id,
                         lambda ledger: _reviewed_source(ledger, assignment_id, body))
    return create(db, coach_id, {"name": body["name"], "description": body["description"],
                                 "nutrition": content})


def current_source(ledger):
    active = ledger.get_active_nutrition_plan()
    if active is None:
        raise drafts.DraftNotFound("The Player has no current Nutrition plan.")
    return {"plan_version_id": active["id"], "nutrition": drafts._starting_draft(ledger, "current")}


def _player_draft(ledger, content, catalog):
    if content["targets"]:
        return deepcopy(content)
    active = ledger.get_active_nutrition_plan()
    targets = drafts._target_options(drafts._active_targets(ledger))
    if active is None or not all(target.get("calories") for target in targets.values()):
        raise ValueError("Set the Player's Nutrition targets before applying a template without targets.")
    variants = content["variants"]
    # A daily template expands to each Player day type. Distinct template meals
    # stay distinct when the Player uses one daily target.
    if "training_day" in variants and "daily" in targets:
        targets = {day: deepcopy(targets["daily"]) for day in ("training_day", "rest_day")}
    meals = {day: rescale_meals(variants.get(day, variants.get("daily", [])), target, catalog)
             for day, target in targets.items()}
    return {"goal": active["goal"], "daily_activity": active["daily_activity"],
            "targets": targets, "variants": meals}


def _apply_to_ledger(ledger, assignment_id, content, body):
    record = nutrition_drafts.read_draft(ledger, assignment_id)
    if record is not None and record["revision"] != body["revision"]:
        raise drafts.DraftConflict("A Nutrition draft already exists or changed. Review it before replacing it.")
    if record is None and body["revision"] is not None:
        raise drafts.DraftConflict("The draft changed. Reopen it before applying the template.")
    catalog = {food["id"]: food for food in reviewed_staples(ledger)}
    if any(portion["id"] not in catalog for meals in content["variants"].values()
           for meal in meals for portion in meal["foods"]):
        raise ValueError("A template food is no longer a reviewed Staple food. Edit the template first.")
    draft = NutritionDraftIn.model_validate(_player_draft(ledger, content, catalog)).model_dump()
    if record is None:
        nutrition_drafts.create_draft(ledger, assignment_id, draft, drafts._active_targets(ledger))
    else:
        nutrition_drafts.save_draft(ledger, assignment_id, draft, record["revision"])
    return drafts.read(ledger, assignment_id)


def apply(db, coach_id, template_id, body):
    template = read(db, coach_id, template_id)
    content = _validated_content(db, template["nutrition"])
    return drafts.run(db, coach_id, body["assignment_id"],
                      lambda ledger: _apply_to_ledger(ledger, body["assignment_id"], content, body))
