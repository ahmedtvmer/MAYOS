"""Pydantic request/response contracts for the FastAPI service."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent.ProgramState import GeneratedProgramSchema, ProgramExerciseSchema

__all__ = [
    "AccountCapabilitiesOut",
    "AccountOut",
    "AccountPlansOut",
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
    "CoachExerciseHistoryOut",
    "CoachExerciseHistoryPointOut",
    "CoachExerciseRecordOut",
    "CoachIdentityOut",
    "CoachInviteRedeemIn",
    "CoachNoticeListOut",
    "CoachPersonalRecordOut",
    "CoachPlayerDivergenceOut",
    "CoachPlayerExerciseOut",
    "CoachPlayerExercisesOut",
    "CoachPlayerLatestSessionOut",
    "CoachPlayerRecentSessionOut",
    "CoachPlayerSessionExerciseOut",
    "CoachPlayerSummaryOut",
    "CoachProfileOut",
    "CoachProfileUpdate",
    "CoachProgramRequestListOut",
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
    "PlanStateOut",
    "PlayerNoticeListOut",
    "PlayerProgramRequestIn",
    "PlayerProgramRequestListOut",
    "ProfileUpdate",
    "ProgramExerciseSchema",
    "ProgramGenerateIn",
    "ProgramRequestDeclineIn",
    "ProgramRequestOut",
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


class PlanStateOut(BaseModel):
    """One capability's server-owned plan. A status field leaves room for later lifecycle states."""

    plan: Literal["free", "pro"]
    status: str


class AccountPlansOut(BaseModel):
    """Independent Lifter and Coach plans. ``None`` means the account lacks that capability."""

    lifter: PlanStateOut | None = None
    coach: PlanStateOut | None = None


class AccountOut(BaseModel):
    """Current account identity, capabilities, and plan states, read from the durable registry."""

    account_id: str
    trainee_id: str
    capabilities: AccountCapabilitiesOut
    plans: AccountPlansOut


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


class CoachPlayerSessionExerciseOut(BaseModel):
    """One exercise's working-set totals within a session."""

    name: str
    sets: int
    reps: int
    volume_kg: float


class CoachPlayerDivergenceOut(BaseModel):
    """A factual skipped or unplanned exercise in the player's workout history."""

    kind: str
    exercise_id: str
    exercise_name: str


class CoachPlayerLatestSessionOut(BaseModel):
    """The assigned player's most recent committed session."""

    session_date: str
    split_name: str
    readiness_score: int | None = None
    sets_count: int
    total_volume_kg: float
    exercises: list[CoachPlayerSessionExerciseOut] = []
    divergences: list[CoachPlayerDivergenceOut] = []


class CoachPlayerRecentSessionOut(BaseModel):
    """A compact session entry for the assigned player's recent history."""

    session_id: str
    session_date: str
    split_name: str
    readiness_score: int | None = None
    sets_count: int
    total_volume_kg: float
    divergences: list[CoachPlayerDivergenceOut] = []


class CoachPlayerSummaryOut(BaseModel):
    """Roster identity plus the assigned player's volume and session activity."""

    player_username: str
    started_at: str
    status: str
    volume: dict[str, float]
    latest_session: CoachPlayerLatestSessionOut | None = None
    recent_sessions: list[CoachPlayerRecentSessionOut] = []


class CoachPlayerExerciseOut(BaseModel):
    id: str
    name: str


class CoachPlayerExercisesOut(BaseModel):
    exercises: list[CoachPlayerExerciseOut]


class CoachPersonalRecordOut(BaseModel):
    exercise_id: str
    name: str
    record_type: str
    reps: int
    value: float
    prev_value: float | None = None
    achieved_at: str
    session_id: str | None = None


class CoachExerciseHistoryPointOut(BaseModel):
    """One progression point for the assigned player's exercise."""

    date: str
    weight_kg: float
    reps: int
    rpe: float
    e1rm: float


class CoachExerciseRecordOut(BaseModel):
    """One recorded personal record for the assigned player's exercise."""

    record_type: str
    reps: int
    value: float
    prev_value: float | None = None
    achieved_at: str
    session_id: str | None = None


class CoachExerciseHistoryOut(BaseModel):
    """Progression history, latest-record caption, and records for one exercise."""

    history: list[CoachExerciseHistoryPointOut]
    caption: str | None = None
    records: list[CoachExerciseRecordOut]


class AssignmentNoticeOut(BaseModel):
    notice_id: str
    kind: str
    message: str
    created_at: str
    read_at: str | None = None


class CoachNoticeListOut(BaseModel):
    notices: list[AssignmentNoticeOut]


class PlayerNoticeListOut(BaseModel):
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


class PlayerProgramRequestIn(BaseModel):
    """A player's request against their coach-controlled program; the identity is the JWT."""

    kind: Literal["exercise_substitution", "split_change"]
    day_name: str | None = Field(default=None, max_length=80)
    exercise_id: str | None = Field(default=None, max_length=120)
    replacement_exercise_id: str | None = Field(default=None, max_length=120)
    desired_weekly_frequency: int | None = Field(default=None, ge=1, le=5)
    desired_split_preference: str | None = Field(default=None, max_length=200)
    reason: str = Field(min_length=1, max_length=500)


class ProgramRequestOut(BaseModel):
    """A program request's pinned target and its current resolution state."""

    request_id: str
    assignment_id: str
    kind: str
    program_version: int
    day_name: str | None = None
    exercise_id: str | None = None
    replacement_exercise_id: str | None = None
    desired_weekly_frequency: int | None = None
    desired_split_preference: str | None = None
    reason: str
    status: str
    response: str | None = None
    created_at: str
    resolved_at: str | None = None
    resolved_by: str | None = None


class PlayerProgramRequestListOut(BaseModel):
    requests: list[ProgramRequestOut]


class CoachProgramRequestListOut(BaseModel):
    requests: list[ProgramRequestOut]


class ProgramRequestDeclineIn(BaseModel):
    response: str = Field(min_length=1, max_length=500)


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
