"""Shared SHA-256 token hashing for owner-issued and recovery codes.

Every raw bearer token (coach invite, assignment invite, password reset, and
account claim) is stored only as its SHA-256 hex digest (ADR-007). The four
issuance/redeem paths share this one implementation so they cannot drift.
"""

import hashlib


def hash_token(token: str) -> str:
    """SHA-256 hex digest of a raw token; ``str`` coercion is part of the contract."""
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()
