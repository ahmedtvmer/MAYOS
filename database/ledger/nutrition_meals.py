"""Version-pinned meal snapshots and catalog inputs for the pure generator."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from core.food_swap import swap_day
from core.meal_generator import MealGenerationInput
from core.meal_setup import restriction_reasons
from core.meal_execution import generate_meals_bounded
from database.food_library.lookup import _food
from database.ledger.nutrition import NutritionMealGenerationCacheKey
from database.ledger.nutrition_swap_foods import library_food, swap_allowed

MEAL_GENERATION_CACHE_VERSION = 2

if TYPE_CHECKING:
    from database.ledger.handle import TrainingLedger


def reviewed_staples(ledger: TrainingLedger):
    # An unseeded catalog is a supported deployment state, not an error fallback.
    if not ledger.conn.execute(
        "SELECT 1 FROM catalog.sqlite_master WHERE type='table' AND name='foods'"
    ).fetchone():
        return []
    rows = ledger.conn.execute(
        "SELECT * FROM catalog.foods WHERE reviewed=1 AND hidden=0 "
        "AND staple_roles_json<>'[]' ORDER BY staple_order, id"
    ).fetchall()
    return [_food(row) for row in rows]


def _swaps(variant):
    return {meal["slot"]: {food["role"]: food["id"] for food in meal["foods"] if food.get("swapped")}
            for meal in variant.get("meals", [])}


def meals_still_allowed(ledger, meals):
    current = {food["id"]: food for food in reviewed_staples(ledger)}
    restrictions = ledger.get_meal_setup()["restrictions"]
    return all(swap_allowed(library_food(ledger, food["id"]), restrictions) if food.get("swapped")
               else food["id"] in current and not (
                   set(restriction_reasons(current[food["id"]], restrictions)) - {"disliked"})
               for meal in meals for food in meal["foods"])


def _allowed_swaps(ledger, previous, day_type, restrictions):
    variant = previous.get("variants", {}).get(day_type, {})
    saved = (_swaps(variant) if variant.get("meals")
             else previous.get("swaps", {}).get(day_type, {}))
    foods = {food_id: library_food(ledger, food_id)
             for roles in saved.values() for food_id in roles.values()}
    allowed = {food_id: food for food_id, food in foods.items() if swap_allowed(food, restrictions)}
    return {slot: {role: food_id for role, food_id in roles.items() if food_id in allowed}
            for slot, roles in saved.items()}, allowed


def _variant_targets(targets):
    options = targets if any(key in targets for key in ("daily", "training_day", "rest_day")) else {"daily": targets}
    return {day_type: options.get(day_type) or options.get("daily") or options.get("training_day") or options.get("rest_day")
            for day_type in ("training_day", "rest_day")}


def _variant_requests(ledger, targets, previous):
    setup = ledger.get_meal_setup()
    staples = reviewed_staples(ledger)
    selected_targets = _variant_targets(targets)
    requests = {}
    swaps = {}
    for day_type in ("training_day", "rest_day"):
        swaps[day_type], swap_foods = _allowed_swaps(ledger, previous, day_type, setup["restrictions"])
        requests[day_type] = MealGenerationInput(
            targets=selected_targets[day_type], setup=setup, training_day=day_type == "training_day", staples=staples,
            swaps=swaps[day_type], swap_foods=swap_foods,
        )
    return requests, swaps


def _variant_fingerprint(request, replacements):
    content = json.dumps({"version": MEAL_GENERATION_CACHE_VERSION, "request": asdict(request),
                          "replacements": replacements},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _variant_generation_key(ledger, entry_date, day_type, fingerprint):
    return f"{ledger.ledger_id}:{entry_date}:{day_type}:{fingerprint}"


def _food_cache_identity(ledger):
    if not ledger.conn.execute(
        "SELECT 1 FROM catalog.sqlite_master WHERE type='table' AND name='foods'"
    ).fetchone():
        return "unseeded", []
    if ledger.conn.execute(
        "SELECT 1 FROM catalog.sqlite_master WHERE type='table' AND name='food_search_revision'"
    ).fetchone():
        revision = ledger.conn.execute(
            "SELECT counter FROM catalog.food_search_revision WHERE id=1"
        ).fetchone()[0]
        return f"revision:{revision}", None
    staples = reviewed_staples(ledger)
    content = json.dumps(staples, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest(), staples


def _meal_cache_fingerprint(targets, setup, training_day, food_identity):
    content = json.dumps({"version": MEAL_GENERATION_CACHE_VERSION, "targets": targets, "setup": setup,
                          "training_day": training_day, "food_identity": food_identity},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class _VariantCache:
    ledger: TrainingLedger
    plan_version_id: int
    entry_date: str
    setup: dict
    food_identity: str
    staples: list[dict] | None

    def get_or_generate(self, day_type, targets):
        fingerprint = _meal_cache_fingerprint(
            targets, self.setup, day_type == "training_day", self.food_identity,
        )
        cache_key = NutritionMealGenerationCacheKey(
            self.entry_date, self.plan_version_id, fingerprint, day_type,
        )
        variant = self.ledger.get_nutrition_meal_generation_cache(cache_key)
        if variant is not None:
            return variant
        if self.staples is None:
            self.staples = reviewed_staples(self.ledger)
        request = MealGenerationInput(
            targets=targets, setup=self.setup, training_day=day_type == "training_day", staples=self.staples,
        )
        generation_key = _variant_generation_key(self.ledger, self.entry_date, day_type, fingerprint)
        variant = generate_meals_bounded(request, generation_key)
        self.ledger.save_nutrition_meal_generation_cache(cache_key, variant)
        return variant


def generate_variants(ledger, targets, previous):
    """Pin inputs now; solve each day type only when a reader requests it."""
    requests, swaps = _variant_requests(ledger, targets, previous)
    return {"enabled": True, "variants": {}, "swaps": swaps, "targets_changed": False,
            "generation_requests": {day_type: asdict(request) for day_type, request in requests.items()}}


def resolve_variant(ledger, plan, payload, day_type):
    saved = payload.get("variants", {}).get(day_type)
    if saved is not None:
        return saved
    frozen = payload.get("generation_requests", {}).get(day_type)
    if not payload.get("enabled") or frozen is None:
        return {"status": "unavailable", "reason": "staples", "meals": []}
    request = MealGenerationInput(**frozen)
    replacements = payload.get("deferred_swaps", {}).get(day_type, [])
    fingerprint = _variant_fingerprint(request, replacements)
    # Pinned inputs belong to the immutable version, not the date of a later read.
    cache_key = NutritionMealGenerationCacheKey(plan["created_at"][:10], plan["id"], fingerprint, day_type)
    return _resolved_generation(ledger, cache_key, request, replacements)


def _resolved_generation(ledger, cache_key, request, replacements):
    variant = ledger.get_nutrition_meal_generation_cache(cache_key)
    if variant is None:
        key = _variant_generation_key(ledger, cache_key.entry_date, cache_key.variant, cache_key.fingerprint)
        variant = generate_meals_bounded(request, key)
        variant = swap_day(variant, replacements)
        if not ledger.conn.execute("PRAGMA query_only").fetchone()[0]:
            ledger.save_nutrition_meal_generation_cache(cache_key, variant)
    return variant


def cached_variants_for_plan(ledger, plan, entry_date, day_type):
    targets = _variant_targets(json.loads(plan["targets_json"]))
    setup = ledger.get_meal_setup()
    food_identity, staples = _food_cache_identity(ledger)
    cache = _VariantCache(ledger, plan["id"], str(entry_date), setup, food_identity, staples)
    variants = {day_type: cache.get_or_generate(day_type, targets[day_type])}
    return {"enabled": True, "variants": variants, "swaps": {}, "targets_changed": False}


def meals_for_version(ledger, plan):
    if plan.meals is not None:
        return plan.meals
    active = ledger.get_active_nutrition_plan()
    previous = json.loads(active["meals_json"]) if active is not None and active["meals_json"] else None
    if not previous or not previous.get("enabled"):
        return None
    if active["author"] == "Coach":
        return {**previous, "targets_changed": previous.get("targets_changed", False)
                or json.loads(active["targets_json"]) != plan.targets}
    return generate_variants(ledger, plan.targets, previous)
