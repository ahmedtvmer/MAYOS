"""Stable, additive structured messages for coach alerts."""

from __future__ import annotations

import math
from collections.abc import Mapping
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


def coach_alert_message(kind: Any, evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Build allowlisted metadata and a safe English fallback for one alert."""
    builder = _COACH_ALERT_BUILDERS.get(kind) if isinstance(kind, str) else None
    if builder is None:
        return _build_alert_message(None, {}, "Alert details are unavailable.")
    return builder(evidence)


def _build_alert_message(
    code: str | None, params: dict[str, Any], fallback: str
) -> dict[str, Any]:
    if code is not None:
        allowlist = COACH_ALERT_MESSAGE_PARAM_ALLOWLISTS.get(code)
        if allowlist is None or not params.keys() <= allowlist:
            code, params = None, {}
    return {
        "message_code": code,
        "message_params": params,
        "message_fallback": fallback,
    }


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
        return _build_alert_message(None, {}, fallback)
    return _build_alert_message(
        "coach_alert.missed_expected_days.v1",
        {"count": count, "start_date": start, "end_date": end},
        fallback,
    )


def _follow_up(evidence: Mapping[str, Any]) -> dict[str, Any]:
    due_on = _alert_date(evidence.get("due_on"))
    fallback = f"Follow-up due since {due_on or 'an earlier date'}"
    if due_on is None:
        return _build_alert_message(None, {}, fallback)
    return _build_alert_message("coach_alert.follow_up_due.v1", {"due_on": due_on}, fallback)


def _stall(evidence: Mapping[str, Any]) -> dict[str, Any]:
    count = _alert_count(evidence.get("stall_length"))
    started = _alert_date(evidence.get("window_start_date"))
    fallback = (
        f"Stalling — {count if count is not None else 0} sessions without a "
        f"personal record (since {started or 'an earlier date'})"
    )
    if count is None:
        return _build_alert_message(None, {}, fallback)
    return _build_alert_message(
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
        return _build_alert_message(None, {}, fallback)
    if choice is not None and not valid_choice:
        return _build_alert_message(None, {}, fallback)
    return _build_alert_message(
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
        return _build_alert_message(None, {}, fallback)
    return _build_alert_message(
        "coach_alert.performance_regression.v1",
        {"exercise_name": safe_name, "e1rm_delta": delta, "status_badge": safe_badge},
        fallback,
    )


def _profile_change(evidence: Mapping[str, Any]) -> dict[str, Any]:
    changes = evidence.get("profile_changes")
    if not isinstance(changes, Mapping):
        return _build_alert_message(None, {}, "Training profile changed.")
    fields = [field for field in _PROFILE_FIELDS if field in changes]
    if not fields:
        return _build_alert_message(None, {}, "Training profile changed.")
    return _build_alert_message(
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
