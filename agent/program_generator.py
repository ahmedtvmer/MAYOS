import random
import re

from dotenv import load_dotenv

from agent.program_blueprints import (
    FAT_LOSS_CARDIO_NOTE,
    MAX_RECOVERY_CUTS_PER_DAY,
    SLOT_FALLBACKS,
    SLOT_SPECS,
    WARMUP_FAMILIES,
    WARMUP_REPS,
    WARMUP_REST_SECONDS,
    WARMUP_SETS,
    is_escalated_isolation,
    is_fat_loss_goal,
    is_poor_recovery,
    resolve_sets_family,
    slot_working_sets,
)
from agent.program_rules import (
    apply_rep_preference,
    fetch_slot_candidates,
    fetch_warmup_candidates,
    resolve_split,
)
from agent.ProgramState import (
    CustomDayPlan,
    DynamicSplitPlan,
    GeneratedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
    WarmupExerciseSchema,
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

RPE_BY_ARCHETYPE = {
    "heavy_compound": 8.5,
    "medium_compound": 9.0,
    "isolation": 9.5,
}

MIN_EXERCISES_PER_DAY = 3
POOL_WEIGHTS = (4, 2, 1)


def get_biomechanical_cue(name: str, mechanic: str) -> str:
    name_lower = name.lower()
    if mechanic == "compound":
        if any(w in name_lower for w in ["press", "push", "dip"]):
            return MECHANIC_CUES["compound_press"]
        if any(w in name_lower for w in ["row", "pull", "chin"]):
            return MECHANIC_CUES["compound_pull"]
        return MECHANIC_CUES["compound_lower"]
    return MECHANIC_CUES["isolation"]


def format_rest(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds / 60:g} min"


def build_warmup_block(
    family: str,
    equipment_access: str,
    limitations: str,
) -> list[WarmupExerciseSchema]:
    """Resolves the 2-3 general preparation movements that open every session."""
    keys = WARMUP_FAMILIES.get(family, WARMUP_FAMILIES["full"])
    warmups: list[WarmupExerciseSchema] = []
    seen_ids: set[str] = set()
    for key in keys:
        for candidate in fetch_warmup_candidates(key, equipment_access, limitations, limit=3):
            candidate_id = str(candidate["id"])
            if candidate_id in seen_ids:
                continue
            seen_ids.add(candidate_id)
            warmups.append(
                WarmupExerciseSchema(
                    exercise_id=candidate_id,
                    exercise_name=candidate["name"],
                    sets=WARMUP_SETS,
                    reps=WARMUP_REPS,
                    rest_seconds=WARMUP_REST_SECONDS,
                    image_path=candidate.get("image_path"),
                    gif_path=candidate.get("gif_path"),
                )
            )
            break
    return warmups


def _pick_candidate(candidates: list[dict], excluded_ids: set[str]) -> dict | None:
    available = [c for c in candidates if str(c["id"]) not in excluded_ids]
    if not available:
        return None
    pool = available[:3]
    weights = POOL_WEIGHTS[: len(pool)]
    return random.choices(pool, weights=weights, k=1)[0]


def assemble_deterministic_day(
    day: CustomDayPlan,
    equipment_access: str,
    limitations: str,
    rep_preference: str,
    excluded_ids: set[str],
    recovery_cut: bool = False,
) -> ProgramDaySchema:
    """Fills every blueprint slot with one catalog movement, honouring slot prescriptions."""
    selected_exercises: list[ProgramExerciseSchema] = []
    sets_family = resolve_sets_family(day.warmup_family, getattr(day, "sets_family", None))
    double_slots = tuple(getattr(day, "double_slots", ()) or ())
    cuts_used = 0

    for slot_key in day.target_slots:
        spec = SLOT_SPECS.get(slot_key)
        if spec is None:
            logger.warning(f"Unknown slot '{slot_key}' in day '{day.day_name}' was skipped.")
            continue
        candidates = fetch_slot_candidates(slot_key, equipment_access, limitations, limit=8)
        chosen = _pick_candidate(candidates, excluded_ids)
        if chosen is None:
            # A limitation filter can empty the whole pool (back rule vs hinges):
            # fall back to a safe substitute slot instead of silently shrinking the day.
            for fallback_key in SLOT_FALLBACKS.get(slot_key, ()):
                fallback_spec = SLOT_SPECS.get(fallback_key)
                if fallback_spec is None:
                    continue
                fallback_candidates = fetch_slot_candidates(fallback_key, equipment_access, limitations, limit=8)
                fallback_chosen = _pick_candidate(fallback_candidates, excluded_ids)
                if fallback_chosen is not None:
                    logger.info(f"Substituted '{fallback_key}' for limited slot '{slot_key}' (day '{day.day_name}').")
                    chosen, slot_key, spec = fallback_chosen, fallback_key, fallback_spec
                    break
        if chosen is None:
            logger.warning(f"No catalog candidate for slot '{slot_key}' (day '{day.day_name}').")
            continue

        candidate_id = str(chosen["id"])
        excluded_ids.add(candidate_id)
        rep_min, rep_max = apply_rep_preference(spec.reps, rep_preference)
        apply_cut = (
            recovery_cut and cuts_used < MAX_RECOVERY_CUTS_PER_DAY and is_escalated_isolation(slot_key, sets_family)
        )
        if apply_cut:
            cuts_used += 1

        selected_exercises.append(
            ProgramExerciseSchema(
                exercise_id=candidate_id,
                exercise_name=chosen["name"],
                slot_key=slot_key,
                warmup_sets=spec.warmup_sets,
                target_sets=slot_working_sets(slot_key, spec.archetype, sets_family, double_slots, recovery_cut=apply_cut),
                target_reps_min=rep_min,
                target_reps_max=rep_max,
                target_rpe=RPE_BY_ARCHETYPE.get(spec.archetype, 9.0),
                rest_seconds=spec.rest_seconds,
                notes=chosen.get("instructions") or None,
                image_path=chosen.get("image_path"),
                gif_path=chosen.get("gif_path"),
            )
        )

    if len(selected_exercises) < MIN_EXERCISES_PER_DAY:
        for slot_key in day.target_slots:
            if len(selected_exercises) >= MIN_EXERCISES_PER_DAY:
                break
            spec = SLOT_SPECS.get(slot_key)
            if spec is None:
                continue
            for candidate in fetch_slot_candidates(slot_key, equipment_access, limitations, limit=6):
                candidate_id = str(candidate["id"])
                if any(ex.exercise_id == candidate_id for ex in selected_exercises):
                    continue
                rep_min, rep_max = apply_rep_preference(spec.reps, rep_preference)
                selected_exercises.append(
                    ProgramExerciseSchema(
                        exercise_id=candidate_id,
                        exercise_name=candidate["name"],
                        slot_key=slot_key,
                        warmup_sets=spec.warmup_sets,
                        target_sets=slot_working_sets(slot_key, spec.archetype, sets_family, double_slots),
                        target_reps_min=rep_min,
                        target_reps_max=rep_max,
                        target_rpe=RPE_BY_ARCHETYPE.get(spec.archetype, 9.0),
                        rest_seconds=spec.rest_seconds,
                        notes=candidate.get("instructions") or None,
                        image_path=candidate.get("image_path"),
                        gif_path=candidate.get("gif_path"),
                    )
                )
                break

    return ProgramDaySchema(
        day_order=day.day_order,
        day_name=day.day_name,
        warmup_exercises=build_warmup_block(day.warmup_family, equipment_access, limitations),
        exercises=selected_exercises,
        cardio=day.cardio,
    )


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


def render_program_markdown(program: GeneratedProgramSchema) -> str:
    lines = [
        f"# {program.program_name}",
        f"**Split:** {program.split_type} | **Frequency:** {program.weekly_frequency} Days/Week\n",
    ]
    for day in program.days:
        lines.append(f"### Day {day.day_order}: {day.day_name}")
        if day.warmup_exercises:
            warmup_text = " | ".join(
                f"**{w.exercise_name}** {w.sets}×{w.reps} ({format_rest(w.rest_seconds)} rest)"
                for w in day.warmup_exercises
            )
            lines.append(f"**WARM UPS:** {warmup_text}")
        lines.append("| # | Exercise | Warm-up | Sets | Reps | RPE | Rest |")
        lines.append("| :---: | :--- | :---: | :---: | :---: | :---: | :---: |")
        for idx, ex in enumerate(day.exercises, start=1):
            rest = format_rest(ex.rest_seconds)
            warmup = f"{ex.warmup_sets}" if ex.warmup_sets else "-"
            lines.append(
                f"| {idx} | **{ex.exercise_name}** | {warmup} | {ex.target_sets} | "
                f"{ex.target_reps_min}~{ex.target_reps_max} | @{ex.target_rpe} | {rest} |"
            )
        if day.cardio:
            lines.append(f"**{day.cardio}**")
        lines.append("")
    return "\n".join(lines)


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
        keywords = [
            "upper",
            "lower",
            "ppl",
            "push",
            "pull",
            "legs",
            "arnold",
            "full body",
            "bro split",
            "anterior",
            "posterior",
            "glute",
            "total body",
        ]
        if not any(kw in user_split_override.lower() for kw in keywords):
            clean_split_override = None

    split_plan: DynamicSplitPlan = resolve_split(
        frequency=freq, preference=clean_split_override, gender=profile.get("gender", "male")
    )
    rep_pref = rep_preference_override or profile.get("rep_preference", "balanced")

    generated_days: list[ProgramDaySchema] = []
    recovery_cut = is_poor_recovery(profile.get("stress_and_sleep"))

    for day in split_plan.days:
        day_plan = assemble_deterministic_day(
            day=day,
            equipment_access=profile.get("equipment_access", "commercial gym"),
            limitations=profile.get("injuries_or_limitations", "None"),
            rep_preference=rep_pref,
            excluded_ids=set(),
            recovery_cut=recovery_cut,
        )
        generated_days.append(day_plan)

    # Goals modulate only the cardio layer; the lifting program is goal-agnostic.
    if is_fat_loss_goal(profile.get("current_goal"), profile.get("long_term_goal")):
        for day_plan in generated_days:
            day_plan.cardio = FAT_LOSS_CARDIO_NOTE

    program = GeneratedProgramSchema(
        program_name=split_plan.split_name,
        split_type=split_plan.split_name,
        weekly_frequency=len(split_plan.days),
        days=generated_days,
    )

    db.save_training_program(program.model_dump())

    return program, render_program_markdown(program)
