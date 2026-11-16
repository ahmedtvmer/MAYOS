"""Player-free Nutrition template inputs; publication still validates per Player."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from svc.nutrition_draft_schemas import DraftMealIn, DraftTargetsIn


class NutritionTemplateContent(BaseModel):
    goal: Literal["lose", "maintain", "gain"] = "maintain"
    daily_activity: Literal["mostly_sitting", "on_feet", "physical_job"] = "mostly_sitting"
    targets: dict[str, DraftTargetsIn] = Field(default_factory=dict)
    variants: dict[str, list[DraftMealIn]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def day_types(self):
        for options in (self.targets, self.variants):
            if set(options) not in (set(), {"daily"}, {"training_day", "rest_day"}):
                raise ValueError("Use daily or both training_day and rest_day.")
        if self.targets and self.variants and set(self.targets) != set(self.variants):
            raise ValueError("Meals and targets must use the same day types.")
        if not self.targets and not self.variants:
            raise ValueError("Add Meal slots or Nutrition targets.")
        for meals in self.variants.values():
            if not meals or len(meals) > 12 or len({meal.slot for meal in meals}) != len(meals):
                raise ValueError("Use 1 to 12 Meal slots with unique ids per day type.")
            if any(not meal.foods or any(food.grams <= 0 for food in meal.foods) for meal in meals):
                raise ValueError("Add foods with positive grams to each Meal slot.")
        return self


class NutritionTemplateMetadata(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, name):
        if not name.strip():
            raise ValueError("Name cannot be blank.")
        return name.strip()


class NutritionTemplateIn(NutritionTemplateMetadata):
    nutrition: NutritionTemplateContent


class NutritionTemplateSaveFromIn(NutritionTemplateMetadata):
    source: Literal["draft", "current"]
    revision: int | None = Field(default=None, ge=1)
    plan_version_id: int | None = Field(default=None, ge=1)
    include_targets: bool = False

    @model_validator(mode="after")
    def pinned_source(self):
        if self.source == "draft" and self.revision is None:
            raise ValueError("Provide the reviewed draft revision.")
        if self.source == "current" and self.plan_version_id is None:
            raise ValueError("Provide the reviewed Nutrition plan version.")
        return self


class NutritionTemplateApplyIn(BaseModel):
    assignment_id: str = Field(min_length=1, max_length=100)
    # Missing means create only; an existing draft requires the reviewed revision.
    revision: int | None = Field(default=None, ge=1)
