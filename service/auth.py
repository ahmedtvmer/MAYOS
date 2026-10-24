"""Player registration, login, and first password. Returns plain dicts; no session state.

Proof level is password possession. Unknown users and wrong passwords are
indistinguishable (``Invalid credentials.``); only registration reveals
ID-taken, which is inherent to signup.
"""

from dataclasses import dataclass
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt

from service import acquisition
from service._base import ledger_scope
from service.credential_locks import account_credential_lock
from service.coach import (
    DEFAULT_CAPACITY,
    GENERIC_NEW_ACCOUNT_INVITE_ERROR,
)
from service._tokens import hash_token

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
INVALID_CREDENTIALS = "Invalid credentials."
MIN_COACH_INVITE_CODE_LENGTH = 10
MAX_COACH_INVITE_CODE_LENGTH = 128
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"constant-time-login-check", bcrypt.gensalt()).decode("utf-8")


def _login_lockout_setting(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default

USERNAME_TAKEN = "This Trainee ID already exists. Please log in."


@dataclass(frozen=True)
class PlayerRegistration:
    coach_invite_code: str | None = None
    display_language: str = "en"
    first_touch: dict[str, Any] | None = None


def validate_password(password: Any) -> str:
    if not isinstance(password, str) or not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError(f"Password must be {MIN_PASSWORD_LENGTH}–{MAX_PASSWORD_LENGTH} characters.")
    return password


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def register_player(
    db: Any,
    username: str,
    password: str,
    registration: PlayerRegistration = PlayerRegistration(),
) -> dict[str, Any]:
    """Creates an immutable account identity plus its ledger.

    A username that already has a live account, or an unenrolled local ledger,
    is refused so existing local ledgers are never silently adopted (issue #42
    owns opted-in import).
    """
    clean_id = db._sanitize_username(username)
    coach_granted_at = None
    normalized_first_touch = acquisition.normalize_first_touch(registration.first_touch)
    if not clean_id:
        return {"ok": False, "error": "Trainee ID is empty after sanitization."}
    if registration.coach_invite_code is not None:
        try:
            validate_password(password)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "code": "weak_new"}
        if not isinstance(registration.coach_invite_code, str) or not (
            MIN_COACH_INVITE_CODE_LENGTH
            <= len(registration.coach_invite_code)
            <= MAX_COACH_INVITE_CODE_LENGTH
        ):
            return {"ok": False, "error": GENERIC_NEW_ACCOUNT_INVITE_ERROR, "code": "invalid_coach_invite"}
        coach_granted_at = datetime.now(UTC).isoformat()
        with db.catalog_transaction(immediate=True):
            account = db.register_account_with_coach_invite(
                hash_token(registration.coach_invite_code),
                clean_id,
                coach_granted_at,
                DEFAULT_CAPACITY,
                registration.display_language,
            )
            if account is not None:
                account_id = account["account_id"]
                db.record_first_touch_acquisition_once(account_id, normalized_first_touch)
        if account is None:
            return {"ok": False, "error": GENERIC_NEW_ACCOUNT_INVITE_ERROR, "code": "invalid_coach_invite"}
    else:
        if (
            db.get_active_account_by_username(clean_id) is not None
            or db.ledger_exists(clean_id)
            or db.is_username_held(clean_id)
        ):
            return {"ok": False, "error": USERNAME_TAKEN, "code": "username_taken"}
        try:
            validate_password(password)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        with db.catalog_transaction(immediate=True):
            account_id = db.create_account(
                clean_id,
                display_language=registration.display_language,
            )
            if account_id is not None:
                db.record_first_touch_acquisition_once(account_id, normalized_first_touch)
    if account_id is None:
        return {"ok": False, "error": USERNAME_TAKEN, "code": "username_taken"}
    account = db.get_account(account_id) or {}
    # A reused username gets a fresh ledger id (see DatabaseManager.create_account),
    # so always mount the account's own ledger rather than the username.
    ledger_id = account.get("ledger_id") or clean_id
    with db.open_ledger(ledger_id) as ledger:
        ledger.set_password_hash(hash_password(password))
    account = db.get_account(account_id) or account
    return {
        "ok": True,
        "trainee_id": ledger_id,
        "account_id": account_id,
        "coach_granted_at": coach_granted_at,
        "session_epoch": account.get("session_epoch", 1),
        "display_language": account.get("display_language", "en"),
        "first_touch": normalized_first_touch,
    }


def clear_account_login_failures(db: Any, account_id: str) -> None:
    with db.catalog_transaction(immediate=True):
        db.catalog_conn.execute(
            "DELETE FROM account_login_failures WHERE account_id = ?", (account_id,)
        )


def _verify_account_password_locked(db: Any, account: dict[str, Any], password: Any) -> bool:
    """Checks the stored hash and records a login outcome while account-locked."""
    account = db.get_account(account["account_id"])
    if not db.is_live_account(account) or not db.ledger_exists(account["ledger_id"]):
        verify_password(password if isinstance(password, str) else "", _DUMMY_PASSWORD_HASH)
        return False
    with db.open_ledger(account["ledger_id"]) as ledger:
        stored_hash = ledger.get_password_hash()
    if not stored_hash:
        verify_password(password if isinstance(password, str) else "", _DUMMY_PASSWORD_HASH)
        return False
    password_matches = verify_password(password if isinstance(password, str) else "", stored_hash)
    return _record_password_login_outcome(db, account["account_id"], password_matches)


def _record_password_login_outcome(db: Any, account_id: str, password_matches: bool) -> bool:
    threshold = _login_lockout_setting("LOGIN_LOCKOUT_THRESHOLD", 10)
    window = _login_lockout_setting("LOGIN_LOCKOUT_WINDOW_SECONDS", 900)
    cooldown = _login_lockout_setting("LOGIN_LOCKOUT_COOLDOWN_SECONDS", 900)
    with db.catalog_transaction(immediate=True):
        now = datetime.now(UTC)
        row = db.catalog_conn.execute(
            "SELECT failed_at, failure_count, locked_until FROM account_login_failures WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        if row and row[2] and row[2] > now.isoformat():
            return False
        if password_matches:
            db.catalog_conn.execute("DELETE FROM account_login_failures WHERE account_id = ?", (account_id,))
            return True
        inside_window = bool(row and (now - datetime.fromisoformat(row[0])).total_seconds() < window)
        failure_count = int(row[1]) + 1 if inside_window else 1
        locked_until = (now + timedelta(seconds=cooldown)).isoformat() if failure_count == threshold else None
        db.catalog_conn.execute(
            "INSERT INTO account_login_failures(account_id, failed_at, failure_count, locked_until) "
            "VALUES(?, ?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET "
            "failed_at=CASE WHEN ? THEN account_login_failures.failed_at ELSE excluded.failed_at END, "
            "failure_count=excluded.failure_count, locked_until=excluded.locked_until",
            (account_id, now.isoformat(), failure_count, locked_until, int(inside_window)),
        )
    return False


def verify_account_password(db: Any, account: dict[str, Any] | None, password: Any) -> bool:
    """Checks a password under its cross-process account lock."""
    if account is None or not db.ledger_exists(account["ledger_id"]):
        verify_password(password if isinstance(password, str) else "", _DUMMY_PASSWORD_HASH)
        return False
    with account_credential_lock(account["account_id"], db.catalog_path):
        return _verify_account_password_locked(db, account, password)


def login_player(db: Any, username: str, password: str) -> dict[str, Any]:
    clean_id = db._sanitize_username(username)
    account = db.get_active_account_by_username(clean_id) if clean_id else None
    if account is None:
        verify_account_password(db, None, password)
        return {"ok": False, "error": INVALID_CREDENTIALS}
    # The first lookup supplies the immutable lock key; refresh the account and
    # read the epoch again only after entering that account's credential lock.
    with account_credential_lock(account["account_id"], db.catalog_path):
        account = db.get_active_account_by_username(clean_id)
        if account is None or not _verify_account_password_locked(db, account, password):
            return {"ok": False, "error": INVALID_CREDENTIALS}
        account = db.get_account(account["account_id"])
        if account is None:
            return {"ok": False, "error": INVALID_CREDENTIALS}
    with db.open_ledger(account["ledger_id"]) as ledger:
        profile = ledger.get_player_profile()
        return {
            "ok": True,
            "trainee_id": account["ledger_id"],
            "account_id": account["account_id"],
            "session_epoch": account["session_epoch"],
            "display_language": account.get("display_language", "en"),
            "has_profile": bool(profile),
            "profile": profile,
            "active_program": ledger.get_active_program() if profile else None,
        }


def account_has_password(db: Any, account: dict[str, Any] | None) -> bool:
    """True when the account's ledger carries a password hash (short-lived mount).

    One helper for every "does this account have a password?" question
    (``/auth/me``, disconnect, set-password, #114), so they cannot disagree.
    A missing ledger answers False: there is nothing to sign in with.
    """
    if not account or not db.ledger_exists(account["ledger_id"]):
        return False
    with db.open_ledger(account["ledger_id"]) as ledger:
        return ledger.get_password_hash() is not None


def _password_already_set() -> dict[str, Any]:
    return {
        "ok": False,
        "error": "A password is already set. Use change-password to change it.",
        "code": "password_exists",
    }


def set_initial_password(db: Any, account_id: str, new_password: Any) -> dict[str, Any]:
    """Authenticated: gives a passwordless account its first password (#114).

    Only an account that has **no** password may use it; one that already has a
    password is pointed at ``change-password`` instead. Validation is
    :func:`validate_password`, the same rule registration and claim use.

    The first password is written with :meth:`set_password_hash_if_absent`, so
    the "no password yet" check and the write are one conditional statement:
    two concurrent first-set requests cannot both succeed — the loser gets the
    same ``password_exists`` refusal as an account that already had one.

    Deliberately does **not** bump the session epoch: adding a sign-in method
    must not sign anyone out (connect, disconnect, and the first password all
    share this rule), while changing an existing password still does.
    """
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_player"] or not db.ledger_exists(account["ledger_id"]):
        return {"ok": False, "error": "Trainee ledger not found."}
    with db.open_ledger(account["ledger_id"]) as ledger:
        if ledger.get_password_hash() is not None:
            return _password_already_set()
        try:
            clean = validate_password(new_password)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "code": "weak_new"}
        if not ledger.set_password_hash_if_absent(hash_password(clean)):
            # Another first-set landed between our read and the write.
            return _password_already_set()
    return {"ok": True, "trainee_id": account["ledger_id"], "account_id": account_id}


def change_password(
    db: Any, account_id: str, current_password: str, new_password: str, ledger: Any | None = None
) -> dict[str, Any]:
    """Authenticated password change. Revokes all sessions via the registry epoch.

    ``account_id`` is the immutable id verified from the caller's JWT, never a
    reusable username: resolving by id means a request that raced a delete and
    username reuse cannot touch the new account that inherited the name. The
    account must still be a live player whose ledger exists.

    The caller is already JWT-authenticated, so a wrong current password is
    reported plainly (400-class ``error``); route layers must NOT map this to
    401 or clients will treat it as session expiry.
    """
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_player"] or not db.ledger_exists(account["ledger_id"]):
        return {"ok": False, "error": "Trainee ledger not found."}
    with account_credential_lock(account["account_id"], db.catalog_path):
        with ledger_scope(db, ledger, account["ledger_id"]) as handle:
            stored = handle.get_password_hash()
            if stored is None:
                return {"ok": False, "error": "No password is set on this account.", "code": "password_missing"}
            if not isinstance(current_password, str) or not verify_password(current_password, stored):
                return {"ok": False, "error": "Current password is incorrect.", "code": "bad_current"}
            try:
                clean_new_password = validate_password(new_password)
            except ValueError as exc:
                return {"ok": False, "error": str(exc), "code": "weak_new"}
            if verify_password(clean_new_password, stored):
                return {"ok": False, "error": "New password must differ from the current one.", "code": "same_as_current"}
            new_password_hash = hash_password(clean_new_password)
            with db.catalog_transaction(immediate=True):
                now_iso = datetime.now(UTC).isoformat()
                db.invalidate_unused_reset_tokens(account["account_id"], now_iso)
                new_version = db.bump_account_session_epoch(account["account_id"])
            if new_version is None:
                return {"ok": False, "error": "Trainee ledger not found."}
            handle.set_password_hash(new_password_hash)
        clear_account_login_failures(db, account["account_id"])
    return {
        "ok": True,
        "trainee_id": account["ledger_id"],
        "account_id": account["account_id"],
        "token_version": new_version,
    }
