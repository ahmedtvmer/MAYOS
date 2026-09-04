import os
from typing import Dict, List, Any
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_ollama import ChatOllama
from agent.ProgramState import DynamicSplitPlan, CustomDayPlan
from database.database_manager import DatabaseManager

load_dotenv()
db = DatabaseManager()
llm = ChatOllama(model=os.getenv("LLM"), temperature=0.0)

# -------------------------------------------------------------------------
# Muscle Slang to Database Clause Translation Layer
# -------------------------------------------------------------------------
SLANG_TO_SQL_MAP = {
    # Lower Body
    "quads": "LOWER(target_muscle) = 'quads'",
    "hamstrings": "LOWER(target_muscle) = 'hamstrings'",
    "glutes": "LOWER(target_muscle) = 'glutes'",
    "calves": "LOWER(target_muscle) = 'calves' OR LOWER(body_part) = 'lower legs'",
    
    # Upper Body Pull
    "lats": "LOWER(target_muscle) = 'lats'",
    "upper back": "LOWER(target_muscle) IN ('upper back', 'traps', 'spine')",
    "biceps": "LOWER(target_muscle) IN ('biceps', 'brachialis')",
    
    # Upper Body Push
    "chest": "LOWER(target_muscle) = 'pectorals' OR LOWER(body_part) = 'chest'",
    "side delts": "LOWER(name) LIKE '%lateral raise%' OR (LOWER(target_muscle) = 'delts' AND LOWER(name) LIKE '%side%')",
    "rear delts": "LOWER(name) LIKE '%rear delt%' OR LOWER(name) LIKE '%face pull%'",
    "front delts": "LOWER(target_muscle) = 'delts' AND LOWER(name) LIKE '%press%'",
    "triceps": "LOWER(target_muscle) = 'triceps'",
    
    # Core
    "abs": "LOWER(target_muscle) = 'abs' OR LOWER(body_part) = 'waist'",
}

COMPOUND_KEYWORDS = [
    "press", "row", "squat", "deadlift", "pull-up", "chin-up", 
    "dip", "lunge", "leg press", "hack squat", "pulldown"
]

EXCLUDED_TERMS = [
    "stretch", "yoga", "warm-up", "jump", "quick feet", "bike", 
    "hop", "run", "reach", "twist", "tilt", "roll", "walk"
]

# -------------------------------------------------------------------------
# Rep Corridor Rules (Biomechanical Bounds)
# -------------------------------------------------------------------------
REP_WINDOWS = {
    "low": {
        "compound": (5, 8),
        "isolation": (8, 12),
    },
    "balanced": {
        "compound": (6, 10),
        "isolation": (10, 15),
    },
    "high": {
        "compound": (8, 12),
        "isolation": (12, 20),
    },
}

def get_target_rep_window(mechanic: str, rep_preference: str = "balanced") -> tuple[int, int]:
    """Resolves safe rep boundaries based on movement mechanic and user preference."""
    pref = rep_preference.lower() if rep_preference in REP_WINDOWS else "balanced"
    return REP_WINDOWS[pref].get(mechanic, (8, 12))

# -------------------------------------------------------------------------
# Dynamic Split Presets & LLM Fallback
# -------------------------------------------------------------------------
SYSTEM_SPLIT_PROMPT = """You are an expert biomechanics and hypertrophy coach.
Convert the user's split preference into a structured training week.

Rules:
1. Day Count: The number of days MUST equal exactly {frequency} (hard limit: max 5 days).
2. Permitted Targets: Use ONLY targets from this explicit list:
   'quads', 'hamstrings', 'glutes', 'calves', 'chest', 'lats', 'upper back', 'side delts', 'rear delts', 'triceps', 'biceps', 'abs'.
3. Lower/Leg Day Balancing:
   - You MAY append low-fatigue upper isolations ('side delts', 'biceps', 'triceps', 'abs') to lower/leg days.
   - NEVER assign upper compound targets ('chest', 'lats', 'upper back') to a lower day.
4. Fatigue Management: Avoid heavy spinal compounds for back and lower body on consecutive days.
5. Provide 4 to 5 distinct target muscles per day to avoid session volume padding.
"""

def get_default_split(frequency: int, gender: str = "male") -> DynamicSplitPlan:
    is_female = (gender or "").lower() == "female"

    if is_female:
        presets = {
            1: DynamicSplitPlan(
                split_name="Full Body (Glute Specialized)",
                days=[
                    CustomDayPlan(
                        day_order=1,
                        day_name="Full Body",
                        target_body_parts=["glutes", "hamstrings", "quads", "lats", "abs"]
                    )
                ]
            ),
            2: DynamicSplitPlan(
                split_name="Lower (Glute Bias) / Upper & Core",
                days=[
                    CustomDayPlan(day_order=1, day_name="Lower (Glute & Quad)", target_body_parts=["glutes", "quads", "hamstrings", "calves", "abs"]),
                    CustomDayPlan(day_order=2, day_name="Upper & Glute Pump", target_body_parts=["lats", "upper back", "chest", "side delts", "glutes"])
                ]
            ),
            3: DynamicSplitPlan(
                split_name="Glute Hypertrophy Tri-Phase",
                days=[
                    CustomDayPlan(day_order=1, day_name="Lower A (Glute & Quad)", target_body_parts=["glutes", "quads", "calves", "lats", "abs"]),
                    CustomDayPlan(day_order=2, day_name="Upper & Posture", target_body_parts=["lats", "upper back", "chest", "side delts", "rear delts"]),
                    CustomDayPlan(day_order=3, day_name="Lower B (Glute & Hamstring)", target_body_parts=["glutes", "hamstrings", "glutes", "quads", "abs"])
                ]
            ),
            4: DynamicSplitPlan(
                split_name="Lower Body & Glute Specialization",
                days=[
                    CustomDayPlan(day_order=1, day_name="Lower 1 (Glute & Quad Bias)", target_body_parts=["glutes", "quads", "hamstrings", "calves", "abs"]),
                    CustomDayPlan(day_order=2, day_name="Upper (Back & Delts Focus)", target_body_parts=["lats", "upper back", "chest", "side delts", "triceps"]),
                    CustomDayPlan(day_order=3, day_name="Lower 2 (Glute & Hamstring Bias)", target_body_parts=["glutes", "hamstrings", "quads", "glutes", "calves"]),
                    CustomDayPlan(day_order=4, day_name="Full Body (Glute & Core Finisher)", target_body_parts=["glutes", "lats", "side delts", "hamstrings", "abs"])
                ]
            ),
            5: DynamicSplitPlan(
                split_name="5-Day Glute & Physique Specialization",
                days=[
                    CustomDayPlan(day_order=1, day_name="Glutes & Quads", target_body_parts=["glutes", "quads", "calves", "abs"]),
                    CustomDayPlan(day_order=2, day_name="Upper (Back & Shoulders)", target_body_parts=["lats", "upper back", "chest", "side delts"]),
                    CustomDayPlan(day_order=3, day_name="Glutes & Hamstrings", target_body_parts=["glutes", "hamstrings", "glutes", "calves"]),
                    CustomDayPlan(day_order=4, day_name="Upper & Core", target_body_parts=["lats", "upper back", "side delts", "abs"]),
                    CustomDayPlan(day_order=5, day_name="Glute Focus & Legs", target_body_parts=["glutes", "quads", "hamstrings", "abs"])
                ]
            )
        }
        return presets[frequency]

    # Male Defaults
    presets = {
        1: DynamicSplitPlan(
            split_name="Consolidated Full Body",
            days=[
                CustomDayPlan(day_order=1, day_name="Full Body", target_body_parts=["quads", "chest", "lats", "hamstrings", "side delts"])
            ]
        ),
        2: DynamicSplitPlan(
            split_name="Full Body A/B",
            days=[
                CustomDayPlan(day_order=1, day_name="Full Body A", target_body_parts=["quads", "chest", "upper back", "hamstrings", "triceps"]),
                CustomDayPlan(day_order=2, day_name="Full Body B", target_body_parts=["hamstrings", "lats", "chest", "side delts", "biceps"])
            ]
        ),
        3: DynamicSplitPlan(
            split_name="Full Body Tri-Phase",
            days=[
                CustomDayPlan(day_order=1, day_name="Full Body A", target_body_parts=["quads", "chest", "lats", "calves", "triceps"]),
                CustomDayPlan(day_order=2, day_name="Full Body B", target_body_parts=["hamstrings", "upper back", "side delts", "abs", "biceps"]),
                CustomDayPlan(day_order=3, day_name="Full Body C", target_body_parts=["quads", "chest", "lats", "hamstrings", "side delts"])
            ]
        ),
        4: DynamicSplitPlan(
            split_name="Upper / Lower (Arms & Delts Augmented)",
            days=[
                CustomDayPlan(day_order=1, day_name="Upper 1", target_body_parts=["chest", "upper back", "lats", "side delts", "triceps"]),
                CustomDayPlan(day_order=2, day_name="Lower 1", target_body_parts=["quads", "hamstrings", "calves", "abs", "side delts"]),
                CustomDayPlan(day_order=3, day_name="Upper 2", target_body_parts=["chest", "lats", "upper back", "rear delts", "biceps"]),
                CustomDayPlan(day_order=4, day_name="Lower 2", target_body_parts=["hamstrings", "quads", "glutes", "calves", "biceps"])
            ]
        ),
        5: DynamicSplitPlan(
            split_name="Hybrid PPL / Upper-Lower",
            days=[
                CustomDayPlan(day_order=1, day_name="Push", target_body_parts=["chest", "side delts", "triceps"]),
                CustomDayPlan(day_order=2, day_name="Pull", target_body_parts=["lats", "upper back", "rear delts", "biceps"]),
                CustomDayPlan(day_order=3, day_name="Legs", target_body_parts=["quads", "hamstrings", "calves", "abs"]),
                CustomDayPlan(day_order=4, day_name="Upper", target_body_parts=["chest", "lats", "upper back", "side delts", "biceps"]),
                CustomDayPlan(day_order=5, day_name="Lower", target_body_parts=["quads", "hamstrings", "glutes", "calves"])
            ]
        )
    }
    return presets[frequency]

def resolve_split(frequency: int, preference: str | None = None, gender: str = "male") -> DynamicSplitPlan:
    clamped_freq = min(max(int(frequency), 1), 5)
    if not preference or preference.strip().lower() in ["standard", "default", "none", "balanced"]:
        return get_default_split(clamped_freq, gender=gender)

    structured_llm = llm.with_structured_output(DynamicSplitPlan)
    gender_context = "female trainee (prioritize glutes and lower body; reduce arm volume)" if gender.lower() == "female" else "male trainee"
    prompt = [
        SystemMessage(content=SYSTEM_SPLIT_PROMPT.format(frequency=clamped_freq)),
        HumanMessage(content=f"Frequency: {clamped_freq} days/week. Trainee: {gender_context}. User Split Request: '{preference}'")
    ]
    plan: DynamicSplitPlan = structured_llm.invoke(prompt)

    if len(plan.days) > clamped_freq:
        plan.days = plan.days[:clamped_freq]

    return plan

def calculate_volume_budget(stress_and_sleep: str) -> int:
    text = stress_and_sleep.lower()
    poor_indicators = [
        "poor", "bad", "terrible", "low sleep", "lack of sleep", 
        "insomnia", "high stress", "stressed", "4 hours", "5 hours", "6 hours"
    ]
    if any(phrase in text for phrase in poor_indicators):
        return 8
    return 12

import re

def clean_exercise_name(name: str, replace_with_machine: bool = True) -> str:
    """
    Cleans dataset naming artifacts.
    Replaces leading 'lever ' with 'machine ' (or strips it if False).
    Also strips trailing version numbers like 'v. 2'.
    """
    replacement = "machine " if replace_with_machine else ""
    cleaned = re.sub(r"^lever\s+", replacement, name, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+v\.\s*\d+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()

def fetch_filtered_candidates(
    muscle_group: str | None = None,
    equipment_access: str = "commercial gym",
    limitations: str = "None",
    limit: int = 4,
    body_part: str | None = None,
) -> List[Dict[str, Any]]:
    conn = db.get_connection()
    cursor = conn.cursor()

    target = (muscle_group or body_part or "").strip().lower()
    where_clause = SLANG_TO_SQL_MAP.get(target)

    if not where_clause:
        where_clause = f"(LOWER(target_muscle) LIKE '%{target}%' OR LOWER(body_part) LIKE '%{target}%')"

    exclusion_sql = " AND ".join([f"LOWER(name) NOT LIKE '%{term}%'" for term in EXCLUDED_TERMS])

    bodyweight_clause = ""
    if "gym" in equipment_access.lower() or "commercial" in equipment_access.lower():
        bodyweight_clause = "AND LOWER(name) NOT LIKE '%push-up%' AND LOWER(name) NOT LIKE '%pushup%'"

    query = f"""
        SELECT id, name, body_part, target_muscle, equipment, instructions, image_path, gif_path 
        FROM exercises 
        WHERE ({where_clause})
          AND LOWER(body_part) != 'cardio'
          AND ({exclusion_sql})
          {bodyweight_clause}
    """

    if any(w in limitations.lower() for w in ["back", "lumbar", "spine"]):
        query += " AND LOWER(name) NOT LIKE '%deadlift%' AND LOWER(name) NOT LIKE '%good morning%'"

    # Rank machines/cables/supported setups first for high progressive overload stability
    query += """
        ORDER BY 
          CASE 
            WHEN LOWER(equipment) IN ('leverage machine', 'smith machine') THEN 1
            WHEN LOWER(equipment) IN ('cable') THEN 2
            WHEN LOWER(equipment) IN ('barbell', 'dumbbell') THEN 3
            ELSE 4
          END ASC,
          CASE 
            WHEN LOWER(name) LIKE '%chest supported%' 
              OR LOWER(name) LIKE '%chest-supported%' 
              OR LOWER(name) LIKE '%seated%' 
              OR LOWER(name) LIKE '%lying%' THEN 1
            ELSE 2
          END ASC,
          RANDOM()
        LIMIT ?
    """

    cursor.execute(query, (limit,))
    rows = cursor.fetchall()
    cols = [col[0] for col in cursor.description]
    candidates = []

    for row in rows:
        item = dict(zip(cols, row))
        item["name"] = clean_exercise_name(item["name"], replace_with_machine=True)
        name_lower = item["name"].lower()
        is_calf = "calf" in name_lower
        is_compound = any(kw in name_lower for kw in COMPOUND_KEYWORDS) and not is_calf
        item["mechanic"] = "compound" if is_compound else "isolation"
        candidates.append(item)

    return candidates