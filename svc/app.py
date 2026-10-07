"""FastAPI application factory for the hosted inference service."""

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler as default_http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from database.storage import storage_status
from service.app_version import (
    ANDROID_BUILD_HEADER,
    android_store_url,
    is_web_client,
    minimum_android_build,
    parse_android_build,
)
from service.admin_auth import AdminSecurity, partial_secret_configuration
from service.messages import MessageMetadata, ai_limit_message, http_error_message
from service import account_deletion as account_deletion_service
from service.analytics import register_analytics_preference_reader, register_configured_sink
from service.model_limits import ModelLimitExceeded
from service.model_metering import record_model_usage
from service.periodic_status import (
    ALERT_SWEEP_JOB,
    DAILY_BACKUP_JOB,
    configured_interval_seconds,
    record_run,
)
from svc.dependencies import AccountDeletedError
from svc.rate_limit import limiter
from svc.routers import (
    admin,
    alerts,
    assignments,
    auth,
    chat,
    coach,
    coach_ai,
    coach_exercises,
    checkpoint_reviews,
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
REQUEST_FAILURE_DETAIL = "Request failed. Please try again."
_APP_VERSION_POLICY_EXEMPT_PATHS = frozenset(
    {
        "/healthz",
        "/readyz",
        "/privacy",
        "/account/delete-request",
        "/reset-password",
        "/.well-known/assetlinks.json",
        "/app/version-policy",
    }
)


def _android_build_policy_exempts(request: Request) -> bool:
    path = request.url.path
    return (
        request.method == "OPTIONS"
        or path in _APP_VERSION_POLICY_EXEMPT_PATHS
        or path == "/admin"
        or path.startswith("/admin/")
        or is_web_client(request.headers.get("X-MAYOS-Client"))
    )


def _app_update_required_response(min_build: int) -> JSONResponse:
    detail = "An app update is required before you can continue."
    message_fields = http_error_message(
        426,
        detail,
        message_metadata=MessageMetadata(
            code="app.update_required.v1",
            params={"min_build": min_build},
        ),
    )
    return JSONResponse(
        status_code=426,
        content={
            "error": "app_update_required",
            "detail": detail,
            "min_build": min_build,
            "store_url": android_store_url(),
            **message_fields,
        },
    )


def web_origins() -> list[str]:
    """Browser origins allowed by CORS, from comma-separated ``UI_BASE_URL``.

    Holds the web app's host (e.g. the Cloudflare Pages origin, ADR 048) and any
    local development origin. A browser's ``Origin`` never has a trailing slash,
    so one is stripped to keep a pasted URL from silently failing every request.
    """
    raw = os.getenv("UI_BASE_URL", "http://localhost:7357")
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]

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


def _error_response_parts(
    response: Response,
) -> tuple[dict[str, Any], dict[str, str]] | None:
    if response.status_code in {204, 304} or not getattr(response, "body", None):
        return None
    try:
        content = json.loads(response.body)
    except (TypeError, ValueError):
        return None
    if not isinstance(content, dict):
        return None
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() != "content-length"
    }
    return content, headers


def _add_error_metadata(
    request: Request,
    response: Response,
    message_metadata: MessageMetadata | None = None,
    validation_errors: Any = None,
) -> Response:
    """Adds structured metadata to a JSON error without changing its detail."""
    response_parts = _error_response_parts(response)
    if response_parts is None:
        return response
    content, headers = response_parts
    content.update(
        http_error_message(
            response.status_code,
            content.get("detail") or content.get("error"),
            validation_errors=validation_errors,
            message_metadata=message_metadata,
        )
    )
    return JSONResponse(
        status_code=response.status_code,
        content=content,
        headers=headers,
        background=_ai_analytics_background_tasks(request),
    )


_install_access_log_redaction()


def _register_model_metering() -> None:
    """Wires the metering sink once at startup (utils must not import service).

    The LangChain callback in ``utils.model_metering`` records every model call
    through this sink; until it is registered the callback is a no-op (ADR 038).
    """
    from utils import model_metering

    model_metering.set_recorder(record_model_usage)


async def _periodic_loop(db: object, interval_seconds: float, step: object, job: str) -> None:
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
        except Exception as exc:
            record_run(job, interval_seconds, False, type(exc).__name__)
            logger.exception("%s iteration failed; the loop continues", job)
        else:
            record_run(job, interval_seconds, True, None)
        await asyncio.sleep(interval_seconds)


def readiness_snapshot() -> tuple[str, dict[str, bool | str]]:
    """Returns the verdict and details shared by the readiness endpoint and dashboard."""
    storage_ok, storage_detail = storage_status()
    details = {**_ready, "storage": storage_ok, "storage_detail": storage_detail}
    if _ready["draining"] or not (_ready["model"] and _ready["catalog"] and storage_ok):
        return "not_ready", details
    return "ready", details


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
    from service.checkpoint_review_ai import log_enable_gate_at_startup as log_checkpoint_review_gate

    checkpoint_gate = log_checkpoint_review_gate()
    if checkpoint_gate.enabled:
        logger.info("Checkpoint review AI enabled: %s", checkpoint_gate.reason)
    if unit_test_mode:
        logger.info("SKIP_LLM_LOAD set; skipping catalog init and LLM warmup (unit-test mode).")
        _ready["catalog"] = True
        _ready["storage"] = True
    else:
        try:
            validate_data_root()
            _ready["storage"] = True
            db = DatabaseManager()
            from database.offsite_backup import configure_database_offsite_backup

            configure_database_offsite_backup(db, log_disabled=True)
            # The app owns the one store; requests receive it via get_db.
            app.state.db = db
            register_analytics_preference_reader(db.analytics_preference_allows)
            # Complete any deletion whose catalog transaction did not finish, so
            # a crash cannot leave a half-deleted account (ADR 015/039).
            await asyncio.to_thread(account_deletion_service.replay_deletions, db)
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
                account_deletion_service.capture_deletion_facts(applied_restore["deletion_facts"])
                logger.warning(
                    "Boot-time restore from %s applied; %s deletion(s) reapplied.",
                    applied_restore["snapshot"],
                    applied_restore["deletions_reapplied"],
                )
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
    sweep_interval = configured_interval_seconds(ALERT_SWEEP_JOB)
    if loops_enabled and sweep_interval > 0:
        from service.alert_sweep import run_sweep

        sweep_task = asyncio.create_task(_periodic_loop(app.state.db, sweep_interval, run_sweep, ALERT_SWEEP_JOB))
        logger.info("Alert sweep loop started (every %ss).", sweep_interval)

    # Daily online backups run in this same always-on API Machine, because a
    # detached Machine cannot mount /data (#41). The job creates at most one
    # snapshot per UTC day, so the default hourly cadence just retries a failed
    # day sooner. 0 disables the loop.
    backup_interval = configured_interval_seconds(DAILY_BACKUP_JOB)
    if loops_enabled and backup_interval > 0:
        from database.backup import create_daily_backup

        backup_task = asyncio.create_task(
            _periodic_loop(app.state.db, backup_interval, create_daily_backup, DAILY_BACKUP_JOB)
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
    await _cancel_loop(sweep_task, ALERT_SWEEP_JOB)
    await _cancel_loop(backup_task, DAILY_BACKUP_JOB)
    from svc.llm import unload_all

    await asyncio.to_thread(unload_all)
    logger.info("Lifespan shutdown complete.")


def create_app() -> FastAPI:
    app = FastAPI(title="Mayos Training Engine", version="2.0.0", lifespan=lifespan)
    app.state.limiter = limiter
    app.state.db = None
    app.state.admin_security = AdminSecurity()
    if partial_secret_configuration():
        logger.warning("Owner admin secrets are partially configured; /admin stays disabled.")
    _register_model_metering()
    register_configured_sink()

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        response = _rate_limit_exceeded_handler(request, exc)
        return _add_error_metadata(request, response)

    @app.exception_handler(ModelLimitExceeded)
    async def model_limit_handler(request: Request, exc: ModelLimitExceeded):
        """One 429 shape for every per-account model limit refusal (ADR 038)."""
        refusal = ai_limit_message(exc.kind, exc.detail)
        response = JSONResponse(status_code=429, content={"detail": exc.detail})
        return _add_error_metadata(
            request,
            response,
            MessageMetadata(
                code=refusal["message_code"],
                params=refusal["message_params"],
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        response = JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(errors)},
        )
        return _add_error_metadata(request, response, validation_errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        response = await default_http_exception_handler(request, exc)
        return _add_error_metadata(
            request,
            response,
            getattr(exc, "message_metadata", None),
        )

    @app.exception_handler(AccountDeletedError)
    async def account_deleted_handler(request: Request, exc: AccountDeletedError):
        """A machine-readable 401 so a device can tell a deleted account from expiry (ADR 039).

        Disclosed only to a holder of a validly signed token for that account
        (the signature is verified before this is raised), so it reveals nothing
        to an unauthenticated caller.
        """
        return JSONResponse(
            status_code=401,
            content={"error": "account_deleted"},
            background=_ai_analytics_background_tasks(request),
        )

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

    @app.middleware("http")
    async def secure_admin_surface(request: Request, call_next):
        path = request.url.path
        if path != "/admin" and not path.startswith("/admin/"):
            return await call_next(request)
        security = request.app.state.admin_security
        login_route = path == "/admin/login" and request.method in {"GET", "POST"}
        asset_route = path.startswith("/admin/assets/") and request.method in {"GET", "HEAD"}
        if path == "/admin/login" and not login_route:
            response = admin.not_found_response()
        elif not security.config.enabled:
            response = admin.not_found_response()
        elif asset_route:
            response = await call_next(request)
        elif not login_route and (
            not security.has_valid_session(request.cookies.get(admin.SESSION_COOKIE))
        ):
            response = admin.not_found_response()
        else:
            response = await call_next(request)
        _apply_admin_security_headers(response)
        return response

    @app.middleware("http")
    async def enforce_android_build_policy(request: Request, call_next):
        min_build = minimum_android_build()
        if min_build == 0 or _android_build_policy_exempts(request):
            return await call_next(request)
        build = parse_android_build(request.headers.get(ANDROID_BUILD_HEADER))
        if build is None or build >= min_build:
            return await call_next(request)
        return _app_update_required_response(min_build)

    # CORS wraps the build-policy middleware so browsers can read the structured
    # 426 response. Registering this last makes it the outermost user middleware.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=web_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        response = JSONResponse(
            status_code=502,
            content={"detail": REQUEST_FAILURE_DETAIL},
        )
        return _add_error_metadata(request, response)

    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(recovery.router)
    app.include_router(public_pages.router)
    app.include_router(coach.router)
    app.include_router(coach_exercises.router)
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
    app.include_router(checkpoint_reviews.router)

    @app.get("/app/version-policy", tags=["app"])
    async def app_version_policy():
        """Returns the Android minimum build and store link without authentication."""
        return {"min_build": minimum_android_build(), "store_url": android_store_url()}

    @app.get("/healthz", response_model=HealthOut, tags=["ops"])
    async def healthz():
        return {"status": "ok" if not _ready["draining"] else "draining", "details": dict(_ready)}

    @app.get("/readyz", response_model=HealthOut, tags=["ops"])
    async def readyz():
        status, details = readiness_snapshot()
        if status != "ready":
            return JSONResponse(status_code=503, content={"status": status, "details": details})
        return {"status": status, "details": details}

    return app


def _ai_analytics_background_tasks(request: Request):
    return getattr(request.state, "ai_analytics_background_tasks", None)


def _apply_admin_security_headers(response) -> None:
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    content_security_policy = response.headers.get("Content-Security-Policy")
    if content_security_policy is None:
        content_security_policy = "default-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    elif "frame-ancestors 'none'" not in content_security_policy:
        content_security_policy += "; frame-ancestors 'none'"
    response.headers["Content-Security-Policy"] = content_security_policy


app = create_app()
