"""Owner-scoped Coach exercise creation and search."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from database.exercise_library.filters import ExerciseFilters, exercise_filters_for
from database.registry.coach_exercises import CoachExerciseCreate
from svc.dependencies import VerifiedPlayer, get_current_coach, get_db
from svc.schemas import CoachExerciseCreateIn, CoachExerciseOut, CoachExerciseSearchOut

router = APIRouter(prefix="/coach/exercises", tags=["coach"])


def _search_exercise_entries(
    db: Any,
    coach_account_id: str,
    query: str,
    filters: ExerciseFilters,
) -> dict[str, list[dict[str, Any]]]:
    filter_browse = not query and filters.has_curated_filters
    library = db.find_exercises_by_name(
        query,
        limit=None if filter_browse else 10,
        filter_browse=filter_browse,
        filters=filters,
    )
    owned = (
        []
        if filters.has_curated_filters
        else db.search_coach_exercises(coach_account_id, query, limit=10)
    )
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
    query: str | None = Query(default=None, max_length=120),
    primary_muscle: list[str] | None = Query(None),
    primary_action: list[str] | None = Query(None),
):
    """Search library rows; filter-only browsing is unbounded and display-name ordered.

    Coach exercises are included for name searches and omitted whenever a
    Primary muscle or Primary action filter is active.
    """
    try:
        filters = exercise_filters_for(primary_muscle, primary_action)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    clean_query = (query or "").strip()
    if not clean_query and not filters.has_curated_filters:
        raise HTTPException(
            status_code=400,
            detail="Provide query, primary_muscle, primary_action, or a combination.",
        )
    return await asyncio.to_thread(
        _search_exercise_entries, db, coach.account_id, clean_query, filters
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
