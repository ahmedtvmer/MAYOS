import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

from dotenv import load_dotenv

from core.effort import min_rir_from_rpe
from agent.program_blueprints import (
    _SMALL_MUSCLE_OPENERS,
    ExperienceLevel,
    MAX_COACH_PATTERN_RECOVERY_CUTS_PER_DAY,
    MAX_RECOVERY_CUTS_PER_DAY,
    SLOT_FALLBACKS,
    SLOT_STAPLES,
    SLOT_SPECS,
    SPLIT_DISPLAY_NAMES,
    SlotSpec,
    WARMUP_FAMILIES,
    WARMUP_SPECS,
    WARMUP_REPS,
    WARMUP_REST_SECONDS,
    WARMUP_SETS,
    experience_level_for_training_age,
    is_escalated_isolation,
    is_poor_recovery,
    rest_seconds_for_exercise_class,
    resolve_sets_family,
    slot_working_sets,
    target_rpe_for_experience,
    warmup_sets_for_load_class,
)
from agent.program_rules import (
    NO_LIMITATIONS,
    SLOT_CANDIDATE_SIGNATURE,
    apply_rep_preference,
    exercise_mechanic,
    fetch_slot_candidates,
    fetch_warmup_candidates,
    resolve_split,
)
from agent.program_cardio import CoachCardioOptions, apply_program_cardio
from agent.ProgramState import (
    CustomDayPlan,
    DynamicSplitPlan,
    GeneratedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
    SuggestedSubstitute,
    WarmupExerciseSchema,
)
from utils.equipment_access import BODYWEIGHT_ONLY, COMMERCIAL_GYM, map_equipment_access
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
SPLIT_OVERRIDE_VALUES = (
    "Upper",
    "Lower",
    "PPL",
    "Push",
    "Pull",
    "Legs",
    "Arnold",
    "Full Body",
    "Bro Split",
    "Anterior",
    "Posterior",
    "Glute",
    "Total Body",
)

_SPLIT_TERM_REPLACEMENTS = (
    ("upper", ("علوي", "العلوي", "علوية", "العلوية", "فوق", "fo2")),
    ("lower", ("سفلي", "السفلي", "سفلية", "السفلية", "تحت", "ta7t")),
    ("push", ("دفع", "الدفع", "بوش", "dafa3", "daf3")),
    ("pull", ("سحب", "السحب", "بول", "sa7b")),
    (
        "legs",
        ("أرجل", "ارجل", "الأرجل", "الارجل", "رجل", "ليجز", "ليغز", "legz", "arjel", "regleen"),
    ),
    ("full body", ("جسم كامل", "الجسم كامل", "الجسم الكامل", "كامل الجسم", "فول بادي", "فول بودي", "فول بدي", "فل بادي", "فل بودي")),
    ("bro split", ("برو سبليت", "برو سبلت")),
    ("arnold", ("أرنولد",)),
    ("glute", ("جلوت", "غلوت", "جلوتس", "غلوتس", "الجلوتس", "الغلوتس", "المؤخرة", "الأرداف", "الارداف")),
    ("total body", ("الجسم بالكامل", "كل الجسم")),
)

_DIRECTION_TERM_REPLACEMENTS = (
    ("anterior", ("أمامي", "الأمامي", "امامية", "الامامية", "amami")),
    ("posterior", ("خلفي", "الخلفي", "خلفية", "الخلفية", "khalfi")),
)

_ARABIC_SPLIT_CHARACTER_MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
    }
)
_ARABIC_SHOULDER_PATTERN = re.compile(
    r"(?<!\w)(?:ال)?(?:ا?كتاف|كتف(?:ان|ين|ه|ها)?)(?!\w)"
)


def _basic_split_text(preference: str) -> str:
    without_marks = "".join(
        character
        for character in unicodedata.normalize("NFKC", preference.casefold())
        if unicodedata.category(character)[0] != "M" and character != "ـ"
    )
    return re.sub(r"[^\w]+", " ", without_marks.translate(_ARABIC_SPLIT_CHARACTER_MAP))


_NORMALIZED_SPLIT_WORDS = frozenset(
    word
    for _english, aliases in (*_SPLIT_TERM_REPLACEMENTS, *_DIRECTION_TERM_REPLACEMENTS)
    for alias in aliases
    for word in _basic_split_text(alias).split()
)


def _normalize_split_alias_text(preference: str) -> str:
    words = _basic_split_text(preference).split()
    normalized = []
    for word in words:
        if word in {"و", "w"}:
            continue
        if word.startswith("و") and word[1:] in _NORMALIZED_SPLIT_WORDS:
            word = word[1:]
        normalized.append(word)
    return " ".join(normalized)


def _normalized_split_replacements() -> tuple[tuple[re.Pattern[str], str], ...]:
    replacements = []
    for english, aliases in (*_SPLIT_TERM_REPLACEMENTS, *_DIRECTION_TERM_REPLACEMENTS):
        for alias in aliases:
            normalized = _normalize_split_alias_text(alias)
            if normalized:
                replacements.append((normalized, english))
    replacements.sort(key=lambda item: len(item[0]), reverse=True)
    return tuple(
        (
            re.compile(
                r"(?<!\w)" + r"\s+".join(map(re.escape, normalized.split())) + r"(?!\w)"
            ),
            english,
        )
        for normalized, english in replacements
    )


_NORMALIZED_SPLIT_REPLACEMENTS = _normalized_split_replacements()
_NORMALIZED_DIRECTION_TERMS = {
    english: frozenset(_normalize_split_alias_text(alias) for alias in aliases)
    for english, aliases in _DIRECTION_TERM_REPLACEMENTS
}
_SPLIT_ABBREVIATION_PATTERNS = (
    (re.compile(r"(?<!\w)u\s*l(?!\w)"), "upper lower"),
    (re.compile(r"(?<!\w)f\s*b(?!\w)"), "full body"),
    (re.compile(r"(?<!\w)p\s*p\s*l(?!\w)"), "ppl"),
    (re.compile(r"(?<!\w)ul(?!\w)"), "upper lower"),
    (re.compile(r"(?<!\w)fb(?!\w)"), "full body"),
)


def _has_split_override_value(preference: str) -> bool:
    return any(value.lower() in preference.lower() for value in SPLIT_OVERRIDE_VALUES)


def _translate_split_preference(preference: str) -> str | None:
    if _has_split_override_value(preference):
        return preference

    normalized = _normalize_split_alias_text(preference)
    if not normalized:
        return None

    translated = _translate_split_terms(normalized)
    translated = _expand_split_abbreviations(translated)
    if not _has_split_override_value(translated) or _contains_one_sided_push_pull(translated):
        return None
    return _normalize_push_pull_split_terms(translated)


def _translate_split_terms(preference: str) -> str:
    has_direction_pair = _has_direction_pair(preference) and not _ARABIC_SHOULDER_PATTERN.search(
        preference
    )
    translated = preference
    for pattern, english in _NORMALIZED_SPLIT_REPLACEMENTS:
        if english in {"anterior", "posterior"} and not has_direction_pair:
            continue
        translated = pattern.sub(english, translated)
    return translated


def _expand_split_abbreviations(preference: str) -> str:
    for pattern, english in _SPLIT_ABBREVIATION_PATTERNS:
        preference = pattern.sub(english, preference)
    return preference


def _normalize_push_pull_split_terms(preference: str) -> str:
    words = preference.split()
    split_positions = [index for index, word in enumerate(words) if word in {"push", "pull", "legs"}]
    split_terms = {words[index] for index in split_positions}
    if not {"push", "pull"}.issubset(split_terms):
        return preference

    first_split_position = split_positions[0]
    before = [word for word in words[:first_split_position] if word not in split_terms]
    after = [word for word in words[first_split_position:] if word not in split_terms]
    ordered_terms = ("push", "pull", "legs") if "legs" in split_terms else ("push", "pull")
    return " ".join((*before, *ordered_terms, *after))


def _has_direction_pair(preference: str) -> bool:
    words = preference.split()
    anterior = _NORMALIZED_DIRECTION_TERMS["anterior"]
    posterior = _NORMALIZED_DIRECTION_TERMS["posterior"]
    return any(
        (first in anterior and second in posterior)
        or (first in posterior and second in anterior)
        for first, second in zip(words, words[1:])
    )


def _contains_one_sided_push_pull(preference: str) -> bool:
    has_push = re.search(r"(?<!\w)push(?!\w)", preference) is not None
    has_pull = re.search(r"(?<!\w)pull(?!\w)", preference) is not None
    return has_push != has_pull and not any(
        value.lower() in preference.lower()
        for value in SPLIT_OVERRIDE_VALUES
        if value.lower() not in {"push", "pull", "legs"}
    )


def _recognized_split_preference(preference: str) -> str | None:
    split_type = preference.strip().casefold()
    if split_type in SPLIT_DISPLAY_NAMES:
        return split_type
    return _translate_split_preference(preference)


def has_supported_split_keyword(preference: str) -> bool:
    return _recognized_split_preference(preference) is not None


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
    split_id_override: str | None = None
    coach_cardio: CoachCardioOptions | None = None


def get_biomechanical_cue(
    exercise_entry: str | Mapping[str, Any], experience_level: ExperienceLevel
) -> str:
    if isinstance(exercise_entry, Mapping):
        exercise_name = str(exercise_entry.get("name") or exercise_entry.get("exercise_name") or "")
    else:
        exercise_name = exercise_entry
    name_lower = exercise_name.lower()
    if exercise_mechanic(exercise_entry) == "compound":
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


def _suggestion_candidates(candidates: list[dict], slot_key: str) -> list[dict]:
    staples = _ordered_staples(candidates, slot_key)
    staple_ids = {str(candidate["id"]) for candidate in staples}
    signatures = [
        candidate
        for candidate in candidates
        if candidate.get("_candidate_source") == SLOT_CANDIDATE_SIGNATURE
        and str(candidate["id"]) not in staple_ids
    ]
    return [*staples, *signatures]


def _staple_candidate_ids(candidates: list[dict], slot_key: str) -> set[str]:
    return {str(candidate["id"]) for candidate in _ordered_staples(candidates, slot_key)}


def _without_signature_candidates(candidates: list[dict]) -> list[dict]:
    return [
        candidate
        for candidate in candidates
        if candidate.get("_candidate_source") != SLOT_CANDIDATE_SIGNATURE
    ]


def _pick_candidate(candidates: list[dict], slot_key: str, excluded_ids: set[str]) -> dict | None:
    return next(
        (
            candidate
            for candidate in _suggestion_candidates(candidates, slot_key)
            if str(candidate["id"]) not in excluded_ids
        ),
        None,
    )


def _limitation_removed_staples(
    candidates: list[dict],
    slot_key: str,
    context: DayGenerationContext,
    excluded_ids: set[str],
    *,
    ledger: Any,
) -> bool:
    """Whether limitations removed Staples and no allowed unused Staple remains."""
    if str(context.limitations or "").strip().casefold() in {"", NO_LIMITATIONS.casefold()}:
        return False
    unrestricted_ids = _staple_candidate_ids(
        fetch_slot_candidates(
            slot_key,
            context.equipment_access,
            NO_LIMITATIONS,
            limit=SLOT_CANDIDATE_LIMIT,
            ledger=ledger,
        ),
        slot_key,
    )
    limited_ids = _staple_candidate_ids(candidates, slot_key)
    return bool(unrestricted_ids - limited_ids) and not (limited_ids - excluded_ids)


def _fetch_generation_candidates(
    slot_key: str,
    context: DayGenerationContext,
    excluded_ids: set[str],
    *,
    ledger: Any,
) -> tuple[list[dict], bool]:
    candidates = fetch_slot_candidates(
        slot_key,
        context.equipment_access,
        context.limitations,
        limit=SLOT_CANDIDATE_LIMIT,
        ledger=ledger,
    )
    limitation_removed_staples = _limitation_removed_staples(
        candidates, slot_key, context, excluded_ids, ledger=ledger
    )
    if limitation_removed_staples:
        candidates = _without_signature_candidates(candidates)
    return candidates, limitation_removed_staples


def _pick_from_alternate_slot(
    slot_key: str,
    context: DayGenerationContext,
    excluded_ids: set[str],
    source_limited_staples: bool,
    ledger: Any,
) -> tuple[dict | None, list[dict]]:
    candidates, alternate_limited_staples = _fetch_generation_candidates(
        slot_key, context, excluded_ids, ledger=ledger
    )
    if source_limited_staples and not alternate_limited_staples:
        candidates = _without_signature_candidates(candidates)
    return _pick_candidate(candidates, slot_key, excluded_ids), candidates


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
    max_recovery_cuts = (
        MAX_COACH_PATTERN_RECOVERY_CUTS_PER_DAY
        if sets_family == "coach"
        else MAX_RECOVERY_CUTS_PER_DAY
    )
    substitute_options: dict[str, list[dict]] = {}

    for slot_key in day.target_slots:
        spec = SLOT_SPECS.get(slot_key)
        if spec is None:
            logger.warning(f"Unknown slot '{slot_key}' in day '{day.day_name}' was skipped.")
            continue
        candidates, limitation_removed_staples = _fetch_generation_candidates(
            slot_key, context, excluded_ids, ledger=ledger
        )
        chosen = _pick_candidate(candidates, slot_key, excluded_ids)
        resolved_slot = slot_key
        candidate_slot = slot_key
        if chosen is None:
            # A limitation or Equipment access filter can empty the pool; try
            # the blueprint's safe fallback slots instead of shrinking the day.
            fallback_options = SLOT_FALLBACKS.get(slot_key, {})
            fallback_keys = (
                *fallback_options.get(None, ()),
                *fallback_options.get(context.equipment_access, ()),
            )
            if context.equipment_access == BODYWEIGHT_ONLY and slot_key == "ham_hinge":
                fallback_keys = ()
            for fallback_key in fallback_keys:
                fallback_spec = SLOT_SPECS.get(fallback_key)
                if fallback_spec is None:
                    continue
                fallback_chosen, fallback_candidates = _pick_from_alternate_slot(
                    fallback_key, context, excluded_ids,
                    limitation_removed_staples, ledger,
                )
                if fallback_chosen is not None:
                    logger.info(f"Substituted '{fallback_key}' for limited slot '{slot_key}' (day '{day.day_name}').")
                    chosen, resolved_slot, spec = fallback_chosen, fallback_key, fallback_spec
                    candidates = fallback_candidates
                    candidate_slot = fallback_key
                    break
        if chosen is None:
            logger.warning(f"No catalog candidate for slot '{slot_key}' (day '{day.day_name}').")
            continue

        candidate_id = str(chosen["id"])
        excluded_ids.add(candidate_id)
        substitute_options[candidate_id] = _suggestion_candidates(candidates, candidate_slot)
        apply_cut = (
            context.recovery_cut
            and cuts_used < max_recovery_cuts
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
            candidates, _ = _fetch_generation_candidates(
                slot_key, context, excluded_ids, ledger=ledger
            )
            day_ids = {exercise.exercise_id for exercise in selected_exercises}
            suggestion_candidates = _suggestion_candidates(candidates, slot_key)
            candidate = next(
                (
                    option
                    for option in suggestion_candidates
                    if str(option["id"]) not in day_ids
                ),
                None,
            )
            if candidate is None:
                continue
            candidate_id = str(candidate["id"])
            substitute_options[candidate_id] = suggestion_candidates
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
    if context.equipment_access == BODYWEIGHT_ONLY and sets_family == "coach":
        opener_index = next(
            (
                index
                for index, exercise in enumerate(selected_exercises)
                if exercise.slot_key in _SMALL_MUSCLE_OPENERS
            ),
            None,
        )
        if opener_index is not None:
            selected_exercises.insert(0, selected_exercises.pop(opener_index))
    for exercise in selected_exercises:
        alternatives = []
        for candidate in substitute_options.get(exercise.exercise_id, []):
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
        program.model_dump(),
        published_by_coach_account_id=published_by_coach_account_id,
        starting_position=None,
    )
    return program, markdown


def generate_program_draft_pipeline(
    request: ProgramGenerationRequest,
    *,
    inference_call: Callable[..., Any] | None = None,
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
    inference_call: Callable[..., Any] | None = None,
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
    inference_call: Callable[..., Any] | None = None,
) -> DynamicSplitPlan:
    if request.split_id_override is not None:
        return resolve_split(
            frequency=weekly_frequency,
            preference=request.split_id_override,
            gender=profile.get("gender", "male"),
        )
    preference = request.user_split_override
    if preference:
        preference = _recognized_split_preference(preference)
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
        limitations=profile.get("injuries_or_limitations", NO_LIMITATIONS),
        rep_preference=request.rep_preference_override or profile.get("rep_preference", "balanced"),
        recovery_cut=is_poor_recovery(profile.get("stress_and_sleep")),
        experience_level=experience_level_for_training_age(profile.get("training_age_years", 0.0)),
    )
    days = []
    for day in split_plan.days:
        if (
            context.equipment_access == BODYWEIGHT_ONLY
            and day.day_name.casefold() == "pull"
            and "vertical_pull" not in day.target_slots
        ):
            day = day.model_copy(
                update={"target_slots": ["vertical_pull", *day.target_slots]}
            )
        days.append(
            assemble_deterministic_day(day=day, context=context, excluded_ids=set(), ledger=ledger)
        )
    apply_program_cardio(days, split_plan.days, profile, request.coach_cardio)
    return days
