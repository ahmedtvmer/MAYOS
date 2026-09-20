"""FastAPI application factory. Single-replica service (local GGUF + SQLite)."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from svc.rate_limit import limiter
from svc.routers import auth, chat, dashboard, media, onboarding, profile, programs, workouts
from svc.schemas import HealthOut

logger = logging.getLogger(__name__)

_ready = {"model": False, "catalog": False, "draining": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from database.database_manager import DatabaseManager
    from svc.llm import warmup_llm

    if os.getenv("SKIP_LLM_LOAD") == "true":
        logger.info("SKIP_LLM_LOAD set; skipping catalog init and LLM warmup (unit-test mode).")
        _ready["catalog"] = True
    else:
        try:
            DatabaseManager()
            _ready["catalog"] = True
        except Exception:
            logger.exception("Catalog initialization failed during lifespan startup")
        try:
            await warmup_llm()
            _ready["model"] = True
        except Exception:
            logger.exception("LLM warmup failed during lifespan startup")
    logger.info("Lifespan startup complete (model=%s catalog=%s).", _ready["model"], _ready["catalog"])
    yield
    _ready["draining"] = True
    from svc.llm import unload_all

    await asyncio.to_thread(unload_all)
    logger.info("Lifespan shutdown complete.")


def create_app() -> FastAPI:
    app = FastAPI(title="Mayos Training Engine", version="2.0.0", lifespan=lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    ui_origin = os.getenv("UI_BASE_URL", "http://localhost:8501")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ui_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=502, content={"detail": "Request failed. Please try again."})

    app.include_router(auth.router)
    app.include_router(media.router)
    app.include_router(profile.router)
    app.include_router(programs.router)
    app.include_router(onboarding.router)
    app.include_router(workouts.router)
    app.include_router(chat.router)
    app.include_router(dashboard.router)

    @app.get("/healthz", response_model=HealthOut, tags=["ops"])
    async def healthz():
        return {"status": "ok" if not _ready["draining"] else "draining", "details": dict(_ready)}

    @app.get("/readyz", response_model=HealthOut, tags=["ops"])
    async def readyz():
        if _ready["draining"] or not (_ready["model"] and _ready["catalog"]):
            return JSONResponse(status_code=503, content={"status": "not_ready", "details": dict(_ready)})
        return {"status": "ready", "details": dict(_ready)}

    return app


app = create_app()
