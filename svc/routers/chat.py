"""Dialogue history and assistant turns.

JSON responses for now; todo 8 upgrades ``POST /chat/messages`` to SSE
without changing the persisted contract.
"""

import asyncio
import json
import queue
import threading
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from agent.assistant_graph import stream_assistant_turn
from service import chat as chat_service
from service.model_limits import admit_model_request
from svc.dependencies import account_id_of, get_db, get_ledger, get_verified_player
from svc.llm import InferenceScope, bound_stream
from svc.rate_limit import CHAT_LIMIT, limiter
from svc.schemas import ChatMessageIn
from utils.text_scrubber import PIPELINE_ERROR_RESPONSE

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/history")
async def read_history(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    return await asyncio.to_thread(chat_service.get_history, db, str(player), ledger)


@router.delete("/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_history(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    await asyncio.to_thread(chat_service.clear_history, db, str(player), ledger)
    return None


def _run_turn(
    db: Any,
    player: Any,
    content: str,
    out: "queue.Queue[tuple[str, Any]]",
    account_id: str | None = None,
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
        with db.open_ledger(str(player)) as ledger:
            profile = ledger.get_player_profile() or {}
            history = chat_service.prepare_user_turn(db, content, ledger)
            tail = chat_service.build_tail_messages(history)
            state = chat_service.build_turn_state(
                str(player),
                tail,
                coach_tone=profile.get("coach_tone", "Direct, grounded, and pragmatic"),
                custom_instructions=profile.get("custom_instructions", ""),
                player_account_id=account_id_of(player),
            )
            for piece in bound_stream(
                stream_assistant_turn,
                state,
                ledger=ledger,
                store=db,
                scope=InferenceScope(
                    account_id=account_id, role="player", purpose="chat", admit=False, store=db
                ),
            ):
                out.put(("token", piece))
            chat_service.persist_assistant_message(ledger, state.get("response_content"))
        out.put(("done", {"response_content": state.get("response_content") or "", "program_updated": bool(state.get("program_updated"))}))
    except Exception:
        out.put(("error", {"detail": PIPELINE_ERROR_RESPONSE}))
    finally:
        out.put(("end", None))


@router.post("/messages")
@limiter.limit(CHAT_LIMIT)
async def post_message(
    request: Request,
    body: ChatMessageIn,
    player: Annotated[Any, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
):
    account_id = account_id_of(player)
    # Refuse before the stream starts: the app-wide ModelLimitExceeded handler
    # returns a plain HTTP 429 with a JSON ``detail`` (surfaced verbatim by the
    # mobile client, ADR 036/038).
    admit_model_request(account_id, guard=False, db=db)

    out: "queue.Queue[tuple[str, Any]]" = queue.Queue()
    worker = threading.Thread(
        target=_run_turn, args=(db, player, body.content, out, account_id), daemon=True
    )
    worker.start()

    async def event_stream():
        while True:
            kind, payload = await asyncio.to_thread(out.get)
            if kind == "end":
                break
            if await request.is_disconnected():
                break
            if kind == "token":
                yield f"data: {json.dumps({'token': payload})}\n\n"
            elif kind == "done":
                yield f"data: {json.dumps({'done': True, **payload})}\n\n"
            elif kind == "error":
                yield f"event: error\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
