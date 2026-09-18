"""Pydantic request/response contracts for the FastAPI service."""

from typing import Any

from pydantic import BaseModel, Field

from agent.ProgramState import GeneratedProgramSchema, ProgramExerciseSchema

__all__ = [
    "ChatMessageIn",
    "ChatMessageOut",
    "ExerciseSetsIn",
    "GeneratedProgramSchema",
    "OnboardingStartOut",
    "OnboardingStepIn",
    "OnboardingStepOut",
    "PersonaUpdate",
    "ProfileUpdate",
    "ProgramExerciseSchema",
    "ProgramGenerateIn",
    "SessionCommitIn",
    "TraineeIn",
    "TokenOut",
    "WorkoutSetIn",
]


class TraineeIn(BaseModel):
    trainee_id: str = Field(min_length=1, max_length=60)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    trainee_id: str


class ProfileUpdate(BaseModel):
    proportions: str | None = None
    rep_preference: str | None = None
    current_goal: str | None = None
    weekly_frequency: int | None = Field(default=None, ge=1, le=5)
    equipment_access: str | None = None
    injuries_or_limitations: str | None = None
    weight_kg: float | None = Field(default=None, ge=30.0, le=250.0)


class PersonaUpdate(BaseModel):
    coach_tone: str = Field(min_length=1, max_length=200)
    custom_instructions: str = Field(default="", max_length=5000)


class ProgramGenerateIn(BaseModel):
    rep_preference_override: str | None = None
    frequency_override: int | None = Field(default=None, ge=1, le=5)
    user_split_override: str | None = None


class WorkoutSetIn(BaseModel):
    weight_kg: float = Field(ge=0.0, le=500.0)
    reps: int = Field(ge=0, le=50)
    rpe: float = Field(ge=6.0, le=10.0)


class ExerciseSetsIn(BaseModel):
    exercise: ProgramExerciseSchema
    sets: list[WorkoutSetIn] = Field(min_length=1)


class SessionCommitIn(BaseModel):
    day_order: int = Field(ge=1, le=5)
    readiness: int = Field(ge=1, le=5)
    session_notes: str = Field(default="", max_length=2000)
    sets: list[ExerciseSetsIn] = Field(min_length=1)


class ChatMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class ChatMessageOut(BaseModel):
    response_content: str
    program_updated: bool


class OnboardingStepIn(BaseModel):
    content: str | None = Field(default=None, max_length=5000)
    reset: bool = False


class OnboardingStartOut(BaseModel):
    intake_step: int
    is_complete: bool
    messages: list[str]


class OnboardingStepOut(OnboardingStartOut):
    pass


class HealthOut(BaseModel):
    status: str
    details: dict[str, Any] = {}
