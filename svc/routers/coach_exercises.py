"""Owner-scoped Coach exercise creation and search."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from database.registry.coach_exercises import CoachExerciseCreate
from svc.dependencies import VerifiedPlayer, get_current_coach, get_db
from svc.schemas import CoachExerciseCreateIn, CoachExerciseOut, CoachExerciseSearchOut

router = APIRouter(prefix="/coach/exercises", tags=["coach"])


def _search_exercise_entries(
    db: Any, coach_account_id: str, query: str
) -> dict[str, list[dict[str, Any]]]:
    library = db.find_exercises_by_name(query, limit=10)
    owned = db.search_coach_exercises(coach_account_id, query, limit=10)
    return {
        "exercises": [
            *({**exercise, "is_coach_exercise": False} for exercise in library),
            *owned,
        ]
    }


@router.get("", response_model=CoachExerciseSearchOut)
async def search_coach_exercises(
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
    query: str = Query(min_length=1, max_length=120),
):
    """Search Exercise library rows alongside this Coach's own exercises."""
    return await asyncio.to_thread(
        _search_exercise_entries, db, coach.account_id, query
    )


@router.post("", response_model=CoachExerciseOut, status_code=status.HTTP_201_CREATED)
async def create_coach_exercise(
    body: CoachExerciseCreateIn,
    coach: Annotated[VerifiedPlayer, Depends(get_current_coach)],
    db: Annotated[Any, Depends(get_db)],
):
    fields = CoachExerciseCreate(**body.model_dump())
    exercise = await asyncio.to_thread(
        db.create_coach_exercise, coach.account_id, fields
    )
    return CoachExerciseOut(**exercise)
