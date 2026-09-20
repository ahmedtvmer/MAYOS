from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

# --- Pydantic Output Contracts ---


class ProgramExerciseSchema(BaseModel):
    exercise_id: str = Field(description="Exact ID matching candidate from the database")
    exercise_name: str = Field(description="Exact name of the exercise")
    slot_key: str | None = Field(default=None, description="Movement slot that produced this exercise")
    warmup_sets: int = Field(default=0, ge=0, le=4, description="Ramped warm-up sets before working sets")
    target_sets: int = Field(default=2, ge=1, le=4, description="Working sets count (1 to 4)")
    target_reps_min: int = Field(ge=4, le=30, description="Lower bound of rep window")
    target_reps_max: int = Field(ge=4, le=30, description="Upper bound of rep window")
    target_rpe: float = Field(default=8.5, ge=7.0, le=10.0, description="Proximity to failure (7.0 to 10.0)")
    rest_seconds: int = Field(default=180, description="Rest period in seconds")
    notes: str | None = Field(default=None, description="Execution steps from the exercise catalog (or a chat-supplied cue)")
    image_path: str | None = Field(default=None, description="Local path or URL to demonstration image")
    gif_path: str | None = Field(default=None, description="Local path or URL to demonstration animated GIF")


class WarmupExerciseSchema(BaseModel):
    exercise_id: str | None = Field(default=None, description="Catalog ID when resolvable")
    exercise_name: str = Field(description="Warm-up movement name")
    sets: int = Field(default=2, ge=1, le=3)
    reps: int = Field(default=10, ge=5, le=20)
    rest_seconds: int = Field(default=45)
    notes: str | None = Field(default=None, description="Optional warm-up note")
    image_path: str | None = Field(default=None)
    gif_path: str | None = Field(default=None)


class ProgramDaySchema(BaseModel):
    day_name: str = Field(description="e.g., 'Upper 1', 'Lower 1'")
    day_order: int = Field(ge=1, le=5)
    warmup_exercises: list[WarmupExerciseSchema] = Field(
        default_factory=list, description="2-3 general preparation movements performed before the session"
    )
    exercises: list[ProgramExerciseSchema] = Field(
        min_length=3, max_length=14, description="6 to 12 high-yield movement slots per session"
    )
    cardio: str | None = Field(default=None, description="Optional cardio finisher note")


class ProgramSchema(BaseModel):
    program_name: str = Field(description="Display title of the generated split")
    weekly_frequency: int = Field(ge=1, le=5, description="Number of training days per week")
    split_type: str = Field(default="custom", description="Split categorization, e.g., 'Upper/Lower', 'PPL'")
    instructions: str = Field(default="", description="Reserved program-level notes (currently unused)")
    days: list[ProgramDaySchema] = Field(description="Ordered list of training day routines")


class GeneratedProgramSchema(BaseModel):
    program_name: str = Field(description="Descriptive title of the program")
    split_type: str = Field(description="Resolved split architecture")
    weekly_frequency: int = Field(ge=1, le=5)
    instructions: str = Field(default="", description="Reserved program-level notes (currently unused)")
    days: list[ProgramDaySchema]


# --- LangGraph Node State ---


class ProgramState(TypedDict):
    user_id: int
    raw_profile: dict[str, Any]
    user_split_override: str | None
    rep_preference: Literal["low", "balanced", "high"]
    resolved_frequency: int
    resolved_split: str
    target_days: list[str]
    volume_budget: dict[str, int]
    candidate_pool: dict[str, list[dict[str, Any]]]
    generated_program: GeneratedProgramSchema | None
    error: str | None


class CustomDayPlan(BaseModel):
    day_order: int = Field(ge=1, le=5)
    day_name: str = Field(description="e.g., 'Chest & Back', 'Upper', 'Arms & Delts'")
    target_slots: list[str] = Field(
        default_factory=list,
        description="Ordered movement slot keys for this session, e.g. ['incline_press', 'horizontal_row', 'biceps_preacher']",
    )
    target_body_parts: list[str] = Field(
        default_factory=list,
        description="Legacy muscle targets; only used as a fallback when target_slots is empty",
    )
    warmup_family: str = Field(default="full", description="Warm-up block family: upper, lower, full or arms")
    sets_family: str | None = Field(
        default=None, description="Working-set profile: standard, leg, arms or full (defaults from warmup_family)"
    )
    double_slots: list[str] = Field(
        default_factory=list, description="Full-body priority slots that earn a second working set"
    )
    cardio: str | None = Field(default=None, description="Optional cardio note")


class DynamicSplitPlan(BaseModel):
    split_name: str = Field(description="Clean descriptive title for this split")
    days: list[CustomDayPlan] = Field(description="Exact list of days matching committed frequency")
