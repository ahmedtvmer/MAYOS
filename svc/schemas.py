"""Pydantic request/response contracts for the FastAPI service."""

from typing import Any

from pydantic import BaseModel, Field

from agent.ProgramState import GeneratedProgramSchema, ProgramExerciseSchema

__all__ = [
    "AccountCapabilitiesOut",
    "AccountOut",
    "AssignmentAccessOut",
    "AssignmentEndOut",
    "AssignmentInviteIssueOut",
    "AssignmentInvitePreviewOut",
    "AssignmentInviteTokenIn",
    "AssignmentNoticeOut",
    "AssignmentOut",
    "AssignmentRedeemIn",
    "AssignmentRedeemOut",
    "ChatMessageIn",
    "ChatMessageOut",
    "CoachAssignmentsOut",
    "CoachCapabilityDisableOut",
    "CoachIdentityOut",
    "CoachInviteRedeemIn",
    "CoachNoticeListOut",
    "CoachProfileOut",
    "CoachProfileUpdate",
    "CoachRosterEntryOut",
    "EmailUpdateIn",
    "ExerciseSetsIn",
    "ForgotPasswordIn",
    "GeneratedProgramSchema",
    "MessageOut",
    "OnboardingStartOut",
    "OnboardingStepIn",
    "OnboardingStepOut",
    "PasswordChangeIn",
    "PersonaUpdate",
    "ProfileUpdate",
    "ProgramExerciseSchema",
    "ProgramGenerateIn",
    "RecoveryEmailOut",
    "ResetPasswordIn",
    "SessionCommitIn",
    "TraineeIn",
    "TokenOut",
    "WorkoutSetIn",
]


class TraineeIn(BaseModel):
    trainee_id: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=8, max_length=128)
    remember_me: bool = False


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    trainee_id: str


class MessageOut(BaseModel):
    message: str


class AccountCapabilitiesOut(BaseModel):
    player: bool
    coach: bool


class AccountOut(BaseModel):
    """Current account identity and capabilities, read from the durable registry."""

    account_id: str
    trainee_id: str
    capabilities: AccountCapabilitiesOut


class CoachInviteRedeemIn(BaseModel):
    """Body for authenticated coach-invite redemption. The identity is the JWT, never the body."""

    token: str = Field(min_length=10, max_length=128)


class CoachProfileOut(BaseModel):
    """Coach-authored profile fields, keyed by the immutable account id."""

    account_id: str
    display_name: str
    bio: str
    specialization: str
    capacity: int


class CoachProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=60)
    bio: str = Field(default="", max_length=1000)
    specialization: str = Field(default="", max_length=200)
    capacity: int = Field(ge=1, le=200)


class CoachIdentityOut(BaseModel):
    """The coach's current, product-facing identity shown to a prospective player."""

    display_name: str
    bio: str
    specialization: str


class AssignmentAccessOut(BaseModel):
    """The exact training-data access an active assignment grants (ADR 014)."""

    scope: str
    includes_current_history: bool
    includes_historical_history: bool
    active_while_assigned: bool
    description: str


class AssignmentInvitePreviewOut(BaseModel):
    """Preview returned before consent. Reading it never consumes the code."""

    coach: CoachIdentityOut
    access: AssignmentAccessOut
    expires_at: str


class AssignmentOut(BaseModel):
    assignment_id: str
    coach: CoachIdentityOut
    started_at: str
    status: str


class AssignmentInviteIssueOut(BaseModel):
    """The one-time code and remaining capacity for the issuing coach."""

    token: str
    expires_at: str
    active_assignments: int
    capacity: int


class AssignmentInviteTokenIn(BaseModel):
    """Secret invite code carried in the body so it never lands in access logs."""

    token: str = Field(min_length=10, max_length=128)


class AssignmentRedeemIn(BaseModel):
    """Consent is explicit; the player identity is the JWT, never the body."""

    token: str = Field(min_length=10, max_length=128)
    consent: bool


class AssignmentRedeemOut(BaseModel):
    assignment: AssignmentOut
    notices_created: int
    email_sent: bool


class AssignmentEndOut(BaseModel):
    assignment_id: str
    status: str
    ended_at: str


class CoachRosterEntryOut(BaseModel):
    """Active assignment identity for the coach console; contains no training history."""

    assignment_id: str
    player_username: str
    started_at: str
    status: str


class CoachAssignmentsOut(BaseModel):
    assignments: list[CoachRosterEntryOut]


class AssignmentNoticeOut(BaseModel):
    notice_id: str
    kind: str
    message: str
    created_at: str
    read_at: str | None = None


class CoachNoticeListOut(BaseModel):
    notices: list[AssignmentNoticeOut]


class CoachCapabilityDisableOut(BaseModel):
    coach: bool
    ended_assignments: int


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class EmailUpdateIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class RecoveryEmailOut(BaseModel):
    email: str | None = None


class ForgotPasswordIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


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
