"""Capability-scoped completed-answer and resource entitlements (#66/#67)."""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, NoReturn

from database.registry.model_usage import AllowanceReservation
from utils.env_flags import env_flag
from utils.utc_day import utc_day_bounds

LAUNCH_ALLOWANCES_ENABLED_ENV = "AI_LAUNCH_ALLOWANCES_ENABLED"
_CAPABILITY_PREFIX = {"lifter": "LIFTER", "coach": "COACH"}
Capability = Literal["lifter", "coach"]

# Structured, owner-reviewed program work stays metered, but its launch sizing
# is deferred to #263 and it does not consume Coach allowance admission.
COACH_ALLOWANCE_EXCLUDED_PURPOSES = frozenset(
    {"coach_program_import", "coach_program_request"}
)


@dataclass(frozen=True)
class CapabilityAllowanceQuery:
    account_id: str
    capability: Capability
    plan: str
    now: datetime | None = None
    projected_completed_turn_id: str | None = None


@dataclass(frozen=True)
class AllowanceTurn:
    account_id: str
    capability: Capability
    turn_id: str
    purpose: str | None


def launch_allowances_enabled() -> bool:
    """Launch entitlements stay off during the closed trial."""
    return env_flag(LAUNCH_ALLOWANCES_ENABLED_ENV, False)


def _configured_limit(
    capability: Literal["lifter", "coach"],
    plan: str,
    kind: Literal["requests", "resource_tokens"],
) -> int:
    prefix = _CAPABILITY_PREFIX.get(capability)
    if prefix is None or plan not in {"free", "pro"}:
        raise ValueError("Unknown AI allowance capability or plan.")
    suffix = "REQUESTS" if kind == "requests" else "RESOURCE_TOKENS"
    name = f"{prefix}_AI_{plan.upper()}_DAILY_{suffix}"
    raw = os.getenv(name)
    if raw is None:
        raise RuntimeError(f"{name} must be configured when launch AI allowances are enabled.")
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value


def _day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    return utc_day_bounds(now)


def lifter_plan(db: Any, account_id: str) -> str:
    return capability_plan(db, account_id, "lifter")


def coach_plan(db: Any, account_id: str) -> str:
    return capability_plan(db, account_id, "coach")


def capability_plan(db: Any, account_id: str, capability: Capability) -> str:
    from service.plans import (
        CAPABILITY_LIFTER,
        effective_coach_plan,
        plans_for_account,
    )

    account = db.get_account(account_id)
    if capability == "coach":
        plan = effective_coach_plan(db, account)
        return str(plan or "free")
    plan = plans_for_account(db, account).get(CAPABILITY_LIFTER)
    if plan is None:
        # A missing stored grant means Free, and a transient plan lookup gap
        # must not turn an otherwise completed assistant answer into an error.
        return "free"
    return str(plan["plan"])


def get_lifter_allowance(
    db: Any,
    account_id: str,
    plan: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    return get_capability_allowance(
        db,
        CapabilityAllowanceQuery(account_id, "lifter", plan, now),
    )


def get_coach_allowance(
    db: Any,
    account_id: str,
    plan: str,
    *,
    now: datetime | None = None,
    projected_completed_turn_id: str | None = None,
) -> dict[str, Any]:
    return get_capability_allowance(
        db,
        CapabilityAllowanceQuery(
            account_id,
            "coach",
            plan,
            now,
            projected_completed_turn_id,
        ),
    )


def get_capability_allowance(
    db: Any,
    query: CapabilityAllowanceQuery,
) -> dict[str, Any]:
    """Returns durable capability state, using the shared trial policy until launch."""
    start, reset = _day_bounds(query.now)
    if not launch_allowances_enabled():
        return _trial_allowance(db, query.account_id, start, reset)
    return _launch_allowance(db, query, start, reset)


def _trial_allowance(
    db: Any, account_id: str, start: datetime, reset: datetime
) -> dict[str, Any]:
    from service.model_limits import daily_token_limit, utc_day_start_iso

    return {
        "mode": "trial",
        "status": "trial",
        "request_limit": None,
        "requests_used": None,
        "requests_remaining": None,
        "resource_limit": daily_token_limit(),
        "resource_used": db.sum_model_tokens_for_account(
            account_id, utc_day_start_iso(start)
        ),
        "reset_at": reset.isoformat(),
    }


def _launch_allowance(
    db: Any,
    query: CapabilityAllowanceQuery,
    start: datetime,
    reset: datetime,
) -> dict[str, Any]:
    request_limit = _configured_limit(query.capability, query.plan, "requests")
    resource_limit = _configured_limit(query.capability, query.plan, "resource_tokens")
    usage = db.ai_allowance_usage(
        query.account_id,
        query.capability,
        now=start,
        projected_completed_turn_id=query.projected_completed_turn_id,
    )
    remaining = max(0, request_limit - usage["requests_used"])
    return {
        "mode": "launch",
        "status": _allowance_status(remaining, usage["resource_used"], resource_limit),
        "request_limit": request_limit,
        "requests_used": usage["requests_used"],
        "requests_remaining": remaining,
        "resource_limit": resource_limit,
        "resource_used": usage["resource_used"],
        "reset_at": reset.isoformat(),
    }


def _allowance_status(remaining: int, resource_used: int, resource_limit: int) -> str:
    if remaining == 0:
        return "requests_exhausted"
    if resource_used >= resource_limit:
        return "resource_cutoff"
    if resource_used * 5 >= resource_limit * 4:
        return "warning"
    return "available"


def admit_lifter_turn(
    db: Any,
    account_id: str,
    turn_id: str,
    purpose: str | None,
) -> bool:
    return admit_capability_turn(
        db, AllowanceTurn(account_id, "lifter", turn_id, purpose)
    )


def admit_coach_turn(
    db: Any,
    account_id: str,
    turn_id: str,
    purpose: str | None,
) -> bool:
    return admit_capability_turn(
        db, AllowanceTurn(account_id, "coach", turn_id, purpose)
    )


def admit_capability_turn(
    db: Any,
    request: AllowanceTurn,
) -> bool:
    """Reserves one completed-answer slot and checks its capability resources."""
    if (
        request.capability == "lifter"
        and request.purpose == "checkpoint_review"
    ) or (
        request.capability == "coach"
        and request.purpose in COACH_ALLOWANCE_EXCLUDED_PURPOSES
    ) or not launch_allowances_enabled():
        return False
    return _reserve_capability_turn(db, request)


def _reserve_capability_turn(db: Any, request: AllowanceTurn) -> bool:
    effective_plan = capability_plan(db, request.account_id, request.capability)
    request_limit = _configured_limit(request.capability, effective_plan, "requests")
    resource_limit = _configured_limit(request.capability, effective_plan, "resource_tokens")
    result = db.reserve_ai_allowance_turn(
        AllowanceReservation(
            account_id=request.account_id,
            capability=request.capability,
            purpose=request.purpose,
            turn_id=request.turn_id,
            request_limit=request_limit,
            resource_limit=resource_limit,
        )
    )
    if result["refusal"] is not None:
        _raise_allowance_refusal(
            result["refusal"], result, request_limit, request.capability
        )
    return True


def _raise_allowance_refusal(
    refusal: str,
    state: dict[str, Any],
    request_limit: int,
    capability: Capability,
) -> NoReturn:
    from service.model_limits import ModelLimitExceeded

    reset_at = str(state["reset_at"])
    remaining = max(0, request_limit - int(state["requests_used"]))
    code, params, detail = _allowance_refusal_message(
        refusal, remaining, reset_at, capability
    )
    raise ModelLimitExceeded(
        detail,
        refusal,
        message_code=code,
        message_params=params,
    )


def _allowance_refusal_message(
    refusal: str, remaining: int, reset_at: str, capability: Capability = "lifter"
) -> tuple[str, dict[str, Any], str]:
    date = reset_at[:10]
    label = "Lifter" if capability == "lifter" else "Coach"
    if refusal == "resource_cutoff":
        code = "ai_allowance.resource_cutoff.v1"
        params = {"remaining_requests": remaining, "reset_at": reset_at}
    elif refusal == "request_in_progress":
        code = "ai_allowance.request_in_progress.v1"
        params = {"remaining_requests": remaining, "reset_at": reset_at}
    else:
        code = "ai_allowance.requests_exhausted.v1"
        params = {"remaining_requests": 0, "reset_at": reset_at}
    detail = _allowance_refusal_detail(refusal, remaining, date, label)
    return code, params, detail


def _allowance_refusal_detail(
    refusal: str, remaining: int, date: str, label: str
) -> str:
    if refusal == "resource_cutoff":
        return (
            f"The daily {label} resource limit has been reached. "
            f"{_request_remaining_phrase(remaining)}. "
            f"The allowance resets at {date} 00:00 UTC."
        )
    if refusal == "request_in_progress":
        return f"All remaining daily {label} requests are currently in progress. Please retry shortly."
    return f"The daily {label} request allowance is exhausted. It resets at {date} 00:00 UTC."


def _request_remaining_phrase(remaining: int) -> str:
    request = "request" if remaining == 1 else "requests"
    verb = "remains" if remaining == 1 else "remain"
    return f"{remaining} {request} {verb}"


def finish_allowance_turn(
    db: Any,
    turn_id: str,
    outcome: Literal["completed", "failed", "interrupted", "truncated"],
) -> None:
    """Persists the final outcome for a previously reserved assistant turn."""
    db.finish_ai_allowance_turn(turn_id, outcome)
