"""Coach/player assignment invites and the consented assignment lifecycle.

A coach with the live coach capability issues a single-use, expiring, capacity-bound
bearer code. A code is *not* recipient bound (ADR 014): the first authenticated
player to consent to it becomes assigned, so a forwarded code binds a different
player. The player previews the coach's current identity and the exact access the
assignment grants before explicitly consenting. Redemption is one catalog
transaction that claims the code, checks the player's existing assignment and the
coach's current capacity, creates the assignment, and writes the coach's in-app
notice. The generic email notice is sent after that commit, so a transport failure
never rolls back a consented assignment.

Account ids always come from the verified JWT; request bodies never select them.
Only SHA-256 hashes of codes are stored and neither codes nor notices are logged.
"""

import hashlib
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from service.email_sender import send_assignment_redemption_email

logger = logging.getLogger(__name__)

DEFAULT_INVITE_TTL_MINUTES = 3 * 24 * 60
MIN_INVITE_TTL_MINUTES = 5
MAX_INVITE_TTL_MINUTES = 43200
MAX_NOTICES = 50

GENERIC_INVITE_ERROR = "Invalid or expired invite code."
SELF_ASSIGNMENT_ERROR = "You cannot assign yourself as your own coach."
ALREADY_ASSIGNED_ERROR = "You already have an active coaching assignment."
CAPACITY_ERROR = "This coach's roster is full. Ask them for a new invite later."
CONSENT_REQUIRED_ERROR = "You must explicitly accept the assignment to redeem this invite."
ROSTER_FULL_ERROR = "Your roster is full. End an assignment before issuing another invite."

ACCESS_SCOPE = "current_and_historical_training_data"
ACCESS_DESCRIPTION = (
    "While this assignment is active, your coach can view all of your training data, "
    "both current and historical. Your coach loses that access immediately when the "
    "assignment ends. Your conversations with the player assistant stay private."
)


def _bounded_ttl_minutes(minutes: int) -> int:
    return min(max(int(minutes), MIN_INVITE_TTL_MINUTES), MAX_INVITE_TTL_MINUTES)


def assignment_invite_ttl() -> timedelta:
    """Assignment invite lifetime; default 3 days, clamped to the documented 5 min – 30 day bounds."""
    try:
        minutes = int(os.getenv("ASSIGNMENT_INVITE_TTL_MINUTES", str(DEFAULT_INVITE_TTL_MINUTES)))
    except ValueError:
        minutes = DEFAULT_INVITE_TTL_MINUTES
    return timedelta(minutes=_bounded_ttl_minutes(minutes))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _valid_token(token: Any) -> bool:
    return isinstance(token, str) and 10 <= len(token) <= 128


def _access_disclosure() -> dict[str, Any]:
    return {
        "scope": ACCESS_SCOPE,
        "includes_current_history": True,
        "includes_historical_history": True,
        "active_while_assigned": True,
        "description": ACCESS_DESCRIPTION,
    }


def _coach_identity(db: Any, coach_account_id: str, account: dict[str, Any]) -> dict[str, str]:
    profile = db.get_coach_profile(coach_account_id)
    if profile is None:
        return {"display_name": account["username"], "bio": "", "specialization": ""}
    return {
        "display_name": profile["display_name"],
        "bio": profile["bio"],
        "specialization": profile["specialization"],
    }


def _reason_error(reason: str) -> str:
    if reason == "self":
        return SELF_ASSIGNMENT_ERROR
    if reason == "already_assigned":
        return ALREADY_ASSIGNED_ERROR
    if reason == "capacity":
        return CAPACITY_ERROR
    return GENERIC_INVITE_ERROR


def issue_assignment_invite(
    db: Any,
    coach_account_id: str,
    token_factory: Callable[[], str] | None = None,
    ttl_minutes: int | None = None,
) -> dict[str, Any]:
    """Coach issues a single-use, capacity-bound assignment invite.

    Refuses when the coach capability is absent or the roster is already at capacity,
    so a code can never be minted that could not be redeemed.
    """
    account = db.get_account(coach_account_id)
    if not db.is_live_account(account) or not account["is_coach"]:
        return {"ok": False, "error": "Coach capability required."}

    capacity = db.get_coach_capacity(coach_account_id)
    if capacity is None:
        return {"ok": False, "error": "Set up your coach profile before issuing invites."}
    active = db.count_active_assignments_for_coach(coach_account_id)
    if active >= capacity:
        return {"ok": False, "error": ROSTER_FULL_ERROR, "active_assignments": active, "capacity": capacity}

    if ttl_minutes is None:
        ttl = assignment_invite_ttl()
    elif isinstance(ttl_minutes, bool) or not isinstance(ttl_minutes, int) or ttl_minutes <= 0:
        return {"ok": False, "error": "Invite lifetime must be a positive number of minutes."}
    else:
        ttl = timedelta(minutes=_bounded_ttl_minutes(ttl_minutes))

    raw_token = token_factory() if token_factory else secrets.token_urlsafe(32)
    expires_at = (datetime.now(UTC) + ttl).isoformat()
    db.create_assignment_invite(_hash_token(raw_token), coach_account_id, expires_at)
    return {
        "ok": True,
        "token": raw_token,
        "expires_at": expires_at,
        "active_assignments": active,
        "capacity": capacity,
    }


def preview_assignment_invite(db: Any, token: Any, player_account_id: str) -> dict[str, Any]:
    """Reads the coach identity and access disclosure for a code without consuming it."""
    if not _valid_token(token):
        return {"ok": False, "error": GENERIC_INVITE_ERROR}
    invite = db.get_assignment_invite(_hash_token(token))
    now_iso = datetime.now(UTC).isoformat()
    if invite is None or invite["used_at"] is not None or invite["expires_at"] <= now_iso:
        return {"ok": False, "error": GENERIC_INVITE_ERROR}
    if invite["coach_account_id"] == str(player_account_id):
        return {"ok": False, "error": SELF_ASSIGNMENT_ERROR}

    coach = db.get_account(invite["coach_account_id"])
    if not db.is_live_account(coach) or not coach["is_coach"]:
        return {"ok": False, "error": GENERIC_INVITE_ERROR}
    player = db.get_account(player_account_id)
    if not db.is_live_account(player) or not player["is_player"]:
        return {"ok": False, "error": GENERIC_INVITE_ERROR}
    if db.get_active_assignment_for_player(player_account_id) is not None:
        return {"ok": False, "error": ALREADY_ASSIGNED_ERROR}

    return {
        "ok": True,
        "coach": _coach_identity(db, invite["coach_account_id"], coach),
        "access": _access_disclosure(),
        "expires_at": invite["expires_at"],
    }


def _send_redemption_email(
    db: Any, coach_account: dict[str, Any] | None, coach_display_name: str, player_username: str
) -> bool:
    """Best-effort email after the assignment commits. Never raises into the request."""
    if coach_account is None:
        return False
    to_email = db.get_trainee_email(coach_account["ledger_id"])
    if not to_email:
        return False
    try:
        return send_assignment_redemption_email(to_email, coach_display_name, player_username)
    except Exception:
        logger.exception("Assignment notice email raised unexpectedly")
        return False


def redeem_assignment_invite(db: Any, token: Any, player_account_id: str, consent: bool) -> dict[str, Any]:
    """Atomically redeems a code after explicit consent; emails the coach afterwards.

    The assignment, single-use claim, and in-app notice commit together. The email is
    a post-commit side effect, so a transport failure leaves the assignment intact.
    """
    if consent is not True:
        return {"ok": False, "error": CONSENT_REQUIRED_ERROR}
    if not _valid_token(token):
        return {"ok": False, "error": GENERIC_INVITE_ERROR}

    now_iso = datetime.now(UTC).isoformat()
    result = db.redeem_assignment_invite(_hash_token(token), player_account_id, now_iso)
    if not result["ok"]:
        return {"ok": False, "error": _reason_error(result["reason"])}

    db.prune_assignment_invites(now_iso)
    coach_account = db.get_account(result["coach_account_id"])
    identity = _coach_identity(db, result["coach_account_id"], coach_account) if coach_account else {
        "display_name": "",
        "bio": "",
        "specialization": "",
    }
    email_sent = _send_redemption_email(db, coach_account, identity["display_name"], result["player_username"])
    return {
        "ok": True,
        "assignment": {
            "assignment_id": result["assignment_id"],
            "coach": identity,
            "started_at": result["started_at"],
            "status": "active",
        },
        "notices_created": 1,
        "email_sent": email_sent,
    }


def get_player_assignment(db: Any, player_account_id: str) -> dict[str, Any] | None:
    """The player's active assignment with the coach's current identity, or ``None``."""
    assignment = db.get_active_assignment_for_player(player_account_id)
    if assignment is None:
        return None
    coach = db.get_account(assignment["coach_account_id"])
    if not db.is_live_account(coach) or not coach["is_coach"]:
        return None
    return {
        "assignment_id": assignment["assignment_id"],
        "coach": _coach_identity(db, assignment["coach_account_id"], coach),
        "started_at": assignment["started_at"],
        "status": assignment["status"],
    }


def end_assignment(db: Any, account_id: str, assignment_id: Any, ended_by: str) -> dict[str, Any]:
    """Ends an assignment when the caller is the coach or the player. Revocation is immediate."""
    if not isinstance(assignment_id, str) or not assignment_id:
        return {"ok": False, "error": "Assignment not found."}
    result = db.end_assignment(assignment_id, account_id, datetime.now(UTC).isoformat(), ended_by)
    if not result["ok"]:
        reason = result["reason"]
        if reason == "forbidden":
            return {"ok": False, "error": "You are not part of this assignment."}
        if reason == "already_ended":
            return {"ok": False, "error": "This assignment has already ended."}
        return {"ok": False, "error": "Assignment not found."}
    return {"ok": True, "assignment_id": assignment_id, "status": "ended", "ended_at": result["ended_at"]}


def list_coach_assignments(db: Any, coach_account_id: str) -> list[dict[str, Any]]:
    """Active assignments for a coach: identity and timing only, no training history."""
    return [
        {
            "assignment_id": row["assignment_id"],
            "player_username": row["player_username"],
            "started_at": row["started_at"],
            "status": row["status"],
        }
        for row in db.list_active_assignments_for_coach(coach_account_id)
    ]


def list_coach_notices(db: Any, coach_account_id: str) -> list[dict[str, Any]]:
    return db.list_assignment_notices(coach_account_id, MAX_NOTICES)


def mark_coach_notices_read(db: Any, coach_account_id: str) -> int:
    return db.mark_assignment_notices_read(coach_account_id, datetime.now(UTC).isoformat())


def disable_coach_capability(db: Any, coach_account_id: str) -> dict[str, Any]:
    """Ends every assignment and clears the capability in one catalog transaction.

    The account's own player ledger is never touched, so its training data survives
    (ADR 013/014).
    """
    result = db.disable_coach_account(
        coach_account_id, datetime.now(UTC).isoformat(), "coach_capability_disabled"
    )
    if not result["ok"]:
        return {"ok": False, "error": "Coach capability required."}
    return {"ok": True, "ended_assignments": result["ended_assignments"]}
