"""Shared best-effort coach in-app notices (ADR 029/030/031).

A notice failure must never fail the fact it describes, so every writer routes
through :func:`notify_coach`, which swallows and logs any exception.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["notify_coach", "player_display_name"]


def player_display_name(db: Any, assignment: dict[str, Any]) -> str:
    """The player's username for a notice, or a safe generic fallback."""
    account = db.get_account(assignment["player_account_id"])
    return account["username"] if account else "A player"


def notify_coach(
    db: Any,
    assignment: dict[str, Any],
    kind: str,
    message: str,
    now_iso: str,
) -> bool:
    """Writes one coach in-app notice; returns ``False`` (never raises) on failure."""
    try:
        db.create_assignment_notice(
            assignment["coach_account_id"],
            assignment["assignment_id"],
            kind,
            message,
            now_iso,
        )
    except Exception:
        logger.exception("Coach in-app notice raised unexpectedly")
        return False
    return True
