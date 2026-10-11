"""Coach-owned settings that apply to roster signals."""

from __future__ import annotations

from typing import Any

DEFAULT_STALL_THRESHOLD_WEEKS = 3


def get_settings(db: Any, coach_account_id: str) -> dict[str, int] | None:
    """Reads settings only for a live Coach account with a coach profile."""
    account = db.get_account(coach_account_id)
    if not db.is_live_account(account) or not account.get("is_coach"):
        return None
    weeks = db.get_coach_stall_threshold(coach_account_id)
    if weeks is None:
        return None
    return {"stall_threshold_weeks": weeks}


def update_settings(
    db: Any, coach_account_id: str, stall_threshold_weeks: int
) -> dict[str, int] | None:
    """Stores a bounded calendar-week threshold for the authenticated Coach."""
    account = db.get_account(coach_account_id)
    if not db.is_live_account(account) or not account.get("is_coach"):
        return None
    weeks = int(stall_threshold_weeks)
    if not db.set_coach_stall_threshold(coach_account_id, weeks):
        return None
    return {"stall_threshold_weeks": weeks}
