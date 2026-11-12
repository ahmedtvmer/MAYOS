import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from math import floor
from typing import Any, Callable

from dotenv import load_dotenv

from core.effort import min_rir_from_rpe
from core.movement_restrictions import restriction_for_candidate
from agent.program_blueprints import (
    _SMALL_MUSCLE_OPENERS,
    ExperienceLevel,
    LEGACY_GLUTE_PRIORITY_SPLIT_NAMES,
    RETIRED_GLUTE_PRIORITY_SPLIT_REQUESTS,
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
    test_set_rir_for_experience,
    warmup_sets_for_load_class,
)
from agent.program_rules import (
    NO_LIMITATIONS,
    SLOT_CANDIDATE_SIGNATURE,
    apply_rep_preference,
    exercise_mechanic,
    fetch_slot_candidates,
    fetch_warmup_candidates,
    restricted_candidate_reasons,
    resolve_split,
)
from agent.program_cardio import CoachCardioOptions, apply_program_cardio
from agent.program_order import order_program_exercises
from agent.focus_muscles import (
    FOCUS_EXTRA_TABLE, FOCUS_MUSCLE_SLOTS, FOCUS_MULTIPLIER, FOCUS_REGION_POLICY,
)
from agent.program_rationale import (
    SELECTION_ALREADY_USED_TODAY,
    SELECTION_EQUIPMENT_ACCESS_STAPLE,
    SELECTION_HIDDEN,
    SELECTION_FALLBACK,
    SELECTION_LIMITATION_SUBSTITUTE,
    SETS_COACH_DOSE,
    SETS_RECOVERY_CUT,
    SELECTION_FOCUS_MUSCLE_EXTRA,
    POSITION_FOCUS_FIRST,
    POSITION_AFTER_FOCUS_EXTRA,
    SETS_FOCUS_MULTIPLIER,
    FOCUS_UNAVAILABLE,
    FOCUS_LIGHTEST_TRAINING_DAY,
    FOCUS_NEW_WEEKLY_EXPOSURE,
    SPLIT_COACH_PICK,
    SPLIT_FREQUENCY_DEFAULT,
    SPLIT_LIFTER_REQUEST,
    SPLIT_UNSUPPORTED_FREQUENCY,
    ExerciseRationaleOptions,
    build_program_rationale,
    exercise_rationale,
)
from agent.ProgramState import (
    CustomDayPlan,
    DynamicSplitPlan,
    GeneratedProgramSchema,
    ProgramDaySchema,
    ProgramExerciseSchema,
    ProgramSetGroupSchema,
    SuggestedSubstitute,
    WarmupExerciseSchema,
)
from utils.equipment_access import BODYWEIGHT_ONLY, COMMERCIAL_GYM, map_equipment_access
from utils.logger import MayosLogger

load_dotenv()
logger = MayosLogger().get_logger("program_generator")

PROGRAM_DESIGN_VERSION = 5

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
    if split_type in RETIRED_GLUTE_PRIORITY_SPLIT_REQUESTS:
        return None
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
    movement_restrictions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExercisePrescription:
    movement_slot: str
    spec: SlotSpec
    working_sets: int
    rep_preference: str
    experience_level: ExperienceLevel


@dataclass(frozen=True)
class _FocusDosePlan:
    focus: dict[str, str]
    candidate_policy: dict[str, Any]
    muscle_slots: set[str]
    baseline: int
    target: int
    baseline_exercises: dict[int, tuple[Any, ...]]
    context: DayGenerationContext
    day_families: dict[int, str]


@dataclass(frozen=True)
class _FocusExtraPlacement:
    plan: _FocusDosePlan
    slot_key: str
    actual_weekly_sets: int
    day_choice: dict[str, Any]


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
        set_groups=_generated_set_groups(prescription),
        target_reps_min=rep_min,
        target_reps_max=rep_max,
        target_rpe=target_rpe_for_experience(spec, prescription.experience_level),
        rest_seconds=rest_seconds_for_exercise_class(spec),
        notes="",
        image_path=candidate.get("image_path"),
        gif_path=candidate.get("gif_path"),
        suggested_substitutes=suggested_substitutes or [],
    )


def _generated_set_groups(prescription: ExercisePrescription) -> list[ProgramSetGroupSchema]:
    rep_min, rep_max = apply_rep_preference(prescription.spec.reps, prescription.rep_preference)
    working_rir = 10 - target_rpe_for_experience(prescription.spec, prescription.experience_level)
    # One set uses working effort; two or more include one calibration set.
    counts_and_rir = [(prescription.working_sets, working_rir)]
    if prescription.working_sets > 1:
        counts_and_rir = [
            (1, test_set_rir_for_experience(prescription.experience_level)),
            (prescription.working_sets - 1, working_rir),
        ]
    return [
        ProgramSetGroupSchema(sets=count, reps_min=rep_min, reps_max=rep_max, target_rir=rir)
        for count, rir in counts_and_rir
    ]


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
    movement_restrictions: tuple[str, ...] | list[str] = (),
    skipped_restricted: list[dict[str, str]] | None = None,
) -> list[WarmupExerciseSchema]:
    """Resolves the 2-3 general preparation movements that open every session."""
    keys = WARMUP_FAMILIES.get(family, WARMUP_FAMILIES["full"])
    warmups: list[WarmupExerciseSchema] = []
    seen_ids: set[str] = set()
    for key in keys:
        fallback_keys = WARMUP_SPECS[key].get("fallbacks", ())
        for candidate_key in (key, *fallback_keys):
            candidate = None
            for option in fetch_warmup_candidates(
                candidate_key, equipment_access, limitations, limit=3, ledger=ledger
            ):
                restriction = restriction_for_candidate(option, "", movement_restrictions)
                if restriction:
                    if skipped_restricted is not None:
                        skipped_restricted.append({
                            "slot": f"warmup:{candidate_key}",
                            "restriction": restriction,
                        })
                    continue
                if str(option["id"]) not in seen_ids:
                    candidate = option
                    break
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
    fetch_options = {"limit": SLOT_CANDIDATE_LIMIT, "ledger": ledger}
    if context.movement_restrictions:
        fetch_options["restrictions"] = context.movement_restrictions
    unrestricted = fetch_slot_candidates(
        slot_key, context.equipment_access, NO_LIMITATIONS, **fetch_options
    )
    unrestricted_ids = _staple_candidate_ids(unrestricted, slot_key)
    limited_ids = _staple_candidate_ids(candidates, slot_key)
    return bool(unrestricted_ids - limited_ids) and not (limited_ids - excluded_ids)


def _fetch_generation_candidates(
    slot_key: str,
    context: DayGenerationContext,
    excluded_ids: set[str],
    *,
    ledger: Any,
) -> tuple[list[dict], bool]:
    fetch_options = {"limit": SLOT_CANDIDATE_LIMIT, "ledger": ledger}
    if context.movement_restrictions:
        fetch_options["restrictions"] = context.movement_restrictions
    candidates = fetch_slot_candidates(
        slot_key, context.equipment_access, context.limitations, **fetch_options
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


def _limitation_selection_code(
    candidate: dict[str, Any], slot_key: str, context: DayGenerationContext, ledger: Any,
    excluded_ids: set[str] | None = None,
) -> str | None:
    staples = SLOT_STAPLES.get(slot_key, ())
    candidate_id = str(candidate["id"])
    if candidate_id not in staples or staples.index(candidate_id) == 0:
        return None
    fetch_options = {"limit": SLOT_CANDIDATE_LIMIT, "ledger": ledger}
    if context.movement_restrictions:
        fetch_options["restrictions"] = context.movement_restrictions
    without_limitations = _staple_candidate_ids(
        fetch_slot_candidates(
            slot_key, context.equipment_access, NO_LIMITATIONS, **fetch_options
        ), slot_key,
    )
    prior_staples = staples[: staples.index(candidate_id)]
    if any(staple_id in (excluded_ids or set()) for staple_id in prior_staples):
        return SELECTION_ALREADY_USED_TODAY
    if any(staple_id in without_limitations for staple_id in prior_staples):
        return SELECTION_LIMITATION_SUBSTITUTE
    if context.equipment_access != COMMERCIAL_GYM:
        full_access_options = {"limit": SLOT_CANDIDATE_LIMIT, "ledger": ledger}
        if context.movement_restrictions:
            full_access_options["restrictions"] = context.movement_restrictions
        full_access = _staple_candidate_ids(fetch_slot_candidates(
            slot_key, COMMERCIAL_GYM, context.limitations, **full_access_options
        ), slot_key)
        if any(staple_id in full_access for staple_id in prior_staples):
            return SELECTION_EQUIPMENT_ACCESS_STAPLE
    return SELECTION_HIDDEN


def assemble_deterministic_day(
    day: CustomDayPlan,
    context: DayGenerationContext,
    excluded_ids: set[str],
    *,
    ledger: Any,
) -> ProgramDaySchema:
    return _assemble_deterministic_day_with_rationale(day, context, excluded_ids, ledger=ledger)[0]


def _assemble_deterministic_day_with_rationale(
    day: CustomDayPlan, context: DayGenerationContext, excluded_ids: set[str], *, ledger: Any
) -> tuple[ProgramDaySchema, list[dict[str, Any]]]:
    """Fills every blueprint slot with one catalog movement, honouring slot prescriptions."""
    selected_exercises: list[ProgramExerciseSchema] = []
    selected_rationales: list[dict[str, Any]] = []
    sets_family = resolve_sets_family(day.warmup_family, getattr(day, "sets_family", None))
    double_slots = tuple(getattr(day, "double_slots", ()) or ())
    cuts_used = 0
    max_recovery_cuts = (
        MAX_COACH_PATTERN_RECOVERY_CUTS_PER_DAY
        if sets_family == "coach"
        else MAX_RECOVERY_CUTS_PER_DAY
    )
    substitute_options: dict[str, list[dict]] = {}
    skipped_restricted: list[dict[str, str]] = []

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
        blocked_reasons = restricted_candidate_reasons(
            slot_key, context.equipment_access, context.limitations,
            context.movement_restrictions, ledger=ledger,
        ) if not chosen else []
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
            for fallback_key in (() if blocked_reasons else fallback_keys):
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
            skipped_restricted.extend(
                {"slot": slot_key, "restriction": reason}
                for reason in blocked_reasons
            )
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

        prescription = ExercisePrescription(
                    movement_slot=resolved_slot,
                    spec=spec,
                    working_sets=slot_working_sets(
                        slot_key, spec.archetype, sets_family, double_slots, recovery_cut=apply_cut
                    ),
                    rep_preference=context.rep_preference,
                    experience_level=context.experience_level,
                )
        options = ExerciseRationaleOptions(
                    selection_code=(
                        (
                            SELECTION_LIMITATION_SUBSTITUTE
                            if limitation_removed_staples else SELECTION_FALLBACK
                        ) if resolved_slot != slot_key else _limitation_selection_code(
                            chosen, slot_key, context, ledger, excluded_ids
                        )
                    ),
                    selection_params={"slot": slot_key, "rank": SLOT_STAPLES.get(slot_key, ()).index(str(chosen["id"])) + 1} if str(chosen["id"]) in SLOT_STAPLES.get(slot_key, ()) else {"slot": slot_key},
                    sets_code=SETS_RECOVERY_CUT if apply_cut else SETS_COACH_DOSE,
                    day_slots=tuple(day.target_slots),
                    experience_level=context.experience_level,
                    cut_from=slot_working_sets(slot_key, spec.archetype, sets_family, double_slots) if apply_cut else None,
                )
        selected_exercises.append(_build_program_exercise(chosen, prescription, []))
        selected_rationales.append(exercise_rationale(chosen, prescription, options))

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
            prescription = ExercisePrescription(
                        movement_slot=slot_key,
                        spec=spec,
                        working_sets=slot_working_sets(slot_key, spec.archetype, sets_family, double_slots),
                        rep_preference=context.rep_preference,
                        experience_level=context.experience_level,
                    )
            options = ExerciseRationaleOptions(day_slots=tuple(day.target_slots), experience_level=context.experience_level)
            selected_exercises.append(_build_program_exercise(candidate, prescription, []))
            selected_rationales.append(exercise_rationale(candidate, prescription, options))
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
            selected_rationales.insert(0, selected_rationales.pop(opener_index))
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

    for index, reason in enumerate(selected_rationales, start=1):
        reason["position"]["params"]["index"] = index
    program_day = ProgramDaySchema(
        day_order=day.day_order,
        day_name=day.day_name,
        warmup_exercises=build_warmup_block(
            day.warmup_family,
            context.equipment_access,
            context.limitations,
            ledger=ledger,
            movement_restrictions=context.movement_restrictions,
            skipped_restricted=skipped_restricted,
        ),
        exercises=selected_exercises,
        cardio=day.cardio,
    )
    exercise_reasons = [
        {"position": index, "exercise_id": exercise.exercise_id, "rationale": reason}
        for index, (exercise, reason) in enumerate(zip(selected_exercises, selected_rationales), start=1)
    ]
    if skipped_restricted:
        exercise_reasons.append({"skipped": skipped_restricted})
    return program_day, exercise_reasons


def assemble_program_day(
    day: CustomDayPlan, context: DayGenerationContext, excluded_ids: set[str], *, ledger: Any
) -> tuple[ProgramDaySchema, list[dict[str, Any]]]:
    """Public assembly seam used by the generation pipeline."""
    return _assemble_deterministic_day_with_rationale(day, context, excluded_ids, ledger=ledger)


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
                f"| {idx} | **{ex.exercise_name}** | {warmup} | {ex.working_sets} | "
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
    active_program = ledger.get_active_program()
    active_split = str(getattr(active_program, "split_type", "")).strip().casefold()
    if active_split in LEGACY_GLUTE_PRIORITY_SPLIT_NAMES:
        _migrate_legacy_glute_weak_point(ledger, profile)
        profile = _generation_profile(ledger)
        if not (user_split_override and user_split_override.strip()):
            request = ProgramGenerationRequest("full_body", rep_preference_override, frequency_override)
    if published_by_coach_account_id is None and weekly_frequency != profile.get("weekly_frequency"):
        ledger.update_player_frequency(weekly_frequency)
    program, markdown = _build_program(profile, request, weekly_frequency, ledger)
    persisted_program = program.model_dump()
    if published_by_coach_account_id is None:
        persisted_program["design_version"] = PROGRAM_DESIGN_VERSION
    ledger.save_training_program(
        persisted_program,
        published_by_coach_account_id=published_by_coach_account_id,
        starting_position=None,
    )
    return program, markdown


def _migrate_legacy_glute_weak_point(ledger: Any, profile: dict[str, Any]) -> None:
    if profile.get("weak_points") is not None:
        return
    profile["weak_points"] = [{"muscle": "glutes", "source": "migrated"}]
    ledger.upsert_player_profile(profile)


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
    days, rationale_days = _generate_program_days(profile, request, split_plan, ledger)
    focus_muscles = list(profile.get("weak_points") or [])
    program = GeneratedProgramSchema(
        program_name=split_plan.split_name,
        split_type=split_plan.split_name,
        weekly_frequency=len(split_plan.days),
        days=days,
        program_rationale={"days": rationale_days},
    )
    program.program_rationale = build_program_rationale(program, split_plan, request.coach_cardio)
    for day_rationale, exercise_reasons in zip(program.program_rationale["days"], rationale_days):
        day_rationale["exercises"] = exercise_reasons["exercises"]
        if exercise_reasons.get("skipped"):
            day_rationale["skipped"] = exercise_reasons["skipped"]
        if exercise_reasons.get("cardio_restriction"):
            day_rationale["cardio_restriction"] = exercise_reasons["cardio_restriction"]
    day_families = {
        day.day_order: day.family or day.warmup_family for day in split_plan.days
    }
    _order_generated_program(program, day_families, profile)
    _apply_focus_muscles(program, focus_muscles, profile, ledger, day_families)
    if focus_muscles:
        _order_generated_program(program, day_families, profile)
    return program, render_program_markdown(program)


def _order_generated_program(program, day_families, profile):
    experience_level = experience_level_for_training_age(profile.get("training_age_years", 0.0))
    rationale_days = {
        day["day_order"]: day for day in program.program_rationale["days"]
    }
    for day in program.days:
        rationale_day = rationale_days[day.day_order]
        exercise_reasons = rationale_day["exercises"]
        ordered = order_program_exercises(
            day.exercises,
            [entry["rationale"] for entry in exercise_reasons],
            day_family=day_families.get(day.day_order),
            experience_level=experience_level,
        )
        reasons_by_id = {entry["exercise_id"]: entry for entry in exercise_reasons}
        day.exercises = [entry.exercise for entry in ordered]
        rationale_day["exercises"] = [
            {
                **reasons_by_id[entry.exercise.exercise_id],
                "position": index,
                "rationale": entry.rationale,
            }
            for index, entry in enumerate(ordered, start=1)
        ]


def _apply_focus_muscles(program, focus_muscles, profile, ledger, day_families):
    """Selects Focus variants, places them, doses them, and records their reasons."""
    context = DayGenerationContext(
        equipment_access=map_equipment_access(profile.get("equipment_access", COMMERCIAL_GYM)),
        limitations=profile.get("injuries_or_limitations", NO_LIMITATIONS),
        rep_preference=profile.get("rep_preference", "balanced"),
        recovery_cut=False,
        experience_level=experience_level_for_training_age(profile.get("training_age_years", 0.0)),
        movement_restrictions=tuple(profile.get("movement_restrictions", ())),
    )
    baseline_exercises = {
        day.day_order: tuple(day.exercises)
        for day in program.days
    }
    focus_reasons = []
    for focus in focus_muscles:
        muscle = focus["muscle"]
        focus_policy = FOCUS_EXTRA_TABLE[muscle]
        muscle_slots = FOCUS_MUSCLE_SLOTS[muscle]
        baseline = _focus_baseline_sets(muscle_slots, baseline_exercises)
        target = _focus_target_weekly_sets(baseline)
        plan = _FocusDosePlan(
            focus, focus_policy, muscle_slots, baseline, target, baseline_exercises,
            context, day_families,
        )
        focus_reason = _insert_focus_extras(program, plan, ledger)
        focus_reasons.append(focus_reason)
    _recompute_focus_positions(program, focus_reasons)
    program.program_rationale["focus_muscles"] = focus_reasons


def _focus_baseline_sets(muscle_slots, baseline_exercises):
    return sum(
        exercise.working_sets
        for exercises in baseline_exercises.values()
        for exercise in exercises
        if exercise.slot_key in muscle_slots
    )


def _insert_focus_extras(program, plan, ledger):
    muscle, source = plan.focus["muscle"], plan.focus.get("source", "named")
    focus_reason = {"muscle": muscle, "source": source, "status": "added", "extra_exercise_ids": []}
    focus_reason["extras"] = []
    opened_days = set()
    actual = plan.baseline
    day_choices = []
    while actual < plan.target:
        addition = _insert_next_focus_extra(program, plan, opened_days, ledger)
        if addition is None:
            focus_reason["reason"] = _focus_unavailable_reason(
                muscle, plan.context.equipment_access, plan.target - actual,
                _focus_restriction_reason(plan.candidate_policy, plan.context, ledger),
            )
            break
        target_day, new_exercise, day_choice = addition
        actual += new_exercise.working_sets
        focus_reason["extra_exercise_ids"].append(new_exercise.exercise_id)
        day_choices.append(day_choice)
        focus_reason["extras"].append({
            "exercise_id": new_exercise.exercise_id,
            "day_order": target_day.day_order,
            "day_choice_reason": day_choice,
        })
        opened_days.add(target_day.day_order)
    if not focus_reason["extra_exercise_ids"]:
        focus_reason["status"] = "unavailable"
        focus_reason.pop("extra_exercise_ids")
        focus_reason.pop("extras")
        focus_reason["reason"] = focus_reason.pop("reason", _focus_unavailable_reason(
            muscle, plan.context.equipment_access, plan.target - actual,
            _focus_restriction_reason(plan.candidate_policy, plan.context, ledger),
        ))
    _record_focus_actual(program, focus_reason, actual)
    if day_choices:
        focus_reason["day_choice_reason"] = day_choices[0]
    return focus_reason


def _insert_next_focus_extra(program, plan, opened_days, ledger):
    candidate, slot_key = _focus_extra_candidate_for_program(
        program, plan.candidate_policy, plan.context, ledger
    )
    if candidate is None:
        return None
    day, day_choice = _focus_target_day_for_extra(
        program, plan, slot_key, opened_days
    )
    if day is None:
        return None
    actual = sum(
        exercise.working_sets
        for training_day in program.days
        for exercise in training_day.exercises
        if exercise.slot_key in plan.muscle_slots
    )
    placement = _FocusExtraPlacement(plan, slot_key, actual, day_choice)
    exercise = _insert_focus_exercise(program, day, candidate, placement)
    return day, exercise, day_choice


def _focus_extra_candidate_for_program(program, focus_policy, context, ledger):
    exercises = [exercise for day in program.days for exercise in day.exercises]
    return _focus_extra_candidate(
        focus_policy,
        {exercise.slot_key for exercise in exercises},
        {exercise.exercise_id for exercise in exercises},
        context,
        ledger,
    )


def _focus_unavailable_reason(muscle, equipment_access, missing_sets, restriction=None):
    params = {
        "muscle": muscle,
        "equipment_access": equipment_access,
        "missing_weekly_sets": missing_sets,
    }
    if restriction:
        params["restriction"] = restriction
    return {"code": FOCUS_UNAVAILABLE, "params": params}


def _focus_restriction_reason(focus_policy, context, ledger):
    blocked = []
    for slot_key in focus_policy["candidate_slots"]:
        candidates, _ = _fetch_generation_candidates(slot_key, context, set(), ledger=ledger)
        if candidates:
            return None
        blocked.extend(restricted_candidate_reasons(
            slot_key, context.equipment_access, context.limitations,
            context.movement_restrictions, ledger=ledger,
        ))
    return blocked[0] if blocked else None


def _insert_focus_exercise(program, day, candidate, placement):
    plan = placement.plan
    spec = SLOT_SPECS[placement.slot_key]
    prescription = ExercisePrescription(
        movement_slot=placement.slot_key,
        spec=spec,
        working_sets=2,
        rep_preference=plan.context.rep_preference,
        experience_level=plan.context.experience_level,
    )
    exercise = _build_program_exercise(candidate, prescription, [])
    rationale_day = _focus_rationale_day(program, day.day_order)
    insert_at = _focus_exercise_prefix_length(rationale_day["exercises"])
    day.exercises.insert(insert_at, exercise)
    rationale = _focus_extra_rationale(
        candidate, prescription, exercise, placement
    )
    rationale_day["exercises"].insert(insert_at, {
        "position": insert_at + 1, "exercise_id": exercise.exercise_id, "rationale": rationale,
    })
    return exercise


def _focus_extra_rationale(candidate, prescription, exercise, placement):
    plan = placement.plan
    slot_key = placement.slot_key
    rationale = exercise_rationale(
        candidate, prescription,
        ExerciseRationaleOptions(
            day_slots=(slot_key,), experience_level=plan.context.experience_level
        ),
    )
    rationale["selection"] = {"code": SELECTION_FOCUS_MUSCLE_EXTRA, "params": {
        "muscle": plan.focus["muscle"], "slot": slot_key,
        "exercise_id": exercise.exercise_id,
    }}
    rationale["position"] = {"code": POSITION_FOCUS_FIRST, "params": {
        "muscle": plan.focus["muscle"], "slot": slot_key,
    }}
    rationale["prescription"]["sets"] = _focus_sets_rationale(
        exercise, plan, placement.actual_weekly_sets
    )
    rationale["day_choice"] = placement.day_choice
    return rationale


def _focus_sets_rationale(exercise, plan, actual):
    return {"code": SETS_FOCUS_MULTIPLIER, "params": {
        "count": exercise.working_sets,
        "baseline_weekly_sets": plan.baseline,
        "target_weekly_sets": plan.target,
        "actual_weekly_sets": actual + exercise.working_sets,
        "multiplier": FOCUS_MULTIPLIER,
    }}


def _focus_rationale_day(program, day_order):
    return next(item for item in program.program_rationale["days"] if item["day_order"] == day_order)


def _focus_exercise_prefix_length(exercise_reasons):
    return sum(
        1 for reason in exercise_reasons
        if reason["rationale"]["selection"]["code"] == SELECTION_FOCUS_MUSCLE_EXTRA
    )


def _record_focus_actual(program, focus_reason, actual):
    exercise_ids = focus_reason.get("extra_exercise_ids", [])
    exercise_id_set = set(exercise_ids)
    for day in program.program_rationale["days"]:
        for item in day["exercises"]:
            if item["exercise_id"] in exercise_id_set:
                item["rationale"]["prescription"]["sets"]["params"]["actual_weekly_sets"] = actual
    if exercise_ids:
        focus_reason.update({
            "exercise_id": exercise_ids[0],
            "day_order": next(
                day["day_order"] for day in program.program_rationale["days"]
                if any(item["exercise_id"] == exercise_ids[0] for item in day["exercises"])
            ),
        })


def _recompute_focus_positions(program, focus_reasons):
    focus_muscles_by_exercise = {
        exercise_id: item["muscle"]
        for item in focus_reasons
        for exercise_id in item.get("extra_exercise_ids", ())
    }
    if not focus_muscles_by_exercise:
        return
    from agent.program_rationale import _position_code
    for day in program.days:
        rationale_day = _focus_rationale_day(program, day.day_order)
        _recompute_focus_day_positions(
            day, rationale_day, focus_muscles_by_exercise, _position_code
        )


def _recompute_focus_day_positions(day, rationale_day, focus_muscles_by_exercise, position_code):
    slots = tuple(exercise.slot_key for exercise in day.exercises)
    for index, (exercise, reason) in enumerate(
        zip(day.exercises, rationale_day["exercises"]), start=1
    ):
        reason["position"] = index
        position = reason["rationale"]["position"]
        position["params"]["index"] = index
        if exercise.exercise_id in focus_muscles_by_exercise:
            continue
        if position["code"] in {
            "position.main_progressed_lift",
            "position.beginner_compound_first",
            "position.stabilizer_safety",
            "position.pre_exhaust",
        }:
            continue
        displaced_focus = _displaced_focus_muscle(
            rationale_day["exercises"][:index - 1], focus_muscles_by_exercise
        )
        if displaced_focus and position["code"] == "position.small_muscle_opener":
            position["code"] = POSITION_AFTER_FOCUS_EXTRA
            position["params"]["focus_muscle"] = displaced_focus
            continue
        position["code"] = position_code(slots[index - 1], slots)


def _displaced_focus_muscle(previous_reasons, focus_muscles_by_exercise):
    return next(
        (
            focus_muscles_by_exercise[item["exercise_id"]]
            for item in previous_reasons
            if item["exercise_id"] in focus_muscles_by_exercise
        ),
        None,
    )


def _focus_extra_candidate(focus_policy, used_slots, used_ids, context, ledger):
    for slot_key in focus_policy["candidate_slots"]:
        if slot_key not in used_slots:
            candidate = _eligible_focus_candidate(focus_policy, slot_key, used_ids, context, ledger)
            if candidate:
                return candidate, slot_key
    main_slot = focus_policy["main_slot"]
    candidate = _eligible_focus_candidate(focus_policy, main_slot, used_ids, context, ledger)
    return candidate, main_slot if candidate else None


def _focus_target_weekly_sets(baseline: int) -> int:
    nearest_two_set_step = floor(baseline * FOCUS_MULTIPLIER / 2 + 0.5) * 2
    return max(baseline + 2, nearest_two_set_step)


def _focus_target_day_for_extra(program, plan, slot_key, opened_days):
    muscle = plan.focus["muscle"]
    eligible_days = [
        day for day in _focus_days_under_cap(program)
        if _focus_day_region_eligible(day, plan, slot_key)
    ]
    available = [day for day in eligible_days if day.day_order not in opened_days]
    if not eligible_days:
        return None, None
    current_exercises = _current_focus_exercises(program)
    exposures = _focus_exposure_count(plan, current_exercises)
    new_days = _focus_new_exposure_days(available, plan, slot_key, current_exercises)
    if new_days:
        day = _lightest_focus_day(new_days, current_exercises)
        return day, _focus_day_choice_reason(
            FOCUS_NEW_WEEKLY_EXPOSURE, muscle, exposures, day.day_order
        )
    training_days = [day for day in available if any(
        ex.slot_key in plan.muscle_slots for ex in current_exercises[day.day_order]
    )]
    fallback = _lightest_focus_day(training_days or available or eligible_days, current_exercises)
    return fallback, _focus_day_choice_reason(
        FOCUS_LIGHTEST_TRAINING_DAY, muscle, exposures, fallback.day_order
    )


def _focus_days_under_cap(program):
    return [day for day in program.days if sum(
        item["rationale"]["selection"]["code"] == SELECTION_FOCUS_MUSCLE_EXTRA
        for item in program.program_rationale["days"][day.day_order - 1]["exercises"]
    ) < 2]


def _current_focus_exercises(program):
    return {day.day_order: tuple(day.exercises) for day in program.days}


def _focus_exposure_count(plan, current_exercises):
    return sum(any(ex.slot_key in plan.muscle_slots for ex in exercises)
               for exercises in current_exercises.values())


def _focus_new_exposure_days(available, plan, slot_key, current_exercises):
    return [day for day in available if _focus_day_adds_exposure(day, plan, slot_key, current_exercises)]


def _focus_day_adds_exposure(day, plan, slot_key, current_exercises):
    region_policy = FOCUS_REGION_POLICY[plan.focus["muscle"]]
    home_family = region_policy["home_region"]
    family = plan.day_families[day.day_order]
    if family == "arms":
        family = "upper"
    if any(ex.slot_key in plan.muscle_slots for ex in current_exercises[day.day_order]):
        return False
    if family == home_family or (home_family == "neutral" and family in {"upper", "lower"}):
        return True
    return (
        family in region_policy["isolation_cross_regions"]
        and SLOT_SPECS[slot_key].archetype == "isolation"
    )


def _focus_day_region_eligible(day, plan, slot_key):
    policy = FOCUS_REGION_POLICY[plan.focus["muscle"]]
    home = policy["home_region"]
    family = plan.day_families[day.day_order]
    if family == "arms":
        family = "upper"
    if family == "full":
        return True
    if home == "neutral":
        return family in {"upper", "lower"}
    if family == home:
        return True
    if _focus_day_trains_region(day, home):
        return True
    return (
        family in policy["isolation_cross_regions"]
        and SLOT_SPECS[slot_key].archetype == "isolation"
    )


def _focus_day_trains_region(day, home):
    return any(
        ex.slot_key in {
            slot for muscle, region in FOCUS_REGION_POLICY.items()
            if region["home_region"] == home
            for slot in FOCUS_MUSCLE_SLOTS[muscle]
        }
        for ex in day.exercises
    )


def _lightest_focus_day(days, baseline_exercises):
    return min(days, key=lambda day: (
        sum(ex.working_sets for ex in baseline_exercises[day.day_order]), day.day_order
    ))


def _focus_day_choice_reason(code, muscle, exposures, day_order):
    increase = 1 if code == FOCUS_NEW_WEEKLY_EXPOSURE else 0
    return {"code": code, "params": {
        "muscle": muscle, "exposures_before": exposures,
        "exposures_after": exposures + increase, "day_order": day_order,
    }}


def _eligible_focus_candidate(focus_policy, slot_key, used_ids, context, ledger):
    candidates, _ = _fetch_generation_candidates(slot_key, context, used_ids, ledger=ledger)
    excluded_equipment = {
        equipment.casefold() for equipment in focus_policy.get("excluded_equipment", ())
    }
    candidates = [
        candidate for candidate in candidates
        if str(candidate.get("equipment") or "").strip().casefold() not in excluded_equipment
    ]
    preferred_ids = focus_policy.get("preferred_exercise_ids_by_slot", {}).get(slot_key)
    if preferred_ids:
        by_id = {str(candidate["id"]): candidate for candidate in candidates}
        preferred_candidates = [
            by_id[exercise_id]
            for exercise_id in preferred_ids
            if exercise_id in by_id and exercise_id not in used_ids
        ]
        if preferred_candidates:
            return preferred_candidates[0]
        return None
    return _pick_candidate(candidates, slot_key, used_ids)


def _tag_split_plan(plan: DynamicSplitPlan, requested_reason: str) -> DynamicSplitPlan:
    reason = (
        SPLIT_UNSUPPORTED_FREQUENCY
        if getattr(plan, "split_reason_code", None) == SPLIT_UNSUPPORTED_FREQUENCY
        else requested_reason
    )
    if hasattr(plan, "model_copy"):
        return plan.model_copy(update={"split_reason_code": reason})
    plan.split_reason_code = reason
    return plan


def _resolve_split_plan(
    profile: dict[str, Any],
    request: ProgramGenerationRequest,
    weekly_frequency: int,
    inference_call: Callable[..., Any] | None = None,
) -> DynamicSplitPlan:
    if request.split_id_override is not None:
        plan = resolve_split(
            frequency=weekly_frequency,
            preference=request.split_id_override,
            gender=profile.get("gender", "male"),
        )
        return _tag_split_plan(plan, SPLIT_COACH_PICK)
    preference = request.user_split_override
    if preference:
        preference = _recognized_split_preference(preference)
    plan = resolve_split(
        frequency=weekly_frequency,
        preference=preference,
        gender=profile.get("gender", "male"),
        inference_call=inference_call,
    )
    reason = SPLIT_LIFTER_REQUEST if preference else SPLIT_FREQUENCY_DEFAULT
    return _tag_split_plan(plan, reason)


def _generate_program_days(
    profile: dict[str, Any],
    request: ProgramGenerationRequest,
    split_plan: DynamicSplitPlan,
    ledger: Any,
) -> tuple[list[ProgramDaySchema], list[dict[str, Any]]]:
    context = DayGenerationContext(
        equipment_access=map_equipment_access(profile.get("equipment_access", COMMERCIAL_GYM)),
        limitations=profile.get("injuries_or_limitations", NO_LIMITATIONS),
        rep_preference=request.rep_preference_override or profile.get("rep_preference", "balanced"),
        recovery_cut=is_poor_recovery(profile.get("stress_and_sleep")),
        experience_level=experience_level_for_training_age(profile.get("training_age_years", 0.0)),
        movement_restrictions=tuple(profile.get("movement_restrictions", ())),
    )
    days = []
    rationale_days = []
    for day in split_plan.days:
        if (
            context.equipment_access == BODYWEIGHT_ONLY
            and day.day_name.casefold() == "pull"
            and "vertical_pull" not in day.target_slots
        ):
            day = day.model_copy(
                update={"target_slots": ["vertical_pull", *day.target_slots]}
            )
        built = assemble_program_day(day=day, context=context, excluded_ids=set(), ledger=ledger)
        if isinstance(built, tuple):
            program_day, exercise_reasons = built
        else:
            program_day, exercise_reasons = built, []
        skipped_restrictions = [
            skipped
            for entry in exercise_reasons
            for skipped in entry.get("skipped", [])
        ]
        exercise_reasons = [entry for entry in exercise_reasons if "exercise_id" in entry]
        days.append(program_day)
        day_rationale = {"day_order": day.day_order, "warmup": [], "cardio": None, "exercises": exercise_reasons}
        if skipped_restrictions:
            day_rationale["skipped"] = skipped_restrictions
        rationale_days.append(day_rationale)
    cardio_adjustments = apply_program_cardio(days, split_plan.days, profile, request.coach_cardio)
    if cardio_adjustments:
        for day_rationale in rationale_days:
            day_rationale["cardio_restriction"] = cardio_adjustments
    return days, rationale_days
