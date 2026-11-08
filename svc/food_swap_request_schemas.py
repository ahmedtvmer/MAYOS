"""Food swap request commands; account and Assignment identities are server-owned."""

from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


class FoodSwapRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    plan_version_id: int = Field(gt=0)
    day_type: Literal["training_day", "rest_day"]
    slot: str = Field(min_length=1, max_length=80)
    food_index: int = Field(ge=0, le=99)
    food_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(default="", max_length=500)


class FoodSwapRequestDeclineIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    response: str = Field(min_length=1, max_length=500)


class FoodSwapRequestApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    response: str = Field(default="", max_length=500)
    food_id: str = Field(min_length=1, max_length=100)
    grams: float = Field(gt=0, le=10000, allow_inf_nan=False)
