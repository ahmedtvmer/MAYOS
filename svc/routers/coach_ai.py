"""Optional coach AI assistant for one selected player (issue #45, ADR 049).

``POST /coach/assignments/{assignment_id}/assistant`` runs behind the same two
gates as every other coach route — the live coach capability and an active,
owned assignment (ADR 025) — plus the feature gate: with the feature off the
route answers 404 and no model is built or called. Refusals (404, 403, 429) are
plain HTTP answers sent before the SSE stream starts; the answer itself streams
in the player-chat wire format (#396). The exchange itself is never persisted;
only the ADR 038 metering rows are written (role ``coach``).
"""

import asyncio
import json
import queue
import threading
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from fastapi.responses import StreamingResponse

from service import analytics
from service import coach_ai as coach_ai_service
from service import coach_history as coach_history_service
from service.messages import MessageMetadata, chat_error_message
from service.model_limits import ModelAdmissionContext, admit_model_request
from svc.dependencies import VerifiedPlayer, account_id_of, get_current_coach, get_db
from svc.errors import message_http_exception
from svc.llm import (
    InferenceScope,
    InferenceTurnState,
    bound_stream,
    inference_turn,
    register_ai_analytics_background_tasks,
)
from svc.rate_limit import COACH_ASSISTANT_LIMIT, limiter
from svc.schemas import CoachAssistantIn
from utils.text_scrubber import PIPELINE_ERROR_RESPONSE

router = APIRouter(prefix="/coach/assignments", tags=["coach"])


@dataclass(frozen=True)
class _CoachAssistantRequest:
    request: Request
    background_tasks: BackgroundTasks
    assignment_id: str
    body: CoachAssistantIn
    coach: VerifiedPlayer
    db: Any


@dataclass
class _CoachAssistantStream:
    request: Request
    background_tasks: BackgroundTasks
    messages: list[Any]
    scope: InferenceScope
    turn: InferenceTurnState = field(init=False)
    events: "queue.Queue[tuple[str, Any]]" = field(default_factory=queue.Queue)
    disconnected: threading.Event = field(default_factory=threading.Event)
    worker_done: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        self.turn = InferenceTurnState(self.scope)


async def _prepare_stream(endpoint: _CoachAssistantRequest) -> _CoachAssistantStream:
    register_ai_analytics_background_tasks(endpoint.request, endpoint.background_tasks)
    if not coach_ai_service.coach_ai_enabled():
        raise message_http_exception(
            status.HTTP_404_NOT_FOUND,
            "Coach AI is not available.",
            MessageMetadata("coach.ai_unavailable.v1"),
        )

    account_id = account_id_of(endpoint.coach)
    client = analytics.client_context(endpoint.request)
    messages = await _load_assignment_messages(endpoint, account_id)
    scope = _coach_inference_scope(endpoint.db, account_id, client)
    _admit_coach_turn(endpoint, account_id, client)
    return _CoachAssistantStream(
        endpoint.request, endpoint.background_tasks, messages, scope
    )


async def _load_assignment_messages(
    endpoint: _CoachAssistantRequest, account_id: str
) -> list[Any]:
    prompt = coach_ai_service.AssistantPrompt(
        endpoint.body.question,
        [turn.model_dump() for turn in endpoint.body.history],
    )
    messages = await asyncio.to_thread(
        coach_ai_service.prepare_messages,
        endpoint.db,
        account_id,
        endpoint.assignment_id,
        prompt,
    )
    if messages is None:
        raise message_http_exception(
            status.HTTP_403_FORBIDDEN,
            coach_history_service.DENIED_ERROR,
            MessageMetadata("assignment.none_active.v1"),
        )
    return messages


def _coach_inference_scope(db: Any, account_id: str, client: Any) -> InferenceScope:
    return InferenceScope(
        account_id=account_id,
        role="coach",
        purpose="coach_assistant",
        admit=False,
        store=db,
        client=client,
    )


def _admit_coach_turn(
    endpoint: _CoachAssistantRequest, account_id: str, client: Any
) -> None:
    admit_model_request(
        account_id,
        guard=False,
        db=endpoint.db,
        context=ModelAdmissionContext(
            role="coach", client=client, background_tasks=endpoint.background_tasks
        ),
    )


def _consume_model_stream(stream: _CoachAssistantStream) -> str:
    answer: str | None = None
    with inference_turn(stream.scope, state=stream.turn, wait_for=stream.worker_done):
        for kind, payload in bound_stream(
            coach_ai_service.stream_answer, stream.messages, scope=stream.scope
        ):
            if kind == "token":
                stream.events.put(("token", payload))
            elif kind == "done":
                answer = payload
    if answer is None:
        raise RuntimeError("Coach assistant stream ended without a final answer.")
    return answer


def _run_stream_turn(stream: _CoachAssistantStream) -> None:
    try:
        answer = _consume_model_stream(stream)
        if stream.disconnected.is_set():
            stream.turn.mark_interrupted()
        stream.events.put(("done", answer))
    except Exception:
        if stream.disconnected.is_set():
            stream.turn.mark_interrupted()
        stream.events.put(("error", _stream_error_payload()))
    finally:
        stream.worker_done.set()
        stream.events.put(("end", None))


def _stream_error_payload() -> dict[str, Any]:
    return {
        "detail": PIPELINE_ERROR_RESPONSE,
        **chat_error_message(PIPELINE_ERROR_RESPONSE),
    }


def _sse_frame(kind: str, payload: Any) -> str:
    if kind == "token":
        return f"data: {json.dumps({'token': payload})}\n\n"
    if kind == "done":
        return f"data: {json.dumps({'done': True, 'answer': payload})}\n\n"
    return f"event: error\ndata: {json.dumps(payload)}\n\n"


async def _event_stream(stream: _CoachAssistantStream):
    try:
        while True:
            kind, payload = await asyncio.to_thread(stream.events.get)
            if kind == "end":
                break
            if await stream.request.is_disconnected():
                stream.disconnected.set()
                break
            yield _sse_frame(kind, payload)
    finally:
        if not stream.worker_done.is_set():
            stream.disconnected.set()
            stream.turn.mark_interrupted()


def _start_stream(stream: _CoachAssistantStream) -> StreamingResponse:
    stream.background_tasks.add_task(stream.turn.emit_after, stream.worker_done)
    threading.Thread(target=_run_stream_turn, args=(stream,), daemon=True).start()
    return StreamingResponse(
        _event_stream(stream), media_type="text/event-stream", background=stream.background_tasks
    )


@router.post("/{assignment_id}/assistant")
@limiter.limit(COACH_ASSISTANT_LIMIT)
async def coach_assistant(
    request: Request,
    background_tasks: BackgroundTasks,
    assignment_id: str,
    body: CoachAssistantIn,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Returns refusals before SSE starts, otherwise streams the answer."""
    endpoint = _CoachAssistantRequest(
        request, background_tasks, assignment_id, body, coach, db
    )
    return _start_stream(await _prepare_stream(endpoint))
