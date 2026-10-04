"""Best-effort product events derived from committed ADR 038 metering rows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
import uuid

from service import analytics
from service.model_limits import daily_token_limit, request_limit_per_minute, utc_day_start_iso
from utils.model_downloader import configured_model_ids

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class AIRequestContext:
    account_id: str | None
    turn_id: str
    role: str
    purpose: str | None
    store: Any
    client: analytics.ClientContext
    latency_ms: int
    outcome: str
    finish_reason: str | None


@dataclass(frozen=True)
class AILimitContext:
    account_id: str
    role: str
    limit: str
    hit_id: str
    store: Any
    client: analytics.ClientContext


@dataclass(frozen=True)
class _UsageSnapshot:
    rows: list[dict[str, Any]]
    tokens_today: int
    turns_today: int
    plan: str


def _safe_models(rows: list[dict[str, Any]]) -> list[str]:
    configured = configured_model_ids()
    models = {
        model if model in configured else "other"
        for row in rows
        if (model := str(row.get("model") or ""))
    }
    return sorted(models)[:5] or ["other"]


def _account_plan(store: Any, account_id: str, role: str) -> str:
    from service.plans import CAPABILITY_COACH, CAPABILITY_LIFTER, effective_plans_for_account

    capability = {"coach": CAPABILITY_COACH, "player": CAPABILITY_LIFTER}.get(role)
    if capability is None:
        return "unknown"
    try:
        plans = effective_plans_for_account(store, store.get_account(account_id))
        plan = plans.get(capability)
        value = plan.get("plan") if isinstance(plan, dict) else None
        return value if value in analytics.AI_PLANS else "unknown"
    except Exception:
        logger.exception("Could not read the current plan for AI analytics.")
        return "unknown"


def _committed_usage_rows(context: AIRequestContext) -> list[dict[str, Any]] | None:
    account_id = context.account_id
    if not account_id:
        return None
    try:
        uuid.UUID(account_id)
    except (TypeError, ValueError):
        return None
    try:
        rows = context.store.model_usage_rows_for_turn(context.turn_id, account_id)
    except Exception:
        logger.exception("Could not read committed AI metering rows for analytics.")
        return None
    account_rows = [row for row in rows if row.get("account_id") == account_id]
    return account_rows


def _read_usage_snapshot(context: AIRequestContext) -> _UsageSnapshot | None:
    rows = _committed_usage_rows(context)
    if rows is None or context.account_id is None:
        return None
    try:
        day_start = utc_day_start_iso()
        tokens_today = context.store.sum_model_tokens_for_account(context.account_id, day_start)
        turns_today = context.store.count_model_turns_for_account(context.account_id, day_start)
    except Exception:
        logger.exception("Could not read current AI usage totals for analytics.")
        return None
    return _UsageSnapshot(
        rows=rows,
        tokens_today=tokens_today,
        turns_today=turns_today,
        plan=_account_plan(context.store, context.account_id, context.role),
    )


def _metered_properties(rows: list[dict[str, Any]]) -> dict[str, Any]:
    input_tokens = sum(row["input_tokens"] for row in rows)
    output_tokens = sum(row["output_tokens"] for row in rows)
    models = _safe_models(rows)
    return {
        "models": models,
        "model_count": len(models),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tokens": input_tokens + output_tokens,
        "cost_usd": sum(row["cost_usd"] for row in rows),
        "estimated": any(row["estimated"] for row in rows),
    }


def _scope_properties(context: AIRequestContext, snapshot: _UsageSnapshot) -> dict[str, Any]:
    use_case = context.purpose if context.purpose in analytics.AI_USE_CASES else "other"
    reason = context.finish_reason if context.finish_reason in analytics.AI_FINISH_REASONS else "unknown"
    return {
        "plan": snapshot.plan,
        "use_case": use_case,
        "latency_ms": min(max(0, int(context.latency_ms)), 31_557_600),
        "outcome": context.outcome,
        "finish_reason": reason,
    }


def _current_limit_properties(snapshot: _UsageSnapshot) -> dict[str, int]:
    return {
        "turns_today": min(max(0, snapshot.turns_today), 1_000_000),
        "requests_per_minute_limit": min(max(0, request_limit_per_minute()), 1_000_000),
        "tokens_today": min(max(0, snapshot.tokens_today), 100_000_000),
        "tokens_daily_limit": min(max(0, daily_token_limit()), 100_000_000),
    }


def _completed_event(context: AIRequestContext, snapshot: _UsageSnapshot) -> analytics.AnalyticsEvent:
    properties = _metered_properties(snapshot.rows)
    properties.update(_scope_properties(context, snapshot))
    properties.update(_current_limit_properties(snapshot))
    return analytics.AnalyticsEvent(
        account_id=context.account_id,
        event="ai_request_completed",
        domain_key=context.turn_id,
        role=context.role,
        properties=properties,
    )


def capture_ai_request_completed(context: AIRequestContext) -> None:
    """Emits one event whose token and cost values are read from persisted rows."""
    snapshot = _read_usage_snapshot(context)
    if snapshot is None:
        return
    analytics.capture(_completed_event(context, snapshot), context.client)


def capture_ai_request_limited(context: AILimitContext) -> None:
    """Emits a coded limit refusal after its durable refusal record commits."""
    mapped = {"rate": "requests_per_minute", "daily_tokens": "daily_tokens"}.get(context.limit)
    if mapped is None:
        return
    plan = _account_plan(context.store, context.account_id, context.role)
    try:
        analytics.capture(
            analytics.AnalyticsEvent(
                account_id=context.account_id,
                event="ai_request_limited",
                domain_key=context.hit_id,
                role=context.role,
                properties={"limit": mapped, "plan": plan},
            ),
            context.client,
        )
    except Exception:
        logger.exception("Could not emit the AI limit event; the refusal remains in effect.")


__all__ = ["AIRequestContext", "AILimitContext", "capture_ai_request_completed", "capture_ai_request_limited"]
