"""Deterministic, de-identified signal snapshot for a Coach's Roster (#310)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from service import attendance as attendance_service
from service import assignments as assignments_service
from service import coach_ai
from service import missed_day_alerts
from service import stalling
from service.coach_settings import DEFAULT_STALL_THRESHOLD_WEEKS
from service.schedule import local_date_in


@dataclass(frozen=True)
class SnapshotContext:
    db: Any
    now: datetime
    stall_threshold_weeks: int
    active_alerts: list[dict[str, Any]]


def _eligible_assignments(
    db: Any, coach_account_id: str, roster_rows: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """The single roster-snapshot eligibility boundary (#326 extends this)."""
    eligible = []
    for roster_entry in roster_rows:
        assignment = db.get_active_assignment_for_coach(
            coach_account_id, str(roster_entry["assignment_id"])
        )
        if assignment is None:
            continue
        if (
            assignment.get("roster_ai_disclosure_version")
            != assignments_service.ROSTER_AI_DISCLOSURE_VERSION
            or assignment.get("roster_ai_disclosed_at") is None
        ):
            continue
        player = db.get_account(assignment["player_account_id"])
        if db.is_live_account(player):
            eligible.append((roster_entry, assignment, player))
    return eligible


def _elapsed_days(today: date, date_value: Any) -> int | None:
    if not date_value:
        return None
    return max(0, (today - date.fromisoformat(str(date_value)[:10])).days)


def _urgency_inputs(
    roster_entry: dict[str, Any], today: date, pending_requests: int
) -> dict[str, int | None]:
    follow_up_overdue_days = 0
    if roster_entry.get("next_follow_up_on"):
        follow_up_overdue_days = _elapsed_days(today, roster_entry["next_follow_up_on"]) or 0
    return {
        "new_lapsing_alerts": int(roster_entry.get("alerts_new_lapsing") or 0),
        "other_new_coach_alerts": max(
            0,
            int(roster_entry.get("alerts_new") or 0)
            - int(roster_entry.get("alerts_new_lapsing") or 0),
        ),
        "pending_program_requests": pending_requests,
        "missed_day_streak": int(roster_entry.get("current_missed_streak") or 0),
        "follow_up_overdue_days": follow_up_overdue_days,
        "days_since_last_workout": _elapsed_days(today, roster_entry.get("last_workout_on")),
        "stall_length_sessions": int(roster_entry.get("stall_length") or 0),
    }


def _attendance_signals(
    ledger: Any,
    assignment: dict[str, Any],
    ledger_id: str,
    now: datetime,
) -> tuple[int | None, int | None, float | None, date | None]:
    evaluation = missed_day_alerts.evaluate_ledger_attendance(
        ledger, assignment, ledger_id, now
    )
    if evaluation is None:
        return None, None, None, None

    missed_7 = _missed_expected_days_in_window(evaluation, 7)
    missed_14 = _missed_expected_days_in_window(evaluation, 14)
    adherence = attendance_service.adherence_percentage(
        evaluation, window_start=evaluation.local_today - timedelta(days=27)
    )
    return missed_7, missed_14, adherence, evaluation.local_today


def _missed_expected_days_in_window(evaluation: Any, days: int) -> int:
    window_start = evaluation.local_today - timedelta(days=days - 1)
    return sum(day >= window_start for day in evaluation.missed_days)


def _weeks_without_personal_record(ledger: Any, program: Any, today: date) -> int | None:
    if program is None or program.version is None:
        return None
    sessions = ledger.stall_recount_facts(None)
    exercise_ids = {
        str(exercise.exercise_id)
        for day in program.days
        for exercise in day.exercises
        if exercise.exercise_id
    }
    reference_date = stalling.personal_record_reference_date(
        sessions, int(program.version), exercise_ids
    )
    if reference_date is None:
        return None
    days = max(0, (today - date.fromisoformat(reference_date)).days)
    return days // 7


def _effort_rising_same_load(
    program: Any, alerts: list[dict[str, Any]], assignment_id: str
) -> bool:
    main_lift_ids = set(coach_ai.main_lift_exercise_names(program))
    if not main_lift_ids:
        return False
    return any(
        alert.get("assignment_id") == assignment_id
        and alert.get("kind") == "performance_regression"
        and alert.get("state") in {"new", "acknowledged"}
        and str((alert.get("details") or {}).get("exercise_id") or "") in main_lift_ids
        for alert in alerts
    )


def _threshold(db: Any, coach_account_id: str) -> int:
    return db.get_coach_stall_threshold(coach_account_id) or DEFAULT_STALL_THRESHOLD_WEEKS


def _client_mapping(
    opaque_id: str, assignment: dict[str, Any]
) -> dict[str, str]:
    return {
        "player_id": opaque_id,
        "assignment_id": str(assignment["assignment_id"]),
    }


def _empty_ledger_signals() -> dict[str, Any]:
    return {
        "missed_expected_days_7d": None,
        "missed_expected_days_14d": None,
        "adherence_pct_28d": None,
        "weeks_without_personal_record": None,
        "effort_rising_same_load_main_lift": False,
    }


def _ledger_signals(
    player: dict[str, Any], assignment: dict[str, Any], context: SnapshotContext
) -> tuple[dict[str, Any], date]:
    local_timezone = context.db.get_roster_timezone(str(assignment["assignment_id"])) or "UTC"
    local_today = local_date_in(context.now, local_timezone)
    if not context.db.ledger_exists(player["ledger_id"]):
        return _empty_ledger_signals(), local_today
    with context.db.open_ledger(player["ledger_id"]) as ledger:
        missed_7, missed_14, adherence, attendance_today = _attendance_signals(
            ledger, assignment, player["ledger_id"], context.now
        )
        local_today = attendance_today or local_today
        program = ledger.get_active_program()
        weeks_without_record = _weeks_without_personal_record(ledger, program, local_today)
    return {
        "missed_expected_days_7d": missed_7,
        "missed_expected_days_14d": missed_14,
        "adherence_pct_28d": adherence,
        "weeks_without_personal_record": weeks_without_record,
        "effort_rising_same_load_main_lift": _effort_rising_same_load(
            program, context.active_alerts, str(assignment["assignment_id"])
        ),
    }, local_today


def _player_signal(
    roster_entry: dict[str, Any],
    assignment: dict[str, Any],
    player: dict[str, Any],
    context: SnapshotContext,
) -> tuple[dict[str, Any], dict[str, str]]:
    opaque_id = uuid.uuid4().hex
    ledger_signals, local_today = _ledger_signals(player, assignment, context)
    weeks_without_record = ledger_signals["weeks_without_personal_record"]
    pending_requests = int(roster_entry.get("pending_requests") or 0)
    signal = {
        "player_id": opaque_id,
        "urgency_inputs": _urgency_inputs(roster_entry, local_today, pending_requests),
    }
    signal.update(ledger_signals)
    signal["stall_threshold_met"] = (
        weeks_without_record is not None
        and weeks_without_record >= context.stall_threshold_weeks
    )
    signal["days_since_last_check_in"] = _elapsed_days(
        local_today, context.db.latest_check_in_on(str(assignment["assignment_id"]))
    )
    signal.update({"bodyweight_trend": None, "coaching_subscription_end": None})
    return signal, _client_mapping(opaque_id, assignment)


def roster_signal_snapshot(
    db: Any, coach_account_id: str, *, now: datetime | None = None
) -> dict[str, Any]:
    """Builds allowlisted player facts and keeps identity in a sibling mapping."""
    instant = now or datetime.now(UTC)
    threshold = _threshold(db, coach_account_id)
    roster_rows = assignments_service.list_coach_assignments(db, coach_account_id, now=instant)
    eligible = _eligible_assignments(db, coach_account_id, roster_rows)
    active_alerts = db.list_coach_alerts(coach_account_id, ("new", "acknowledged"))
    context = SnapshotContext(db, instant, threshold, active_alerts)
    players, client_mapping = _ranked_signals(eligible, context)
    return _snapshot_response(instant, threshold, players, client_mapping)


def _ranked_signals(
    eligible: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
    context: SnapshotContext,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    players = []
    client_mapping = []
    for roster_entry, assignment, player in eligible:
        signal, mapping = _player_signal(roster_entry, assignment, player, context)
        signal["urgency_rank"] = len(players) + 1
        players.append(signal)
        client_mapping.append(mapping)
    return players, client_mapping


def _snapshot_response(
    instant: datetime,
    threshold: int,
    players: list[dict[str, Any]],
    client_mapping: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "snapshot": {
            "as_of": instant.astimezone(UTC).date().isoformat(),
            "stall_threshold_weeks": int(threshold),
            "players": players,
        },
        "client_mapping": client_mapping,
    }
