"""Registration and login. Issues JWTs; trainee proof level is unchanged (ID possession)."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from service import auth as auth_service
from svc.auth import create_access_token
from svc.dependencies import get_db
from svc.rate_limit import REGISTER_LIMIT, LOGIN_LIMIT, limiter
from svc.schemas import TokenOut, TraineeIn

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(REGISTER_LIMIT)
async def register(request: Request, body: TraineeIn, db: Annotated[Any, Depends(get_db)]):
    def _run():
        result = auth_service.register_trainee(db, body.trainee_id)
        if not result["ok"]:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result["error"])
        return result["trainee_id"]

    trainee_id = await asyncio.to_thread(_run)
    return TokenOut(access_token=create_access_token(trainee_id), trainee_id=trainee_id)


@router.post("/login", response_model=TokenOut)
@limiter.limit(LOGIN_LIMIT)
async def login(request: Request, body: TraineeIn, db: Annotated[Any, Depends(get_db)]):
    def _run():
        result = auth_service.login_trainee(db, body.trainee_id)
        if not result["ok"]:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["error"])
        return result

    result = await asyncio.to_thread(_run)
    return TokenOut(access_token=create_access_token(result["trainee_id"]), trainee_id=result["trainee_id"])
