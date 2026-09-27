"""Workout prescription, session commit, and ledger export."""

import asyncio
import io
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse

from service import sessions as sessions_service
from service import workouts as workouts_service
from svc.dependencies import account_id_of, bind_request, get_current_trainee, get_db
from svc.schemas import SessionCommitIn, SessionPerformedDateCorrectIn, SessionPerformedDateCorrectOut

router = APIRouter(prefix="/workouts", tags=["workouts"])

EXPORT_MEDIA_TYPES = {"csv": "text/csv", "json": "application/json"}


def _day_plan(db: Any, player: str, day_order: int) -> Any:
    program = db.get_active_program()
    if program is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active program.")
    try:
        return workouts_service.day_plan_from(program, day_order)
    except workouts_service.DayPlanNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _sets_payload(db: Any, body: SessionCommitIn) -> list[dict[str, Any]]:
    payload = []
    for item in body.sets:
        exercise_id = item.exercise.exercise_id
        if db.get_exercise_catalog_entry(exercise_id) is None:
            raise workouts_service.SessionSyncValidationError(f"Unknown exercise id: {exercise_id}.")
        payload.append(
            {
                "exercise": item.exercise,
                "sets": [s.model_dump() for s in item.sets],
                "previous_perf": db.get_last_performance(exercise_id),
            }
        )
    return payload


@router.get("/exercises")
async def search_exercises(
    query: str,
    player: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    """Catalog exercises matching ``query``, for picking a real unplanned exercise (#34)."""

    def _run():
        bind_request(db, player)
        return {"exercises": db.find_exercises_by_name(query, limit=10)}

    return await asyncio.to_thread(_run)


@router.get("/exercises/{exercise_id}")
async def read_exercise_catalog_detail(
    exercise_id: str,
    player: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    """One catalog exercise for the read-only exercise-detail view (#53).

    Returns name, category (= body_part in the source data), body_part,
    equipment, primary + secondary muscles, instructions, and the stored media
    paths. The media paths are exposed so the client can gate display behind its
    build-time media flag; no media is bundled or served by this endpoint.
    """

    def _run():
        bind_request(db, player)
        detail = db.get_exercise_catalog_detail(exercise_id)
        if detail is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown exercise id.")
        return detail

    return await asyncio.to_thread(_run)


@router.get("/prescription")
async def read_prescription(
    day_order: int,
    trainee: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        bind_request(db, trainee)
        return workouts_service.build_prescription(db, trainee, _day_plan(db, trainee, day_order))

    return await asyncio.to_thread(_run)


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def commit_session(
    body: SessionCommitIn,
    player: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run() -> workouts_service.CommitOutcome:
        bind_request(db, player)
        if body.client_session_id is None:
            # Legacy online-only contract, unchanged.
            day_plan = _day_plan(db, player, body.day_order)
            return workouts_service.commit_session(
                db, player, day_plan, body.readiness, body.session_notes, _sets_payload(db, body),
                account_id=account_id_of(player),
            )

        try:
            uuid.UUID(body.client_session_id)
        except (AttributeError, TypeError, ValueError):
            raise workouts_service.SessionSyncValidationError("client_session_id must be a UUID.") from None

        # ADR 033: an existing commit replays its exact stored response before
        # any mutable catalog, day, or program validation, and writes nothing.
        # The player's ledger is already bound and authenticated above, so a
        # foreign client session id is never visible here.
        replayed = workouts_service.committed_session(db, body.client_session_id)
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
        )
        return workouts_service.commit_logged_session(
            db,
            player,
            body.day_order,
            body.readiness,
            body.session_notes,
            _sets_payload(db, body),
            sync=sync,
            account_id=account_id_of(player),
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
            content={"error": "program_version_mismatch", "active_version": exc.active_version},
        )

    if not result.created:
        return JSONResponse(status_code=status.HTTP_200_OK, content=result.body)
    return result.body


@router.get("/sessions/latest")
async def read_latest_session(
    player: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    """The player's most recent committed session, or 404 when none (#53).

    Home uses this to derive the next program day: the session carries the day
    name (``split_name``) written at commit, and ``day_order`` when the ledger
    stores one. It is a read-only identity lookup, scoped to the player's own
    ledger.
    """

    def _run():
        bind_request(db, player)
        return db.get_latest_committed_session()

    result = await asyncio.to_thread(_run)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No committed sessions.",
        )
    return result


@router.get("/sessions/by-client-id/{client_session_id}")
async def read_session_by_client_id(
    client_session_id: str,
    player: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    """The stored commit response for a client session id, or 404 when never committed.

    The idempotency record itself is immutable (ADR 033), but this read reflects
    the session's live state: a performed-date correction (ADR 035) is overlaid so
    the client's reconciliation view shows the corrected date and history.
    """

    def _run():
        bind_request(db, player)
        commit = db.get_session_commit(client_session_id)
        if commit is None:
            return None
        body = json.loads(commit["response_json"])
        return workouts_service.session_state(db, body.get("session_id"), body)

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
    session_id: str,
    body: SessionPerformedDateCorrectIn,
    player: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    """Corrects a recent committed session's performed date (ADR 020/035).

    Only the player's own ledger is bound, so another player's session id is a
    404. A session older than the three-day correction window is a 409; an
    invalid or out-of-window date is a 400. Correcting to the current date is an
    idempotent no-op. A successful correction re-runs the missed-day attendance
    evaluation so affected alerts reflect the corrected history.
    """

    def _run():
        result = workouts_service.correct_performed_date(
            db,
            player,
            session_id,
            body.performed_date,
            account_id=account_id_of(player),
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


async def _stream_session_log(trainee: str, db: Any, fmt: str) -> StreamingResponse:
    def _run():
        bind_request(db, trainee)
        return sessions_service.export_session_log(db, trainee, fmt)

    result = await asyncio.to_thread(_run)
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
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    return await _stream_session_log(trainee, db, "csv")


@router.get("/sessions/export.json")
async def export_sessions_json(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    return await _stream_session_log(trainee, db, "json")
