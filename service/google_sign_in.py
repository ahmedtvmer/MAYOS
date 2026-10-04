"""Google sign-in: username picker, first-sign-in account creation, and link management (#113/#114).

A Verified Google identity is matched for sign-in by ``sub`` only. No name from
the token is persisted: ``given_name`` seeds a *suggestion* that the person
may change before anything is written. A verified email is used for the signup
nudge and may become the new account's verified recovery email only when it is
unused. On an existing account it can verify only a matching unverified
recovery address; no Google email is logged.

Once an account exists, the same identity can be connected or disconnected
(:func:`link_account` / :func:`unlink_account`): connect is idempotent and
conflicts never say which other account holds the subject, and disconnect is
refused while the account has no password, because an account always keeps at
least one way to sign in (CONTEXT.md, "Linked sign-in").

The picker's rule is stricter than ``/auth/register``: after lowercasing, a
picked username must be 3–30 characters of ``a–z 0–9 _ -`` and is **refused**
when it does not match, never silently stripped (``register_player`` keeps its
own sanitising behaviour; see the issue #113 report).
"""

import re
import sqlite3
from datetime import UTC, datetime
from typing import Any, NamedTuple

from service import admin_accounts, auth as auth_service, password_reset


class GoogleIdentity(NamedTuple):
    """Verified Google claims, including the transient email proof."""

    sub: str
    iat: int | None = None
    given_name: str | None = None
    email: str | None = None
    email_verified: bool = False


class GoogleSignupCompletion(NamedTuple):
    """Verified data needed to complete a first Google sign-in."""

    subject: str
    username: Any
    display_language: str = "en"
    identity: GoogleIdentity | None = None
    recovery_email_conflict: bool = False


PROVIDER = "google"
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 30
INVALID_USERNAME = "Username must be 3–30 characters of a–z, 0–9, _ or - (lowercase)."
USERNAME_TAKEN = "This username is already taken."
ALREADY_LINKED = "This Google account is already linked to a MAYOS account."
#: Connect conflict: the subject belongs to someone else. Never says who (#114).
LINKED_ELSEWHERE = "This Google account is already connected to another MAYOS account"
#: Connect conflict: the caller already has a different Google identity.
DIFFERENT_GOOGLE = "This account already has a different Google account connected. Disconnect it first."
#: Disconnect refusal: an account always keeps at least one way to sign in.
NEEDS_PASSWORD = "Set a password before disconnecting Google, so you can still sign in."

_USERNAME_RE = re.compile(r"[a-z0-9_-]{3,30}")
#: Used when the token carries no usable given name (or only punctuation).
_SUGGESTION_FALLBACK = "player"


class SignUpConflictError(Exception):
    """A completion that must not create an account: taken username, live link."""


class SignInMethodError(Exception):
    """A refused sign-in-method change; its message is safe to show the caller."""


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


def sign_in(db: Any, identity: GoogleIdentity) -> dict[str, Any]:
    """Resolves a verified Google identity to a session or a signup suggestion.

    The link is keyed on ``(google, subject)`` and matched to a **live**
    account only; a link to a deleted account is treated as no link, so the
    person simply picks a username again and the link is re-pointed in the
    completion transaction. For an unlinked subject, a verified email that
    matches a live account's recovery email adds a nudge to the signup answer;
    it never links or creates an account. For a linked subject, it may verify
    only the account's matching current recovery email. A live account whose
    ledger never materialised (an interrupted completion) is repaired here
    before the session is issued, so nobody is stranded behind the registry's
    ledger gate.
    """
    account_id = db.get_linked_sign_in_account_id(PROVIDER, identity.sub)
    account = db.get_account(account_id) if account_id else None
    if db.is_live_account(account):
        _verify_matching_recovery_email(db, account["account_id"], identity)
        return {
            "kind": "session",
            "account_id": account["account_id"],
            "trainee_id": _materialise_ledger(db, account),
            "session_epoch": account["session_epoch"],
            "display_language": account.get("display_language", "en"),
        }
    verified_email = _verified_email(identity)
    return {
        "kind": "signup",
        "suggested_username": suggest_username(db, identity.given_name),
        "existing_account_hint": verified_email is not None and _has_live_recovery_email(db, verified_email),
    }


def _has_live_recovery_email(db: Any, email: str | None) -> bool:
    """Compares a verified Google email with the catalog's normalized recovery keys.

    The email stays in memory for this lookup. Only a live account's boolean
    match is returned; no email or matching account identity leaves this helper.
    """
    return admin_accounts.find_by_recovery_email(db, email) is not None


def complete_signup(db: Any, completion: GoogleSignupCompletion) -> dict[str, Any]:
    """Creates the account and the link in one catalog transaction.

    Mirrors ``register_player``: player capability, its own ledger, no password
    hash. Every race loses cleanly — a username taken by another registration
    or a subject linked concurrently fails the transaction, so no second
    account is ever created for one Google identity.

    A retry of a completion that committed the account and the link but died
    while materialising the ledger heals into that account's session only when
    the requested username matches the committed account.
    """
    clean = validate_username(completion.username)
    healed = _self_heal(db, completion.subject, clean)
    if healed is not None:
        return healed
    linked_at = datetime.now(UTC).isoformat()
    with db.catalog_transaction(immediate=True):
        existing_id = db.get_linked_sign_in_account_id(PROVIDER, completion.subject)
        if existing_id is not None:
            if db.is_live_account(db.get_account(existing_id)):
                raise SignUpConflictError(ALREADY_LINKED)
            # A dead account's link is replaced here, in the same transaction.
            db.remove_linked_sign_in(PROVIDER, completion.subject)
        if not _is_free(db, clean):
            raise SignUpConflictError(USERNAME_TAKEN)
        account_id = db.create_account(clean, display_language=completion.display_language)
        if account_id is None:
            raise SignUpConflictError(USERNAME_TAKEN)
        try:
            db.link_sign_in(PROVIDER, completion.subject, account_id, linked_at=linked_at)
        except sqlite3.IntegrityError:
            # UNIQUE(provider, subject): the other completion won the race, and
            # unwinding here takes the freshly created account with it.
            raise SignUpConflictError(ALREADY_LINKED) from None
        _store_signup_recovery_email(db, account_id, completion)
    account = db.get_account(account_id) or {}
    # Materialise the ledger, as registration does when it stores the hash, so
    # the session this returns passes the registry's ledger-existence gate.
    # If this fails, the committed account + link are self-healed by the next
    # sign-in or retry (see _self_heal).
    ledger_id = _materialise_ledger(db, account, fallback=clean)
    return {
        "ok": True,
        "account_id": account_id,
        "trainee_id": ledger_id,
        "session_epoch": account.get("session_epoch", 1),
        "display_language": account.get("display_language", "en"),
    }


def link_account(db: Any, account_id: str, identity: GoogleIdentity) -> dict[str, Any]:
    """Connects a verified Google identity to the signed-in caller's account (#114).

    Idempotent when that exact subject is already connected. Both conflict
    directions are refused with their own message and neither ever reveals
    *which* other account is involved: a subject held by a live account answers
    :data:`LINKED_ELSEWHERE`, and a caller who already connected a different
    Google identity is told to disconnect that one first (:data:`DIFFERENT_GOOGLE`).

    A subject whose only link points at a deleted account is treated as free —
    the same rule sign-in applies — and repointed here, inside this one
    catalog transaction, so no second account is ever created for it. The
    session epoch is untouched: connecting is not a credential change.
    """
    subject = identity.sub
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_player"]:
        return {"ok": False, "error": "Trainee ledger not found."}
    linked_at = datetime.now(UTC).isoformat()
    with db.catalog_transaction():
        holder = db.get_linked_sign_in_account_id(PROVIDER, subject)
        if holder == account_id:
            _verify_matching_recovery_email(db, account_id, identity)
            return {"ok": True, "message": "Google account already connected."}
        if holder is not None:
            if db.is_live_account(db.get_account(holder)):
                raise SignInMethodError(LINKED_ELSEWHERE)
            db.remove_linked_sign_in(PROVIDER, subject)
        connected = db.get_linked_sign_in_subject(account_id, PROVIDER)
        if connected is not None and connected != subject:
            raise SignInMethodError(DIFFERENT_GOOGLE)
        try:
            db.link_sign_in(PROVIDER, subject, account_id, linked_at=linked_at)
        except sqlite3.IntegrityError:
            raise _link_conflict(db, account_id, subject) from None
        _verify_matching_recovery_email(db, account_id, identity)
    return {"ok": True, "message": "Google account connected."}


def _verified_email(identity: GoogleIdentity) -> str | None:
    if identity.email_verified is not True:
        return None
    return password_reset.normalize_email(identity.email)


def _verify_matching_recovery_email(
    db: Any, account_id: str, identity: GoogleIdentity | None
) -> None:
    if identity is None:
        return
    email = _verified_email(identity)
    if email is not None:
        db.mark_recovery_email_verified_if_matches(account_id, email)


def _store_signup_recovery_email(
    db: Any, account_id: str, completion: GoogleSignupCompletion
) -> None:
    if completion.recovery_email_conflict:
        return
    identity = completion.identity
    if identity is None:
        return
    email = _verified_email(identity)
    if email is None or db.get_account_by_email(email) is not None:
        return
    db.set_account_email(account_id, email)
    db.mark_recovery_email_verified_if_matches(account_id, email)


def _link_conflict(db: Any, account_id: str, subject: str) -> SignInMethodError:
    """Names which unique constraint refused the insert, without leaking who.

    ``UNIQUE(provider, subject)`` means the identity is connected to another
    account (:data:`LINKED_ELSEWHERE`); ``UNIQUE(account_id, provider)`` — an
    account holds at most one link per provider (#114) — means this account
    already connected a *different* identity, so the caller must disconnect it
    first (:data:`DIFFERENT_GOOGLE`). Both answers stay generic: neither says
    which other account is involved.
    """
    holder = db.get_linked_sign_in_account_id(PROVIDER, subject)
    if holder is not None and holder != account_id:
        return SignInMethodError(LINKED_ELSEWHERE)
    return SignInMethodError(DIFFERENT_GOOGLE)


def unlink_account(db: Any, account_id: str) -> dict[str, Any]:
    """Disconnects the caller's Google identity, refused unless a password exists.

    The glossary rule (CONTEXT.md, "Linked sign-in"): an account always keeps
    at least one way to sign in, so a Google-only account must set a password
    first (:data:`NEEDS_PASSWORD`) and nothing is written before that check
    passes. An account with no link is an idempotent no-op, and removing a link
    never bumps the session epoch.
    """
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_player"]:
        return {"ok": False, "error": "Trainee ledger not found."}
    if db.get_linked_sign_in_subject(account_id, PROVIDER) is None:
        return {"ok": True, "message": "No Google account was connected."}
    if not auth_service.account_has_password(db, account):
        raise SignInMethodError(NEEDS_PASSWORD)
    with db.catalog_transaction():
        subject = db.get_linked_sign_in_subject(account_id, PROVIDER)
        if subject is not None:
            db.remove_linked_sign_in(PROVIDER, subject)
    return {"ok": True, "message": "Google account disconnected."}


def _self_heal(db: Any, subject: str, expected_username: str) -> dict[str, Any] | None:
    """Repairs a completion retry only for its originally requested username.

    A completion may have committed the account and the link and then died
    creating the ledger file. A retry with the same username recreates the
    ledger and issues the session; a different username keeps the linked
    account conflict instead of adopting that account as its own retry.
    """
    account_id = db.get_linked_sign_in_account_id(PROVIDER, subject)
    account = db.get_account(account_id) if account_id else None
    if (
        not db.is_live_account(account)
        or account["username"] != expected_username
        or db.ledger_exists(account["ledger_id"])
    ):
        return None
    ledger_id = _materialise_ledger(db, account)
    return {
        "ok": True,
        "account_id": account["account_id"],
        "trainee_id": ledger_id,
        "session_epoch": account["session_epoch"],
    }


def _materialise_ledger(db: Any, account: dict[str, Any], fallback: str | None = None) -> str:
    """Creates the account's ledger file when it is missing; returns its id.

    Registration creates the ledger as it stores the password hash; a Google
    account has no hash, so the file is created here — idempotently, so a
    repaired account and a fresh one behave identically.
    """
    ledger_id = str(account.get("ledger_id") or fallback or "")
    if not ledger_id:
        # Invariant: every catalog account carries a ledger id (NOT NULL).
        raise RuntimeError("Account has no ledger id; refusing to guess one.")
    if not db.ledger_exists(ledger_id):
        with db.open_ledger(ledger_id):
            pass
    return ledger_id


def _is_free(db: Any, clean: str) -> bool:
    """True when no live account owns ``clean`` and no ledger file claims it."""
    return (
        db.get_active_account_by_username(clean) is None
        and not db.ledger_exists(clean)
        and not db.is_username_held(clean)
    )


def _base_from_given_name(given_name: Any) -> str:
    base = re.sub(r"[^a-z0-9_-]", "", str(given_name or "").lower())[:MAX_USERNAME_LENGTH]
    if len(base) < MIN_USERNAME_LENGTH:
        return _SUGGESTION_FALLBACK
    return base
