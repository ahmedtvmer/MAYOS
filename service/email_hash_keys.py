"""Purpose-separated keys for email references and recovery limits."""

import hashlib
import hmac
import os
import secrets

_FALLBACK_EMAIL_HASH_ROOT = secrets.token_bytes(32)


def derive_email_hash_key(purpose: str) -> bytes:
    """Derives a stable purpose-specific key from config or the process secret."""
    secret = os.getenv("JWT_SECRET", "").encode()
    root_key = secret or _FALLBACK_EMAIL_HASH_ROOT
    return hmac.new(root_key, f"email-{purpose}".encode(), hashlib.sha256).digest()
