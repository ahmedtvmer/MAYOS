"""Deterministic per-muscle working-set reviews (#234)."""

import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from agent.progression_engine import set_e1rm
from agent.ProgramState import program_exercise_working_sets
from agent.program_blueprints import SLOT_STAPLES, experience_level_for_training_age
from agent.program_weeks import flatten_program_days, normalize_program_weeks
from utils.equipment_access import equipment_access_allows

CEILINGS = {"beginner": 8, "intermediate": 10, "advanced": 13}


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
    targets = _exercise_targets(ledger, current_days)
    sets_by_muscle: dict[str, int] = {}
    exercises_by_muscle: dict[str, list[tuple[Any, Any, str]]] = {}
    for day in current_days:
        for ex in day["exercises"]:
            exercise_id = str(ex["exercise_id"])
            muscle = targets.get(exercise_id)
            if muscle:
                working_sets = program_exercise_working_sets(ex)
                sets_by_muscle[muscle] = sets_by_muscle.get(muscle, 0) + working_sets
                exercises_by_muscle.setdefault(muscle, []).append((day, ex, exercise_id))
    by_muscle, sessions = _history_by_muscle(ledger, active_version, changed, as_of, targets)
    adherence = _adherence(ledger, active_version, changed, as_of, elapsed_weeks, program.weekly_frequency)
    experience = float(profile.get("training_age_years") or 0)
    level = experience_level_for_training_age(experience)
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
            sets_by_muscle[muscle], level,
        )
        placements = exercises_by_muscle[muscle]
        edits = _place_delta(placements, delta)
        placed = _placed_delta(placements, edits)
        if delta > placed:
            extra = _second_staple(
                ledger,
                program,
                placements,
                targets,
                muscle,
                delta - placed,
                profile.get("equipment_access"), current_week,
            )
            if extra:
                edits.append(extra)
                placed += int(extra["add_exercise"]["target_sets"])
        if delta and not placed:
            continue
        actual_delta = placed if delta > 0 else -placed if delta < 0 else 0
        results.append({"muscle": muscle, "verdict": verdict, "reason": reason, "set_delta": actual_delta, "edits": edits, "weekly_sets": sets_by_muscle[muscle]})
    eligible = bool(results)
    return {"eligible": eligible, "next_eligible_date": next_date.isoformat(), "muscles": results}


def _current_week_days(program_weeks: list[dict[str, Any]], current_week: int) -> list[dict[str, Any]]:
    return next(
        (week["days"] for week in program_weeks if int(week["week_order"]) == current_week),
        program_weeks[0]["days"] if program_weeks else [],
    )


def _exercise_targets(ledger: Any, days: list[dict[str, Any]]) -> dict[str, str | None]:
    exercise_ids = {str(ex["exercise_id"]) for day in days for ex in day["exercises"]}
    exercise_ids.update(str(item) for values in SLOT_STAPLES.values() for item in values)
    if not exercise_ids:
        return {}
    return ledger.volume_review_exercise_targets(sorted(exercise_ids))


def _history_by_muscle(
    ledger: Any, version: int, start: date, end: date, targets: dict[str, str | None]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    rows = ledger.volume_review_workout_rows(version, start.isoformat(), end.isoformat())
    by_muscle: dict[str, list[dict[str, Any]]] = {}
    sessions: dict[str, dict[str, Any]] = {}
    for row in rows:
        muscle = targets.get(str(row["exercise_id"]))
        if not muscle:
            continue
        session_id = str(row["session_id"])
        sessions[session_id] = row
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
    weekly_sets: int,
    level: str,
) -> tuple[str, int, str]:
    if adherence < .75:
        return "low_adherence", 0, "Consistency comes first; complete at least 75% of planned sessions before changing volume."
    if trend == "progressing":
        return "progressing", 0, f"{muscle} is progressing on its working sets; keep volume steady."
    if trend == "regressing" or (trend == "flat" and (low_readiness or overshoot_sessions >= 2)):
        delta = -min(2, max(0, weekly_sets - 4))
        if delta == 0:
            return "at_floor", 0, f"{muscle} is already at the four-set weekly floor; keep volume steady."
        return "under_recovered", delta, f"{muscle} performance is {trend} with recovery strain; reduce weekly work."
    delta = max(0, min(2, CEILINGS[level] - weekly_sets))
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


def _placed_delta(placements: list[tuple[Any, Any, str]], edits: list[dict[str, Any]]) -> int:
    original = {
        (int(day["week_order"]), int(day["day_order"]), exercise_id): program_exercise_working_sets(exercise)
        for day, exercise, exercise_id in placements
    }
    return sum(
        abs(int(edit["target_sets"]) - original[(edit["week_order"], edit["day_order"], edit["exercise_id"])])
        for edit in edits if "exercise_id" in edit
    )


def _place_delta(exercises: list[tuple[Any, Any, str]], delta: int) -> list[dict[str, Any]]:
    edits = []
    ordered = list(exercises if delta >= 0 else reversed(exercises))
    remaining = abs(delta)
    for day, exercise, exercise_id in ordered:
        current = program_exercise_working_sets(exercise)
        minimum = _minimum_exercise_working_sets(exercise)
        capacity = max(0, 3 - current) if delta > 0 else max(0, current - minimum)
        change = min(remaining, capacity)
        if change:
            edits.append({"week_order": int(day["week_order"]), "day_order": int(day["day_order"]), "day_name": day["day_name"], "exercise_id": exercise_id, "target_sets": current + change if delta > 0 else current - change})
            remaining -= change
        if not remaining:
            break
    return edits


def _minimum_exercise_working_sets(exercise: dict[str, Any]) -> int:
    groups = exercise.get("set_groups") or []
    return 1 + sum(int(group["sets"]) for group in groups[1:]) if groups else 1


def _second_staple(
    ledger: Any,
    program: Any,
    placements: list[tuple[Any, Any, str]],
    targets: dict[str, str | None],
    muscle: str,
    remaining: int,
    equipment_access: str | None,
    current_week: int,
) -> dict[str, Any] | None:
    """Put remaining added work on the next curated Staple on another day."""
    present = {eid for _, _, eid in placements}
    for source_day, source, source_id in placements:
        source_slot = str(source.get("slot_key") or "")
        staple_lists = [SLOT_STAPLES[source_slot]] if source_slot in SLOT_STAPLES else list(SLOT_STAPLES.values())
        next_ids = []
        for staples in staple_lists:
            try:
                next_ids.extend(staples[staples.index(source_id) + 1 :])
            except ValueError:
                next_ids.extend(staples)
        for staple_id in next_ids:
            if staple_id in present or targets.get(staple_id) != muscle:
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
                    "target_sets": min(remaining, 3),
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
