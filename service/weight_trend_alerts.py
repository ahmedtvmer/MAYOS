"""Coach alerts for Player weight trends moving away from a target."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from service import coach_analytics
from service.weight_history import WeightTrendQuery, get_weight_trend, player_local_date

logger = logging.getLogger(__name__)

WEIGHT_TREND_KIND = "weight_off_target_trend"
WEIGHT_TREND_COOLDOWN = timedelta(days=14)
WEIGHT_TREND_THRESHOLD_KG = 1.0
WEIGHT_TREND_WINDOW_DAYS = 14
WEIGHT_TREND_MIN_SPAN_DAYS = 7


def evaluate_assignment(
    db: Any,
    assignment: dict[str, Any],
    *,
    now: datetime | None = None,
    ledger: Any | None = None,
) -> bool:
    """Creates one alert when a 14-day trend moves at least 1 kg away."""
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    instant = instant.astimezone(UTC)
    player_account_id = str(assignment["player_account_id"])
    account = db.get_account(player_account_id)
    if not db.is_live_account(account):
        return False

    ledger_id = str(account["ledger_id"])
    if not db.ledger_exists(ledger_id):
        return False
    if ledger is None:
        with db.open_ledger(ledger_id) as handle:
            return _evaluate_with_ledger(db, assignment, handle, instant)
    return _evaluate_with_ledger(db, assignment, ledger, instant)


def _evaluate_with_ledger(
    db: Any,
    assignment: dict[str, Any],
    ledger: Any,
    instant: datetime,
) -> bool:
    player_account_id = str(assignment["player_account_id"])
    profile = ledger.get_player_profile() or {}
    target = profile.get("target_weight_kg")
    if target is None:
        return False
    as_of = player_local_date(ledger, str(ledger.ledger_id), instant)
    trend = get_weight_trend(
        db,
        WeightTrendQuery(
            ledger_id=str(ledger.ledger_id), weeks=2, as_of=as_of
        ),
        ledger,
    )
    start_date = as_of - timedelta(days=WEIGHT_TREND_WINDOW_DAYS - 1)
    points = tuple(point for point in trend.points if start_date <= point.date <= as_of)
    if len(points) < 2:
        return False
    start, latest = points[0], points[-1]
    if (latest.date - start.date).days < WEIGHT_TREND_MIN_SPAN_DAYS:
        return False
    target_kg = float(target)
    start_distance = abs(start.weight_kg - target_kg)
    latest_distance = abs(latest.weight_kg - target_kg)
    distance_change = latest_distance - start_distance
    if latest_distance <= WEIGHT_TREND_THRESHOLD_KG:
        return False
    if distance_change < WEIGHT_TREND_THRESHOLD_KG:
        return False

    previous = db.get_latest_coach_alert_created_at(player_account_id, WEIGHT_TREND_KIND)
    if previous:
        previous_at = datetime.fromisoformat(previous)
        if previous_at.tzinfo is None:
            previous_at = previous_at.replace(tzinfo=UTC)
        if instant - previous_at.astimezone(UTC) < WEIGHT_TREND_COOLDOWN:
            return False

    details = {
        "weight_points": [
            {"date": point.date.isoformat(), "weight_kg": point.weight_kg}
            for point in points
        ],
        "target_weight_kg": target_kg,
        "distance_change_kg": distance_change,
        "window_days": WEIGHT_TREND_WINDOW_DAYS,
        "threshold_kg": WEIGHT_TREND_THRESHOLD_KG,
    }
    inserted = coach_analytics.create_coach_alert(
        db,
        coach_analytics.CoachAlertDraft(
            alert_id=uuid.uuid4().hex,
            assignment_id=str(assignment["assignment_id"]),
            coach_account_id=str(assignment["coach_account_id"]),
            player_account_id=player_account_id,
            alert_kind=WEIGHT_TREND_KIND,
            dedupe_key=f"{start.date.isoformat()}:{latest.date.isoformat()}",
            details=details,
            created_at=instant.isoformat(),
        ),
    )
    return bool(inserted["created"])


def evaluate_for_player(
    db: Any,
    player_account_id: str | None,
    *,
    ledger: Any | None = None,
) -> bool:
    """Best-effort immediate evaluation, scoped to the Player's active Coach."""
    if not player_account_id:
        return False
    try:
        assignment = db.get_active_assignment_for_player(str(player_account_id))
        if assignment is None:
            return False
        return evaluate_assignment(db, assignment, ledger=ledger)
    except Exception:
        logger.exception("Weight trend alert evaluation failed")
        return False
