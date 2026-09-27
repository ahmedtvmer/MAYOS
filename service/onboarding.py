"""Onboarding intake steps over the onboarding graph."""

from typing import Any

from langchain_core.messages import HumanMessage


def _graph_config(db: Any, ledger: Any) -> dict[str, Any]:
    """Carries the explicit ledger/store on the LangGraph run config (ADR 041)."""
    return {"configurable": {"ledger": ledger, "store": db}}


def start_onboarding(
    db: Any, ledger_id: str, player_account_id: str | None = None, ledger: Any | None = None
) -> dict[str, Any]:
    from agent.onboarding_graph import onboarding_graph
    from service._base import ledger_scope
    from svc.llm import InferenceScope, run_inference_sync

    clean_id = db._sanitize_username(ledger_id)
    with ledger_scope(db, ledger, clean_id) as handle:
        state = {"messages": [], "trainee_id": clean_id, "intake_step": 1, "is_complete": False, "profile_data": None}
        return run_inference_sync(
            onboarding_graph.invoke,
            state,
            config=_graph_config(db, handle),
            scope=InferenceScope(
                account_id=player_account_id, role="player", purpose="onboarding", store=db
            ),
        )


def answer_intake(
    db: Any,
    ledger_id: str,
    state: dict[str, Any],
    user_input: str,
    player_account_id: str | None = None,
    ledger: Any | None = None,
) -> dict[str, Any]:
    from agent.onboarding_graph import onboarding_graph
    from service._base import ledger_scope
    from svc.llm import InferenceScope, run_inference_sync

    clean_id = db._sanitize_username(ledger_id)
    with ledger_scope(db, ledger, clean_id) as handle:
        state["messages"].append(HumanMessage(content=user_input))
        state["trainee_id"] = clean_id
        output = run_inference_sync(
            onboarding_graph.invoke,
            state,
            config=_graph_config(db, handle),
            scope=InferenceScope(
                account_id=player_account_id, role="player", purpose="onboarding", store=db
            ),
        )
        state.update(output)
        return state


def complete_onboarding(
    db: Any,
    ledger_id: str,
    state: dict[str, Any],
    player_account_id: str | None = None,
    ledger: Any | None = None,
) -> dict[str, Any]:
    from agent.program_generator import generate_program_pipeline
    from svc.llm import InferenceScope, run_inference_sync

    from service.programs import COACH_CONTROLLED_ERROR, ensure_active_program, player_controls_program

    from service._base import ledger_scope

    with ledger_scope(db, ledger, ledger_id) as ledger:
        clean_id = ledger.ledger_id

        def _resolve_program():
            resolved = ensure_active_program(db, clean_id, player_account_id=player_account_id, ledger=ledger)
            if resolved is None and player_controls_program(db, ledger, player_account_id):
                resolved = generate_program_pipeline(ledger=ledger)[0]
            return resolved

        program = run_inference_sync(
            _resolve_program,
            scope=InferenceScope(
                account_id=player_account_id, role="player", purpose="onboarding_complete", store=db
            ),
        )
        if program is None:
            ledger.add_chat_message("assistant", f"Welcome! {COACH_CONTROLLED_ERROR}")
            return {"program": None, "state": state, "program_message": COACH_CONTROLLED_ERROR}
        ledger.add_chat_message(
            "assistant",
            f"Welcome! I have calibrated your active routine: **{program.program_name}** "
            f"({program.weekly_frequency} days/week). Inspect your split in **Program & Dashboard**, "
            "log your work in **Active Workout Logger**, or query me here.",
        )
        return {"program": program, "state": state}
