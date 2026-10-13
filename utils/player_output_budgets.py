"""Output token budgets for calls made with the hosted player model."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal

PLAYER_CHAT_REPLY_MAX_OUTPUT_TOKENS = 200
INTENT_ROUTING_MAX_OUTPUT_TOKENS = 112
# The correctly capped #199 gate truncated all five cases at 56; retain the former ceiling.
SUBSTITUTION_RESOLUTION_MAX_OUTPUT_TOKENS = 200
ABBREVIATION_EXPANSION_MAX_OUTPUT_TOKENS = 48
# #194 peaked at 1019 tokens; retain 25% headroom now that #406 enforces the cap.
DYNAMIC_SPLIT_PLAN_MAX_OUTPUT_TOKENS = 1280
CHECKPOINT_REVIEW_MAX_OUTPUT_TOKENS = 200

PlayerCallSite = Literal[
    "chat_reply",
    "intent_routing",
    "substitution_resolution",
    "abbreviation_expansion",
    "dynamic_split_plan",
    "checkpoint_review",
]

CALL_SITE_BUDGETS: dict[PlayerCallSite, int] = {
    "chat_reply": PLAYER_CHAT_REPLY_MAX_OUTPUT_TOKENS,
    "intent_routing": INTENT_ROUTING_MAX_OUTPUT_TOKENS,
    "substitution_resolution": SUBSTITUTION_RESOLUTION_MAX_OUTPUT_TOKENS,
    "abbreviation_expansion": ABBREVIATION_EXPANSION_MAX_OUTPUT_TOKENS,
    "dynamic_split_plan": DYNAMIC_SPLIT_PLAN_MAX_OUTPUT_TOKENS,
    "checkpoint_review": CHECKPOINT_REVIEW_MAX_OUTPUT_TOKENS,
}

_BUDGET_OVERRIDES: ContextVar[Mapping[PlayerCallSite, int] | None] = ContextVar(
    "player_output_budget_overrides", default=None
)


def player_output_budget(call_site: PlayerCallSite) -> int:
    """Returns the production budget, honoring a scoped measurement override."""
    overrides = _BUDGET_OVERRIDES.get()
    if overrides is not None and call_site in overrides:
        return overrides[call_site]
    return CALL_SITE_BUDGETS[call_site]


@contextmanager
def override_player_output_budgets(
    overrides: Mapping[PlayerCallSite, int],
) -> Iterator[None]:
    """Temporarily replaces selected budgets in the current context."""
    token = _BUDGET_OVERRIDES.set(overrides)
    try:
        yield
    finally:
        _BUDGET_OVERRIDES.reset(token)
