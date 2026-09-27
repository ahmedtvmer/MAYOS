"""Password-confirmed durable account deletion (ADR 015/039).

The account holder proves possession of their password, then the account is
durably deleted: every session invalidated in the registry, the live ledger and
its backups removed, and a record kept outside the catalog snapshot so a
restored backup cannot resurrect the identity. The caller is JWT-authenticated,
so a wrong password is reported plainly (400-class) and changes nothing; route
layers must NOT map it to 401 or clients will treat it as session expiry.
"""

from datetime import UTC, datetime
from typing import Any

from service._base import bind_user
from service.auth import INVALID_CREDENTIALS, verify_password


def delete_account(db: Any, account_id: str, password: Any) -> dict[str, Any]:
    """Verifies the password and deletes the account and its active data.

    ``account_id`` is the immutable id verified from the caller's JWT, never the
    reusable username, so a request that raced a deletion and username reuse can
    never delete the new account that inherited the name.
    """
    account = db.get_account(account_id)
    if not db.is_live_account(account) or not account["is_player"]:
        return {"ok": False, "error": INVALID_CREDENTIALS}

    bind_user(db, account["ledger_id"])
    stored = db.get_password_hash()
    if stored is None:
        return {"ok": False, "error": INVALID_CREDENTIALS}
    if not isinstance(password, str) or not verify_password(password, stored):
        return {"ok": False, "error": INVALID_CREDENTIALS}

    db.delete_account(account["account_id"], datetime.now(UTC).isoformat())
    return {"ok": True, "account_id": account["account_id"], "trainee_id": account["ledger_id"]}
