"""Catalog-side Coach alerts for changes to a Training profile."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from service.coach_notices import notify_coach, player_display_name
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
            merged = dict(existing["details"].get("profile_changes", {})) if existing else {}
            for field, change in changes.items():
                prior = merged.get(field)
                earliest = prior.get("before", change["before"]) if isinstance(prior, dict) else change["before"]
                latest = change["after"]
                if earliest == latest:
                    merged.pop(field, None)
                else:
                    merged[field] = {"before": earliest, "after": latest}

            if existing is not None and not merged:
                db.update_coach_alert_details(existing["alert_id"], {"profile_changes": {}})
                db.resolve_open_coach_alerts_for_dedupe(
                    assignment["assignment_id"], PROFILE_CHANGE_KIND, dedupe_key, now_iso
                )
                return
            details = {"profile_changes": merged}
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
            notify_coach(
                db,
                assignment,
                PROFILE_CHANGE_KIND,
                f"{player_display_name(db, assignment)} changed their Training profile. Review the alert in your roster.",
                now_iso,
            )
        except Exception:
            logger.warning("Could not notify the Coach about a profile-change alert.", exc_info=True)
