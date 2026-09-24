"""Rate limits. Auth routes are strict (anti-enumeration); chat/onboarding keyed per user."""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _key(request: Request) -> str:
    ip = get_remote_address(request)
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
