from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field
from agent.program_prescription import (
    DEFAULT_TARGET_SETS,
    MAX_REPS,
    MAX_EXERCISES_PER_DAY,
    MAX_PROGRAM_DAYS,
    MAX_PROGRAM_NOTES_LENGTH,
    MAX_RAMPED_WARMUP_SETS,
    MAX_TEMPO_LENGTH,
    MAX_WARMUP_MOVEMENT_REPS,
    MAX_WARMUP_MOVEMENT_SETS,
    MAX_GENERATED_TARGET_SETS,
    MIN_REPS,
    MIN_GENERATED_EXERCISES_PER_DAY,
    MIN_GENERATED_TARGET_RPE,
    MIN_GENERATED_TARGET_SETS,
    MIN_RAMPED_WARMUP_SETS,
    MIN_WARMUP_MOVEMENT_REPS,
    MIN_WARMUP_MOVEMENT_SETS,
    DEFAULT_EXERCISE_REST_SECONDS,
    DEFAULT_WARMUP_MOVEMENT_REPS,
    DEFAULT_WARMUP_MOVEMENT_REST_SECONDS,
    DEFAULT_WARMUP_MOVEMENT_SETS,
)

# --- Pydantic Output Contracts ---


class SuggestedSubstitute(BaseModel):
    exercise_id: str
    exercise_name: str


class ProgramExerciseSchema(BaseModel):
    exercise_id: str = Field(description="Exact ID matching candidate from the database")
    exercise_name: str = Field(description="Exact name of the exercise")
    equipment: str | None = Field(default=None, description="Exercise library equipment")
    slot_key: str | None = Field(default=None, description="Movement slot that produced this exercise")
    warmup_sets: int = Field(
        default=MIN_RAMPED_WARMUP_SETS,
        ge=MIN_RAMPED_WARMUP_SETS,
        le=MAX_RAMPED_WARMUP_SETS,
        description="Ramped warm-up sets before working sets",
    )
    target_sets: int = Field(
        default=DEFAULT_TARGET_SETS,
        ge=MIN_GENERATED_TARGET_SETS,
        le=MAX_GENERATED_TARGET_SETS,
        description="Working sets count",
    )
    target_reps_min: int = Field(ge=MIN_REPS, le=MAX_REPS, description="Lower bound of rep window")
    target_reps_max: int = Field(ge=MIN_REPS, le=MAX_REPS, description="Upper bound of rep window")
    target_rpe: float = Field(
        default=8.5,
        ge=MIN_GENERATED_TARGET_RPE,
        le=10.0,
        description="Proximity to failure (7.0 to 10.0)",
    )
    rest_seconds: int = Field(default=DEFAULT_EXERCISE_REST_SECONDS, description="Rest period in seconds")
    tempo: str | None = Field(default=None, max_length=MAX_TEMPO_LENGTH, description="Optional movement tempo cue")
    notes: str | None = Field(
        default=None,
        max_length=MAX_PROGRAM_NOTES_LENGTH,
        description="Execution steps from the exercise catalog (or a chat-supplied cue)",
    )
    image_path: str | None = Field(default=None, description="Local path or URL to demonstration image")
    gif_path: str | None = Field(default=None, description="Local path or URL to demonstration animated GIF")
    suggested_substitutes: list[SuggestedSubstitute] = Field(
        default_factory=list,
        description="Next Equipment access-compatible Staple exercises for this movement slot",
    )


class WarmupExerciseSchema(BaseModel):
    exercise_id: str | None = Field(default=None, description="Catalog ID when resolvable")
    equipment: str | None = Field(default=None, description="Exercise library equipment")
    exercise_name: str = Field(description="Warm-up movement name")
    sets: int = Field(
        default=DEFAULT_WARMUP_MOVEMENT_SETS,
        ge=MIN_WARMUP_MOVEMENT_SETS,
        le=MAX_WARMUP_MOVEMENT_SETS,
    )
    reps: int = Field(
        default=DEFAULT_WARMUP_MOVEMENT_REPS,
        ge=MIN_WARMUP_MOVEMENT_REPS,
        le=MAX_WARMUP_MOVEMENT_REPS,
    )
    rest_seconds: int = Field(default=DEFAULT_WARMUP_MOVEMENT_REST_SECONDS)
    notes: str | None = Field(default=None, max_length=MAX_PROGRAM_NOTES_LENGTH, description="Optional warm-up note")
    image_path: str | None = Field(default=None)
    gif_path: str | None = Field(default=None)


class ProgramDaySchema(BaseModel):
    day_name: str = Field(description="e.g., 'Upper 1', 'Lower 1'")
    day_order: int = Field(ge=1, le=MAX_PROGRAM_DAYS)
    warmup_exercises: list[WarmupExerciseSchema] = Field(
        default_factory=list, description="2-3 general preparation movements performed before the session"
    )
    exercises: list[ProgramExerciseSchema] = Field(
        min_length=MIN_GENERATED_EXERCISES_PER_DAY,
        max_length=MAX_EXERCISES_PER_DAY,
        description="Ordered exercises prescribed for the training day",
    )
    cardio: str | None = Field(default=None, description="Optional cardio finisher note")


class ProgramSchema(BaseModel):
    program_name: str = Field(description="Display title of the generated split")
    weekly_frequency: int = Field(ge=1, le=MAX_PROGRAM_DAYS, description="Number of training days per week")
    split_type: str = Field(default="custom", description="Split categorization, e.g., 'Upper/Lower', 'PPL'")
    instructions: str = Field(default="", description="Reserved program-level notes (currently unused)")
    days: list[ProgramDaySchema] = Field(
        max_length=MAX_PROGRAM_DAYS,
        description="Ordered list of training day routines",
    )


class GeneratedProgramSchema(BaseModel):
    program_name: str = Field(description="Descriptive title of the program")
    split_type: str = Field(description="Resolved split architecture")
    weekly_frequency: int = Field(ge=1, le=MAX_PROGRAM_DAYS)
    instructions: str = Field(default="", description="Reserved program-level notes (currently unused)")
    days: list[ProgramDaySchema] = Field(max_length=MAX_PROGRAM_DAYS)
    version: int | None = Field(default=None, description="Stable ledger version; set when loaded from storage")
    published_by_coach_account_id: str | None = Field(
        default=None, description="Publishing coach's account id; None for player self-service"
    )
    created_at: str | None = Field(
        default=None, description="Ledger creation timestamp; set when loaded from storage"
    )


class PersistedProgramExerciseSchema(ProgramExerciseSchema):
    """A stored prescription, including coach-authored set and effort ranges."""

    target_sets: int = Field(default=DEFAULT_TARGET_SETS, ge=1, description="Working sets count")
    target_rpe: float = Field(default=8.5, ge=5.0, le=10.0, description="Proximity to failure")


class PersistedProgramDaySchema(BaseModel):
    day_name: str = Field(description="e.g., 'Upper 1', 'Lower 1'")
    day_order: int = Field(ge=1, le=MAX_PROGRAM_DAYS)
    warmup_exercises: list[WarmupExerciseSchema] = Field(default_factory=list)
    exercises: list[PersistedProgramExerciseSchema] = Field(
        min_length=1, max_length=MAX_EXERCISES_PER_DAY
    )
    cardio: str | None = None


class PersistedProgramSchema(GeneratedProgramSchema):
    """A saved program; coach-authored prescriptions may use the broader range."""

    days: list[PersistedProgramDaySchema] = Field(max_length=MAX_PROGRAM_DAYS)


# --- LangGraph Node State ---


class ProgramState(TypedDict):
    user_id: int
    raw_profile: dict[str, Any]
    user_split_override: str | None
    rep_preference: Literal["low", "balanced", "high"]
    resolved_frequency: int
    resolved_split: str
    target_days: list[str]
    candidate_pool: dict[str, list[dict[str, Any]]]
    generated_program: GeneratedProgramSchema | None
    error: str | None


class CustomDayPlan(BaseModel):
    day_order: int = Field(ge=1, le=MAX_PROGRAM_DAYS)
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
