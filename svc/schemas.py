"""Pydantic request/response contracts for the FastAPI service."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

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
    "CheckInIn",
    "CheckInOut",
    "ClaimIn",
    "CoachAlertListOut",
    "CoachAlertOut",
    "CoachAssistantIn",
    "CoachAssistantOut",
    "CoachAssistantTurn",
    "CoachAssignmentsOut",
    "CoachCapabilityDisableOut",
    "CoachCheckInCreateOut",
    "CoachCheckInListOut",
    "CoachCrossRosterProgramRequestListOut",
    "CoachCrossRosterProgramRequestOut",
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
    "CoachPlayerPauseOut",
    "CoachPlayerRecentSessionOut",
    "CoachPlayerScheduleOut",
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
    "IntakeAnswerIn",
    "IntakeConfirmOut",
    "IntakeFieldOut",
    "IntakeOut",
    "IntakeProgressOut",
    "IntakeProgramOut",
    "MessageOut",
    "OnboardingStartOut",
    "OnboardingStepIn",
    "OnboardingStepOut",
    "PasswordChangeIn",
    "PersonaUpdate",
    "PlanStateOut",
    "PlayerCheckInListOut",
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
    "ScheduledPauseOut",
    "SessionCommitIn",
    "TraineeIn",
    "TrainingPauseCreateOut",
    "TrainingPauseIn",
    "TrainingPauseListOut",
    "TrainingScheduleOut",
    "TrainingScheduleSetOut",
    "TrainingScheduleUpdateIn",
    "TrainingScheduleVersionOut",
    "TokenOut",
    "WorkoutSetIn",
]


class TraineeIn(BaseModel):
    trainee_id: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=8, max_length=128)
    remember_me: bool = False


class ClaimIn(BaseModel):
    """One-time claim of an imported account with its owner-issued claim code."""

    trainee_id: str = Field(min_length=1, max_length=60)
    claim_code: str = Field(min_length=1, max_length=128)
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
    """Current account identity, capabilities, and plan states, read from the durable registry.

    ``coach_ai_enabled`` is the server's effective feature state (flag plus
    recorded eval/privacy report, ADR 049), so a client can hide the coach
    assistant entry point when the operator has not enabled it.
    """

    account_id: str
    trainee_id: str
    capabilities: AccountCapabilitiesOut
    plans: AccountPlansOut
    coach_ai_enabled: bool = False


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


#: Bounds for the coach assistant request (issue #45). The client holds the
#: transcript in memory and sends it with every call; the server keeps nothing.
COACH_QUESTION_MAX_CHARS = 1000
COACH_HISTORY_MAX_TURNS = 12
COACH_HISTORY_TURN_MAX_CHARS = 2000


class CoachAssistantTurn(BaseModel):
    """One client-held transcript turn; roles are the coach's and the assistant's."""

    role: Literal["coach", "assistant"]
    content: str = Field(min_length=1, max_length=COACH_HISTORY_TURN_MAX_CHARS)


class CoachAssistantIn(BaseModel):
    """A coach question with the in-memory transcript for one selected player.

    Nothing here is persisted server-side beyond ADR 038 model-usage metering.
    """

    question: str = Field(min_length=1, max_length=COACH_QUESTION_MAX_CHARS)
    history: list[CoachAssistantTurn] = Field(default_factory=list, max_length=COACH_HISTORY_MAX_TURNS)


class CoachAssistantOut(BaseModel):
    """The model's analysis of the selected player's telemetry."""

    answer: str


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
    """One roster row: assignment identity plus the catalog-side urgency basis (ticket #118).

    ``last_workout_on`` is a date only, never session detail, and every field is
    read from catalog tables so listing the roster mounts no player ledger.
    ``program_name`` is the active program's display name, cached catalog-side
    by the evaluation or the coach's publication (#120).
    """

    assignment_id: str
    player_username: str
    started_at: str
    status: str
    alerts_new: int = 0
    alerts_acknowledged: int = 0
    current_missed_streak: int = 0
    next_follow_up_on: str | None = None
    pending_requests: int = 0
    last_workout_on: str | None = None
    program_name: str | None = None


class CoachAssignmentsOut(BaseModel):
    assignments: list[CoachRosterEntryOut]


class CoachAlertOut(BaseModel):
    """One catalog-side alert for the coach alert centre (ADR 030/031/032).

    ``kind`` distinguishes missed-day, follow-up-due, deload, and
    performance-regression alerts. The kind-specific fields are flattened beside
    the common ones, so a client can read ``streak_start_date``/``missed_count``,
    ``due_on``, or the progression evidence directly.
    """

    alert_id: str
    assignment_id: str
    player_username: str
    kind: str
    state: str
    created_at: str
    acknowledged_at: str | None = None
    resolved_at: str | None = None
    resolved_by: str | None = None
    streak_start_date: str | None = None
    last_missed_date: str | None = None
    missed_count: int = 0
    due_on: str | None = None
    last_check_in_on: str | None = None
    severity: str | None = None
    reason: str | None = None
    recent_readiness_avg: float | None = None
    volume_multiplier: float | None = None
    intensity_cap_rpe: float | None = None
    exercise_id: str | None = None
    exercise_name: str | None = None
    status_badge: str | None = None
    e1rm_delta: float | None = None
    current_e1rm: float | None = None
    top_load: float | None = None
    top_reps: int | None = None
    top_rpe: float | None = None
    session_id: str | None = None
    session_date: str | None = None
    latest_session_id: str | None = None
    latest_session_date: str | None = None


class CoachAlertListOut(BaseModel):
    alerts: list[CoachAlertOut]


class CheckInIn(BaseModel):
    """A coach-recorded check-in: date, contact channel, and an optional note."""

    checked_in_on: str
    channel: str
    note: str | None = None


class CheckInOut(BaseModel):
    """One immutable check-in fact, visible to the coach (while assigned) and the player."""

    check_in_id: str
    assignment_id: str
    checked_in_on: str
    channel: str
    note: str | None = None
    created_at: str
    coach_username: str | None = None
    assignment_status: str | None = None


class CoachCheckInListOut(BaseModel):
    check_ins: list[CheckInOut]


class CoachCheckInCreateOut(BaseModel):
    check_in: CheckInOut
    next_follow_up_on: str | None = None


class PlayerCheckInListOut(BaseModel):
    check_ins: list[CheckInOut]


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


class PerformedDateCorrectionOut(BaseModel):
    """One immutable performed-date correction on a committed session (ADR 035)."""

    previous_date: str
    corrected_date: str
    corrected_at: str


class CoachPlayerLatestSessionOut(BaseModel):
    """The assigned player's most recent committed session."""

    session_id: str | None = None
    session_date: str
    split_name: str
    readiness_score: int | None = None
    sets_count: int
    total_volume_kg: float
    program_version: int | None = None
    active_program_version_at_sync: int | None = None
    is_historical_program: bool = False
    uploaded_at: str | None = None
    edited_at: str | None = None
    corrections: list[PerformedDateCorrectionOut] = []
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
    program_version: int | None = None
    active_program_version_at_sync: int | None = None
    is_historical_program: bool = False
    uploaded_at: str | None = None
    edited_at: str | None = None
    corrections: list[PerformedDateCorrectionOut] = []
    divergences: list[CoachPlayerDivergenceOut] = []


class CoachPlayerScheduleOut(BaseModel):
    """The assigned player's current expected training weekdays and timezone."""

    weekdays: list[int]
    timezone: str


class CoachPlayerPauseOut(BaseModel):
    """An upcoming or active training pause the assigned player scheduled."""

    starts_on: str
    ends_on: str


class CoachPlayerSummaryOut(BaseModel):
    """Roster identity plus the assigned player's volume and session activity."""

    player_username: str
    started_at: str
    status: str
    volume: dict[str, float]
    latest_session: CoachPlayerLatestSessionOut | None = None
    recent_sessions: list[CoachPlayerRecentSessionOut] = []
    schedule: CoachPlayerScheduleOut | None = None
    pauses: list[CoachPlayerPauseOut] = []


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


class AccountDeleteIn(BaseModel):
    """Password confirmation for an in-app, irreversible account deletion (ADR 015/039)."""

    password: str = Field(min_length=1, max_length=128)


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
    # The intake's allowed values (service/intake.py); anything else would be
    # stored and then silently read as "balanced" by the program generator.
    rep_preference: Literal["low", "balanced", "high"] | None = None
    current_goal: str | None = None
    weekly_frequency: int | None = Field(default=None, ge=1, le=5)
    equipment_access: str | None = None
    injuries_or_limitations: str | None = None
    weight_kg: float | None = Field(default=None, ge=30.0, le=250.0)


class PersonaUpdate(BaseModel):
    coach_tone: str = Field(min_length=1, max_length=200)
    custom_instructions: str = Field(default="", max_length=5000)


class TrainingScheduleVersionOut(BaseModel):
    """One effective-dated version of the player's expected training weekdays."""

    schedule_id: str
    weekdays: list[int]
    timezone: str
    effective_from: str
    created_at: str


class ScheduledPauseOut(BaseModel):
    """A prospective pause; no reason is stored or returned."""

    pause_id: str
    starts_on: str
    ends_on: str
    created_at: str


class TrainingScheduleOut(BaseModel):
    """The current schedule, every version, and today's active pauses."""

    current: TrainingScheduleVersionOut | None = None
    versions: list[TrainingScheduleVersionOut] = []
    pauses: list[ScheduledPauseOut] = []


class TrainingScheduleUpdateIn(BaseModel):
    """A player sets expected weekdays and timezone separately from program order."""

    weekdays: list[int]
    timezone: str = Field(min_length=1, max_length=64)
    effective_from: str | None = None


class TrainingScheduleSetOut(BaseModel):
    """The appended version and the schedule now current."""

    version: TrainingScheduleVersionOut
    current: TrainingScheduleVersionOut | None = None


class TrainingPauseIn(BaseModel):
    """A prospective pause body; only the bounds, never a reason."""

    starts_on: str = Field(min_length=1, max_length=10)
    ends_on: str = Field(min_length=1, max_length=10)


class TrainingPauseListOut(BaseModel):
    pauses: list[ScheduledPauseOut]


class TrainingPauseCreateOut(BaseModel):
    """The created pause and whether the assigned coach was notified."""

    pause: ScheduledPauseOut
    notice_sent: bool


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


class CoachCrossRosterProgramRequestOut(ProgramRequestOut):
    """One request across the coach's roster: the per-assignment fields plus the player.

    ``assignment_id`` is already part of ``ProgramRequestOut``, so the client can
    apply or decline through the existing per-assignment endpoints directly.
    """

    player_username: str


class CoachCrossRosterProgramRequestListOut(BaseModel):
    requests: list[CoachCrossRosterProgramRequestOut]


class ProgramRequestDeclineIn(BaseModel):
    response: str = Field(min_length=1, max_length=500)


class WorkoutSetIn(BaseModel):
    weight_kg: float = Field(ge=0.0, le=500.0)
    reps: int = Field(ge=0, le=50)
    rpe: float = Field(ge=6.0, le=10.0)
    is_warmup: bool = False


class ExerciseSetsIn(BaseModel):
    exercise: ProgramExerciseSchema
    sets: list[WorkoutSetIn] = Field(min_length=1)


class SessionCommitIn(BaseModel):
    day_order: int = Field(ge=1, le=5)
    readiness: int = Field(ge=1, le=5)
    session_notes: str = Field(default="", max_length=2000)
    sets: list[ExerciseSetsIn] = Field(min_length=1)

    # Offline-sync contract (ADR 020/033). When ``client_session_id`` is absent
    # the request keeps the legacy online-only behaviour; when present the
    # performed date/timezone, captured program version, and capture instant are
    # required and validated by the service.
    client_session_id: str | None = Field(default=None, max_length=64)
    performed_date: str | None = Field(default=None, max_length=10)
    performed_timezone: str | None = Field(default=None, max_length=64)
    program_version: int | None = Field(default=None, ge=0)
    captured_at: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _sync_fields_require_client_session_id(self) -> "SessionCommitIn":
        if self.client_session_id is None and (
            self.performed_date is not None
            or self.performed_timezone is not None
            or self.program_version is not None
            or self.captured_at is not None
        ):
            raise ValueError("performed_date/performed_timezone/program_version/captured_at require client_session_id.")
        return self


class SessionPerformedDateCorrectIn(BaseModel):
    """A requested performed-date correction for one committed session (ADR 035)."""

    performed_date: str = Field(max_length=10)


class SessionPerformedDateCorrectOut(BaseModel):
    """The result of a performed-date correction; ``changed`` is false for a no-op."""

    session_id: str
    session_date: str
    previous_date: str | None = None
    edited_at: str | None = None
    changed: bool
    corrections: list[PerformedDateCorrectionOut] = []


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


class IntakeAnswerIn(BaseModel):
    """One named onboarding answer; validation is the service's (field-specific)."""

    value: Any


class IntakeFieldOut(BaseModel):
    """One named onboarding decision: contract, current answer, and prefill marker."""

    name: str
    type: str
    required: bool
    allowed_values: list[str] = []
    minimum: float | None = None
    maximum: float | None = None
    profile_field: str
    explanation: str | None = None
    hint: str | None = None
    examples: list[str] = []
    option_descriptions: dict[str, str] = {}
    answer: Any | None = None
    prefilled: bool = False
    answered: bool = False
    updated_at: str | None = None


class IntakeProgressOut(BaseModel):
    """Resume progress over the required decisions."""

    answered_required: int
    required_total: int
    answered: int
    total_fields: int
    next_unanswered: str | None = None


class IntakeProgramOut(BaseModel):
    """The stored first-program result, returned once the intake is confirmed."""

    program_name: str | None = None
    weekly_frequency: int | None = None
    program_message: str | None = None


class IntakeOut(BaseModel):
    """`GET /onboarding/intake` and the answer endpoints' updated read-back."""

    status: str
    disclosure_acknowledged: bool
    fields: list[IntakeFieldOut]
    progress: IntakeProgressOut
    program: IntakeProgramOut | None = None


class IntakeConfirmOut(BaseModel):
    """`POST /onboarding/intake/confirm`: the confirmed first-program result."""

    status: str
    program_name: str | None = None
    weekly_frequency: int | None = None
    program_message: str | None = None


class HealthOut(BaseModel):
    status: str
    details: dict[str, Any] = {}
