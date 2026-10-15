"""Catalog-side Coach alerts for changes to a Training profile."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from database.registry.assignments import AssignmentNoticeRecord
from service.coach_notices import (
    build_assignment_notice_record,
    notify_coach,
    player_display_name,
)
from service import analytics as analytics_service
from service import coach_analytics

logger = logging.getLogger(__name__)

PROFILE_CHANGE_KIND = "profile_change"
PROFILE_CHANGE_FIELDS = ("injuries_or_limitations", "equipment_access")
_OPEN_STATES = ("new", "acknowledged")


@dataclass(frozen=True)
class ProfileChangeSnapshot:
    """The committed before/after profile values and request attribution."""

    player_account_id: str | None
    before_profile: dict[str, Any]
    after_profile: dict[str, Any]
    client: analytics_service.ClientContext = analytics_service.UNKNOWN_CLIENT


__all__ = [
    "ProfileChangeSnapshot",
    "PROFILE_CHANGE_FIELDS",
    "PROFILE_CHANGE_KIND",
    "changed_fields",
    "normalize_profile_value",
    "record_profile_change",
]


def normalize_profile_value(field: str, value: Any) -> Any:
    """Use the same string trimming used by profile rebuild comparisons."""
    if field == "weekly_frequency":
        return int(value)
    if isinstance(value, str):
        return value.strip()
    return value


def changed_fields(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return only changed, allowlisted Training profile facts."""
    result: dict[str, dict[str, Any]] = {}
    for field in PROFILE_CHANGE_FIELDS:
        default = "None" if field == "injuries_or_limitations" else None
        before_value = normalize_profile_value(field, before.get(field, default))
        after_value = normalize_profile_value(field, after.get(field, default))
        if before_value != after_value:
            result[field] = {"before": before_value, "after": after_value}
    return result


def _episode_key(db: Any, assignment_id: str) -> tuple[str, dict[str, Any] | None]:
    """Find the newest episode by deterministic key, or reserve its next key.

    Alert rows form a contiguous sequence per assignment. Looking up each key
    through the registry's unique-key accessor makes retries find the same open
    episode, while a resolved episode advances to a new key.
    """
    episode = 1
    latest = None
    while True:
        key = f"episode:{episode}"
        alert = db.get_coach_alert_by_dedupe(assignment_id, PROFILE_CHANGE_KIND, key)
        if alert is None:
            return key, latest if latest and latest["state"] in _OPEN_STATES else None
        latest = alert
        if latest["state"] in _OPEN_STATES:
            return key, latest
        episode += 1


def record_profile_change(
    db: Any,
    snapshot: ProfileChangeSnapshot,
) -> None:
    """Best-effort profile-change alert after the Training profile write."""
    player_account_id = snapshot.player_account_id
    if not player_account_id:
        return
    changes = changed_fields(snapshot.before_profile, snapshot.after_profile)
    if not changes:
        return

    now_iso = datetime.now(UTC).isoformat()
    assignment = None
    created_alert = None
    try:
        with db.catalog_transaction():
            assignment = db.get_active_assignment_for_player(str(player_account_id))
            if assignment is None:
                return
            dedupe_key, existing = _episode_key(db, assignment["assignment_id"])
            existing_details = dict(existing["details"]) if existing else {}
            merged = dict(existing_details.get("profile_changes", {}))
            for field, change in changes.items():
                prior = merged.get(field)
                earliest = prior.get("before", change["before"]) if isinstance(prior, dict) else change["before"]
                latest = change["after"]
                if earliest == latest:
                    merged.pop(field, None)
                else:
                    merged[field] = {"before": earliest, "after": latest}

            if existing is not None and not merged and not existing_details.get("injury_changes"):
                db.update_coach_alert_details(existing["alert_id"], {**existing_details, "profile_changes": {}})
                db.resolve_open_coach_alerts_for_dedupe(
                    assignment["assignment_id"], PROFILE_CHANGE_KIND, dedupe_key, now_iso
                )
                return
            details = {**existing_details, "profile_changes": merged}
            if existing is not None:
                db.update_coach_alert_details(existing["alert_id"], details)
                return
            inserted = coach_analytics.create_coach_alert(
                db,
                coach_analytics.CoachAlertDraft(
                    alert_id=uuid.uuid4().hex,
                    assignment_id=assignment["assignment_id"],
                    coach_account_id=assignment["coach_account_id"],
                    player_account_id=str(player_account_id),
                    alert_kind=PROFILE_CHANGE_KIND,
                    dedupe_key=dedupe_key,
                    details=details,
                    created_at=now_iso,
                ),
                client=snapshot.client,
            )
            if inserted["created"]:
                created_alert = inserted["alert"]
    except Exception:
        logger.warning("Could not create profile-change Coach alert for account %s.", player_account_id, exc_info=True)
        return
    if assignment is not None and created_alert is not None:
        try:
            player_name = player_display_name(db, assignment)
            message = (
                f"{player_name} changed their Training profile. Review the alert in your roster."
            )
            notify_coach(
                db,
                build_assignment_notice_record(
                    AssignmentNoticeRecord(
                        account_id=assignment["coach_account_id"],
                        assignment_id=assignment["assignment_id"],
                        kind=PROFILE_CHANGE_KIND,
                        message=message,
                        created_at=now_iso,
                    ),
                    "assignment_notice.profile_change.v1",
                    {"player_name": player_name},
                ),
            )
        except Exception:
            logger.warning("Could not notify the Coach about a profile-change alert.", exc_info=True)


def record_injury_change(
    db: Any,
    player_account_id: str | None,
    injury: dict[str, Any],
    *,
    change: str,
    previous_status: str | None = None,
    client: analytics_service.ClientContext = analytics_service.UNKNOWN_CLIENT,
) -> None:
    """Adds a new injury or record edit to the active profile-change alert episode."""
    if not player_account_id:
        return
    client = client or analytics_service.UNKNOWN_CLIENT
    now_iso = datetime.now(UTC).isoformat()
    assignment = None
    created_alert = None
    try:
        with db.catalog_transaction():
            assignment = db.get_active_assignment_for_player(str(player_account_id))
            if assignment is None:
                return
            dedupe_key, existing = _episode_key(db, assignment["assignment_id"])
            details = dict(existing.get("details", {})) if existing else {}
            injury_changes = dict(details.get("injury_changes", {}))
            injury_id = str(injury["id"])
            prior = injury_changes.get(injury_id)
            update = {
                "body_area": injury.get("body_area"),
                "description": injury.get("description", ""),
                "status": injury.get("status", "reported"),
                "change": change,
                "changed_at": now_iso,
            }
            earliest_previous_status = (
                prior.get("previous_status")
                if isinstance(prior, dict) and "previous_status" in prior
                else previous_status
            )
            if earliest_previous_status is not None:
                update["previous_status"] = earliest_previous_status
            injury_changes[injury_id] = update
            details["injury_changes"] = injury_changes
            if existing is not None:
                db.update_coach_alert_details(existing["alert_id"], details)
                return
            inserted = coach_analytics.create_coach_alert(
                db,
                coach_analytics.CoachAlertDraft(
                    alert_id=uuid.uuid4().hex,
                    assignment_id=assignment["assignment_id"],
                    coach_account_id=assignment["coach_account_id"],
                    player_account_id=str(player_account_id),
                    alert_kind=PROFILE_CHANGE_KIND,
                    dedupe_key=dedupe_key,
                    details=details,
                    created_at=now_iso,
                ),
                client=client,
            )
            if inserted["created"]:
                created_alert = inserted["alert"]
    except Exception:
        logger.warning("Could not create injury-change Coach alert for account %s.", player_account_id, exc_info=True)
        return
    if assignment is not None and created_alert is not None:
        try:
            player_name = player_display_name(db, assignment)
            notify_coach(
                db,
                build_assignment_notice_record(
                    AssignmentNoticeRecord(
                        account_id=assignment["coach_account_id"],
                        assignment_id=assignment["assignment_id"],
                        kind=PROFILE_CHANGE_KIND,
                        message=f"{player_name} updated an injury record. Review the alert in your roster.",
                        created_at=now_iso,
                    ),
                    "assignment_notice.profile_change.v1",
                    {"player_name": player_name},
                ),
            )
        except Exception:
            logger.warning("Could not notify the Coach about an injury record change.", exc_info=True)


def record_clearance_change(
    db: Any,
    player_account_id: str | None,
    clearance: dict[str, Any],
    *,
    change: str,
    client: analytics_service.ClientContext = analytics_service.UNKNOWN_CLIENT,
) -> None:
    """Creates one assignment-gated Coach alert for each clearance write or edit."""
    if not player_account_id:
        return
    now_iso = datetime.now(UTC).isoformat()
    assignment = None
    created_alert = None
    try:
        with db.catalog_transaction():
            assignment = db.get_active_assignment_for_player(str(player_account_id))
            if assignment is None:
                return
            event_key = f"clearance:{clearance['id']}:{change}:{clearance.get('recorded_at') or now_iso}"
            inserted = coach_analytics.create_coach_alert(
                db,
                coach_analytics.CoachAlertDraft(
                    alert_id=uuid.uuid4().hex,
                    assignment_id=assignment["assignment_id"],
                    coach_account_id=assignment["coach_account_id"],
                    player_account_id=str(player_account_id),
                    alert_kind=PROFILE_CHANGE_KIND,
                    dedupe_key=event_key,
                    details={
                        "clearance_changes": [{
                            "id": str(clearance["id"]),
                            "injury_id": str(clearance["injury_id"]),
                            "exercise_name": clearance.get("exercise_name", ""),
                            "verdict": clearance.get("verdict", ""),
                            "change": change,
                            "changed_at": now_iso,
                        }],
                    },
                    created_at=now_iso,
                ),
                client=client or analytics_service.UNKNOWN_CLIENT,
            )
            if inserted["created"]:
                created_alert = inserted["alert"]
    except Exception:
        logger.warning("Could not create exercise-clearance Coach alert for account %s.", player_account_id, exc_info=True)
        return
    if assignment is not None and created_alert is not None:
        try:
            player_name = player_display_name(db, assignment)
            notify_coach(
                db,
                build_assignment_notice_record(
                    AssignmentNoticeRecord(
                        account_id=assignment["coach_account_id"],
                        assignment_id=assignment["assignment_id"],
                        kind=PROFILE_CHANGE_KIND,
                    message=f"{player_name} changed an exercise clearance. Review the alert in your roster.",
                        created_at=now_iso,
                    ),
                    "assignment_notice.profile_change.v1",
                    {"player_name": player_name},
                ),
            )
        except Exception:
            logger.warning("Could not notify the Coach about an exercise clearance change.", exc_info=True)
