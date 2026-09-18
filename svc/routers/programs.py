"""Program generation, retrieval, and Excel export."""

import asyncio
import io
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from agent.ProgramState import GeneratedProgramSchema
from agent.program_generator import generate_program_pipeline
from service import programs as programs_service
from svc.dependencies import bind_request, get_current_trainee, get_db
from svc.schemas import ProgramGenerateIn

router = APIRouter(prefix="/programs", tags=["programs"])


@router.post("/generate", response_model=GeneratedProgramSchema)
async def generate_program(
    body: ProgramGenerateIn,
    trainee: Annotated[str, Depends(get_current_trainee)],
    db: Annotated[Any, Depends(get_db)],
):
    def _run():
        bind_request(db, trainee)
        try:
            program, _ = generate_program_pipeline(
                user_split_override=body.user_split_override,
                rep_preference_override=body.rep_preference_override,
                frequency_override=body.frequency_override,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return program

    return await asyncio.to_thread(_run)


@router.get("/active", response_model=GeneratedProgramSchema | None)
async def read_active_program(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    def _run():
        bind_request(db, trainee)
        return programs_service.ensure_active_program(db, trainee)

    return await asyncio.to_thread(_run)


@router.get("/active.xlsx")
async def export_active_program(
    trainee: Annotated[str, Depends(get_current_trainee)], db: Annotated[Any, Depends(get_db)]
):
    def _run():
        bind_request(db, trainee)
        result = programs_service.export_active_program(db, trainee)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active program.")
        return result

    filename, payload = await asyncio.to_thread(_run)
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
