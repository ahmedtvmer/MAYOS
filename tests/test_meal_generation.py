"""Concurrency behavior for the bounded Nutrition generator."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from core.meal_generator import MealGenerationInput
from core import meal_execution


def _request():
    return MealGenerationInput(
        targets={"calories": 1800, "protein_g": 100, "carbs_g": 200, "fat_g": 50},
        setup={"meal_count": 3, "training_time": "evening",
               "restrictions": {"allergies": [], "dislikes": [], "vegetarian": False}},
        training_day=False,
        staples=[
            {"id": "protein", "name": "Chicken", "reviewed": True, "hidden": False,
             "vegetarian": False, "allergens": [], "allergens_reviewed": True,
             "staple_roles": ["protein"],
             "nutrients": {"energy_kcal": 165, "protein_g": 31, "carbohydrate_g": 0, "fat_g": 3.6}},
            {"id": "carb", "name": "Rice", "reviewed": True, "hidden": False,
             "vegetarian": True, "allergens": [], "allergens_reviewed": True,
             "staple_roles": ["carb"],
             "nutrients": {"energy_kcal": 130, "protein_g": 2.7, "carbohydrate_g": 28, "fat_g": 0.3}},
            {"id": "vegetable-fat", "name": "Olive oil", "reviewed": True, "hidden": False,
             "vegetarian": True, "allergens": [], "allergens_reviewed": True,
             "staple_roles": ["vegetable_fat"],
             "portion_label": "local portion", "portion_grams": 1,
             "nutrients": {"energy_kcal": 900, "protein_g": 0, "carbohydrate_g": 0, "fat_g": 100}},
        ],
    )


class _CountingExecutor:
    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=2)
        self.submissions = 0

    def submit(self, function, *args):
        self.submissions += 1
        return self._pool.submit(function, *args)

    def shutdown(self):
        self._pool.shutdown()


def test_concurrent_meal_requests_share_one_generation(monkeypatch):
    request = _request()
    barrier = Barrier(2)
    key = f"single-flight:{id(barrier)}"
    executor = _CountingExecutor()
    monkeypatch.setattr(meal_execution, "_generation_pool", executor)

    def generate_together():
        barrier.wait(timeout=5)
        return meal_execution.generate_meals_bounded(request, key)

    try:
        with ThreadPoolExecutor(max_workers=2) as callers:
            meal_plans = [future.result() for future in (
                callers.submit(generate_together), callers.submit(generate_together),
            )]
        assert meal_plans[0] == meal_plans[1]
        assert executor.submissions == 1
    finally:
        executor.shutdown()
