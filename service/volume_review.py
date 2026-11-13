"""Deterministic per-muscle working-set reviews (#234)."""

import json
import math
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from agent.program_rationale import CHANGE_VOLUME_REVIEW
from agent.progression_engine import set_e1rm
from agent.ProgramState import program_exercise_working_sets
from agent.program_blueprints import SLOT_STAPLES, experience_level_for_training_age
from agent.focus_muscles import FOCUS_MULTIPLIER, FOCUS_REVIEW_MUSCLES
from agent.program_weeks import flatten_program_days, normalize_program_weeks
from utils.equipment_access import equipment_access_allows

BASE_CEILINGS = {"beginner": 8, "intermediate": 10, "advanced": 13}
REMOVAL_FLOOR = 4


def _review_focus_muscles(program: Any) -> set[str]:
    """Map version-pinned Weak point keys to Volume review muscle groups."""
    rationale = getattr(program, "program_rationale", None) or {}
    return {
        review_muscle
        for item in rationale.get("focus_muscles", [])
        if isinstance(item, dict) and item.get("muscle")
        for review_muscle in FOCUS_REVIEW_MUSCLES.get(str(item["muscle"]).strip().lower(), set())
    }


def review_facts(ledger: Any, program: Any, profile: dict[str, Any], as_of: date) -> dict[str, Any]:
    """Return a deterministic review payload without writing the ledger."""
    active_version = int(program.version)
    changed = date.fromisoformat(str(program.created_at)[:10]) if program.created_at else as_of
    next_date = as_of + timedelta(weeks=1)
    elapsed_weeks = max(0, (as_of - changed).days // 7)
    if as_of < changed + timedelta(weeks=4):
        return {"eligible": False, "next_eligible_date": next_date.isoformat(), "muscles": []}

    current_week = ledger.get_program_position(program).current_week
    program_weeks = normalize_program_weeks(program)
    current_days = _current_week_days(program_weeks, current_week)
    history_rows = ledger.volume_review_workout_rows(
        active_version, changed.isoformat(), as_of.isoformat()
    )
    credits = _exercise_credits(
        ledger, current_days, [str(row["exercise_id"]) for row in history_rows]
    )
    sets_by_muscle: dict[str, float] = {}
    exercises_by_muscle: dict[str, list[tuple[Any, Any, str, float]]] = {}
    for day in current_days:
        for ex in day["exercises"]:
            exercise_id = str(ex["exercise_id"])
            working_sets = program_exercise_working_sets(ex)
            for muscle, attribution in credits.get(exercise_id, {}).items():
                credit = float(attribution["credit"])
                if credit <= 0:
                    continue
                sets_by_muscle[muscle] = sets_by_muscle.get(muscle, 0.0) + working_sets * credit
                exercises_by_muscle.setdefault(muscle, []).append((day, ex, exercise_id, credit))
    by_muscle, sessions = _history_by_muscle(history_rows, credits)
    adherence = _adherence(ledger, active_version, changed, as_of, elapsed_weeks, program.weekly_frequency)
    experience = float(profile.get("training_age_years") or 0)
    level = experience_level_for_training_age(experience)
    focus_muscles = _review_focus_muscles(program)
    results = []
    for muscle in sorted(sets_by_muscle):
        muscle_rows = by_muscle.get(muscle, [])
        exposure_ids = {str(row["session_id"]) for row in muscle_rows}
        if len(exposure_ids) < 4:
            continue
        dated = sorted(muscle_rows, key=lambda row: (row["session_date"], row["logged_at"]))
        midpoint = changed + timedelta(days=(as_of - changed).days // 2)
        trend = _trend_for_muscle(dated, midpoint)
        if trend is None:
            continue
        muscle_sessions = [sessions[sid] for sid in exposure_ids if sid in sessions]
        low_readiness = sum(int(s.get("readiness_score") or 4) <= 2 for s in muscle_sessions) >= max(1, len(muscle_sessions) // 2)
        overshoot_sessions = {
            str(row["session_id"])
            for row in muscle_rows
            if float(row.get("rpe") or 0) >= 9.5
        }
        verdict, delta, reason = _verdict(
            muscle, trend, adherence, low_readiness, len(overshoot_sessions),
            sets_by_muscle[muscle], level, muscle.strip().lower() in focus_muscles,
        )
        placements = exercises_by_muscle[muscle]
        edits = _place_delta(placements, delta)
        placed_sets = _placed_delta(placements, edits)
        placed_credit = _credited_placed_delta(placements, edits)
        if delta > placed_credit:
            extra = _second_staple(
                ledger,
                program,
                placements,
                credits,
                muscle,
                delta - placed_credit,
                profile.get("equipment_access"), current_week,
            )
            if extra:
                edits.append(extra)
                added_sets = int(extra["add_exercise"]["target_sets"])
                placed_sets += added_sets
        if delta and not placed_sets:
            continue
        actual_delta = placed_sets if delta > 0 else -placed_sets if delta < 0 else 0
        results.append({"muscle": muscle, "verdict": verdict, "reason": reason, "set_delta": actual_delta, "edits": edits, "weekly_sets": sets_by_muscle[muscle]})
    eligible = bool(results)
    return {"eligible": eligible, "next_eligible_date": next_date.isoformat(), "muscles": results}


def _current_week_days(program_weeks: list[dict[str, Any]], current_week: int) -> list[dict[str, Any]]:
    return next(
        (week["days"] for week in program_weeks if int(week["week_order"]) == current_week),
        program_weeks[0]["days"] if program_weeks else [],
    )


def _exercise_credits(
    ledger: Any, days: list[dict[str, Any]], extra_ids: list[str] | None = None
) -> dict[str, dict[str, dict[str, Any]]]:
    exercise_ids = {str(ex["exercise_id"]) for day in days for ex in day["exercises"]}
    exercise_ids.update(str(item) for values in SLOT_STAPLES.values() for item in values)
    exercise_ids.update(str(item) for item in (extra_ids or ()) if item)
    if not exercise_ids:
        return {}
    return ledger.volume_review_exercise_credits(sorted(exercise_ids))


def _history_by_muscle(
    rows: list[dict[str, Any]],
    credits: dict[str, dict[str, dict[str, Any]]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    by_muscle: dict[str, list[dict[str, Any]]] = {}
    sessions: dict[str, dict[str, Any]] = {}
    for row in rows:
        exercise_credits = credits.get(str(row["exercise_id"]), {})
        session_id = str(row["session_id"])
        sessions[session_id] = row
        for muscle, attribution in exercise_credits.items():
            if float(attribution["credit"]) > 0:
                by_muscle.setdefault(muscle, []).append(row)
    return by_muscle, sessions


def _adherence(ledger: Any, version: int, start: date, end: date, weeks: int, frequency: int) -> float:
    planned = max(1, weeks * int(frequency))
    done = ledger.volume_review_workout_count(version, start.isoformat(), end.isoformat())
    return float(done) / planned


def _verdict(
    muscle: str,
    trend: str,
    adherence: float,
    low_readiness: bool,
    overshoot_sessions: int,
    weekly_sets: float,
    level: str,
    focus: bool = False,
) -> tuple[str, int, str]:
    ceiling = round(BASE_CEILINGS[level] * FOCUS_MULTIPLIER) if focus else BASE_CEILINGS[level]
    floor = math.ceil(REMOVAL_FLOOR * FOCUS_MULTIPLIER) if focus else REMOVAL_FLOOR
    if adherence < .75:
        return "low_adherence", 0, "Consistency comes first; complete at least 75% of planned sessions before changing volume."
    if trend == "progressing":
        return "progressing", 0, f"{muscle} is progressing on its working sets; keep volume steady."
    if trend == "regressing" or (trend == "flat" and (low_readiness or overshoot_sessions >= 2)):
        delta = -min(2, max(0, weekly_sets - floor))
        if delta == 0:
            return "at_floor", 0, f"{muscle} is already at the {floor}-set weekly floor; keep volume steady."
        return "under_recovered", delta, f"{muscle} performance is {trend} with recovery strain; reduce weekly work."
    delta = max(0, min(2, ceiling - weekly_sets))
    if delta == 0:
        return "at_ceiling", 0, f"{muscle} is already at its weekly set ceiling; keep volume steady."
    return "stalled", delta, f"{muscle} has stalled despite good recovery; add weekly working sets."


def _trend_for_muscle(rows: list[dict[str, Any]], midpoint: date) -> str | None:
    """Compare each exercise with itself across the two review windows."""
    halves: dict[str, tuple[list[float], list[float]]] = {}
    for row in rows:
        weight = float(row["weight_kg"] or 0)
        load_kind = "bodyweight_reps" if weight == 0 else "weighted_e1rm"
        key = f"{row['exercise_id']}:{load_kind}"
        earlier, later = halves.setdefault(key, ([], []))
        is_earlier = str(row["session_date"])[:10] <= midpoint.isoformat()
        score = set_e1rm(weight, int(row["reps"]), row.get("rpe")) if weight > 0 else float(row["reps"])
        (earlier if is_earlier else later).append(score)
    changes = []
    for earlier, later in halves.values():
        old, new = max(earlier, default=0), max(later, default=0)
        if old and new:
            changes.append((new - old) / old)
    if not changes:
        return None
    change = sum(changes) / len(changes)
    return "progressing" if change > .015 else "regressing" if change < -.015 else "flat"


def _placed_delta(placements: list[tuple[Any, Any, str, float]], edits: list[dict[str, Any]]) -> int:
    original = {
        (int(day["week_order"]), int(day["day_order"]), exercise_id): program_exercise_working_sets(exercise)
        for day, exercise, exercise_id, _credit in placements
    }
    return sum(
        abs(int(edit["target_sets"]) - original[(edit["week_order"], edit["day_order"], edit["exercise_id"])])
        for edit in edits if "exercise_id" in edit
    )


def _credited_placed_delta(
    placements: list[tuple[Any, Any, str, float]], edits: list[dict[str, Any]]
) -> float:
    original = {
        (int(day["week_order"]), int(day["day_order"]), exercise_id): (
            program_exercise_working_sets(exercise), credit
        )
        for day, exercise, exercise_id, credit in placements
    }
    return sum(
        abs(int(edit["target_sets"]) - original[(edit["week_order"], edit["day_order"], edit["exercise_id"])][0])
        * original[(edit["week_order"], edit["day_order"], edit["exercise_id"])][1]
        for edit in edits if "exercise_id" in edit
    )


def _place_delta(exercises: list[tuple[Any, Any, str, float]], delta: int) -> list[dict[str, Any]]:
    edits = []
    ordered = list(exercises if delta >= 0 else reversed(exercises))
    remaining = abs(delta)
    for day, exercise, exercise_id, credit in ordered:
        current = program_exercise_working_sets(exercise)
        minimum = _minimum_exercise_working_sets(exercise)
        capacity = max(0, 3 - current) if delta > 0 else max(0, current - minimum)
        change = min(int(remaining / credit + 1e-9), capacity) if credit > 0 else 0
        if change:
            edits.append({"week_order": int(day["week_order"]), "day_order": int(day["day_order"]), "day_name": day["day_name"], "exercise_id": exercise_id, "target_sets": current + change if delta > 0 else current - change})
            remaining -= change * credit
        if not remaining:
            break
    return edits


def _minimum_exercise_working_sets(exercise: dict[str, Any]) -> int:
    groups = exercise.get("set_groups") or []
    return 1 + sum(int(group["sets"]) for group in groups[1:]) if groups else 1


def _second_staple(
    ledger: Any,
    program: Any,
    placements: list[tuple[Any, Any, str, float]],
    credits: dict[str, dict[str, dict[str, Any]]],
    muscle: str,
    remaining: float,
    equipment_access: str | None,
    current_week: int,
) -> dict[str, Any] | None:
    """Put remaining added work on the next curated Staple on another day."""
    present = {eid for _, _, eid, _credit in placements}
    for source_day, source, source_id, _source_credit in placements:
        source_slot = str(source.get("slot_key") or "")
        staple_lists = [SLOT_STAPLES[source_slot]] if source_slot in SLOT_STAPLES else list(SLOT_STAPLES.values())
        next_ids = []
        for staples in staple_lists:
            try:
                next_ids.extend(staples[staples.index(source_id) + 1 :])
            except ValueError:
                next_ids.extend(staples)
        for staple_id in next_ids:
            staple_credit = float(credits.get(staple_id, {}).get(muscle, {}).get("credit", 0))
            if staple_id in present or staple_credit <= 0:
                continue
            row = ledger.volume_review_staple(staple_id)
            if row is None or not equipment_access_allows(equipment_access, row["equipment"]):
                continue
            target_day = next(
                (
                    day for day in flatten_program_days(normalize_program_weeks(program))
                    if int(day["week_order"]) == current_week
                    and int(day["day_order"]) != int(source_day["day_order"])
                    and int(day["week_order"]) == int(source_day["week_order"])
                ),
                None,
            )
            if target_day is None:
                continue
            return {
                "week_order": int(target_day["week_order"]),
                "day_order": int(target_day["day_order"]),
                "day_name": target_day["day_name"],
                "add_exercise": {
                    "exercise_id": staple_id,
                    "exercise_name": str(row["name"]),
                    "target_sets": min(math.ceil(remaining / staple_credit), 3),
                    "target_reps_min": int(source["target_reps_min"]),
                    "target_reps_max": int(source["target_reps_max"]),
                    "target_rpe": float(source["target_rpe"]),
                    "rest_seconds": int(source["rest_seconds"]),
                    "notes": "",
                    "slot_key": source.get("slot_key"),
                    "warmup_sets": 0,
                },
            }
    return None


def evaluate_review(ledger: Any, program: Any, profile: dict[str, Any], as_of: date) -> dict[str, Any] | None:
    """Persist at most one review per active version/date; safe on commit retries."""
    existing = ledger.get_volume_review(int(program.version), as_of.isoformat())
    if existing:
        return None if existing["status"] == "deferred" else _review_dict(existing)
    prior = ledger.latest_volume_review(int(program.version))
    if prior and (
        prior["status"] == "pending"
        or str(prior["next_eligible_date"]) > as_of.isoformat()
    ):
        return None
    facts = review_facts(ledger, program, profile, as_of)
    if not facts["eligible"]:
        review_id = str(uuid.uuid4())
        ledger.save_volume_review({
            "id": review_id, "program_version": int(program.version), "review_date": as_of.isoformat(),
            "next_eligible_date": facts["next_eligible_date"], "status": "deferred",
            "payload_json": "[]", "created_at": datetime.now().isoformat(),
        })
        return None
    has_changes = any(item["set_delta"] and item["edits"] for item in facts["muscles"])
    status = "pending" if has_changes else "informational"
    review_id = str(uuid.uuid4())
    ledger.save_volume_review({
        "id": review_id, "program_version": int(program.version), "review_date": as_of.isoformat(),
        "next_eligible_date": facts["next_eligible_date"], "status": status,
        "payload_json": json.dumps(facts["muscles"], ensure_ascii=False), "created_at": datetime.now().isoformat(),
    })
    return {"review_id": review_id, "program_version": int(program.version), "review_date": as_of.isoformat(), "next_eligible_date": facts["next_eligible_date"], "status": status, "muscles": facts["muscles"]}


def _review_dict(row: Any) -> dict[str, Any]:
    return {
        "review_id": str(row["id"]),
        "program_version": int(row["program_version"]),
        "review_date": row["review_date"],
        "next_eligible_date": row["next_eligible_date"],
        "status": row["status"],
        "muscles": json.loads(row["payload_json"]),
    }


def list_pending(ledger: Any, active_version: int) -> list[dict[str, Any]]:
    rows = ledger.list_volume_reviews(active_version)
    return [_review_dict(row) for row in rows]


def accept_review(db: Any, ledger: Any, account_id: str, review_id: str) -> dict[str, Any]:
    return _decide_review(db, ledger, account_id, review_id, "accepted")


def dismiss_review(db: Any, ledger: Any, account_id: str, review_id: str) -> dict[str, Any]:
    return _decide_review(db, ledger, account_id, review_id, "dismissed")


def _decide_review(db: Any, ledger: Any, account_id: str, review_id: str, status: str) -> dict[str, Any]:
    from service.programs import player_controls_program
    if not player_controls_program(db, ledger, account_id):
        raise ValueError("coach_controlled")
    with ledger.ledger_transaction():
        row = ledger.get_volume_review_by_id(review_id)
        allowed_statuses = {"pending"} if status == "accepted" else {"pending", "informational"}
        if row is None or row["status"] not in allowed_statuses:
            raise ValueError("review_not_pending")
        current = ledger.get_active_program()
        if current is None or int(current.version) != int(row["program_version"]):
            raise ValueError("program_changed")
        if status == "accepted":
            payload = json.loads(row["payload_json"])
            if not any(muscle["edits"] for muscle in payload):
                raise ValueError("review_not_pending")
            program_data = current.model_dump()
            weeks = normalize_program_weeks(program_data)
            program_data["weeks"] = weeks
            program_data["days"] = flatten_program_days(weeks)
            _apply_edits(program_data, payload)
            program_data["days"] = flatten_program_days(program_data["weeks"])
            from service.program_rationale_changes import (
                carry_program_rationale,
                occurrence_mappings_for_days,
            )
            changes_by_target: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
            for muscle in payload:
                for edit in muscle["edits"]:
                    day = _find_program_day(program_data, edit)
                    week_order = int(day.get("week_order", edit.get("week_order", 1)))
                    day_order = int(day.get("day_order", edit.get("day_order", 1)))
                    if "add_exercise" in edit:
                        added = edit["add_exercise"]
                        position = next(
                            index for index, exercise in enumerate(day["exercises"], 1)
                            if exercise is added
                        )
                        changes_by_target[(week_order, day_order, position)] = [{"code": CHANGE_VOLUME_REVIEW, "params": {
                            "from_sets": 0, "to_sets": int(added.get("target_sets", 0)), "review_id": review_id,
                        }}]
                        continue
                    if "exercise_id" not in edit:
                        continue
                    exercise_id = str(edit["exercise_id"])
                    old_week = next((item for item in normalize_program_weeks(current)
                                     if int(item["week_order"]) == week_order), None)
                    old_day = next((item for item in old_week["days"]
                                    if int(item["day_order"]) == day_order), None) if old_week else None
                    old_ex = next((ex for ex in (old_day or {}).get("exercises", [])
                                   if str(ex["exercise_id"]) == exercise_id), None)
                    if old_ex is not None:
                        before = int(old_ex.get("target_sets", 0))
                        after = int(edit["target_sets"])
                        position = next(index for index, ex in enumerate(day["exercises"], 1)
                                        if str(ex["exercise_id"]) == exercise_id)
                        changes_by_target[(week_order, day_order, position)] = [{"code": CHANGE_VOLUME_REVIEW, "params": {
                            "from_sets": before, "to_sets": after, "review_id": review_id,
                        }}]
            old_days = flatten_program_days(normalize_program_weeks(current))
            new_days = flatten_program_days(normalize_program_weeks(program_data))
            mappings = occurrence_mappings_for_days(
                old_days, new_days, changes_by_target=changes_by_target
            )
            carry_program_rationale(current, program_data, occurrence_mappings=mappings)
            program_data.pop("created_at", None)
            ledger.save_training_program(program_data, published_by_coach_account_id=None, starting_position=ledger.get_program_position(current))
        ledger.set_volume_review_status(review_id, status, datetime.now().isoformat())
    return {"review_id": review_id, "status": status}


def _apply_edits(program_data: dict[str, Any], payload: list[dict[str, Any]]) -> None:
    for muscle in payload:
        for edit in muscle["edits"]:
            day = _find_program_day(program_data, edit)
            if "add_exercise" in edit:
                day["exercises"].append(edit["add_exercise"])
                continue
            for exercise in day["exercises"]:
                if str(exercise["exercise_id"]) == edit["exercise_id"]:
                    exercise["target_sets"] = edit["target_sets"]
                    if exercise.get("set_groups"):
                        others = sum(
                            int(group["sets"]) for group in exercise["set_groups"][1:]
                        )
                        exercise["set_groups"][0]["sets"] = max(
                            1, int(edit["target_sets"]) - others
                        )
                        exercise["target_sets"] = exercise["set_groups"][0]["sets"]
                    break


def _find_program_day(program_data: dict[str, Any], edit: dict[str, Any]) -> dict[str, Any]:
    if program_data.get("weeks"):
        return next(
            day for week in program_data["weeks"]
            if int(week["week_order"]) == edit["week_order"]
            for day in week["days"] if int(day["day_order"]) == edit["day_order"]
        )
    return next(
        day for day in program_data["days"]
        if int(day.get("week_order", 1)) == edit["week_order"]
        and int(day["day_order"]) == edit["day_order"]
    )
