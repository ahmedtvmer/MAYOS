"""Rate limits. Auth routes are strict (anti-enumeration); chat/onboarding keyed per user."""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _client_ip(request: Request) -> str:
    """The client address a limit is keyed on.

    On Fly every request reaches the app from the proxy, so ``get_remote_address``
    would collapse every caller into one bucket — a single visitor could spend
    the whole password budget for everyone. When ``FLY_APP_NAME`` is set (Fly
    injects it into every Machine), the proxy-set ``Fly-Client-IP`` header is the
    real caller and is used instead; off Fly the socket address is used and that
    header — which any client could forge — is ignored.
    """
    if os.getenv("FLY_APP_NAME"):
        forwarded = request.headers.get("fly-client-ip", "")
        if forwarded:
            return forwarded.strip()
    return get_remote_address(request)


def _key(request: Request) -> str:
    ip = _client_ip(request)
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and len(auth) > 20:
        return f"{ip}:{auth[-12:]}"
    return ip


limiter = Limiter(key_func=_key)

LOGIN_LIMIT = os.getenv("RATE_LIMIT_LOGIN", "5/minute")
REGISTER_LIMIT = os.getenv("RATE_LIMIT_REGISTER", "5/minute")
PASSWORD_LIMIT = os.getenv("RATE_LIMIT_PASSWORD", "10/minute")
RESET_LIMIT = os.getenv("RATE_LIMIT_RESET", "3/hour")
CHAT_LIMIT = os.getenv("RATE_LIMIT_CHAT", "30/minute")
ONBOARDING_LIMIT = os.getenv("RATE_LIMIT_ONBOARDING", "30/minute")
COACH_INVITE_LIMIT = os.getenv("RATE_LIMIT_COACH_INVITE", "10/minute")
ASSIGNMENT_INVITE_LIMIT = os.getenv("RATE_LIMIT_ASSIGNMENT_INVITE", "10/minute")
ASSIGNMENT_PREVIEW_LIMIT = os.getenv("RATE_LIMIT_ASSIGNMENT_PREVIEW", "30/minute")
ASSIGNMENT_REDEEM_LIMIT = os.getenv("RATE_LIMIT_ASSIGNMENT_REDEEM", "10/minute")
ASSIGNMENT_MUTATE_LIMIT = os.getenv("RATE_LIMIT_ASSIGNMENT_MUTATE", "30/minute")
