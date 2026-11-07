"""Shared Food library and Personal food text matching."""

from core.arabic import normalize_arabic_text
from database.shared import _normalize_exercise_name


def normalize_food_query(text):
    return normalize_arabic_text(_normalize_exercise_name(text or ""))


def food_match_rank(names, aliases, query):
    if query in names:
        return 0
    if any(name.startswith(query) for name in names):
        return 1
    if any(query in alias for alias in aliases):
        return 2
    if any(query in name for name in names):
        return 3
    return None
