"""Editable Nutrition draft inputs, separate from published food snapshots."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DraftFoodIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, max_length=100)
    grams: float = Field(ge=0, le=10000, allow_inf_nan=False)


class DraftMealIn(BaseModel):
    slot: str = Field(min_length=1, max_length=80)
    name: str = Field(default="", max_length=100)
    note: str = Field(default="", max_length=2000)
    log_label: Literal["breakfast", "lunch", "dinner", "snack"] = "lunch"
    foods: list[DraftFoodIn] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def unique_foods(self):
        if len({food.id for food in self.foods}) != len(self.foods):
            raise ValueError("Use one portion per food in a Meal slot.")
        return self


class DraftTargetsIn(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", allow_inf_nan=False)
    calories: int | float | None = None
    protein_g: int | float | None = None
    carbs_g: int | float | None = None
    fat_g: int | float | None = None
    fiber_g: int | float | None = None
    water_ml: int | float | None = None


class NutritionDraftIn(BaseModel):
    goal: Literal["lose", "maintain", "gain"] = "maintain"
    daily_activity: Literal["mostly_sitting", "on_feet", "physical_job"] = "mostly_sitting"
    targets: dict[str, DraftTargetsIn] = Field(default_factory=dict)
    variants: dict[str, list[DraftMealIn]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def day_types(self):
        for options in (self.targets, self.variants):
            if set(options) not in (set(), {"daily"}, {"training_day", "rest_day"}):
                raise ValueError("Use daily or both training_day and rest_day.")
        if self.variants and set(self.variants) != set(self.targets):
            raise ValueError("Meals and targets must use the same day types.")
        for meals in self.variants.values():
            if len(meals) > 12 or len({meal.slot for meal in meals}) != len(meals):
                raise ValueError("Use up to 12 Meal slots with unique ids per day type.")
        return self


class NutritionDraftSaveIn(BaseModel):
    draft: NutritionDraftIn
    revision: int = Field(ge=1)


class NutritionDraftStartIn(BaseModel):
    source: Literal["blank", "current", "generated"] = "blank"


class NutritionDraftPublishIn(BaseModel):
    revision: int = Field(ge=1)
    confirm_takeover: bool = False
