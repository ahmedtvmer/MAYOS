"""Privacy-first Sentry configuration for API errors (ADR 097)."""

import hashlib
import hmac
import os
from typing import Any

_HEADER_ALLOWLIST: set[str] = set()
SERVER_ERROR_MESSAGE = "API returned a server error"


def anonymous_account_id(account_id: str) -> str:
    """Return a stable, purpose-separated HMAC identifier for an account."""
    secret = os.getenv("ANONYMOUS_ID_SECRET") or os.getenv("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("ANONYMOUS_ID_SECRET or JWT_SECRET is required")
    digest = hmac.new(
        secret.encode("utf-8"),
        b"mayos:sentry-account:v1:" + account_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Allow only stack locations, safe routing metadata and anonymous identity."""
    request = event.get("request")
    if isinstance(request, dict):
        safe_request: dict[str, Any] = {}
        if request.get("method"):
            safe_request["method"] = request["method"]
        headers = request.get("headers")
        if isinstance(headers, dict):
            safe_request["headers"] = {
                key: value for key, value in headers.items()
                if isinstance(key, str) and key.lower() in _HEADER_ALLOWLIST
            }
        event["request"] = safe_request

    # Treat integration-added fields as untrusted. Retain only diagnostic
    # structure that has an explicit privacy contract.
    allowed = {
        "event_id", "timestamp", "platform", "level", "logger", "transaction", "message",
        "release", "environment", "tags", "exception", "request", "user",
    }
    for key in list(event):
        if key not in allowed:
            event.pop(key, None)
    event.pop("tags", None)
    if event.get("message") != SERVER_ERROR_MESSAGE:
        event.pop("message", None)
    # Sentry's ASGI integrations normally name transactions from route
    # templates. Keep only those generated templates, never raw request paths.
    transaction = event.get("transaction")
    if (
        not isinstance(transaction, str)
        or not transaction.startswith("/")
        or "{" not in transaction
        or "}" not in transaction
    ):
        event.pop("transaction", None)
    exception_data = event.get("exception")
    exception = exception_data.get("values", []) if isinstance(exception_data, dict) else []
    safe_values = []
    for item in exception:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"ExceptionGroup", "BaseExceptionGroup"}:
            continue
        safe_item = {}
        if isinstance(item.get("type"), str):
            safe_item["type"] = item["type"]
        stack = item.get("stacktrace")
        if isinstance(stack, dict):
            safe_frames = []
            for frame in stack.get("frames", []):
                if not isinstance(frame, dict):
                    continue
                safe_frame = {
                    key: frame[key]
                    for key in ("filename", "function", "lineno", "in_app")
                    if key in frame
                }
                safe_frames.append(safe_frame)
            safe_item["stacktrace"] = {"frames": safe_frames}
        safe_values.append(safe_item)
    if safe_values:
        event["exception"] = {"values": safe_values}
    else:
        event.pop("exception", None)
    user = event.get("user")
    anonymous_id = user.get("id") if isinstance(user, dict) else None
    event["user"] = {"id": anonymous_id} if anonymous_id else {}
    return event


class ServerErrorCaptureMiddleware:
    """Capture handled HTTP 5xx responses without intercepting exceptions."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not os.getenv("SENTRY_DSN", "").strip():
            await self.app(scope, receive, send)
            return

        response_status = None

        async def capture_response(message: dict[str, Any]) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
            await send(message)

        await self.app(scope, receive, capture_response)
        if response_status is not None and response_status >= 500:
            import sentry_sdk

            sentry_sdk.capture_message(SERVER_ERROR_MESSAGE, level="error")


def initialize_sentry(*, transport: Any = None) -> bool:
    """Initialize Sentry only when explicitly configured; tracing stays off."""
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT") or os.getenv("MAYOS_ENV", "development"),
        release=os.getenv("SENTRY_RELEASE") or os.getenv("GIT_COMMIT", "unknown"),
        send_default_pii=False,
        before_send=before_send,
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
        integrations=[
            FastApiIntegration(failed_request_status_codes=set()),
            StarletteIntegration(failed_request_status_codes=set()),
            LoggingIntegration(level=None, event_level=None),
        ],
        default_integrations=False,
        transport=transport,
    )
    return True


def set_account_user(account_id: str) -> None:
    if os.getenv("SENTRY_DSN", "").strip():
        import sentry_sdk

        sentry_sdk.set_user({"id": anonymous_account_id(account_id)})
