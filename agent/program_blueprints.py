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
embedded here: the UI shows the catalog's own form demos and trainees can ask
the coaching assistant for cues.
"""

import re
from dataclasses import dataclass
from typing import Literal

Archetype = Literal["heavy_compound", "medium_compound", "isolation"]


@dataclass(frozen=True)
class SlotSpec:
    """One movement slot and everything the assembler needs to fill it."""

    key: str
    sql: str
    archetype: Archetype
    equipment_pref: tuple[str, ...]
    reps: tuple[int, int]
    rest_seconds: int
    warmup_sets: int = 0
    exclude_sql: str = ""
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
    name_rank: tuple[str, ...] = (),
) -> SlotSpec:
    return SlotSpec(
        key=key,
        sql=sql,
        archetype=archetype,
        equipment_pref=equipment_pref,
        reps=reps,
        rest_seconds=rest_seconds,
        warmup_sets=warmup_sets,
        exclude_sql=exclude_sql,
        name_rank=name_rank,
    )


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
    ),
    "chest_fly": _slot(
        "chest_fly",
        "(LOWER(name) LIKE '%fly%' OR LOWER(name) LIKE '%pec deck%') AND LOWER(target_muscle) = 'pectorals'",
        "isolation",
        ("cable", "leverage machine", "dumbbell", "band"),
        reps=(8, 10),
        rest_seconds=180,
        name_rank=("incline", "middle", "flat", "fly", "pec deck"),
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
    ),
    "pullover": _slot(
        "pullover",
        "(LOWER(name) LIKE '%pullover%' OR LOWER(name) LIKE '%straight arm pulldown%')",
        "isolation",
        ("cable", "dumbbell", "barbell"),
        reps=(8, 10),
        rest_seconds=180,
        exclude_sql="LOWER(name) NOT LIKE '%stretch%'",
    ),
    "shrug": _slot(
        "shrug",
        "LOWER(name) LIKE '%shrug%'",
        "isolation",
        ("leverage machine", "smith machine", "cable", "dumbbell", "barbell", "band"),
        reps=(6, 10),
        rest_seconds=180,
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
        warmup_sets=1,
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
    ),
    # --- Arms --------------------------------------------------------------
    "biceps_preacher": _slot(
        "biceps_preacher",
        "LOWER(name) LIKE '%preacher%' AND LOWER(target_muscle) IN ('biceps', 'brachialis')",
        "isolation",
        ("dumbbell", "cable", "leverage machine", "ez barbell", "barbell", "smith machine"),
        reps=(6, 10),
        rest_seconds=180,
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
    ),
    "triceps_pushdown": _slot(
        "triceps_pushdown",
        "LOWER(name) LIKE '%pushdown%' AND LOWER(target_muscle) = 'triceps'",
        "isolation",
        ("cable", "leverage machine"),
        reps=(6, 10),
        rest_seconds=180,
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
    ),
    "forearm_wrist": _slot(
        "forearm_wrist",
        "LOWER(name) LIKE '%wrist curl%' AND LOWER(target_muscle) = 'forearms'",
        "isolation",
        ("barbell", "dumbbell", "cable", "band"),
        reps=(6, 10),
        rest_seconds=120,
    ),
    "forearm_reverse": _slot(
        "forearm_reverse",
        "(LOWER(name) LIKE '%reverse curl%' OR LOWER(name) LIKE '%reverse wrist curl%') "
        "AND LOWER(target_muscle) IN ('forearms', 'biceps')",
        "isolation",
        ("dumbbell", "barbell", "ez barbell", "cable", "band"),
        reps=(6, 10),
        rest_seconds=120,
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
    ),
    "quad_iso": _slot(
        "quad_iso",
        "LOWER(name) LIKE '%leg extension%' AND LOWER(target_muscle) = 'quads'",
        "isolation",
        ("leverage machine", "resistance band", "cable"),
        reps=(6, 10),
        rest_seconds=180,
    ),
    "ham_curl": _slot(
        "ham_curl",
        "LOWER(name) LIKE '%leg curl%' AND LOWER(target_muscle) = 'hamstrings'",
        "isolation",
        ("leverage machine", "cable", "dumbbell", "body weight"),
        reps=(6, 10),
        rest_seconds=240,
        warmup_sets=1,
        name_rank=("seated", "lying", "leaning"),
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
    ),
    "glute_iso": _slot(
        "glute_iso",
        "(LOWER(name) LIKE '%hip extension%' OR LOWER(name) LIKE '%kickback%' "
        "OR LOWER(name) LIKE '%reverse hyper%') AND LOWER(target_muscle) = 'glutes'",
        "isolation",
        ("cable", "leverage machine", "dumbbell", "band", "body weight", "stability ball"),
        reps=(8, 10),
        rest_seconds=180,
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
    ),
    "calf": _slot(
        "calf",
        "(LOWER(name) LIKE '%calf raise%' OR LOWER(name) LIKE '%calf press%' OR LOWER(name) LIKE '%calf%') "
        "AND LOWER(target_muscle) = 'calves'",
        "isolation",
        ("smith machine", "sled machine", "leverage machine", "barbell", "dumbbell", "body weight", "band"),
        reps=(5, 9),
        rest_seconds=240,
        warmup_sets=1,
        exclude_sql="LOWER(name) NOT LIKE '%stretch%' AND LOWER(name) NOT LIKE '%tibialis%'",
        name_rank=("calf raise", "calf press", "seated calf", "standing calf"),
    ),
    # --- Core --------------------------------------------------------------
    "abs": _slot(
        "abs",
        "(LOWER(name) LIKE '%crunch%' OR LOWER(name) LIKE '%sit-up%' OR LOWER(name) LIKE '%sit up%') "
        "AND LOWER(target_muscle) = 'abs'",
        "isolation",
        ("cable", "leverage machine", "body weight", "dumbbell", "stability ball"),
        reps=(8, 12),
        rest_seconds=150,
        exclude_sql="LOWER(name) NOT LIKE '%stretch%' AND LOWER(name) NOT LIKE '%twist%'",
        name_rank=("cable", "kneeling", "seated", "machine"),
    ),
}


# --- General warm-up block (Belghamdi protocol) ----------------------------

WARMUP_SPECS: dict[str, dict[str, object]] = {
    "scapula_push_plus": {
        "sql": "LOWER(name) LIKE '%scapula push%'",
    },
    "y_raise_rear": {
        "sql": "(LOWER(name) LIKE '%y-raise%' OR LOWER(name) LIKE '%reverse fly%' "
        "OR LOWER(name) LIKE '%rear delt fly%' OR LOWER(name) LIKE '%rear lateral%')",
    },
    "pallof_press": {
        "sql": "LOWER(name) LIKE '%pallof%'",
    },
    "external_rotation": {
        "sql": "LOWER(name) LIKE '%external rotation%'",
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
    "upper": ("scapula_push_plus", "y_raise_rear", "pallof_press"),
    "lower": ("glute_bridge", "dead_bug", "reverse_hyper"),
    "full": ("scapula_push_plus", "glute_bridge", "pallof_press"),
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

#: Safe substitutes when a limitation filter empties a slot's candidate pool.
#: ham_hinge is the only slot whose entire pool is deadlift/good-morning named,
#: i.e. the only one the back rule can empty; leg curls are low-back friendly.
SLOT_FALLBACKS: dict[str, tuple[str, ...]] = {"ham_hinge": ("ham_curl",)}


def resolve_sets_family(day_family: str, explicit: str | None = None) -> str:
    """Resolves the working-set profile for a session (explicit value wins)."""
    return explicit or SETS_FAMILY_BY_DAY_FAMILY.get(day_family, "standard")


def is_escalated_isolation(slot_key: str, sets_family: str) -> bool:
    """True when the slot earns its second set purely through a family escalation."""
    if sets_family == "leg" and slot_key in LEG_STAPLE_SLOTS:
        return True
    return sets_family == "arms" and slot_key in ARM_ISOLATION_SLOTS


def slot_working_sets(
    slot_key: str,
    archetype: str,
    sets_family: str,
    double_slots: tuple[str, ...] = (),
    recovery_cut: bool = False,
) -> int:
    """Working sets for one slot occurrence, matching the reference-program profiles.

    Compounds carry 2 sets; isolations start at 1 and earn a second set only in
    the contexts where the reference programs escalated them: leg staples on
    lower days and arm/delt isolations on dedicated arm days. Full-body days run
    a minimal profile (``double_slots`` = the day's priority lifts at 2 sets)
    plus calves. With ``recovery_cut`` (poor stress/sleep) escalated isolations
    drop back to a single set while compounds, priority lifts and calves keep
    theirs — exercise selection, order and frequency never change.
    """
    if slot_key == "calf":
        return 2
    if sets_family == "full" and double_slots:
        return 2 if slot_key in double_slots else 1
    if archetype in COMPOUND_ARCHETYPES:
        return 2
    if is_escalated_isolation(slot_key, sets_family):
        return 1 if recovery_cut else 2
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
    DayBlueprint(
        "Push 2",
        (
            "flat_press",
            "incline_press",
            "chest_fly",
            "shoulder_press",
            "side_delts",
            "triceps_pushdown",
            "abs",
        ),
        family="upper",
        sets_family="arms",
    ),
    DayBlueprint(
        "Pull 2",
        (
            "vertical_pull",
            "horizontal_row",
            "rear_delts",
            "biceps_alt",
            "biceps_preacher",
            "forearm_reverse",
        ),
        family="upper",
        sets_family="arms",
    ),
    DayBlueprint(
        "Legs 2",
        (
            "glute_thrust",
            "ham_curl",
            "quad_iso",
            "adductors",
            "calf",
            "abs",
        ),
        family="lower",
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

SPLIT_DAY_POOLS: dict[str, tuple[DayBlueprint, ...]] = {
    "full_body": FB_DAYS,
    "female_full_body": FEMALE_FB_DAYS,
    "upper_lower": UL_DAYS,
    "female_upper_lower": FEMALE_UL_DAYS,
    "arnold": ARNOLD_DAYS,
    "arnold_x_ul": ARNOLD_X_UL_DAYS,
    "anterior_posterior": ANTERIOR_POSTERIOR_DAYS,
    "ppl": PPL_DAYS,
}

SPLIT_DISPLAY_NAMES: dict[str, str] = {
    "full_body": "Full Body",
    "female_full_body": "Full Body (Glute Specialized)",
    "upper_lower": "Upper / Lower (Arms & Delts Augmented)",
    "female_upper_lower": "Lower (Glute Bias) / Upper & Core",
    "arnold": "Arnold Split (Chest & Back / Shoulders & Arms / Legs)",
    "arnold_x_ul": "Arnold x Upper/Lower",
    "anterior_posterior": "Anterior / Posterior Split",
    "ppl": "Hybrid PPL / Upper-Lower",
}


def _pool_for(split_type: str, gender: str) -> tuple[DayBlueprint, ...] | None:
    if split_type == "full_body":
        return FEMALE_FB_DAYS if (gender or "").lower() == "female" else FB_DAYS
    if split_type == "upper_lower":
        return FEMALE_UL_DAYS if (gender or "").lower() == "female" else UL_DAYS
    return SPLIT_DAY_POOLS.get(split_type)


def resolve_split_type(split_type: str, frequency: int) -> str:
    """Arnold requests at 4-5 days map onto the Arnold x Upper/Lower hybrid.

    The hybrid mirrors Belghamdi's 5-day reference sample (Chest & Back,
    Shoulders & Arms, Lower A, Upper, Lower B); the classic 3-day Arnold
    rotation stays for frequencies 2-3.
    """
    if split_type == "arnold" and frequency >= 4:
        return "arnold_x_ul"
    return split_type


def build_split_days(split_type: str, frequency: int, gender: str = "male") -> list[DayBlueprint] | None:
    """Returns the day templates for a supported split/frequency, else None.

    Frequency 1 is only meaningful for full-body; other splits fall back to the
    frequency-based default (upper/lower 1 day cannot cover a week).
    """
    split_type = resolve_split_type(split_type, frequency)
    pool = _pool_for(split_type, gender)
    if not pool or frequency < 1:
        return None
    if split_type == "anterior_posterior" and frequency == 1:
        return None
    if split_type in {"upper_lower", "arnold", "ppl", "female_upper_lower"} and frequency == 1:
        return None
    if split_type == "arnold_x_ul" and frequency < 3:
        return None
    if frequency > len(pool):
        # Last-resort repeat for future high-frequency pools: suffix duplicate names.
        days = list(pool)
        used_names = {day.name for day in days}
        index = 0
        while len(days) < frequency:
            repeated = pool[index % len(pool)]
            suffix = 2
            while f"{repeated.name} #{suffix}" in used_names:
                suffix += 1
            renamed = f"{repeated.name} #{suffix}"
            used_names.add(renamed)
            days.append(
                DayBlueprint(name=renamed, slots=repeated.slots, family=repeated.family, cardio=repeated.cardio)
            )
            index += 1
        return days[:frequency]
    return list(pool[:frequency])


DEFAULT_SPLIT_BY_FREQUENCY: dict[str, dict[int, str]] = {
    "male": {
        1: "full_body",
        2: "full_body",
        3: "full_body",
        4: "upper_lower",
        5: "arnold_x_ul",
    },
    "female": {
        1: "female_full_body",
        2: "female_full_body",
        3: "female_full_body",
        4: "female_upper_lower",
        5: "female_upper_lower",
    },
}


# Deterministic keyword routing for free-text split preferences. Word-boundary
# regex keeps body-part phrases ("lower back pain", "upper chest focus",
# "posterior chain") from hijacking the split router.
SPLIT_KEYWORD_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "anterior_posterior",
        (
            re.compile(r"\banterior\b"),
            re.compile(r"\bposterior\s+split\b"),
            re.compile(r"\banterior[\s/]*posterior\b"),
        ),
    ),
    ("arnold", (re.compile(r"\barnold\b"),)),
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
    text = preference.lower()
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
    """True when the trainee's stated goal is fat loss (checks both goal fields)."""
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
