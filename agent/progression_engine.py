from typing import Optional, Union, Tuple, Dict, Any, List
from datetime import datetime, timezone, timedelta
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)

EQUIPMENT_INCREMENTS = {
    "barbell": 2.5,
    "olympic barbell": 2.5,
    "smith machine": 2.5,
    "dumbbell": 2.0,
    "cable": 2.5,
    "machine": 2.5,
    "leverage machine": 2.5,
    "bodyweight": 1.0,
    "weighted bodyweight": 1.25,
}

def calculate_e1rm(weight_kg: float, reps: int, rpe: float) -> float:
    if reps <= 0 or weight_kg <= 0:
        return 0.0
    effective_reps = reps + (10.0 - min(max(rpe, 6.0), 10.0))
    return weight_kg * (1.0 + (effective_reps / 30.0))

def round_to_increment(val: float, increment: float) -> float:
    return round(val / increment) * increment

def project_next_load(
    last_weight: float,
    last_reps: int,
    last_rpe: float,
    target_reps_min: Optional[int] = None,
    target_reps_max: Optional[int] = None,
    target_reps: Optional[Union[int, Tuple[int, int], str]] = None,
    target_rpe: float = 8.5,
    equipment: str = "barbell"
) -> Dict[str, Any]:
    if target_reps is not None:
        if isinstance(target_reps, tuple) and len(target_reps) == 2:
            target_reps_min = target_reps_min or target_reps[0]
            target_reps_max = target_reps_max or target_reps[1]
        elif isinstance(target_reps, int):
            target_reps_min = target_reps_min or target_reps
            target_reps_max = target_reps_max or target_reps
        elif isinstance(target_reps, str) and "-" in target_reps:
            parts = target_reps.split("-")
            target_reps_min = target_reps_min or int(parts[0].strip())
            target_reps_max = target_reps_max or int(parts[1].strip())

    target_reps_min = target_reps_min or 8
    target_reps_max = target_reps_max or 12

    if last_weight <= 0 or last_reps <= 0:
        return {"projected_weight": max(last_weight, 20.0), "delta_kg": 0.0, "e1rm": 0.0, "status": "INITIAL_CALIBRATION"}

    increment = 2.5
    for key, inc in EQUIPMENT_INCREMENTS.items():
        if key in equipment.lower():
            increment = inc
            break

    current_e1rm = calculate_e1rm(last_weight, last_reps, last_rpe)

    if last_rpe >= 10.0 and target_rpe <= 8.5:
        target_load = max(last_weight - increment, increment)
        return {"projected_weight": target_load, "delta_kg": -increment, "e1rm": round(current_e1rm, 2), "status": "RPE_OVERSHOOT_DELOAD"}

    if last_reps >= target_reps_max and last_rpe <= target_rpe:
        target_load = last_weight + increment
        return {"projected_weight": target_load, "delta_kg": increment, "e1rm": round(current_e1rm, 2), "status": "PROGRESSION_UP"}

    if last_rpe <= (target_rpe - 1.5):
        target_eff_reps = last_reps + (10.0 - target_rpe)
        raw_projected = current_e1rm / (1.0 + (target_eff_reps / 30.0))
        target_load = max(round_to_increment(raw_projected, increment), last_weight + increment)
        return {"projected_weight": target_load, "delta_kg": round(target_load - last_weight, 2), "e1rm": round(current_e1rm, 2), "status": "DYNAMIC_UPSCALE"}

    return {"projected_weight": last_weight, "delta_kg": 0.0, "e1rm": round(current_e1rm, 2), "status": "LOAD_MAINTAINED"}

def normalize_muscle_group(muscle_name: str) -> str:
    m = (muscle_name or "").strip().lower()
    if any(k in m for k in ["pectoral", "chest"]):
        return "Chest"
    if any(k in m for k in ["lat", "upper back", "trap", "rhomboid", "spine", "back"]):
        return "Back"
    if any(k in m for k in ["quad", "rectus femoris", "vastus"]):
        return "Quads"
    if any(k in m for k in ["hamstring", "biceps femoris", "glute"]):
        return "Hamstrings & Glutes"
    if any(k in m for k in ["delt", "shoulder"]):
        return "Shoulders"
    if any(k in m for k in ["bicep", "brachialis"]):
        return "Biceps"
    if any(k in m for k in ["tricep"]):
        return "Triceps"
    if any(k in m for k in ["calve", "soleus", "gastrocnemius"]):
        return "Calves"
    if any(k in m for k in ["ab", "core", "oblique"]):
        return "Abs"
    return "Other"

def get_weekly_muscle_volume(db: DatabaseManager, days_lookback: int = 7) -> Dict[str, float]:
    cursor = db.conn.cursor()
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days_lookback)).isoformat()[:10]

    cursor.execute("""
        SELECT ws.exercise_id, e.target_muscle, e.body_part
        FROM workout_sets ws
        JOIN workout_sessions s ON ws.session_id = s.id
        JOIN catalog.exercises e ON ws.exercise_id = e.id
        WHERE s.session_date >= ? AND ws.is_warmup = 0
    """, (cutoff_date,))
    working_sets = cursor.fetchall()

    volume_tally: Dict[str, float] = {
        "Chest": 0.0, "Back": 0.0, "Shoulders": 0.0,
        "Quads": 0.0, "Hamstrings & Glutes": 0.0,
        "Biceps": 0.0, "Triceps": 0.0, "Calves": 0.0, "Abs": 0.0
    }

    if not working_sets:
        return volume_tally

    distinct_ex_ids = list({row[0] for row in working_sets})
    placeholders = ",".join("?" for _ in distinct_ex_ids)
    cursor.execute(
        f"SELECT exercise_id, muscle FROM catalog.exercise_secondary_muscles WHERE exercise_id IN ({placeholders})",
        distinct_ex_ids
    )
    secondaries_map: Dict[str, List[str]] = {}
    for ex_id, muscle in cursor.fetchall():
        secondaries_map.setdefault(ex_id, []).append(muscle)

    for ex_id, target_muscle, body_part in working_sets:
        primary_group = normalize_muscle_group(target_muscle)
        if primary_group == "Other":
            primary_group = normalize_muscle_group(body_part)

        if primary_group in volume_tally:
            volume_tally[primary_group] += 1.0

        matched_secondaries = {
            normalize_muscle_group(m) for m in secondaries_map.get(ex_id, [])
        }
        for sec_group in matched_secondaries:
            if sec_group != "Other" and sec_group != primary_group and sec_group in volume_tally:
                volume_tally[sec_group] += 0.5

    return {k: round(v, 1) for k, v in volume_tally.items()}

def get_exercise_progression_history(db: DatabaseManager, exercise_id: str) -> List[Dict[str, Any]]:
    cursor = db.conn.cursor()
    cursor.execute("""
        SELECT s.session_date, ws.weight_kg, ws.reps, ws.rpe, ws.set_index
        FROM workout_sets ws
        JOIN workout_sessions s ON ws.session_id = s.id
        WHERE ws.exercise_id = ? AND ws.is_warmup = 0
        ORDER BY s.session_date ASC, ws.weight_kg DESC
    """, (exercise_id,))
    
    history_by_date: Dict[str, Dict[str, Any]] = {}
    for session_date, weight, reps, rpe, _ in cursor.fetchall():
        if session_date not in history_by_date:
            history_by_date[session_date] = {
                "date": session_date,
                "weight_kg": weight,
                "reps": reps,
                "rpe": rpe or 8.5,
                "e1rm": round(calculate_e1rm(weight, reps, rpe or 8.5), 2)
            }
    return list(history_by_date.values())

def get_progression_signals(db: DatabaseManager) -> str:
    cursor = db.user_conn.cursor()
    active_program = db.get_active_program()
    target_ceilings = {}
    if active_program:
        for day in active_program.days:
            for ex in day.exercises:
                target_ceilings[str(ex.exercise_id)] = (ex.target_reps_min, ex.target_reps_max, ex.target_rpe or 8.5)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()[:10]
    cursor.execute("""
        SELECT DISTINCT ws.exercise_id, e.name, e.equipment
        FROM workout_sets ws
        JOIN workout_sessions s ON ws.session_id = s.id
        JOIN catalog.exercises e ON ws.exercise_id = e.id
        WHERE s.session_date >= ? AND ws.is_warmup = 0
        LIMIT 5
    """, (cutoff,))

    signals = []
    for ex_id, name, eq in cursor.fetchall():
        history = get_exercise_progression_history(db, ex_id)
        if len(history) >= 2:
            last = history[-1]
            rmin, rmax, rpe_target = target_ceilings.get(str(ex_id), (8, 12, 8.5))
            proj = project_next_load(
                last_weight=last["weight_kg"], last_reps=last["reps"], last_rpe=last["rpe"],
                target_reps_min=rmin, target_reps_max=rmax, target_rpe=rpe_target,
                equipment=eq or "barbell"
            )
            if proj["status"] in ("PROGRESSION_UP", "DYNAMIC_UPSCALE") and proj["delta_kg"] > 0:
                signals.append(f"{name}: +{proj['delta_kg']}kg target ({proj['projected_weight']}kg)")
            elif len(history) >= 3 and history[-1]["e1rm"] <= history[-3]["e1rm"]:
                signals.append(f"{name}: Stalled (3 exposures @ ~{last['weight_kg']}kg)")

    return "Progression Targets: " + " | ".join(signals[:3]) if signals else "Progression: Establishing baseline loads across routine."

def evaluate_systemic_fatigue(db_manager) -> Dict[str, Any]:
    cursor = db_manager.user_conn.cursor()
    cursor.execute("""
        SELECT id, session_date, readiness_score 
        FROM workout_sessions 
        WHERE readiness_score IS NOT NULL
        ORDER BY session_date DESC, rowid DESC 
        LIMIT 5
    """)
    recent_sessions = cursor.fetchall()

    default_result = {
        "deload_recommended": False,
        "severity": "NORMAL",
        "reason": "Fatigue within recoverable limits.",
        "volume_multiplier": 1.0,
        "intensity_cap_rpe": None,
        "recent_readiness_avg": None
    }
    if not recent_sessions:
        return default_result

    readiness_scores = [row[2] for row in recent_sessions]
    last_3_readiness = readiness_scores[:3]
    avg_readiness_3 = sum(last_3_readiness) / len(last_3_readiness)
    default_result["recent_readiness_avg"] = round(avg_readiness_3, 2)

    session_ids = [row[0] for row in recent_sessions[:3]]
    placeholders = ",".join("?" for _ in session_ids)
    cursor.execute(f"SELECT session_id, rpe FROM workout_sets WHERE session_id IN ({placeholders}) AND is_warmup = 0 AND rpe IS NOT NULL", session_ids)
    sets_data = cursor.fetchall()

    high_rpe_count = sum(1 for s in sets_data if s[1] >= 9.5)
    total_working_sets = len(sets_data)
    overshoot_ratio = (high_rpe_count / total_working_sets) if total_working_sets > 0 else 0.0

    if len(last_3_readiness) >= 3 and avg_readiness_3 <= 2.0:
        return {
            "deload_recommended": True, "severity": "HIGH",
            "reason": f"Rolling readiness crash (avg {avg_readiness_3:.1f}/5 across last 3 sessions).",
            "volume_multiplier": 0.5, "intensity_cap_rpe": 7.0,
            "recent_readiness_avg": round(avg_readiness_3, 2)
        }

    if readiness_scores[0] == 1:
        return {
            "deload_recommended": True, "severity": "HIGH",
            "reason": "Acute readiness floor (1/5 logged). Systemic recovery compromised.",
            "volume_multiplier": 0.5, "intensity_cap_rpe": 7.0,
            "recent_readiness_avg": round(avg_readiness_3, 2)
        }

    if total_working_sets >= 6 and overshoot_ratio >= 0.50 and avg_readiness_3 <= 3.0:
        return {
            "deload_recommended": True, "severity": "MODERATE",
            "reason": f"High exertion density ({overshoot_ratio*100:.0f}% of recent sets >= RPE 9.5) alongside declining readiness.",
            "volume_multiplier": 0.6, "intensity_cap_rpe": 8.0,
            "recent_readiness_avg": round(avg_readiness_3, 2)
        }

    return default_result