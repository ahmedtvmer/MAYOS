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
prescriptions derived from the samples, Arabic execution cues and the split
day templates.
"""

from dataclasses import dataclass
from typing import Literal

Archetype = Literal["heavy_compound", "medium_compound", "isolation"]


@dataclass(frozen=True)
class SlotSpec:
    """One movement slot and everything the assembler needs to fill it."""

    key: str
    label_ar: str
    sql: str
    archetype: Archetype
    equipment_pref: tuple[str, ...]
    sets: int
    reps: tuple[int, int]
    rest_seconds: int
    cue_ar: str
    warmup_sets: int = 0
    exclude_sql: str = ""
    name_rank: tuple[str, ...] = ()


def _slot(
    key: str,
    label_ar: str,
    sql: str,
    archetype: Archetype,
    equipment_pref: tuple[str, ...],
    sets: int,
    reps: tuple[int, int],
    rest_seconds: int,
    cue_ar: str,
    warmup_sets: int = 0,
    exclude_sql: str = "",
    name_rank: tuple[str, ...] = (),
) -> SlotSpec:
    return SlotSpec(
        key=key,
        label_ar=label_ar,
        sql=sql,
        archetype=archetype,
        equipment_pref=equipment_pref,
        sets=sets,
        reps=reps,
        rest_seconds=rest_seconds,
        cue_ar=cue_ar,
        warmup_sets=warmup_sets,
        exclude_sql=exclude_sql,
        name_rank=name_rank,
    )


SLOT_SPECS: dict[str, SlotSpec] = {
    # --- Chest -------------------------------------------------------------
    "incline_press": _slot(
        "incline_press",
        "بنش مائل",
        "LOWER(name) LIKE '%incline%' AND (LOWER(name) LIKE '%press%' OR LOWER(name) LIKE '%bench%') "
        "AND LOWER(target_muscle) = 'pectorals'",
        "medium_compound",
        ("leverage machine", "smith machine", "dumbbell", "cable", "barbell"),
        sets=2,
        reps=(5, 7),
        rest_seconds=240,
        cue_ar="ضم ايدك لجوه شويه عشان تحاكي اتجاه الياف الصدر العالي، وبلاش تفتح كوعك 90 درجه.",
        warmup_sets=1,
        exclude_sql="LOWER(name) NOT LIKE '%fly%' AND LOWER(name) NOT LIKE '%push-up%' AND LOWER(name) NOT LIKE '%pushup%'",
    ),
    "flat_press": _slot(
        "flat_press",
        "بنش مستوي",
        "(LOWER(name) LIKE '%chest press%' OR LOWER(name) LIKE '%bench press%' OR LOWER(name) LIKE '%flat press%') "
        "AND LOWER(target_muscle) = 'pectorals'",
        "medium_compound",
        ("leverage machine", "cable", "barbell", "dumbbell", "smith machine"),
        sets=2,
        reps=(6, 8),
        rest_seconds=240,
        cue_ar="لو الجيم يسمح تلعب ع الكيبل العب، ولو الجهاز مش كويس العب دمبل. نزل بالوزن لحد تمدد كامل.",
        warmup_sets=1,
        exclude_sql="LOWER(name) NOT LIKE '%incline%' AND LOWER(name) NOT LIKE '%decline%' "
        "AND LOWER(name) NOT LIKE '%one arm%' AND LOWER(name) NOT LIKE '%push-up%'",
    ),
    "chest_fly": _slot(
        "chest_fly",
        "تفريغ صدر",
        "(LOWER(name) LIKE '%fly%' OR LOWER(name) LIKE '%pec deck%') AND LOWER(target_muscle) = 'pectorals'",
        "isolation",
        ("cable", "leverage machine", "dumbbell", "band"),
        sets=2,
        reps=(8, 10),
        rest_seconds=180,
        cue_ar="فك لوحين كتفك من قبل ما تبدأ الحركه وركز علي الصدر، متحركش كتفك مع الحركه.",
        name_rank=("incline", "middle", "flat", "fly", "pec deck"),
    ),
    # --- Back --------------------------------------------------------------
    "horizontal_row": _slot(
        "horizontal_row",
        "سحب أفقي",
        "LOWER(name) LIKE '%row%' AND LOWER(target_muscle) IN ('upper back', 'lats', 'traps')",
        "heavy_compound",
        ("leverage machine", "smith machine", "dumbbell", "cable", "barbell"),
        sets=2,
        reps=(5, 7),
        rest_seconds=240,
        cue_ar="افتح كيعانك لبره علي قد متقدر وحاول تقرب من زاويه الـ90 حسب راحه كتفك ومرونتك.",
        warmup_sets=2,
        exclude_sql="LOWER(name) NOT LIKE '%upright row%' AND LOWER(name) NOT LIKE '%rear delt%' "
        "AND LOWER(name) NOT LIKE '%unilateral%' AND LOWER(name) NOT LIKE '%one arm%' "
        "AND LOWER(name) NOT LIKE '%single arm%' AND LOWER(name) NOT LIKE '%t bar%' "
        "AND LOWER(name) NOT LIKE '%t-bar%' AND LOWER(name) NOT LIKE '%high row%'"
        " AND LOWER(name) NOT LIKE '%bent over row%' AND LOWER(name) NOT LIKE '%barbell row%'",
    ),
    "upper_back_pull": _slot(
        "upper_back_pull",
        "سحب أحادي للظهر العلوي",
        "(LOWER(name) LIKE '%unilateral row%' OR LOWER(name) LIKE '%one arm row%' "
        "OR LOWER(name) LIKE '%single arm row%' OR LOWER(name) LIKE '%t bar row%' "
        "OR LOWER(name) LIKE '%t-bar%' OR LOWER(name) LIKE '%high row%' "
        "OR LOWER(name) LIKE '%bent over row%' OR LOWER(name) LIKE '%barbell row%') "
        "AND LOWER(target_muscle) IN ('upper back', 'lats')",
        "medium_compound",
        ("leverage machine", "cable", "dumbbell", "smith machine", "barbell"),
        sets=2,
        reps=(6, 10),
        rest_seconds=240,
        cue_ar="بلاش تقعد تلف حوالين نفسك، والتزم بثبات جسمك علي مدار الحركه وركز في مسار كوعك.",
        warmup_sets=1,
    ),
    "vertical_pull": _slot(
        "vertical_pull",
        "سحب رأسي (لات)",
        "(LOWER(name) LIKE '%pulldown%' OR LOWER(name) LIKE '%pull-up%' OR LOWER(name) LIKE '%pull up%' "
        "OR LOWER(name) LIKE '%chin-up%' OR LOWER(name) LIKE '%chin up%' OR LOWER(name) LIKE '%chinup%') "
        "AND LOWER(target_muscle) IN ('lats', 'upper back')",
        "medium_compound",
        ("leverage machine", "cable", "body weight"),
        sets=2,
        reps=(5, 7),
        rest_seconds=240,
        cue_ar="ركز في مسار كوعك وانك بتضم كتافك علي بعض، مش بتسحب علي ضهرك العلوي.",
        warmup_sets=1,
        exclude_sql="LOWER(name) NOT LIKE '%rear pulldown%' AND LOWER(name) NOT LIKE '%rear pull-up%' "
        "AND LOWER(name) NOT LIKE '%behind neck%' AND LOWER(name) NOT LIKE '%straight arm%'",
        name_rank=("front pulldown", "wide grip", "pulldown", "pull-up", "pull up"),
    ),
    "pullover": _slot(
        "pullover",
        "بول أوفر",
        "(LOWER(name) LIKE '%pullover%' OR LOWER(name) LIKE '%straight arm pulldown%')",
        "isolation",
        ("cable", "dumbbell", "barbell"),
        sets=2,
        reps=(8, 10),
        rest_seconds=180,
        cue_ar="مدي حركي كامل من غير ما تحرك كوعك، وحس بالتمدد في عضله اللاتس.",
        exclude_sql="LOWER(name) NOT LIKE '%stretch%'",
    ),
    "shrug": _slot(
        "shrug",
        "ترابيس (شراج)",
        "LOWER(name) LIKE '%shrug%'",
        "isolation",
        ("leverage machine", "smith machine", "cable", "dumbbell", "barbell", "band"),
        sets=2,
        reps=(6, 10),
        rest_seconds=180,
        cue_ar="ارفع كتافك لفوق ناحيه ودنك من غير ما تلف الكتف، ووقف عند القمه ثانيه كامله.",
    ),
    # --- Shoulders ---------------------------------------------------------
    "shoulder_press": _slot(
        "shoulder_press",
        "كتف برس",
        "(LOWER(name) LIKE '%shoulder press%' OR LOWER(name) LIKE '%overhead press%' "
        "OR LOWER(name) LIKE '%arnold press%') AND LOWER(target_muscle) = 'delts'",
        "heavy_compound",
        ("smith machine", "leverage machine", "dumbbell", "barbell", "cable", "kettlebell"),
        sets=2,
        reps=(5, 8),
        rest_seconds=240,
        cue_ar="خلي حوضك لقدام ولكن ضهرك مفرود مش متني، ومتشبكش الوسط بزياده.",
        warmup_sets=1,
    ),
    "side_delts": _slot(
        "side_delts",
        "كتف جانبي",
        "(LOWER(name) LIKE '%lateral raise%' OR LOWER(name) LIKE '%side raise%') "
        "AND LOWER(target_muscle) = 'delts'",
        "isolation",
        ("cable", "leverage machine", "dumbbell", "band"),
        sets=2,
        reps=(6, 8),
        rest_seconds=180,
        cue_ar="حاول علي قد متقدر الحركه تبقي طالعه من كتفك لوحده مش جسمك كله، ومتمرجحش.",
        exclude_sql="LOWER(name) NOT LIKE '%rear%' AND LOWER(name) NOT LIKE '%front%'",
    ),
    "rear_delts": _slot(
        "rear_delts",
        "كتف خلفي",
        "(LOWER(name) LIKE '%rear delt%' OR LOWER(name) LIKE '%reverse fly%' "
        "OR LOWER(name) LIKE '%face pull%' OR LOWER(name) LIKE '%y-raise%' "
        "OR LOWER(name) LIKE '%rear lateral%')",
        "isolation",
        ("cable", "leverage machine", "dumbbell", "band", "barbell", "smith machine"),
        sets=2,
        reps=(6, 10),
        rest_seconds=180,
        cue_ar="فك لوحين كتفك من قبل ما تبدأ الحركه وحاول تركز علي كتفك الخلفي لوحده.",
        exclude_sql="LOWER(name) NOT LIKE '%stretch%'",
        name_rank=("reverse fly", "rear lateral", "rear delt", "y-raise", "face pull"),
    ),
    # --- Arms --------------------------------------------------------------
    "biceps_preacher": _slot(
        "biceps_preacher",
        "باي بريتشر",
        "LOWER(name) LIKE '%preacher%' AND LOWER(target_muscle) IN ('biceps', 'brachialis')",
        "isolation",
        ("dumbbell", "cable", "leverage machine", "ez barbell", "barbell", "smith machine"),
        sets=2,
        reps=(6, 10),
        rest_seconds=180,
        cue_ar="بلاش مدي حركي زياده من الكتف ومتمرجحش جسمك، خلي الحركه كلها جايه من كوعك.",
    ),
    "biceps_alt": _slot(
        "biceps_alt",
        "باي (قبضه مختلفه)",
        "LOWER(name) LIKE '%curl%' AND LOWER(target_muscle) IN ('biceps', 'brachialis')",
        "isolation",
        ("cable", "dumbbell", "ez barbell", "barbell", "smith machine", "leverage machine"),
        sets=2,
        reps=(6, 10),
        rest_seconds=180,
        cue_ar="ثبت كوعك جنب جسمك واعصر الباي في القمه، ومتستخدمش زخم من الضهر.",
        exclude_sql="LOWER(name) NOT LIKE '%wrist%' AND LOWER(name) NOT LIKE '%leg%' "
        "AND LOWER(name) NOT LIKE '%preacher%' AND LOWER(name) NOT LIKE '%reverse%' "
        "AND LOWER(name) NOT LIKE '%spider%'",
    ),
    "triceps_pushdown": _slot(
        "triceps_pushdown",
        "تراي بوش داون",
        "LOWER(name) LIKE '%pushdown%' AND LOWER(target_muscle) = 'triceps'",
        "isolation",
        ("cable", "leverage machine"),
        sets=2,
        reps=(6, 10),
        rest_seconds=180,
        cue_ar="متدخلش الكور بزياده وتتمرجح، هي فرد للكوع فقط من غير ما تتحرك كتفك.",
    ),
    "triceps_overhead": _slot(
        "triceps_overhead",
        "تراي أوفر هيد",
        "(LOWER(name) LIKE '%overhead%' OR LOWER(name) LIKE '%skull%' "
        "OR LOWER(name) LIKE '%lying triceps%' OR LOWER(name) LIKE '%crossbody%') "
        "AND LOWER(target_muscle) = 'triceps'",
        "isolation",
        ("cable", "barbell", "ez barbell", "dumbbell", "leverage machine"),
        sets=2,
        reps=(6, 10),
        rest_seconds=180,
        cue_ar="لو كوعك وجعك العب بوش داون عادي جدا، وحافظ علي كوعك ثابت في مساره.",
        exclude_sql="LOWER(name) NOT LIKE '%stretch%'",
    ),
    "forearm_wrist": _slot(
        "forearm_wrist",
        "ساعد (رسغ)",
        "LOWER(name) LIKE '%wrist curl%' AND LOWER(target_muscle) = 'forearms'",
        "isolation",
        ("barbell", "dumbbell", "cable", "band"),
        sets=2,
        reps=(6, 10),
        rest_seconds=120,
        cue_ar="فك صوابعك تحت في الاستطاله واختار وزن يخليك تعمل انقباض كامل.",
    ),
    "forearm_reverse": _slot(
        "forearm_reverse",
        "ساعد (عكسي)",
        "(LOWER(name) LIKE '%reverse curl%' OR LOWER(name) LIKE '%reverse wrist curl%') "
        "AND LOWER(target_muscle) IN ('forearms', 'biceps')",
        "isolation",
        ("dumbbell", "barbell", "ez barbell", "cable", "band"),
        sets=2,
        reps=(6, 10),
        rest_seconds=120,
        cue_ar="تقدر تغير القبضه براحتك علي حسب الي يريحك، المهم كله نفس الاداء والتحكم.",
    ),
    # --- Legs --------------------------------------------------------------
    "quad_compound": _slot(
        "quad_compound",
        "أرجل أساسي (كوادز)",
        "(LOWER(name) LIKE '%squat%' OR LOWER(name) LIKE '%leg press%' "
        "OR LOWER(name) LIKE '%hack%' OR LOWER(name) LIKE '%lunge%') "
        "AND LOWER(target_muscle) IN ('quads', 'glutes')",
        "heavy_compound",
        ("leverage machine", "sled machine", "smith machine", "barbell", "dumbbell", "kettlebell"),
        sets=2,
        reps=(5, 8),
        rest_seconds=240,
        cue_ar="120 درجه من ثني الركبه يكفي لاستهداف الكوادز، بس حاول تنزل للاخر وتحكم في النزول.",
        warmup_sets=2,
        exclude_sql="LOWER(name) NOT LIKE '%calf%' AND LOWER(name) NOT LIKE '%stretch%' "
        "AND LOWER(name) NOT LIKE '%jump%' AND LOWER(name) NOT LIKE '%pistol%' "
        "AND LOWER(name) NOT LIKE '%sumo%' AND LOWER(name) NOT LIKE '%front squat%'",
        name_rank=("hack", "leg press", "smith hack", "smith squat", "squat"),
    ),
    "quad_lunge": _slot(
        "quad_lunge",
        "طعنات / سكوات فردي",
        "(LOWER(name) LIKE '%split squat%' OR LOWER(name) LIKE '%lunge%') "
        "AND LOWER(target_muscle) IN ('quads', 'glutes')",
        "medium_compound",
        ("dumbbell", "barbell", "smith machine", "cable", "kettlebell", "body weight"),
        sets=2,
        reps=(6, 8),
        rest_seconds=180,
        cue_ar="خلي وزنك علي الرجل الأماميه واظهر الركبه لفوق، ونزل بتحكم من غير ما تلمس الأرض.",
        warmup_sets=1,
        exclude_sql="LOWER(name) NOT LIKE '%jump%' AND LOWER(name) NOT LIKE '%stretch%'",
    ),
    "quad_iso": _slot(
        "quad_iso",
        "فرد أمامي للرجل",
        "LOWER(name) LIKE '%leg extension%' AND LOWER(target_muscle) = 'quads'",
        "isolation",
        ("leverage machine", "resistance band", "cable"),
        sets=3,
        reps=(6, 10),
        rest_seconds=180,
        cue_ar="لو الجهاز مش موجود العب باند ليج اكستنشن. ثبت الفخد واعصر الكوادز في القمه.",
    ),
    "ham_curl": _slot(
        "ham_curl",
        "فرد خلفي للرجل",
        "LOWER(name) LIKE '%leg curl%' AND LOWER(target_muscle) = 'hamstrings'",
        "isolation",
        ("leverage machine", "cable", "dumbbell", "body weight"),
        sets=2,
        reps=(6, 10),
        rest_seconds=240,
        cue_ar="ركز في تثبيت نفسك علي الكرسي ومتمرجحش ضهرك، وحس بالشد في الهامسترينج.",
        warmup_sets=1,
        name_rank=("seated", "lying", "leaning"),
    ),
    "ham_hinge": _slot(
        "ham_hinge",
        "رفعه ميتة رومانية / SLDL",
        "(LOWER(name) LIKE '%romanian%' OR LOWER(name) LIKE '%stiff leg%' "
        "OR LOWER(name) LIKE '%stiff-leg%' OR LOWER(name) LIKE '%good morning%') "
        "AND LOWER(target_muscle) IN ('hamstrings', 'glutes', 'spine')",
        "heavy_compound",
        ("barbell", "dumbbell", "smith machine", "leverage machine", "kettlebell", "band"),
        sets=2,
        reps=(5, 7),
        rest_seconds=240,
        cue_ar="لو مرونتك متسمحش، تقدر تتني ركبتك شويه، وخلي ضهرك مفرود علي طول الحركه.",
        warmup_sets=2,
        exclude_sql="LOWER(name) NOT LIKE '%stretch%' AND LOWER(name) NOT LIKE '%cable assisted%'",
        name_rank=("romanian", "stiff leg", "stiff-leg", "deadlift", "good morning"),
    ),
    "glute_thrust": _slot(
        "glute_thrust",
        "هيب ثراست",
        "(LOWER(name) LIKE '%hip thrust%' OR LOWER(name) LIKE '%glute bridge%') "
        "AND LOWER(target_muscle) = 'glutes'",
        "medium_compound",
        ("barbell", "leverage machine", "smith machine", "dumbbell", "resistance band", "body weight"),
        sets=2,
        reps=(5, 7),
        rest_seconds=240,
        cue_ar="اعصر الجلوت في القمه ثانيه واظهر الحوض لفوق من غير ما تلوي ضهرك.",
        warmup_sets=2,
        name_rank=("hip thrust", "barbell glute bridge", "glute bridge"),
    ),
    "glute_iso": _slot(
        "glute_iso",
        "جلوت عزل / فرد حوض",
        "(LOWER(name) LIKE '%hip extension%' OR LOWER(name) LIKE '%kickback%' "
        "OR LOWER(name) LIKE '%reverse hyper%') AND LOWER(target_muscle) = 'glutes'",
        "isolation",
        ("cable", "leverage machine", "dumbbell", "band", "body weight", "stability ball"),
        sets=2,
        reps=(8, 10),
        rest_seconds=180,
        cue_ar="الحركه جايه من مفصل الحوض مش من اسفل الضهر، واعصر الجلوت في القمه.",
    ),
    "adductors": _slot(
        "adductors",
        "مقربات الفخذ",
        "(LOWER(name) LIKE '%adduction%' OR LOWER(name) LIKE '%adductor%') "
        "AND LOWER(target_muscle) = 'adductors'",
        "isolation",
        ("leverage machine", "cable", "body weight"),
        sets=2,
        reps=(8, 10),
        rest_seconds=150,
        cue_ar="اختار وزن مناسب وثبت نفسك كويس في الجهاز، ومتستخدمش زخم في الفتح والضم.",
        exclude_sql="LOWER(name) NOT LIKE '%stretch%'",
    ),
    "calf": _slot(
        "calf",
        "سمانة",
        "(LOWER(name) LIKE '%calf raise%' OR LOWER(name) LIKE '%calf press%' OR LOWER(name) LIKE '%calf%') "
        "AND LOWER(target_muscle) = 'calves'",
        "isolation",
        ("smith machine", "sled machine", "leverage machine", "barbell", "dumbbell", "body weight", "band"),
        sets=3,
        reps=(5, 9),
        rest_seconds=240,
        cue_ar="اي تمرينه ركبتك مفروده حتي لو مسكت دامبل، واعمل انقباض كامل في القمه وتمد كامل تحت.",
        warmup_sets=1,
        exclude_sql="LOWER(name) NOT LIKE '%stretch%' AND LOWER(name) NOT LIKE '%tibialis%'",
        name_rank=("calf raise", "calf press", "seated calf", "standing calf"),
    ),
    # --- Core --------------------------------------------------------------
    "abs": _slot(
        "abs",
        "بطن",
        "(LOWER(name) LIKE '%crunch%' OR LOWER(name) LIKE '%sit-up%' OR LOWER(name) LIKE '%sit up%') "
        "AND LOWER(target_muscle) = 'abs'",
        "isolation",
        ("cable", "leverage machine", "body weight", "dumbbell", "stability ball"),
        sets=2,
        reps=(8, 12),
        rest_seconds=150,
        cue_ar="ركز ان الحركه تبقي طالعه من تني وفرد عمودك الفقري، مش ضهرك كله بيتحرك.",
        exclude_sql="LOWER(name) NOT LIKE '%stretch%' AND LOWER(name) NOT LIKE '%twist%'",
        name_rank=("cable", "kneeling", "seated", "machine"),
    ),
}


# --- General warm-up block (Belghamdi protocol) ----------------------------

WARMUP_SPECS: dict[str, dict[str, object]] = {
    "scapula_push_plus": {
        "label_ar": "سكابولا بوش بلس",
        "sql": "LOWER(name) LIKE '%scapula push%'",
        "cue_ar": "حركه تسخين للكفاف فقط، مش للفشل. اعمل 10 عدات بحركه كامله.",
    },
    "y_raise_rear": {
        "label_ar": "Y رايز / رير دلت فلاي",
        "sql": "(LOWER(name) LIKE '%y-raise%' OR LOWER(name) LIKE '%reverse fly%' "
        "OR LOWER(name) LIKE '%rear delt fly%' OR LOWER(name) LIKE '%rear lateral%')",
        "cue_ar": "تسخين خفيف للكتف الخلفي، ركز علي الاحساس بالعضله مش الوزن.",
    },
    "pallof_press": {
        "label_ar": "بالوف بريس / روتيشن",
        "sql": "LOWER(name) LIKE '%pallof%'",
        "cue_ar": "ثبت الوسط ومتلفش جسمك، الحركه من غير ارهاق للكور.",
    },
    "external_rotation": {
        "label_ar": "تجميع الكتف الخارجي",
        "sql": "LOWER(name) LIKE '%external rotation%'",
        "cue_ar": "حركه خفيفه لتسخين الكفه الدواره، من غير وزن تقيل.",
    },
    "dead_bug": {
        "label_ar": "ديد باج",
        "sql": "LOWER(name) = 'dead bug'",
        "cue_ar": "اثبت ضهرك في الأرض ومد ايد ورجل بالتبادل من غير ما تحرك الوسط.",
    },
    "glute_bridge": {
        "label_ar": "جلوت بريدج",
        "sql": "(LOWER(name) LIKE '%glute bridge%' OR LOWER(name) LIKE '%hip bridge%')",
        "cue_ar": "تسخين للجلوت والحوض، اعصر في القمه من غير ما تلوي ضهرك.",
    },
    "reverse_hyper": {
        "label_ar": "باك إكستنشن / ريفرس هايبر",
        "sql": "(LOWER(name) LIKE '%reverse hyper%' OR LOWER(name) LIKE '%back extension%')",
        "cue_ar": "تسخين للضهر السفلي والجلوت بحركه ناعمه من غير ارهاق.",
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


PROGRAM_INSTRUCTIONS_AR = (
    "• خد بالك من التسخين وافهمه كويس عشان تبقي جاهز انك تأدي تمرينك بأعلي كفاءه.\n"
    "• الفشل العضلي هو انك متكنش قادر تأدي العده بمدي حركي كامل بأداء قريب جدا من أداء أول عده. "
    "لو عارف ان العده الجايه مش هتبقي كامله متحاولش فيها، ومتزودش عدات جزئيه من نفسك.\n"
    "• كل تمرين مربوط بملحوظات الأداء؛ ركز فيها بين المجاميع عشان تكون فاهم انت داخل تعمل ايه.\n"
    "• متزودش اي حاجه من نفسك ومتعدلش اي تمرين او ترتيب قبل 12 اسبوع من تجربه البرنامج كما هو.\n"
    "• مفيش حاجه تعملها غير زياده تدريجيه بالاحمال سواء عدات او وزن.\n"
    "• الريست 3-5 دقايق في التمارين الأساسيه و2-3 دقايق في العزل، ومتستعجلش."
)

WARMUP_PROTOCOL_AR = (
    "WARM UP PROTOCOL - التسخين\n"
    "• تجهيزات قبل التمرين (أقل من 10 دقايق): بالوف بريس، بالوف روتيشن، "
    "تجميع الكتف الخارجي، سكابولا بوش بلس - 10 عدات لكل حركه من غير ارهاق.\n"
    "• التسخين التخصصي لكل تمرين:\n"
    "  - تمرين خفيف: مجموعه تسخين واحده بحوالي 60% من الوزن الفعلي (3-6 عدات).\n"
    "  - تمرين متوسط: مجموعتين تسخين (50% من الوزن الفعلي، وبعدها 75-80% لـ3 عدات).\n"
    "  - تمرين تقيل: 2-4 مجاميع تسخين (50%، بعدها 75-80% لـ3 عدات، بعدها 85-90% لـ1-3 عدات)."
)


@dataclass(frozen=True)
class DayBlueprint:
    """One session template: an ordered tuple of slot keys plus metadata."""

    name: str
    slots: tuple[str, ...]
    family: str = "full"
    cardio: str | None = None


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
        cardio="كارديو خفيف 10-20 دقيقه (مشي/دراجه) بعد التمرين",
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
        cardio="كارديو خفيف 10 دقايق دراجه بعد التمرين",
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
        cardio="كارديو خفيف 20 دقيقه (مشي مائل) بعد التمرين",
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
        cardio="كارديو خفيف 10 دقايق دراجه بعد التمرين",
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


def build_split_days(split_type: str, frequency: int, gender: str = "male") -> list[DayBlueprint] | None:
    """Returns the day templates for a supported split/frequency, else None.

    Frequency 1 is only meaningful for full-body; other splits fall back to the
    frequency-based default (upper/lower 1 day cannot cover a week).
    """
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
        # Repeat the pool for very high frequencies (clamped at 5 by callers).
        days = list(pool)
        index = 0
        while len(days) < frequency:
            days.append(pool[index % len(pool)])
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


# Deterministic keyword routing for free-text split preferences.
SPLIT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("anterior_posterior", ("anterior", "posterior", "push pull legs upper lower")),
    ("arnold", ("arnold",)),
    ("upper_lower", ("upper", "lower", "u/l", "ul ")),
    ("ppl", ("ppl", "push pull legs", "push/pull/legs", "push, pull, legs")),
    ("full_body", ("full body", "fullbody", "full-body", "total body")),
)


def match_split_keyword(preference: str | None) -> str | None:
    if not preference:
        return None
    text = preference.lower()
    for split_type, keywords in SPLIT_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return split_type
    return None


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
