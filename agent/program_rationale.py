"""Stable Program rationale codes.

Codes: split.frequency_default, split.lifter_request, split.coach_pick,
split.unsupported_frequency; day_order.template; selection.staple,
selection.equipment_access_staple, selection.already_used_today, selection.rebuild_variety, selection.hidden,
selection.signature_match, selection.limitation_substitute, selection.fallback; position.small_muscle_opener,
position.heavy_compound, position.medium_compound, position.isolation,
position.pre_exhaust, position.main_progressed_lift,
position.beginner_compound_first, position.stabilizer_safety;
sets.coach_dose, sets.recovery_cut; reps.movement_class,
reps.rep_preference; rir.experience_level, rir.test_set_rule; rest.movement_class; warmup.template;
sets.player_edit;
cardio.fat_loss_finisher, cardio.coach_option; day_order.full_body_distributed,
day_order.full_body_glute_priority,
day_order.upper_lower_alternating, day_order.female_upper_lower, day_order.arnold,
day_order.arnold_x_ul, day_order.anterior_posterior, day_order.ppl,
day_order.ppl_x_ul_spaces_leg_days. Change codes: change.substitution,
change.program_edit_removed, change.program_edit_trimmed,
change.program_edit_reordered, change.program_edit_added,
change.program_edit_raised, change.volume_review, change.coach_edit.
Parameters are stable JSON values; message
text belongs to the reading assistant.
selection.focus_muscle_extra, position.focus_first, sets.focus_multiplier,
focus.unavailable, focus.new_weekly_exposure and focus.lightest_training_day
are the Focus muscle codes (#492, #512).
"""

from dataclasses import dataclass
from typing import Any


SPLIT_FREQUENCY_DEFAULT = "split.frequency_default"
SPLIT_LIFTER_REQUEST = "split.lifter_request"
SPLIT_COACH_PICK = "split.coach_pick"
SPLIT_UNSUPPORTED_FREQUENCY = "split.unsupported_frequency"
DAY_ORDER_TEMPLATE = "day_order.template"
DAY_ORDER_FULL_BODY_DISTRIBUTED = "day_order.full_body_distributed"
DAY_ORDER_FULL_BODY_GLUTE_PRIORITY = "day_order.full_body_glute_priority"
DAY_ORDER_UPPER_LOWER_ALTERNATING = "day_order.upper_lower_alternating"
DAY_ORDER_FEMALE_UPPER_LOWER = "day_order.female_upper_lower"
DAY_ORDER_ARNOLD = "day_order.arnold"
DAY_ORDER_ARNOLD_X_UL = "day_order.arnold_x_ul"
DAY_ORDER_ANTERIOR_POSTERIOR = "day_order.anterior_posterior"
DAY_ORDER_PPL = "day_order.ppl"
DAY_ORDER_PPL_X_UL_SPACES_LEG_DAYS = "day_order.ppl_x_ul_spaces_leg_days"
SELECTION_STAPLE = "selection.staple"
SELECTION_EQUIPMENT_ACCESS_STAPLE = "selection.equipment_access_staple"
SELECTION_SIGNATURE_MATCH = "selection.signature_match"
SELECTION_LIMITATION_SUBSTITUTE = "selection.limitation_substitute"
SELECTION_FALLBACK = "selection.fallback"
SELECTION_ALREADY_USED_TODAY = "selection.already_used_today"
SELECTION_REBUILD_VARIETY = "selection.rebuild_variety"
SELECTION_HIDDEN = "selection.hidden"
POSITION_SMALL_MUSCLE_OPENER = "position.small_muscle_opener"
POSITION_HEAVY_COMPOUND = "position.heavy_compound"
POSITION_MEDIUM_COMPOUND = "position.medium_compound"
POSITION_ISOLATION = "position.isolation"
POSITION_PRE_EXHAUST = "position.pre_exhaust"
POSITION_MAIN_PROGRESSED_LIFT = "position.main_progressed_lift"
POSITION_BEGINNER_COMPOUND_FIRST = "position.beginner_compound_first"
POSITION_STABILIZER_SAFETY = "position.stabilizer_safety"
SETS_COACH_DOSE = "sets.coach_dose"
SETS_RECOVERY_CUT = "sets.recovery_cut"
SETS_PLAYER_EDIT = "sets.player_edit"
REPS_MOVEMENT_CLASS = "reps.movement_class"
REPS_PREFERENCE = "reps.rep_preference"
RIR_TEST_SET_RULE = "rir.test_set_rule"
REST_MOVEMENT_CLASS = "rest.movement_class"
WARMUP_TEMPLATE = "warmup.template"
CARDIO_FAT_LOSS_FINISHER = "cardio.fat_loss_finisher"
CARDIO_COACH_OPTION = "cardio.coach_option"

# Later Program changes (#494)
CHANGE_SUBSTITUTION = "change.substitution"
CHANGE_PROGRAM_EDIT_REMOVED = "change.program_edit_removed"
CHANGE_PROGRAM_EDIT_TRIMMED = "change.program_edit_trimmed"
CHANGE_PROGRAM_EDIT_REORDERED = "change.program_edit_reordered"
CHANGE_PROGRAM_EDIT_ADDED = "change.program_edit_added"
CHANGE_PROGRAM_EDIT_RAISED = "change.program_edit_raised"
CHANGE_VOLUME_REVIEW = "change.volume_review"
CHANGE_COACH_EDIT = "change.coach_edit"

# Focus muscle rationale codes (#492).
SELECTION_FOCUS_MUSCLE_EXTRA = "selection.focus_muscle_extra"
POSITION_FOCUS_FIRST = "position.focus_first"
POSITION_AFTER_FOCUS_EXTRA = "position.after_focus_extra"
SETS_FOCUS_MULTIPLIER = "sets.focus_multiplier"
FOCUS_UNAVAILABLE = "focus.unavailable"
FOCUS_NEW_WEEKLY_EXPOSURE = "focus.new_weekly_exposure"
FOCUS_LIGHTEST_TRAINING_DAY = "focus.lightest_training_day"


@dataclass(frozen=True)
class ExerciseRationaleOptions:
    selection_code: str | None = None
    sets_code: str = SETS_COACH_DOSE
    day_slots: tuple[str, ...] = ()
    selection_params: dict[str, Any] | None = None
    experience_level: str = "intermediate"
    cut_from: int | None = None


def _selection_reason(candidate: dict[str, Any], slot_key: str) -> dict[str, Any]:
    from agent.program_blueprints import SLOT_STAPLES
    candidate_id = str(candidate["id"])
    staples = SLOT_STAPLES.get(slot_key, ())
    if candidate_id in staples:
        rank = staples.index(candidate_id) + 1
        code = SELECTION_EQUIPMENT_ACCESS_STAPLE if rank > 1 else SELECTION_STAPLE
        return {"code": code, "params": {"slot": slot_key, "exercise_id": candidate_id, "rank": rank}}
    source = candidate.get("_candidate_source")
    if source == "signature":
        return {"code": SELECTION_SIGNATURE_MATCH, "params": {"slot": slot_key, "exercise_id": candidate_id}}
    return {"code": SELECTION_FALLBACK, "params": {"slot": slot_key, "exercise_id": candidate_id}}


def _position_code(slot_key: str, day_slots: tuple[str, ...]) -> str:
    from agent.program_blueprints import SLOT_SPECS, _SMALL_MUSCLE_OPENERS
    from agent.program_order import shares_main_muscle

    spec = SLOT_SPECS[slot_key]
    if slot_key in _SMALL_MUSCLE_OPENERS and day_slots and day_slots[0] == slot_key:
        return POSITION_SMALL_MUSCLE_OPENER
    if spec.archetype == "isolation":
        later_slots = day_slots[day_slots.index(slot_key) + 1:] if slot_key in day_slots else ()
        if any(
            SLOT_SPECS[later].archetype != "isolation"
            and shares_main_muscle(slot_key, later)
            for later in later_slots if later in SLOT_SPECS
        ):
            return POSITION_PRE_EXHAUST
        return POSITION_ISOLATION
    if spec.archetype == "heavy_compound":
        return POSITION_HEAVY_COMPOUND
    return POSITION_MEDIUM_COMPOUND


_POSITION_REASON_COPY = {
    POSITION_PRE_EXHAUST: (
        "This small isolation exercise comes first to wake up the same muscle before a later compound. "
        "The compound may use 5–15% less load; that is not a regression.",
        "يأتي تمرين العزل أولًا لتنشيط العضلة نفسها قبل تمرين مركب لاحق. "
        "قد يقل حمل التمرين المركب بنسبة ٥–١٥٪، وهذا لا يعني تراجعًا.",
    ),
    POSITION_MAIN_PROGRESSED_LIFT: (
        "This is the day's main progressed lift, so it stays ahead of other exercises for the same muscle.",
        "هذا هو تمرين القوة الأساسي المتدرج في اليوم، لذلك يسبق التمارين الأخرى للعضلة نفسها.",
    ),
    POSITION_BEGINNER_COMPOUND_FIRST: (
        "Compound lifts come first so you can practise them with fresh muscles.",
        "تأتي التمارين المركبة أولًا لتتدرب عليها والعضلات في حالة نشاط.",
    ),
    POSITION_STABILIZER_SAFETY: (
        "This isolation follows a lift that needs the same muscles fresh for support or grip.",
        "يأتي تمرين العزل بعد الرفعة التي تحتاج إلى نشاط العضلات نفسها للتثبيت أو القبضة.",
    ),
}


def position_rationale(
    slot_key: str,
    day_slots: tuple[str, ...],
    order_reason: str | None = None,
    index: int | None = None,
) -> dict[str, Any]:
    codes = {
        "pre_exhaust": POSITION_PRE_EXHAUST,
        "main_progressed_lift": POSITION_MAIN_PROGRESSED_LIFT,
        "beginner_compound_first": POSITION_BEGINNER_COMPOUND_FIRST,
        "stabilizer_safety": POSITION_STABILIZER_SAFETY,
    }
    code = codes[order_reason] if order_reason in codes else _position_code(slot_key, day_slots)
    params: dict[str, Any] = {"slot": slot_key}
    if index is not None:
        params["index"] = index
    if code in _POSITION_REASON_COPY:
        params["reason_en"], params["reason_ar"] = _POSITION_REASON_COPY[code]
    return {"code": code, "params": params}


def exercise_rationale(
    candidate: dict[str, Any], prescription: Any, options: ExerciseRationaleOptions
) -> dict[str, Any]:
    from agent.program_blueprints import (
        rest_seconds_for_exercise_class, target_rpe_for_experience, test_set_rir_for_experience,
    )
    from agent.program_rules import apply_rep_preference
    slot_key = prescription.movement_slot
    selection_params = {"slot": slot_key, "exercise_id": str(candidate["id"]), **(options.selection_params or {})}
    selection = (
        {"code": options.selection_code, "params": selection_params}
        if options.selection_code else _selection_reason(candidate, slot_key)
    )
    rep_preference = prescription.rep_preference
    rep_min, rep_max = apply_rep_preference(prescription.spec.reps, rep_preference)
    movement_class = prescription.spec.archetype
    return {
        "selection": selection,
        "position": position_rationale(slot_key, options.day_slots),
        "prescription": {
            "sets": {
                "code": options.sets_code,
                "params": {
                    "count": prescription.working_sets,
                    **({"cut_from": options.cut_from} if options.cut_from is not None else {}),
                },
            },
            "reps": {
                "code": REPS_PREFERENCE if rep_preference != "balanced" else REPS_MOVEMENT_CLASS,
                "params": {
                    "slot": slot_key, "preference": rep_preference,
                    "rep_min": rep_min, "rep_max": rep_max,
                    "movement_class": movement_class,
                },
            },
            "rir": {
                "code": RIR_TEST_SET_RULE,
                "params": {
                    "experience_level": options.experience_level,
                    "target_rir": 10 - target_rpe_for_experience(prescription.spec, options.experience_level),
                    "test_set_rir": test_set_rir_for_experience(options.experience_level),
                    "test_set_count": 1 if prescription.working_sets > 1 else 0,
                    "test_set_counts_toward_weekly_sets": True,
                },
            },
            "rest": {
                "code": REST_MOVEMENT_CLASS,
                "params": {
                    "slot": slot_key, "movement_class": movement_class,
                    "rest_seconds": rest_seconds_for_exercise_class(prescription.spec),
                },
            },
        },
    }


def _day_rationale(day: Any, coach_cardio: Any) -> dict[str, Any]:
    from agent.program_blueprints import (
        FAT_LOSS_CARDIO_BODYWEIGHT_NOTE,
        FAT_LOSS_CARDIO_NOTE,
    )
    cardio = None
    cardio_value = day.cardio
    if hasattr(cardio_value, "model_dump"):
        cardio_value = cardio_value.model_dump(exclude_none=True)
    if cardio_value in (FAT_LOSS_CARDIO_NOTE, FAT_LOSS_CARDIO_BODYWEIGHT_NOTE):
        cardio = {"code": CARDIO_FAT_LOSS_FINISHER, "params": {}}
    elif day.cardio:
        cardio = {
            "code": CARDIO_COACH_OPTION,
            "params": {
                "type": getattr(coach_cardio, "cardio_type", "custom"),
                "minutes": getattr(coach_cardio, "minutes", None),
            },
        }
    return {
        "day_order": day.day_order,
        "warmup": [
            {"code": WARMUP_TEMPLATE, "params": {"exercise_id": movement.exercise_id}}
            for movement in day.warmup_exercises
        ],
        "cardio": cardio,
        "exercises": [],
    }


def build_program_rationale(program: Any, split_plan: Any, coach_cardio: Any = None) -> dict[str, Any]:
    return {
        "split": {
            "code": getattr(split_plan, "split_reason_code", SPLIT_FREQUENCY_DEFAULT),
            "params": {"split": program.split_type, "frequency": program.weekly_frequency},
        },
        "day_order": {
            "code": getattr(split_plan, "day_order_reason_code", DAY_ORDER_TEMPLATE),
            "params": {"split": program.split_type},
        },
        "days": [_day_rationale(day, coach_cardio) for day in program.days],
        "focus_muscles": [],
    }
