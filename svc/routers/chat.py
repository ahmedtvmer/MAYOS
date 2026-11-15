"""Dialogue history and assistant turns.

JSON responses for now; todo 8 upgrades ``POST /chat/messages`` to SSE
without changing the persisted contract.
"""

import asyncio
import json
import logging
import queue
import threading
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from agent.assistant_graph import stream_assistant_turn
from agent.prompts import DEFAULT_ASSISTANT_STYLE
from service import analytics, programs as programs_service
from service import chat as chat_service
from service.program_analytics import ProgramAnalyticsActor
from service.messages import chat_error_message
from service.model_limits import ModelAdmissionContext, admit_model_request
from service.inference_metrics import log_turn_exception, record_failure
from svc.dependencies import account_id_of, get_db, get_ledger, get_verified_player
from svc.llm import (
    InferenceScope,
    InferenceTurnState,
    bound_stream,
    inference_turn,
    register_ai_analytics_background_tasks,
)
from svc.rate_limit import CHAT_LIMIT, limiter
from svc.schemas import (
    AssistantPreferenceOut,
    AssistantPreferenceUpdateIn,
    ChatMessageIn,
    ChatProgramEditDecisionIn,
)
from utils.text_scrubber import PIPELINE_ERROR_RESPONSE

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


def _stream_error_payload() -> dict[str, Any]:
    return {"detail": PIPELINE_ERROR_RESPONSE, **chat_error_message(PIPELINE_ERROR_RESPONSE)}


@router.post("/program-edit-previews/decision")
async def decide_program_edit_preview(
    body: ChatProgramEditDecisionIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    from service.chat_program_edit import resolve_chat_program_edit

    result = await asyncio.to_thread(
        resolve_chat_program_edit, db, ledger, account_id_of(player), body.preview_id,
        confirm=body.confirm, include_optional=body.include_optional,
    )
    if result.get("error") == "preview_expired":
        raise HTTPException(status_code=409, detail="Program edit preview expired.")
    if result.get("error") == "program_changed":
        raise HTTPException(status_code=409, detail="Program changed since preview.")
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result.get("message", "Program edit failed."))
    return {"cancelled": bool(result.get("cancelled")), "version": result.get("version")}


@router.get("/history")
async def read_history(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    return await asyncio.to_thread(
        chat_service.get_history, db, str(player), ledger,
        player_account_id=account_id_of(player),
    )


@router.delete("/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_history(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    await asyncio.to_thread(chat_service.clear_history, db, str(player), ledger)
    return None


@router.get("/preferences", response_model=list[AssistantPreferenceOut])
async def read_preferences(
    ledger: Annotated[Any, Depends(get_ledger)],
):
    return await asyncio.to_thread(ledger.list_assistant_preferences)


@router.put("/preferences/{preference_id}", response_model=AssistantPreferenceOut)
async def update_preference(
    preference_id: str,
    body: AssistantPreferenceUpdateIn,
    ledger: Annotated[Any, Depends(get_ledger)],
):
    try:
        preference = await asyncio.to_thread(
            ledger.update_assistant_preference, preference_id, body.text
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if preference is None:
        raise HTTPException(status_code=404, detail="Assistant preference not found.")
    return preference


@router.delete("/preferences/{preference_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preference(
    preference_id: str,
    ledger: Annotated[Any, Depends(get_ledger)],
):
    deleted = await asyncio.to_thread(ledger.delete_assistant_preference, preference_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Assistant preference not found.")


def _run_turn(
    db: Any,
    player: Any,
    content: str,
    out: "queue.Queue[tuple[str, Any]]",
    account_id: str,
    scope: InferenceScope,
    turn: InferenceTurnState,
    disconnected: threading.Event,
    worker_done: threading.Event,
) -> None:
    """Executes the sync turn on a worker thread, bridging chunks into the queue.

    The worker owns its ledger handle lifetime: it opens one for the duration of
    the turn, so a client disconnect that closes the request handle can never
    close the connection mid-write, and the assistant reply is still persisted.
    Gate-then-mount holds: the request dependency already ran the registry and
    revocation gate, and ``open_ledger`` repeats the deleted-ledger refusal.

    The route already admitted this account for one request, so the stream is
    admitted with ``admit=False`` (it still runs under the account/role usage
    context, so every model call in the turn is attributed). The worker threads
    the same explicit ledger handle through the assistant graph's run config.
    """
    try:
        with inference_turn(scope, state=turn, wait_for=worker_done):
            with db.open_ledger(str(player)) as ledger:
                profile = ledger.get_player_profile() or {}
                history = chat_service.prepare_user_turn(db, content, ledger)
                tail = chat_service.build_tail_messages(history)
                state = chat_service.build_turn_state(
                    str(player),
                    tail,
                    coach_tone=profile.get("coach_tone", DEFAULT_ASSISTANT_STYLE),
                    custom_instructions=profile.get("custom_instructions", ""),
                    player_account_id=account_id,
                )
                for piece in bound_stream(
                    stream_assistant_turn,
                    state,
                    ledger=ledger,
                    store=db,
                    status_callback=lambda status_text: out.put(("status", status_text)),
                    scope=scope,
                ):
                    delivered = threading.Event()
                    out.put(("token", (piece, delivered)))
                    while not delivered.wait(timeout=0.1):
                        if disconnected.is_set():
                            break
                if state.get("pipeline_error"):
                    turn.mark_error()
                    out.put(("error", _stream_error_payload()))
                    return
                chat_service.persist_assistant_message(ledger, state.get("response_content"))
                if disconnected.is_set():
                    turn.mark_interrupted()
                else:
                    turn.mark_answer_completed(state.get("response_content"))
                change = state.get("program_change")
                persisted = ledger.get_active_program() if change else None
                if change and persisted is not None:
                    programs_service.record_program_change(
                        ProgramAnalyticsActor(account_id, "player"),
                        change,
                        persisted,
                        client=scope.client,
                    )
        if disconnected.is_set():
            turn.mark_interrupted()
        allowance = None
        if turn.answer_outcome == "completed":
            from service.ai_allowance import get_lifter_allowance, lifter_plan

            allowance = get_lifter_allowance(
                db, account_id, lifter_plan(db, account_id)
            )
        done_payload = {
            "response_content": state.get("response_content") or "",
            "program_updated": bool(state.get("program_updated")),
            "movement_restrictions_updated": bool(state.get("movement_restrictions_updated")),
            "outcome": turn.answer_outcome,
        }
        if allowance is not None:
            done_payload["lifter_allowance"] = allowance
        if state.get("request_suggestion") is not None:
            done_payload["request_suggestion"] = state["request_suggestion"]
        if state.get("program_edit_preview") is not None:
            done_payload["program_edit_preview"] = state["program_edit_preview"]
        # Serialize on the worker so invalid tool payloads use the same logged
        # error path as generation/persistence failures, before a done is sent.
        done_frame = json.dumps({"done": True, **done_payload}, allow_nan=False)
        out.put(("done", done_frame))
    except Exception as exc:
        log_turn_exception(logger, "Assistant stream worker failed", exc, request_id=turn.turn_id)
        record_failure(exc)
        turn.mark_error()
        if disconnected.is_set():
            turn.mark_interrupted()
        out.put(("error", _stream_error_payload()))
    finally:
        worker_done.set()
        out.put(("end", None))


@router.post("/messages")
@limiter.limit(CHAT_LIMIT)
async def post_message(
    request: Request,
    background_tasks: BackgroundTasks,
    body: ChatMessageIn,
    player: Annotated[Any, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
):
    register_ai_analytics_background_tasks(request, background_tasks)
    account_id = account_id_of(player)
    # Refuse before the stream starts so the app-wide handler can return a
    # structured JSON 429 before any SSE response begins.
    client = analytics.client_context(request)
    scope = InferenceScope(
        account_id=account_id,
        role="player",
        purpose="chat",
        admit=False,
        store=db,
        client=client,
    )
    from service.ai_allowance import launch_allowances_enabled

    admit_model_request(
        account_id,
        guard=False,
        db=db,
        context=ModelAdmissionContext(
            role="player",
            client=client,
            background_tasks=background_tasks,
            skip_daily_token_limit=launch_allowances_enabled(),
        ),
    )
    turn = InferenceTurnState(scope)
    from service.ai_allowance import admit_lifter_turn

    turn.allowance_reserved = admit_lifter_turn(
        db, account_id, turn.turn_id, scope.purpose
    )

    out: "queue.Queue[tuple[str, Any]]" = queue.Queue()
    disconnected = threading.Event()
    worker_done = threading.Event()
    background_tasks.add_task(turn.emit_after, worker_done)
    worker = threading.Thread(
        target=_run_turn,
        args=(db, player, body.content, out, account_id, scope, turn, disconnected, worker_done),
        daemon=True,
    )
    worker.start()

    async def event_stream():
        try:
            while True:
                kind, payload = await asyncio.to_thread(out.get)
                if kind == "end":
                    break
                if await request.is_disconnected():
                    disconnected.set()
                    break
                if kind == "token":
                    token_text, delivered = payload
                    try:
                        yield f"data: {json.dumps({'token': token_text})}\n\n"
                    finally:
                        delivered.set()
                elif kind == "status":
                    yield f"event: status\ndata: {json.dumps({'status': payload})}\n\n"
                elif kind == "done":
                    yield f"data: {payload}\n\n"
                elif kind == "error":
                    yield f"event: error\ndata: {json.dumps(payload)}\n\n"
        except Exception as exc:
            log_turn_exception(logger, "Assistant SSE delivery failed", exc, request_id=turn.turn_id)
            turn.mark_error()
            disconnected.set()
            yield f"event: error\ndata: {json.dumps(_stream_error_payload())}\n\n"
        finally:
            if not worker_done.is_set():
                disconnected.set()
                turn.mark_interrupted()

    return StreamingResponse(event_stream(), media_type="text/event-stream", background=background_tasks)
