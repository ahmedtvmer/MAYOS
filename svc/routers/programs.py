"""Program generation, retrieval, and editing."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from service import analytics, programs as programs_service
from service.program_analytics import ProgramAnalyticsActor
from service.program_substitution import (
    ProgramSubstitution,
    ProgramSubstitutionUndo,
    SubstitutionErrorCode,
    substitute_active_program_exercise as substitute_active_program_exercise_service,
    undo_active_program_substitution,
)
from svc.dependencies import account_id_of, get_db, get_ledger, get_verified_player
from svc.llm import InferenceScope, run_inference_sync
from svc.rate_limit import PROGRAM_MUTATE_LIMIT, limiter
from svc.schemas import (
    ActiveProgramOut,
    ProgramGenerateIn,
    ProgramSubstitutionIn,
    ProgramSubstitutionOut,
    ProgramSubstitutionUndoIn,
)

router = APIRouter(prefix="/programs", tags=["programs"])


def _substitution_error_response(substitution: dict[str, Any]) -> JSONResponse:
    code = substitution["code"]
    http_status = {
        SubstitutionErrorCode.COACH_CONTROLLED: status.HTTP_403_FORBIDDEN,
        SubstitutionErrorCode.NO_ACTIVE_PROGRAM: status.HTTP_404_NOT_FOUND,
        SubstitutionErrorCode.RESTORE_VERSION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
        SubstitutionErrorCode.REPLACEMENT_NOT_FOUND: status.HTTP_404_NOT_FOUND,
        SubstitutionErrorCode.PROGRAM_CHANGED: status.HTTP_409_CONFLICT,
    }.get(code, status.HTTP_400_BAD_REQUEST)
    return JSONResponse(
        status_code=http_status,
        content={"detail": substitution["error"], "code": code.value},
    )


@router.post("/generate", response_model=ActiveProgramOut)
async def generate_program(
    request: Request,
    body: ProgramGenerateIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        account_id = account_id_of(player)
        if not programs_service.player_controls_program(db, ledger, account_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=programs_service.COACH_CONTROLLED_ERROR)
        try:
            program = programs_service.generate_program_version(
                db,
                ledger,
                ProgramAnalyticsActor(account_id, "player"),
                "player_request",
                user_split_override=body.user_split_override,
                rep_preference_override=body.rep_preference_override,
                frequency_override=body.frequency_override,
                client=analytics.client_context(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        result = {
            **programs_service.with_library_equipment(program, db),
            "player_controls_program": programs_service.player_controls_program(db, ledger, account_id),
        }
        return result

    return await asyncio.to_thread(_run)


@router.get("/active", response_model=ActiveProgramOut | None)
async def read_active_program(
    request: Request,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        account_id = account_id_of(player)
        # Reads that return a saved program never call the model, so they are
        # attributed but not admitted; any synthesizing call is still metered.
        program = run_inference_sync(
            programs_service.ensure_active_program,
            db,
            str(player),
            player_account_id=account_id,
            ledger=ledger,
            client=analytics.client_context(request),
            scope=InferenceScope(account_id=account_id, role="player", purpose="program_active", admit=False, store=db),
        )
        if program is None:
            return None
        result = {
            **programs_service.with_library_equipment(program, db),
            "player_controls_program": programs_service.player_controls_program(db, ledger, account_id),
        }
        return result

    return await asyncio.to_thread(_run)


@router.post("/active/substitutions", response_model=ProgramSubstitutionOut)
@limiter.limit(PROGRAM_MUTATE_LIMIT)
async def substitute_active_program_exercise(
    request: Request,
    body: ProgramSubstitutionIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Permanently swaps one slot (or all occurrences) and returns the new version."""

    def _run():
        substitution = substitute_active_program_exercise_service(
            db,
            ledger,
            account_id_of(player),
            ProgramSubstitution(
                day_name=body.day_name,
                exercise_id=body.exercise_id,
                replacement_exercise_id=body.replacement_exercise_id,
                all_occurrences=body.all_occurrences,
                expected_active_version=body.expected_active_version,
            ),
            actor=ProgramAnalyticsActor(account_id_of(player), "player"),
            client=analytics.client_context(request),
        )
        if "code" in substitution:
            return substitution
        substitution["player_controls_program"] = programs_service.player_controls_program(
            db, ledger, account_id_of(player)
        )
        substitution = programs_service.with_library_equipment(substitution, db)
        return substitution

    substitution = await asyncio.to_thread(_run)
    if "code" in substitution:
        return _substitution_error_response(substitution)
    return substitution


@router.post("/active/substitutions/undo", response_model=ProgramSubstitutionOut)
@limiter.limit(PROGRAM_MUTATE_LIMIT)
async def undo_active_program_exercise_substitution(
    request: Request,
    body: ProgramSubstitutionUndoIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    """Restore an exact earlier program snapshot as a new version."""

    def _run():
        restoration = undo_active_program_substitution(
            db,
            ledger,
            account_id_of(player),
            ProgramSubstitutionUndo(
                restore_version=body.restore_version,
                expected_active_version=body.expected_active_version,
            ),
            actor=ProgramAnalyticsActor(account_id_of(player), "player"),
            client=analytics.client_context(request),
        )
        if "code" in restoration:
            return restoration
        restoration["player_controls_program"] = programs_service.player_controls_program(
            db, ledger, account_id_of(player)
        )
        restoration = programs_service.with_library_equipment(restoration, db)
        return restoration

    restoration = await asyncio.to_thread(_run)
    if "code" in restoration:
        return _substitution_error_response(restoration)
    return restoration
