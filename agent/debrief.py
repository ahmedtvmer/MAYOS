from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

from utils.model_downloader import llm

load_dotenv()

DEBRIEF_SYSTEM_TEMPLATE = """You are Myos, an elite strength coach and biomechanics specialist.
Analyze the completed workout session telemetry provided by the trainee.

Tone Directive: {coach_tone}
{custom_instructions}

Directives:
1. Review progression milestones: acknowledge graduated lifts advancing next week.
2. Cross-examine readiness score vs. logged RIR/RPE and trainee notes.
3. Keep the feedback sharp, technical, and concise (under 150 words). No motivational cliches.
4. Structure the output into three concise bulleted sections:
   - **Overload Deltas**: Highlight weight/e1RM advancements.
   - **Fatigue & CNS Check**: Analyze readiness vs performance and notes.
   - **Next Session Directives**: Clear execution marching orders.
"""


def generate_session_debrief(
    split_name: str,
    readiness: int,
    session_notes: str,
    exercise_summaries: list[dict[str, Any]],
    profile: dict[str, Any],
    total_tonnage: float | None = None,
    total_sets: int | None = None,
    fatigue_info: dict[str, Any] | None = None,
) -> str:
    coach_tone = profile.get("coach_tone", "Direct, grounded, and pragmatic")
    raw_instructions = profile.get("custom_instructions", "").strip()
    custom_rules = f"Trainee Guardrails: {raw_instructions}" if raw_instructions else ""

    fatigue_instruction = ""
    if fatigue_info and fatigue_info.get("deload_recommended"):
        cut_pct = int((1.0 - fatigue_info["volume_multiplier"]) * 100)
        fatigue_instruction = (
            f"\n[CRITICAL DIRECTIVE: DELOAD ACTIVE]\n"
            f"- Deload Triggered: {fatigue_info['reason']}\n"
            f"- Prescribed Volume Cut: {cut_pct}%\n"
            f"- Mandatory Intensity Ceiling: RPE {fatigue_info['intensity_cap_rpe']}\n"
            f"Instruct the trainee to cut working sets by {cut_pct}% "
            f"and cap movements at RPE {fatigue_info['intensity_cap_rpe']} next session."
        )

    total_volume_kg = (
        float(total_tonnage)
        if total_tonnage is not None
        else sum(ex.get("volume_load", 0.0) for ex in exercise_summaries)
    )
    total_work_sets = (
        int(total_sets) if total_sets is not None else sum(ex.get("sets_completed", 0) for ex in exercise_summaries)
    )

    graduated_exercises = [ex["name"] for ex in exercise_summaries if ex.get("action") == "increase"]
    holding_exercises = [ex["name"] for ex in exercise_summaries if ex.get("action") == "hold"]

    telemetry_lines = [
        f"- **Split**: {split_name}",
        f"- **Readiness (1-5)**: {readiness}",
        f"- **Session Output**: {total_work_sets} hard working sets | Total Volume Load: {total_volume_kg:,.1f} kg",
        f"- **Graduated Exercises**: {', '.join(graduated_exercises) if graduated_exercises else 'None (Consolidating)'}",
        f"- **Holding / Working in Rep Corridor**: {', '.join(holding_exercises) if holding_exercises else 'None'}",
        f"- **Trainee Notes**: {session_notes if session_notes else 'None logged'}\n",
        f"- **Fatigue & CNS Check**: {fatigue_instruction}",
        "**Movement Performance Details**:",
    ]

    for ex in exercise_summaries:
        e1rm_val = ex.get("current_e1rm")
        e1rm_delta = ex.get("e1rm_delta")
        e1rm_str = (
            f" | e1RM: {e1rm_val} kg" + (f" ({e1rm_delta:+} kg)" if e1rm_delta is not None else "")
            if e1rm_val is not None
            else ""
        )
        action_str = f" | Status: {ex.get('action', 'RECORDED').upper()}" if "action" in ex else ""
        telemetry_lines.append(
            f"  * {ex['name']}: Top Set {ex.get('top_load', 0.0)}kg × {ex.get('top_reps', 0)} @ RPE {ex.get('top_rpe', 8.5)}{e1rm_str}{action_str}"
        )

    system_prompt = DEBRIEF_SYSTEM_TEMPLATE.format(coach_tone=coach_tone, custom_instructions=custom_rules)
    try:
        response = llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"Analyze this session relative to readiness:\n\n{chr(10).join(telemetry_lines)}"),
            ]
        )
        return response.content
    except Exception as e:
        return (
            f"**Session Logged Successfully.**\n\n"
            f"- **Session Output**: {total_work_sets} working sets | **Total Volume Load**: {total_volume_kg:,.1f} kg\n"
            f"- **Graduated Movements**: {', '.join(graduated_exercises) if graduated_exercises else 'None'}\n"
            f"*(Automated debrief generation failed: {e})*"
        )
