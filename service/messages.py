"""Stable structured messages for API errors, coach alerts, and intake copy."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

_REGRESSION_BADGES = {
    "BASELINE",
    "CONSOLIDATING",
    "GRADUATED",
    "LOAD INCREASE",
    "OVERSHOOT",
    "REP OVERLOAD",
    "regression",
}
_DELOAD_REASONS = {
    "rolling_readiness_crash",
    "acute_readiness_floor",
    "high_exertion_density",
}
_PROFILE_FIELDS = ("injuries_or_limitations", "equipment_access")
COACH_ALERT_MESSAGE_PARAM_ALLOWLISTS = {
    "coach_alert.missed_expected_days.v1": frozenset(
        {"count", "start_date", "end_date"}
    ),
    "coach_alert.follow_up_due.v1": frozenset({"due_on"}),
    "coach_alert.stall.v1": frozenset({"count", "window_start_date"}),
    "coach_alert.deload_recommended.v1": frozenset(
        {"reason_code", "recent_readiness_avg", "choice"}
    ),
    "coach_alert.performance_regression.v1": frozenset(
        {"exercise_name", "e1rm_delta", "status_badge"}
    ),
    "coach_alert.profile_change.v1": frozenset({"changed_fields"}),
}
ERROR_MESSAGE_PARAM_ALLOWLISTS = {
    "http.bad_request.v1": frozenset(),
    "http.unauthorized.v1": frozenset(),
    "http.forbidden.v1": frozenset(),
    "http.not_found.v1": frozenset(),
    "http.conflict.v1": frozenset(),
    "http.validation_failed.v1": frozenset(),
    "http.input_too_long.v1": frozenset({"limit"}),
    "http.rate_limited.v1": frozenset(),
    "http.server_error.v1": frozenset(),
    "http.request_failed.v1": frozenset(),
    "ai_limit.request_rate.v1": frozenset(),
    "ai_limit.daily_usage.v1": frozenset(),
    "chat.failed.v1": frozenset(),
    "google.account_already_linked.v1": frozenset(),
    "google.invalid_token.v1": frozenset(),
    "google.linked_elsewhere.v1": frozenset(),
    "google.different_account.v1": frozenset(),
    "google.unlink_password_required.v1": frozenset(),
    "workout.program_version_mismatch.v1": frozenset(),
    "auth.invalid_credentials.v1": frozenset(),
    "auth.username_taken.v1": frozenset(),
    "auth.invalid_or_expired_token.v1": frozenset(),
    "auth.invalid_signup_ticket.v1": frozenset(),
    "auth.signup_ticket_missing.v1": frozenset(),
    "recovery.invalid_or_expired_code.v1": frozenset(),
    "recovery.code_send_limit.v1": frozenset(),
    "recovery.invalid_or_expired_token.v1": frozenset(),
    "coach_invite.invalid_code.v1": frozenset(),
    "assignment.none_active.v1": frozenset(),
    "assignment.invite_invalid.v1": frozenset(),
    "assignment.self_assignment.v1": frozenset(),
    "assignment.already_assigned.v1": frozenset(),
    "assignment.consent_required.v1": frozenset(),
    "assignment.roster_full.v1": frozenset(),
    "assignment.request_invalid.v1": frozenset(),
    "assignment.coach_roster_full.v1": frozenset(),
    "assignment.coach_capability_required.v1": frozenset(),
    "assignment.coach_profile_required.v1": frozenset(),
    "assignment.invite_lifetime_invalid.v1": frozenset(),
    "assignment.not_participant.v1": frozenset(),
    "assignment.already_ended.v1": frozenset(),
    "assignment.program_draft_exists.v1": frozenset(),
    "assignment.program_draft_changed.v1": frozenset(),
    "assignment.program_draft_invalid.v1": frozenset(),
    "assignment.check_in_invalid.v1": frozenset(),
    "assignment.not_found.v1": frozenset(),
    "assignment.program_draft_not_found.v1": frozenset(),
    "assignment.notice_not_found.v1": frozenset(),
    "program.no_active.v1": frozenset(),
    "program.coach_controls.v1": frozenset(),
    "program.substitution.day_not_found.v1": frozenset(),
    "program.substitution.source_not_on_day.v1": frozenset(),
    "program.substitution.replacement_is_source.v1": frozenset(),
    "program.substitution.replacement_not_found.v1": frozenset(),
    "program.substitution.replacement_already_on_day.v1": frozenset(),
    "program.substitution.restore_version_not_found.v1": frozenset(),
    "program.substitution.changed.v1": frozenset(),
    "program_request.invalid_kind.v1": frozenset(),
    "program_request.reason_required.v1": frozenset(),
    "program_request.reason_too_long.v1": frozenset({"limit"}),
    "program_request.direct_change.v1": frozenset(),
    "program_request.no_active_program.v1": frozenset(),
    "program_request.target_incomplete.v1": frozenset(),
    "program_request.same_replacement.v1": frozenset(),
    "program_request.day_not_in_program.v1": frozenset(),
    "program_request.exercise_not_in_day.v1": frozenset(),
    "program_request.replacement_not_found.v1": frozenset(),
    "program_request.frequency_invalid.v1": frozenset(),
    "program_request.split_too_long.v1": frozenset({"limit"}),
    "program_request.not_found.v1": frozenset(),
    "program_request.not_pending.v1": frozenset(),
    "program_request.stale.v1": frozenset(),
    "program_request.response_required.v1": frozenset(),
    "program_request.response_too_long.v1": frozenset({"limit"}),
    "program_request.selection_invalid.v1": frozenset(),
    "intake.structured_active.v1": frozenset(),
    "intake.in_progress.v1": frozenset(),
    "intake.program_generation_unavailable.v1": frozenset(),
    "coach.ai_unavailable.v1": frozenset(),
    "media.unavailable.v1": frozenset(),
    "media.not_found.v1": frozenset(),
}
INTAKE_COPY_MESSAGE_PARAM_ALLOWLISTS: dict[str, frozenset[str]] = {}
MESSAGE_PARAM_ALLOWLISTS = {
    **COACH_ALERT_MESSAGE_PARAM_ALLOWLISTS,
    **ERROR_MESSAGE_PARAM_ALLOWLISTS,
}


def register_intake_copy_message_allowlists(
    allowlists: Mapping[str, frozenset[str]],
) -> None:
    """Adds intake codes after spec loading without importing intake here."""
    INTAKE_COPY_MESSAGE_PARAM_ALLOWLISTS.update(allowlists)
    MESSAGE_PARAM_ALLOWLISTS.update(allowlists)

_HTTP_STATUS_CODES = {
    400: "http.bad_request.v1",
    401: "http.unauthorized.v1",
    403: "http.forbidden.v1",
    404: "http.not_found.v1",
    409: "http.conflict.v1",
    422: "http.validation_failed.v1",
    429: "http.rate_limited.v1",
}
_HTTP_FALLBACKS = {
    400: "The request could not be completed.",
    401: "The request was not authorized.",
    403: "You do not have permission to do that.",
    404: "The requested item was not found.",
    409: "The request conflicts with the current state.",
    422: "The request contains invalid fields.",
    429: "Too many requests. Please try again later.",
}
PROGRAM_VERSION_MISMATCH_DETAIL = (
    "This workout was logged against an older program version."
)
_POSITIVE_LIMIT_CODES = frozenset(
    {
        "http.input_too_long.v1",
        "program_request.reason_too_long.v1",
        "program_request.split_too_long.v1",
        "program_request.response_too_long.v1",
    }
)


@dataclass(frozen=True)
class MessageMetadata:
    """Source-selected code, allowlisted values, and preserved business code."""

    code: str | None = None
    params: Mapping[str, Any] = field(default_factory=dict)
    business_code: str | None = None


def structured_message(
    code: str | None, params: Mapping[str, Any], fallback: str
) -> dict[str, Any]:
    """Builds one safe additive message after checking its per-code values."""
    allowlist = MESSAGE_PARAM_ALLOWLISTS.get(code) if code is not None else None
    if (
        code is None
        or allowlist is None
        or params.keys() != allowlist
        or not _valid_message_params(code, params)
    ):
        return {"message_code": None, "message_params": {}, "message_fallback": fallback}
    return {
        "message_code": code,
        "message_params": dict(params),
        "message_fallback": fallback,
    }


def _valid_message_params(code: str, params: Mapping[str, Any]) -> bool:
    if code in _POSITIVE_LIMIT_CODES:
        limit = params.get("limit")
        return type(limit) is int and 0 < limit <= 10000
    return True


def http_error_message(
    status_code: int,
    fallback: Any = None,
    *,
    validation_errors: Any = None,
    message_metadata: MessageMetadata | None = None,
) -> dict[str, Any]:
    """Returns generic HTTP metadata, plus a safe chat-input size when known."""
    safe_fallback = fallback if isinstance(fallback, str) and fallback else None
    code, params = _http_message_template(status_code, validation_errors)
    if message_metadata is not None and message_metadata.code is not None:
        code = message_metadata.code
        params = dict(message_metadata.params)
    english = safe_fallback or _HTTP_FALLBACKS.get(
        status_code, "The request failed. Please try again."
    )
    error_metadata = structured_message(code, params, english)
    if message_metadata is not None and message_metadata.business_code is not None:
        error_metadata["code"] = message_metadata.business_code
    return error_metadata


def _http_message_template(
    status_code: int,
    validation_errors: Any,
) -> tuple[str, dict[str, Any]]:
    if status_code == 422:
        limit = _max_length_constraint(validation_errors)
        if limit is not None:
            return "http.input_too_long.v1", {"limit": limit}
    if status_code >= 500:
        return "http.server_error.v1", {}
    return _HTTP_STATUS_CODES.get(status_code, "http.request_failed.v1"), {}


def ai_limit_message(kind: str, fallback: str) -> dict[str, Any]:
    """Returns metadata for one of the stable per-account AI refusal classes."""
    code = (
        "ai_limit.daily_usage.v1"
        if kind == "daily_tokens"
        else "ai_limit.request_rate.v1"
    )
    return structured_message(code, {}, fallback)


def chat_error_message(fallback: str) -> dict[str, Any]:
    return structured_message("chat.failed.v1", {}, fallback)


def program_version_mismatch_message(
    fallback: str = PROGRAM_VERSION_MISMATCH_DETAIL,
) -> dict[str, Any]:
    return structured_message("workout.program_version_mismatch.v1", {}, fallback)


def _max_length_constraint(errors: Any) -> int | None:
    if not isinstance(errors, (list, tuple)):
        return None
    for error in errors:
        if not isinstance(error, Mapping):
            continue
        context = error.get("ctx")
        if not isinstance(context, Mapping):
            continue
        limit = context.get("max_length")
        if type(limit) is int and limit > 0:
            return limit
    return None


def coach_alert_message(kind: Any, evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Build allowlisted metadata and a safe English fallback for one alert."""
    builder = _COACH_ALERT_BUILDERS.get(kind) if isinstance(kind, str) else None
    if builder is None:
        return structured_message(None, {}, "Alert details are unavailable.")
    return builder(evidence)


def _alert_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed.isoformat() == value else None


def _alert_count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _alert_number(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _missed_days(evidence: Mapping[str, Any]) -> dict[str, Any]:
    count = _alert_count(evidence.get("missed_count"))
    start = _alert_date(evidence.get("streak_start_date"))
    end = _alert_date(evidence.get("last_missed_date"))
    fallback = (
        f"Missed {count if count is not None else 0} expected training "
        f"{'day' if count == 1 else 'days'} ({start or '?'} to {end or '?'})"
    )
    if count is None or start is None or end is None:
        return structured_message(None, {}, fallback)
    return structured_message(
        "coach_alert.missed_expected_days.v1",
        {"count": count, "start_date": start, "end_date": end},
        fallback,
    )


def _follow_up(evidence: Mapping[str, Any]) -> dict[str, Any]:
    due_on = _alert_date(evidence.get("due_on"))
    fallback = f"Follow-up due since {due_on or 'an earlier date'}"
    if due_on is None:
        return structured_message(None, {}, fallback)
    return structured_message("coach_alert.follow_up_due.v1", {"due_on": due_on}, fallback)


def _stall(evidence: Mapping[str, Any]) -> dict[str, Any]:
    count = _alert_count(evidence.get("stall_length"))
    started = _alert_date(evidence.get("window_start_date"))
    fallback = (
        f"Stalling — {count if count is not None else 0} sessions without a "
        f"personal record (since {started or 'an earlier date'})"
    )
    if count is None:
        return structured_message(None, {}, fallback)
    return structured_message(
        "coach_alert.stall.v1",
        {"count": count, "window_start_date": started},
        fallback,
    )


def _deload(evidence: Mapping[str, Any]) -> dict[str, Any]:
    reason_code = evidence.get("reason_code")
    details = evidence.get("player_deload_choice")
    choice = details.get("choice") if isinstance(details, Mapping) else None
    reason = evidence.get("reason")
    safe_reason = reason if isinstance(reason, str) and reason else "Systemic fatigue"
    fallback = f"Deload recommended — {safe_reason}"
    valid_choice = isinstance(choice, str) and choice in {"undo", "apply"}
    if valid_choice:
        fallback += f" · Player chose to {choice} it for the next workout only"
    readiness = _alert_number(evidence.get("recent_readiness_avg"))
    if (
        not isinstance(reason_code, str)
        or reason_code not in _DELOAD_REASONS
        or readiness is None
    ):
        return structured_message(None, {}, fallback)
    if choice is not None and not valid_choice:
        return structured_message(None, {}, fallback)
    return structured_message(
        "coach_alert.deload_recommended.v1",
        {
            "reason_code": reason_code,
            "recent_readiness_avg": readiness,
            "choice": choice,
        },
        fallback,
    )


def _regression(evidence: Mapping[str, Any]) -> dict[str, Any]:
    name = evidence.get("exercise_name")
    valid_name = isinstance(name, str) and bool(name)
    safe_name = name if valid_name else "Exercise"
    delta = _alert_number(evidence.get("e1rm_delta"))
    badge = evidence.get("status_badge")
    valid_badge = isinstance(badge, str) and badge in _REGRESSION_BADGES
    safe_badge = badge if valid_badge else "regression"
    fallback_delta = "?" if delta is None else f"{'−' if delta < 0 else '+'}{abs(delta):.1f}"
    fallback = f"Performance regression — {safe_name}: e1RM {fallback_delta} kg ({safe_badge})"
    if not valid_name or delta is None or not valid_badge:
        return structured_message(None, {}, fallback)
    return structured_message(
        "coach_alert.performance_regression.v1",
        {"exercise_name": safe_name, "e1rm_delta": delta, "status_badge": safe_badge},
        fallback,
    )


def _profile_change(evidence: Mapping[str, Any]) -> dict[str, Any]:
    changes = evidence.get("profile_changes")
    if not isinstance(changes, Mapping):
        return structured_message(None, {}, "Training profile changed.")
    fields = [field for field in _PROFILE_FIELDS if field in changes]
    if not fields:
        return structured_message(None, {}, "Training profile changed.")
    return structured_message(
        "coach_alert.profile_change.v1",
        {"changed_fields": fields},
        "Training profile changed.",
    )


_COACH_ALERT_BUILDERS: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    "missed_expected_days": _missed_days,
    "follow_up_due": _follow_up,
    "stall": _stall,
    "deload_recommended": _deload,
    "performance_regression": _regression,
    "profile_change": _profile_change,
}
