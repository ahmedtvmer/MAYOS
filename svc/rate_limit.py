"""Rate limits. Auth routes are strict (anti-enumeration); chat/onboarding keyed per user."""

import os
import ipaddress

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def client_ip(request: Request) -> str:
    """The full caller address from the one trusted source.

    Behind a proxy (Fly, or a Cloudflare Tunnel on Hetzner) every request reaches
    the app from the proxy, so the socket address would collapse every caller
    into one bucket. ``MAYOS_CLIENT_IP_HEADER`` names the single proxy-set header
    to trust; when unset and ``FLY_APP_NAME`` is present, Fly's ``Fly-Client-IP``
    is used. With neither, forwarding headers — which any client could forge —
    are ignored. A missing or unparsable trusted header falls back to the socket.
    """
    forwarded_ip = _request_ip(request, _trusted_header())
    if forwarded_ip is not None:
        return forwarded_ip
    socket_ip = get_remote_address(request)
    return _normalize_ip(socket_ip) or socket_ip


def _trusted_header() -> str | None:
    configured = os.getenv("MAYOS_CLIENT_IP_HEADER", "").strip()
    if configured:
        return configured
    return "fly-client-ip" if os.getenv("FLY_APP_NAME") else None


def client_ip_bucket(address: str) -> str:
    """Use one bucket per IPv4 address or IPv6 /64 network."""
    normalized = _normalize_ip(address)
    if normalized is None:
        return address
    parsed = ipaddress.ip_address(normalized)
    if isinstance(parsed, ipaddress.IPv6Address):
        return ipaddress.ip_network(f"{parsed}/64", strict=False).with_prefixlen
    return parsed.compressed


def _request_ip(request: Request, header_name: str | None) -> str | None:
    if header_name is None:
        return None
    forwarded = request.headers.get(header_name, "").strip()
    return _normalize_ip(forwarded) if forwarded else None


def _normalize_ip(value: str) -> str | None:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    mapped_address = getattr(address, "ipv4_mapped", None)
    if mapped_address is not None:
        return mapped_address.compressed
    return address.compressed


_client_ip = client_ip


def _key(request: Request) -> str:
    ip = client_ip_bucket(client_ip(request))
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and len(auth) > 20:
        return f"{ip}:{auth[-12:]}"
    return ip


limiter = Limiter(key_func=_key)

LOGIN_LIMIT = os.getenv("RATE_LIMIT_LOGIN", "5/minute")
REGISTER_LIMIT = os.getenv("RATE_LIMIT_REGISTER", "5/minute")
#: The username picker asks on every keystroke pause, so it gets a roomier
#: budget than login/register while still being per-client (issue #113).
USERNAME_CHECK_LIMIT = os.getenv("RATE_LIMIT_USERNAME_CHECK", "30/minute")
PASSWORD_LIMIT = os.getenv("RATE_LIMIT_PASSWORD", "10/minute")
RESET_LIMIT = os.getenv("RATE_LIMIT_RESET", "3/hour")
CHAT_LIMIT = os.getenv("RATE_LIMIT_CHAT", "30/minute")
ONBOARDING_LIMIT = os.getenv("RATE_LIMIT_ONBOARDING", "30/minute")
PROGRAM_MUTATE_LIMIT = os.getenv("RATE_LIMIT_PROGRAM_MUTATE", "30/minute")
COACH_INVITE_LIMIT = os.getenv("RATE_LIMIT_COACH_INVITE", "10/minute")
ASSIGNMENT_INVITE_LIMIT = os.getenv("RATE_LIMIT_ASSIGNMENT_INVITE", "10/minute")
ASSIGNMENT_PREVIEW_LIMIT = os.getenv("RATE_LIMIT_ASSIGNMENT_PREVIEW", "30/minute")
ASSIGNMENT_REDEEM_LIMIT = os.getenv("RATE_LIMIT_ASSIGNMENT_REDEEM", "10/minute")
ASSIGNMENT_MUTATE_LIMIT = os.getenv("RATE_LIMIT_ASSIGNMENT_MUTATE", "30/minute")
COACH_ASSISTANT_LIMIT = os.getenv("RATE_LIMIT_COACH_ASSISTANT", "30/minute")
WORKOUT_SYNC_FAILURE_LIMIT = os.getenv("RATE_LIMIT_WORKOUT_SYNC_FAILURE", "10/minute")
