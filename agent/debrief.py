# agent/debrief.py
from dataclasses import dataclass
from typing import Any, Dict, List, Literal

from core.effort import UNRATED, min_rir_label

DEBRIEF_SYSTEM_PROMPT = """You are an elite hypertrophic analytics engine.
Generate ONLY the '**Next Session Directives**' section for the debrief.

CRITICAL RULES:
1. DELOAD LOGIC:
   - If [DELOAD STATUS] is ACTIVE: Command volume cut and a reps-in-reserve cap (e.g., "Cut sets by 50%, cap at RIR ≥ 3").
   - If [DELOAD STATUS] is INACTIVE: Do NOT mention deloads, volume cuts, or RIR caps. Give progression or hold marching orders.

2. STRUCTURE:
   - Output MUST be strictly 2 to 4 concise bullet points under 50 words.
   - Zero conversational cheerleading.

Output format:
**Next Session Directives**:
- [Directive 1]
- [Directive 2]
"""


@dataclass(frozen=True)
class _SessionDebriefFacts:
    readiness: int
    session_notes: str
    exercise_summaries: list[dict[str, Any]]
    fatigue_info: dict[str, Any] | None
    total_tonnage: float | None
    pr_events: list[dict[str, Any]]
    display_language: str


_ARABIC_COUNT_FORMS: dict[str, tuple[str, str, str, str, str, str]] = {
    "training_set": (
        "مجموعات تدريب",
        "مجموعة تدريب واحدة",
        "مجموعتا تدريب",
        "مجموعتي تدريب",
        "مجموعة تدريب",
        "مجموعة تدريب",
    ),
    "repetition": (
        "تكرارات",
        "تكرار واحد",
        "تكراران",
        "تكرارين",
        "تكرارًا",
        "تكرار",
    ),
}


def arabic_count_phrase(
    count: int,
    noun: Literal["training_set", "repetition"],
    *,
    grammatical_case: Literal["nominative", "oblique"] = "nominative",
    numeral_direction: Literal["plain", "isolated"] = "plain",
) -> str:
    """Render a short Arabic count using the shared UI's agreement rules."""
    # Mirrors mobile/lib/src/core/display_language/arabic_count.dart.
    zero_and_few, one, dual, dual_oblique, many, other = _ARABIC_COUNT_FORMS[noun]
    shown_count = (
        f"\u2066{count}\u2069" if numeral_direction == "isolated" else str(count)
    )
    if count == 0:
        return f"{shown_count} {zero_and_few}"
    if count == 1:
        return one
    if count == 2:
        return dual_oblique if grammatical_case == "oblique" else dual
    remainder = count % 100
    if 3 <= remainder <= 10:
        return f"{shown_count} {zero_and_few}"
    if 11 <= remainder <= 99:
        return f"{shown_count} {many}"
    return f"{shown_count} {other}"


def _summary_copy(display_language: str, english: str, arabic: str) -> str:
    return arabic if display_language == "ar" else english


def _isolate_first_strong(value: str) -> str:
    return f"\u2068{value}\u2069"


def _isolate_left_to_right(value: str) -> str:
    return f"\u2066{value}\u2069"


def _deload_volume_cut(fatigue_info: dict[str, Any]) -> str | None:
    """Renders the exact volume-cut percentage from ``volume_multiplier``.

    A multiplier of ``0.5`` means a 50% cut, ``0.6`` a 40% cut. Missing or
    invalid values return ``None`` so the caller never fabricates a number.
    """
    try:
        multiplier = float(fatigue_info.get("volume_multiplier"))
    except (TypeError, ValueError):
        return None
    if not 0.0 < multiplier < 1.0:
        return None
    return f"{(1.0 - multiplier) * 100.0:g}%"


def _deload_rir_cap(fatigue_info: dict[str, Any]) -> str | None:
    """The deload intensity cap as the equivalent *minimum* RIR (#111).

    A cap is the most effort allowed, so it reads as the least RIR the next
    session may leave (RPE 7.0 -> ``≥ 3``), through the shared formatter.
    A missing cap keeps the ``UNRATED`` marker for the formatter to omit;
    invalid values return ``None`` so the directive never fabricates a number.
    """
    raw_cap = fatigue_info.get("intensity_cap_rpe")
    if raw_cap is None:
        return UNRATED
    try:
        cap = float(raw_cap)
    except (TypeError, ValueError):
        return None
    if not 0.0 <= cap <= 10.0:
        return None
    return min_rir_label(cap)


def format_fatigue_cns_check(
    readiness: int,
    total_tonnage: float,
    session_notes: str,
    display_language: str = "en",
) -> str:
    notes_label = _summary_copy(display_language, "Notes", "ملاحظات")
    notes = f" {notes_label}: {session_notes}." if session_notes else ""
    total = f"{total_tonnage:,.1f} kg"
    line = _summary_copy(
        display_language,
        f"- Readiness: {readiness}/5 | Volume Load: {total}.",
        f"- الاستعداد: {_isolate_left_to_right(f'{readiness}/5')} | إجمالي الوزن المرفوع: "
        f"{_isolate_left_to_right(total)}.",
    )
    return f"{line}{notes}"


def _format_exercise_overload(
    exercise: Dict[str, Any], display_language: str
) -> str | None:
    raw_delta = exercise.get("e1rm_delta")
    delta = float(raw_delta) if raw_delta is not None else None
    current = exercise.get("current_e1rm")
    name = exercise.get("name", "Exercise")
    if delta is not None and delta > 0 and current:
        return _summary_copy(
            display_language,
            f"- {name}: e1RM advanced by +{delta:.1f} kg "
            f"({current:.1f} kg). Load step-up (+2.5 kg).",
            f"- {_isolate_first_strong(name)}: تحسن {_isolate_first_strong('e1RM')} بمقدار "
            f"{_isolate_left_to_right(f'+{delta:.1f} kg')} "
            f"({_isolate_left_to_right(f'{current:.1f} kg')}). "
            f"زد الحمل {_isolate_left_to_right('(+2.5 kg)')}.",
        )
    if not current:
        return None
    if delta is None:
        return _summary_copy(
            display_language,
            f"- {name}: Baseline established at {current:.1f} kg e1RM. Load held.",
            f"- {_isolate_first_strong(name)}: خط الأساس لـ "
            f"{_isolate_first_strong('e1RM')}: {_isolate_left_to_right(f'{current:.1f} kg')}. "
            "ثبّت الحمل.",
        )
    return _summary_copy(
        display_language,
        f"- {name}: e1RM maintained at {current:.1f} kg (+0.0 kg). Load held.",
        f"- {_isolate_first_strong(name)}: {_isolate_first_strong('e1RM')} ثابت عند "
        f"{_isolate_left_to_right(f'{current:.1f} kg')} "
        f"{_isolate_left_to_right('(+0.0 kg)')}. ثبّت الحمل.",
    )


def format_overload_deltas(
    exercise_summaries: List[Dict[str, Any]], display_language: str = "en"
) -> str:
    advancements = [
        line
        for exercise in exercise_summaries
        if (line := _format_exercise_overload(exercise, display_language))
    ]
    if advancements:
        return "\n".join(advancements)
    return _summary_copy(
        display_language,
        "- No e1RM advancements recorded; all loads maintained in current rep corridor.",
        f"- لم يُسجل تحسن في {_isolate_first_strong('e1RM')}؛ "
        "بقيت الأوزان ضمن نطاق التكرارات الحالي.",
    )


def _format_prev_value(prev_value: Any, display_language: str = "en") -> str:
    if prev_value is None:
        return _summary_copy(display_language, "first record", "أول قياس")
    prior = f"{float(prev_value):g} kg"
    return _summary_copy(
        display_language,
        f"prev {prior}",
        f"السابق {_isolate_left_to_right(prior)}",
    )


def _format_pr_event(event: Dict[str, Any], display_language: str) -> str | None:
    prev = _format_prev_value(event.get("prev_value"), display_language)
    record_type = event.get("record_type")
    if record_type == "max_weight":
        weight = float(event["value"])
        reps = int(event["reps"])
        repetition_count = arabic_count_phrase(
            reps,
            "repetition",
            grammatical_case="oblique",
            numeral_direction="isolated",
        )
        preposition = "ل" if reps in (1, 2) else "لـ"
        return _summary_copy(
            display_language,
            f"heaviest {weight:g} kg for {reps} reps ({prev})",
            f"أعلى وزن {_isolate_left_to_right(f'{weight:g} kg')} "
            f"{preposition}{repetition_count} ({prev})",
        )
    if record_type == "max_e1rm":
        value = f"{float(event['value']):.1f} kg"
        return _summary_copy(
            display_language,
            f"e1RM {value} ({prev})",
            f"{_isolate_first_strong('e1RM')} {_isolate_left_to_right(value)} ({prev})",
        )
    if record_type == "most_reps":
        previous_reps = int(event.get("prev_value") or 0)
        reps = int(event["value"])
        return _summary_copy(
            display_language,
            f"most reps {reps} reps (prev {previous_reps} reps)",
            f"أعلى عدد من التكرارات: "
            f"{arabic_count_phrase(reps, 'repetition', numeral_direction='isolated')} "
            f"(السابق: "
            f"{arabic_count_phrase(previous_reps, 'repetition', numeral_direction='isolated')})",
        )
    return None


def format_pr_events(pr_events: List[Dict[str, Any]], display_language: str = "en") -> str:
    """Deterministic 🏆 lines for exercise-wide records beaten this session (ADR 042).

    Grouped per movement: one heaviest-weight line (any rep count, never phrased
    as a per-rep-count "× reps" record — the reps are mentioned as the reps the
    weight was lifted for) and one best-e1RM line.
    """
    if not pr_events:
        return ""

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for event in pr_events:
        key = str(event.get("exercise_id") or event.get("name", "Exercise"))
        grouped.setdefault(key, []).append(event)

    lines = []
    for events in grouped.values():
        name = events[0].get("name") or events[0].get("exercise_id", "Exercise")
        parts = [
            part
            for event in events
            if (part := _format_pr_event(event, display_language))
        ]
        if parts:
            heading = _summary_copy(
                display_language, "🏆 New PR", "🏆 رقم قياسي شخصي جديد"
            )
            shown_name = _summary_copy(
                display_language, name, _isolate_first_strong(name)
            )
            lines.append(f"- {heading}: {shown_name} — " + " | ".join(parts))
    return "\n".join(lines)


def generate_session_debrief(
    split_name: str,
    readiness: int,
    session_notes: str,
    exercise_summaries: list[dict[str, Any]],
    profile: dict[str, Any] | None = None,
    fatigue_info: dict[str, Any] | None = None,
    total_tonnage: float | None = None,
    total_sets: int | None = None,
    pr_events: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> str:
    """Render a deterministic debrief in the player's Display language.

    ``display_language`` in the legacy keyword map accepts ``en`` or ``ar``;
    unsupported values use English. Recorded notes and exercise names remain
    in their original wording.
    """
    facts = _SessionDebriefFacts(
        readiness=readiness,
        session_notes=session_notes,
        exercise_summaries=exercise_summaries,
        fatigue_info=fatigue_info,
        total_tonnage=total_tonnage,
        pr_events=pr_events or [],
        display_language="ar" if kwargs.get("display_language") == "ar" else "en",
    )
    return _render_session_debrief(facts)


def _format_deload_directive(
    volume_cut: str | None, rir_cap: str | None, display_language: str
) -> str:
    english_sets = f"Cut sets by {volume_cut}" if volume_cut else "Reduce sets"
    arabic_sets = (
        f"خفّض مجموعات التدريب بنسبة {_isolate_left_to_right(volume_cut)}"
        if volume_cut
        else "قلّل مجموعات التدريب"
    )
    set_clause = _summary_copy(display_language, english_sets, arabic_sets)
    if rir_cap is None or rir_cap == UNRATED:
        cap_clause = ""
    else:
        minimum_rir = rir_cap.removeprefix("≥ ")
        cap_clause = _summary_copy(
            display_language,
            f", cap at RIR {rir_cap}",
            f"، بحيث لا يقل {_isolate_first_strong('RIR')} عن "
            f"{_isolate_left_to_right(minimum_rir)}",
        )
    heading = _summary_copy(display_language, "DELOAD", "تخفيف التدريب")
    return f"- {heading}: {set_clause}{cap_clause}."


def _format_progression_directive(
    exercise: Dict[str, Any], display_language: str
) -> str:
    action = exercise.get("action", "hold")
    raw_delta = exercise.get("e1rm_delta")
    delta = float(raw_delta) if raw_delta is not None else 0.0
    name = exercise.get("name", "Exercise")
    if action == "increase" or delta > 0:
        return _summary_copy(
            display_language,
            f"- Advance load (+2.5 kg) for {name}.",
            f"- زد الحمل {_isolate_left_to_right('(+2.5 kg)')} لتمرين "
            f"{_isolate_first_strong(name)}.",
        )
    return _summary_copy(
        display_language,
        f"- Hold load; build reps in the {name}.",
        f"- ثبّت الحمل وزد التكرارات ضمن نطاق تمرين {_isolate_first_strong(name)}.",
    )


def _format_next_session_directives(facts: _SessionDebriefFacts) -> list[str]:
    fatigue_info = facts.fatigue_info or {}
    if not fatigue_info.get("deload_recommended", False):
        return [
            _format_progression_directive(exercise, facts.display_language)
            for exercise in facts.exercise_summaries
        ]

    directives = [
        _format_deload_directive(
            _deload_volume_cut(fatigue_info),
            _deload_rir_cap(fatigue_info),
            facts.display_language,
        ),
        _summary_copy(
            facts.display_language,
            "- Hold current progression and prepare for deload adjustments.",
            "- ثبّت التدرج الحالي واستعد لتعديلات تخفيف التدريب.",
        ),
    ]
    monitor_readiness = fatigue_info.get("severity") == "HIGH" or (
        "readiness" in fatigue_info.get("reason", "").lower()
    )
    if monitor_readiness:
        directives.append(
            _summary_copy(
                facts.display_language,
                "- Monitor readiness closely and adjust volume cuts as necessary.",
                "- راقب الاستعداد عن قرب واضبط خفض المجموعات عند الحاجة.",
            )
        )
    return directives


def _render_session_debrief(facts: _SessionDebriefFacts) -> str:
    total_tonnage = facts.total_tonnage
    if total_tonnage is None:
        total_tonnage = sum(
            exercise.get("volume_load", 0.0)
            for exercise in facts.exercise_summaries
        )

    deltas = format_overload_deltas(
        facts.exercise_summaries, facts.display_language
    )
    pr_events = format_pr_events(facts.pr_events, facts.display_language)
    if pr_events:
        deltas = f"{deltas}\n{pr_events}"
    fatigue = format_fatigue_cns_check(
        facts.readiness,
        total_tonnage,
        facts.session_notes,
        facts.display_language,
    )
    directives_heading = _summary_copy(
        facts.display_language,
        "Next Session Directives",
        "توجيهات الحصة التالية",
    )
    directives = "\n".join(_format_next_session_directives(facts))
    directives_block = f"**{directives_heading}**:\n{directives}"
    overload_heading = _summary_copy(
        facts.display_language, "Overload Deltas", "تغيرات الأداء"
    )
    fatigue_heading = _summary_copy(
        facts.display_language,
        "Fatigue & CNS Check",
        "مراجعة الإرهاق والجهاز العصبي",
    )
    return (
        f"**{overload_heading}**:\n{deltas}\n\n"
        f"**{fatigue_heading}**:\n{fatigue}\n\n"
        f"{directives_block}"
    )
