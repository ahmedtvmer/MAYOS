"""Workout prescription and session-commit logic (moved verbatim from the UI layer)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from agent.debrief import generate_session_debrief
from agent.progression_engine import (
    calculate_e1rm,
    evaluate_session_prs,
    evaluate_systemic_fatigue,
    project_next_load,
)
from core.warmup import calculate_warmup_sets
from service._base import bind_user
from utils.plate_calculator import calculate_barbell_plates


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
) -> dict[str, Any]:
    """Persists a logged session and returns totals, per-movement analytics, debrief, and pointer."""
    bind_user(db, trainee_id)
    profile = db.get_user_profile() or {}
    session_id = session_id or str(uuid.uuid4())
    now_iso = now_iso or datetime.now(UTC).isoformat()
    today_date = today_date or datetime.now().strftime("%Y-%m-%d")

    db.log_workout_session(
        session_id=session_id,
        session_date=today_date,
        split_name=day_plan.day_name,
        started_at=now_iso,
        completed_at=now_iso,
        readiness_score=readiness,
        notes=session_notes,
    )

    total_tonnage_kg = 0.0
    total_working_sets = 0
    exercise_summaries: list[dict[str, Any]] = []
    all_sets_to_batch: list[dict[str, Any]] = []

    for item in sets_by_exercise:
        ex_obj = item["exercise"]
        sets_data = item["sets"]
        prev_perf = item.get("previous_perf") or []
        working_sets = [s for s in sets_data if not s.get("is_warmup", False)]

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
                    "is_warmup": 0,
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
                "target_text": target_text,
            }
        )

    db.log_workout_sets_batch(all_sets_to_batch)

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
    }
