"""Belghamdi-style movement-slot blueprints.

The reference programs in ``programs/`` (Belghamdi Full Body, Arnold x U-L,
Muscle Mommies, the Ahmed/Adham microcycles and Sardy's U/L) all share one
structural idea: a session is an ordered list of *movement slots* (incline
press, T-bar row, lateral raise, preacher curl, pushdown, wrist curl, leg
curl, adductors, calves, ...), not one-exercise-per-muscle. Fixing every slot
on every day is what guarantees direct arm, forearm, adductor, shrug and
incline-chest work in every program.

This module owns the deterministic structure: slot SQL patterns (resolved
against the catalog by ``agent.program_rules.fetch_slot_candidates``),
reference-derived prescriptions (warm-up ramps, set profiles, rep windows,
rests) and the split day templates. Execution guidance is intentionally not
embedded here: the UI shows the catalog's own form demos and players can ask
the coaching assistant for cues.
"""

import re
from dataclasses import dataclass, replace
from typing import Literal

from database.exercise_library.vocabulary import PRIMARY_ACTIONS, PRIMARY_MUSCLES
from utils.equipment_access import BODYWEIGHT_ONLY, HOME_GYM

Archetype = Literal["heavy_compound", "medium_compound", "isolation"]
ExperienceLevel = Literal["beginner", "intermediate", "advanced"]
PrescriptionClass = Literal["calf_abs", "isolation", "medium_compound", "heavy_compound"]

BEGINNER_MAX_TRAINING_AGE_YEARS = 2.0
INTERMEDIATE_MAX_TRAINING_AGE_YEARS = 5.0
CALF_ABS_SLOT_KEYS = frozenset({"calf", "abs"})
CALF_WORKING_SET_COUNT = 2

COMPOUND_REST_SECONDS_RANGE = (180, 240)
ISOLATION_REST_SECONDS_RANGE = (120, 180)
CALF_ABS_REST_SECONDS_RANGE = (90, 120)
LIGHT_WARMUP_SET_RANGE = (0, 0)
MEDIUM_WARMUP_SET_RANGE = (1, 2)
HEAVY_WARMUP_SET_RANGE = (2, 4)

BEGINNER_HEAVY_COMPOUND_RIR = 1.5
BEGINNER_MEDIUM_COMPOUND_RIR = 1.5
BEGINNER_ISOLATION_RIR = 0.5
BEGINNER_CALF_ABS_RIR = 0.5
INTERMEDIATE_HEAVY_COMPOUND_RIR = 0.5
INTERMEDIATE_MEDIUM_COMPOUND_RIR = 0.5
INTERMEDIATE_ISOLATION_RIR = 0.0
INTERMEDIATE_CALF_ABS_RIR = 0.0
ADVANCED_HEAVY_COMPOUND_RIR = 0.5
ADVANCED_MEDIUM_COMPOUND_RIR = 0.5
ADVANCED_ISOLATION_RIR = 0.0
ADVANCED_CALF_ABS_RIR = 0.0

REST_SECONDS_RANGES_BY_CLASS = {
    "calf_abs": CALF_ABS_REST_SECONDS_RANGE,
    "isolation": ISOLATION_REST_SECONDS_RANGE,
    "medium_compound": COMPOUND_REST_SECONDS_RANGE,
    "heavy_compound": COMPOUND_REST_SECONDS_RANGE,
}
WARMUP_SET_RANGES_BY_CLASS = {
    "calf_abs": LIGHT_WARMUP_SET_RANGE,
    "isolation": LIGHT_WARMUP_SET_RANGE,
    "medium_compound": MEDIUM_WARMUP_SET_RANGE,
    "heavy_compound": HEAVY_WARMUP_SET_RANGE,
}
TARGET_RIR_BY_EXPERIENCE_AND_CLASS = {
    ("beginner", "heavy_compound"): BEGINNER_HEAVY_COMPOUND_RIR,
    ("beginner", "medium_compound"): BEGINNER_MEDIUM_COMPOUND_RIR,
    ("beginner", "isolation"): BEGINNER_ISOLATION_RIR,
    ("beginner", "calf_abs"): BEGINNER_CALF_ABS_RIR,
    ("intermediate", "heavy_compound"): INTERMEDIATE_HEAVY_COMPOUND_RIR,
    ("intermediate", "medium_compound"): INTERMEDIATE_MEDIUM_COMPOUND_RIR,
    ("intermediate", "isolation"): INTERMEDIATE_ISOLATION_RIR,
    ("intermediate", "calf_abs"): INTERMEDIATE_CALF_ABS_RIR,
    ("advanced", "heavy_compound"): ADVANCED_HEAVY_COMPOUND_RIR,
    ("advanced", "medium_compound"): ADVANCED_MEDIUM_COMPOUND_RIR,
    ("advanced", "isolation"): ADVANCED_ISOLATION_RIR,
    ("advanced", "calf_abs"): ADVANCED_CALF_ABS_RIR,
}


@dataclass(frozen=True)
class SlotSpec:
    """One movement slot and everything the assembler needs to fill it."""

    key: str
    sql: str
    archetype: Archetype
    equipment_pref: tuple[str, ...]
    primary_actions: tuple[str, ...]
    primary_muscles: tuple[str, ...]
    reps: tuple[int, int]
    rest_seconds: int
    warmup_sets: int = 0
    exclude_sql: str = ""
    signature_name_exceptions: tuple[str, ...] = ()
    name_rank: tuple[str, ...] = ()


def _slot(
    key: str,
    sql: str,
    archetype: Archetype,
    equipment_pref: tuple[str, ...],
    reps: tuple[int, int],
    rest_seconds: int,
    warmup_sets: int = 0,
    exclude_sql: str = "",
    signature_name_exceptions: tuple[str, ...] = (),
    name_rank: tuple[str, ...] = (),
    primary_actions: tuple[str, ...] = (),
    primary_muscles: tuple[str, ...] = (),
) -> SlotSpec:
    return SlotSpec(
        key=key,
        sql=sql,
        archetype=archetype,
        equipment_pref=equipment_pref,
        primary_actions=primary_actions,
        primary_muscles=primary_muscles,
        reps=reps,
        rest_seconds=rest_seconds,
        warmup_sets=warmup_sets,
        exclude_sql=exclude_sql,
        signature_name_exceptions=signature_name_exceptions,
        name_rank=name_rank,
    )


def validate_slot_signatures(slot_specs: dict[str, SlotSpec]) -> None:
    for slot_key, spec in slot_specs.items():
        _validate_slot_signature_values(
            slot_key, "Primary action", spec.primary_actions, PRIMARY_ACTIONS
        )
        _validate_slot_signature_values(
            slot_key, "Primary muscle", spec.primary_muscles, PRIMARY_MUSCLES
        )


def _validate_slot_signature_values(
    slot_key: str,
    value_label: str,
    signature_values: tuple[str, ...],
    vocabulary: tuple[str, ...],
) -> None:
    if not signature_values:
        raise ValueError(f"Movement slot {slot_key!r} must declare a {value_label}")
    unknown_values = sorted(set(signature_values) - set(vocabulary))
    if unknown_values:
        raise ValueError(
            f"Movement slot {slot_key!r} has unknown {value_label}(s): "
            f"{', '.join(unknown_values)}"
        )


def experience_level_for_training_age(training_age_years: float) -> ExperienceLevel:
    if training_age_years < BEGINNER_MAX_TRAINING_AGE_YEARS:
        return "beginner"
    if training_age_years < INTERMEDIATE_MAX_TRAINING_AGE_YEARS:
        return "intermediate"
    return "advanced"


def prescription_class(spec: SlotSpec) -> PrescriptionClass:
    if spec.key in CALF_ABS_SLOT_KEYS:
        return "calf_abs"
    return spec.archetype


def target_rpe_for_experience(spec: SlotSpec, experience_level: ExperienceLevel) -> float:
    target_rir = TARGET_RIR_BY_EXPERIENCE_AND_CLASS[(experience_level, prescription_class(spec))]
    return 10.0 - target_rir


def warmup_sets_for_load_class(spec: SlotSpec) -> int:
    minimum, maximum = WARMUP_SET_RANGES_BY_CLASS[prescription_class(spec)]
    if not minimum <= spec.warmup_sets <= maximum:
        raise ValueError(f"Invalid warm-up set count for {spec.key}: {spec.warmup_sets}")
    return spec.warmup_sets


def rest_seconds_for_exercise_class(spec: SlotSpec) -> int:
    minimum, maximum = REST_SECONDS_RANGES_BY_CLASS[prescription_class(spec)]
    if not minimum <= spec.rest_seconds <= maximum:
        raise ValueError(f"Invalid rest time for {spec.key}: {spec.rest_seconds}")
    return spec.rest_seconds


SLOT_SPECS: dict[str, SlotSpec] = {
    # --- Chest -------------------------------------------------------------
    "incline_press": _slot(
        "incline_press",
        "LOWER(name) LIKE '%incline%' AND (LOWER(name) LIKE '%press%' OR LOWER(name) LIKE '%bench%') "
        "AND LOWER(target_muscle) = 'pectorals'",
        "medium_compound",
        ("leverage machine", "smith machine", "dumbbell", "cable", "barbell"),
        reps=(5, 7),
        rest_seconds=240,
        warmup_sets=1,
        exclude_sql="LOWER(name) NOT LIKE '%fly%' AND LOWER(name) NOT LIKE '%push-up%' AND LOWER(name) NOT LIKE '%pushup%'",
        primary_actions=("Shoulder Horizontal Adduction",),
        primary_muscles=("Upper Chest",),
    ),
    "flat_press": _slot(
        "flat_press",
        "(LOWER(name) LIKE '%chest press%' OR LOWER(name) LIKE '%bench press%' OR LOWER(name) LIKE '%flat press%') "
        "AND LOWER(target_muscle) = 'pectorals'",
        "medium_compound",
        ("leverage machine", "cable", "barbell", "dumbbell", "smith machine"),
        reps=(6, 8),
        rest_seconds=240,
        warmup_sets=1,
        exclude_sql="LOWER(name) NOT LIKE '%incline%' AND LOWER(name) NOT LIKE '%decline%' "
        "AND LOWER(name) NOT LIKE '%one arm%' AND LOWER(name) NOT LIKE '%push-up%'",
        signature_name_exceptions=("push-up",),
        primary_actions=("Shoulder Horizontal Adduction",),
        primary_muscles=("Chest",),
    ),
    "chest_fly": _slot(
        "chest_fly",
        "(LOWER(name) LIKE '%fly%' OR LOWER(name) LIKE '%pec deck%') AND LOWER(target_muscle) = 'pectorals'",
        "isolation",
        ("cable", "leverage machine", "dumbbell", "band"),
        reps=(8, 10),
        rest_seconds=180,
        name_rank=("incline", "middle", "flat", "fly", "pec deck"),
        primary_actions=("Shoulder Horizontal Adduction",),
        primary_muscles=("Chest",),
    ),
    # --- Back --------------------------------------------------------------
    "horizontal_row": _slot(
        "horizontal_row",
        "LOWER(name) LIKE '%row%' AND LOWER(target_muscle) IN ('upper back', 'lats', 'traps')",
        "heavy_compound",
        ("leverage machine", "smith machine", "dumbbell", "cable", "barbell"),
        reps=(5, 7),
        rest_seconds=240,
        warmup_sets=2,
        exclude_sql="LOWER(name) NOT LIKE '%upright row%' AND LOWER(name) NOT LIKE '%rear delt%' "
        "AND LOWER(name) NOT LIKE '%unilateral%' AND LOWER(name) NOT LIKE '%one arm%' "
        "AND LOWER(name) NOT LIKE '%single arm%' AND LOWER(name) NOT LIKE '%t bar%' "
        "AND LOWER(name) NOT LIKE '%t-bar%' AND LOWER(name) NOT LIKE '%high row%'"
        " AND LOWER(name) NOT LIKE '%bent over row%' AND LOWER(name) NOT LIKE '%barbell row%'",
        primary_actions=("Shoulder Extension",),
        primary_muscles=("Upper Back",),
    ),
    "upper_back_pull": _slot(
        "upper_back_pull",
        "(LOWER(name) LIKE '%unilateral row%' OR LOWER(name) LIKE '%one arm row%' "
        "OR LOWER(name) LIKE '%single arm row%' OR LOWER(name) LIKE '%t bar row%' "
        "OR LOWER(name) LIKE '%t-bar%' OR LOWER(name) LIKE '%high row%' "
        "OR LOWER(name) LIKE '%bent over row%' OR LOWER(name) LIKE '%barbell row%') "
        "AND LOWER(target_muscle) IN ('upper back', 'lats')",
        "medium_compound",
        ("leverage machine", "cable", "dumbbell", "smith machine", "barbell"),
        reps=(6, 10),
        rest_seconds=240,
        warmup_sets=1,
        primary_actions=("Shoulder Extension",),
        primary_muscles=("Upper Back",),
    ),
    "vertical_pull": _slot(
        "vertical_pull",
        "(LOWER(name) LIKE '%pulldown%' OR LOWER(name) LIKE '%pull-up%' OR LOWER(name) LIKE '%pull up%' "
        "OR LOWER(name) LIKE '%chin-up%' OR LOWER(name) LIKE '%chin up%' OR LOWER(name) LIKE '%chinup%') "
        "AND LOWER(target_muscle) IN ('lats', 'upper back')",
        "medium_compound",
        ("leverage machine", "cable", "body weight"),
        reps=(5, 7),
        rest_seconds=240,
        warmup_sets=1,
        exclude_sql="LOWER(name) NOT LIKE '%rear pulldown%' AND LOWER(name) NOT LIKE '%rear pull-up%' "
        "AND LOWER(name) NOT LIKE '%behind neck%' AND LOWER(name) NOT LIKE '%straight arm%'",
        name_rank=("front pulldown", "wide grip", "pulldown", "pull-up", "pull up"),
        primary_actions=("Shoulder Adduction",),
        primary_muscles=("Lats",),
    ),
    "pullover": _slot(
        "pullover",
        "(LOWER(name) LIKE '%pullover%' OR LOWER(name) LIKE '%straight arm pulldown%')",
        "isolation",
        ("cable", "dumbbell", "barbell"),
        reps=(8, 10),
        rest_seconds=180,
        exclude_sql="LOWER(name) NOT LIKE '%stretch%'",
        primary_actions=("Shoulder Extension",),
        primary_muscles=("Lats",),
    ),
    "shrug": _slot(
        "shrug",
        "LOWER(name) LIKE '%shrug%'",
        "isolation",
        ("leverage machine", "smith machine", "cable", "dumbbell", "barbell", "band"),
        reps=(6, 10),
        rest_seconds=180,
        primary_actions=("Scapular Elevation",),
        primary_muscles=("Traps",),
    ),
    # --- Shoulders ---------------------------------------------------------
    "shoulder_press": _slot(
        "shoulder_press",
        "(LOWER(name) LIKE '%shoulder press%' OR LOWER(name) LIKE '%overhead press%' "
        "OR LOWER(name) LIKE '%arnold press%') AND LOWER(target_muscle) = 'delts'",
        "heavy_compound",
        ("smith machine", "leverage machine", "dumbbell", "barbell", "cable", "kettlebell"),
        reps=(5, 8),
        rest_seconds=240,
        warmup_sets=2,
        primary_actions=("Shoulder Flexion",),
        primary_muscles=("Front Delts",),
    ),
    "side_delts": _slot(
        "side_delts",
        "(LOWER(name) LIKE '%lateral raise%' OR LOWER(name) LIKE '%side raise%') "
        "AND LOWER(target_muscle) = 'delts'",
        "isolation",
        ("cable", "leverage machine", "dumbbell", "band"),
        reps=(6, 8),
        rest_seconds=180,
        exclude_sql="LOWER(name) NOT LIKE '%rear%' AND LOWER(name) NOT LIKE '%front%'",
        primary_actions=("Shoulder Abduction",),
        primary_muscles=("Side Delts",),
    ),
    "rear_delts": _slot(
        "rear_delts",
        "(LOWER(name) LIKE '%rear delt%' OR LOWER(name) LIKE '%reverse fly%' "
        "OR LOWER(name) LIKE '%face pull%' OR LOWER(name) LIKE '%y-raise%' "
        "OR LOWER(name) LIKE '%rear lateral%')",
        "isolation",
        ("cable", "leverage machine", "dumbbell", "band", "barbell", "smith machine"),
        reps=(6, 10),
        rest_seconds=180,
        exclude_sql="LOWER(name) NOT LIKE '%stretch%'",
        name_rank=("reverse fly", "rear lateral", "rear delt", "y-raise", "face pull"),
        primary_actions=("Shoulder Horizontal Abduction",),
        primary_muscles=("Rear Delts",),
    ),
    # --- Arms --------------------------------------------------------------
    "biceps_preacher": _slot(
        "biceps_preacher",
        "LOWER(name) LIKE '%preacher%' AND LOWER(target_muscle) IN ('biceps', 'brachialis')",
        "isolation",
        ("dumbbell", "cable", "leverage machine", "ez barbell", "barbell", "smith machine"),
        reps=(6, 10),
        rest_seconds=180,
        primary_actions=("Elbow Flexion",),
        primary_muscles=("Biceps",),
    ),
    "biceps_alt": _slot(
        "biceps_alt",
        "LOWER(name) LIKE '%curl%' AND LOWER(target_muscle) IN ('biceps', 'brachialis')",
        "isolation",
        ("cable", "dumbbell", "ez barbell", "barbell", "smith machine", "leverage machine"),
        reps=(6, 10),
        rest_seconds=180,
        exclude_sql="LOWER(name) NOT LIKE '%wrist%' AND LOWER(name) NOT LIKE '%leg%' "
        "AND LOWER(name) NOT LIKE '%preacher%' AND LOWER(name) NOT LIKE '%reverse%' "
        "AND LOWER(name) NOT LIKE '%spider%'",
        primary_actions=("Elbow Flexion",),
        primary_muscles=("Biceps",),
    ),
    "triceps_pushdown": _slot(
        "triceps_pushdown",
        "LOWER(name) LIKE '%pushdown%' AND LOWER(target_muscle) = 'triceps'",
        "isolation",
        ("cable", "leverage machine"),
        reps=(6, 10),
        rest_seconds=180,
        primary_actions=("Elbow Extension",),
        primary_muscles=("Triceps",),
    ),
    "triceps_overhead": _slot(
        "triceps_overhead",
        "(LOWER(name) LIKE '%overhead%' OR LOWER(name) LIKE '%skull%' "
        "OR LOWER(name) LIKE '%lying triceps%' OR LOWER(name) LIKE '%crossbody%') "
        "AND LOWER(target_muscle) = 'triceps'",
        "isolation",
        ("cable", "barbell", "ez barbell", "dumbbell", "leverage machine"),
        reps=(6, 10),
        rest_seconds=180,
        exclude_sql="LOWER(name) NOT LIKE '%stretch%'",
        primary_actions=("Elbow Extension",),
        primary_muscles=("Triceps",),
    ),
    "forearm_wrist": _slot(
        "forearm_wrist",
        "LOWER(name) LIKE '%wrist curl%' AND LOWER(target_muscle) = 'forearms'",
        "isolation",
        ("barbell", "dumbbell", "cable", "band"),
        reps=(6, 10),
        rest_seconds=120,
        primary_actions=("Wrist Flexion",),
        primary_muscles=("Forearms",),
    ),
    "forearm_reverse": _slot(
        "forearm_reverse",
        "(LOWER(name) LIKE '%reverse curl%' OR LOWER(name) LIKE '%reverse wrist curl%') "
        "AND LOWER(target_muscle) IN ('forearms', 'biceps')",
        "isolation",
        ("dumbbell", "barbell", "ez barbell", "cable", "band"),
        reps=(6, 10),
        rest_seconds=120,
        primary_actions=("Wrist Extension",),
        primary_muscles=("Forearms",),
    ),
    # --- Legs --------------------------------------------------------------
    "quad_compound": _slot(
        "quad_compound",
        "(LOWER(name) LIKE '%squat%' OR LOWER(name) LIKE '%leg press%' "
        "OR LOWER(name) LIKE '%hack%' OR LOWER(name) LIKE '%lunge%') "
        "AND LOWER(target_muscle) IN ('quads', 'glutes')",
        "heavy_compound",
        ("leverage machine", "sled machine", "smith machine", "barbell", "dumbbell", "kettlebell"),
        reps=(5, 8),
        rest_seconds=240,
        warmup_sets=2,
        exclude_sql="LOWER(name) NOT LIKE '%calf%' AND LOWER(name) NOT LIKE '%stretch%' "
        "AND LOWER(name) NOT LIKE '%jump%' AND LOWER(name) NOT LIKE '%pistol%' "
        "AND LOWER(name) NOT LIKE '%sumo%' AND LOWER(name) NOT LIKE '%front squat%'",
        name_rank=("hack", "leg press", "smith hack", "smith squat", "squat"),
        primary_actions=("Knee Extension",),
        primary_muscles=("Quads",),
    ),
    "quad_lunge": _slot(
        "quad_lunge",
        "(LOWER(name) LIKE '%split squat%' OR LOWER(name) LIKE '%lunge%') "
        "AND LOWER(target_muscle) IN ('quads', 'glutes')",
        "medium_compound",
        ("dumbbell", "barbell", "smith machine", "cable", "kettlebell", "body weight"),
        reps=(6, 8),
        rest_seconds=180,
        warmup_sets=1,
        exclude_sql="LOWER(name) NOT LIKE '%jump%' AND LOWER(name) NOT LIKE '%stretch%'",
        primary_actions=("Knee Extension",),
        primary_muscles=("Quads",),
    ),
    "quad_iso": _slot(
        "quad_iso",
        "LOWER(name) LIKE '%leg extension%' AND LOWER(target_muscle) = 'quads'",
        "isolation",
        ("leverage machine", "resistance band", "cable"),
        reps=(6, 10),
        rest_seconds=180,
        primary_actions=("Knee Extension",),
        primary_muscles=("Quads",),
    ),
    "ham_curl": _slot(
        "ham_curl",
        "LOWER(name) LIKE '%leg curl%' AND LOWER(target_muscle) = 'hamstrings'",
        "isolation",
        ("leverage machine", "cable", "dumbbell", "body weight"),
        reps=(6, 10),
        rest_seconds=180,
        name_rank=("seated", "lying", "leaning"),
        primary_actions=("Knee Flexion",),
        primary_muscles=("Hamstrings",),
    ),
    "ham_hinge": _slot(
        "ham_hinge",
        "(LOWER(name) LIKE '%romanian%' OR LOWER(name) LIKE '%stiff leg%' "
        "OR LOWER(name) LIKE '%stiff-leg%' OR LOWER(name) LIKE '%good morning%') "
        "AND LOWER(target_muscle) IN ('hamstrings', 'glutes', 'spine')",
        "heavy_compound",
        ("barbell", "dumbbell", "smith machine", "leverage machine", "kettlebell", "band"),
        reps=(5, 7),
        rest_seconds=240,
        warmup_sets=2,
        exclude_sql="LOWER(name) NOT LIKE '%stretch%' AND LOWER(name) NOT LIKE '%cable assisted%'",
        name_rank=("romanian", "stiff leg", "stiff-leg", "deadlift", "good morning"),
        primary_actions=("Hip Extension",),
        primary_muscles=("Hamstrings",),
    ),
    "glute_thrust": _slot(
        "glute_thrust",
        "(LOWER(name) LIKE '%hip thrust%' OR LOWER(name) LIKE '%glute bridge%') "
        "AND LOWER(target_muscle) = 'glutes'",
        "medium_compound",
        ("barbell", "leverage machine", "smith machine", "dumbbell", "resistance band", "body weight"),
        reps=(5, 7),
        rest_seconds=240,
        warmup_sets=2,
        name_rank=("hip thrust", "barbell glute bridge", "glute bridge"),
        primary_actions=("Hip Extension",),
        primary_muscles=("Glutes",),
    ),
    "glute_iso": _slot(
        "glute_iso",
        "(LOWER(name) LIKE '%hip extension%' OR LOWER(name) LIKE '%kickback%' "
        "OR LOWER(name) LIKE '%reverse hyper%') AND LOWER(target_muscle) = 'glutes'",
        "isolation",
        ("cable", "leverage machine", "dumbbell", "band", "body weight", "stability ball"),
        reps=(8, 10),
        rest_seconds=180,
        primary_actions=("Hip Extension", "Hip Abduction"),
        primary_muscles=("Glutes", "Abductors"),
    ),
    "adductors": _slot(
        "adductors",
        "(LOWER(name) LIKE '%adduction%' OR LOWER(name) LIKE '%adductor%') "
        "AND LOWER(target_muscle) = 'adductors'",
        "isolation",
        ("leverage machine", "cable", "body weight"),
        reps=(8, 10),
        rest_seconds=150,
        exclude_sql="LOWER(name) NOT LIKE '%stretch%'",
        primary_actions=("Hip Adduction",),
        primary_muscles=("Adductors",),
    ),
    "calf": _slot(
        "calf",
        "(LOWER(name) LIKE '%calf raise%' OR LOWER(name) LIKE '%calf press%' OR LOWER(name) LIKE '%calf%') "
        "AND LOWER(target_muscle) = 'calves'",
        "isolation",
        ("smith machine", "sled machine", "leverage machine", "barbell", "dumbbell", "body weight", "band"),
        reps=(5, 9),
        rest_seconds=120,
        exclude_sql="LOWER(name) NOT LIKE '%stretch%' AND LOWER(name) NOT LIKE '%tibialis%'",
        name_rank=("calf raise", "calf press", "seated calf", "standing calf"),
        primary_actions=("Ankle Plantar Flexion",),
        primary_muscles=("Calves",),
    ),
    # --- Core --------------------------------------------------------------
    "abs": _slot(
        "abs",
        "(LOWER(name) LIKE '%crunch%' OR LOWER(name) LIKE '%sit-up%' OR LOWER(name) LIKE '%sit up%') "
        "AND LOWER(target_muscle) = 'abs'",
        "isolation",
        ("cable", "leverage machine", "body weight", "dumbbell", "stability ball"),
        reps=(8, 12),
        rest_seconds=120,
        exclude_sql="LOWER(name) NOT LIKE '%stretch%' AND LOWER(name) NOT LIKE '%twist%'",
        name_rank=("cable", "kneeling", "seated", "machine"),
        primary_actions=("Spinal Flexion",),
        primary_muscles=("Abs",),
    ),
}

validate_slot_signatures(SLOT_SPECS)

# Ordered Staple exercises by movement slot. IDs are the Exercise library's
# stable ExerciseDB IDs or MAYOS-authored IDs. Names are documented beside
# them for readability; generation resolves IDs only.
SLOT_STAPLES: dict[str, tuple[str, ...]] = {
    "incline_press": ("314", "757", "47", "1299"),  # incline DB press; Smith Incline Press; BB incline press; machine incline press
    "flat_press": ("576", "25", "289", "748"),  # machine chest press; BB bench; DB bench; Smith bench
    "chest_fly": ("596", "171", "1278", "1286"),  # Pec Deck; cable incline fly; DB incline fly; DB chest fly
    "horizontal_row": ("1350", "606", "327", "2298"),  # machine seated row; lever T-bar row; incline DB row; inverted row
    "upper_back_pull": ("606", "327", "1331", "3156"),  # lever T-bar row; incline DB row; reverse-grip incline row; bodyweight row
    "vertical_pull": ("150", "3563", "2330", "1429", "652"),  # Lat Pulldown; standing single-arm pulldown; Standing Cable Pulldown; wide-grip pull-up; pull-up
    "pullover": ("184", "2285", "375", "1255"),  # cable pullover; machine pullover; DB pullover; BB pullover
    "shrug": ("305", "220", "406", "95", "604"),  # dumbbell Kelso shrug; cable; DB; BB; machine shrug
    "shoulder_press": ("869", "587", "405", "766", "91"),  # iso-lateral machine press; plate-loaded machine press; seated DB press; Smith press; BB overhead press
    "side_delts": ("178", "584", "395", "977"),  # cable lateral raise; machine lateral raise; seated DB raise; band raise
    "rear_delts": ("mayos:3", "602", "225", "359", "993"),  # MAYOS cable Y-raise; Reverse Pec Deck; cable fly; DB fly; band fly
    "biceps_preacher": ("592", "372", "70", "1633"),  # machine preacher curl; DB preacher curl; BB preacher curl; cable preacher curl
    "biceps_alt": ("318", "mayos:2", "1630", "31", "1769"),  # Incline DB Curl; MAYOS Bayesian curl; cable/BB curl; bodyweight curl
    "triceps_pushdown": ("1723", "201", "200", "241"),  # one-arm pushdown; cable pushdown; rope pushdown; V-bar pushdown
    "triceps_overhead": ("194", "92", "2188", "453", "1771"),  # overhead cable extension; BB/DB/EZ extensions; bodyweight extension
    "forearm_wrist": ("1412", "401", "247", "125"),  # palms-up BB curl; seated DB curl; cable curl; BB curl
    "forearm_reverse": ("1411", "385", "210", "82"),  # palms-down BB curl; DB reverse curl; cable reverse curl; BB reverse curl
    "quad_compound": ("743", "29", "1436", "770", "1476"),  # sled hack squat; front squat; high-bar squat; Smith squat; one-leg squat
    "quad_lunge": ("336", "3470", "54", "1460"),  # DB lunge; forward lunge; BB lunge; walking lunge
    "quad_iso": ("585", "3007"),  # machine leg extension; resistance-band leg extension
    "ham_curl": ("599", "586", "1766", "496", "795"),  # seated curl; lying curl; inverse curl; bench curl; standing curl
    "ham_hinge": ("85", "1459", "44"),  # BB RDL; DB RDL; BB good morning
    "glute_thrust": ("mayos:4", "3562", "3236", "3013"),  # MAYOS machine hip thrust; Barbell Hip Thrust; band; glute bridge
    "glute_iso": ("2286", "597", "3006", "130", "1423", "710", "1774"),  # machine extension/abduction; band abduction; bench extension/reverse hyper; bodyweight abduction
    "adductors": ("598", "168", "1775", "3667"),  # Hip Adduction; cable adduction; side-plank adduction; side-lying adduction
    "calf": ("1375", "1372", "1373", "1371"),  # cable standing calf raise; BB standing; bodyweight standing; BB seated
    "abs": ("175", "595", "274", "267"),  # Cable Crunch; machine crunch; floor crunch; hands-overhead crunch
}


# --- General warm-up block (Belghamdi protocol) ----------------------------

WARMUP_SPECS: dict[str, dict[str, object]] = {
    "scapula_push_plus": {
        "sql": "LOWER(name) LIKE '%scapula push%'",
        "equipment_access_aware": True,
    },
    "y_raise_rear": {
        "sql": "(LOWER(name) LIKE '%y-raise%' OR LOWER(name) LIKE '%reverse fly%' "
        "OR LOWER(name) LIKE '%rear delt fly%' OR LOWER(name) LIKE '%rear lateral%')",
        "equipment_access_aware": True,
        "fallbacks": ("scapula_push_plus",),
    },
    "pallof_press": {
        "sql": "LOWER(name) LIKE '%pallof%'",
        "equipment_pref": ("band", "resistance band", "body weight", "cable", "dumbbell", "leverage machine"),
        "equipment_access_aware": True,
        "fallbacks": ("shoulder_tap",),
    },
    "shoulder_tap": {
        "sql": "LOWER(name) = 'shoulder tap'",
        "equipment_access_aware": True,
    },
    "external_rotation": {
        "sql": "LOWER(name) LIKE '%external rotation%'",
        "equipment_access_aware": True,
        "fallbacks": ("y_raise_rear", "scapula_push_plus"),
        "equipment_pref_by_access": {
            HOME_GYM: ("dumbbell", "band", "body weight", "cable", "leverage machine"),
        },
        "name_rank_by_access": {HOME_GYM: ("standing",)},
    },
    "internal_rotation": {
        "sql": "LOWER(body_part) = 'shoulders' AND LOWER(name) LIKE '%internal rotation%'",
        "equipment_access_aware": True,
        "fallbacks": ("scapula_push_plus",),
    },
    "dead_bug": {
        "sql": "LOWER(name) = 'dead bug'",
    },
    "glute_bridge": {
        "sql": "(LOWER(name) LIKE '%glute bridge%' OR LOWER(name) LIKE '%hip bridge%')",
    },
    "reverse_hyper": {
        "sql": "(LOWER(name) LIKE '%reverse hyper%' OR LOWER(name) LIKE '%back extension%')",
    },
}

WARMUP_FAMILIES: dict[str, tuple[str, ...]] = {
    "upper": ("internal_rotation", "external_rotation", "pallof_press"),
    "lower": ("glute_bridge", "dead_bug", "reverse_hyper"),
    "full": ("external_rotation", "glute_bridge", "pallof_press"),
    "arms": ("y_raise_rear", "external_rotation", "pallof_press"),
}

WARMUP_SETS = 2
WARMUP_REPS = 10
WARMUP_REST_SECONDS = 45



@dataclass(frozen=True)
class DayBlueprint:
    """One session template: an ordered tuple of slot keys plus metadata."""

    name: str
    slots: tuple[str, ...]
    family: str = "full"
    cardio: str | None = None
    sets_family: str | None = None
    double_slots: tuple[str, ...] = ()


COMPOUND_ARCHETYPES = {"heavy_compound", "medium_compound"}

#: Leg-focused movements that earn a second working set on lower-body days.
#: Isolations only — compounds always carry 2 and never consume a recovery cut.
LEG_STAPLE_SLOTS = frozenset({"quad_iso", "ham_curl", "adductors", "glute_iso", "abs"})

#: Isolation slots that earn a second working set on dedicated arm/push/pull days.
ARM_ISOLATION_SLOTS = frozenset(
    {
        "side_delts",
        "rear_delts",
        "shrug",
        "pullover",
        "chest_fly",
        "biceps_preacher",
        "biceps_alt",
        "triceps_pushdown",
        "triceps_overhead",
        "forearm_wrist",
        "forearm_reverse",
    }
)

SETS_FAMILY_BY_DAY_FAMILY = {"lower": "leg", "arms": "arms", "upper": "standard", "full": "full"}

#: Upper bound on escalated-set reductions applied per day under poor recovery,
#: so fatigue management shaves accessory volume without gutting dense splits.
MAX_RECOVERY_CUTS_PER_DAY = 4
# Keep recovery cuts proportional in low-volume coach-pattern weeks.
MAX_COACH_PATTERN_RECOVERY_CUTS_PER_DAY = 2

#: Safe movement-slot substitutes when a limitation or Equipment access filter
#: empties the original candidate pool. ``None`` applies to every Equipment
#: access value; named keys apply only to that canonical Equipment access.
SLOT_FALLBACKS: dict[str, dict[str | None, tuple[str, ...]]] = {
    # The back limitation can empty this slot's hinge pool; leg curls are safe.
    "ham_hinge": {None: ("ham_curl",)},
    # Bodyweight-only libraries cannot fill every gym-specific isolation slot.
    # Use a nearby bodyweight slot while retaining the existing slot picker.
    # Bodyweight-only has no direct Staples for these gym-specific slots.
    "incline_press": {BODYWEIGHT_ONLY: ("flat_press", "quad_lunge")},
    "flat_press": {BODYWEIGHT_ONLY: ("quad_lunge", "vertical_pull")},
    "chest_fly": {BODYWEIGHT_ONLY: ("quad_lunge", "vertical_pull")},
    "pullover": {BODYWEIGHT_ONLY: ("vertical_pull", "horizontal_row")},
    "shrug": {BODYWEIGHT_ONLY: ("upper_back_pull", "horizontal_row")},
    "side_delts": {BODYWEIGHT_ONLY: ("upper_back_pull", "vertical_pull")},
    "rear_delts": {BODYWEIGHT_ONLY: ("upper_back_pull", "horizontal_row")},
    "shoulder_press": {BODYWEIGHT_ONLY: ("quad_lunge", "vertical_pull")},
    "triceps_pushdown": {HOME_GYM: ("triceps_overhead",), BODYWEIGHT_ONLY: ("triceps_overhead", "vertical_pull")},
    "triceps_overhead": {BODYWEIGHT_ONLY: ("vertical_pull", "biceps_alt")},
    "biceps_preacher": {BODYWEIGHT_ONLY: ("biceps_alt", "vertical_pull")},
    "biceps_alt": {BODYWEIGHT_ONLY: ("vertical_pull",)},
    "forearm_wrist": {BODYWEIGHT_ONLY: ("biceps_alt", "vertical_pull")},
    "forearm_reverse": {BODYWEIGHT_ONLY: ("biceps_alt", "vertical_pull")},
    "quad_iso": {BODYWEIGHT_ONLY: ("quad_lunge", "quad_compound")},
}


def resolve_sets_family(day_family: str, explicit: str | None = None) -> str:
    """Resolves the working-set profile for a session (explicit value wins)."""
    return explicit or SETS_FAMILY_BY_DAY_FAMILY.get(day_family, "standard")


def is_escalated_isolation(slot_key: str, sets_family: str) -> bool:
    """True when the slot earns its second set purely through a family escalation."""
    if sets_family in {"leg", "coach"} and slot_key in LEG_STAPLE_SLOTS:
        return True
    return sets_family in {"arms", "coach"} and slot_key in ARM_ISOLATION_SLOTS


def slot_working_sets(
    slot_key: str,
    archetype: str,
    sets_family: str,
    double_slots: tuple[str, ...] = (),
    recovery_cut: bool = False,
) -> int:
    """Return the prescribed working-set count for one slot occurrence.

    Compounds and calves carry 2 sets. Leg and arm focus days escalate their
    staple isolations; coach-pattern days escalate both groups. ``double_slots``
    supports explicit priorities in other plans. A recovery cut drops
    escalated isolations to 1 set without changing the day's selection, order,
    or frequency.
    """
    if recovery_cut and is_escalated_isolation(slot_key, sets_family):
        return 1
    if slot_key == "calf":
        return CALF_WORKING_SET_COUNT
    if sets_family == "full" and double_slots:
        return 2 if slot_key in double_slots else 1
    if slot_key in double_slots:
        return 2
    if archetype in COMPOUND_ARCHETYPES:
        return 2
    if is_escalated_isolation(slot_key, sets_family):
        return 2
    return 1


# --- Day templates (mirroring the reference programs) ----------------------

FB_DAYS: tuple[DayBlueprint, ...] = (
    DayBlueprint(
        "Full Body #1",
        (
            "incline_press",
            "horizontal_row",
            "side_delts",
            "vertical_pull",
            "biceps_preacher",
            "triceps_pushdown",
            "ham_curl",
            "quad_iso",
            "calf",
            "rear_delts",
            "forearm_wrist",
        ),
        family="full",
        double_slots=("incline_press", "horizontal_row"),
    ),
    DayBlueprint(
        "Full Body #2",
        (
            "quad_compound",
            "ham_curl",
            "adductors",
            "horizontal_row",
            "flat_press",
            "upper_back_pull",
            "shoulder_press",
            "biceps_preacher",
            "triceps_pushdown",
            "rear_delts",
            "abs",
        ),
        family="full",
        double_slots=("quad_compound", "flat_press"),
    ),
    DayBlueprint(
        "Full Body #3",
        (
            "ham_hinge",
            "upper_back_pull",
            "shrug",
            "incline_press",
            "quad_iso",
            "side_delts",
            "biceps_alt",
            "triceps_overhead",
            "adductors",
            "calf",
            "forearm_wrist",
        ),
        family="full",
        double_slots=("ham_hinge", "incline_press"),
    ),
    DayBlueprint(
        "Full Body #4",
        (
            "flat_press",
            "vertical_pull",
            "horizontal_row",
            "shoulder_press",
            "side_delts",
            "biceps_alt",
            "triceps_pushdown",
            "quad_compound",
            "ham_curl",
            "calf",
            "abs",
        ),
        family="full",
        double_slots=("flat_press", "vertical_pull"),
    ),
    DayBlueprint(
        "Full Body #5",
        (
            "incline_press",
            "vertical_pull",
            "shrug",
            "chest_fly",
            "side_delts",
            "rear_delts",
            "biceps_preacher",
            "triceps_overhead",
            "quad_iso",
            "glute_iso",
            "calf",
            "abs",
        ),
        family="full",
        double_slots=("incline_press", "vertical_pull"),
    ),
)

FEMALE_FB_DAYS: tuple[DayBlueprint, ...] = (
    DayBlueprint(
        "Glute Full Body #1",
        (
            "glute_thrust",
            "quad_compound",
            "vertical_pull",
            "incline_press",
            "side_delts",
            "biceps_preacher",
            "triceps_pushdown",
            "forearm_wrist",
            "abs",
        ),
        family="full",
        sets_family="leg",
    ),
    DayBlueprint(
        "Glute Full Body #2",
        (
            "ham_hinge",
            "glute_iso",
            "ham_curl",
            "adductors",
            "flat_press",
            "horizontal_row",
            "shrug",
            "triceps_pushdown",
            "biceps_alt",
            "calf",
        ),
        family="full",
        sets_family="leg",
    ),
    DayBlueprint(
        "Glute Full Body #3",
        (
            "glute_thrust",
            "quad_lunge",
            "quad_iso",
            "flat_press",
            "side_delts",
            "rear_delts",
            "triceps_overhead",
            "biceps_preacher",
            "vertical_pull",
        ),
        family="full",
        sets_family="leg",
    ),
    DayBlueprint(
        "Glute Full Body #4",
        (
            "glute_thrust",
            "ham_hinge",
            "quad_iso",
            "vertical_pull",
            "horizontal_row",
            "side_delts",
            "triceps_pushdown",
            "abs",
        ),
        family="full",
        sets_family="leg",
    ),
    DayBlueprint(
        "Glute Full Body #5",
        (
            "glute_iso",
            "quad_lunge",
            "ham_curl",
            "incline_press",
            "chest_fly",
            "biceps_alt",
            "triceps_overhead",
            "calf",
        ),
        family="full",
        sets_family="leg",
    ),
)

UL_DAYS: tuple[DayBlueprint, ...] = (
    DayBlueprint(
        "Upper 1",
        (
            "flat_press",
            "horizontal_row",
            "chest_fly",
            "pullover",
            "vertical_pull",
            "shrug",
            "side_delts",
            "rear_delts",
            "biceps_preacher",
            "triceps_pushdown",
            "forearm_wrist",
        ),
        family="upper",
        cardio="Light cardio: 10-20 min incline walk or cycling after the session",
    ),
    DayBlueprint(
        "Lower 1",
        (
            "quad_compound",
            "quad_iso",
            "ham_curl",
            "adductors",
            "glute_iso",
            "calf",
            "abs",
            "side_delts",
            "triceps_overhead",
            "biceps_alt",
        ),
        family="lower",
        cardio="Light cardio: 10 min cycling after the session",
    ),
    DayBlueprint(
        "Upper 2",
        (
            "incline_press",
            "vertical_pull",
            "chest_fly",
            "horizontal_row",
            "upper_back_pull",
            "shrug",
            "side_delts",
            "rear_delts",
            "biceps_alt",
            "triceps_pushdown",
            "triceps_overhead",
        ),
        family="upper",
        cardio="Light cardio: 20 min incline walk after the session",
    ),
    DayBlueprint(
        "Lower 2",
        (
            "ham_hinge",
            "ham_curl",
            "quad_iso",
            "adductors",
            "glute_thrust",
            "calf",
            "abs",
            "side_delts",
            "biceps_alt",
            "rear_delts",
        ),
        family="lower",
        cardio="Light cardio: 10 min cycling after the session",
    ),
    DayBlueprint(
        "Upper 3",
        (
            "flat_press",
            "incline_press",
            "horizontal_row",
            "vertical_pull",
            "shoulder_press",
            "chest_fly",
            "side_delts",
            "rear_delts",
            "biceps_preacher",
            "triceps_pushdown",
            "forearm_reverse",
        ),
        family="upper",
    ),
)

ARNOLD_DAYS: tuple[DayBlueprint, ...] = (
    DayBlueprint(
        "Chest & Back",
        (
            "incline_press",
            "horizontal_row",
            "flat_press",
            "vertical_pull",
            "upper_back_pull",
            "shrug",
            "rear_delts",
        ),
        family="upper",
    ),
    DayBlueprint(
        "Shoulders & Arms",
        (
            "side_delts",
            "triceps_pushdown",
            "shoulder_press",
            "biceps_preacher",
            "forearm_reverse",
            "triceps_overhead",
            "forearm_wrist",
        ),
        family="arms",
    ),
    DayBlueprint(
        "Legs",
        (
            "calf",
            "quad_compound",
            "ham_curl",
            "quad_iso",
            "glute_iso",
            "adductors",
            "abs",
        ),
        family="lower",
    ),
)

ARNOLD_X_UL_DAYS: tuple[DayBlueprint, ...] = (
    ARNOLD_DAYS[0],
    ARNOLD_DAYS[1],
    DayBlueprint(
        "Lower A",
        (
            "ham_curl",
            "adductors",
            "glute_iso",
            "quad_iso",
            "calf",
            "abs",
        ),
        family="lower",
    ),
    DayBlueprint(
        "Upper",
        (
            "vertical_pull",
            "upper_back_pull",
            "flat_press",
            "horizontal_row",
            "incline_press",
            "biceps_alt",
            "triceps_pushdown",
        ),
        family="upper",
    ),
    DayBlueprint(
        "Lower B",
        (
            "side_delts",
            "calf",
            "quad_compound",
            "quad_iso",
            "adductors",
            "rear_delts",
        ),
        family="lower",
    ),
)

ANTERIOR_POSTERIOR_DAYS: tuple[DayBlueprint, ...] = (
    DayBlueprint(
        "Anterior",
        (
            "incline_press",
            "flat_press",
            "shoulder_press",
            "side_delts",
            "triceps_pushdown",
            "triceps_overhead",
            "quad_compound",
            "abs",
        ),
        family="upper",
    ),
    DayBlueprint(
        "Posterior",
        (
            "vertical_pull",
            "horizontal_row",
            "shrug",
            "rear_delts",
            "biceps_preacher",
            "biceps_alt",
            "forearm_wrist",
            "ham_curl",
            "calf",
        ),
        family="upper",
    ),
    DayBlueprint(
        "Anterior 2",
        (
            "flat_press",
            "incline_press",
            "chest_fly",
            "side_delts",
            "quad_iso",
            "quad_lunge",
            "abs",
            "triceps_pushdown",
        ),
        family="upper",
    ),
    DayBlueprint(
        "Posterior 2",
        (
            "ham_hinge",
            "ham_curl",
            "glute_thrust",
            "glute_iso",
            "upper_back_pull",
            "rear_delts",
            "forearm_reverse",
            "biceps_alt",
            "calf",
        ),
        family="lower",
    ),
    DayBlueprint(
        "Anterior 3",
        (
            "incline_press",
            "shoulder_press",
            "chest_fly",
            "side_delts",
            "biceps_alt",
            "quad_compound",
            "quad_iso",
            "abs",
        ),
        family="upper",
    ),
)

PPL_DAYS: tuple[DayBlueprint, ...] = (
    DayBlueprint(
        "Push",
        (
            "incline_press",
            "flat_press",
            "shoulder_press",
            "side_delts",
            "triceps_pushdown",
            "triceps_overhead",
            "abs",
        ),
        family="upper",
        sets_family="arms",
    ),
    DayBlueprint(
        "Pull",
        (
            "vertical_pull",
            "horizontal_row",
            "upper_back_pull",
            "shrug",
            "rear_delts",
            "biceps_preacher",
            "forearm_wrist",
        ),
        family="upper",
        sets_family="arms",
    ),
    DayBlueprint(
        "Legs",
        (
            "quad_compound",
            "quad_iso",
            "ham_curl",
            "ham_hinge",
            "adductors",
            "calf",
            "abs",
        ),
        family="lower",
    ),
)

PPL_X_UL_DAYS: tuple[DayBlueprint, ...] = (
    *PPL_DAYS,
    replace(UL_DAYS[2], name="Upper"),
    replace(
        UL_DAYS[1],
        name="Lower",
        slots=(
            "quad_compound",
            "quad_iso",
            "ham_curl",
            "adductors",
            "glute_iso",
            "calf",
            "abs",
        ),
    ),
)

FEMALE_UL_DAYS: tuple[DayBlueprint, ...] = (
    DayBlueprint(
        "Lower 1 (Glute & Quad)",
        (
            "glute_thrust",
            "quad_compound",
            "ham_curl",
            "adductors",
            "calf",
            "abs",
            "side_delts",
            "triceps_pushdown",
        ),
        family="lower",
    ),
    DayBlueprint(
        "Upper 1",
        (
            "vertical_pull",
            "incline_press",
            "horizontal_row",
            "side_delts",
            "rear_delts",
            "biceps_preacher",
            "triceps_pushdown",
            "forearm_wrist",
        ),
        family="upper",
    ),
    DayBlueprint(
        "Lower 2 (Glute & Hamstring)",
        (
            "ham_hinge",
            "glute_iso",
            "quad_iso",
            "ham_curl",
            "calf",
            "abs",
            "side_delts",
            "biceps_alt",
        ),
        family="lower",
    ),
    DayBlueprint(
        "Upper 2",
        (
            "incline_press",
            "flat_press",
            "vertical_pull",
            "chest_fly",
            "side_delts",
            "rear_delts",
            "biceps_alt",
            "triceps_overhead",
        ),
        family="upper",
    ),
    DayBlueprint(
        "Lower 3 (Glute Pump)",
        (
            "glute_thrust",
            "quad_lunge",
            "adductors",
            "ham_curl",
            "calf",
            "abs",
            "triceps_pushdown",
            "side_delts",
        ),
        family="lower",
    ),
)


# The default three-to-five-day templates use a restrained weekly dose and
# repeat each broad muscle group on two or three separate days. Priority
# starters open the day before the remaining work is ordered by movement class.
_COACH_PATTERN_EVENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("chest", ("incline_press", "flat_press", "chest_fly")),
    ("back", ("vertical_pull", "horizontal_row", "shrug")),
    ("shoulders", ("shoulder_press", "side_delts", "rear_delts")),
    ("biceps", ("biceps_preacher", "biceps_alt")),
    ("triceps", ("triceps_pushdown", "triceps_overhead")),
    ("forearms", ("forearm_wrist", "forearm_reverse")),
    ("quads", ("quad_compound", "quad_iso")),
    ("hamstrings", ("ham_curl", "ham_hinge")),
    ("glutes", ("glute_thrust", "glute_iso")),
    ("adductors", ("adductors", "adductors")),
    ("calves", ("calf", "calf")),
    ("abs", ("abs", "abs")),
)

_COACH_PATTERN_THREE_DAY_SLOTS: tuple[tuple[str, ...], ...] = (
    (
        "incline_press", "vertical_pull", "shoulder_press", "biceps_preacher",
        "triceps_pushdown", "quad_compound", "ham_curl", "adductors", "calf",
    ),
    (
        "flat_press", "horizontal_row", "side_delts", "biceps_alt",
        "triceps_overhead", "forearm_wrist", "glute_thrust", "calf", "abs",
    ),
    (
        "chest_fly", "shrug", "rear_delts", "forearm_reverse", "quad_iso",
        "ham_hinge", "glute_iso", "adductors", "abs",
    ),
)

_SMALL_MUSCLE_OPENERS = (
    "side_delts", "calf", "adductors", "rear_delts", "forearm_wrist", "abs",
)


def _ordered_coach_day_slots(slots: list[str], day_index: int) -> tuple[str, ...]:
    opener = next(
        (
            slot
            for offset in range(len(_SMALL_MUSCLE_OPENERS))
            if (slot := _SMALL_MUSCLE_OPENERS[(day_index + offset) % len(_SMALL_MUSCLE_OPENERS)])
            in slots
        ),
        None,
    )
    remaining = [slot for slot in slots if slot != opener]
    archetype_order = {"heavy_compound": 0, "medium_compound": 1, "isolation": 2}
    remaining.sort(key=lambda slot: (archetype_order[SLOT_SPECS[slot].archetype], slot))
    return ((opener,) if opener else ()) + tuple(remaining)


def coach_pattern_days(frequency: int) -> list[DayBlueprint]:
    """Builds a low-volume default week with glutes at base volume."""
    return _coach_pattern_days(frequency, glute_exposures=2)


def glute_priority_days(frequency: int) -> list[DayBlueprint]:
    """Builds the default week with one additional glute exposure."""
    return _coach_pattern_days(frequency, glute_exposures=3)


def _coach_pattern_days(frequency: int, glute_exposures: int) -> list[DayBlueprint]:
    if frequency not in (3, 4, 5):
        return []
    assigned = (
        _three_day_coach_slots(glute_exposures)
        if frequency == 3
        else _distribute_coach_events(frequency, glute_exposures)
    )
    names = tuple(f"Full Body #{index}" for index in range(1, frequency + 1))
    return [
        DayBlueprint(
            name=names[index],
            slots=_ordered_coach_day_slots(slots, index),
            family="full",
            sets_family="coach",
            cardio=UL_DAYS[index].cardio if frequency == 4 else None,
        )
        for index, slots in enumerate(assigned)
    ]


def _three_day_coach_slots(glute_exposures: int) -> list[list[str]]:
    assigned = [list(slots) for slots in _COACH_PATTERN_THREE_DAY_SLOTS]
    if glute_exposures == 3:
        assigned[2].append("glute_thrust")
    return assigned


def _distribute_coach_events(frequency: int, glute_exposures: int) -> list[list[str]]:
    assigned = [[] for _ in range(frequency)]
    for group_index, (group, slots) in enumerate(_COACH_PATTERN_EVENTS):
        events = (*slots, "glute_thrust") if group == "glutes" and glute_exposures == 3 else slots
        _assign_group_events(assigned, group_index, events)
    return assigned


def _assign_group_events(assigned: list[list[str]], group_index: int, slots: tuple[str, ...]) -> None:
    frequency = len(assigned)
    used_days: set[int] = set()
    for slot in slots:
        candidates = [day for day in range(frequency) if day not in used_days]
        day_index = min(
            candidates,
            key=lambda day: (len(assigned[day]), (day - group_index) % frequency),
        )
        assigned[day_index].append(slot)
        used_days.add(day_index)


def coach_upper_lower_days(frequency: int) -> list[DayBlueprint]:
    """Build a balanced four-day Upper/Lower split with two weekly exposures."""
    if frequency != 4:
        return []
    return [
        DayBlueprint(
            "Upper 1",
            (
                "side_delts", "incline_press", "vertical_pull", "biceps_preacher",
                "triceps_pushdown", "forearm_wrist",
            ),
            family="upper",
            sets_family="coach",
            cardio=UL_DAYS[0].cardio,
        ),
        DayBlueprint(
            "Lower 1",
            ("adductors", "quad_compound", "ham_curl", "glute_thrust", "calf", "abs"),
            family="lower",
            sets_family="coach",
            cardio=UL_DAYS[1].cardio,
        ),
        DayBlueprint(
            "Upper 2",
            (
                "rear_delts", "flat_press", "horizontal_row", "shoulder_press",
                "biceps_alt", "triceps_overhead", "forearm_reverse", "shrug",
            ),
            family="upper",
            sets_family="coach",
            cardio=UL_DAYS[2].cardio,
        ),
        DayBlueprint(
            "Lower 2",
            ("calf", "quad_iso", "ham_hinge", "glute_iso", "adductors", "abs"),
            family="lower",
            sets_family="coach",
            cardio=UL_DAYS[3].cardio,
        ),
    ]


def coach_ppl_upper_lower_days(frequency: int) -> list[DayBlueprint]:
    """Build a five-day PPL + Upper/Lower split with balanced repeat work."""
    if frequency != 5:
        return []
    return [
        DayBlueprint(
            "Upper",
            (
                "forearm_wrist", "incline_press", "vertical_pull", "biceps_preacher",
                "triceps_pushdown",
            ),
            family="upper",
            sets_family="coach",
        ),
        DayBlueprint(
            "Lower",
            ("adductors", "quad_compound", "ham_curl", "glute_thrust", "calf", "abs"),
            family="lower",
            sets_family="coach",
        ),
        DayBlueprint(
            "Push",
            (
                "side_delts", "flat_press", "shoulder_press", "chest_fly",
                "triceps_overhead", "triceps_pushdown",
            ),
            family="upper",
            sets_family="coach",
        ),
        DayBlueprint(
            "Pull",
            ("rear_delts", "horizontal_row", "shrug", "biceps_alt", "forearm_reverse"),
            family="upper",
            sets_family="coach",
        ),
        DayBlueprint(
            "Legs",
            ("calf", "quad_iso", "ham_hinge", "glute_iso", "adductors", "abs"),
            family="lower",
            sets_family="coach",
        ),
    ]


_COACH_PATTERN_BUILDERS = {
    "full_body": coach_pattern_days,
    "female_full_body": glute_priority_days,
    "upper_lower": coach_upper_lower_days,
    "ppl_x_ul": coach_ppl_upper_lower_days,
}


SPLIT_DAY_POOLS: dict[str, tuple[DayBlueprint, ...]] = {
    "full_body": FB_DAYS,
    "female_full_body": FEMALE_FB_DAYS,
    "upper_lower": UL_DAYS,
    "female_upper_lower": FEMALE_UL_DAYS,
    "arnold": ARNOLD_DAYS,
    "arnold_x_ul": ARNOLD_X_UL_DAYS,
    "anterior_posterior": ANTERIOR_POSTERIOR_DAYS,
    "ppl": PPL_DAYS,
    "ppl_x_ul": PPL_X_UL_DAYS,
}

SPLIT_SUPPORTED_FREQUENCIES: dict[str, tuple[int, ...]] = {
    "full_body": (1, 2, 3, 4, 5),
    "female_full_body": (1, 2, 3, 4, 5),
    "upper_lower": (2, 3, 4, 5),
    "female_upper_lower": (2, 3, 4, 5),
    "arnold": (3,),
    "arnold_x_ul": (5,),
    "anterior_posterior": (2, 3, 4, 5),
    "ppl": (3,),
    "ppl_x_ul": (5,),
}

SPLIT_TYPE_ALIASES_BY_FREQUENCY: dict[tuple[str, int], str] = {
    ("arnold", 5): "arnold_x_ul",
    ("ppl", 5): "ppl_x_ul",
}

SPLIT_DISPLAY_NAMES: dict[str, str] = {
    "full_body": "Full Body",
    "female_full_body": "Full Body (Glute Priority)",
    "upper_lower": "Upper / Lower (Arms & Delts Augmented)",
    "female_upper_lower": "Lower (Glute Bias) / Upper & Core",
    "arnold": "Arnold Split (Chest & Back / Shoulders & Arms / Legs)",
    "arnold_x_ul": "Arnold × Upper/Lower",
    "anterior_posterior": "Anterior / Posterior Split",
    "ppl": "PPL",
    "ppl_x_ul": "PPL × UL",
}


def _pool_for(split_type: str, gender: str) -> tuple[DayBlueprint, ...] | None:
    if split_type == "full_body":
        return FB_DAYS
    if split_type == "upper_lower":
        return UL_DAYS
    return SPLIT_DAY_POOLS.get(split_type)


def resolve_split_type(split_type: str, frequency: int) -> str:
    """Five-day Arnold and PPL requests map onto their Upper/Lower hybrids.

    The Arnold hybrid retains the reference five-day shape. The PPL hybrid
    keeps Push/Pull/Legs and adds one existing Upper and Lower blueprint.
    """
    return SPLIT_TYPE_ALIASES_BY_FREQUENCY.get((split_type, frequency), split_type)


def build_split_days(split_type: str, frequency: int, gender: str = "male") -> list[DayBlueprint] | None:
    """Returns the day templates for a supported split/frequency, else None.

    Unsupported split/frequency combinations return None so the caller can
    use the player's deterministic frequency default.
    """
    split_type = resolve_split_type(split_type, frequency)
    if frequency not in SPLIT_SUPPORTED_FREQUENCIES.get(split_type, ()):
        return None
    coach_pattern_builder = _COACH_PATTERN_BUILDERS.get(split_type)
    if coach_pattern_builder and frequency in (3, 4, 5):
        coach_days = coach_pattern_builder(frequency)
        if coach_days:
            return coach_days
    pool = _pool_for(split_type, gender)
    if not pool:
        return None
    return list(pool[:frequency])


DEFAULT_SPLIT_BY_FREQUENCY: dict[str, dict[int, str]] = {
    gender: {
        1: "full_body",
        2: "full_body",
        3: "full_body",
        4: "upper_lower",
        5: "ppl_x_ul",
    }
    for gender in ("male", "female")
}


# Deterministic keyword routing for free-text split preferences. Word-boundary
# regex keeps body-part phrases ("lower back pain", "upper chest focus",
# "posterior chain") from hijacking the split router. Glute-priority prose is
# left for the planner; only its exact catalog label or id is deterministic.
SPLIT_KEYWORD_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "anterior_posterior",
        (
            re.compile(r"\banterior\b"),
            re.compile(r"\bposterior\s+split\b"),
            re.compile(r"\banterior[\s/]*posterior\b"),
        ),
    ),
    (
        "arnold_x_ul",
        (
            re.compile(r"\barnold\s*(?:x|×)\s*(?:upper\s*/\s*lower|u\s*/\s*l|ul)\b"),
            re.compile(r"\barnold[\s\S]*\bupper\b[\s\S]*\blower\b"),
            re.compile(r"\barnold[\s\S]*\blower\b[\s\S]*\bupper\b"),
        ),
    ),
    ("arnold", (re.compile(r"\barnold\b"),)),
    (
        "ppl_x_ul",
        (
            re.compile(r"\bppl\s*(?:x|×)\s*(?:upper\s*/\s*lower|u\s*/\s*l|ul)\b"),
            re.compile(r"\bppl[\s\S]*\bupper\s*[-/\s]\s*lower\b"),
        ),
    ),
    (
        "upper_lower",
        (
            re.compile(r"\bupper\s*/\s*lower\b"),
            re.compile(r"\bu\s*/\s*l\b"),
            re.compile(r"\bupper\b[\s\S]*\blower\b"),
            re.compile(r"\blower\b[\s\S]*\bupper\b"),
        ),
    ),
    ("ppl", (re.compile(r"\bppl\b"), re.compile(r"\bpush[\s,/*-]*pull[\s,/*-]*legs\b"))),
    (
        "full_body",
        (
            re.compile(r"\bfull[-\s]?body\b"),
            re.compile(r"\bfullbody\b"),
            re.compile(r"\btotal\s+body\b"),
        ),
    ),
)


def match_split_keyword(preference: str | None) -> str | None:
    if not preference:
        return None
    text = preference.strip().casefold()
    if text in {
        "female_full_body",
        SPLIT_DISPLAY_NAMES["female_full_body"].casefold(),
    }:
        return "female_full_body"
    for split_type, patterns in SPLIT_KEYWORD_PATTERNS:
        if any(pattern.search(text) for pattern in patterns):
            return split_type
    return None


# Goals modulate ONLY the cardio layer: lifting blueprints, exercise selection
# and prescriptions stay identical for every goal (cutting must not dilute the
# training that preserves muscle). Word-boundary patterns keep "hypertrophy",
# "bulking", "muscle gain", "strength" and "progressive overload" inert.
FAT_LOSS_GOAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bfat\s*loss\b",
        r"\blos(?:e|ing)\s+(?:\w+\s+){0,3}weight\b",
        r"\bweight\s*loss\b",
        r"\bcut(?:ting)?\b",
        r"\bget\s+lean\b",
        r"\blean\s+(?:out|down)\b",
        r"\bshred(?:ding)?\b",
        r"\b(?:burn(?:ing)?|reduc(?:e|ing)|drop(?:ping)?|lower(?:ing)?|los(?:e|ing))\s+"
        r"(?:\w+\s+){0,2}(?:body\s*)?fat\b",
        r"\bfat\s*reduction\b",
        r"\bslim(?:ming)?\s*down\b",
        r"\b(?:get|look)(?:ing|s)?\s+(?:more\s+)?defined\b",
        r"\brecomp(?:osition)?\b",
        r"\bton(?:e|es|ed|ing)(?:\s*up)?\b",
    )
)

FAT_LOSS_CARDIO_NOTE = (
    "Fat-loss finisher: 20-30 min incline treadmill walk (8-12% incline, brisk ~4-5 km/h) "
    "or moderate cycling, after the session"
)


def is_fat_loss_goal(current_goal: str | None, long_term_goal: str | None = None) -> bool:
    """True when the player's stated goal is fat loss (checks both goal fields)."""
    for goal in (current_goal, long_term_goal):
        if not goal:
            continue
        text = goal.lower()
        if any(pattern.search(text) for pattern in FAT_LOSS_GOAL_PATTERNS):
            return True
    return False


# Recovery signals modulate ONLY escalated-accessory volume (see
# ``slot_working_sets``): poor stress/sleep never changes exercise selection,
# order or frequency. Word-boundary patterns keep neutral narratives
# ("good sleep, 8 hours, low stress") inert.
POOR_RECOVERY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:poor|bad|terrible|low)\s+(?:sleep|recovery)\b",
        r"\black\s+of\s+sleep\b",
        r"\binsomnia\b",
        r"\bsleep\s+depriv(?:ed|ation)\b",
        r"\b(?:high|heavy|lots?\s+of)\s+stress\b",
        r"\bstressed\b",
        r"\b(?:4|5|6|four|five|six)\s*(?:-|to)?\s*hours\b",
    )
)


def is_poor_recovery(stress_and_sleep: str | None) -> bool:
    """True when the stress/sleep narrative signals reduced recovery capacity."""
    if not stress_and_sleep:
        return False
    text = stress_and_sleep.lower()
    return any(pattern.search(text) for pattern in POOR_RECOVERY_PATTERNS)


# Fallback used when the LLM returns legacy muscle targets instead of slot keys.
BODY_PART_TO_SLOTS: dict[str, tuple[str, ...]] = {
    "chest": ("incline_press", "flat_press"),
    "lats": ("vertical_pull", "upper_back_pull"),
    "upper back": ("horizontal_row", "upper_back_pull"),
    "traps": ("shrug",),
    "side delts": ("side_delts",),
    "rear delts": ("rear_delts",),
    "front delts": ("shoulder_press",),
    "biceps": ("biceps_preacher", "biceps_alt"),
    "triceps": ("triceps_pushdown", "triceps_overhead"),
    "forearms": ("forearm_wrist", "forearm_reverse"),
    "quads": ("quad_compound", "quad_iso"),
    "hamstrings": ("ham_curl", "ham_hinge"),
    "glutes": ("glute_thrust", "glute_iso"),
    "adductors": ("adductors",),
    "calves": ("calf",),
    "abs": ("abs",),
}


def body_parts_to_slots(target_body_parts: list[str]) -> list[str]:
    """Maps legacy muscle targets onto representative slot keys, de-duplicated."""
    slots: list[str] = []
    for part in target_body_parts:
        for slot_key in BODY_PART_TO_SLOTS.get(part.strip().lower(), ()):
            if slot_key not in slots:
                slots.append(slot_key)
    return slots
