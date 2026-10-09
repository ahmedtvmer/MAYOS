import re
from dataclasses import dataclass
from typing import Any, Callable

from dotenv import load_dotenv

from core.effort import min_rir_from_rpe
from agent.program_blueprints import (
    FAT_LOSS_CARDIO_NOTE,
    ExperienceLevel,
    MAX_RECOVERY_CUTS_PER_DAY,
    SLOT_FALLBACKS,
    SLOT_STAPLES,
    SLOT_SPECS,
    SlotSpec,
    WARMUP_FAMILIES,
    WARMUP_SPECS,
    WARMUP_REPS,
    WARMUP_REST_SECONDS,
    WARMUP_SETS,
    experience_level_for_training_age,
    is_escalated_isolation,
    is_fat_loss_goal,
    is_poor_recovery,
    rest_seconds_for_exercise_class,
    resolve_sets_family,
    slot_working_sets,
    target_rpe_for_experience,
    warmup_sets_for_load_class,
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
    SuggestedSubstitute,
    WarmupExerciseSchema,
)
from utils.equipment_access import COMMERCIAL_GYM, map_equipment_access
from utils.logger import MyosLogger

load_dotenv()
logger = MyosLogger().get_logger("program_generator")

MECHANIC_CUES = {
    "compound_press": "Control the 2-3s eccentric, pause briefly at full stretch, drive without locking out aggressively.",
    "compound_pull": "Initiate with scapular depression, pull elbows toward hips, pause 1s at peak contraction.",
    "compound_lower": "Brace core into belt/pad, control descent into active depth, drive through mid-foot.",
    "isolation_beginner": "Eliminate momentum, control the eccentric, and stop 0–1 reps short of failure.",
    "isolation_technical_failure": "Eliminate momentum, control the eccentric, and continue to technical failure: the last full-range rep that looks like the first.",
}

MIN_EXERCISES_PER_DAY = 3
SLOT_CANDIDATE_LIMIT = 100
SUGGESTED_SUBSTITUTE_COUNT = 2


@dataclass(frozen=True)
class DayGenerationContext:
    equipment_access: str
    limitations: str
    rep_preference: str
    recovery_cut: bool
    experience_level: ExperienceLevel


@dataclass(frozen=True)
class ExercisePrescription:
    movement_slot: str
    spec: SlotSpec
    working_sets: int
    rep_preference: str
    experience_level: ExperienceLevel


@dataclass(frozen=True)
class ProgramGenerationRequest:
    user_split_override: str | None = None
    rep_preference_override: str | None = None
    frequency_override: int | None = None


def get_biomechanical_cue(name: str, mechanic: str, experience_level: ExperienceLevel) -> str:
    name_lower = name.lower()
    if mechanic == "compound":
        # Word starts only: "chin" must not match "Machine", nor "row" match "Narrow".
        if re.search(r"\b(?:press|push|dip)", name_lower):
            return MECHANIC_CUES["compound_press"]
        if re.search(r"\b(?:row|pull|chin)", name_lower):
            return MECHANIC_CUES["compound_pull"]
        return MECHANIC_CUES["compound_lower"]
    cue_key = "isolation_beginner" if experience_level == "beginner" else "isolation_technical_failure"
    return MECHANIC_CUES[cue_key]


def _build_program_exercise(
    candidate: dict[str, Any], prescription: ExercisePrescription,
    suggested_substitutes: list[SuggestedSubstitute] | None = None,
) -> ProgramExerciseSchema:
    spec = prescription.spec
    rep_min, rep_max = apply_rep_preference(spec.reps, prescription.rep_preference)
    return ProgramExerciseSchema(
        exercise_id=str(candidate["id"]),
        exercise_name=candidate["name"],
        equipment=candidate.get("equipment"),
        slot_key=prescription.movement_slot,
        warmup_sets=warmup_sets_for_load_class(spec),
        target_sets=prescription.working_sets,
        target_reps_min=rep_min,
        target_reps_max=rep_max,
        target_rpe=target_rpe_for_experience(spec, prescription.experience_level),
        rest_seconds=rest_seconds_for_exercise_class(spec),
        notes=candidate.get("instructions") or None,
        image_path=candidate.get("image_path"),
        gif_path=candidate.get("gif_path"),
        suggested_substitutes=suggested_substitutes or [],
    )


def format_rest(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds / 60:g} min"


def build_warmup_block(
    family: str,
    equipment_access: str,
    limitations: str,
    *,
    ledger: Any,
) -> list[WarmupExerciseSchema]:
    """Resolves the 2-3 general preparation movements that open every session."""
    keys = WARMUP_FAMILIES.get(family, WARMUP_FAMILIES["full"])
    warmups: list[WarmupExerciseSchema] = []
    seen_ids: set[str] = set()
    for key in keys:
        fallback_keys = WARMUP_SPECS[key].get("fallbacks", ())
        for candidate_key in (key, *fallback_keys):
            candidate = next(
                (
                    option
                    for option in fetch_warmup_candidates(
                        candidate_key, equipment_access, limitations, limit=3, ledger=ledger
                    )
                    if str(option["id"]) not in seen_ids
                ),
                None,
            )
            if candidate is None:
                continue
            candidate_id = str(candidate["id"])
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


def _ordered_staples(candidates: list[dict], slot_key: str) -> list[dict]:
    """Return only Equipment access-allowed candidates explicitly listed as Staples."""
    by_id = {str(candidate["id"]): candidate for candidate in candidates}
    return [by_id[exercise_id] for exercise_id in SLOT_STAPLES.get(slot_key, ()) if exercise_id in by_id]


def _pick_candidate(candidates: list[dict], slot_key: str, excluded_ids: set[str]) -> dict | None:
    available = [c for c in _ordered_staples(candidates, slot_key) if str(c["id"]) not in excluded_ids]
    if not available:
        return None
    return available[0]


def assemble_deterministic_day(
    day: CustomDayPlan,
    context: DayGenerationContext,
    excluded_ids: set[str],
    *,
    ledger: Any,
) -> ProgramDaySchema:
    """Fills every blueprint slot with one catalog movement, honouring slot prescriptions."""
    selected_exercises: list[ProgramExerciseSchema] = []
    sets_family = resolve_sets_family(day.warmup_family, getattr(day, "sets_family", None))
    double_slots = tuple(getattr(day, "double_slots", ()) or ())
    cuts_used = 0
    staple_options: dict[str, list[dict]] = {}

    for slot_key in day.target_slots:
        spec = SLOT_SPECS.get(slot_key)
        if spec is None:
            logger.warning(f"Unknown slot '{slot_key}' in day '{day.day_name}' was skipped.")
            continue
        candidates = fetch_slot_candidates(slot_key, context.equipment_access, context.limitations, limit=SLOT_CANDIDATE_LIMIT, ledger=ledger)
        chosen = _pick_candidate(candidates, slot_key, excluded_ids)
        resolved_slot = slot_key
        if chosen is None:
            # A limitation or Equipment access filter can empty the pool; try
            # the blueprint's safe fallback slots instead of shrinking the day.
            fallback_options = SLOT_FALLBACKS.get(slot_key, {})
            fallback_keys = (
                *fallback_options.get(None, ()),
                *fallback_options.get(context.equipment_access, ()),
            )
            for fallback_key in fallback_keys:
                fallback_spec = SLOT_SPECS.get(fallback_key)
                if fallback_spec is None:
                    continue
                fallback_candidates = fetch_slot_candidates(fallback_key, context.equipment_access, context.limitations, limit=SLOT_CANDIDATE_LIMIT, ledger=ledger)
                fallback_chosen = _pick_candidate(fallback_candidates, fallback_key, excluded_ids)
                if fallback_chosen is not None:
                    logger.info(f"Substituted '{fallback_key}' for limited slot '{slot_key}' (day '{day.day_name}').")
                    chosen, resolved_slot, spec = fallback_chosen, fallback_key, fallback_spec
                    candidates = fallback_candidates
                    break
        if chosen is None:
            logger.warning(f"No catalog candidate for slot '{slot_key}' (day '{day.day_name}').")
            continue

        candidate_id = str(chosen["id"])
        excluded_ids.add(candidate_id)
        staple_options[candidate_id] = _ordered_staples(candidates, resolved_slot)
        apply_cut = (
            context.recovery_cut
            and cuts_used < MAX_RECOVERY_CUTS_PER_DAY
            and is_escalated_isolation(slot_key, sets_family)
        )
        if apply_cut:
            cuts_used += 1

        selected_exercises.append(
            _build_program_exercise(
                chosen,
                ExercisePrescription(
                    movement_slot=resolved_slot,
                    spec=spec,
                    working_sets=slot_working_sets(
                        slot_key, spec.archetype, sets_family, double_slots, recovery_cut=apply_cut
                    ),
                    rep_preference=context.rep_preference,
                    experience_level=context.experience_level,
                ),
                [],
            )
        )

    if len(selected_exercises) < MIN_EXERCISES_PER_DAY:
        for slot_key in day.target_slots:
            if len(selected_exercises) >= MIN_EXERCISES_PER_DAY:
                break
            spec = SLOT_SPECS.get(slot_key)
            if spec is None:
                continue
            candidates = fetch_slot_candidates(slot_key, context.equipment_access, context.limitations, limit=SLOT_CANDIDATE_LIMIT, ledger=ledger)
            ordered_candidates = _ordered_staples(candidates, slot_key)
            for candidate in ordered_candidates:
                candidate_id = str(candidate["id"])
                if any(ex.exercise_id == candidate_id for ex in selected_exercises):
                    continue
                staple_options[candidate_id] = ordered_candidates
                selected_exercises.append(
                    _build_program_exercise(
                        candidate,
                        ExercisePrescription(
                            movement_slot=slot_key,
                            spec=spec,
                            working_sets=slot_working_sets(slot_key, spec.archetype, sets_family, double_slots),
                            rep_preference=context.rep_preference,
                            experience_level=context.experience_level,
                        ),
                        [],
                    )
                )
                break

    prescribed_ids = {exercise.exercise_id for exercise in selected_exercises}
    for exercise in selected_exercises:
        alternatives = []
        for candidate in staple_options.get(exercise.exercise_id, []):
            candidate_id = str(candidate["id"])
            if candidate_id == exercise.exercise_id or candidate_id in prescribed_ids:
                continue
            alternatives.append(SuggestedSubstitute(exercise_id=candidate_id, exercise_name=str(candidate["name"])))
            if len(alternatives) == SUGGESTED_SUBSTITUTE_COUNT:
                break
        exercise.suggested_substitutes = alternatives

    return ProgramDaySchema(
        day_order=day.day_order,
        day_name=day.day_name,
        warmup_exercises=build_warmup_block(day.warmup_family, context.equipment_access, context.limitations, ledger=ledger),
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
        lines.append("| # | Exercise | Warm-up | Sets | Reps | Min RIR | Rest |")
        lines.append("| :---: | :--- | :---: | :---: | :---: | :---: | :---: |")
        for idx, ex in enumerate(day.exercises, start=1):
            rest = format_rest(ex.rest_seconds)
            warmup = f"{ex.warmup_sets}" if ex.warmup_sets else "-"
            # Display boundary (#111): the target is stored as RPE and read as
            # its equivalent *minimum* RIR, a whole number rounded up.
            minimum = min_rir_from_rpe(ex.target_rpe)
            lines.append(
                f"| {idx} | **{ex.exercise_name}** | {warmup} | {ex.target_sets} | "
                f"{ex.target_reps_min}~{ex.target_reps_max} | {minimum if minimum is not None else ''} | {rest} |"
            )
        if day.cardio:
            lines.append(f"**{day.cardio}**")
        lines.append("")
    return "\n".join(lines)


def generate_program_pipeline(
    user_split_override: str | None = None,
    rep_preference_override: str | None = None,
    frequency_override: int | None = None,
    published_by_coach_account_id: str | None = None,
    *,
    ledger: Any,
) -> tuple[GeneratedProgramSchema, str]:
    """Generates and persists a new active Program version."""
    profile = _generation_profile(ledger)
    request = ProgramGenerationRequest(user_split_override, rep_preference_override, frequency_override)
    weekly_frequency = _resolve_generation(profile, request)
    if published_by_coach_account_id is None and weekly_frequency != profile.get("weekly_frequency"):
        ledger.update_player_frequency(weekly_frequency)
    program, markdown = _build_program(profile, request, weekly_frequency, ledger)
    ledger.save_training_program(
        program.model_dump(), published_by_coach_account_id=published_by_coach_account_id
    )
    return program, markdown


def generate_program_draft_pipeline(
    request: ProgramGenerationRequest,
    *,
    inference_call: Callable[..., DynamicSplitPlan] | None = None,
    ledger: Any,
    profile: dict[str, Any] | None = None,
) -> tuple[GeneratedProgramSchema, str]:
    """Builds generated content without changing the active Program or profile.

    ``profile`` generates from an edited profile that is not saved yet; by
    default the ledger's saved profile is used.
    """
    if profile is None:
        profile = _generation_profile(ledger)
    weekly_frequency = _resolve_generation(profile, request)
    return _build_program(profile, request, weekly_frequency, ledger, inference_call=inference_call)


def _generation_profile(ledger: Any) -> dict[str, Any]:
    profile = ledger.get_player_profile()
    if not profile:
        raise ValueError("No user profile found in SQLite. Complete intake first.")
    return profile


def _resolve_generation(
    profile: dict[str, Any], request: ProgramGenerationRequest
) -> int:
    text_frequency = extract_frequency_from_text(request.user_split_override)
    if text_frequency is not None:
        validate_frequency(text_frequency)
    if request.frequency_override is not None:
        frequency = request.frequency_override
    elif text_frequency is not None:
        frequency = text_frequency
    else:
        frequency = profile.get("weekly_frequency", 4)
    return validate_frequency(frequency)


def _build_program(
    profile: dict[str, Any],
    request: ProgramGenerationRequest,
    weekly_frequency: int,
    ledger: Any,
    *,
    inference_call: Callable[..., DynamicSplitPlan] | None = None,
) -> tuple[GeneratedProgramSchema, str]:
    split_plan = _resolve_split_plan(profile, request, weekly_frequency, inference_call)
    days = _generate_program_days(profile, request, split_plan, ledger)
    program = GeneratedProgramSchema(
        program_name=split_plan.split_name,
        split_type=split_plan.split_name,
        weekly_frequency=len(split_plan.days),
        days=days,
    )
    return program, render_program_markdown(program)


def _resolve_split_plan(
    profile: dict[str, Any],
    request: ProgramGenerationRequest,
    weekly_frequency: int,
    inference_call: Callable[..., DynamicSplitPlan] | None = None,
) -> DynamicSplitPlan:
    preference = request.user_split_override
    if preference:
        keywords = (
            "upper", "lower", "ppl", "push", "pull", "legs", "arnold", "full body",
            "bro split", "anterior", "posterior", "glute", "total body",
        )
        if not any(keyword in preference.lower() for keyword in keywords):
            preference = None
    return resolve_split(
        frequency=weekly_frequency,
        preference=preference,
        gender=profile.get("gender", "male"),
        inference_call=inference_call,
    )


def _generate_program_days(
    profile: dict[str, Any],
    request: ProgramGenerationRequest,
    split_plan: DynamicSplitPlan,
    ledger: Any,
) -> list[ProgramDaySchema]:
    context = DayGenerationContext(
        equipment_access=map_equipment_access(profile.get("equipment_access", COMMERCIAL_GYM)),
        limitations=profile.get("injuries_or_limitations", "None"),
        rep_preference=request.rep_preference_override or profile.get("rep_preference", "balanced"),
        recovery_cut=is_poor_recovery(profile.get("stress_and_sleep")),
        experience_level=experience_level_for_training_age(profile.get("training_age_years", 0.0)),
    )
    days = [
        assemble_deterministic_day(day=day, context=context, excluded_ids=set(), ledger=ledger)
        for day in split_plan.days
    ]
    if is_fat_loss_goal(profile.get("current_goal"), profile.get("long_term_goal")):
        for day in days:
            day.cardio = FAT_LOSS_CARDIO_NOTE
    return days
