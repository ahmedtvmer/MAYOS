"""Coach capability issuance and the coach profile.

During the closed trial only the owner may enable the coach capability. Issuance
is an operator action (:func:`issue_coach_invite`), never a public authenticated
account API: the CLI in ``scripts/issue_coach_invite.py`` resolves a live player
account and mints a single-use, account-bound code. Redemption is authenticated
and atomic — the caller's immutable account id must match the invite's binding,
the code must be unused and unexpired, and the ``is_coach`` flip commits in the
same catalog transaction that claims the code.

Only SHA-256 hashes of invite tokens are stored (ADR-007 pattern); the raw code
is returned once to the operator. The client body can never set ``is_coach``.
"""

import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

DEFAULT_CAPACITY = 10
MIN_CAPACITY = 1
MAX_CAPACITY = 200
MAX_DISPLAY_NAME = 60
MAX_BIO = 1000
MAX_SPECIALIZATION = 200
MIN_INVITE_TTL_MINUTES = 5
MAX_INVITE_TTL_MINUTES = 43200

GENERIC_INVITE_ERROR = "Invalid or expired invite code."


def _bounded_ttl_minutes(minutes: int) -> int:
    """Clamps an invite lifetime to the documented 5 min – 30 day bounds."""
    return min(max(int(minutes), MIN_INVITE_TTL_MINUTES), MAX_INVITE_TTL_MINUTES)


def coach_invite_ttl() -> timedelta:
    """Invite lifetime; default 24 h, clamped to the documented 5 min – 30 day bounds."""
    try:
        minutes = int(os.getenv("COACH_INVITE_TTL_MINUTES", "1440"))
    except ValueError:
        minutes = 1440
    return timedelta(minutes=_bounded_ttl_minutes(minutes))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_coach_invite(
    db: Any,
    username: str,
    token_factory: Callable[[], str] | None = None,
    ttl_minutes: int | None = None,
) -> dict[str, Any]:
    """Owner-only issuance: mint a single-use coach invite bound to a live account.

    Returns the raw token exactly once for the operator to hand to the invited
    person; only its hash is stored. Refuses a username with no live player
    account so a code can never target a ghost or a non-player.
    """
    clean_id = db._sanitize_username(username)
    account = db.get_active_account_by_username(clean_id) if clean_id else None
    if account is None or not db.user_exists(account["ledger_id"]):
        return {"ok": False, "error": f"Unknown account '{username}'."}
    if ttl_minutes is None:
        ttl = coach_invite_ttl()
    elif isinstance(ttl_minutes, bool) or not isinstance(ttl_minutes, int) or ttl_minutes <= 0:
        return {"ok": False, "error": "Invite lifetime must be a positive number of minutes."}
    else:
        ttl = timedelta(minutes=_bounded_ttl_minutes(ttl_minutes))
    raw_token = token_factory() if token_factory else secrets.token_urlsafe(32)
    expires_at = (datetime.now(UTC) + ttl).isoformat()
    db.create_coach_invite(_hash_token(raw_token), account["account_id"], expires_at)
    return {
        "ok": True,
        "token": raw_token,
        "account_id": account["account_id"],
        "username": account["ledger_id"],
        "expires_at": expires_at,
    }


def redeem_coach_invite(db: Any, account_id: str, token: str) -> dict[str, Any]:
    """Authenticated redemption. Unknown/expired/used/mismatched codes share one error.

    ``account_id`` comes from the verified JWT, never the body, so the code can
    only ever grant the account the owner bound it to.
    """
    if not isinstance(token, str) or not (10 <= len(token) <= 128):
        return {"ok": False, "error": GENERIC_INVITE_ERROR}
    now_iso = datetime.now(UTC).isoformat()
    account = db.redeem_coach_invite(_hash_token(token), account_id, now_iso, DEFAULT_CAPACITY)
    if account is None:
        return {"ok": False, "error": GENERIC_INVITE_ERROR}
    db.prune_coach_invites(now_iso)
    return {
        "ok": True,
        "account_id": account["account_id"],
        "username": account["ledger_id"],
        "capabilities": {"player": account["is_player"], "coach": account["is_coach"]},
    }


def get_coach_profile(db: Any, account_id: str) -> dict[str, Any] | None:
    """Reads the coach profile for a verified coach account, or ``None`` when absent."""
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_coach"]:
        return None
    return db.get_coach_profile(account["account_id"])


def validate_coach_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalizes and bounds coach-authored fields. Raises :class:`ValueError`."""
    display_name = payload.get("display_name")
    if not isinstance(display_name, str) or not 1 <= len(display_name.strip()) <= MAX_DISPLAY_NAME:
        raise ValueError(f"Display name must be 1–{MAX_DISPLAY_NAME} characters.")

    bio = payload.get("bio", "")
    if bio is None:
        bio = ""
    if not isinstance(bio, str) or len(bio) > MAX_BIO:
        raise ValueError(f"Bio must be at most {MAX_BIO} characters.")

    specialization = payload.get("specialization", "")
    if specialization is None:
        specialization = ""
    if not isinstance(specialization, str) or len(specialization) > MAX_SPECIALIZATION:
        raise ValueError(f"Specialization must be at most {MAX_SPECIALIZATION} characters.")

    capacity = payload.get("capacity")
    if isinstance(capacity, bool) or not isinstance(capacity, int) or not MIN_CAPACITY <= capacity <= MAX_CAPACITY:
        raise ValueError(f"Capacity must be a whole number between {MIN_CAPACITY} and {MAX_CAPACITY}.")

    return {
        "display_name": display_name.strip(),
        "bio": bio,
        "specialization": specialization,
        "capacity": capacity,
    }


def update_coach_profile(db: Any, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Authenticated coach-only profile update. Validates before any write."""
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_coach"]:
        return {"ok": False, "error": "Coach capability required."}
    try:
        clean = validate_coach_profile(payload)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    db.upsert_coach_profile(account["account_id"], clean)
    return {"ok": True, "profile": db.get_coach_profile(account["account_id"])}
