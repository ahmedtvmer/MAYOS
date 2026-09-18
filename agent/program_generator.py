import random
import re

from dotenv import load_dotenv

from agent.program_rules import (
    fetch_filtered_candidates,
    get_target_rep_window,
    resolve_split,
)
from agent.ProgramState import (
    DynamicSplitPlan,
    GeneratedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
)
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

load_dotenv()
logger = MyosLogger().get_logger("program_generator")
db = DatabaseManager()

MECHANIC_CUES = {
    "compound_press": "Control the 2-3s eccentric, pause briefly at full stretch, drive without locking out aggressively.",
    "compound_pull": "Initiate with scapular depression, pull elbows toward hips, pause 1s at peak contraction.",
    "compound_lower": "Brace core into belt/pad, control descent into active depth, drive through mid-foot.",
    "isolation": "Eliminate momentum, control the eccentric portion, push to genuine concentric failure (0-1 RIR).",
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
    target_muscles: list[str],
    equipment_access: str,
    limitations: str,
    rep_preference: str,
    excluded_ids: set[str],
) -> ProgramDaySchema:
    selected_exercises = []

    for muscle in target_muscles:
        candidates = fetch_filtered_candidates(
            muscle_group=muscle, equipment_access=equipment_access, limitations=limitations, limit=6
        )
        available = [c for c in candidates if str(c["id"]) not in excluded_ids]
        chosen = random.choice(available[:3]) if available else (random.choice(candidates[:2]) if candidates else None)

        if chosen:
            cid = str(chosen["id"])
            excluded_ids.add(cid)
            mechanic = chosen["mechanic"]
            rep_min, rep_max = get_target_rep_window(mechanic, rep_preference)

            exercise_schema = ProgramExerciseSchema(
                exercise_id=cid,
                exercise_name=chosen["name"],
                target_sets=3 if mechanic == "compound" else 2,
                target_reps_min=rep_min,
                target_reps_max=rep_max,
                target_rpe=8.5 if mechanic == "compound" else 9.5,
                rest_seconds=150 if mechanic == "compound" else 90,
                notes=get_biomechanical_cue(chosen["name"], mechanic),
                image_path=chosen.get("image_path"),
                gif_path=chosen.get("gif_path"),
            )
            selected_exercises.append((0 if mechanic == "compound" else 1, exercise_schema))

    selected_exercises.sort(key=lambda x: x[0])
    ordered_list = [item[1] for item in selected_exercises]

    if len(ordered_list) < 3:
        backup_candidates = fetch_filtered_candidates(
            muscle_group=target_muscles[0] if target_muscles else "chest",
            equipment_access=equipment_access,
            limitations=limitations,
            limit=5,
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
                        gif_path=c.get("gif_path"),
                    )
                )
                if len(ordered_list) >= 3:
                    break

    return ProgramDaySchema(day_order=day_order, day_name=day_name, exercises=ordered_list)


def extract_frequency_from_text(text: str | None) -> int | None:
    if not text:
        return None
    words = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
        "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
        "seventy": 70, "eighty": 80, "ninety": 90,
    }
    number_word = "|".join((*words, "hundred", "thousand", "million"))
    match = re.search(
        rf"(?<![\w.])(?P<number>[+-]?\d+|(?:minus\s+)?(?:{number_word})"
        rf"(?:(?:[\s-]+(?:and\s+)?)(?:{number_word}))*)"
        r"\s*(?:-\s*)?(?:days?|d/wk|x|times\s+(?:a|per)\s+week)\b",
        text.lower(),
    )
    if not match:
        return None
    token = match.group("number")
    if re.fullmatch(r"[+-]?\d+", token):
        return int(token)
    total, current = 0, 0
    for word in re.findall(r"\w+", token):
        if word == "hundred":
            current = max(current, 1) * 100
        elif word in ("thousand", "million"):
            total += max(current, 1) * (1000 if word == "thousand" else 1000000)
            current = 0
        elif word in words:
            current += words[word]
    return (total + current) * (-1 if token.startswith("minus") else 1)


def validate_frequency(value: int | str) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"[+-]?\d+", str(value).strip()):
        raise ValueError("Weekly frequency must be an integer from 1 to 5 days (maximum 5).")
    frequency = int(value)
    if not 1 <= frequency <= 5:
        raise ValueError("Weekly frequency must be from 1 to 5 days (maximum 5).")
    return frequency


def generate_program_pipeline(
    user_split_override: str | None = None,
    rep_preference_override: str | None = None,
    frequency_override: int | None = None,
) -> tuple[GeneratedProgramSchema, str]:
    profile = db.get_user_profile()
    if not profile:
        raise ValueError("No user profile found in SQLite. Complete intake first.")

    text_frequency = extract_frequency_from_text(user_split_override)
    if text_frequency is not None:
        validate_frequency(text_frequency)
    if frequency_override is not None:
        freq = validate_frequency(frequency_override)
    elif text_frequency is not None:
        freq = validate_frequency(text_frequency)
    else:
        freq = validate_frequency(profile.get("weekly_frequency", 4))

    if freq != profile.get("weekly_frequency"):
        db.update_user_frequency(freq)

    clean_split_override = user_split_override
    if user_split_override:
        keywords = ["upper", "lower", "ppl", "push", "pull", "legs", "arnold", "full body", "bro split"]
        if not any(kw in user_split_override.lower() for kw in keywords):
            clean_split_override = None

    split_plan: DynamicSplitPlan = resolve_split(
        frequency=freq, preference=clean_split_override, gender=profile.get("gender", "male")
    )
    rep_pref = rep_preference_override or profile.get("rep_preference", "balanced")

    generated_days: list[ProgramDaySchema] = []
    used_exercise_ids: set[str] = set()

    for day in split_plan.days:
        day_plan = assemble_deterministic_day(
            day_order=day.day_order,
            day_name=day.day_name,
            target_muscles=day.target_body_parts,
            equipment_access=profile.get("equipment_access", "commercial gym"),
            limitations=profile.get("injuries_or_limitations", "None"),
            rep_preference=rep_pref,
            excluded_ids=used_exercise_ids,
        )
        generated_days.append(day_plan)

    program = GeneratedProgramSchema(
        program_name=f"Custom {split_plan.split_name}",
        split_type=split_plan.split_name,
        weekly_frequency=len(split_plan.days),
        days=generated_days,
    )

    db.save_training_program(program.model_dump())

    lines = [
        f"# {program.program_name}",
        f"**Split:** {program.split_type} | **Frequency:** {program.weekly_frequency} Days/Week\n",
    ]
    for day in program.days:
        lines.append(f"### Day {day.day_order}: {day.day_name}")
        lines.append("| Order | Exercise | Sets | Reps | Target RPE | Rest | Notes |")
        lines.append("| :---: | :--- | :---: | :---: | :---: | :---: | :--- |")
        for idx, ex in enumerate(day.exercises, start=1):
            lines.append(
                f"| {idx} | **{ex.exercise_name}** | {ex.target_sets} | {ex.target_reps_min}-{ex.target_reps_max} | @{ex.target_rpe} | {ex.rest_seconds}s | {ex.notes or '-'} |"
            )
        lines.append("")

    return program, "\n".join(lines)
