"""Coach alerts for repeated Nutrition adherence patterns."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from service import coach_analytics
from service import nutrition as nutrition_service
from service.schedule import local_date_in, timezone_for_versions

OFF_KIND = "nutrition_off_streak"
UNLOGGED_KIND = "nutrition_unlogged"


@dataclass(frozen=True)
class AdherenceHistory:
    verdicts: dict[date, str]
    food_days: set[date]


def _read_adherence(
    db: Any, ledger_id: str, now: datetime
) -> tuple[date, date, date, bool, AdherenceHistory]:
    with db.open_ledger(ledger_id) as ledger:
        versions = ledger.list_training_schedules(ledger_id)
        timezone = timezone_for_versions(versions) if versions else "UTC"
        today = local_date_in(now, timezone)
        has_targets = nutrition_service.read(ledger, today=today).get("state") == "ready"
        start = today
        first_plan_at = ledger.get_first_nutrition_plan_created_at()
        if first_plan_at:
            created = datetime.fromisoformat(first_plan_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            start = local_date_in(created, timezone) + timedelta(days=1)
        completed_through = today - timedelta(days=1)
        entries = {date.fromisoformat(row["date"]): row["value"] for row in
                   ledger.list_nutrition_adherence(start.isoformat(), today.isoformat())}
        food_days = {date.fromisoformat(day) for day in ledger.list_food_log_dates(start, today)}
    return today, start, completed_through, has_targets, AdherenceHistory(entries, food_days)


def _is_signal_day(kind: str, day: date, history: AdherenceHistory) -> bool:
    if kind == OFF_KIND:
        return history.verdicts.get(day) == "off"
    return day not in history.verdicts and day not in history.food_days


def _qualifying_episodes(
    today: date, start: date, completed_through: date,
    history: AdherenceHistory, has_targets: bool
) -> dict[str, date]:
    qualifying: dict[str, date] = {}
    if not has_targets:
        return qualifying
    off_through = today if today in history.verdicts else completed_through
    for kind, through in ((OFF_KIND, off_through), (UNLOGGED_KIND, completed_through)):
        run_start = through
        run_length = 0
        while run_start >= start and _is_signal_day(kind, run_start, history):
            run_length += 1
            run_start -= timedelta(days=1)
        if run_length >= 3:
            qualifying[kind] = run_start + timedelta(days=1)
    return qualifying


def _record_episode(
    db: Any, assignment: dict[str, Any], kind: str, start: date, now_iso: str
) -> tuple[bool, int]:
    key = start.isoformat()
    inserted = coach_analytics.create_coach_alert(db, coach_analytics.CoachAlertDraft(
        alert_id=uuid.uuid4().hex, assignment_id=assignment["assignment_id"],
        coach_account_id=assignment["coach_account_id"],
        player_account_id=assignment["player_account_id"], alert_kind=kind,
        dedupe_key=key, details={"episode_start_date": key}, created_at=now_iso,
    ))
    resolved = db.resolve_open_coach_alerts_for_assignment(
        assignment["assignment_id"], now_iso, kind, except_dedupe_key=key
    )
    return bool(inserted["created"]), resolved


def _active_episode(
    alerts: list[dict[str, Any]], assignment_id: str, kind: str
) -> dict[str, Any] | None:
    return next((row for row in alerts
                 if row["assignment_id"] == assignment_id and row["kind"] == kind), None)


def _has_good_day_after(
    episode: dict[str, Any], history: AdherenceHistory
) -> bool:
    start = date.fromisoformat(episode["details"]["episode_start_date"])
    if episode["kind"] == UNLOGGED_KIND and any(day > start for day in history.food_days):
        return True
    return any(day > start and value in ("on_target", "roughly")
               for day, value in history.verdicts.items())


def _apply_kind(
    db: Any, assignment: dict[str, Any], kind: str, now_iso: str,
    alerts: list[dict[str, Any]], history: AdherenceHistory,
    qualifying: dict[str, date]
) -> tuple[int, int]:
    episode = _active_episode(alerts, assignment["assignment_id"], kind)
    if episode is not None:
        if _has_good_day_after(episode, history):
            resolved = db.resolve_open_coach_alerts_for_assignment(
                assignment["assignment_id"], now_iso, kind
            )
            return 0, resolved
        return 0, 0
    episode_start = qualifying.get(kind)
    if episode_start is None:
        return 0, 0
    created, resolved = _record_episode(db, assignment, kind, episode_start, now_iso)
    return int(created), resolved


def _apply_episodes(
    db: Any, assignment: dict[str, Any], now: datetime,
    history: AdherenceHistory, qualifying: dict[str, date], has_targets: bool,
    open_alerts: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    created = resolved = 0
    now_iso = now.isoformat()
    if open_alerts is None:
        open_alerts = db.list_coach_alerts(
            assignment["coach_account_id"], ("new", "acknowledged")
        )
    with db.catalog_transaction():
        if not has_targets:
            resolved += db.resolve_open_coach_alerts_for_assignment(
                assignment["assignment_id"], now_iso, UNLOGGED_KIND
            )
        for kind in (OFF_KIND, UNLOGGED_KIND):
            episode_created, episode_resolved = _apply_kind(
                db, assignment, kind, now_iso, open_alerts, history, qualifying
            )
            created += episode_created
            resolved += episode_resolved
    return {"alerts_created": created, "alerts_resolved": resolved}


def evaluate_assignment(
    db: Any, assignment: dict[str, Any], now: datetime,
    open_alerts: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    account = db.get_account(assignment["player_account_id"])
    if not db.is_live_account(account) or not db.ledger_exists(account["ledger_id"]):
        return {"alerts_created": 0, "alerts_resolved": 0}
    today, start, completed_through, has_targets, history = _read_adherence(
        db, account["ledger_id"], now
    )
    qualifying = _qualifying_episodes(
        today, start, completed_through, history, has_targets
    )
    return _apply_episodes(db, assignment, now, history, qualifying, has_targets, open_alerts)
