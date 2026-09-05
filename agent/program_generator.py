# agent/program_generator.py
import os
import re
import random
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_ollama import ChatOllama

from agent.ProgramState import (
    GeneratedProgramSchema, 
    ProgramDaySchema, 
    ProgramExerciseSchema,
    DynamicSplitPlan
)
from agent.program_rules import (
    resolve_split,
    fetch_filtered_candidates,
    get_target_rep_window
)
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

load_dotenv()
logger = MyosLogger().get_logger("program_generator")

db = DatabaseManager()
llm = ChatOllama(model=os.getenv("LLM", "qwen2.5:3b"), temperature=0.1)

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

def assemble_deterministic_day(
    day_order: int,
    day_name: str,
    target_muscles: List[str],
    equipment_access: str,
    limitations: str,
    rep_preference: str,
    excluded_ids: set[str]
) -> ProgramDaySchema:
    """
    Deterministically selects top-ranked exercises directly from SQL candidate pools.
    Runs in < 5ms per day with zero LLM latency.
    """
    selected_exercises = []

    for muscle in target_muscles:
        candidates = fetch_filtered_candidates(
            muscle_group=muscle,
            equipment_access=equipment_access,
            limitations=limitations,
            limit=6
        )

        # Filter out movements already used on other days
        available = [c for c in candidates if str(c["id"]) not in excluded_ids]
        
        # Pick randomly among top 2-3 available movements for variation
        chosen = None
        if available:
            pool = available[:3]
            chosen = random.choice(pool)
        elif candidates:
            chosen = random.choice(candidates[:2])

        if chosen:
            cid = str(chosen["id"])
            excluded_ids.add(cid)
            mechanic = chosen["mechanic"]
            rep_min, rep_max = get_target_rep_window(mechanic, rep_preference)

            target_rpe = 8.5 if mechanic == "compound" else 9.5
            rest_secs = 150 if mechanic == "compound" else 90

            exercise_schema = ProgramExerciseSchema(
                exercise_id=cid,
                exercise_name=chosen["name"],
                target_sets=3 if mechanic == "compound" else 2,
                target_reps_min=rep_min,
                target_reps_max=rep_max,
                target_rpe=target_rpe,
                rest_seconds=rest_secs,
                notes=get_biomechanical_cue(chosen["name"], mechanic),
                image_path=chosen.get("image_path"),
                gif_path=chosen.get("gif_path")
            )
            selected_exercises.append((0 if mechanic == "compound" else 1, exercise_schema))

    selected_exercises.sort(key=lambda x: x[0])
    ordered_list = [item[1] for item in selected_exercises]

    if len(ordered_list) < 3:
        backup_candidates = fetch_filtered_candidates(
            muscle_group=target_muscles[0] if target_muscles else "chest",
            equipment_access=equipment_access,
            limitations=limitations,
            limit=5
        )
        for c in backup_candidates:
            if str(c["id"]) not in excluded_ids:
                excluded_ids.add(str(c["id"]))
                ordered_list.append(
                    ProgramExerciseSchema(
                        exercise_id=str(c["id"]),
                        exercise_name=c["name"],
                        target_sets=2,
                        target_reps_min=10,
                        target_reps_max=15,
                        target_rpe=9.0,
                        rest_seconds=90,
                        notes=get_biomechanical_cue(c["name"], "isolation"),
                        image_path=c.get("image_path"),
                        gif_path=c.get("gif_path")
                    )
                )
                if len(ordered_list) >= 3:
                    break

    return ProgramDaySchema(
        day_order=day_order,
        day_name=day_name,
        exercises=ordered_list
    )

def extract_frequency_from_text(text: str | None) -> Optional[int]:
    if not text:
        return None
    match = re.search(r"\b([1-5])\s*(?:days?|x|-day)\b", text.lower())
    if match:
        return int(match.group(1))
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    for word, num in words.items():
        if re.search(rf"\b{word}\s*(?:days?|-day)\b", text.lower()):
            return num
    return None

def generate_program_pipeline(
    user_split_override: Optional[str] = None,
    rep_preference_override: Optional[str] = None,
    frequency_override: Optional[int] = None
) -> tuple[GeneratedProgramSchema, str]:
    profile = db.get_user_profile()
    if not profile:
        raise ValueError("No user profile found in SQLite. Complete intake first.")

    detected_freq = frequency_override or extract_frequency_from_text(user_split_override)
    freq = detected_freq if detected_freq else profile.get("weekly_frequency", 4)
    freq = min(max(int(freq), 1), 5)

    if freq != profile.get("weekly_frequency"):
        db.update_user_frequency(freq)

    clean_split_override = user_split_override
    if user_split_override:
        text = user_split_override.lower()
        keywords = ["upper", "lower", "ppl", "push", "pull", "legs", "arnold", "full body", "bro split"]
        if not any(kw in text for kw in keywords):
            clean_split_override = None

    gender = profile.get("gender", "male")
    split_plan: DynamicSplitPlan = resolve_split(
        frequency=freq, 
        preference=clean_split_override, 
        gender=gender
    )
    rep_pref = rep_preference_override or profile.get("rep_preference", "balanced")

    generated_days: List[ProgramDaySchema] = []
    used_exercise_ids: set[str] = set()

    # Fast deterministic synthesis
    for day in split_plan.days:
        day_plan = assemble_deterministic_day(
            day_order=day.day_order,
            day_name=day.day_name,
            target_muscles=day.target_body_parts,
            equipment_access=profile.get("equipment_access", "commercial gym"),
            limitations=profile.get("injuries_or_limitations", "None"),
            rep_preference=rep_pref,
            excluded_ids=used_exercise_ids
        )
        generated_days.append(day_plan)

    program = GeneratedProgramSchema(
        program_name=f"Custom {split_plan.split_name}",
        split_type=split_plan.split_name,
        weekly_frequency=len(split_plan.days),
        days=generated_days
    )

    db.save_training_program(program.model_dump())
    
    # Table formatting
    lines = [f"# {program.program_name}", f"**Split:** {program.split_type} | **Frequency:** {program.weekly_frequency} Days/Week\n"]
    for day in program.days:
        lines.append(f"### Day {day.day_order}: {day.day_name}")
        lines.append("| Order | Exercise | Sets | Reps | Target RPE | Rest | Notes |")
        lines.append("| :---: | :--- | :---: | :---: | :---: | :---: | :--- |")
        for idx, ex in enumerate(day.exercises, start=1):
            lines.append(f"| {idx} | **{ex.exercise_name}** | {ex.target_sets} | {ex.target_reps_min}-{ex.target_reps_max} | @{ex.target_rpe} | {ex.rest_seconds}s | {ex.notes or '-'} |")
        lines.append("")

    return program, "\n".join(lines)