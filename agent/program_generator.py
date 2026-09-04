import os
import json
from typing import Dict, Any, List
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_ollama import ChatOllama
from agent.ProgramState import (
    GeneratedProgramSchema, 
    ProgramDaySchema, 
    DynamicSplitPlan
)
from agent.program_rules import (
    resolve_split,
    calculate_volume_budget,
    fetch_filtered_candidates,
    get_target_rep_window
)
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

load_dotenv()
logger = MyosLogger().get_logger("program_generator")

db = DatabaseManager()
llm = ChatOllama(model=os.getenv("LLM", "qwen2.5:3b"), temperature=0.1)

# Biomechanical Execution Cues Template
MECHANIC_CUES = {
    "compound_press": "Control the 2-3s eccentric, pause briefly at full stretch, drive without locking out aggressively.",
    "compound_pull": "Initiate with scapular depression, pull elbows toward hips, pause 1s at peak contraction.",
    "compound_lower": "Brace core into belt/pad, control descent into active depth, drive through mid-foot.",
    "isolation": "Eliminate momentum, control the eccentric portion, push to genuine concentric failure (0-1 RIR)."
}

def get_biomechanical_cue(name: str, mechanic: str) -> str:
    name_lower = name.lower()
    if mechanic == "compound":
        if any(w in name_lower for w in ["press", "push", "dip"]):
            return MECHANIC_CUES["compound_press"]
        if any(w in name_lower for w in ["row", "pull", "chin"]):
            return MECHANIC_CUES["compound_pull"]
        return MECHANIC_CUES["compound_lower"]
    return MECHANIC_CUES["isolation"]

DAY_SYNTHESIS_PROMPT = """You are an elite hypertrophy and mechanical-tension coach.
Assemble a single workout session using ONLY the provided candidates.

Rules:
1. Exercise Count: Pick EXACTLY 1 exercise per muscle group in target_muscles.
2. Stability & Overload: Always favor machines, cables, or supported setups over free balance.
3. Rep Windows & Volume:
   - Assign working sets: strictly 2 or 3 sets.
   - Use the 'recommended_reps' provided in each candidate's metadata.
   - Compound target RPE: 8.0 to 8.5 (1-2 RIR).
   - Isolation target RPE: 9.0 to 10.0 (0-1 RIR).
4. Uniqueness: Every exercise_id MUST be unique. Never duplicate exercises in the same workout.
"""

def synthesize_day(
    day_order: int,
    day_name: str,
    target_muscles: List[str],
    equipment_access: str,
    limitations: str,
    rep_preference: str,
    excluded_ids: set[str]
) -> ProgramDaySchema:
    candidate_pool = {}
    candidate_lookup: Dict[str, Dict[str, Any]] = {}

    for muscle in target_muscles:
        candidates = fetch_filtered_candidates(
            muscle_group=muscle,
            equipment_access=equipment_access,
            limitations=limitations,
            limit=4
        )
        
        # Filter out movements already used across other days
        fresh_candidates = [c for c in candidates if str(c["id"]) not in excluded_ids]
        pool_source = fresh_candidates if fresh_candidates else candidates

        candidate_pool[muscle] = []
        for c in pool_source:
            cid = str(c["id"])
            mechanic = c["mechanic"]
            rep_min, rep_max = get_target_rep_window(mechanic, rep_preference)
            
            c_info = {
                "id": cid,
                "name": c["name"],
                "mechanic": mechanic,
                "equipment": c["equipment"],
                "recommended_reps": f"{rep_min}-{rep_max}",
                "image_path": c.get("image_path"),
                "gif_path": c.get("gif_path")
            }
            candidate_pool[muscle].append(c_info)
            candidate_lookup[cid] = c_info

    day_payload = {
        "day_order": day_order,
        "day_name": day_name,
        "target_muscles": target_muscles,
        "candidate_pool": candidate_pool
    }

    structured_llm = llm.with_structured_output(ProgramDaySchema)
    prompt = [
        SystemMessage(content=DAY_SYNTHESIS_PROMPT),
        HumanMessage(content=(
            f"Generate Day {day_order} ({day_name}). Pick 1 exercise per target muscle.\n"
            f"Data:\n{json.dumps(day_payload, indent=2)}"
        ))
    ]

    day_plan: ProgramDaySchema = structured_llm.invoke(prompt)

    # -------------------------------------------------------------------------
    # Programmatic Post-Processing & Enforcement
    # -------------------------------------------------------------------------
    seen_ids = set()
    cleaned_exercises = []

    for ex in day_plan.exercises:
        if ex.exercise_id in seen_ids:
            continue
        seen_ids.add(ex.exercise_id)

        meta = candidate_lookup.get(ex.exercise_id, {})
        mechanic = meta.get("mechanic", "isolation")
        
        # Attach media assets
        ex.image_path = meta.get("image_path")
        ex.gif_path = meta.get("gif_path")

        expected_min, expected_max = get_target_rep_window(mechanic, rep_preference)
        ex.target_reps_min = expected_min
        ex.target_reps_max = expected_max
        ex.target_sets = min(max(ex.target_sets, 2), 3)
        ex.notes = get_biomechanical_cue(ex.exercise_name, mechanic)

        cleaned_exercises.append((0 if mechanic == "compound" else 1, ex))

    cleaned_exercises.sort(key=lambda x: x[0])
    day_plan.exercises = [item[1] for item in cleaned_exercises]

    return day_plan

def format_program_markdown(program: GeneratedProgramSchema) -> str:
    lines = []
    lines.append(f"# {program.program_name}")
    lines.append(f"**Split:** {program.split_type} | **Frequency:** {program.weekly_frequency} Days/Week\n")

    for day in program.days:
        lines.append(f"### Day {day.day_order}: {day.day_name}")
        lines.append("| Order | Exercise | Sets | Reps | Target RPE | Rest | Notes & Execution Cues |")
        lines.append("| :---: | :--- | :---: | :---: | :---: | :---: | :--- |")
        
        for idx, ex in enumerate(day.exercises, start=1):
            cue = ex.notes if ex.notes else "-"
            reps = f"{ex.target_reps_min}–{ex.target_reps_max}"
            lines.append(
                f"| {idx} | **{ex.exercise_name}** | {ex.target_sets} | {reps} | @{ex.target_rpe} | {ex.rest_seconds}s | {cue} |"
            )
        lines.append("")

    return "\n".join(lines)

def generate_program_pipeline(
    user_split_override: str | None = None,
    rep_preference_override: str | None = None
) -> tuple[GeneratedProgramSchema, str]:
    profile = db.get_user_profile()
    if not profile:
        raise ValueError("No user profile found in SQLite. Run onboarding first.")

    freq = profile["weekly_frequency"]
    gender = profile.get("gender", "male")
    split_plan: DynamicSplitPlan = resolve_split(
        frequency=freq, 
        preference=user_split_override, 
        gender=gender
    )
    rep_pref = rep_preference_override or profile.get("rep_preference", "balanced")

    logger.info(f"Generating {split_plan.split_name} ({len(split_plan.days)} days) for {gender} with '{rep_pref}' rep preference...")
    
    generated_days: List[ProgramDaySchema] = []
    used_exercise_ids: set[str] = set()

    for day in split_plan.days:
        logger.info(f"Synthesizing Day {day.day_order}: {day.day_name}...")
        day_plan = synthesize_day(
            day_order=day.day_order,
            day_name=day.day_name,
            target_muscles=day.target_body_parts,
            equipment_access=profile["equipment_access"],
            limitations=profile.get("injuries_or_limitations", "None"),
            rep_preference=rep_pref,
            excluded_ids=used_exercise_ids
        )
        
        for ex in day_plan.exercises:
            used_exercise_ids.add(ex.exercise_id)

        generated_days.append(day_plan)

    program = GeneratedProgramSchema(
        program_name=f"Custom {split_plan.split_name}",
        split_type=split_plan.split_name,
        weekly_frequency=len(split_plan.days),
        days=generated_days
    )

    db.save_training_program(program.model_dump())
    logger.info("Program successfully persisted to SQLite database.")

    table_output = format_program_markdown(program)
    return program, table_output