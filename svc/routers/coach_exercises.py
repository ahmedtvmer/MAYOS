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
    replacing_exercise_id: str | None,
) -> dict[str, list[dict[str, Any]]]:
    filter_browse = not query and filters.has_curated_filters
    library = db.find_exercises_by_name(
        query,
        limit=None if filter_browse else 10,
        filter_browse=filter_browse,
        filters=filters,
        replacing_exercise_id=replacing_exercise_id,
    )
    owned = (
        []
        if filters.excludes_coach_exercises
        else db.search_coach_exercises(
            coach_account_id,
            query,
            limit=None if filter_browse else 10,
            equipment_categories=filters.equipment_categories,
        )
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
    equipment_category: list[str] | None = Query(None),
    load_type: list[str] | None = Query(None),
    replacing_exercise_id: str | None = None,
):
    """Search library rows; filter-only browsing ranks against an optional replacement.

    Coach exercises match Equipment category through their Equipment tag and are
    omitted when a Primary muscle, Primary action, or Load type filter is active.
    """
    try:
        filters = exercise_filters_for(
            primary_muscle, primary_action, load_type, equipment_category
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    clean_query = (query or "").strip()
    if not clean_query and not filters.has_curated_filters:
        raise HTTPException(
            status_code=400,
            detail=(
                "Provide query, primary_muscle, primary_action, equipment_category, "
                "load_type, or a combination."
            ),
        )
    return await asyncio.to_thread(
        _search_exercise_entries,
        db,
        coach.account_id,
        clean_query,
        filters,
        replacing_exercise_id,
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
