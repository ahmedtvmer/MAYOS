"""Workout prescription, session commit, and ledger export."""

import asyncio
import io
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from database.exercise_resolution import resolve_exercise_display_row
from database.exercise_library.filters import exercise_filters_for
from service import analytics
from service import sessions as sessions_service
from service import workouts as workouts_service
from service import workout_analytics
from service.messages import MessageMetadata, program_version_mismatch_message
from svc.dependencies import account_id_of, get_db, get_ledger, get_verified_player
from svc.errors import message_http_exception
from svc.rate_limit import WORKOUT_SYNC_FAILURE_LIMIT, limiter
from svc.schemas import (
    BaselinesOut,
    PlayerLatestSessionOut,
    SessionCommitIn,
    SessionPerformedDateCorrectIn,
    SessionPerformedDateCorrectOut,
    WorkoutSyncFailureIn,
)
from utils.equipment_access import COMMERCIAL_GYM, map_equipment_access

router = APIRouter(prefix="/workouts", tags=["workouts"])

EXPORT_MEDIA_TYPES = {"csv": "text/csv", "json": "application/json"}


def _day_plan(ledger: Any, day_order: int) -> Any:
    program = ledger.get_active_program()
    if program is None:
        raise message_http_exception(
            status.HTTP_404_NOT_FOUND,
            "No active program.",
            MessageMetadata("program.no_active.v1"),
        )
    try:
        return workouts_service.day_plan_from(program, day_order)
    except workouts_service.DayPlanNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _prescribed_exercise_ids(ledger: Any, program_version: int | None) -> set[str]:
    program = (
        ledger.get_program_by_version(program_version)
        if program_version is not None
        else ledger.get_active_program()
    )
    if program is None:
        if program_version is not None:
            active_program = ledger.get_active_program()
            raise workouts_service.ProgramVersionMismatchError(
                active_program.version if active_program is not None else None
            )
        return set()
    return {
        str(exercise.exercise_id)
        for day in program.days
        for exercise in day.exercises
    }


def _sets_payload(db: Any, ledger: Any, body: SessionCommitIn) -> list[dict[str, Any]]:
    payload = []
    prescribed_ids = _prescribed_exercise_ids(ledger, body.program_version)
    for item in body.sets:
        exercise_id = item.exercise.exercise_id
        exercise = resolve_exercise_display_row(db, exercise_id)
        if exercise is None or (
            exercise.get("is_coach_exercise") and exercise_id not in prescribed_ids
        ):
            raise workouts_service.SessionSyncValidationError(f"Unknown exercise id: {exercise_id}.")
        payload.append(
            {
                "exercise": item.exercise,
                "sets": [s.model_dump() for s in item.sets],
                "previous_perf": ledger.get_last_performance(exercise_id),
            }
        )
    return payload


def _warmup_movements_payload(db: Any, body: SessionCommitIn) -> list[dict[str, Any]]:
    movements = []
    for movement in body.warmup_movements:
        payload = movement.model_dump()
        entry = (
            db.get_exercise_library_entry(movement.exercise_id)
            if movement.exercise_id
            else None
        )
        if movement.exercise_id and entry is None:
            payload["exercise_id"] = None
        if movement.equipment is not None:
            payload["equipment"] = entry.get("equipment") if entry is not None else None
        else:
            payload.pop("equipment", None)
        movements.append(payload)
    return movements


@router.get("/exercises")
async def search_exercises(
    player: Annotated[Any, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
    ledger: Annotated[Any, Depends(get_ledger)],
    query: str | None = None,
    target_muscle: str | None = None,
    primary_muscle: list[str] | None = Query(None),
    primary_action: list[str] | None = Query(None),
):
    """Search the Exercise library by name, target muscle or curated filters.

    A filter-only browse returns all matching rows in display-name order and
    applies the player's Equipment access. Name searches remain limited to 10
    and ignore Equipment access, matching the existing Replace browse behavior.
    """
    try:
        filters = exercise_filters_for(primary_muscle, primary_action)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not (query or target_muscle or filters.has_curated_filters):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Provide query, target_muscle, primary_muscle, primary_action, "
                "or a combination."
            ),
        )
    filter_browse = bool(
        (target_muscle or filters.has_curated_filters) and not (query or "").strip()
    )
    # Replace filter-only browsing is unbounded so it never drops matching rows.
    limit = None if filter_browse else 10
    equipment_access = None
    if filter_browse:
        equipment_access = map_equipment_access(
            (ledger.get_player_profile() or {}).get("equipment_access", COMMERCIAL_GYM)
        )
    exercises = db.find_exercises_by_name(
        query or "",
        limit=limit,
        target_muscle=target_muscle,
        equipment_access=equipment_access,
        filter_browse=filter_browse,
        filters=filters,
    )
    return {
        # Filter-only browsing suggests options; typed searches stay bounded.
        "exercises": exercises,
    }


@router.get("/exercises/{exercise_id}")
async def read_exercise_library_detail(
    exercise_id: str,
    player: Annotated[Any, Depends(get_verified_player)],
    db: Annotated[Any, Depends(get_db)],
):
    """One catalog exercise for the read-only exercise-detail view (#53).

    Returns name, category (= body_part in the source data), body_part,
    equipment, curated Primary muscle and actions, source primary + secondary muscles,
    instructions, and stored media paths. The client gates media display behind
    its build-time media flag; this endpoint does not serve media.
    """
    detail = db.get_exercise_library_detail(exercise_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown exercise id.")
    return detail


@router.get("/prescription")
async def read_prescription(
    day_order: int,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        return workouts_service.build_prescription(
            db,
            str(player),
            _day_plan(ledger, day_order),
            ledger=ledger,
            player_account_id=player.account_id,
        )

    return await asyncio.to_thread(_run)


@router.get("/baselines", response_model=BaselinesOut)
async def read_baselines(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Exercise baselines for the device's live personal-record checks (#122, ADR 042).

    One row per exercise the player has committed a working set for, carrying
    the exercise-wide aggregates the commit comparison uses plus the working
    sets of the most recent committed session (``last_session``, effort as
    RIR or null). Scoped to the caller's own ledger.
    """
    return await asyncio.to_thread(workouts_service.baselines, db, str(player), ledger=ledger)


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def commit_session(
    request: Request,
    body: SessionCommitIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run() -> workouts_service.CommitOutcome:
        if body.client_session_id is None:
            # Legacy online-only contract, unchanged.
            day_plan = _day_plan(ledger, body.day_order)
            return workouts_service.commit_session(
                db, str(player), day_plan, body.readiness, body.session_notes,
                _sets_payload(db, ledger, body),
                warmup_movements=_warmup_movements_payload(db, body),
                cardio=body.cardio.model_dump() if body.cardio is not None else None,
                account_id=account_id_of(player), ledger=ledger,
                client=analytics.client_context(request),
            )

        try:
            uuid.UUID(body.client_session_id)
        except (AttributeError, TypeError, ValueError):
            raise workouts_service.SessionSyncValidationError("client_session_id must be a UUID.") from None

        # ADR 033: an existing commit replays its exact stored response before
        # any mutable catalog, day, or program validation, and writes nothing.
        replayed = workouts_service.committed_session(ledger, body.client_session_id)
        if replayed is not None:
            return replayed

        if body.program_version is None:
            raise workouts_service.SessionSyncValidationError("program_version is required.")
        workouts_service.validate_sync_fields(
            body.performed_date, body.performed_timezone, body.captured_at
        )

        sync = workouts_service.SyncMetadata(
            client_session_id=body.client_session_id,
            performed_date=body.performed_date,
            performed_timezone=body.performed_timezone,
            program_version=body.program_version,
            captured_at=body.captured_at,
            captured_offline=body.captured_offline,
        )
        return workouts_service.commit_logged_session(
            db,
            str(player),
            body.day_order,
            body.readiness,
            body.session_notes,
            _sets_payload(db, ledger, body),
            sync=sync,
            warmup_movements=_warmup_movements_payload(db, body),
            cardio=body.cardio.model_dump() if body.cardio is not None else None,
            account_id=account_id_of(player),
            ledger=ledger,
            client=analytics.client_context(request),
        )

    try:
        result = await asyncio.to_thread(_run)
    except workouts_service.SessionSyncValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except workouts_service.DayPlanNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except workouts_service.ProgramVersionMismatchError as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "program_version_mismatch",
                "active_version": exc.active_version,
                **program_version_mismatch_message(),
            },
        )

    if not result.created:
        return JSONResponse(status_code=status.HTTP_200_OK, content=result.body)
    return result.body


@router.post("/sync-failures", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(WORKOUT_SYNC_FAILURE_LIMIT)
async def report_sync_failure(
    request: Request,
    body: WorkoutSyncFailureIn,
    player: Annotated[Any, Depends(get_verified_player)],
):
    workout_analytics.report_sync_failure(
        account_id_of(player),
        body.reason_code,
        body.attempt,
        client=analytics.client_context(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions/latest", response_model=PlayerLatestSessionOut)
async def read_latest_session(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
):
    """The player's most recent committed session, or 404 when none (#53).

    Home uses this to derive the next program day: the session carries the day
    name (``split_name``) written at commit, and ``day_order`` when the ledger
    stores one. It is a read-only identity lookup, scoped to the player's own
    ledger.
    """
    result = await asyncio.to_thread(ledger.get_latest_committed_session)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No committed sessions.",
        )
    return result


@router.get("/sessions/by-client-id/{client_session_id}")
async def read_session_by_client_id(
    client_session_id: str,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
):
    """The stored commit response for a client session id, or 404 when never committed.

    The idempotency record itself is immutable (ADR 033), but this read reflects
    the session's live state: a performed-date correction (ADR 035) is overlaid so
    the client's reconciliation view shows the corrected date and history.
    """

    def _run():
        commit = ledger.get_session_commit(client_session_id)
        if commit is None:
            return None
        body = json.loads(commit["response_json"])
        return workouts_service.session_state(
            None, str(player), body.get("session_id"), body, ledger=ledger
        )

    result = await asyncio.to_thread(_run)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No committed session for this client session id.",
        )
    return result


@router.patch(
    "/sessions/{session_id}/performed-date",
    response_model=SessionPerformedDateCorrectOut,
)
async def correct_session_performed_date(
    request: Request,
    session_id: str,
    body: SessionPerformedDateCorrectIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Corrects a recent committed session's performed date (ADR 020/035).

    Only the player's own ledger is opened, so another player's session id is a
    404. A session older than the three-day correction window is a 409; an
    invalid or out-of-window date is a 400. Correcting to the current date is an
    idempotent no-op. A successful correction re-runs the missed-day attendance
    evaluation so affected alerts reflect the corrected history.
    """

    def _run():
        result = workouts_service.correct_performed_date(
            db,
            str(player),
            session_id,
            body.performed_date,
            account_id=account_id_of(player),
            ledger=ledger,
            client=analytics.client_context(request),
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No such session.",
            )
        return result

    try:
        return await asyncio.to_thread(_run)
    except workouts_service.SessionSyncValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except workouts_service.SessionCorrectionNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


async def _stream_session_log(player: str, db: Any, ledger: Any, fmt: str) -> StreamingResponse:
    result = await asyncio.to_thread(sessions_service.export_session_log, db, player, fmt, ledger)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No sessions logged yet.")
    filename, payload = result
    return StreamingResponse(
        io.BytesIO(payload),
        media_type=EXPORT_MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/sessions/export.csv")
async def export_sessions_csv(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    return await _stream_session_log(str(player), db, ledger, "csv")


@router.get("/sessions/export.json")
async def export_sessions_json(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    return await _stream_session_log(str(player), db, ledger, "json")
