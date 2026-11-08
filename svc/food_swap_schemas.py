"""Food swap request boundaries, separate from shared Nutrition schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class FoodSwapTargetIn(BaseModel):
    plan_version_id: int = Field(ge=1)
    day_type: Literal["training_day", "rest_day"]
    slot: Literal["breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner"]
    role: Literal["protein", "carb", "vegetable_fat"]


class FoodSwapIn(FoodSwapTargetIn):
    food_id: str = Field(min_length=1, max_length=100)
