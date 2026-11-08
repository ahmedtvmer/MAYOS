"""Resolve explicit Food swaps against the current visible Food library."""

from core.meal_setup import restriction_reasons
from database.food_library.lookup import _food


def library_food(ledger, food_id):
    if not ledger.conn.execute(
        "SELECT 1 FROM catalog.sqlite_master WHERE type='table' AND name='foods'"
    ).fetchone():
        return None
    row = ledger.conn.execute(
        "SELECT * FROM catalog.foods WHERE id=? AND hidden=0", (food_id,),
    ).fetchone()
    return _food(row) if row else None


def swap_allowed(food, restrictions):
    return bool(food and (food["reviewed"] or not food["staple_roles"])
                and not set(restriction_reasons(food, restrictions)) - {"disliked"})
