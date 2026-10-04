"""Optional coach AI assistant for one selected player (issue #45, ADR 049).

``POST /coach/assignments/{assignment_id}/assistant`` runs behind the same two
gates as every other coach route — the live coach capability and an active,
owned assignment (ADR 025) — plus the feature gate: with the feature off the
route answers 404 and no model is built or called. The exchange itself is
never persisted; only the ADR 038 metering rows are written (role ``coach``).
"""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from service import analytics
from service import coach_ai as coach_ai_service
from service import coach_history as coach_history_service
from svc.dependencies import VerifiedPlayer, get_current_coach, get_db
from svc.llm import register_ai_analytics_background_tasks
from svc.rate_limit import COACH_ASSISTANT_LIMIT, limiter
from svc.schemas import CoachAssistantIn, CoachAssistantOut

router = APIRouter(prefix="/coach/assignments", tags=["coach"])


@router.post("/{assignment_id}/assistant", response_model=CoachAssistantOut)
@limiter.limit(COACH_ASSISTANT_LIMIT)
async def coach_assistant(
    request: Request,
    background_tasks: BackgroundTasks,
    assignment_id: str,
    body: CoachAssistantIn,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    """Answers one coach question about one assigned player from telemetry only.

    The feature gate answers 404 before anything is read or called; a revoked,
    unknown, or other-coach assignment denies with the same generic 403 as the
    rest of the coach surface, and the per-account model limits (ADR 038) are
    enforced at the inference entry with role ``coach``.
    """
    register_ai_analytics_background_tasks(request, background_tasks)
    if not coach_ai_service.coach_ai_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Coach AI is not available."
        )

    def _run():
        result = coach_ai_service.ask(
            db,
            coach.account_id,
            assignment_id,
            body.question,
            [turn.model_dump() for turn in body.history],
            client=analytics.client_context(request),
            background_tasks=background_tasks,
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=coach_history_service.DENIED_ERROR,
            )
        return result

    return CoachAssistantOut(**await asyncio.to_thread(_run))
