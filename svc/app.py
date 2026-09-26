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

from database.storage import storage_status
from svc.rate_limit import limiter
from svc.routers import (
    alerts,
    assignments,
    auth,
    chat,
    coach,
    dashboard,
    media,
    onboarding,
    profile,
    programs,
    workouts,
)
from svc.schemas import HealthOut

logger = logging.getLogger(__name__)

_ready = {"model": False, "catalog": False, "storage": False, "draining": False}

DEFAULT_ALERT_SWEEP_INTERVAL_SECONDS = 3600.0


def _alert_sweep_interval_seconds() -> float:
    """The in-process sweep cadence; ``MAYOS_ALERT_SWEEP_INTERVAL_SECONDS=0`` disables it."""
    raw = os.getenv("MAYOS_ALERT_SWEEP_INTERVAL_SECONDS", str(DEFAULT_ALERT_SWEEP_INTERVAL_SECONDS))
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid MAYOS_ALERT_SWEEP_INTERVAL_SECONDS=%r; using the default.", raw)
        return DEFAULT_ALERT_SWEEP_INTERVAL_SECONDS


async def _alert_sweep_loop(interval_seconds: float) -> None:
    """Runs the alert sweep once at startup, then every interval, until cancelled.

    Evaluations are idempotent and due-ness is computed per player-local day, so
    an hourly cadence is sufficient (ADR 030/031).
    """
    from database.database_manager import DatabaseManager
    from service.alert_sweep import run_sweep

    while True:
        try:
            await asyncio.to_thread(run_sweep, DatabaseManager())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Alert sweep iteration failed; the loop continues")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from database.database_manager import DatabaseManager
    from database.storage import StorageNotReady, validate_data_root
    from svc.llm import warmup_llm

    _ready.update(model=False, catalog=False, storage=False, draining=False)
    sweep_task: asyncio.Task[None] | None = None
    unit_test_mode = os.getenv("SKIP_LLM_LOAD") == "true"
    if unit_test_mode:
        logger.info("SKIP_LLM_LOAD set; skipping catalog init and LLM warmup (unit-test mode).")
        _ready["catalog"] = True
        _ready["storage"] = True
    else:
        try:
            validate_data_root()
            _ready["storage"] = True
            DatabaseManager()
            _ready["catalog"] = True
        except StorageNotReady:
            logger.exception(
                "Persistent data root is not ready; refusing to create the catalog/ledgers on ephemeral storage."
            )
        except Exception:
            logger.exception("Catalog initialization failed during lifespan startup")
        try:
            await warmup_llm()
            _ready["model"] = True
        except Exception:
            logger.exception("LLM warmup failed during lifespan startup")

    interval_seconds = _alert_sweep_interval_seconds()
    if _ready["catalog"] and _ready["storage"] and not unit_test_mode and interval_seconds > 0:
        sweep_task = asyncio.create_task(_alert_sweep_loop(interval_seconds))
        logger.info("Alert sweep loop started (every %ss).", interval_seconds)

    logger.info(
        "Lifespan startup complete (model=%s catalog=%s storage=%s).",
        _ready["model"],
        _ready["catalog"],
        _ready["storage"],
    )
    yield
    _ready["draining"] = True
    if sweep_task is not None:
        sweep_task.cancel()
        try:
            await sweep_task
        except asyncio.CancelledError:
            pass
        logger.info("Alert sweep loop stopped.")
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
    app.include_router(coach.router)
    app.include_router(assignments.coach_router)
    app.include_router(assignments.player_router)
    app.include_router(alerts.router)
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
        storage_ok, storage_detail = storage_status()
        details = {**_ready, "storage": storage_ok, "storage_detail": storage_detail}
        if _ready["draining"] or not (_ready["model"] and _ready["catalog"] and storage_ok):
            return JSONResponse(status_code=503, content={"status": "not_ready", "details": details})
        return {"status": "ready", "details": details}

    return app


app = create_app()
