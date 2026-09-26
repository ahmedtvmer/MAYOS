"""Workout prescription and session-commit logic (moved verbatim from the UI layer)."""

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent.debrief import generate_session_debrief
from agent.progression_engine import (
    calculate_e1rm,
    evaluate_session_prs,
    evaluate_systemic_fatigue,
    project_next_load,
)
from core.warmup import calculate_warmup_sets
from service._base import bind_user
from service.schedule import latest_schedule_timezone, local_date_in, local_today, parse_iso_date
from utils.plate_calculator import calculate_barbell_plates

logger = logging.getLogger(__name__)

#: Performed dates may be entered or corrected up to three days back (ADR 020).
MAX_BACKDATE_DAYS = 3

#: Device clocks drift; a capture timestamp within this window of "now" is fine.
CLOCK_SKEW = timedelta(minutes=10)


class SessionSyncValidationError(ValueError):
    """Raised for an invalid commit request (mapped to HTTP 400 by the router)."""


class SessionCorrectionNotAllowedError(Exception):
    """The session is older than the three-day correction window (mapped to HTTP 409, ADR 035)."""


class ProgramVersionMismatchError(Exception):
    """The captured program version no longer matches the player's active program."""

    def __init__(self, active_version: int | None):
        self.active_version = active_version
        super().__init__("program_version_mismatch")


class DayPlanNotFoundError(Exception):
    """No training day with the requested order exists on the active program."""

    def __init__(self, day_order: int):
        self.day_order = day_order
        super().__init__(f"No day with order {day_order}.")


@dataclass(frozen=True)
class CommitOutcome:
    """A session commit's response body and whether this call performed the commit."""

    body: dict[str, Any]
    created: bool


@dataclass(frozen=True)
class SyncMetadata:
    """Offline-sync identity for one commit (ADR 020/033); all-``None`` for the legacy path."""

    client_session_id: str | None = None
    performed_date: str | None = None
    performed_timezone: str | None = None
    program_version: int | None = None
    captured_at: str | None = None


def day_plan_from(program: Any, day_order: int) -> Any:
    """The requested training day, or ``DayPlanNotFoundError`` (shared by service and router)."""
    for day in program.days:
        if day.day_order == day_order:
            return day
    raise DayPlanNotFoundError(day_order)


def is_historical_program(
    program_version: int | None, active_program_version_at_sync: int | None
) -> bool:
    """True when a session was captured against a program older than the one active at sync (ADR 034).

    Single source of truth for the derived flag. The database layer returns only
    the raw stored versions; callers in the service layer derive the flag.
    """
    return (
        program_version is not None
        and active_program_version_at_sync is not None
        and int(program_version) < int(active_program_version_at_sync)
    )


def resolve_sync_program(db: Any, active_program: Any, captured_version: int | None) -> Any:
    """The program to commit a draft against, or raise ``ProgramVersionMismatchError`` (ADR 034).

    The captured version must exist in the player's ledger and be no newer than
    the active version. An equal version resolves to the active program; an
    older version resolves to the historical (inactive) program row, which is
    never reactivated or rewritten. An unknown, newer, or missing version is
    refused.
    """
    active_version = active_program.version
    if captured_version is None or active_version is None:
        raise ProgramVersionMismatchError(active_version)
    if captured_version == active_version:
        return active_program
    if captured_version < active_version:
        historical = db.get_program_by_version(captured_version)
        if historical is not None:
            return historical
    raise ProgramVersionMismatchError(active_version)


def _now() -> datetime:
    """The single clock seam for sync validation; tests monkeypatch this."""
    return datetime.now(UTC)


def _parse_captured_at(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SessionSyncValidationError("captured_at must be an ISO instant.")
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError:
        raise SessionSyncValidationError("captured_at must be an ISO instant.") from None
    if parsed.tzinfo is None:
        raise SessionSyncValidationError("captured_at must include a timezone offset.")
    return parsed


def _performed_date_window(*, timezone: str, capture: datetime, current: datetime) -> tuple[date, date]:
    """The inclusive performed-date window for one capture instant (ADR 020/035).

    A performed date may be up to ``MAX_BACKDATE_DAYS`` before the capture's
    local date and never after it, nor after the player's local today. Both the
    entry path (ADR 033) and the correction path derive their bounds here, and
    the local dates come from the ADR 029 ``local_date_in`` helper, so there is
    one definition of the window.
    """
    capture_local = local_date_in(capture, timezone)
    local_today = local_date_in(current, timezone)
    earliest = capture_local - timedelta(days=MAX_BACKDATE_DAYS)
    latest = min(capture_local, local_today)
    return earliest, latest


def _validate_performed_within_window(performed: date, *, earliest: date, latest: date) -> None:
    """Refuses a performed date outside ``[earliest, latest]`` with the shared messages."""
    if performed > latest:
        raise SessionSyncValidationError(
            "performed_date cannot be after the workout was captured or in the future."
        )
    if performed < earliest:
        raise SessionSyncValidationError(
            f"performed_date cannot be more than {MAX_BACKDATE_DAYS} days before the workout was captured."
        )


def validate_sync_fields(
    performed_date: Any,
    performed_timezone: Any,
    captured_at: Any,
    *,
    now: datetime | None = None,
) -> tuple[date, str, datetime]:
    """Validates the offline-sync fields (ADR 020/033).

    ``performed_date`` must be a strict ``YYYY-MM-DD`` within the capture-anchored
    window: no more than three days before the local date of ``captured_at`` and
    never after it, nor after the player's local today. ``captured_at`` must be a
    timezone-aware ISO instant that is not in the future beyond a small clock
    skew. An unknown timezone is refused rather than guessed.
    """
    if not isinstance(performed_timezone, str) or not performed_timezone.strip():
        raise SessionSyncValidationError("A performed timezone is required.")
    try:
        ZoneInfo(performed_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise SessionSyncValidationError(f"Unknown timezone: {performed_timezone}.") from None

    try:
        performed = parse_iso_date(performed_date, "performed_date")
    except ValueError as exc:
        raise SessionSyncValidationError(str(exc)) from None
    captured = _parse_captured_at(captured_at)
    current = now or _now()
    if captured > current + CLOCK_SKEW:
        raise SessionSyncValidationError("captured_at cannot be in the future.")

    earliest, latest = _performed_date_window(
        timezone=performed_timezone, capture=captured, current=current
    )
    _validate_performed_within_window(performed, earliest=earliest, latest=latest)
    return performed, performed_timezone, captured


def _correction_timezone(performed_timezone: Any, schedule_timezone: str | None) -> str:
    """The session's performed timezone, else the player's schedule timezone, else UTC (ADR 029/035)."""
    if isinstance(performed_timezone, str) and performed_timezone.strip():
        return performed_timezone.strip()
    return schedule_timezone or "UTC"


def validate_performed_date_correction(
    performed_date: Any,
    *,
    session_date: Any,
    performed_timezone: Any,
    schedule_timezone: str | None,
    capture_instant: Any,
    now: datetime | None = None,
) -> tuple[date, date, str]:
    """Validates a performed-date correction against the same window as entry (ADR 020/035).

    The new date must be a strict ``YYYY-MM-DD`` within the shared capture-anchored
    window: no more than ``MAX_BACKDATE_DAYS`` before the capture's local date and
    never after it, nor after the player's local today (the session's performed
    timezone, else the player's schedule timezone, else UTC). The session itself
    is correctable only while its capture local date is within that window of the
    player's local today; otherwise it is history that can no longer be rewritten.

    Returns ``(new_date, previous_date, timezone)``.
    """
    try:
        performed = parse_iso_date(performed_date, "performed_date")
    except ValueError as exc:
        raise SessionSyncValidationError(str(exc)) from None
    try:
        previous = parse_iso_date(session_date, "session_date")
    except ValueError as exc:
        raise SessionSyncValidationError(str(exc)) from None

    timezone = _correction_timezone(performed_timezone, schedule_timezone)
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise SessionSyncValidationError(f"Unknown timezone: {timezone}.") from None

    captured = _parse_captured_at(capture_instant)
    current = now or _now()
    capture_local = local_date_in(captured, timezone)
    if (local_date_in(current, timezone) - capture_local).days > MAX_BACKDATE_DAYS:
        raise SessionCorrectionNotAllowedError(
            f"A performed date can be corrected only within {MAX_BACKDATE_DAYS} days of the workout."
        )

    earliest, latest = _performed_date_window(
        timezone=timezone, capture=captured, current=current
    )
    _validate_performed_within_window(performed, earliest=earliest, latest=latest)
    return performed, previous, timezone


def _evaluate_missed_days(db: Any, account_id: str) -> None:
    """Best-effort attendance refresh after a commit; never fails the workout commit (ADR 030)."""
    try:
        from service import missed_day_alerts

        missed_day_alerts.evaluate_for_ledger(db, account_id)
    except Exception:
        logger.exception("Missed-day alert evaluation raised unexpectedly after session commit")


def _evaluate_progression_alerts(
    db: Any,
    account_id: str,
    session_id: str,
    session_date: str,
    exercise_summaries: list[dict[str, Any]],
    fatigue_post: dict[str, Any],
) -> None:
    """Best-effort deload/regression alert evaluation after a commit (ADR 032).

    Catalog-only, so it is safe to run after the missed-day hook has unmounted the
    player's ledger; a failure never fails the workout commit.
    """
    try:
        from service import progression_alerts

        progression_alerts.evaluate_commit(
            db, account_id, session_id, session_date, exercise_summaries, fatigue_post
        )
    except Exception:
        logger.exception("Progression alert evaluation raised unexpectedly after session commit")


def _run_post_commit_hooks(
    db: Any,
    account_id: str | None,
    session_id: str,
    session_date: str,
    exercise_summaries: list[dict[str, Any]],
    fatigue_post: dict[str, Any],
) -> None:
    """Catalog hooks that run after the ledger transaction commits (ADR 030/032)."""
    if not account_id:
        return
    _evaluate_missed_days(db, account_id)
    _evaluate_progression_alerts(db, account_id, session_id, session_date, exercise_summaries, fatigue_post)


def _is_barbell(exercise: Any) -> bool:
    return "barbell" in exercise.exercise_name.lower() or "barbell" in str(getattr(exercise, "equipment", "")).lower()


def evaluate_fatigue(db: Any, trainee_id: str) -> dict[str, Any]:
    bind_user(db, trainee_id)
    return evaluate_systemic_fatigue(db)


def build_prescription(db: Any, trainee_id: str, day_plan: Any) -> dict[str, Any]:
    """Auto-regulated targets per exercise for the given training day."""
    bind_user(db, trainee_id)
    fatigue_info = evaluate_systemic_fatigue(db)
    targets = []
    for ex_idx, ex in enumerate(day_plan.exercises, start=1):
        is_barbell = _is_barbell(ex)
        effective_sets = ex.target_sets
        target_rpe_cap = ex.target_rpe or 8.5
        if fatigue_info["deload_recommended"]:
            effective_sets = max(1, round(ex.target_sets * fatigue_info["volume_multiplier"]))
            target_rpe_cap = min(target_rpe_cap, fatigue_info["intensity_cap_rpe"] or 10.0)
        last_perf = db.get_last_performance(ex.exercise_id)
        entry: dict[str, Any] = {
            "exercise_id": str(ex.exercise_id),
            "exercise_name": ex.exercise_name,
            "is_barbell": is_barbell,
            "effective_sets": effective_sets,
            "target_rpe_cap": target_rpe_cap,
            "last_perf": last_perf,
            "projected_weight": 20.0,
        }
        if last_perf:
            top_prev = max(last_perf, key=lambda s: s["weight_kg"])
            proj = project_next_load(
                last_weight=top_prev["weight_kg"],
                last_reps=top_prev["reps"],
                last_rpe=top_prev.get("rpe", 8.5),
                target_reps_min=ex.target_reps_min,
                target_reps_max=ex.target_reps_max,
                target_rpe=target_rpe_cap,
                equipment="barbell" if is_barbell else "other",
            )
            entry["projected_weight"] = proj["projected_weight"]
            entry["projection"] = proj
            delta = proj["delta_kg"]
            entry["large_jump"] = bool(
                delta >= 5.0 or (top_prev["weight_kg"] > 0 and (delta / top_prev["weight_kg"]) >= 0.10)
            )
        if is_barbell and entry["projected_weight"] > 0:
            entry["plates"] = calculate_barbell_plates(entry["projected_weight"])
        if ex_idx == 1 or ex.target_reps_min <= 8:
            entry["warmups"] = calculate_warmup_sets(entry["projected_weight"])
        targets.append(entry)
    return {"fatigue_info": fatigue_info, "targets": targets}


def _persist_session(
    db: Any,
    trainee_id: str,
    day_plan: Any,
    readiness: int,
    session_notes: str,
    sets_by_exercise: list[dict[str, Any]],
    *,
    session_id: str,
    now_iso: str,
    today_date: str,
    sync: SyncMetadata,
    active_program_version_at_sync: int | None = None,
) -> dict[str, Any]:
    """Writes one session and all of its derived records; the caller owns the transaction.

    Returns the response body. No ledger commit happens here, so the whole
    commit (session, sets, divergences, PRs, debrief, chat pointer) is atomic.
    ``active_program_version_at_sync`` is the version active when the commit
    landed, which may be newer than the captured ``sync.program_version`` for a
    historical-sync session (ADR 034).
    """
    profile = db.get_user_profile() or {}

    db.log_workout_session(
        session_id=session_id,
        session_date=today_date,
        split_name=day_plan.day_name,
        started_at=now_iso,
        completed_at=now_iso,
        readiness_score=readiness,
        notes=session_notes,
        client_session_id=sync.client_session_id,
        performed_timezone=sync.performed_timezone,
        program_version=sync.program_version,
        active_program_version_at_sync=active_program_version_at_sync,
        captured_at=sync.captured_at,
        uploaded_at=now_iso,
    )

    total_tonnage_kg = 0.0
    total_working_sets = 0
    exercise_summaries: list[dict[str, Any]] = []
    all_sets_to_batch: list[dict[str, Any]] = []
    performed: list[dict[str, str]] = []
    performed_ids: set[str] = set()

    for item in sets_by_exercise:
        ex_obj = item["exercise"]
        sets_data = item["sets"]
        prev_perf = item.get("previous_perf") or []
        working_sets = [s for s in sets_data if not s.get("is_warmup", False)]
        exercise_id = str(ex_obj.exercise_id)
        if working_sets and exercise_id not in performed_ids:
            performed_ids.add(exercise_id)
            performed.append({"exercise_id": exercise_id, "exercise_name": ex_obj.exercise_name})

        total_working_sets += len(working_sets)
        ex_volume = sum(s["weight_kg"] * s["reps"] for s in working_sets)
        total_tonnage_kg += ex_volume

        for idx, s in enumerate(sets_data, start=1):
            all_sets_to_batch.append(
                {
                    "id": str(uuid.uuid4()),
                    "session_id": session_id,
                    "exercise_id": str(ex_obj.exercise_id),
                    "set_index": idx,
                    "weight_kg": float(s["weight_kg"]),
                    "reps": int(s["reps"]),
                    "rpe": float(s["rpe"]),
                    "is_warmup": 1 if s.get("is_warmup") else 0,
                    "logged_at": now_iso,
                }
            )

        if not working_sets:
            continue
        top_set = max(working_sets, key=lambda x: x["weight_kg"])
        curr_e1rm = round(calculate_e1rm(top_set["weight_kg"], top_set["reps"], top_set["rpe"]), 2)

        next_proj = project_next_load(
            last_weight=top_set["weight_kg"],
            last_reps=top_set["reps"],
            last_rpe=top_set["rpe"],
            target_reps_min=ex_obj.target_reps_min,
            target_reps_max=ex_obj.target_reps_max,
            target_rpe=ex_obj.target_rpe or 8.5,
            equipment="barbell" if ("barbell" in ex_obj.exercise_name.lower()) else "other",
        )

        if prev_perf:
            prev_top = max(prev_perf, key=lambda x: x["weight_kg"])
            prev_e1rm = round(calculate_e1rm(prev_top["weight_kg"], prev_top["reps"], prev_top.get("rpe", 8.5)), 2)
            e1rm_delta: float | None = round(curr_e1rm - prev_e1rm, 2)
            load_delta: float | None = round(top_set["weight_kg"] - prev_top["weight_kg"], 2)
            reps_delta: int | None = top_set["reps"] - prev_top["reps"]

            if top_set["weight_kg"] > prev_top["weight_kg"]:
                status_badge, action = "LOAD INCREASE", "increase"
            elif top_set["reps"] > prev_top["reps"] and top_set["weight_kg"] >= prev_top["weight_kg"]:
                status_badge, action = "REP OVERLOAD", "increase"
            elif top_set["reps"] >= ex_obj.target_reps_max and top_set["rpe"] <= ex_obj.target_rpe:
                status_badge, action = "GRADUATED", "increase"
            elif top_set["rpe"] >= 10.0 and ex_obj.target_rpe <= 8.5:
                status_badge, action = "OVERSHOOT", "deload"
            else:
                status_badge, action = "CONSOLIDATING", "hold"
        else:
            e1rm_delta = load_delta = reps_delta = None
            status_badge, action = "BASELINE", "hold"

        if next_proj["status"] == "PROGRESSION_UP":
            target_text = f"Bracket ceiling reached. Advance load to {next_proj['projected_weight']} kg for {ex_obj.target_reps_min}–{ex_obj.target_reps_max} reps."
        elif next_proj["status"] == "DYNAMIC_UPSCALE":
            target_text = f"Velocity surplus detected. Step load up to {next_proj['projected_weight']} kg (+{next_proj['delta_kg']} kg)."
        elif next_proj["status"] == "RPE_OVERSHOOT_DELOAD":
            target_text = f"Exertion threshold exceeded. Deload to {next_proj['projected_weight']} kg to re-establish reserve."
        elif prev_perf:
            target_text = f"Consolidate at {top_set['weight_kg']} kg. Push for {min(top_set['reps'] + 1, ex_obj.target_reps_max)} reps @ RPE {ex_obj.target_rpe}."
        else:
            target_text = f"Baseline logged at {top_set['weight_kg']} kg. Target {ex_obj.target_reps_min}–{ex_obj.target_reps_max} reps next session."

        exercise_summaries.append(
            {
                "exercise_id": exercise_id,
                "name": ex_obj.exercise_name,
                "top_load": top_set["weight_kg"],
                "top_reps": top_set["reps"],
                "top_rpe": top_set["rpe"],
                "sets_completed": len(working_sets),
                "volume_load": ex_volume,
                "current_e1rm": curr_e1rm,
                "e1rm_delta": e1rm_delta,
                "load_delta": load_delta,
                "reps_delta": reps_delta,
                "action": action,
                "status_badge": status_badge,
                "projection_status": next_proj["status"],
                "target_text": target_text,
            }
        )

    db.log_workout_sets_batch(all_sets_to_batch)

    prescribed_ids = {str(ex.exercise_id) for ex in day_plan.exercises}
    divergences: list[dict[str, str]] = [
        {
            "kind": "skipped",
            "exercise_id": str(ex.exercise_id),
            "exercise_name": ex.exercise_name,
        }
        for ex in day_plan.exercises
        if str(ex.exercise_id) not in performed_ids
    ]
    divergences.extend(
        {
            "kind": "unplanned",
            "exercise_id": entry["exercise_id"],
            "exercise_name": entry["exercise_name"],
        }
        for entry in performed
        if entry["exercise_id"] not in prescribed_ids
    )
    seen_divergences: set[tuple[str, str]] = set()
    deduped_divergences: list[dict[str, str]] = []
    for divergence in divergences:
        key = (divergence["kind"], divergence["exercise_id"])
        if key not in seen_divergences:
            seen_divergences.add(key)
            deduped_divergences.append(divergence)
    divergences = deduped_divergences
    db.record_session_divergences(session_id, divergences, now_iso)

    pr_events: list[dict[str, Any]] = []
    for item in sets_by_exercise:
        ex_obj = item["exercise"]
        pr_events.extend(
            evaluate_session_prs(
                db,
                session_id,
                str(ex_obj.exercise_id),
                item["sets"],
                exercise_name=ex_obj.exercise_name,
                achieved_at=now_iso,
            )
        )

    fatigue_post = evaluate_systemic_fatigue(db)
    debrief_content = generate_session_debrief(
        split_name=day_plan.day_name,
        readiness=readiness,
        session_notes=session_notes,
        exercise_summaries=exercise_summaries,
        profile=profile,
        total_tonnage=total_tonnage_kg,
        total_sets=total_working_sets,
        fatigue_info=fatigue_post,
        pr_events=pr_events,
    )
    db.save_session_debrief(session_id, debrief_content)
    compact_pointer = (
        f"📋 **Session Logged:** {day_plan.day_name} ({today_date}) | "
        f"{total_working_sets} Sets | Volume: {total_tonnage_kg:,.1f} kg | "
        f"Readiness: {readiness}/5 | Saved to Ledger."
    )
    db.add_chat_message("assistant", compact_pointer)

    return {
        "session_id": session_id,
        "total_tonnage_kg": total_tonnage_kg,
        "total_working_sets": total_working_sets,
        "exercise_summaries": exercise_summaries,
        "debrief": debrief_content,
        "pointer": compact_pointer,
        "fatigue_post": fatigue_post,
        "new_prs": pr_events,
        "divergences": divergences,
        # Version visibility (ADR 034): what the draft was logged against vs.
        # the program active when the commit landed. ``is_historical_program``
        # is the explicit flag both the player and assigned coach render.
        "program_version": sync.program_version,
        "active_program_version_at_sync": active_program_version_at_sync,
        "is_historical_program": is_historical_program(
            sync.program_version, active_program_version_at_sync
        ),
    }


def _commit_outcome_from_row(row: dict[str, Any]) -> CommitOutcome:
    """Turns a stored ``session_commits`` row into the response it recorded."""
    return CommitOutcome(json.loads(row["response_json"]), created=False)


def committed_session(db: Any, client_session_id: str | None) -> CommitOutcome | None:
    """The exact stored outcome for a client session id, if one exists (ADR 020/033).

    Callers must use this to replay *before* any mutable catalog, day, or
    program validation: the stored response is the truth for a committed
    client session id, and a catalog or program change must never turn a retry
    into a 400/404/409.
    """
    if not client_session_id:
        return None
    existing = db.get_session_commit(client_session_id)
    return _commit_outcome_from_row(existing) if existing is not None else None


def session_state(db: Any, session_id: Any, body: dict[str, Any]) -> dict[str, Any]:
    """The stored commit body overlaid with the live session's corrected state (ADR 035).

    The idempotency record is immutable, so the reconciliation read overlays the
    session's current ``session_date``, ``edited_at``, and ``corrections``
    history (the same key the coach responses use). A body whose session is
    absent from this ledger is returned unchanged.
    """
    session = db.get_workout_session(session_id) if isinstance(session_id, str) else None
    if session is None:
        return body
    return {
        **body,
        "session_date": session["session_date"],
        "edited_at": session["edited_at"],
        "corrections": db.list_performed_date_corrections(session["session_id"]),
    }


def commit_session(
    db: Any,
    trainee_id: str,
    day_plan: Any,
    readiness: int,
    session_notes: str,
    sets_by_exercise: list[dict[str, Any]],
    session_id: str | None = None,
    now_iso: str | None = None,
    today_date: str | None = None,
    account_id: str | None = None,
    sync: SyncMetadata | None = None,
) -> CommitOutcome:
    """Persists a logged session and returns totals, per-movement analytics, debrief, and pointer.

    When the caller does not pin ``today_date``, the performed date is the
    player's local today from their schedule timezone (ADR 029/030), not the
    server clock, so attendance matches what the player experienced.

    All ledger writes happen in one transaction; post-commit catalog hooks run
    afterwards and are best-effort (ADR 030/032/033). This is the legacy,
    always-creates path (no idempotency record); ``created`` is always ``True``.
    """
    bind_user(db, trainee_id)
    sync = sync or SyncMetadata()
    session_id = session_id or str(uuid.uuid4())
    now_iso = now_iso or _now().isoformat()
    today_date = today_date or local_today(db, trainee_id).isoformat()

    with db.ledger_transaction():
        body = _persist_session(
            db,
            trainee_id,
            day_plan,
            readiness,
            session_notes,
            sets_by_exercise,
            session_id=session_id,
            now_iso=now_iso,
            today_date=today_date,
            sync=sync,
        )

    _run_post_commit_hooks(
        db, account_id, session_id, today_date, body["exercise_summaries"], body["fatigue_post"]
    )
    return CommitOutcome(body, created=True)


def commit_logged_session(
    db: Any,
    trainee_id: str,
    day_order: int,
    readiness: int,
    session_notes: str,
    sets_by_exercise: list[dict[str, Any]],
    *,
    sync: SyncMetadata,
    account_id: str | None = None,
    now_iso: str | None = None,
) -> CommitOutcome:
    """Idempotently commits one offline-captured workout (ADR 020/033/034).

    If ``client_session_id`` was already committed, the exact stored response is
    replayed and nothing is written. The active program is re-resolved inside
    the same ledger transaction (after ``BEGIN IMMEDIATE``), so a concurrent
    program change is caught rather than racing an earlier, outside-the-
    transaction check. A draft captured against the active version, or against
    an older version that still exists in the ledger, commits against the exact
    day plan it trained against; the active program is never rewritten. A
    captured version that is newer than the active one or absent from the
    ledger is refused with ``ProgramVersionMismatchError``. Concurrent
    duplicates are serialised by the unique index plus one transaction: the
    loser replays the winner's response. Post-commit hooks run only when this
    call performed the commit, for historical sessions too (ADR 034).
    """
    bind_user(db, trainee_id)
    client_session_id = sync.client_session_id
    replayed = committed_session(db, client_session_id)
    if replayed is not None:
        return replayed

    now_iso = now_iso or _now().isoformat()
    session_id = str(uuid.uuid4())
    try:
        with db.ledger_transaction():
            replayed = committed_session(db, client_session_id)
            if replayed is not None:
                return replayed

            program = db.get_active_program()
            if program is None:
                raise DayPlanNotFoundError(day_order)
            active_version = program.version
            resolved = resolve_sync_program(db, program, sync.program_version)
            day_plan = day_plan_from(resolved, day_order)

            body = _persist_session(
                db,
                trainee_id,
                day_plan,
                readiness,
                session_notes,
                sets_by_exercise,
                session_id=session_id,
                now_iso=now_iso,
                today_date=sync.performed_date,
                sync=sync,
                active_program_version_at_sync=active_version,
            )
            db.record_session_commit(client_session_id, session_id, json.dumps(body), now_iso)
            outcome = CommitOutcome(body, created=True)
    except sqlite3.IntegrityError:
        # A concurrent duplicate won the unique index; replay its response.
        existing = db.get_session_commit(client_session_id)
        if existing is None:
            raise
        return _commit_outcome_from_row(existing)

    _run_post_commit_hooks(
        db, account_id, session_id, sync.performed_date, outcome.body["exercise_summaries"], outcome.body["fatigue_post"]
    )
    return outcome


def correct_performed_date(
    db: Any,
    trainee_id: str,
    session_id: str,
    performed_date: Any,
    *,
    account_id: str,
    now_iso: str | None = None,
) -> dict[str, Any] | None:
    """Corrects one committed session's performed date (ADR 020/035).

    Returns the correction result, or ``None`` when the session is not in this
    player's ledger (the router maps that to 404). The session read and every
    validation run inside the same ``BEGIN IMMEDIATE`` ledger transaction that
    performs the write (mirroring ADR 034's resolve-inside-the-transaction
    rationale), so the date cannot be corrected against a session that changed
    under a concurrent commit. Correcting to the session's current date is an
    idempotent no-op checked before the recency/window validation, so an old
    session corrected to its own date returns unchanged. Otherwise the session's
    ``session_date`` is rewritten and ``edited_at`` is stamped, with an immutable
    correction row appended; ``uploaded_at`` and ``captured_at`` stay untouched.
    The stored idempotent commit response is never rewritten — the by-client-id
    read reflects the live session — and only the missed-day attendance hook
    re-runs, after the transaction exits, so a correction can resolve or open a
    missed-day alert. Progression alerts and PRs are intentionally not recomputed.
    """
    bind_user(db, trainee_id)
    now_iso = now_iso or _now().isoformat()

    with db.ledger_transaction():
        session = db.get_workout_session(session_id)
        if session is None:
            return None

        try:
            performed = parse_iso_date(performed_date, "performed_date")
        except ValueError as exc:
            raise SessionSyncValidationError(str(exc)) from None
        previous_date = session["session_date"]
        if performed.isoformat() == previous_date:
            return {
                "session_id": session_id,
                "session_date": previous_date,
                "previous_date": previous_date,
                "edited_at": session.get("edited_at"),
                "changed": False,
                "corrections": db.list_performed_date_corrections(session_id),
            }

        capture_instant = (
            session.get("captured_at") or session.get("uploaded_at") or session.get("started_at")
        )
        performed, previous, _timezone = validate_performed_date_correction(
            performed_date,
            session_date=previous_date,
            performed_timezone=session.get("performed_timezone"),
            schedule_timezone=latest_schedule_timezone(db, trainee_id),
            capture_instant=capture_instant,
        )

        corrected_date = performed.isoformat()
        db.update_session_performed_date(session_id, corrected_date, now_iso)
        db.record_performed_date_correction(
            session_id, previous.isoformat(), corrected_date, now_iso
        )
        corrections = db.list_performed_date_corrections(session_id)

    _evaluate_missed_days(db, account_id)
    return {
        "session_id": session_id,
        "session_date": corrected_date,
        "previous_date": previous.isoformat(),
        "edited_at": now_iso,
        "changed": True,
        "corrections": corrections,
    }
