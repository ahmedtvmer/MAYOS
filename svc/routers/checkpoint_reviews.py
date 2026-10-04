"""Player reads for computed Checkpoint reviews (#221)."""

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from service import analytics
from service import checkpoint_reviews as checkpoint_reviews_service
from svc.dependencies import get_db, get_ledger, get_verified_player
from svc.llm import register_ai_analytics_background_tasks
from svc.schemas import CheckpointReviewListItemOut, CheckpointReviewOut

router = APIRouter(tags=["checkpoint reviews"])


@router.get("/checkpoint-reviews", response_model=list[CheckpointReviewListItemOut])
async def list_player_checkpoint_reviews(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    return await asyncio.to_thread(
        checkpoint_reviews_service.list_checkpoint_reviews, db, str(player), ledger
    )


@router.get("/checkpoint-reviews/{checkpoint}", response_model=CheckpointReviewOut)
async def read_player_checkpoint_review(
    request: Request,
    background_tasks: BackgroundTasks,
    checkpoint: int,
    player: Annotated[Any, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
):
    register_ai_analytics_background_tasks(request, background_tasks)
    review = await asyncio.to_thread(
        checkpoint_reviews_service.read_checkpoint_review,
        db,
        str(player),
        checkpoint,
        account_id=player.account_id,
        opened_at=datetime.now(UTC).isoformat(),
        client=analytics.client_context(request),
        background_tasks=background_tasks,
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Checkpoint review not found.")
    return review
