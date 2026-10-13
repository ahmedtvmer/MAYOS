import re
from collections.abc import Mapping
from typing import Any, Callable

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

from agent.program_blueprints import (
    DEFAULT_SPLIT_BY_FREQUENCY,
    SLOT_SPECS,
    SLOT_STAPLES,
    SlotSpec,
    SPLIT_DISPLAY_NAMES,
    REST_SECONDS_RANGES_BY_CLASS,
    WARMUP_FAMILIES,
    WARMUP_SPECS,
    body_parts_to_slots,
    build_split_days,
    match_split_keyword,
    resolve_split_type,
)
from agent.movement_signatures import matches_movement_signature
from agent.ProgramState import CustomDayPlan, DynamicSplitPlan
from database.exercise_library.ranking import replacement_rank_sql
from database.exercise_library.schema import exercise_library_visible_sql
from database.exercise_library.values import split_curation_values
from utils.equipment_access import COMMERCIAL_GYM, equipment_access_sql, map_equipment_access
from utils.model_downloader import llm
from utils import player_output_budgets

load_dotenv()

NO_LIMITATIONS = "None"

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

#: Single-joint movements whose names contain a compound keyword ("pulldown").
ISOLATION_NAME_MARKERS = ("calf", "straight-arm", "straight arm")


def is_compound_name(name: str) -> bool:
    name_lower = name.lower()
    return any(kw in name_lower for kw in COMPOUND_KEYWORDS) and not any(
        marker in name_lower for marker in ISOLATION_NAME_MARKERS
    )


def _curation_actions(action_field: Any) -> tuple[str, ...]:
    if isinstance(action_field, str):
        return split_curation_values(action_field)
    return tuple(str(action).strip() for action in (action_field or ()) if str(action).strip())


def _action_joint(action: str) -> str:
    normalized = action.casefold()
    if normalized.startswith(("shoulder ", "scapular ")):
        return "shoulder"
    prefix = normalized.split(" ", 1)[0]
    return {"spinal": "spine"}.get(prefix, prefix)


def _curated_action_mechanic(primary_actions: tuple[str, ...], secondary_actions: tuple[str, ...]) -> str:
    actions = {
        action.casefold()
        for action in (*primary_actions, *secondary_actions)
        if not action.casefold().startswith("anti-") and action.casefold() != "conditioning"
    }
    if not actions:
        return "isolation"

    primary_normalized = {action.casefold() for action in primary_actions}
    joints = {_action_joint(action) for action in actions}
    trunk_work = (
        {"hip flexion", "spinal flexion"}.issubset(actions)
        and joints.issubset({"hip", "spine"})
        and "hip extension" not in actions
    )
    if trunk_work:
        return "isolation"
    if "hip extension" in primary_normalized:
        return "compound"
    return "compound" if len(joints) >= 2 else "isolation"


def exercise_mechanic(exercise: Mapping[str, Any] | str) -> str:
    """Return compound/isolation from curated joints, or legacy name keywords."""
    if isinstance(exercise, str):
        return "compound" if is_compound_name(exercise) else "isolation"

    primary_actions = _curation_actions(exercise.get("primary_action"))
    secondary_actions = _curation_actions(exercise.get("secondary_actions"))
    if not primary_actions and not secondary_actions:
        name = str(exercise.get("name") or exercise.get("exercise_name") or "")
        return "compound" if is_compound_name(name) else "isolation"
    return _curated_action_mechanic(primary_actions, secondary_actions)


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

# The curation vocabulary has no field that marks explosive intent. Keep this
# name check limited to signature substitutions so explicit Staples retain
# their coach-defined priority and name-pattern behavior stays unchanged.
EXPLOSIVE_SIGNATURE_PATTERNS = (
    re.compile(
        r"\b(?:clap|plyo|plyometric|broad[ -]jump|jump|depth|bound|drop|explosive)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bcleans?(?![ -]grip\b)\b", re.IGNORECASE),
    re.compile(r"\bsnatch(?:es)?(?![ -]grip\b)\b", re.IGNORECASE),
    re.compile(r"\bjerks?\b", re.IGNORECASE),
    re.compile(r"\b(?:high|clean|hang)[ -]pulls?\b", re.IGNORECASE),
)


def _is_excluded(name: str) -> bool:
    """Word-boundary exclusion so 'run' never kills 'crunch' or 'reach' never kills 'preacher'."""
    return any(pattern.search(name) for pattern in EXCLUDED_PATTERNS)


def _is_explosive_signature_substitute(name: str) -> bool:
    """Whether a power or Olympic variant cannot fill a signature slot."""
    return any(pattern.search(name) for pattern in EXPLOSIVE_SIGNATURE_PATTERNS)

BASE_REP_WINDOWS = {"compound": (6, 10), "isolation": (10, 15)}

REP_PREFERENCE_OFFSETS = {
    "low": (-1, -1),
    "balanced": (0, 0),
    "high": (2, 2),
}


def get_target_rep_window(mechanic: str, rep_preference: str = "balanced") -> tuple[int, int]:
    return apply_rep_preference(BASE_REP_WINDOWS.get(mechanic, (8, 12)), rep_preference)


def rest_seconds_for_mechanic(mechanic: str) -> int:
    prescription_class = "heavy_compound" if mechanic == "compound" else "isolation"
    minimum, maximum = REST_SECONDS_RANGES_BY_CLASS[prescription_class]
    return (minimum + maximum) // 2


def apply_rep_preference(reps: tuple[int, int], rep_preference: str | None) -> tuple[int, int]:
    """Shifts the blueprint rep window by the player's rep preference (clamped at 4)."""
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


def _parsed_dynamic_split_plan(structured_response: Any) -> DynamicSplitPlan | None:
    if not isinstance(structured_response, Mapping):
        return None
    raw_message = structured_response.get("raw")
    raw_metadata = getattr(raw_message, "response_metadata", None) or {}
    finish_reason = raw_metadata.get("finish_reason") or raw_metadata.get("stop_reason")
    if (
        finish_reason in {"length", "max_tokens"}
        or structured_response.get("parsing_error") is not None
    ):
        return None
    parsed_plan = structured_response.get("parsed")
    return parsed_plan if isinstance(parsed_plan, DynamicSplitPlan) else None


def resolve_split(
    frequency: int,
    preference: str | None = None,
    gender: str = "male",
    inference_call: Callable[..., Any] | None = None,
) -> DynamicSplitPlan:
    clamped_freq = min(max(int(frequency), 1), 5)
    if not preference or preference.strip().lower() in ["standard", "default", "none", "balanced"]:
        return get_default_split(clamped_freq, gender=gender)

    canonical_split = preference.strip().casefold()
    split_type = (
        canonical_split
        if canonical_split in SPLIT_DISPLAY_NAMES
        else match_split_keyword(preference)
    )
    if split_type:
        plan = get_split_plan(split_type, clamped_freq, gender)
        if plan is not None:
            return plan
        # Recognized request at an unsupported frequency (e.g. "arnold" at 1 day):
        # stay deterministic and fall back to the frequency default rather than the LLM.
        return get_default_split(clamped_freq, gender=gender)

    structured_llm = llm.with_structured_output(
        DynamicSplitPlan,
        include_raw=True,
        max_completion_tokens=player_output_budgets.player_output_budget("dynamic_split_plan"),
    )
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
    if inference_call is None:
        response = structured_llm.invoke(prompt)
    else:
        response = inference_call(structured_llm.invoke, prompt)
    plan = _parsed_dynamic_split_plan(response)
    if plan is None:
        return get_default_split(clamped_freq, gender=gender)
    if len(plan.days) > clamped_freq:
        plan.days = plan.days[:clamped_freq]
    return _sanitize_llm_plan(plan, clamped_freq, gender)


def clean_exercise_name(name: str, replace_with_machine: bool = True) -> str:
    def replace_lever(match: re.Match[str]) -> str:
        if not replace_with_machine:
            return ""
        return "Machine " if match.group(0)[0].isupper() else "machine "

    # Display names arrive in Title Case, so preserve the case of "Lever".
    cleaned = re.sub(r"^lever\s+", replace_lever, name, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+v\.\s*\d+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _equipment_rank_sql(preference: tuple[str, ...], column: str = "equipment") -> str:
    """Builds an ORDER BY CASE ranking catalog equipment against the slot preference."""
    whens = []
    for index, equipment in enumerate(preference, start=1):
        if not re.fullmatch(r"[a-z0-9 ]+", equipment):
            raise ValueError(f"Unsafe equipment token: {equipment!r}")
        whens.append(f"WHEN '{equipment}' THEN {index}")
    return f"CASE LOWER({column}) {' '.join(whens)} ELSE {len(preference) + 1} END"


def _name_rank_sql(name_rank: tuple[str, ...]) -> str:
    """Builds an ORDER BY CASE ranking catalog names against preferred movement patterns."""
    if not name_rank:
        return ""
    return f"{_name_rank_expression(name_rank)} ASC, "


def _name_rank_expression(name_rank: tuple[str, ...]) -> str:
    if not name_rank:
        return "0"
    whens = []
    for index, pattern in enumerate(name_rank, start=1):
        if not re.fullmatch(r"[a-z0-9 -]+", pattern):
            raise ValueError(f"Unsafe name pattern: {pattern!r}")
        whens.append(f"WHEN LOWER(e.name) LIKE '%{pattern}%' THEN {index}")
    return f"CASE {' '.join(whens)} ELSE {len(name_rank) + 1} END"


def _back_limitation_filter(limitations: str, source_name_column: str = "e.name") -> str | None:
    if any(word in limitations.lower() for word in ("back", "lumbar", "spine")):
        return (
            f"LOWER({source_name_column}) NOT LIKE '%deadlift%' "
            f"AND LOWER({source_name_column}) NOT LIKE '%good morning%'"
        )
    return None


def _slot_source_filter(
    spec: SlotSpec, staple_ids: tuple[str, ...]
) -> str:
    clauses = ["sp.exercise_id IS NOT NULL"] if staple_ids else []
    clauses.append(
        "(cf.primary_action IS NOT NULL AND cf.primary_muscle IS NOT NULL)"
    )
    clauses.append(f"({spec.sql})")
    return " OR ".join(clauses)


def _slot_ctes_and_join(
    spec: SlotSpec, staple_ids: tuple[str, ...]
) -> tuple[str, str, list[Any]]:
    ctes = ["replacement_cf AS (SELECT ? AS primary_action, ? AS primary_muscle)"]
    params: list[Any] = [spec.primary_actions[0], spec.primary_muscles[0]]
    if staple_ids:
        value_rows = ", ".join("(?, ?)" for _ in staple_ids)
        ctes.append(f"staple_priority(exercise_id, staple_rank) AS (VALUES {value_rows})")
        params.extend(value for rank, exercise_id in enumerate(staple_ids) for value in (exercise_id, rank))
    else:
        ctes.append("staple_priority(exercise_id, staple_rank) AS (SELECT NULL, NULL WHERE 0)")
    join = "LEFT JOIN staple_priority sp ON sp.exercise_id = e.id"
    return ", ".join(ctes), join, params


def _slot_filters(
    spec: SlotSpec,
    equipment_access: str,
    limitations: str,
    staple_ids: tuple[str, ...],
) -> list[str]:
    source_filter = _slot_source_filter(spec, staple_ids)
    where = [
        f"({source_filter})",
        "LOWER(e.body_part) != 'cardio'",
        exercise_library_visible_sql("e.id", schema="catalog"),
        equipment_access_sql(equipment_access, "e.equipment"),
    ]
    if spec.exclude_sql:
        signature_name_exceptions = _signature_name_exception_filter(spec)
        exclusion_filter = f"({spec.exclude_sql})"
        if signature_name_exceptions:
            exclusion_filter = f"({exclusion_filter} OR ({signature_name_exceptions}))"
        where.append(exclusion_filter)
    back_filter = _back_limitation_filter(limitations)
    if back_filter:
        where.append(back_filter)
    return where


def _signature_name_exception_filter(spec: SlotSpec) -> str:
    if not spec.signature_name_exceptions:
        return ""
    complete_curation = (
        "sp.exercise_id IS NULL AND cf.primary_action IS NOT NULL "
        "AND cf.primary_muscle IS NOT NULL"
    )
    exclusion_clauses = spec.exclude_sql.split(" AND ")
    exception_clauses = []
    for source_name in spec.signature_name_exceptions:
        remaining = [
            clause
            for clause in exclusion_clauses
            if (
                (match := re.fullmatch(r"LOWER\(name\) NOT LIKE '%([^%]+)%'", clause))
                is None
                or match.group(1).casefold() not in source_name.casefold()
            )
        ]
        escaped_name = source_name.casefold().replace("'", "''")
        remaining_sql = " AND ".join(remaining) or "1 = 1"
        exception_clauses.append(
            f"({complete_curation} AND LOWER(e.name) = '{escaped_name}' AND ({remaining_sql}))"
        )
    return " OR ".join(exception_clauses)


SLOT_CANDIDATE_STAPLE_RANK = 0
SLOT_CANDIDATE_SIGNATURE_RANK = 1
SLOT_CANDIDATE_NAME_RANK = 2
SLOT_CANDIDATE_STAPLE = "staple"
SLOT_CANDIDATE_SIGNATURE = "signature"
SLOT_CANDIDATE_NAME = "name"

_SLOT_SOURCE_RANK_SQL = (
    f"CASE WHEN sp.exercise_id IS NOT NULL THEN {SLOT_CANDIDATE_STAPLE_RANK} "
    f"WHEN cf.primary_action IS NOT NULL AND cf.primary_muscle IS NOT NULL "
    f"THEN {SLOT_CANDIDATE_SIGNATURE_RANK} ELSE {SLOT_CANDIDATE_NAME_RANK} END"
)


def _slot_rank_select(spec: SlotSpec) -> str:
    expressions = {
        "rank_source": _SLOT_SOURCE_RANK_SQL,
        "rank_staple": "COALESCE(sp.staple_rank, 0)",
        "rank_signature": replacement_rank_sql(),
        "rank_equipment": _equipment_rank_sql(spec.equipment_pref, "e.equipment"),
        "rank_name_pattern": _name_rank_expression(spec.name_rank),
        "rank_name_review": "CASE WHEN COALESCE(edn.is_reviewed, 0) = 1 THEN 0 ELSE 1 END",
        "rank_sort_name": "LOWER(COALESCE(edn.display_name, e.name))",
    }
    return ", ".join(f"{expression} AS {name}" for name, expression in expressions.items())


_SLOT_CANDIDATE_ORDER_SQL = (
    "rank_source ASC, "
    f"CASE WHEN rank_source = {SLOT_CANDIDATE_STAPLE_RANK} THEN rank_staple END ASC, "
    f"CASE WHEN rank_source = {SLOT_CANDIDATE_SIGNATURE_RANK} THEN rank_signature END ASC, "
    f"CASE WHEN rank_source = {SLOT_CANDIDATE_SIGNATURE_RANK} THEN rank_equipment END ASC, "
    f"CASE WHEN rank_source = {SLOT_CANDIDATE_SIGNATURE_RANK} THEN rank_name_review END ASC, "
    f"CASE WHEN rank_source = {SLOT_CANDIDATE_SIGNATURE_RANK} THEN rank_sort_name END ASC, "
    f"CASE WHEN rank_source = {SLOT_CANDIDATE_NAME_RANK} THEN rank_name_pattern END ASC, "
    f"CASE WHEN rank_source = {SLOT_CANDIDATE_NAME_RANK} THEN rank_equipment END ASC, e.id ASC"
)


def _slot_candidate_sql(ctes: str, joins: str, where: list[str], rank_select: str) -> str:
    return f"""
        WITH {ctes}
        SELECT e.id, COALESCE(edn.display_name, e.name) AS name,
               e.name AS source_name, e.body_part, e.target_muscle,
               e.equipment, e.instructions, e.image_path, e.gif_path,
               cf.primary_action, cf.primary_muscle,
               COALESCE(cf.secondary_actions, '') AS secondary_actions,
               {rank_select}
        FROM catalog.exercises e
        LEFT JOIN catalog.exercise_display_names edn ON edn.exercise_id = e.id
        LEFT JOIN catalog.exercise_curated_fields cf ON cf.exercise_id = e.id
        {joins}
        CROSS JOIN replacement_cf
        WHERE {' AND '.join(where)}
        ORDER BY {_SLOT_CANDIDATE_ORDER_SQL}
    """


def _slot_candidate_query(
    spec: SlotSpec,
    equipment_access: str,
    limitations: str,
    staple_ids: tuple[str, ...],
) -> tuple[str, list[Any]]:
    ctes, join, cte_params = _slot_ctes_and_join(spec, staple_ids)
    where = _slot_filters(spec, equipment_access, limitations, staple_ids)
    rank_select = _slot_rank_select(spec)
    query = _slot_candidate_sql(ctes, join, where, rank_select)
    return query, cte_params


def _slot_candidate_source(candidate: dict[str, Any], spec: SlotSpec) -> str | None:
    source_rank = candidate["rank_source"]
    if source_rank == SLOT_CANDIDATE_SIGNATURE_RANK:
        if not matches_movement_signature(
            candidate.get("primary_action"), candidate.get("primary_muscle"), spec
        ):
            return None
        return SLOT_CANDIDATE_SIGNATURE
    return SLOT_CANDIDATE_STAPLE if source_rank == SLOT_CANDIDATE_STAPLE_RANK else SLOT_CANDIDATE_NAME


def _candidate_rows(
    cursor, limit: int, slot_spec: SlotSpec | None = None
) -> list[dict[str, Any]]:
    columns = [column[0] for column in cursor.description]
    rank_columns = [name for name in columns if name.startswith("rank_")]
    candidates = []
    for row in cursor.fetchall():
        candidate = dict(zip(columns, row))
        source_name = candidate.pop("source_name")
        if _is_excluded(source_name):
            continue
        candidate["secondary_actions"] = split_curation_values(candidate["secondary_actions"])
        candidate["mechanic"] = exercise_mechanic(candidate)
        if slot_spec is not None:
            candidate_source = _slot_candidate_source(candidate, slot_spec)
            if candidate_source is None:
                continue
            if candidate_source == SLOT_CANDIDATE_SIGNATURE and _is_explosive_signature_substitute(source_name):
                continue
            candidate["_candidate_source"] = candidate_source
            candidate.pop("primary_action", None)
            candidate.pop("primary_muscle", None)
        for rank_column in rank_columns:
            candidate.pop(rank_column, None)
        candidate["name"] = clean_exercise_name(candidate["name"], replace_with_machine=True)
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


def _fetch_by_sql(
    sql: str,
    equipment_pref: tuple[str, ...],
    equipment_access: str,
    limitations: str,
    limit: int,
    extra_exclude: str = "",
    name_rank: tuple[str, ...] = (),
    filter_equipment_access: bool = True,
    *,
    ledger: Any,
) -> list[dict[str, Any]]:
    conn = ledger.conn
    cursor = conn.cursor()

    where = [f"({sql})"]
    if extra_exclude:
        where.append(f"({extra_exclude})")
    where.append("LOWER(body_part) != 'cardio'")
    where.append(exercise_library_visible_sql("e.id", schema="catalog"))
    if filter_equipment_access:
        where.append(equipment_access_sql(equipment_access))
    source_name = "(SELECT source_exercise.name FROM catalog.exercises source_exercise WHERE source_exercise.id = e.id)"
    back_filter = _back_limitation_filter(limitations, source_name)
    if back_filter:
        where.append(back_filter)

    rank_sql = _equipment_rank_sql(equipment_pref)
    query = f"""
        SELECT e.id, COALESCE(edn.display_name, e.name) AS name,
               (SELECT source_exercise.name FROM catalog.exercises source_exercise
                WHERE source_exercise.id = e.id) AS source_name,
               e.body_part, e.target_muscle,
               e.equipment, e.instructions, e.image_path, e.gif_path,
               cf.primary_action, COALESCE(cf.secondary_actions, '') AS secondary_actions
        FROM exercises e
        LEFT JOIN catalog.exercise_display_names edn ON edn.exercise_id = e.id
        LEFT JOIN catalog.exercise_curated_fields cf ON cf.exercise_id = e.id
        WHERE {' AND '.join(where)}
        ORDER BY {_name_rank_sql(name_rank)}{rank_sql} ASC, id ASC
        LIMIT ?
    """
    cursor.execute(query, (limit * 4,))
    return _candidate_rows(cursor, limit)


def fetch_slot_candidates(
    slot_key: str,
    equipment_access: str = COMMERCIAL_GYM,
    limitations: str = NO_LIMITATIONS,
    limit: int = 6,
    *,
    ledger: Any,
) -> list[dict[str, Any]]:
    """Returns ordered Staples, signature matches, and uncurated name matches for a slot."""
    spec = SLOT_SPECS.get(slot_key)
    if spec is None:
        return []
    cursor = ledger.conn.cursor()
    query, params = _slot_candidate_query(
        spec, equipment_access, limitations, SLOT_STAPLES.get(slot_key, ())
    )
    cursor.execute(query, params)
    candidates = _candidate_rows(cursor, limit, spec)
    for item in candidates:
        item["slot_key"] = slot_key
    return candidates


def fetch_warmup_candidates(
    warmup_key: str,
    equipment_access: str = COMMERCIAL_GYM,
    limitations: str = NO_LIMITATIONS,
    limit: int = 4,
    *,
    ledger: Any,
) -> list[dict[str, Any]]:
    """Resolves a general warm-up movement (Pallof, scapula push plus, glute bridge, ...)."""
    spec = WARMUP_SPECS.get(warmup_key)
    if spec is None:
        return []
    access = map_equipment_access(equipment_access)
    preference = tuple(
        spec.get("equipment_pref_by_access", {}).get(
            access, spec.get("equipment_pref", ("body weight", "band", "cable", "dumbbell", "leverage machine"))
        )
    )
    name_rank = tuple(spec.get("name_rank_by_access", {}).get(access, ()))
    candidates = _fetch_by_sql(
        str(spec["sql"]),
        preference,
        equipment_access,
        limitations,
        limit,
        name_rank=name_rank,
        ledger=ledger,
        filter_equipment_access=(
            bool(spec.get("equipment_access_aware")) and access != COMMERCIAL_GYM
        ),
    )
    for item in candidates:
        item["warmup_key"] = warmup_key
    return candidates


def fetch_filtered_candidates(
    muscle_group: str | None = None,
    equipment_access: str = COMMERCIAL_GYM,
    limitations: str = NO_LIMITATIONS,
    limit: int = 4,
    body_part: str | None = None,
    *,
    ledger: Any,
) -> list[dict[str, Any]]:
    conn = ledger.conn
    cursor = conn.cursor()

    target = (muscle_group or body_part or "").strip().lower()
    where_clause = SLANG_TO_SQL_MAP.get(
        target, f"(LOWER(target_muscle) LIKE '%{target}%' OR LOWER(body_part) LIKE '%{target}%')"
    )

    query = f"""
        SELECT e.id, e.name, e.body_part, e.target_muscle, e.equipment,
               e.instructions, e.image_path, e.gif_path, cf.primary_action,
               COALESCE(cf.secondary_actions, '') AS secondary_actions
        FROM exercises e
        LEFT JOIN catalog.exercise_curated_fields cf ON cf.exercise_id = e.id
        WHERE ({where_clause})
          AND LOWER(body_part) != 'cardio'
          AND {equipment_access_sql(equipment_access)}
          AND {exercise_library_visible_sql('e.id', schema='catalog')}
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
        item["secondary_actions"] = split_curation_values(item["secondary_actions"])
        item["mechanic"] = exercise_mechanic(item)
        candidates.append(item)
        if len(candidates) >= limit:
            break

    return candidates
