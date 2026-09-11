# agent/debrief.py
from typing import Any, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from utils.model_downloader import llm
from utils.text_scrubber import scrub_coach_output

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
    exercise_summaries: List[Dict[str, Any]],
    profile: Optional[Dict[str, Any]] = None,
    fatigue_info: Optional[Dict[str, Any]] = None,
) -> str:
    """Generates a structured post-workout debrief from raw telemetry."""
    is_deload = bool(fatigue_info and fatigue_info.get("deload_recommended", False))
    
    # 1. Format Deload Telemetry
    if is_deload:
        vol_cut_pct = int((1.0 - fatigue_info.get("volume_multiplier", 0.5)) * 100)
        rpe_cap = fatigue_info.get("intensity_cap_rpe", 7.0)
        deload_block = (
            f"[DELOAD STATUS]: ACTIVE\n"
            f"- Severity: {fatigue_info.get('severity', 'HIGH')}\n"
            f"- Trigger Reason: {fatigue_info.get('reason')}\n"
            f"- Mandated Volume Cut: {vol_cut_pct}%\n"
            f"- Mandated Next Session RPE Cap: RPE {rpe_cap}\n"
        )
    else:
        deload_block = "[DELOAD STATUS]: INACTIVE (Normal Progression)\n"

    # 2. Format Exercise Metrics
    exercise_lines = []
    total_tonnage = 0.0
    for ex in exercise_summaries:
        vol = ex.get("volume_load", 0.0)
        total_tonnage += vol
        top_load = ex.get("top_load", 0.0)
        top_reps = ex.get("top_reps", 0)
        hist_rpe = ex.get("top_rpe", 8.0)
        action = ex.get("action", "hold")
        curr_e1rm = ex.get("current_e1rm")
        e1rm_delta = ex.get("e1rm_delta", 0.0)

        e1rm_str = f"{curr_e1rm:.1f} kg (Delta: {e1rm_delta:+.1f} kg)" if curr_e1rm else "N/A"
        
        target_directive = "Advance load (+2.5 kg)" if action == "increase" else "Hold load; build reps"
        if is_deload:
            target_directive = f"DELOAD: Reduce sets, cap at RPE {fatigue_info.get('intensity_cap_rpe', 7.0)}"

        exercise_lines.append(
            f"- {ex['name']}:\n"
            f"  * Logged Set: {top_load} kg x {top_reps} reps @ historical RPE {hist_rpe}\n"
            f"  * Calculated e1RM: {e1rm_str}\n"
            f"  * Programmed Action: {action.upper()} -> Next Directive: {target_directive}"
        )

    telemetry_payload = (
        f"{deload_block}\n"
        f"[SESSION TELEMETRY]\n"
        f"- Split: {split_name}\n"
        f"- Logged Readiness: {readiness}/5\n"
        f"- Total Volume Load: {total_tonnage:,.1f} kg\n"
        f"- Trainee Notes: {session_notes or 'None'}\n\n"
        f"[EXERCISE PERFORMANCE]\n" + "\n".join(exercise_lines)
    )

    deltas_block = format_overload_deltas(exercise_summaries)
    fatigue_block = format_fatigue_cns_check(readiness, total_tonnage, session_notes)

    messages = [
        SystemMessage(content=DEBRIEF_SYSTEM_PROMPT),
        HumanMessage(content=telemetry_payload),
    ]

    raw_directives = llm.invoke(messages).content
    cleaned_directives = scrub_coach_output(raw_directives)

    final_output = (
        f"**Overload Deltas**:\n{deltas_block}\n\n"
        f"**Fatigue & CNS Check**:\n{fatigue_block}\n\n"
        f"{cleaned_directives}"
    )
    return final_output
