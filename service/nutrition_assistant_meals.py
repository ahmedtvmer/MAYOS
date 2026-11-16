"""Minimal saved-meal facts and bounded pages for Player inference."""

import json


def _food_summary(food):
    summary = {"name": food["name"][:80], "grams": food["grams"]}
    if len(food["name"]) > 80:
        summary["name_truncated"] = True
    if food.get("arabic_name"):
        summary["arabic_name"] = food["arabic_name"][:80]
        if len(food["arabic_name"]) > 80:
            summary["arabic_name_truncated"] = True
    return summary


def meal_context(state):
    return {
        "day_type": state["target_day_type"],
        "meals_enabled": state.get("meals_enabled", False),
        "meals_targets_changed": state.get("meals_targets_changed", False),
        "meals": [{"slot": meal["slot"], "foods": [_food_summary(food) for food in meal["foods"]]}
                  for meal in state.get("meals", [])],
    }


def _group_foods(foods):
    meals = []
    for slot, food in foods:
        if not meals or meals[-1]["slot"] != slot:
            meals.append({"slot": slot, "foods": []})
        meals[-1]["foods"].append(food)
    return meals


def meal_page(projection, offset, max_bytes):
    # Empty / single / many foods and multibyte names must keep valid JSON.
    if "meals" not in projection:
        return projection
    foods = [(meal["slot"], food) for meal in projection["meals"] for food in meal["foods"]]
    summary = {key: value for key, value in projection.items() if key != "meals"}
    summary["food_count"] = len(foods)
    if offset >= len(foods):
        return {**summary, "meals": [], "next_offset": None}
    for end in range(len(foods), offset, -1):
        page = {**summary, "meals": _group_foods(foods[offset:end]),
                "next_offset": end if end < len(foods) else None}
        rendered = json.dumps(page, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(rendered.encode("utf-8")) <= max_bytes:
            return page
    return {"status": "truncated", "message": "The Nutrition details exceeded the tool result limit."}
