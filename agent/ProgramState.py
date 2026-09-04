from typing import TypedDict, List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field

# --- Pydantic Output Contracts ---

class ProgramExerciseSchema(BaseModel):
    exercise_id: str = Field(description="Exact ID matching candidate from the database")
    exercise_name: str = Field(description="Exact name of the exercise")
    target_sets: int = Field(default=3, ge=2, le=3, description="Working sets count (strictly 2 to 3)")
    target_reps_min: int = Field(ge=4, le=30, description="Lower bound of rep window")
    target_reps_max: int = Field(ge=4, le=30, description="Upper bound of rep window")
    target_rpe: float = Field(default=8.5, ge=7.0, le=10.0, description="Proximity to failure (7.0 to 10.0)")
    rest_seconds: int = Field(default=120, description="Rest period in seconds")
    notes: Optional[str] = Field(default=None, description="Biomechanical execution cue")

class ProgramDaySchema(BaseModel):
    day_name: str = Field(description="e.g., 'Upper 1', 'Lower 1'")
    day_order: int = Field(ge=1, le=5)
    exercises: List[ProgramExerciseSchema] = Field(
        min_length=4, 
        max_length=6, 
        description="Strictly 4 to 6 high-yield movements per session"
    )

class GeneratedProgramSchema(BaseModel):
    program_name: str = Field(description="Descriptive title of the program")
    split_type: str = Field(description="Resolved split architecture")
    weekly_frequency: int = Field(ge=1, le=5)
    days: List[ProgramDaySchema]

# --- LangGraph Node State ---

class ProgramState(TypedDict):
    user_id: int
    raw_profile: Dict[str, Any]
    user_split_override: Optional[str]
    rep_preference: Literal["low", "balanced", "high"]
    resolved_frequency: int
    resolved_split: str
    target_days: List[str]
    volume_budget: Dict[str, int]
    candidate_pool: Dict[str, List[Dict[str, Any]]]
    generated_program: Optional[GeneratedProgramSchema]
    error: Optional[str]

class CustomDayPlan(BaseModel):
    day_order: int = Field(ge=1, le=5)
    day_name: str = Field(description="e.g., 'Chest & Back', 'Upper', 'Arms & Delts'")
    target_body_parts: List[str] = Field(
        description="Target muscle groups for this session, e.g. ['chest', 'back'] or ['waist', 'upper legs'] matching the dataset's body_part column"
    )

class DynamicSplitPlan(BaseModel):
    split_name: str = Field(description="Clean descriptive title for this split")
    days: List[CustomDayPlan] = Field(description="Exact list of days matching committed frequency")