import os
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_ollama import ChatOllama

load_dotenv()
llm = ChatOllama(
    model=os.getenv("LLM", "qwen2.5:3b"),
    temperature=0.0,
    num_ctx=4096
)
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
    exercise_summaries: List[Dict[str, Any]],
    profile: Dict[str, Any],
    total_tonnage: Optional[float] = None,
    total_sets: Optional[int] = None
) -> str:
    """
    Summarizes session telemetry and invokes the local LLM to generate
    a structured post-workout debriefing aligned with user persona directives.
    """
    coach_tone = profile.get("coach_tone", "Direct, grounded, and pragmatic")
    raw_instructions = profile.get("custom_instructions", "").strip()
    custom_rules = f"Trainee Guardrails: {raw_instructions}" if raw_instructions else ""

    # 1. Resolve Session Volume & Sets safely
    if total_tonnage is not None:
        total_volume_kg = float(total_tonnage)
    else:
        total_volume_kg = sum(ex.get("volume_load", 0.0) for ex in exercise_summaries)

    if total_sets is not None:
        total_work_sets = int(total_sets)
    else:
        total_work_sets = sum(ex.get("sets_completed", 0) for ex in exercise_summaries)

    graduated_exercises = [ex["name"] for ex in exercise_summaries if ex.get("action") == "increase"]
    holding_exercises = [ex["name"] for ex in exercise_summaries if ex.get("action") == "hold"]

    # 2. Inject Volume Metrics into Telemetry Lines
    telemetry_lines = [
        f"- **Split**: {split_name}",
        f"- **Readiness (1-5)**: {readiness}",
        f"- **Session Output**: {total_work_sets} hard working sets | Total Volume Load: {total_volume_kg:,.1f} kg",
        f"- **Graduated Exercises**: {', '.join(graduated_exercises) if graduated_exercises else 'None (Consolidating)'}",
        f"- **Holding / Working in Rep Corridor**: {', '.join(holding_exercises) if holding_exercises else 'None'}",
        f"- **Trainee Notes**: {session_notes if session_notes else 'None logged'}\n",
        "**Movement Performance Details**:"
    ]

    for ex in exercise_summaries:
        e1rm_val = ex.get("current_e1rm")
        e1rm_delta = ex.get("e1rm_delta")
        if e1rm_val is not None:
            e1rm_str = f" | e1RM: {e1rm_val} kg" + (f" ({e1rm_delta:+} kg)" if e1rm_delta is not None else "")
        else:
            e1rm_str = ""

        action_str = f" | Status: {ex.get('action', 'RECORDED').upper()}" if "action" in ex else ""

        telemetry_lines.append(
            f"  * {ex['name']}: Top Set {ex.get('top_load', 0.0)}kg × {ex.get('top_reps', 0)} @ RPE {ex.get('top_rpe', 8.5)}"
            f"{e1rm_str}{action_str}"
        )

    telemetry_payload = "\n".join(telemetry_lines)

    system_prompt = DEBRIEF_SYSTEM_TEMPLATE.format(
        coach_tone=coach_tone,
        custom_instructions=custom_rules
    )

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=(
                    f"Analyze this completed session and critique the total volume output ({total_volume_kg:,.1f} kg across {total_work_sets} sets) "
                    f"relative to the trainee's readiness score:\n\n{telemetry_payload}"
                )
            )
        ])
        return response.content
    except Exception as e:
        # 3. Fallback volume injection
        return (
            f"**Session Logged Successfully.**\n\n"
            f"- **Session Output**: {total_work_sets} working sets | **Total Volume Load**: {total_volume_kg:,.1f} kg\n"
            f"- **Graduated Movements**: {', '.join(graduated_exercises) if graduated_exercises else 'None'}\n"
            f"*(Automated debrief generation failed: {e})*"
        )