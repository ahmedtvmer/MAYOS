"""FastAPI application factory. Single-replica service (local GGUF + SQLite)."""

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from database.storage import storage_status
from service.model_limits import ModelLimitExceeded
from service.model_metering import record_model_usage
from svc.dependencies import AccountDeletedError
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
    recovery,
    workouts,
)
from svc.schemas import HealthOut

logger = logging.getLogger(__name__)

_ready = {"model": False, "catalog": False, "storage": False, "draining": False}


class RedactResetTokenFilter(logging.Filter):
    """Redacts a ``token=…`` query value from log records.

    Installed on ``uvicorn.access`` so the reset link's single-use token never
    lands in access logs, regardless of the uvicorn CLI flags a deployment uses
    (ADR 037). Applies to the message template and to every string argument, so
    both pre-rendered and arg-formatted records are covered.
    """

    _TOKEN_QUERY = re.compile(r"(?i)(token=)[^&\s\"']+")

    @classmethod
    def _redact(cls, value: object) -> object:
        return cls._TOKEN_QUERY.sub(r"\1[REDACTED]", value) if isinstance(value, str) else value

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(self._redact(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: self._redact(value) for key, value in record.args.items()}
        return True


def _install_access_log_redaction() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(existing, RedactResetTokenFilter) for existing in access_logger.filters):
        access_logger.addFilter(RedactResetTokenFilter())


_install_access_log_redaction()


def _register_model_metering() -> None:
    """Wires the metering sink once at startup (utils must not import service).

    The LangChain callback in ``utils.model_metering`` records every model call
    through this sink; until it is registered the callback is a no-op (ADR 038).
    """
    from utils import model_metering

    model_metering.set_recorder(record_model_usage)

DEFAULT_ALERT_SWEEP_INTERVAL_SECONDS = 3600.0


def _alert_sweep_interval_seconds() -> float:
    """The in-process sweep cadence; ``MAYOS_ALERT_SWEEP_INTERVAL_SECONDS=0`` disables it."""
    raw = os.getenv("MAYOS_ALERT_SWEEP_INTERVAL_SECONDS", str(DEFAULT_ALERT_SWEEP_INTERVAL_SECONDS))
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid MAYOS_ALERT_SWEEP_INTERVAL_SECONDS=%r; using the default.", raw)
        return DEFAULT_ALERT_SWEEP_INTERVAL_SECONDS


async def _alert_sweep_loop(db: object, interval_seconds: float) -> None:
    """Runs the alert sweep once at startup, then every interval, until cancelled.

    Evaluations are idempotent and due-ness is computed per player-local day, so
    an hourly cadence is sufficient (ADR 030/031).
    """
    from service.alert_sweep import run_sweep

    while True:
        try:
            await asyncio.to_thread(run_sweep, db)
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
            db = DatabaseManager()
            # The app owns the one store; requests receive it via get_db.
            app.state.db = db
            # Complete any deletion whose catalog transaction did not finish, so
            # a crash cannot leave a half-deleted account (ADR 015/039).
            await asyncio.to_thread(db.replay_deletions)
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
        sweep_task = asyncio.create_task(_alert_sweep_loop(app.state.db, interval_seconds))
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
    app.state.db = None
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    _register_model_metering()

    @app.exception_handler(ModelLimitExceeded)
    async def model_limit_handler(request: Request, exc: ModelLimitExceeded):
        """One 429 shape for every per-account model limit refusal (ADR 038)."""
        return JSONResponse(status_code=429, content={"detail": exc.detail})

    @app.exception_handler(AccountDeletedError)
    async def account_deleted_handler(request: Request, exc: AccountDeletedError):
        """A machine-readable 401 so a device can tell a deleted account from expiry (ADR 039).

        Disclosed only to a holder of a validly signed token for that account
        (the signature is verified before this is raised), so it reveals nothing
        to an unauthenticated caller.
        """
        return JSONResponse(status_code=401, content={"error": "account_deleted"})

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
    app.include_router(recovery.router)
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
