"""Privacy-safe analytics for committed Coach actions and history reads."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from service import analytics

logger = logging.getLogger(__name__)

DAILY_MARKER_RETENTION_DAYS = 30


def _now() -> datetime:
    """The current instant; a test seam for daily-event boundary behavior."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class CoachAnalyticsDailyMarker:
    """The private key shared by one persisted daily marker and its event UUID."""

    event_kind: str
    utc_day: str
    assignment_id: str | None = None


@dataclass(frozen=True)
class CoachAlertDraft:
    """The registry fields required to create one Coach alert."""

    alert_id: str
    assignment_id: str
    coach_account_id: str
    player_account_id: str
    alert_kind: str
    dedupe_key: str
    details: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class CoachDailyView:
    """The Coach and private Assignment scope for one daily view capture."""

    coach_account_id: str
    assignment_id: str | None = None
    now: datetime | None = None
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT


def _utc_day(now: datetime | None = None) -> str:
    instant = now or _now()
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(UTC).date().isoformat()


def _claim_daily_marker(
    db: Any,
    coach_account_id: str,
    marker: CoachAnalyticsDailyMarker,
) -> bool:
    try:
        return db.claim_coach_analytics_daily_marker(
            coach_account_id,
            marker.event_kind,
            marker.utc_day,
            assignment_id=marker.assignment_id,
        )
    except sqlite3.Error:
        logger.warning("Could not claim a Coach analytics daily marker.", exc_info=True)
        return False


def capture_coach_alert_created(
    alert: dict[str, Any], *, client: analytics.ClientContext = analytics.UNKNOWN_CLIENT
) -> None:
    """Captures one newly committed alert, with its category as a safe enum."""
    analytics.capture(
        analytics.AnalyticsEvent(
            account_id=str(alert["coach_account_id"]),
            event="coach_alert_created",
            domain_key=f"{alert['alert_id']}:created",
            role="coach",
            properties={"alert_kind": str(alert["kind"])},
        ),
        client,
    )


def _capture_after_catalog_commit(
    db: Any,
    alert: dict[str, Any],
    client: analytics.ClientContext,
) -> None:
    after_commit = getattr(db, "_after_catalog_commit", None)
    if after_commit is None:
        capture_coach_alert_created(alert, client=client)
    else:
        after_commit(lambda: capture_coach_alert_created(alert, client=client))


def _capture_inserted_alert(
    db: Any,
    inserted: dict[str, Any],
    client: analytics.ClientContext,
) -> None:
    alert = inserted.get("alert")
    if inserted.get("created") and alert is not None:
        _capture_after_catalog_commit(db, alert, client)


def create_coach_alert(
    db: Any,
    draft: CoachAlertDraft,
    *,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> dict[str, Any]:
    """Creates an alert and captures only its first committed insertion."""
    inserted = db.insert_coach_alert(
        draft.alert_id,
        draft.assignment_id,
        draft.coach_account_id,
        draft.player_account_id,
        draft.alert_kind,
        draft.dedupe_key,
        draft.details,
        draft.created_at,
    )
    _capture_inserted_alert(db, inserted, client)
    return inserted


def _time_open_seconds(alert: dict[str, Any], now: datetime) -> int:
    created_at = datetime.fromisoformat(str(alert["created_at"]))
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    action_at = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    elapsed = max(0, int((action_at.astimezone(UTC) - created_at.astimezone(UTC)).total_seconds()))
    maximum = analytics.PROPERTY_TYPES["time_open_seconds"].maximum
    return min(elapsed, maximum) if maximum is not None else elapsed


def _alert_action_properties(alert: dict[str, Any], now: datetime) -> dict[str, Any]:
    return {
        "alert_kind": alert["kind"],
        "time_open_seconds": _time_open_seconds(alert, now),
        "is_coaching_action": True,
    }


def _capture_alert_transition(
    alert: dict[str, Any],
    now: datetime,
    event: Literal["coach_alert_acknowledged", "coach_alert_resolved"],
    domain_action: Literal["acknowledged", "resolved"],
    *,
    client: analytics.ClientContext,
) -> None:
    analytics.capture(
        analytics.AnalyticsEvent(
            account_id=str(alert["coach_account_id"]),
            event=event,
            domain_key=f"{alert['alert_id']}:{domain_action}",
            role="coach",
            properties=_alert_action_properties(alert, now),
        ),
        client,
    )


def capture_coach_alert_acknowledged(
    alert: dict[str, Any],
    now: datetime,
    *,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> None:
    """Captures a Coach acknowledgement after its state transition commits."""
    _capture_alert_transition(
        alert,
        now,
        "coach_alert_acknowledged",
        "acknowledged",
        client=client,
    )


def capture_coach_alert_resolved(
    alert: dict[str, Any],
    now: datetime,
    *,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> None:
    """Captures a Coach resolution after its state transition commits."""
    _capture_alert_transition(
        alert,
        now,
        "coach_alert_resolved",
        "resolved",
        client=client,
    )


def capture_check_in_recorded(
    coach_account_id: str,
    check_in_id: str,
    *,
    client: analytics.ClientContext = analytics.UNKNOWN_CLIENT,
) -> None:
    """Captures only the fact that a Coach committed a check-in."""
    analytics.capture(
        analytics.AnalyticsEvent(
            account_id=str(coach_account_id),
            event="check_in_recorded",
            domain_key=f"{check_in_id}:recorded",
            role="coach",
            properties={"is_coaching_action": True},
        ),
        client,
    )


def _daily_event_domain_key(view: CoachDailyView, utc_day: str) -> str:
    scope = f":{view.assignment_id}" if view.assignment_id is not None else ""
    return f"{view.coach_account_id}{scope}:{utc_day}"


def _daily_marker(
    view: CoachDailyView,
    event: Literal["coach_alerts_viewed", "player_history_viewed"],
) -> CoachAnalyticsDailyMarker:
    return CoachAnalyticsDailyMarker(event, _utc_day(view.now), view.assignment_id)


def _claim_marker_then_capture(
    db: Any,
    view: CoachDailyView,
    event: Literal["coach_alerts_viewed", "player_history_viewed"],
) -> bool:
    marker = _daily_marker(view, event)
    if not _claim_daily_marker(db, view.coach_account_id, marker):
        return False
    analytics.capture(
        analytics.AnalyticsEvent(
            account_id=view.coach_account_id,
            event=event,
            domain_key=_daily_event_domain_key(view, marker.utc_day),
            role="coach",
        ),
        view.client,
    )
    return True


def capture_coach_alerts_viewed(
    db: Any,
    view: CoachDailyView,
) -> bool:
    """Claims one Coach alert-list view per UTC day before capture."""
    return _claim_marker_then_capture(db, view, "coach_alerts_viewed")


def capture_player_history_viewed(
    db: Any,
    view: CoachDailyView,
) -> bool:
    """Claims one history view per Coach, Assignment and UTC day after authorization."""
    if view.assignment_id is None:
        raise ValueError("An Assignment scope is required for a Player history view.")
    return _claim_marker_then_capture(db, view, "player_history_viewed")


def prune_daily_markers(db: Any, now: datetime | None = None) -> int:
    """Removes daily markers outside the retained UTC-day window."""
    today = datetime.fromisoformat(_utc_day(now)).date()
    cutoff = (today - timedelta(days=DAILY_MARKER_RETENTION_DAYS)).isoformat()
    try:
        return db.prune_coach_analytics_daily_markers(cutoff)
    except sqlite3.Error:
        logger.warning("Could not prune Coach analytics daily markers.", exc_info=True)
        return 0
