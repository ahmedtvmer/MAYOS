import re
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

from agent.program_blueprints import (
    DEFAULT_SPLIT_BY_FREQUENCY,
    SLOT_SPECS,
    SPLIT_DISPLAY_NAMES,
    WARMUP_FAMILIES,
    WARMUP_SPECS,
    body_parts_to_slots,
    build_split_days,
    match_split_keyword,
    resolve_split_type,
)
from agent.ProgramState import CustomDayPlan, DynamicSplitPlan
from database.database_manager import DatabaseManager
from utils.model_downloader import llm

load_dotenv()
db = DatabaseManager()

SLANG_TO_SQL_MAP = {
    "quads": "LOWER(target_muscle) = 'quads'",
    "hamstrings": "LOWER(target_muscle) = 'hamstrings'",
    "glutes": "LOWER(target_muscle) = 'glutes'",
    "calves": "LOWER(target_muscle) = 'calves' OR LOWER(body_part) = 'lower legs'",
    "lats": "LOWER(target_muscle) = 'lats'",
    "upper back": "LOWER(target_muscle) IN ('upper back', 'traps', 'spine')",
    "traps": "LOWER(target_muscle) IN ('traps', 'upper back')",
    "biceps": "LOWER(target_muscle) IN ('biceps', 'brachialis')",
    "chest": "LOWER(target_muscle) = 'pectorals' OR LOWER(body_part) = 'chest'",
    "side delts": "LOWER(name) LIKE '%lateral raise%' OR (LOWER(target_muscle) = 'delts' AND LOWER(name) LIKE '%side%')",
    "rear delts": "LOWER(name) LIKE '%rear delt%' OR LOWER(name) LIKE '%face pull%'",
    "front delts": "LOWER(target_muscle) = 'delts' AND LOWER(name) LIKE '%press%'",
    "triceps": "LOWER(target_muscle) = 'triceps'",
    "forearms": "LOWER(target_muscle) = 'forearms' OR LOWER(body_part) = 'lower arms'",
    "adductors": "LOWER(target_muscle) = 'adductors'",
    "abs": "LOWER(target_muscle) = 'abs' OR LOWER(body_part) = 'waist'",
}

COMPOUND_KEYWORDS = [
    "press",
    "row",
    "squat",
    "deadlift",
    "pull-up",
    "chin-up",
    "dip",
    "lunge",
    "leg press",
    "hack squat",
    "pulldown",
]

EXCLUDED_TERMS = [
    "stretch",
    "yoga",
    "warm-up",
    "jump",
    "quick feet",
    "bike",
    "hop",
    "run",
    "reach",
    "twist",
    "tilt",
    "roll",
    "walk",
]

EXCLUDED_PATTERNS = [re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE) for term in EXCLUDED_TERMS]


def _is_excluded(name: str) -> bool:
    """Word-boundary exclusion so 'run' never kills 'crunch' or 'reach' never kills 'preacher'."""
    return any(pattern.search(name) for pattern in EXCLUDED_PATTERNS)

REP_WINDOWS = {
    "low": {"compound": (5, 8), "isolation": (8, 12)},
    "balanced": {"compound": (6, 10), "isolation": (10, 15)},
    "high": {"compound": (8, 12), "isolation": (12, 20)},
}

REP_PREFERENCE_OFFSETS = {
    "low": (-1, -1),
    "balanced": (0, 0),
    "high": (2, 2),
}


def get_target_rep_window(mechanic: str, rep_preference: str = "balanced") -> tuple[int, int]:
    pref = rep_preference.lower() if rep_preference in REP_WINDOWS else "balanced"
    return REP_WINDOWS[pref].get(mechanic, (8, 12))


def apply_rep_preference(reps: tuple[int, int], rep_preference: str | None) -> tuple[int, int]:
    """Shifts the blueprint rep window by the trainee's rep preference (clamped at 4)."""
    offset = REP_PREFERENCE_OFFSETS.get((rep_preference or "balanced").lower(), (0, 0))
    return (max(4, reps[0] + offset[0]), max(4, reps[1] + offset[1]))


SYSTEM_SPLIT_PROMPT = """You are an expert hypertrophy coach.
Convert the user's split preference into a structured training week using movement slots.

Rules:
1. Day Count: The number of days MUST equal exactly {frequency} (hard limit: max 5 days).
2. Permitted Slots: use ONLY these exact slot keys:
   chest: 'incline_press', 'flat_press', 'chest_fly'
   back: 'vertical_pull', 'horizontal_row', 'upper_back_pull', 'pullover', 'shrug'
   shoulders: 'shoulder_press', 'side_delts', 'rear_delts'
   arms: 'biceps_preacher', 'biceps_alt', 'triceps_pushdown', 'triceps_overhead', 'forearm_wrist', 'forearm_reverse'
   legs: 'quad_compound', 'quad_lunge', 'quad_iso', 'ham_curl', 'ham_hinge', 'glute_thrust', 'glute_iso', 'adductors', 'calf'
   core: 'abs'
3. Session Size: Full Body days 8-12 slots; Upper days 7-12; Lower days 6-10; Push/Pull/Arms days 5-8.
4. Weekly Coverage (mandatory): incline_press AND flat_press; vertical_pull AND horizontal_row; side_delts AND rear_delts; biceps_preacher or biceps_alt; triceps_pushdown AND triceps_overhead; forearm_wrist or forearm_reverse; at least one lower day with adductors AND calf; at least one shrug and one abs slot.
5. Ordering: heaviest compounds first, then machine/medium compounds, then isolations, then arms/forearms/abs.
6. Fatigue Management: avoid heavy spinal loads (ham_hinge, quad_compound) on consecutive days.
7. Lower days MAY include low-fatigue upper isolations ('side_delts', 'biceps_preacher', 'biceps_alt', 'triceps_pushdown', 'triceps_overhead', 'abs').
"""


def _plan_from_blueprint_days(split_name: str, days: list) -> DynamicSplitPlan:
    return DynamicSplitPlan(
        split_name=split_name,
        days=[
            CustomDayPlan(
                day_order=index,
                day_name=day.name,
                target_slots=list(day.slots),
                warmup_family=day.family,
                sets_family=day.sets_family,
                double_slots=list(day.double_slots),
                cardio=day.cardio,
            )
            for index, day in enumerate(days, start=1)
        ],
    )


SPLIT_FREQUENCY_NAMES: dict[tuple[str, int], str] = {
    ("full_body", 1): "Consolidated Full Body",
    ("full_body", 2): "Full Body A/B",
    ("full_body", 3): "Full Body Tri-Phase",
    ("full_body", 4): "Full Body 4-Day",
    ("full_body", 5): "Full Body 5-Day",
    ("female_full_body", 1): "Full Body (Glute Specialized)",
    ("female_full_body", 2): "Glute Bias A/B",
    ("female_full_body", 3): "Glute Hypertrophy Tri-Phase",
    ("female_full_body", 4): "Glute Specialization 4-Day",
    ("female_full_body", 5): "Glute Specialization 5-Day",
    ("upper_lower", 1): "Upper / Lower (Arms & Delts Augmented)",
    ("upper_lower", 2): "Upper / Lower (Arms & Delts Augmented)",
    ("upper_lower", 3): "Upper / Lower / Upper (Arms & Delts Augmented)",
    ("upper_lower", 4): "Upper / Lower (Arms & Delts Augmented)",
    ("upper_lower", 5): "Upper / Lower x2 + Upper",
    ("female_upper_lower", 4): "Lower (Glute Bias) / Upper & Core",
    ("female_upper_lower", 5): "Glute & Upper Hypertrophy 5-Day",
    ("arnold", 2): "Arnold Split (Condensed)",
    ("arnold", 3): "Arnold Split (Chest & Back / Shoulders & Arms / Legs)",
    ("arnold_x_ul", 4): "Arnold x Upper/Lower (4-Day)",
    ("arnold_x_ul", 5): "Arnold x Upper/Lower",
    ("anterior_posterior", 2): "Anterior / Posterior Split",
    ("anterior_posterior", 3): "Anterior / Posterior Split",
    ("anterior_posterior", 4): "Anterior / Posterior Split",
    ("anterior_posterior", 5): "Anterior / Posterior Split",
    ("ppl", 2): "Push / Pull",
    ("ppl", 3): "Push / Pull / Legs",
    ("ppl", 4): "Push / Pull / Legs / Push",
    ("ppl", 5): "Hybrid PPL / Upper-Lower",
}


def get_split_plan(split_type: str, frequency: int, gender: str = "male") -> DynamicSplitPlan | None:
    """Builds a blueprint-backed split plan, or None when unsupported for the frequency."""
    split_type = resolve_split_type(split_type, frequency)
    days = build_split_days(split_type, frequency, gender)
    if not days:
        return None
    split_name = SPLIT_FREQUENCY_NAMES.get((split_type, frequency))
    if not split_name:
        split_name = SPLIT_DISPLAY_NAMES.get(split_type, split_type.replace("_", " ").title())
    return _plan_from_blueprint_days(split_name, days)


def get_default_split(frequency: int, gender: str = "male") -> DynamicSplitPlan:
    clamped_freq = min(max(int(frequency), 1), 5)
    gender_key = "female" if (gender or "").lower() == "female" else "male"
    split_type = DEFAULT_SPLIT_BY_FREQUENCY.get(gender_key, {}).get(clamped_freq, "full_body")
    plan = get_split_plan(split_type, clamped_freq, gender) or get_split_plan("full_body", clamped_freq, gender)
    if plan is None:
        raise ValueError(f"No blueprint available for frequency {clamped_freq}")
    return plan


def _sanitize_llm_plan(plan: DynamicSplitPlan, frequency: int, gender: str) -> DynamicSplitPlan:
    """Filters hallucinated slot keys and falls back to the deterministic default plan."""
    valid_slots = set(SLOT_SPECS)
    sanitized_days: list[CustomDayPlan] = []
    for day in plan.days:
        slots = [slot for slot in day.target_slots if slot in valid_slots]
        if not slots and day.target_body_parts:
            slots = body_parts_to_slots(day.target_body_parts)
        slots = list(dict.fromkeys(slots))
        family = day.warmup_family if day.warmup_family in WARMUP_FAMILIES else "full"
        sanitized_days.append(day.model_copy(update={"target_slots": slots, "warmup_family": family}))
    if len(sanitized_days) != frequency or any(len(day.target_slots) < 3 for day in sanitized_days):
        return get_default_split(frequency, gender)
    return plan.model_copy(update={"days": sanitized_days})


def resolve_split(frequency: int, preference: str | None = None, gender: str = "male") -> DynamicSplitPlan:
    clamped_freq = min(max(int(frequency), 1), 5)
    if not preference or preference.strip().lower() in ["standard", "default", "none", "balanced"]:
        return get_default_split(clamped_freq, gender=gender)

    split_type = match_split_keyword(preference)
    if split_type:
        plan = get_split_plan(split_type, clamped_freq, gender)
        if plan is not None:
            return plan
        # Recognized request at an unsupported frequency (e.g. "arnold" at 1 day):
        # stay deterministic and fall back to the frequency default rather than the LLM.
        return get_default_split(clamped_freq, gender=gender)

    structured_llm = llm.with_structured_output(DynamicSplitPlan)
    gender_context = (
        "female trainee (prioritize glutes and lower body; still include direct arm and forearm work)"
        if gender.lower() == "female"
        else "male trainee"
    )
    prompt = [
        SystemMessage(content=SYSTEM_SPLIT_PROMPT.format(frequency=clamped_freq)),
        HumanMessage(
            content=f"Frequency: {clamped_freq} days/week. Trainee: {gender_context}. User Split Request: '{preference}'"
        ),
    ]
    plan: DynamicSplitPlan = structured_llm.invoke(prompt)
    if len(plan.days) > clamped_freq:
        plan.days = plan.days[:clamped_freq]
    return _sanitize_llm_plan(plan, clamped_freq, gender)


def calculate_volume_budget(stress_and_sleep: str) -> int:
    text = stress_and_sleep.lower()
    poor_indicators = [
        "poor",
        "bad",
        "terrible",
        "low sleep",
        "lack of sleep",
        "insomnia",
        "high stress",
        "stressed",
        "4 hours",
        "5 hours",
        "6 hours",
    ]
    return 8 if any(phrase in text for phrase in poor_indicators) else 12


def clean_exercise_name(name: str, replace_with_machine: bool = True) -> str:
    replacement = "machine " if replace_with_machine else ""
    cleaned = re.sub(r"^lever\s+", replacement, name, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+v\.\s*\d+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _equipment_rank_sql(preference: tuple[str, ...]) -> str:
    """Builds an ORDER BY CASE ranking catalog equipment against the slot preference."""
    whens = []
    for index, equipment in enumerate(preference, start=1):
        if not re.fullmatch(r"[a-z0-9 ]+", equipment):
            raise ValueError(f"Unsafe equipment token: {equipment!r}")
        whens.append(f"WHEN '{equipment}' THEN {index}")
    return f"CASE LOWER(equipment) {' '.join(whens)} ELSE {len(preference) + 1} END"


def _name_rank_sql(name_rank: tuple[str, ...]) -> str:
    """Builds an ORDER BY CASE ranking catalog names against preferred movement patterns."""
    if not name_rank:
        return ""
    whens = []
    for index, pattern in enumerate(name_rank, start=1):
        if not re.fullmatch(r"[a-z0-9 -]+", pattern):
            raise ValueError(f"Unsafe name pattern: {pattern!r}")
        whens.append(f"WHEN LOWER(name) LIKE '%{pattern}%' THEN {index}")
    return f"CASE {' '.join(whens)} ELSE {len(name_rank) + 1} END ASC, "


def _fetch_by_sql(
    sql: str,
    equipment_pref: tuple[str, ...],
    equipment_access: str,
    limitations: str,
    limit: int,
    extra_exclude: str = "",
    name_rank: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    conn = db.get_connection()
    cursor = conn.cursor()

    where = [f"({sql})"]
    if extra_exclude:
        where.append(f"({extra_exclude})")
    where.append("LOWER(body_part) != 'cardio'")
    if "gym" in equipment_access.lower() or "commercial" in equipment_access.lower():
        where.append("LOWER(name) NOT LIKE '%push-up%' AND LOWER(name) NOT LIKE '%pushup%'")
    if any(w in limitations.lower() for w in ["back", "lumbar", "spine"]):
        where.append("LOWER(name) NOT LIKE '%deadlift%' AND LOWER(name) NOT LIKE '%good morning%'")

    rank_sql = _equipment_rank_sql(equipment_pref)
    query = f"""
        SELECT id, name, body_part, target_muscle, equipment, instructions, image_path, gif_path
        FROM exercises
        WHERE {' AND '.join(where)}
        ORDER BY {_name_rank_sql(name_rank)}{rank_sql} ASC, RANDOM()
        LIMIT ?
    """
    cursor.execute(query, (limit * 4,))
    rows = cursor.fetchall()
    cols = [col[0] for col in cursor.description]
    candidates = []
    for row in rows:
        item = dict(zip(cols, row))
        if _is_excluded(item["name"]):
            continue
        item["name"] = clean_exercise_name(item["name"], replace_with_machine=True)
        name_lower = item["name"].lower()
        is_compound = any(kw in name_lower for kw in COMPOUND_KEYWORDS) and "calf" not in name_lower
        item["mechanic"] = "compound" if is_compound else "isolation"
        candidates.append(item)
        if len(candidates) >= limit:
            break
    return candidates


def fetch_slot_candidates(
    slot_key: str,
    equipment_access: str = "commercial gym",
    limitations: str = "None",
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Resolves a movement slot against the catalog, ranked by the slot's equipment preference."""
    spec = SLOT_SPECS.get(slot_key)
    if spec is None:
        return []
    candidates = _fetch_by_sql(
        spec.sql,
        spec.equipment_pref,
        equipment_access,
        limitations,
        limit,
        extra_exclude=spec.exclude_sql,
        name_rank=spec.name_rank,
    )
    for item in candidates:
        item["slot_key"] = slot_key
    return candidates


def fetch_warmup_candidates(
    warmup_key: str,
    equipment_access: str = "commercial gym",
    limitations: str = "None",
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Resolves a general warm-up movement (Pallof, scapula push plus, glute bridge, ...)."""
    spec = WARMUP_SPECS.get(warmup_key)
    if spec is None:
        return []
    preference = ("body weight", "band", "cable", "dumbbell", "leverage machine")
    candidates = _fetch_by_sql(
        str(spec["sql"]),
        preference,
        equipment_access,
        limitations,
        limit,
    )
    for item in candidates:
        item["warmup_key"] = warmup_key
    return candidates


def fetch_filtered_candidates(
    muscle_group: str | None = None,
    equipment_access: str = "commercial gym",
    limitations: str = "None",
    limit: int = 4,
    body_part: str | None = None,
) -> list[dict[str, Any]]:
    conn = db.get_connection()
    cursor = conn.cursor()

    target = (muscle_group or body_part or "").strip().lower()
    where_clause = SLANG_TO_SQL_MAP.get(
        target, f"(LOWER(target_muscle) LIKE '%{target}%' OR LOWER(body_part) LIKE '%{target}%')"
    )

    bodyweight_clause = ""
    if "gym" in equipment_access.lower() or "commercial" in equipment_access.lower():
        bodyweight_clause = "AND LOWER(name) NOT LIKE '%push-up%' AND LOWER(name) NOT LIKE '%pushup%'"

    query = f"""
        SELECT id, name, body_part, target_muscle, equipment, instructions, image_path, gif_path
        FROM exercises
        WHERE ({where_clause})
          AND LOWER(body_part) != 'cardio'
          {bodyweight_clause}
    """
    if any(w in limitations.lower() for w in ["back", "lumbar", "spine"]):
        query += " AND LOWER(name) NOT LIKE '%deadlift%' AND LOWER(name) NOT LIKE '%good morning%'"

    query += """
        ORDER BY
          CASE
            WHEN LOWER(equipment) IN ('leverage machine', 'smith machine') THEN 1
            WHEN LOWER(equipment) IN ('cable') THEN 2
            WHEN LOWER(equipment) IN ('barbell', 'dumbbell') THEN 3
            ELSE 4
          END ASC,
          CASE
            WHEN LOWER(name) LIKE '%chest supported%'
              OR LOWER(name) LIKE '%chest-supported%'
              OR LOWER(name) LIKE '%seated%'
              OR LOWER(name) LIKE '%lying%' THEN 1
            ELSE 2
          END ASC,
          RANDOM()
        LIMIT ?
    """
    cursor.execute(query, (limit * 4,))
    rows = cursor.fetchall()
    cols = [col[0] for col in cursor.description]
    candidates = []

    for row in rows:
        item = dict(zip(cols, row))
        if _is_excluded(item["name"]):
            continue
        item["name"] = clean_exercise_name(item["name"], replace_with_machine=True)
        name_lower = item["name"].lower()
        is_compound = any(kw in name_lower for kw in COMPOUND_KEYWORDS) and "calf" not in name_lower
        item["mechanic"] = "compound" if is_compound else "isolation"
        candidates.append(item)
        if len(candidates) >= limit:
            break

    return candidates
