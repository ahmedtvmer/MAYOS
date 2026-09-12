# agent/debrief.py
from typing import Any, Dict, List

DEBRIEF_SYSTEM_PROMPT = """You are an elite hypertrophic analytics engine.
Generate ONLY the '**Next Session Directives**' section for the debrief.

CRITICAL RULES:
1. DELOAD LOGIC:
   - If [DELOAD STATUS] is ACTIVE: Command volume cut and RPE cap (e.g., "Cut sets by 50%, cap at RPE 7.0").
   - If [DELOAD STATUS] is INACTIVE: Do NOT mention deloads, volume cuts, or RPE caps. Give progression or hold marching orders.

2. STRUCTURE:
   - Output MUST be strictly 2 to 4 concise bullet points under 50 words.
   - Zero conversational cheerleading.

Output format:
**Next Session Directives**:
- [Directive 1]
- [Directive 2]
"""

def format_fatigue_cns_check(readiness: int, total_tonnage: float, session_notes: str) -> str:
    notes_str = f" Notes: {session_notes}." if session_notes else ""
    return f"- Readiness: {readiness}/5 | Volume Load: {total_tonnage:,.1f} kg.{notes_str}"

def format_overload_deltas(exercise_summaries: List[Dict[str, Any]]) -> str:
    advancements = []
    for ex in exercise_summaries:
        delta = ex.get("e1rm_delta", 0.0)
        curr = ex.get("current_e1rm")
        name = ex.get("name", "Exercise")
        if delta > 0 and curr:
            advancements.append(f"- {name}: e1RM advanced by +{delta:.1f} kg ({curr:.1f} kg). Load step-up (+2.5 kg).")
        elif curr:
            advancements.append(f"- {name}: e1RM maintained at {curr:.1f} kg (+0.0 kg). Load held.")
    
    if not advancements:
        return "- No e1RM advancements recorded; all loads maintained in current rep corridor."
    
    return "\n".join(advancements)


def generate_session_debrief(
    split_name: str,
    readiness: int,
    session_notes: str,
    exercise_summaries: list[dict[str, Any]],
    profile: dict[str, Any] | None = None,
    fatigue_info: dict[str, Any] | None = None,
) -> str:
    """Generates a structured post-workout debrief from raw telemetry."""
    is_deload = bool(fatigue_info and fatigue_info.get("deload_recommended", False))

    # 1. Deterministic Metrics & Fatigue Blocks
    total_tonnage = sum(ex.get("volume_load", 0.0) for ex in exercise_summaries)
    deltas_block = format_overload_deltas(exercise_summaries)
    fatigue_block = format_fatigue_cns_check(readiness, total_tonnage, session_notes)

    # 2. Deterministic Next Session Directives (Zero LLM Drift)
    directives: list[str] = []

    if is_deload:
        rpe_cap = fatigue_info.get("intensity_cap_rpe", 7.0)
        directives.append(f"- DELOAD: Reduce sets, cap at RPE {rpe_cap:.1f}.")
        directives.append("- Hold current progression and prepare for deload adjustments.")
        if fatigue_info.get("severity") == "HIGH" or "readiness" in fatigue_info.get("reason", "").lower():
            directives.append("- Monitor readiness closely and adjust volume cuts as necessary.")
    else:
        for ex in exercise_summaries:
            action = ex.get("action", "hold")
            name = ex.get("name", "Exercise")
            delta = ex.get("e1rm_delta", 0.0)
            if action == "increase" or delta > 0:
                directives.append(f"- Advance load (+2.5 kg) for {name}.")
            else:
                directives.append(f"- Hold load; build reps in the {name}.")

    directives_block = "**Next Session Directives**:\n" + "\n".join(directives)

    # 3. Assemble Immutable 3-Section Payload
    return (
        f"**Overload Deltas**:\n{deltas_block}\n\n"
        f"**Fatigue & CNS Check**:\n{fatigue_block}\n\n"
        f"{directives_block}"
    )
