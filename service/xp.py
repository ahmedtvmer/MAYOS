"""XP, ranks and the weekly-streak award (#743, #795).

XP rewards doing what the plan says, never raw intensity: there is no extra XP
for going heavier or harder, deload workouts earn full XP, and XP never
decreases. Awards are written once per session (and once per finished week for
the streak) in the ledger, so a commit replay, a draft sync or a later read
never awards twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

# Award values (owner decision, #743).
XP_PLANNED_WORKOUT = 5
XP_ALL_SETS = 2
XP_EFFORT_IN_RANGE = 1
XP_PER_RECORD = 2
MAX_RECORDS_PER_WORKOUT = 2
XP_CARDIO = 2
XP_WEEKLY_STREAK = 5

# A logged effort may sit this much above the target and still count as in
# range (RPE is logged in half steps).
EFFORT_TOLERANCE_RPE = 0.5
# A set logged with no effort counts as RPE 10 (#111).
UNRATED_SET_RPE = 10.0


@dataclass(frozen=True)
class Rank:
    rank_id: str
    name_en: str
    name_ar: str
    threshold: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.rank_id,
            "name_en": self.name_en,
            "name_ar": self.name_ar,
            "threshold": self.threshold,
        }


# Thresholds sized to about 8 XP per workout (ADR, #743).
RANKS: tuple[Rank, ...] = (
    Rank("rookie", "Rookie", "مبتدئ", 0),
    Rank("regular", "Regular", "منتظم", 80),
    Rank("committed", "Committed", "ملتزم", 240),
    Rank("dedicated", "Dedicated", "مثابر", 600),
    Rank("veteran", "Veteran", "محترف", 1200),
    Rank("elite", "Elite", "نخبة", 2400),
    Rank("legend", "Legend", "أسطورة", 4000),
)


def rank_for(xp_total: int) -> Rank:
    current = RANKS[0]
    for rank in RANKS:
        if xp_total >= rank.threshold:
            current = rank
    return current


def rank_by_id(rank_id: str | None) -> dict[str, Any] | None:
    """The rank's API shape for a cached rank id, or None when unknown."""
    for rank in RANKS:
        if rank.rank_id == rank_id:
            return rank.as_dict()
    return None


def next_rank_after(rank: Rank) -> Rank | None:
    index = RANKS.index(rank)
    return RANKS[index + 1] if index + 1 < len(RANKS) else None


def rank_progress(xp_total: int) -> dict[str, Any]:
    """The rank fields shared by the status read and the commit response."""
    total = max(0, int(xp_total))
    current = rank_for(total)
    upcoming = next_rank_after(current)
    return {
        "xp_total": total,
        "rank": current.as_dict(),
        "next_rank": upcoming.as_dict() if upcoming else None,
        "xp_into_rank": total - current.threshold,
        "xp_for_next_rank": (upcoming.threshold - current.threshold) if upcoming else None,
    }


@dataclass(frozen=True)
class SessionXpFacts:
    """Plain facts about one committed session used by the award rules."""

    planned: bool
    prescribed_sets: int | None
    target_rpe_by_exercise: dict[str, float]
    working_sets: list[dict[str, Any]]
    record_exercises: int
    has_cardio: bool


def _exercise_targets(exercise: Any) -> tuple[int, float]:
    groups = list(getattr(exercise, "set_groups", None) or [])
    if groups:
        sets = sum(int(group.sets) for group in groups)
        target = max(10.0 - float(group.target_rir) for group in groups)
        return sets, target
    return int(getattr(exercise, "target_sets", 0) or 0), float(exercise.target_rpe)


def day_plan_targets(day_plan: Any) -> tuple[int, dict[str, float]]:
    """Prescribed working sets and the per-exercise effort ceiling of a day."""
    total = 0
    targets: dict[str, float] = {}
    for exercise in getattr(day_plan, "exercises", None) or []:
        sets, target = _exercise_targets(exercise)
        total += sets
        key = str(exercise.exercise_id)
        targets[key] = max(target, targets.get(key, 0.0))
    return total, targets


def award_session(facts: SessionXpFacts) -> list[tuple[str, int]]:
    """The awards one counted session earns, as (kind, xp) pairs.

    Only rules a session meets produce an award; the saved summary shows a
    rule that was not met as +0 from the full rule list.
    """
    awards: list[tuple[str, int]] = []
    if facts.planned:
        awards.append(("planned_workout", XP_PLANNED_WORKOUT))
    working = facts.working_sets
    if facts.planned and facts.prescribed_sets and len(working) >= facts.prescribed_sets:
        awards.append(("all_sets", XP_ALL_SETS))
    if facts.planned and working and facts.target_rpe_by_exercise:
        fallback = max(facts.target_rpe_by_exercise.values())
        in_range = all(
            float(row["rpe"] if row.get("rpe") is not None else UNRATED_SET_RPE)
            <= facts.target_rpe_by_exercise.get(str(row["exercise_id"]), fallback)
            + EFFORT_TOLERANCE_RPE
            for row in working
        )
        if in_range:
            awards.append(("effort_in_range", XP_EFFORT_IN_RANGE))
    records = min(max(0, facts.record_exercises), MAX_RECORDS_PER_WORKOUT)
    if records:
        awards.append(("personal_record", XP_PER_RECORD * records))
    if facts.has_cardio:
        awards.append(("cardio", XP_CARDIO))
    return awards


def saturday_week_start(day: date) -> date:
    return day - timedelta(days=(day.weekday() - 5) % 7)


def _session_facts(ledger: Any, session: dict[str, Any], day_plan: Any | None) -> SessionXpFacts:
    session_id = str(session["session_id"])
    planned = day_plan is not None
    prescribed, targets = day_plan_targets(day_plan) if day_plan is not None else (None, {})
    return SessionXpFacts(
        planned=planned,
        prescribed_sets=prescribed,
        target_rpe_by_exercise=targets,
        working_sets=ledger.xp_session_working_sets(session_id),
        record_exercises=ledger.xp_session_record_exercises(session_id),
        has_cardio=ledger.xp_session_has_cardio(session_id),
    )


def _day_plan_for(ledger: Any, session: dict[str, Any], programs: dict[int, Any]) -> Any | None:
    version = session.get("program_version")
    day_order = session.get("program_day_order")
    if version is None or day_order is None:
        return None
    version = int(version)
    if version not in programs:
        programs[version] = ledger.get_program_by_version(version)
    program = programs[version]
    if program is None:
        return None
    week_order = int(session.get("program_week_order") or 1)
    for day in program.days:
        if day.day_order == int(day_order) and day.week_order == week_order:
            return day
    return None


def ensure_xp_current(
    ledger: Any,
    imported_workouts: int,
    local_today: date,
    now_iso: str | None = None,
    *,
    active_program: Any | None = None,
) -> None:
    """Awards XP for every committed session and finished week not yet processed.

    Idempotent: processed sessions and awarded weeks are never revisited. The
    first ``imported_workouts`` sessions by insertion are imported history and
    earn nothing, the same rule Checkpoints use. Only the first counted
    session on a local day earns workout XP. A finished week (before the
    current one) with at least one counted workout earns the streak award once.
    """
    now_iso = now_iso or datetime.now(UTC).isoformat()
    with ledger.ledger_transaction():
        sessions = ledger.list_sessions_for_xp()
        processed = ledger.xp_processed_session_ids()
        imported_ids = {
            str(row["session_id"]) for row in sessions[: max(0, int(imported_workouts))]
        }
        counted_dates = ledger.xp_counted_dates()
        # Reuse the program the caller already loaded, so a commit reads the
        # active program once (sessions of older versions load theirs).
        programs: dict[int, Any] = (
            {int(active_program.version): active_program}
            if active_program is not None and getattr(active_program, "version", None) is not None
            else {}
        )
        for session in sessions:
            session_id = str(session["session_id"])
            if session_id in processed:
                continue
            session_date = str(session["session_date"])
            if session_id in imported_ids or session_date in counted_dates:
                ledger.mark_xp_session(
                    session_id, counted=False, session_date=session_date, now_iso=now_iso
                )
                continue
            facts = _session_facts(ledger, session, _day_plan_for(ledger, session, programs))
            for kind, xp in award_session(facts):
                ledger.add_xp_award(kind, xp, now_iso=now_iso, session_id=session_id)
            ledger.mark_xp_session(
                session_id, counted=True, session_date=session_date, now_iso=now_iso
            )
            counted_dates.add(session_date)

        current_week = saturday_week_start(local_today)
        awarded_weeks = ledger.xp_awarded_weeks()
        finished_weeks = {
            saturday_week_start(date.fromisoformat(day))
            for day in counted_dates
        }
        for week in sorted(finished_weeks):
            if week < current_week and week.isoformat() not in awarded_weeks:
                ledger.add_xp_award(
                    "weekly_streak", XP_WEEKLY_STREAK, now_iso=now_iso,
                    week_start=week.isoformat(),
                )


AWARD_RULES: tuple[str, ...] = (
    "planned_workout",
    "all_sets",
    "effort_in_range",
    "personal_record",
    "cardio",
)


def commit_xp_summary(ledger: Any, session_id: str, xp_before: int) -> dict[str, Any]:
    """The commit response's XP block: this session's breakdown and any rank-up.

    Every rule is listed, a rule the session did not meet with 0 XP, so the
    saved summary can show +0 lines. A session that earned no workout XP
    (a second workout that day) reports ``counted`` false.
    """
    awards = {row["kind"]: row["xp"] for row in ledger.xp_awards_for_session(session_id)}
    counted = ledger.xp_session_counted(session_id) is True
    total = ledger.xp_total()
    before_rank = rank_for(xp_before)
    after_rank = rank_for(total)
    return {
        "counted": counted,
        "awarded": sum(awards.values()),
        "breakdown": [
            {"kind": kind, "xp": int(awards.get(kind, 0))} for kind in AWARD_RULES
        ],
        "rank_up": after_rank.as_dict() if after_rank.threshold > before_rank.threshold else None,
        **rank_progress(total),
    }
