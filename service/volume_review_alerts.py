"""Coach alerts for newly stored coach controlled Volume reviews (#235)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from service import coach_analytics

KIND = "volume_review"


def resolve_for_assignment(db: Any, assignment_id: str) -> int:
    now = datetime.now(UTC).isoformat()
    with db.catalog_transaction():
        return db.resolve_open_coach_alerts_for_assignment(
            assignment_id, now, KIND
        )


def evaluate_review(
    db: Any, assignment: dict[str, Any] | None, review: dict[str, Any] | None
) -> None:
    if assignment is None or review is None:
        return
    now = datetime.now(UTC).isoformat()
    dedupe_key = str(review["review_id"]) if review and review["status"] != "deferred" else None
    with db.catalog_transaction():
        db.resolve_open_coach_alerts_for_assignment(
            str(assignment["assignment_id"]), now, KIND, except_dedupe_key=dedupe_key
        )
        if dedupe_key is None:
            return
        coach_analytics.create_coach_alert(
            db,
            coach_analytics.CoachAlertDraft(
                alert_id=uuid.uuid4().hex,
                assignment_id=assignment["assignment_id"],
                coach_account_id=assignment["coach_account_id"],
                player_account_id=assignment["player_account_id"],
                alert_kind=KIND,
                dedupe_key=dedupe_key,
                details={"program_version": int(review["program_version"]), "review_date": review["review_date"]},
                created_at=now,
            ),
        )
