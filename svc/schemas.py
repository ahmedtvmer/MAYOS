"""Pydantic request/response contracts for the FastAPI service."""

from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from service.analytics import PROPERTY_TYPES, WORKOUT_SYNC_FAILURE_REASONS
from service.intake import IntakeValidationError, validate_answer
from service.program_import_constants import (
    MAX_PROGRAM_IMPORT_ROWS,
)

from agent.ProgramState import (
    GeneratedProgramSchema,
    PersistedProgramDaySchema,
    PersistedProgramExerciseSchema,
    PersistedProgramSchema,
    ProgramExerciseSchema,
    SuggestedSubstitute,
)
from agent.program_prescription import (
    DEFAULT_TARGET_REPS_MAX,
    DEFAULT_TARGET_REPS_MIN,
    DEFAULT_TARGET_RIR,
    DEFAULT_TARGET_SETS,
    MAX_REPS,
    MAX_TARGET_RIR,
    MAX_EXERCISES_PER_DAY,
    DEFAULT_EXERCISE_REST_SECONDS,
    DEFAULT_WARMUP_MOVEMENT_REPS,
    DEFAULT_WARMUP_MOVEMENT_REST_SECONDS,
    DEFAULT_WARMUP_MOVEMENT_SETS,
    MAX_PROGRAM_DAYS,
    MAX_PROGRAM_NOTES_LENGTH,
    MAX_RAMPED_WARMUP_SETS,
    MAX_TEMPO_LENGTH,
    MAX_WARMUP_MOVEMENT_REPS,
    MAX_WARMUP_MOVEMENT_SETS,
    MIN_RAMPED_WARMUP_SETS,
    MIN_WARMUP_MOVEMENT_REPS,
    MIN_WARMUP_MOVEMENT_SETS,
    MIN_REPS,
    MIN_TARGET_RIR,
)
from agent.prompts import ASSISTANT_STYLE_KEYS, MAX_ASSISTANT_STYLE_INSTRUCTIONS
AssistantStyleKey = Literal[*ASSISTANT_STYLE_KEYS]
WorkoutSyncFailureReason = Literal[*WORKOUT_SYNC_FAILURE_REASONS]

__all__ = [
    "ActiveProgramOut",
    "AccountCapabilitiesOut",
    "AccountOut",
    "AccountPlansOut",
    "AnalyticsPreferenceIn",
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
    "CardioIn",
    "CardioOut",
    "CheckInIn",
    "CheckInOut",
    "CoachAlertListOut",
    "CoachAlertOut",
    "CoachAssistantIn",
    "CoachAssistantOut",
    "CoachAssistantTurn",
    "CoachActiveProgramDetailsOut",
    "CoachActiveProgramDayOut",
    "CoachActiveProgramExerciseOut",
    "CoachActiveProgramOut",
    "CoachAssignmentsOut",
    "CoachCapabilityDisableOut",
    "CoachCheckInCreateOut",
    "CheckpointRatingPartOut",
    "CheckpointReviewListItemOut",
    "CheckpointReviewOut",
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
    "CoachProgramApproveIn",
    "CoachProgramDraftIn",
    "CoachProgramDraftOut",
    "ProgramImportCreateIn",
    "ProgramImportDraftRowIn",
    "CoachExerciseCreateIn",
    "CoachExerciseOut",
    "ProgramDraftDayIn",
    "ProgramDraftExerciseIn",
    "CoachRosterEntryOut",
    "EmailUpdateIn",
    "ExerciseSetsIn",
    "ForgotPasswordIn",
    "GeneratedProgramSchema",
    "GoogleCompleteIn",
    "GoogleLinkIn",
    "GoogleSignInIn",
    "GoogleSignUpOut",
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
    "PlayerLatestSessionOut",
    "PlayerNoticeListOut",
    "PlayerProgramRequestIn",
    "PlayerProgramRequestListOut",
    "ProfileUpdate",
    "ProgramExerciseSchema",
    "ProgramGenerateIn",
    "ProgramSubstitutionIn",
    "ProgramSubstitutionUndoIn",
    "ProgramSubstitutionOut",
    "ProgramRequestDeclineIn",
    "ProgramRequestOut",
    "RecoveryEmailOut",
    "ResetPasswordIn",
    "ScheduledPauseOut",
    "SessionCommitIn",
    "SetPasswordIn",
    "TraineeIn",
    "TrainingPauseCreateOut",
    "TrainingPauseIn",
    "TrainingPauseListOut",
    "TrainingStatusOut",
    "TrainingScheduleOut",
    "TrainingScheduleSetOut",
    "TrainingScheduleUpdateIn",
    "TrainingScheduleVersionOut",
    "TokenOut",
    "UsernameAvailableOut",
    "WarmupMovementOut",
    "WarmupMovementSetOut",
    "WorkoutSetIn",
    "WorkoutSyncFailureIn",
]


class FirstTouchIn(BaseModel):
    """Untrusted acquisition input; the service keeps only normalized fields."""

    model_config = ConfigDict(extra="forbid")

    utm_source: str | None = Field(default=None, max_length=2048)
    utm_medium: str | None = Field(default=None, max_length=2048)
    utm_campaign: str | None = Field(default=None, max_length=2048)
    referrer_host: str | None = Field(default=None, max_length=2048)


class TraineeIn(BaseModel):
    trainee_id: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=8, max_length=128)
    remember_me: bool = False
    coach_invite_code: str | None = None
    display_language: Literal["en", "ar"] = "en"
    first_touch: FirstTouchIn | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    trainee_id: str
    display_language: Literal["en", "ar"] = "en"


class DisplayLanguageIn(BaseModel):
    display_language: Literal["en", "ar"]


class AnalyticsPreferenceIn(BaseModel):
    analytics_allowed: bool


class GoogleSignInIn(BaseModel):
    """Google ID token from the client. Verified server-side; never trusted as-is."""

    id_token: str


class GoogleSignUpOut(BaseModel):
    """First Google sign-in: a ticket, a guess, and a non-identifying nudge.

    The ticket is the 15-minute proof that this ``sub`` was just verified; the
    suggestion is derived from the token's given name, checked for
    availability, and stored only if the person keeps it. The hint is true
    only when Google's verified email matches a live recovery email; no email
    or matched account identity is included.
    """

    signup_ticket: str
    suggested_username: str
    existing_account_hint: bool = False


class GoogleCompleteIn(BaseModel):
    """Completes a first Google sign-in with its short-lived verified ID token."""

    signup_ticket: str
    username: str
    display_language: Literal["en", "ar"] = "en"
    id_token: str | None = None
    first_touch: FirstTouchIn | None = None


class GoogleLinkIn(BaseModel):
    """Connects a Google identity to the signed-in caller (issue #114)."""

    id_token: str


class SetPasswordIn(BaseModel):
    """First password for an account that has none, e.g. a Google-only one (#114)."""

    new_password: str = Field(min_length=8, max_length=128)


class UsernameAvailableOut(BaseModel):
    """Picker answer: ``reason`` is present only when the username is taken."""

    available: bool
    reason: str | None = None


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

    ``has_password`` and ``linked_sign_ins`` report how the account can sign in
    (issue #114): providers only, never a subject, so a client can render
    "Connected: Google" without ever seeing Google's ``sub``.

    ``coach_ai_enabled`` is the server's effective feature state (flag plus
    recorded eval/privacy report, ADR 049), so a client can hide the coach
    assistant entry point when the operator has not enabled it.
    """

    account_id: str
    trainee_id: str
    capabilities: AccountCapabilitiesOut
    plans: AccountPlansOut
    has_password: bool
    linked_sign_ins: list[str]
    display_language: Literal["en", "ar"]
    analytics_allowed: bool = True
    recovery_email_verified: bool = False
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
    coach_preparing_program: bool


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
    alerts_new_lapsing: int = 0
    alerts_acknowledged: int = 0
    current_missed_streak: int = 0
    stall_length: int = 0
    next_follow_up_on: str | None = None
    pending_requests: int = 0
    last_workout_on: str | None = None
    program_name: str | None = None


class CoachAssignmentsOut(BaseModel):
    assignments: list[CoachRosterEntryOut]


class WeightTrendPointOut(BaseModel):
    date: str
    weight_kg: float


class CoachAlertOut(BaseModel):
    """One catalog-side alert for the coach alert centre (ADR 030/031/032).

    ``kind`` distinguishes missed-day, follow-up-due, deload,
    performance-regression, stall, and profile-change alerts. The kind-specific fields
    are flattened beside the common ones, so a client can read
    ``streak_start_date``/``missed_count``, ``due_on``, progression evidence,
    ``stall_length``/``window_start_date``, or the ``profile_changes`` before/after values directly.
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
    stall_length: int = 0
    window_start_date: str | None = None
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
    player_deload_choice: dict[str, Any] | None = None
    profile_changes: dict[str, dict[str, Any]] | None = None
    weight_points: list[WeightTrendPointOut] | None = None
    target_weight_kg: float | None = None
    distance_change_kg: float | None = None
    window_days: int | None = None
    threshold_kg: float | None = None
    message_code: str | None = None
    message_params: dict[str, Any] = Field(default_factory=dict)
    message_fallback: str | None = None


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


class WarmupMovementSetOut(BaseModel):
    weight_kg: float | None
    reps: int


class WarmupMovementOut(BaseModel):
    exercise_id: str | None = None
    exercise_name: str
    sets: list[WarmupMovementSetOut]


class CardioOut(BaseModel):
    """The cardio prescription and minutes recorded for one session."""

    prescription: str
    minutes: int


class PlayerLatestSessionOut(BaseModel):
    """The player's latest session identity and separately recorded warm-ups/cardio."""

    session_id: str
    session_date: str
    split_name: str
    day_order: int | None = None
    program_version: int | None = None
    warmup_movements: list[WarmupMovementOut] = []
    cardio: CardioOut | None = None


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
    warmup_movements: list[WarmupMovementOut] = []
    cardio: CardioOut | None = None


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
    warmup_movements: list[WarmupMovementOut] = []
    cardio: CardioOut | None = None


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


class CheckpointRatingPartOut(BaseModel):
    part: str
    label: str


class CheckpointReviewListItemOut(BaseModel):
    checkpoint: int
    period_start: str
    period_end: str
    rating: list[CheckpointRatingPartOut]
    opened: bool


class CheckpointReviewOut(BaseModel):
    checkpoint: int
    period_start: str
    period_end: str
    facts: dict[str, Any]
    rating: list[CheckpointRatingPartOut]
    text: str
    text_is_template: bool


class CoachExerciseHistoryPointOut(BaseModel):
    """One progression point for the assigned player's exercise."""

    date: str
    weight_kg: float
    reps: int
    rpe: float | None = None
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
    equipment: str | None = None


class AssignmentNoticeOut(BaseModel):
    notice_id: str
    kind: str
    message: str
    created_at: str
    read_at: str | None = None
    program_change_summary: dict[str, Any] | None = None
    summary_dismissed_at: str | None = None


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
    """Confirmation for an in-app, irreversible account deletion (ADR 015/039).

    Exactly one proof is accepted (#114): the account's password, or a fresh
    Google ID token whose subject is linked to the caller.
    """

    password: str | None = Field(default=None, min_length=1, max_length=128)
    google_id_token: str | None = Field(default=None, min_length=1, max_length=8192)

    @model_validator(mode="after")
    def _exactly_one_proof(self) -> "AccountDeleteIn":
        if (self.password is None) == (self.google_id_token is None):
            raise ValueError("Provide either password or google_id_token.")
        return self


class EmailUpdateIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class RecoveryEmailOut(BaseModel):
    email: str | None = None
    verified: bool = False
    pending_email: str | None = None


class ForgotPasswordIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rep_preference: str | None = None
    current_goal: str | None = None
    weekly_frequency: int | None = None
    equipment_access: str | None = None
    injuries_or_limitations: str | None = None
    weight_kg: float | None = None
    target_weight_kg: float | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_training_profile_against_intake(cls, value: Any) -> Any:
        """Use the onboarding catalog for every editable intake field."""
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        for field_name in (
            "current_goal",
            "equipment_access",
            "injuries_or_limitations",
            "weight_kg",
            "target_weight_kg",
            "weekly_frequency",
            "rep_preference",
        ):
            if field_name in normalized and normalized[field_name] is not None:
                try:
                    normalized[field_name] = validate_answer(field_name, normalized[field_name])
                except IntakeValidationError as exc:
                    raise ValueError(str(exc)) from None
        return normalized


class WeightEntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weight_kg: float

    @model_validator(mode="before")
    @classmethod
    def validate_weight_against_intake(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "weight_kg" not in value:
            return value
        normalized = dict(value)
        try:
            normalized["weight_kg"] = validate_answer("weight_kg", normalized["weight_kg"])
        except IntakeValidationError as exc:
            raise ValueError(str(exc)) from None
        return normalized


class WeightEntryOut(BaseModel):
    entry_date: str
    weight_kg: float


class WeightTrendOut(BaseModel):
    points: list[WeightTrendPointOut]
    change_kg: float | None
    target_weight_kg: float | None


class PersonaUpdate(BaseModel):
    coach_tone: AssistantStyleKey
    custom_instructions: str = Field(default="")

    @field_validator("custom_instructions", mode="before")
    @classmethod
    def trim_assistant_style_instructions(cls, instructions: Any) -> Any:
        if not isinstance(instructions, str):
            return instructions
        trimmed = instructions.strip()
        if len(trimmed) > MAX_ASSISTANT_STYLE_INSTRUCTIONS:
            raise ValueError(
                f"Instructions must be at most {MAX_ASSISTANT_STYLE_INSTRUCTIONS} characters"
            )
        return trimmed


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


class TrainingStatusOut(BaseModel):
    """The player's Weekly streak and Checkpoint progress."""

    weekly_streak: int
    week_start: str
    week_done: int
    week_target: int
    mayos_workouts: int
    next_checkpoint: int
    workouts_to_next: int


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


class ProgramDraftInput(BaseModel):
    """Strict draft input that rejects all unknown fields."""

    model_config = ConfigDict(extra="forbid")


class ProgramDraftExerciseIn(ProgramDraftInput):
    exercise_id: str = Field(min_length=1, max_length=200)
    exercise_name: str = ""
    body_part: str | None = None
    equipment: str | None = None
    note: str | None = None
    video_url: str | None = None
    is_coach_exercise: bool = False
    slot_key: str | None = None
    warmup_sets: int = Field(default=MIN_RAMPED_WARMUP_SETS, ge=MIN_RAMPED_WARMUP_SETS, le=MAX_RAMPED_WARMUP_SETS)
    target_sets: int = DEFAULT_TARGET_SETS
    target_reps_min: int = Field(
        default=DEFAULT_TARGET_REPS_MIN,
        description=f"Lower rep bound, from {MIN_REPS} to {MAX_REPS}.",
    )
    target_reps_max: int = Field(
        default=DEFAULT_TARGET_REPS_MAX,
        description=f"Upper rep bound, from {MIN_REPS} to {MAX_REPS}.",
    )
    target_rir: float = Field(
        default=DEFAULT_TARGET_RIR,
        description=f"Target RIR, from {MIN_TARGET_RIR:g} to {MAX_TARGET_RIR:g}.",
    )
    rest_seconds: int = DEFAULT_EXERCISE_REST_SECONDS
    tempo: str | None = Field(default=None, max_length=MAX_TEMPO_LENGTH)
    notes: str | None = Field(default=None, max_length=MAX_PROGRAM_NOTES_LENGTH)
    image_path: str | None = None
    gif_path: str | None = None
    suggested_substitutes: list[SuggestedSubstitute] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_target_rpe(cls, fields: Any) -> Any:
        if not isinstance(fields, dict):
            return fields
        normalized = dict(fields)
        if "target_rir" not in normalized and "target_rpe" in normalized:
            try:
                normalized["target_rir"] = 10 - float(normalized["target_rpe"])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("target_rpe must be numeric") from exc
        normalized.pop("target_rpe", None)
        return normalized


class ProgramDraftWarmupExerciseIn(ProgramDraftInput):
    exercise_id: str | None = None
    equipment: str | None = None
    exercise_name: str
    sets: int = Field(default=DEFAULT_WARMUP_MOVEMENT_SETS, ge=MIN_WARMUP_MOVEMENT_SETS, le=MAX_WARMUP_MOVEMENT_SETS)
    reps: int = Field(default=DEFAULT_WARMUP_MOVEMENT_REPS, ge=MIN_WARMUP_MOVEMENT_REPS, le=MAX_WARMUP_MOVEMENT_REPS)
    rest_seconds: int = DEFAULT_WARMUP_MOVEMENT_REST_SECONDS
    notes: str | None = Field(default=None, max_length=MAX_PROGRAM_NOTES_LENGTH)
    image_path: str | None = None
    gif_path: str | None = None


class ProgramDraftDayIn(ProgramDraftInput):

    day_name: str = Field(default="Day 1", min_length=1, max_length=100)
    day_order: int = Field(default=1, ge=1, le=MAX_PROGRAM_DAYS)
    warmup_exercises: list[ProgramDraftWarmupExerciseIn] = Field(default_factory=list)
    exercises: list[ProgramDraftExerciseIn] = Field(default_factory=list)
    cardio: str | None = None


class CoachProgramDraftIn(ProgramDraftInput):
    program_name: str = Field(default="Custom program", min_length=1, max_length=120)
    split_type: str = "custom"
    weekly_frequency: int = Field(default=1, ge=1, le=MAX_PROGRAM_DAYS)
    instructions: str = ""
    days: list[ProgramDraftDayIn] = Field(default_factory=list, max_length=MAX_PROGRAM_DAYS)

    @model_validator(mode="before")
    @classmethod
    def strip_server_metadata(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        for field_name in ("version", "published_by_coach_account_id"):
            normalized.pop(field_name, None)
        return normalized


class CoachProgramApproveIn(BaseModel):
    expected_active_version: int = Field(ge=1)
    resolve_request_ids: list[str] = Field(default_factory=list)


class CoachProgramPublishIn(BaseModel):
    resolve_request_ids: list[str] = Field(default_factory=list)


class CoachProgramPublicationOut(PersistedProgramSchema):
    resolved_request_ids: list[str] = Field(default_factory=list)


class CoachProgramDraftOut(BaseModel):
    assignment_id: str
    draft: CoachProgramDraftIn
    created_at: str
    updated_at: str


class ProgramImportDraftRowIn(BaseModel):
    """One Coach-confirmed canonical row sent back without its file or raw cells."""

    model_config = ConfigDict(extra="forbid")

    source_row: int = Field(ge=1)
    day: Any
    day_name: Any = None
    order: Any
    exercise_name: str
    exercise_id: str = Field(min_length=1, max_length=200)
    sets: Any
    reps_min: Any
    reps_max: Any
    target_rir: Any
    rest_seconds: Any
    tempo: Any = None
    notes: Any = None


class ProgramImportCreateIn(BaseModel):
    """Coach-confirmed import rows; the uploaded file is not retained between steps."""

    model_config = ConfigDict(extra="forbid")

    program_name: str | None = Field(default=None, max_length=120)
    rows: list[ProgramImportDraftRowIn] = Field(min_length=1, max_length=MAX_PROGRAM_IMPORT_ROWS)


class CoachActiveProgramExerciseOut(PersistedProgramExerciseSchema):
    """Coach-only Exercise library labels resolved when the response is built."""

    primary_muscle: str | None = None
    primary_action: str | None = None
    equipment_category: str | None = None
    load_type: str | None = None
    coach_equipment: str | None = None


class CoachActiveProgramDayOut(PersistedProgramDaySchema):
    exercises: list[CoachActiveProgramExerciseOut] = Field(
        min_length=1,
        max_length=MAX_EXERCISES_PER_DAY,
    )


class CoachActiveProgramDetailsOut(BaseModel):
    """Active Training program content without account identity fields."""

    program_name: str
    split_type: str
    weekly_frequency: int
    instructions: str
    days: list[CoachActiveProgramDayOut]
    version: int | None = None
    provenance: Literal["automatic", "coach"]
    active_since: str | None = None


class CoachActiveProgramOut(BaseModel):
    """The active program and pending Program draft state for one assignment."""

    program: CoachActiveProgramDetailsOut | None = None
    has_draft: bool


class CoachExerciseCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    body_part: str | None = Field(default=None, max_length=80)
    equipment: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=1000)
    video_url: str | None = Field(default=None, max_length=2048)

    @field_validator("name", "body_part", "equipment", "note", "video_url", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            clean = value.strip()
            return clean or None
        return value

    @field_validator("video_url")
    @classmethod
    def require_https_video_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
            valid = parsed.scheme == "https" and bool(parsed.hostname)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Video link must use https.")
        return value


class CoachExerciseOut(BaseModel):
    id: str
    name: str
    primary_muscle: str | None = None
    primary_action: str | None = None
    secondary_actions: list[str] = Field(default_factory=list)
    body_part: str | None = None
    equipment: str | None = None
    equipment_category: str = "Other"
    load_type: str | None = None
    note: str | None = None
    video_url: str | None = None
    image_path: str | None = None
    gif_path: str | None = None
    is_coach_exercise: bool = True


class CoachExerciseSearchOut(BaseModel):
    exercises: list[CoachExerciseOut]


class ProgramSubstitutionIn(BaseModel):
    """One permanent slot swap in the player's active program."""

    day_name: str = Field(min_length=1, max_length=100)
    exercise_id: str = Field(min_length=1, max_length=200)
    replacement_exercise_id: str = Field(min_length=1, max_length=200)
    all_occurrences: bool = False
    expected_active_version: int | None = Field(default=None, ge=1)


class ProgramSubstitutionUndoIn(BaseModel):
    restore_version: int = Field(ge=1)
    expected_active_version: int = Field(ge=1)


class ActiveProgramOut(PersistedProgramSchema):
    """An active program plus the server's current Program-authority decision."""

    player_controls_program: bool


class ProgramSubstitutionOut(PersistedProgramSchema):
    previous_version: int
    player_controls_program: bool


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
    exercise_name: str | None = None
    replacement_exercise_id: str | None = None
    replacement_exercise_name: str | None = None
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
    #: Optional effort (#111): absent means "not rated". RPE 5.0-10.0 is RIR 5-0.
    rpe: float | None = Field(default=None, ge=5.0, le=10.0)
    is_warmup: bool = False


class ExerciseSetsIn(BaseModel):
    exercise: ProgramExerciseSchema
    sets: list[WorkoutSetIn] = Field(min_length=1)


class WarmupMovementSetIn(BaseModel):
    weight_kg: float | None = Field(
        default=None, ge=0.0, le=500.0, allow_inf_nan=False
    )
    reps: int = Field(ge=1, le=50)


class WarmupMovementIn(BaseModel):
    exercise_id: str | None = Field(default=None, min_length=1, max_length=64)
    equipment: str | None = Field(default=None, max_length=80)
    exercise_name: str = Field(min_length=1, max_length=120)
    sets: list[WarmupMovementSetIn] = Field(min_length=1, max_length=10)


class CardioIn(BaseModel):
    prescription: str = Field(min_length=1, max_length=500)
    minutes: int = Field(ge=1, le=600)


class SessionCommitIn(BaseModel):
    day_order: int = Field(ge=1, le=5)
    readiness: int = Field(ge=1, le=5)
    session_notes: str = Field(default="", max_length=2000)
    sets: list[ExerciseSetsIn] = Field(min_length=1)
    warmup_movements: list[WarmupMovementIn] = Field(default_factory=list)
    cardio: CardioIn | None = None

    # Offline-sync contract (ADR 020/033). When ``client_session_id`` is absent
    # the request keeps the legacy online-only behaviour; when present the
    # performed date/timezone, captured program version, and capture instant are
    # required and validated by the service.
    client_session_id: str | None = Field(default=None, max_length=64)
    performed_date: str | None = Field(default=None, max_length=10)
    performed_timezone: str | None = Field(default=None, max_length=64)
    program_version: int | None = Field(default=None, ge=0)
    captured_at: str | None = Field(default=None, max_length=64)
    captured_offline: bool = False

    @model_validator(mode="after")
    def _sync_fields_require_client_session_id(self) -> "SessionCommitIn":
        if self.client_session_id is None and (
            self.performed_date is not None
            or self.performed_timezone is not None
            or self.program_version is not None
            or self.captured_at is not None
            or self.captured_offline
        ):
            raise ValueError(
                "performed_date/performed_timezone/program_version/captured_at/captured_offline require client_session_id."
            )
        return self


class SessionPerformedDateCorrectIn(BaseModel):
    """A requested performed-date correction for one committed session (ADR 035)."""

    performed_date: str = Field(max_length=10)


class WorkoutSyncFailureIn(BaseModel):
    reason_code: WorkoutSyncFailureReason
    attempt: int = Field(ge=1, le=PROPERTY_TYPES["attempt"].maximum)


class SessionPerformedDateCorrectOut(BaseModel):
    """The result of a performed-date correction; ``changed`` is false for a no-op."""

    session_id: str
    session_date: str
    previous_date: str | None = None
    edited_at: str | None = None
    changed: bool
    corrections: list[PerformedDateCorrectionOut] = []


class BaselineSetOut(BaseModel):
    """One previous-performance set, in logged order (#122).

    Effort is RIR at the display boundary (``10 - RPE``); null when the set is
    unrated (#111).
    """

    weight_kg: float
    reps: int
    rir: float | None = None


class BaselineLastSessionOut(BaseModel):
    """The latest previous-performance session for one exercise (#122)."""

    performed_date: str
    sets: list[BaselineSetOut]


class BaselineOut(BaseModel):
    """One exercise's baseline: the aggregates a device freezes for live record checks."""

    exercise_id: str
    sessions_logged: int = Field(ge=0)
    performance_sessions_logged: int = Field(default=0, ge=0)
    max_weight_kg: float | None = None
    best_e1rm_kg: float | None = None
    best_zero_load_reps: int | None = Field(default=None, ge=1)
    last_session: BaselineLastSessionOut


class BaselinesOut(BaseModel):
    """``GET /workouts/baselines``: previous performance and strict record aggregates."""

    baselines: list[BaselineOut]


CHAT_MESSAGE_MAX_CHARS = 400


class ChatMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=CHAT_MESSAGE_MAX_CHARS)


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


class StructuredMessageOut(BaseModel):
    """Stable client-rendered copy plus its unchanged English fallback."""

    message_code: str | None = None
    message_params: dict[str, Any] = Field(default_factory=dict)
    message_fallback: str | None = None


class IntakeFieldOut(BaseModel):
    """One named onboarding decision: contract, current answer, and prefill marker."""

    name: str
    type: str
    required: bool
    allowed_values: list[str] = []
    minimum: float | None = None
    maximum: float | None = None
    minimum_length: int | None = None
    maximum_length: int | None = None
    profile_field: str
    explanation: str | None = None
    explanation_message: StructuredMessageOut | None = None
    hint: str | None = None
    hint_message: StructuredMessageOut | None = None
    examples: list[str] = []
    example_messages: list[StructuredMessageOut | None] = []
    option_descriptions: dict[str, str] = {}
    option_description_messages: dict[str, StructuredMessageOut | None] = {}
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
    program_message_metadata: StructuredMessageOut | None = None


class IntakeOut(BaseModel):
    """`GET /onboarding/intake` and the answer endpoints' updated read-back."""

    status: str
    disclosure_acknowledged: bool
    fields: list[IntakeFieldOut]
    profile_rebuild_fields: list[str] = []
    progress: IntakeProgressOut
    program: IntakeProgramOut | None = None


class IntakeConfirmOut(BaseModel):
    """`POST /onboarding/intake/confirm`: the confirmed first-program result."""

    status: str
    program_name: str | None = None
    weekly_frequency: int | None = None
    program_message: str | None = None
    program_message_metadata: StructuredMessageOut | None = None
    fields: list[IntakeFieldOut] = []


class HealthOut(BaseModel):
    status: str
    details: dict[str, Any] = {}
