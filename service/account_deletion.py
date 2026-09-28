"""Password-confirmed durable account deletion (ADR 015/039).

The account holder proves possession of their password, then the account is
durably deleted: every session invalidated in the registry, the live ledger and
its backups removed, and a record kept outside the catalog snapshot so a
restored backup cannot resurrect the identity. The caller is JWT-authenticated,
so a wrong password is reported plainly (400-class) and changes nothing; route
layers must NOT map it to 401 or clients will treat it as session expiry.

Every refusal — unknown or non-live account, non-player account, a ledger with
no password hash (imported-but-unclaimed, ADR 045), a non-string password, or a
wrong password — spends exactly one bcrypt verification, so neither the in-app
path nor the public web form leaks "does this account exist?" through timing
(#43).
"""

from datetime import UTC, datetime
from typing import Any

from service._base import ledger_scope
from service.auth import INVALID_CREDENTIALS, hash_password, verify_password

# Lazily built so importing this module stays cheap; one bcrypt verification is
# spent against it for every refusal that has no stored hash to compare with.
_UNKNOWN_ACCOUNT_HASH: str | None = None


def _spend_one_bcrypt(password: Any) -> None:
    """Burns exactly one bcrypt verification for a refusal with no stored hash.

    The password is coerced to ``""`` when it is not a string, so a caller that
    skipped validation (the public deletion form) costs the same as a wrong
    password instead of skipping the work and answering faster.
    """
    global _UNKNOWN_ACCOUNT_HASH
    if _UNKNOWN_ACCOUNT_HASH is None:
        _UNKNOWN_ACCOUNT_HASH = hash_password("mayos-unknown-account-equalizer")
    verify_password(password if isinstance(password, str) else "", _UNKNOWN_ACCOUNT_HASH)


def delete_account(db: Any, account_id: str, password: Any, ledger: Any | None = None) -> dict[str, Any]:
    """Verifies the password and deletes the account and its active data.

    ``account_id`` is the immutable id verified from the caller's JWT, never the
    reusable username, so a request that raced a deletion and username reuse can
    never delete the new account that inherited the name.
    """
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_player"]:
        _spend_one_bcrypt(password)
        return {"ok": False, "error": INVALID_CREDENTIALS}

    with ledger_scope(db, ledger, account["ledger_id"]) as ledger:
        stored = ledger.get_password_hash()
        if stored is None:
            _spend_one_bcrypt(password)
            return {"ok": False, "error": INVALID_CREDENTIALS}
        if not verify_password(password if isinstance(password, str) else "", stored):
            return {"ok": False, "error": INVALID_CREDENTIALS}

    db.delete_account(account["account_id"], datetime.now(UTC).isoformat(), ledger_id=account["ledger_id"])
    return {"ok": True, "account_id": account["account_id"], "trainee_id": account["ledger_id"]}


def delete_account_by_username(db: Any, username: Any, password: Any) -> dict[str, Any]:
    """External deletion-request path: resolve the reusable username, then delete.

    The username is normalised exactly as ``service.auth.login_player`` does it
    (``db._sanitize_username`` plus the live-ledger check), so a form submission
    and a login agree on which account is meant. The deletion and its password
    confirmation are then the same code the in-app ``DELETE /auth/account`` runs
    (ADR 015/039); only the way the caller identifies the account differs,
    because a browser form has no session. Every failure returns the same
    ``INVALID_CREDENTIALS`` shape and spends one bcrypt verification, so the
    form can never reveal whether an account exists (#43).
    """
    clean_id = db._sanitize_username(username if isinstance(username, str) else "")
    account = db.get_active_account_by_username(clean_id) if clean_id else None
    if account is None or not account["is_player"] or not db.ledger_exists(account["ledger_id"]):
        _spend_one_bcrypt(password)
        return {"ok": False, "error": INVALID_CREDENTIALS}
    return delete_account(db, account["account_id"], password)
