import math
from typing import Dict, List, Any
from datetime import datetime, timezone, timedelta
import sqlite3

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
    """Calculates RPE-adjusted estimated 1RM using modified Epley/Wathan formulation."""
    if reps <= 0 or weight_kg <= 0:
        return 0.0
    effective_reps = reps + (10.0 - min(max(rpe, 6.0), 10.0))
    return weight_kg * (1.0 + (effective_reps / 30.0))

def round_to_increment(val: float, increment: float) -> float:
    """Snaps calculated values to physical equipment plate/pin increments."""
    return round(val / increment) * increment

def project_next_load(
    last_weight: float,
    last_reps: int,
    last_rpe: float,
    target_reps_min: int,
    target_reps_max: int,
    target_rpe: float,
    equipment: str = "barbell"
) -> Dict[str, Any]:
    """
    Hypertrophy double progression with dynamic RPE auto-regulation:
    - Maintains weight while accumulating reps within [min, max].
    - Increments load when the rep ceiling is reached at target RPE.
    - Upscales load early if RPE indicates surplus capacity (RIR >= 3).
    - Protects against overshoots (RPE 10).
    """
    if last_weight <= 0 or last_reps <= 0:
        return {
            "projected_weight": max(last_weight, 20.0),
            "delta_kg": 0.0,
            "e1rm": 0.0,
            "status": "INITIAL_CALIBRATION"
        }

    eq_lower = equipment.lower()
    increment = 2.5
    for key, inc in EQUIPMENT_INCREMENTS.items():
        if key in eq_lower:
            increment = inc
            break

    current_e1rm = calculate_e1rm(last_weight, last_reps, last_rpe)

    # 1. Overshoot Protection: Absolute failure on sub-maximal prescription
    if last_rpe >= 10.0 and target_rpe <= 8.5:
        target_load = max(last_weight - increment, increment)
        return {
            "projected_weight": target_load,
            "delta_kg": -increment,
            "e1rm": round(current_e1rm, 2),
            "status": "RPE_OVERSHOOT_DELOAD"
        }

    # 2. Ceiling Cleared: Hit top of rep bracket at or below target RPE -> Progression Up
    if last_reps >= target_reps_max and last_rpe <= target_rpe:
        target_load = last_weight + increment
        return {
            "projected_weight": target_load,
            "delta_kg": increment,
            "e1rm": round(current_e1rm, 2),
            "status": "PROGRESSION_UP"
        }

    # 3. Surplus Reserve: Moved the weight with RPE <= 7.0 (RIR >= 3)
    if last_rpe <= (target_rpe - 1.5):
        # Project target load for the SAME rep count at target RPE
        target_eff_reps = last_reps + (10.0 - target_rpe)
        raw_projected = current_e1rm / (1.0 + (target_eff_reps / 30.0))
        target_load = round_to_increment(raw_projected, increment)
        target_load = max(target_load, last_weight + increment)
        return {
            "projected_weight": target_load,
            "delta_kg": round(target_load - last_weight, 2),
            "e1rm": round(current_e1rm, 2),
            "status": "DYNAMIC_UPSCALE"
        }

    # 4. Standard Working Bracket: Maintain load, drive rep accumulation
    return {
        "projected_weight": last_weight,
        "delta_kg": 0.0,
        "e1rm": round(current_e1rm, 2),
        "status": "LOAD_MAINTAINED"
    }

def get_weekly_muscle_volume(db: DatabaseManager, days_lookback: int = 7) -> Dict[str, float]:
    """
    Aggregates working sets across a rolling window.
    Direct Target Muscle = 1.0 Set Credit
    Secondary / Synergist Muscle = 0.5 Set Credit
    """
    cursor = db.conn.cursor()
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days_lookback)).isoformat()[:10]

    # Query all working sets inside lookback window
    query = """
        SELECT 
            ws.exercise_id,
            e.target_muscle,
            ws.session_id
        FROM workout_sets ws
        JOIN workout_sessions s ON ws.session_id = s.id
        JOIN catalog.exercises e ON ws.exercise_id = e.id
        WHERE s.session_date >= ? AND ws.is_warmup = 0
    """
    cursor.execute(query, (cutoff_date,))
    working_sets = cursor.fetchall()

    volume_tally: Dict[str, float] = {}

    for ex_id, target_muscle, _ in working_sets:
        # 1. Primary muscle credit
        prim = target_muscle.strip().lower()
        volume_tally[prim] = volume_tally.get(prim, 0.0) + 1.0

        # 2. Secondary muscles credit (0.5 sets each)
        cursor.execute(
            "SELECT muscle FROM catalog.exercise_secondary_muscles WHERE exercise_id = ?",
            (ex_id,)
        )
        sec_rows = cursor.fetchall()
        for (sec_m,) in sec_rows:
            sec = sec_m.strip().lower()
            volume_tally[sec] = volume_tally.get(sec, 0.0) + 0.5

    return {k: round(v, 1) for k, v in sorted(volume_tally.items(), key=lambda x: x[1], reverse=True)}

def get_exercise_progression_history(db: DatabaseManager, exercise_id: str) -> List[Dict[str, Any]]:
    """Fetches chronological top-set history and e1RM for charting any exercise in the ledger."""
    cursor = db.conn.cursor()
    query = """
        SELECT 
            s.session_date,
            ws.weight_kg,
            ws.reps,
            ws.rpe,
            ws.set_index
        FROM workout_sets ws
        JOIN workout_sessions s ON ws.session_id = s.id
        WHERE ws.exercise_id = ? AND ws.is_warmup = 0
        ORDER BY s.session_date ASC, ws.weight_kg DESC
    """
    cursor.execute(query, (exercise_id,))
    rows = cursor.fetchall()

    history_by_date: Dict[str, Dict[str, Any]] = {}
    for session_date, weight, reps, rpe, set_idx in rows:
        # Retain top load per session date
        if session_date not in history_by_date:
            e1rm = calculate_e1rm(weight, reps, rpe or 8.5)
            history_by_date[session_date] = {
                "date": session_date,
                "weight_kg": weight,
                "reps": reps,
                "rpe": rpe or 8.5,
                "e1rm": round(e1rm, 2)
            }

    return list(history_by_date.values())

def get_progression_signals(db: DatabaseManager) -> str:
    """Extracts compact progression and plateau signals for prompt telemetry."""
    cursor = db.conn.cursor()
    
    # Inspect distinct exercises performed in the last 30 days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()[:10]
    cursor.execute("""
        SELECT DISTINCT ws.exercise_id, e.name, e.equipment
        FROM workout_sets ws
        JOIN workout_sessions s ON ws.session_id = s.id
        JOIN catalog.exercises e ON ws.exercise_id = e.id
        WHERE s.session_date >= ? AND ws.is_warmup = 0
        LIMIT 5
    """, (cutoff,))
    exercises = cursor.fetchall()

    signals = []
    for ex_id, name, eq in exercises:
        history = get_exercise_progression_history(db, ex_id)
        if len(history) >= 2:
            last = history[-1]
            prev = history[-2]
            proj = project_next_load(
                last["weight_kg"], last["reps"], last["rpe"], 
                target_reps=last["reps"], target_rpe=8.5, equipment=eq
            )
            if proj["delta_kg"] > 0:
                signals.append(f"{name}: +{proj['delta_kg']}kg target ({proj['projected_weight']}kg)")
            elif len(history) >= 3 and history[-1]["e1rm"] <= history[-3]["e1rm"]:
                signals.append(f"{name}: Stalled (3 exposures @ ~{last['weight_kg']}kg)")

    if not signals:
        return "Progression: Establishing baseline loads across routine."
    return "Progression Targets: " + " | ".join(signals[:3])


def evaluate_systemic_fatigue(db_manager) -> Dict[str, Any]:
    """
    Evaluates systemic fatigue dynamically across historical sessions.
    
    Heuristic Triggers:
    1. Readiness Crash: Rolling 3-session average readiness <= 2.0 / 5.0.
    2. Chronic Exertion: 4+ consecutive sessions with average logged RPE >= 9.0.
    3. Low Readiness Spike: Last session readiness == 1 / 5 with high tonnage.
    
    Returns structured recommendations without mutating database tables.
    """
    cursor = db_manager.user_conn.cursor()
    
    # 1. Fetch the last 5 sessions with readiness scores
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

    # 2. Check sets from recent sessions for exertion/overshoot data
    session_ids = [row[0] for row in recent_sessions[:3]]
    placeholders = ",".join("?" for _ in session_ids)
    
    cursor.execute(f"""
        SELECT session_id, rpe 
        FROM workout_sets 
        WHERE session_id IN ({placeholders}) AND is_warmup = 0 AND rpe IS NOT NULL
    """, session_ids)
    sets_data = cursor.fetchall()

    high_rpe_count = sum(1 for s in sets_data if s[1] >= 9.5)
    total_working_sets = len(sets_data)
    overshoot_ratio = (high_rpe_count / total_working_sets) if total_working_sets > 0 else 0.0

    # --- Evaluation Heuristics ---

    # Trigger A: Systemic Readiness Crash
    if len(last_3_readiness) >= 3 and avg_readiness_3 <= 2.0:
        return {
            "deload_recommended": True,
            "severity": "HIGH",
            "reason": f"Rolling readiness crash (avg {avg_readiness_3:.1f}/5 across last 3 sessions).",
            "volume_multiplier": 0.5,
            "intensity_cap_rpe": 7.0,
            "recent_readiness_avg": round(avg_readiness_3, 2)
        }

    # Trigger B: Critical Readiness Floor
    if readiness_scores[0] == 1:
        return {
            "deload_recommended": True,
            "severity": "HIGH",
            "reason": "Acute readiness floor (1/5 logged). Systemic recovery compromised.",
            "volume_multiplier": 0.5,
            "intensity_cap_rpe": 7.0,
            "recent_readiness_avg": round(avg_readiness_3, 2)
        }

    # Trigger C: Excessive Accumulation of RPE 9.5-10 Sets
    if total_working_sets >= 6 and overshoot_ratio >= 0.50 and avg_readiness_3 <= 3.0:
        return {
            "deload_recommended": True,
            "severity": "MODERATE",
            "reason": f"High exertion density ({overshoot_ratio*100:.0f}% of recent sets >= RPE 9.5) alongside declining readiness.",
            "volume_multiplier": 0.6,
            "intensity_cap_rpe": 8.0,
            "recent_readiness_avg": round(avg_readiness_3, 2)
        }

    return default_result