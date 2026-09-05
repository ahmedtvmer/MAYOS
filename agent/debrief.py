import os
from typing import List, Dict, Any
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_ollama import ChatOllama

load_dotenv()
llm = ChatOllama(model=os.getenv("LLM", "qwen2.5:3b"), temperature=0.2)

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
    profile: Dict[str, Any]
) -> str:
    """
    Summarizes session telemetry and invokes the local LLM to generate
    a structured post-workout debriefing aligned with user persona directives.
    """
    coach_tone = profile.get("coach_tone", "Direct, grounded, and pragmatic")
    raw_instructions = profile.get("custom_instructions", "").strip()
    custom_rules = f"Trainee Guardrails: {raw_instructions}" if raw_instructions else ""

    # Aggregate session metrics
    total_volume_kg = sum(ex["volume_load"] for ex in exercise_summaries)
    graduated_exercises = [ex["name"] for ex in exercise_summaries if ex["action"] == "increase"]
    holding_exercises = [ex["name"] for ex in exercise_summaries if ex["action"] == "hold"]

    # Format telemetry breakdown
    telemetry_lines = [
        f"- **Split**: {split_name}",
        f"- **Readiness (1-5)**: {readiness}",
        f"- **Total Volume Load**: {total_volume_kg:,.1f} kg",
        f"- **Graduated Exercises**: {', '.join(graduated_exercises) if graduated_exercises else 'None (Consolidating)'}",
        f"- **Holding / Working in Rep Corridor**: {', '.join(holding_exercises) if holding_exercises else 'None'}",
        f"- **Trainee Notes**: {session_notes if session_notes else 'None logged'}\n",
        "**Movement Performance Details**:"
    ]

    for ex in exercise_summaries:
        e1rm_str = f"{ex['current_e1rm']} kg ({ex['e1rm_delta']:+} kg)" if ex["e1rm_delta"] is not None else f"{ex['current_e1rm']} kg"
        telemetry_lines.append(
            f"  * {ex['name']}: Top Set {ex['top_load']}kg × {ex['top_reps']} @ RPE {ex['top_rpe']} | "
            f"e1RM: {e1rm_str} | Status: {ex['action'].upper()}"
        )

    telemetry_payload = "\n".join(telemetry_lines)

    system_prompt = DEBRIEF_SYSTEM_TEMPLATE.format(
        coach_tone=coach_tone,
        custom_instructions=custom_rules
    )

    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Analyze this completed session:\n\n{telemetry_payload}")
        ])
        return response.content
    except Exception as e:
        return (
            f"**Session Logged Successfully.**\n\n"
            f"- **Total Volume**: {total_volume_kg:,.1f} kg\n"
            f"- **Graduated Movements**: {', '.join(graduated_exercises) if graduated_exercises else 'None'}\n"
            f"*(Automated debrief generation failed: {e})*"
        )