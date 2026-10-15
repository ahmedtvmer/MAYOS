"""Reproducible paired-usage replay helpers for the closed trial (#262)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from service import model_limits
from utils.model_pricing import compute_cost, price_for


def _turn_tokens(turn: dict[str, Any]) -> int:
    return sum(
        max(0, int(call.get("input_tokens", 0)))
        + max(0, int(call.get("output_tokens", 0)))
        for call in turn.get("calls", [])
    )


def _call_cost(call: dict[str, Any]) -> float | None:
    model = str(call.get("model", ""))
    if "cost_usd" in call:
        return call["cost_usd"]
    if price_for(model) is None:
        return None
    return compute_cost(
        model,
        int(call.get("input_tokens", 0)),
        int(call.get("output_tokens", 0)),
        cached_input_tokens=int(call.get("cached_input_tokens", 0)),
    )


@dataclass
class TrialReplayStore:
    """Small usage store adapter for calls to the existing admission seam."""

    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    rows: list[dict[str, Any]] = field(default_factory=list)
    limit_hits: list[dict[str, str]] = field(default_factory=list)

    def record_call(
        self, account_id: str, turn: dict[str, Any], call: dict[str, Any], turn_id: str
    ) -> None:
        self.rows.append(
            {
                "account_id": account_id,
                "role": str(turn.get("role", "unknown")),
                "purpose": turn.get("purpose"),
                "model": str(call.get("model", "")),
                "input_tokens": max(0, int(call.get("input_tokens", 0))),
                "cached_input_tokens": max(0, int(call.get("cached_input_tokens", 0))),
                "output_tokens": max(0, int(call.get("output_tokens", 0))),
                "estimated": bool(call.get("estimated", True)),
                "cost_usd": _call_cost(call),
                "turn_id": turn_id,
                "created_at": self.now.isoformat(),
            }
        )

    def sum_model_tokens_for_account(
        self, account_id: str, start_iso: str, end_iso: str | None = None
    ) -> int:
        return sum(
            row["input_tokens"] + row["output_tokens"]
            for row in self.rows
            if row["account_id"] == account_id
            and row["created_at"] >= start_iso
            and (end_iso is None or row["created_at"] < end_iso)
            and row["purpose"] != "checkpoint_review"
        )

    def record_model_limit_hit(self, account_id: str, kind: str) -> str:
        hit_id = f"hit-{len(self.limit_hits) + 1}"
        self.limit_hits.append({"account_id": account_id, "kind": kind, "id": hit_id})
        return hit_id

    def _prune_model_limit_hits(self, _cutoff: str) -> None:
        return None


def _minimum_limit(turns: list[dict[str, Any]]) -> int:
    required = 0
    prefix = 0
    for turn in turns:
        if turn.get("purpose") == "checkpoint_review":
            continue
        tokens = _turn_tokens(turn)
        required = max(required, prefix + 1)
        prefix += tokens
    return required


def _record_admitted_turn(
    store: TrialReplayStore, account_id: str, turn: dict[str, Any], index: int
) -> dict[str, Any]:
    exempt = turn.get("purpose") == "checkpoint_review"
    if not exempt:
        model_limits.admit_model_request(account_id, guard=False, db=store, now=store.now)
    turn_id = f"{account_id}:{turn.get('turn_id') or turn.get('case_id') or index}"
    for call in turn.get("calls", []):
        store.record_call(account_id, turn, call, turn_id)
    return {
        "case_id": str(turn.get("case_id", "unknown")),
        "role": str(turn.get("role", "unknown")),
        "turn_tokens": _turn_tokens(turn),
        "purpose": turn.get("purpose"),
    }


def _usage_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    countable = [row for row in rows if row["purpose"] != "checkpoint_review"]
    all_costs_known = bool(rows) and all(row["cost_usd"] is not None for row in rows)
    return {
        "daily_input_tokens": sum(row["input_tokens"] for row in countable),
        "daily_cached_input_tokens": sum(row["cached_input_tokens"] for row in countable),
        "daily_output_tokens": sum(row["output_tokens"] for row in countable),
        "daily_tokens_after_replay": sum(
            row["input_tokens"] + row["output_tokens"] for row in countable
        ),
        "daily_model_call_count": len(countable),
        "persisted_call_count": len(rows),
        "persisted_cost_usd": (
            sum(float(row["cost_usd"]) for row in rows) if all_costs_known else None
        ),
        "unpriced_call_count": sum(row["cost_usd"] is None for row in rows),
        "estimated_call_count": sum(bool(row["estimated"]) for row in rows),
    }


def _refusal(turn: dict[str, Any], index: int, usage_before: int, kind: str) -> dict[str, Any]:
    return {
        "turn_index": index,
        "case_id": str(turn.get("case_id", "unknown")),
        "role": str(turn.get("role", "unknown")),
        "kind": kind,
        "tokens_before_refusal": usage_before,
        "measured_turn_tokens": _turn_tokens(turn),
    }


def replay_trial_day(
    turns: list[dict[str, Any]], *, account_id: str, now: datetime | None = None
) -> dict[str, Any]:
    """Replays measured turns in order against the current shared trial cap.

    Each turn contains its role, purpose, case id, and all measured calls.
    Checkpoint reviews bypass admission and are excluded from the daily sum.
    """
    moment = now or datetime.now(UTC)
    store = TrialReplayStore(now=moment.astimezone(UTC))
    try:
        admitted, first_refusal = _replay_schedule(turns, account_id, store)
        return _replay_report(store, admitted, first_refusal, turns, account_id, moment)
    finally:
        model_limits.reset_model_limits()


def _replay_schedule(
    turns: list[dict[str, Any]], account_id: str, store: TrialReplayStore
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    admitted: list[dict[str, Any]] = []
    first_refusal: dict[str, Any] | None = None
    usage_before = 0
    for index, turn in enumerate(turns):
        try:
            admitted.append(_record_admitted_turn(store, account_id, turn, index))
        except model_limits.ModelLimitExceeded as exc:
            first_refusal = _refusal(turn, index, usage_before, exc.kind)
            break
        if turn.get("purpose") != "checkpoint_review":
            usage_before += _turn_tokens(turn)
    return admitted, first_refusal


def _role_counts(admitted: list[dict[str, Any]]) -> dict[str, int]:
    roles = sorted({row["role"] for row in admitted})
    return {role: sum(row["role"] == role for row in admitted) for role in roles}


def _potential_tokens(turns: list[dict[str, Any]]) -> int:
    return sum(
        _turn_tokens(turn)
        for turn in turns
        if turn.get("purpose") != "checkpoint_review"
    )


def _replay_report(
    store: TrialReplayStore,
    admitted: list[dict[str, Any]],
    first_refusal: dict[str, Any] | None,
    turns: list[dict[str, Any]],
    account_id: str,
    moment: datetime,
) -> dict[str, Any]:
    return {
        "account_id": account_id,
        "first_refusal": first_refusal,
        "admitted_turns": admitted,
        "admitted_turn_count": len(admitted),
        "admitted_role_counts": _role_counts(admitted),
        "limit_hits": store.limit_hits,
        **_replay_totals(store, turns, moment),
    }


def _replay_totals(
    store: TrialReplayStore, turns: list[dict[str, Any]], moment: datetime
) -> dict[str, Any]:
    totals = _usage_totals(store.rows)
    return {
        "day_start_utc": model_limits.utc_day_start_iso(moment),
        "daily_limit": model_limits.daily_token_limit(),
        "potential_tokens_if_all_scheduled_turns_admitted": _potential_tokens(turns),
        "minimum_limit_to_admit_all_scheduled_turns": _minimum_limit(turns),
        **totals,
    }


def decide_trial_cap(
    english_replay: dict[str, Any],
    arabic_replay: dict[str, Any],
    *,
    current_limit: int,
    ordinary_use_day: bool,
    equivalent_successful_work: bool,
) -> dict[str, Any]:
    """Applies ADR 059's Arabic-only refusal trigger to eligible day replays."""
    if not (ordinary_use_day and equivalent_successful_work):
        return _cap_decision(current_limit, "The replay is not yet an eligible ordinary-use equivalent-work day.", False)
    arabic_refusal = arabic_replay.get("first_refusal") or {}
    if arabic_refusal.get("kind") == "daily_tokens" and not english_replay.get("first_refusal"):
        return _raise_trial_cap(current_limit, arabic_replay)
    return _cap_decision(
        current_limit,
        "The accepted Arabic-only refusal trigger was not demonstrated.",
        False,
    )


def _raise_trial_cap(current_limit: int, arabic_replay: dict[str, Any]) -> dict[str, Any]:
    required_limit = int(arabic_replay.get("minimum_limit_to_admit_all_scheduled_turns", 0))
    reason = (
        "The equivalent Arabic day reaches the shared cap while the English day passes; "
        "the selected limit admits every scheduled turn under admission-time soft-cap behavior."
    )
    return _cap_decision(max(current_limit, required_limit), reason, True, decision="raise")


def _cap_decision(
    setting: int, reason: str, trigger_met: bool, *, decision: str = "retain"
) -> dict[str, Any]:
    return {
        "setting": setting,
        "decision": decision,
        "reason": reason,
        "trigger_met": trigger_met,
    }


__all__ = ["TrialReplayStore", "decide_trial_cap", "replay_trial_day"]
