"""Coach stall alerts (ADR 032, issue #204)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from service.coach_notices import notify_coach, player_display_name

STALL_KIND = "stall"
STALL_ALERT_THRESHOLD = 8


def _close_open(db: Any, assignment_id: str, now_iso: str) -> int:
    state = db.get_alert_signal_state(assignment_id, STALL_KIND, "")
    if state is None or not int(state["active"]):
        return 0
    resolved = db.resolve_open_coach_alerts_for_dedupe(
        assignment_id, STALL_KIND, str(state["episode_key"]), now_iso
    )
    db.upsert_alert_signal_state(assignment_id, STALL_KIND, "", 0, state["episode_key"], now_iso)
    return resolved


def resolve_for_assignment(db: Any, assignment_id: str, now: datetime | None = None) -> int:
    """System-resolve an open stall alert (new program or missed-day streak)."""
    now_iso = (now or datetime.now(UTC)).isoformat()
    with db.catalog_transaction():
        return _close_open(db, assignment_id, now_iso)


def evaluate_commit(
    db: Any,
    assignment: dict[str, Any],
    session_id: str,
    stall_length: int,
    window_start_date: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Open, extend, or close the one stall episode for a committing session."""
    now_iso = (now or datetime.now(UTC)).isoformat()
    assignment_id = str(assignment["assignment_id"])
    notices = False
    with db.catalog_transaction():
        if db.is_stall_session_processed(assignment_id, session_id):
            return {"evaluated": False, "alerts_created": 0, "alerts_resolved": 0}
        missed_streak = db.get_roster_missed_streak(assignment_id)
        created = 0
        resolved = 0
        state = db.get_alert_signal_state(assignment_id, STALL_KIND, "")
        if missed_streak > 0 or stall_length < STALL_ALERT_THRESHOLD or not window_start_date:
            resolved = _close_open(db, assignment_id, now_iso)
        elif state is None or not int(state["active"]):
            # Like the existing signal episodes, the committing session that
            # opens this episode is its stable key; the displayed window date
            # remains reduced evidence on the alert itself.
            dedupe_key = session_id
            details = {"stall_length": int(stall_length), "window_start_date": str(window_start_date)}
            inserted = db.insert_coach_alert(
                uuid.uuid4().hex,
                assignment_id,
                assignment["coach_account_id"],
                assignment["player_account_id"],
                STALL_KIND,
                dedupe_key,
                details,
                now_iso,
            )
            db.upsert_alert_signal_state(assignment_id, STALL_KIND, "", 1, dedupe_key, now_iso)
            if inserted["created"]:
                created = 1
                notices = True
        else:
            dedupe_key = str(state["episode_key"])
            alert = db.get_coach_alert_by_dedupe(assignment_id, STALL_KIND, dedupe_key)
            if alert is not None:
                db.update_coach_alert_details(
                    alert["alert_id"],
                    {"stall_length": int(stall_length), "window_start_date": alert["details"]["window_start_date"]},
                )
        db.mark_stall_session_processed(assignment_id, session_id, now_iso)
    if notices:
        notify_coach(
            db,
            assignment,
            STALL_KIND,
            f"{player_display_name(db, assignment)} has a stall alert. Review the alert in your roster.",
            now_iso,
        )
    return {"evaluated": True, "alerts_created": created, "alerts_resolved": resolved}
