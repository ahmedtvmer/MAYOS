"""Server-owned Lifter and Coach plan state, keyed by the immutable account id.

Plans are capability-scoped: an account that can train has a Lifter plan and an
account that can coach has a Coach plan, independent of each other. Eligibility
comes only from the durable registry capabilities, never from a client-supplied
role or username.

An eligible capability with no stored plan is on the ongoing Free plan: the
service computes that default, so no write happens on a read and a client can
never assert its own entitlement. `effective_coach_plan` applies the configured
closed-trial override without changing the stored plan. `set_plan` records
server-verified plan grants; it is not an HTTP route and adds no billing or
payment path.
"""

from typing import Any

from utils.env_flags import env_flag

CAPABILITY_LIFTER = "lifter"
CAPABILITY_COACH = "coach"
CAPABILITIES = (CAPABILITY_LIFTER, CAPABILITY_COACH)

PLAN_FREE = "free"
PLAN_PRO = "pro"
PLANS = (PLAN_FREE, PLAN_PRO)

DEFAULT_STATUS = "active"
COACH_CLOSED_TRIAL_OVERRIDE_ENV = "COACH_CLOSED_TRIAL_OVERRIDE"

# Which durable capability makes a plan eligible for an account.
_CAPABILITY_FLAG = {
    CAPABILITY_LIFTER: "is_player",
    CAPABILITY_COACH: "is_coach",
}


def plans_for_account(db: Any, account: dict[str, Any] | None) -> dict[str, dict[str, Any] | None]:
    """Resolves both plan states for a durable account row.

    A capability the account does not hold yields ``None``; an eligible
    capability defaults to the ongoing Free plan unless a stored override says
    otherwise.
    """
    if not db.is_live_account(account):
        return {CAPABILITY_LIFTER: None, CAPABILITY_COACH: None}
    stored = {row["capability"]: row for row in db.list_plans(account["account_id"])}
    plans: dict[str, dict[str, Any] | None] = {}
    for capability, flag in _CAPABILITY_FLAG.items():
        if not account[flag]:
            plans[capability] = None
            continue
        override = stored.get(capability)
        if override is not None and override["plan"] == PLAN_PRO:
            plans[capability] = {"plan": PLAN_PRO, "status": override["status"]}
        else:
            plans[capability] = {"plan": PLAN_FREE, "status": DEFAULT_STATUS}
    return plans


def read_plans(db: Any, account_id: str) -> dict[str, dict[str, Any] | None]:
    """Reads both plan states by immutable account id, failing closed to ``None``."""
    return plans_for_account(db, db.get_account(account_id))


def effective_coach_plan(
    db: Any,
    account: dict[str, Any] | None,
    *,
    stored_plans: dict[str, dict[str, Any] | None] | None = None,
) -> str | None:
    """Returns the stored Coach plan unless the closed-trial override grants Pro."""
    if not db.is_live_account(account) or not account["is_coach"]:
        return None
    if env_flag(COACH_CLOSED_TRIAL_OVERRIDE_ENV, True):
        return PLAN_PRO
    plans = stored_plans if stored_plans is not None else plans_for_account(db, account)
    coach_plan = plans[CAPABILITY_COACH]
    return coach_plan["plan"] if coach_plan is not None else None


def effective_plans_for_account(db: Any, account: dict[str, Any] | None) -> dict[str, dict[str, Any] | None]:
    """Returns account plans with the Coach plan's closed-trial entitlement applied."""
    plans = plans_for_account(db, account)
    coach_plan = effective_coach_plan(db, account, stored_plans=plans)
    if coach_plan is not None and plans[CAPABILITY_COACH] is not None:
        plans[CAPABILITY_COACH]["plan"] = coach_plan
    return plans


def set_plan(
    db: Any,
    account_id: str,
    capability: str,
    plan: str,
    status: str = DEFAULT_STATUS,
) -> dict[str, Any]:
    """Records a server-verified plan state for one capability.

    Refuses an unknown capability/plan or an account that does not hold the
    matching capability, so an entitlement can never be attached to a
    capability the account lacks.
    """
    if capability not in CAPABILITIES or plan not in PLANS:
        return {"ok": False, "error": "Unknown capability or plan."}
    account = db.get_account(account_id)
    if not db.is_live_account(account):
        return {"ok": False, "error": "Account not found."}
    if not account[_CAPABILITY_FLAG[capability]]:
        return {"ok": False, "error": f"{capability.capitalize()} capability required."}
    db.set_plan(account_id, capability, plan, status)
    return {"ok": True, "plans": plans_for_account(db, account)}
