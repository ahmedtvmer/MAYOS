"""Google sign-in: username picker and first-sign-in account creation (#113).

A Verified Google identity is a ``sub`` (plus the token's ``iat``) — never an
email address, and no name from the token is persisted: ``given_name`` is read
once to seed a *suggestion* that the person may change before anything is
written. No account exists until a username is picked, so abandoning the flow
leaves nothing behind.

The picker's rule is stricter than ``/auth/register``: after lowercasing, a
picked username must be 3–30 characters of ``a–z 0–9 _ -`` and is **refused**
when it does not match, never silently stripped (``register_player`` keeps its
own sanitising behaviour; see the issue #113 report).
"""

import re
import sqlite3
from datetime import UTC, datetime
from typing import Any

PROVIDER = "google"
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 30
INVALID_USERNAME = "Username must be 3–30 characters of a–z, 0–9, _ or - (lowercase)."
USERNAME_TAKEN = "This username is already taken."
ALREADY_LINKED = "This Google account is already linked to a MAYOS account."

_USERNAME_RE = re.compile(r"[a-z0-9_-]{3,30}")
#: Used when the token carries no usable given name (or only punctuation).
_SUGGESTION_FALLBACK = "player"


class SignUpConflictError(Exception):
    """A completion that must not create an account: taken username, live link."""


def validate_username(raw: Any) -> str:
    """Returns the picked username lowercased, or raises ``ValueError`` with the rule.

    Only lowercasing is applied: every other deviation from ``a–z 0–9 _ -`` is
    a refusal, so no input is quietly rewritten into a different username.
    """
    if not isinstance(raw, str):
        raise ValueError(INVALID_USERNAME)
    clean = raw.lower()
    if _USERNAME_RE.fullmatch(clean) is None:
        raise ValueError(INVALID_USERNAME)
    return clean


def username_available(db: Any, username: Any) -> dict[str, Any]:
    """``{available, reason?}`` for the picker, under the same rule as completion."""
    clean = validate_username(username)
    if not _is_free(db, clean):
        return {"available": False, "reason": "taken"}
    return {"available": True}


def suggest_username(db: Any, given_name: Any) -> str:
    """A valid, currently free username derived from the token's given name.

    A suggestion only: it is checked for availability here (with a numeric
    suffix when the base is taken) and stored only if the person keeps it.
    """
    base = _base_from_given_name(given_name)
    candidate = base
    suffix = 2
    while not _is_free(db, candidate) and suffix <= 1000:
        tag = f"-{suffix}"
        candidate = f"{base[: MAX_USERNAME_LENGTH - len(tag)]}{tag}"
        suffix += 1
    return candidate


def sign_in(db: Any, subject: str, given_name: Any = None) -> dict[str, Any]:
    """Resolves a verified Google identity to a session or a signup suggestion.

    The link is keyed on ``(google, subject)`` and matched to a **live**
    account only; a link to a deleted account is treated as no link, so the
    person simply picks a username again and the link is re-pointed in the
    completion transaction.
    """
    account_id = db.get_linked_sign_in_account_id(PROVIDER, subject)
    account = db.get_account(account_id) if account_id else None
    if db.is_live_account(account):
        return {
            "kind": "session",
            "account_id": account["account_id"],
            "trainee_id": account["ledger_id"],
            "session_epoch": account["session_epoch"],
        }
    return {"kind": "signup", "suggested_username": suggest_username(db, given_name)}


def complete_signup(db: Any, subject: str, username: Any) -> dict[str, Any]:
    """Creates the account and the link in one catalog transaction.

    Mirrors ``register_player``: player capability, its own ledger, no password
    hash. Every race loses cleanly — a username taken by another registration
    or a subject linked concurrently fails the transaction, so no second
    account is ever created for one Google identity.
    """
    clean = validate_username(username)
    linked_at = datetime.now(UTC).isoformat()
    with db.catalog_transaction():
        existing_id = db.get_linked_sign_in_account_id(PROVIDER, subject)
        if existing_id is not None:
            if db.is_live_account(db.get_account(existing_id)):
                raise SignUpConflictError(ALREADY_LINKED)
            # A dead account's link is replaced here, in the same transaction.
            db.remove_linked_sign_in(PROVIDER, subject)
        if not _is_free(db, clean):
            raise SignUpConflictError(USERNAME_TAKEN)
        account_id = db.create_account(clean)
        if account_id is None:
            raise SignUpConflictError(USERNAME_TAKEN)
        try:
            db.link_sign_in(PROVIDER, subject, account_id, linked_at=linked_at)
        except sqlite3.IntegrityError:
            # UNIQUE(provider, subject): the other completion won the race, and
            # unwinding here takes the freshly created account with it.
            raise SignUpConflictError(ALREADY_LINKED) from None
    account = db.get_account(account_id) or {}
    ledger_id = account.get("ledger_id") or clean
    # Materialise the ledger, as registration does when it stores the hash, so
    # the session this returns passes the registry's ledger-existence gate.
    with db.open_ledger(ledger_id):
        pass
    return {
        "ok": True,
        "account_id": account_id,
        "trainee_id": ledger_id,
        "session_epoch": account.get("session_epoch", 1),
    }


def _is_free(db: Any, clean: str) -> bool:
    """True when no live account owns ``clean`` and no ledger file claims it."""
    return db.get_active_account_by_username(clean) is None and not db.ledger_exists(clean)


def _base_from_given_name(given_name: Any) -> str:
    base = re.sub(r"[^a-z0-9_-]", "", str(given_name or "").lower())[:MAX_USERNAME_LENGTH]
    if len(base) < MIN_USERNAME_LENGTH:
        return _SUGGESTION_FALLBACK
    return base
