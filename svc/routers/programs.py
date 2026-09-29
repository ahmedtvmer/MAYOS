"""Program generation, retrieval, and Excel export."""

import asyncio
import io
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from agent.ProgramState import GeneratedProgramSchema
from agent.program_generator import generate_program_pipeline
from service import programs as programs_service
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
    ProgramGenerateIn,
    ProgramSubstitutionIn,
    ProgramSubstitutionOut,
    ProgramSubstitutionUndoIn,
)

router = APIRouter(prefix="/programs", tags=["programs"])


def _raise_substitution_error(substitution: dict[str, Any]) -> None:
    code = substitution["code"]
    http_status = {
        SubstitutionErrorCode.COACH_CONTROLLED: status.HTTP_403_FORBIDDEN,
        SubstitutionErrorCode.NO_ACTIVE_PROGRAM: status.HTTP_404_NOT_FOUND,
        SubstitutionErrorCode.RESTORE_VERSION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
        SubstitutionErrorCode.REPLACEMENT_NOT_FOUND: status.HTTP_404_NOT_FOUND,
        SubstitutionErrorCode.PROGRAM_CHANGED: status.HTTP_409_CONFLICT,
    }.get(code, status.HTTP_400_BAD_REQUEST)
    raise HTTPException(status_code=http_status, detail=substitution["error"])


@router.post("/generate", response_model=GeneratedProgramSchema)
async def generate_program(
    body: ProgramGenerateIn,
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        account_id = account_id_of(player)
        if not programs_service.player_controls_program(db, ledger, account_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=programs_service.COACH_CONTROLLED_ERROR
            )
        try:
            program, _ = run_inference_sync(
                generate_program_pipeline,
                user_split_override=body.user_split_override,
                rep_preference_override=body.rep_preference_override,
                frequency_override=body.frequency_override,
                ledger=ledger,
                scope=InferenceScope(
                    account_id=account_id, role="player", purpose="program_generate", store=db
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return program

    return await asyncio.to_thread(_run)


@router.get("/active", response_model=GeneratedProgramSchema | None)
async def read_active_program(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        account_id = account_id_of(player)
        # Reads that return a saved program never call the model, so they are
        # attributed but not admitted; any synthesizing call is still metered.
        return run_inference_sync(
            programs_service.ensure_active_program,
            db,
            str(player),
            player_account_id=account_id,
            ledger=ledger,
            scope=InferenceScope(
                account_id=account_id, role="player", purpose="program_active", admit=False, store=db
            ),
        )

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
        )
        if "code" in substitution:
            _raise_substitution_error(substitution)
        return substitution

    return await asyncio.to_thread(_run)


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
        )
        if "code" in restoration:
            _raise_substitution_error(restoration)
        return restoration

    return await asyncio.to_thread(_run)


@router.get("/active.xlsx")
async def export_active_program(
    player: Annotated[Any, Depends(get_verified_player)],
    ledger: Annotated[Any, Depends(get_ledger)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        result = programs_service.export_active_program(db, str(player), ledger=ledger)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active program.")
        return result

    filename, payload = await asyncio.to_thread(_run)
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
