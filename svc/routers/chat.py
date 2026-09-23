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
from svc.dependencies import bind_request, get_current_trainee, get_db
from svc.llm import bound_stream
from svc.rate_limit import CHAT_LIMIT, limiter
from svc.schemas import ChatMessageIn
from utils.text_scrubber import PIPELINE_ERROR_RESPONSE

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/history")
async def read_history(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    def _run():
        bind_request(db, trainee)
        return chat_service.get_history(db, trainee)

    return await asyncio.to_thread(_run)


@router.delete("/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_history(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    def _run():
        bind_request(db, trainee)
        chat_service.clear_history(db, trainee)

    await asyncio.to_thread(_run)
    return None


def _run_turn(db: Any, trainee: str, content: str, out: "queue.Queue[tuple[str, Any]]") -> None:
    """Executes the sync turn on a worker thread, bridging chunks into the queue."""
    try:
        bind_request(db, trainee)
        profile = db.get_user_profile() or {}
        history = db.get_chat_history()
        db.add_chat_message("user", content)
        tail = chat_service.build_tail_messages(history + [{"role": "user", "content": content}])
        state = chat_service.build_turn_state(
            db,
            trainee,
            tail,
            coach_tone=profile.get("coach_tone", "Direct, grounded, and pragmatic"),
            custom_instructions=profile.get("custom_instructions", ""),
        )
        for piece in bound_stream(stream_assistant_turn, state):
            out.put(("token", piece))
        chat_service.persist_assistant_message(db, state.get("response_content"))
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
    trainee: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    out: "queue.Queue[tuple[str, Any]]" = queue.Queue()
    worker = threading.Thread(target=_run_turn, args=(db, trainee, body.content, out), daemon=True)
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
