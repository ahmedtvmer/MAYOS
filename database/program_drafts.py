"""Cleanup helpers for assignment-keyed Program drafts."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def discard_assignment_program_draft(
    db: Any,
    assignment_id: str,
    player_account_id: str,
    *,
    best_effort: bool = False,
) -> None:
    """Discards the draft from its Player ledger after assignment revocation."""
    try:
        player = db.get_account(player_account_id)
        if not db.is_live_account(player):
            return
        ledger_id = player["ledger_id"]
        if hasattr(db, "ledger_exists") and not db.ledger_exists(ledger_id):
            return
        with db.open_ledger(ledger_id) as ledger:
            ledger.discard_program_draft(assignment_id)
    except Exception:
        logger.exception("Could not discard Program draft for ended assignment %s", assignment_id)
        if not best_effort:
            raise
