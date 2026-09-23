"""Onboarding intake steps over the onboarding graph."""

from typing import Any

from langchain_core.messages import HumanMessage

from service._base import bind_user


def start_onboarding(db: Any, trainee_id: str) -> dict[str, Any]:
    from agent.onboarding_graph import onboarding_graph
    from svc.llm import run_inference_sync

    clean_id = bind_user(db, trainee_id)
    state = {"messages": [], "trainee_id": clean_id, "intake_step": 1, "is_complete": False, "profile_data": None}
    return run_inference_sync(onboarding_graph.invoke, state)


def answer_intake(db: Any, trainee_id: str, state: dict[str, Any], user_input: str) -> dict[str, Any]:
    from agent.onboarding_graph import onboarding_graph
    from svc.llm import run_inference_sync

    clean_id = bind_user(db, trainee_id)
    state["messages"].append(HumanMessage(content=user_input))
    state["trainee_id"] = clean_id
    output = run_inference_sync(onboarding_graph.invoke, state)
    state.update(output)
    return state


def complete_onboarding(db: Any, trainee_id: str, state: dict[str, Any]) -> dict[str, Any]:
    from agent.program_generator import generate_program_pipeline

    from service.programs import ensure_active_program

    clean_id = bind_user(db, trainee_id)
    program = ensure_active_program(db, clean_id) or generate_program_pipeline()[0]
    db.add_chat_message(
        "assistant",
        f"Welcome! I have calibrated your active routine: **{program.program_name}** "
        f"({program.weekly_frequency} days/week). Inspect your split in **Program & Dashboard**, "
        "log your work in **Active Workout Logger**, or query me here.",
    )
    return {"program": program, "state": state}
