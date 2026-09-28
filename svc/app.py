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
    coach_ai,
    dashboard,
    media,
    onboarding,
    profile,
    programs,
    public_pages,
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
DEFAULT_DAILY_BACKUP_INTERVAL_SECONDS = 3600.0


def _env_interval_seconds(name: str, default: float) -> float:
    """Reads a non-negative interval in seconds; malformed values use ``default``."""
    raw = os.getenv(name, str(default))
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using the default.", name, raw)
        return default


async def _periodic_loop(db: object, interval_seconds: float, step: object, label: str) -> None:
    """Runs ``step(db)`` once at startup, then every interval, until cancelled.

    One generic loop backs both the alert sweep and the daily backup. Either job
    is idempotent on its own schedule, so a restart-biased cadence only repeats a
    step that is already a no-op. A failure is logged and never stops the loop.
    """
    while True:
        try:
            await asyncio.to_thread(step, db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("%s iteration failed; the loop continues", label)
        await asyncio.sleep(interval_seconds)


async def _cancel_loop(task: asyncio.Task[None] | None, label: str) -> None:
    """Cancels a periodic loop and waits for it to exit before shutdown."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("%s loop stopped.", label)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from database.database_manager import DatabaseManager
    from database.storage import StorageNotReady, validate_data_root
    from svc.llm import warmup_llm

    _ready.update(model=False, catalog=False, storage=False, draining=False)
    sweep_task: asyncio.Task[None] | None = None
    backup_task: asyncio.Task[None] | None = None
    unit_test_mode = os.getenv("SKIP_LLM_LOAD") == "true"
    # Coach AI is opt-in: with COACH_AI_ENABLED on, a recorded passing privacy
    # and evaluation report for the current prompt version is required, or the
    # startup check logs the refusal and the feature stays off (ADR 049).
    from service.coach_ai import log_enable_gate_at_startup

    gate = log_enable_gate_at_startup()
    if gate.enabled:
        logger.info("Coach AI enabled: %s", gate.reason)
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
            # A restore is a boot-time step: the only volume-owning writer cannot
            # be scaled to zero for an offline restore, and restoring while it
            # serves is unsafe. Apply the scheduled snapshot in place (restoring
            # into this live connection) and reapply the current deletions record
            # BEFORE readiness goes green or any loop starts. On failure the
            # marker stays and we fail closed instead of serving a half-restored
            # catalog (#41, ADR 044).
            from database.backup import apply_pending_restore

            applied_restore = await asyncio.to_thread(apply_pending_restore, db)
            if applied_restore is not None:
                logger.warning("Boot-time restore applied: %s", applied_restore)
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

    loops_enabled = _ready["catalog"] and _ready["storage"] and not unit_test_mode
    # The alert sweep runs in-process; its evaluations are idempotent and due-ness
    # is per player-local day, so an hourly cadence is sufficient (ADR 030/031).
    sweep_interval = _env_interval_seconds("MAYOS_ALERT_SWEEP_INTERVAL_SECONDS", DEFAULT_ALERT_SWEEP_INTERVAL_SECONDS)
    if loops_enabled and sweep_interval > 0:
        from service.alert_sweep import run_sweep

        sweep_task = asyncio.create_task(_periodic_loop(app.state.db, sweep_interval, run_sweep, "Alert sweep"))
        logger.info("Alert sweep loop started (every %ss).", sweep_interval)

    # Daily online backups run in this same always-on API Machine, because a
    # detached Machine cannot mount /data (#41). The job creates at most one
    # snapshot per UTC day, so the default hourly cadence just retries a failed
    # day sooner. 0 disables the loop.
    backup_interval = _env_interval_seconds(
        "MAYOS_DAILY_BACKUP_INTERVAL_SECONDS", DEFAULT_DAILY_BACKUP_INTERVAL_SECONDS
    )
    if loops_enabled and backup_interval > 0:
        from database.backup import create_daily_backup

        backup_task = asyncio.create_task(
            _periodic_loop(app.state.db, backup_interval, create_daily_backup, "Daily backup")
        )
        logger.info("Daily backup loop started (every %ss).", backup_interval)

    logger.info(
        "Lifespan startup complete (model=%s catalog=%s storage=%s).",
        _ready["model"],
        _ready["catalog"],
        _ready["storage"],
    )
    yield
    _ready["draining"] = True
    await _cancel_loop(sweep_task, "Alert sweep")
    await _cancel_loop(backup_task, "Daily backup")
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
    app.include_router(public_pages.router)
    app.include_router(coach.router)
    app.include_router(coach_ai.router)
    app.include_router(assignments.coach_router)
    app.include_router(assignments.coach_roster_router)
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
