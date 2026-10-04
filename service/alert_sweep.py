"""The hourly alert sweep coordinator (ADR 030/031).

Runs both alert evaluators across every active assignment: the missed-day
evaluation (which may mount the player ledger) and the catalog-only follow-up
evaluation. One player's failure is logged and never stops the sweep.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from service import account_deletion as account_deletion_service
from service.check_ins import evaluate_follow_up
from service.missed_day_alerts import evaluate_assignment

logger = logging.getLogger(__name__)

__all__ = ["run_sweep"]


def run_sweep(db: Any, now: datetime | None = None) -> dict[str, int]:
    """Evaluates every active assignment; one player's failure never stops the sweep.

    Missed-day evaluation opens the player's ledger as an explicit handle (closing
    it when done); follow-up evaluation is catalog-only and runs even when the
    missed-day pass skipped or failed, so a due follow-up still fires without a
    ledger (ADR 031).
    """
    now = now or datetime.now(UTC)
    counts = {
        "evaluated": 0,
        "skipped": 0,
        "alerts_created": 0,
        "alerts_resolved": 0,
        "follow_ups_created": 0,
        "spend_alert_fired": 0,
        "errors": 0,
    }
    # Finish any deletion whose catalog transaction did not complete, so an
    # interrupted deletion resolves on the next sweep without a restart
    # (ADR 039). Incremental: already-applied records are skipped.
    try:
        account_deletion_service.replay_deletions(db)
    except Exception:
        counts["errors"] += 1
        logger.exception("Deletion replay failed during the sweep")
    for assignment in db.list_all_active_assignments():
        result: dict[str, Any] | None = None
        try:
            result = evaluate_assignment(db, assignment, now=now)
        except Exception:
            counts["errors"] += 1
            logger.exception(
                "Missed-day evaluation failed for assignment %s", assignment.get("assignment_id")
            )
        if result is not None:
            if result.get("skipped"):
                counts["skipped"] += 1
            elif result.get("evaluated"):
                counts["evaluated"] += 1
            counts["alerts_created"] += int(result.get("alerts_created", 0))
            counts["alerts_resolved"] += int(result.get("alerts_resolved", 0))
        try:
            follow_up = evaluate_follow_up(db, assignment, now=now)
            counts["follow_ups_created"] += int(follow_up.get("created", 0))
        except Exception:
            counts["errors"] += 1
            logger.exception(
                "Follow-up evaluation failed for assignment %s", assignment.get("assignment_id")
            )
    # The model spend alert rides this existing sweep rather than adding a loop
    # (ADR 038, AC3). It is deduped per UTC month and never raises.
    try:
        from service.model_metering import evaluate_spend_alert

        spend = evaluate_spend_alert(db, now=now)
        counts["spend_alert_fired"] = 1 if spend.get("fired") else 0
    except Exception:
        counts["errors"] += 1
        logger.exception("Model spend-alert evaluation failed")
    try:
        account_deletion_service.retry_analytics_deletions(db, now=now)
    except Exception:
        counts["errors"] += 1
        logger.exception("Analytics deletion retry failed during the sweep")
    return counts
