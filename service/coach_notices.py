"""Shared best-effort coach in-app notices (ADR 029/030/031).

A notice failure must never fail the fact it describes, so every writer routes
through :func:`notify_coach`, which swallows and logs any exception.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from database.registry.assignments import AssignmentNoticeRecord
from service.messages import structured_message

logger = logging.getLogger(__name__)

__all__ = ["build_assignment_notice_record", "notify_coach", "player_display_name"]


def build_assignment_notice_record(
    notice: AssignmentNoticeRecord,
    message_code: str,
    message_params: dict[str, Any],
    message_fallback: str | None = None,
) -> AssignmentNoticeRecord:
    """Builds a notice record with allowlisted metadata and its safe fallback."""
    fallback = notice.message if message_fallback is None else message_fallback
    metadata = structured_message(message_code, message_params, fallback)
    return replace(
        notice,
        message_code=metadata["message_code"],
        message_params=metadata["message_params"],
        message_fallback=metadata["message_fallback"],
    )


def player_display_name(db: Any, assignment: dict[str, Any]) -> str:
    """The player's username for a notice, or a safe generic fallback."""
    account = db.get_account(assignment["player_account_id"])
    return account["username"] if account else "A player"


def notify_coach(db: Any, notice: AssignmentNoticeRecord) -> bool:
    """Writes one coach in-app notice; returns ``False`` (never raises) on failure."""
    try:
        db.create_assignment_notice_record(notice)
    except Exception:
        logger.exception("Coach in-app notice raised unexpectedly")
        return False
    return True
