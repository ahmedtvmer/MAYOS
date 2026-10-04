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

import hmac
import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from service import audit_log, email_sender
from service import analytics as analytics_service
from service._tokens import hash_token

DEFAULT_CAPACITY = 10
MIN_CAPACITY = 1
MAX_CAPACITY = 200
MAX_DISPLAY_NAME = 60
MAX_BIO = 1000
MAX_SPECIALIZATION = 200
MIN_INVITE_TTL_MINUTES = 5
MAX_INVITE_TTL_MINUTES = 43200
MAX_NEW_ACCOUNT_INVITE_TTL_MINUTES = 10080
DEFAULT_NEW_ACCOUNT_INVITE_TTL_MINUTES = 1440

GENERIC_INVITE_ERROR = "Invalid or expired invite code."
GENERIC_NEW_ACCOUNT_INVITE_ERROR = "This coach invite code isn't valid for this username"


@dataclass(frozen=True)
class OwnerCoachInviteEmailRequest:
    account_id: str
    raw_code: str
    actor: str
    source_ip: str | None


def _bounded_ttl_minutes(minutes: int, maximum: int = MAX_INVITE_TTL_MINUTES) -> int:
    """Clamps an invite lifetime to its minimum and the selected maximum."""
    return min(max(int(minutes), MIN_INVITE_TTL_MINUTES), maximum)


def _invalid_ttl(minutes: int | None) -> bool:
    return isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0


def coach_invite_ttl() -> timedelta:
    """Invite lifetime; default 24 h, clamped to the documented 5 min – 30 day bounds."""
    try:
        minutes = int(os.getenv("COACH_INVITE_TTL_MINUTES", "1440"))
    except ValueError:
        minutes = 1440
    return timedelta(minutes=_bounded_ttl_minutes(minutes))


def issue_coach_invite(
    db: Any,
    username: str,
    token_factory: Callable[[], str] | None = None,
    ttl_minutes: int | None = None,
    source_ip: str | None = None,
    account_id: str | None = None,
    new_account: bool = False,
    *,
    actor: str,
) -> dict[str, Any]:
    """Owner-only issuance for an existing Account or a held username.

    Returns the raw token exactly once for the operator to hand to the invited
    person; only its hash is stored. New-account mode reserves an unowned
    username until redemption or expiry.
    """
    clean_id = db._sanitize_username(username)
    if new_account:
        if ttl_minutes is None:
            ttl = timedelta(minutes=DEFAULT_NEW_ACCOUNT_INVITE_TTL_MINUTES)
        elif _invalid_ttl(ttl_minutes):
            return {
                "ok": False,
                "code": "invalid_ttl",
                "error": "Invite lifetime must be a positive number of minutes.",
            }
        else:
            ttl = timedelta(minutes=_bounded_ttl_minutes(ttl_minutes, MAX_NEW_ACCOUNT_INVITE_TTL_MINUTES))
        raw_token = token_factory() if token_factory else secrets.token_urlsafe(32)
        expires_at = (datetime.now(UTC) + ttl).isoformat()
        if not clean_id:
            return {
                "ok": False,
                "code": "username_unavailable",
                "error": "Username is unavailable.",
            }
        with db.catalog_transaction(immediate=True):
            if not db.issue_new_account_coach_invite(hash_token(raw_token), clean_id, expires_at):
                return {
                    "ok": False,
                    "code": "username_unavailable",
                    "error": "Username is unavailable.",
                }
            audit_log.write_audit_entry(
                db,
                audit_log.AuditEvent(actor=actor, action="coach_invite_issued", source_ip=source_ip),
            )
        return {
            "ok": True,
            "token": raw_token,
            "username": clean_id,
            "expires_at": expires_at,
            "mode": "new_account",
        }

    if ttl_minutes is None:
        ttl = coach_invite_ttl()
    elif _invalid_ttl(ttl_minutes):
        return {
            "ok": False,
            "code": "invalid_ttl",
            "error": "Invite lifetime must be a positive number of minutes.",
        }
    else:
        ttl = timedelta(minutes=_bounded_ttl_minutes(ttl_minutes))
    with db.catalog_transaction():
        account = _coach_invite_account(db, clean_id, account_id)
        if account is None:
            return {"ok": False, "code": "not_found", "error": f"Unknown account '{username}'."}
        if account["is_coach"]:
            return {
                "ok": False,
                "code": "already_coach",
                "error": "Account already has coach capability.",
            }
        raw_token = token_factory() if token_factory else secrets.token_urlsafe(32)
        expires_at = (datetime.now(UTC) + ttl).isoformat()
        db.create_coach_invite(hash_token(raw_token), account["account_id"], expires_at)
        audit_log.write_audit_entry(
            db,
            audit_log.AuditEvent(
                actor=actor,
                action="coach_invite_issued",
                target_account_id=account["account_id"],
                source_ip=source_ip,
            ),
        )
    return {
        "ok": True,
        "token": raw_token,
        "account_id": account["account_id"],
        "username": account["username"],
        "expires_at": expires_at,
    }


def _coach_invite_account(db: Any, clean_id: str, account_id: str | None) -> dict[str, Any] | None:
    account = db.get_account(account_id) if account_id else db.get_active_account_by_username(clean_id) if clean_id else None
    if (
        account is None
        or not db.is_live_account(account)
        or not account["is_player"]
        or account["username"] != clean_id
        or not db.ledger_exists(account["ledger_id"])
    ):
        return None
    return account


def revoke_coach_invite(
    db: Any, invite_id: str, actor: str, source_ip: str | None = None
) -> dict[str, Any]:
    """Revokes a live invite by its stored SHA-256 token hash."""
    if not isinstance(invite_id, str) or re.fullmatch(r"[0-9a-f]{64}", invite_id) is None:
        return {"ok": False, "error": "Invite can't be revoked."}
    now_iso = datetime.now(UTC).isoformat()
    with db.catalog_transaction():
        invite = db.revoke_coach_invite(invite_id, now_iso)
        if invite is None:
            return {"ok": False, "error": "Invite can't be revoked."}
        audit_log.write_audit_entry(
            db,
            audit_log.AuditEvent(
                actor=actor,
                action="coach_invite_revoked",
                target_account_id=invite["account_id"],
                source_ip=source_ip,
            ),
        )
    return {"ok": True, "account_id": invite["account_id"]}


def list_coach_invites(db: Any, account_id: str | None = None) -> list[dict[str, Any]]:
    """Returns live invites and used, expired, or revoked invites from 30 days."""
    moment = datetime.now(UTC)
    now_iso = moment.isoformat()
    recent_since_iso = (moment - timedelta(days=30)).isoformat()
    rows = db.list_coach_invites(now_iso, recent_since_iso, account_id)
    invites = []
    for row in rows:
        if row["used_at"] is not None:
            status, status_at = "used", row["used_at"]
        elif row["revoked_at"] is not None:
            status, status_at = "revoked", row["revoked_at"]
        elif row["expires_at"] <= now_iso:
            status, status_at = "expired", row["expires_at"]
        else:
            status, status_at = "live", None
        invites.append({**row, "mode": "Account-bound", "status": status, "status_at": status_at})
    return invites


def owner_send_coach_invite_email(db: Any, request: OwnerCoachInviteEmailRequest) -> dict[str, str]:
    """Emails a currently live, account-bound Coach invite to a verified address."""
    account = db.get_account(request.account_id)
    if not db.is_live_account(account):
        return {"outcome": "not_found"}
    invite = _live_bound_invite(db, request.account_id, request.raw_code)
    if invite is None or account["is_coach"]:
        return {"outcome": "invite_unavailable"}
    from service.password_reset import verified_recovery_email, write_owner_audit

    email, ineligible_outcome = verified_recovery_email(db, request.account_id)
    if ineligible_outcome:
        action = (
            "coach_invite_email_unavailable"
            if email is None
            else "coach_invite_email_unverified"
        )
        write_owner_audit(
            db,
            audit_log.AuditEvent(
                actor=request.actor,
                action=action,
                target_account_id=request.account_id,
                source_ip=request.source_ip,
            ),
        )
        return {"outcome": ineligible_outcome}
    delivered = email_sender.send_coach_invite_email(
        email,
        request.raw_code,
        account["display_language"],
        account_id=request.account_id,
    )
    action = "coach_invite_emailed" if delivered else "coach_invite_email_failed"
    write_owner_audit(
        db,
        audit_log.AuditEvent(
            actor=request.actor,
            action=action,
            target_account_id=request.account_id,
            source_ip=request.source_ip,
        ),
    )
    return {"outcome": "sent" if delivered else "send_failed"}


def _live_bound_invite(db: Any, account_id: str, raw_code: str) -> dict[str, Any] | None:
    if not isinstance(raw_code, str) or not 10 <= len(raw_code) <= 128:
        return None
    code_hash = hash_token(raw_code)
    return next(
        (
            invite
            for invite in list_coach_invites(db, account_id)
            if invite["status"] == "live" and hmac.compare_digest(invite["token_hash"], code_hash)
        ),
        None,
    )


def redeem_coach_invite(
    db: Any,
    account_id: str,
    token: str,
    *,
    client: analytics_service.ClientContext = analytics_service.UNKNOWN_CLIENT,
) -> dict[str, Any]:
    """Authenticated redemption. Unknown/expired/used/mismatched codes share one error.

    ``account_id`` comes from the verified JWT, never the body, so the code can
    only ever grant the account the owner bound it to.
    """
    if not isinstance(token, str) or not (10 <= len(token) <= 128):
        return {"ok": False, "error": GENERIC_INVITE_ERROR}
    now_iso = datetime.now(UTC).isoformat()
    account = db.redeem_coach_invite(hash_token(token), account_id, now_iso, DEFAULT_CAPACITY)
    if account is None:
        return {"ok": False, "error": GENERIC_INVITE_ERROR}
    db.prune_coach_invites(now_iso)
    capture_coach_capability_granted(db, account["account_id"], now_iso, client=client)
    return {
        "ok": True,
        "account_id": account["account_id"],
        "username": account["username"],
        "capabilities": {"player": account["is_player"], "coach": account["is_coach"]},
    }


def capture_coach_capability_granted_event(
    account_id: str,
    granted_at: str,
    *,
    client: analytics_service.ClientContext = analytics_service.UNKNOWN_CLIENT,
) -> None:
    analytics_service.capture(
        analytics_service.AnalyticsEvent(
            account_id=account_id,
            event="coach_capability_granted",
            domain_key=f"{account_id}:granted:{granted_at}",
            role="coach",
        ),
        client,
    )


def capture_coach_capability_granted(
    db: Any,
    account_id: str,
    granted_at: str,
    *,
    client: analytics_service.ClientContext = analytics_service.UNKNOWN_CLIENT,
) -> None:
    """Captures a committed Coach grant and initializes its roster property."""
    roster_size = db.count_active_assignments_for_coach(account_id)
    capture_coach_capability_granted_event(account_id, granted_at, client=client)
    analytics_service.set_person(account_id, {"is_coach": True, "active_roster_size": roster_size})


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
