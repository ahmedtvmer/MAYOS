"""Admin password reset: set a new password for a player ledger from the ops console.

For an enrolled account, revokes ALL sessions by mandatorily advancing the
catalog registry session epoch (a bare local ledger falls back to the ledger
token version). Use when a player loses access and self-service email recovery
is unavailable.

Usage:
    python scripts/reset_password.py <ledger_id> [--password NEWPASS]
    python scripts/reset_password.py <ledger_id> --users-dir /data/users

Without --password, the operator is prompted securely (getpass, no echo).
"""

import argparse
import getpass
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.database_manager import (  # noqa: E402
    DEFAULT_BACKUPS_DIR,
    DEFAULT_CATALOG_PATH,
    DEFAULT_LEDGERS_DIR,
    DatabaseManager,
)
from service import auth as auth_service  # noqa: E402
from utils.logger import MyosLogger  # noqa: E402

logger = MyosLogger().get_logger(__name__)


def reset_password(db: DatabaseManager, ledger_id: str, new_password: str) -> tuple[str, int, bool]:
    """Set a fresh password and revoke the account's sessions.

    Returns ``(ledger_id, epoch, enrolled)``. For an enrolled account, ``epoch``
    is the new registry session epoch and advancing it is mandatory: registry
    verification is what actually revokes live API sessions. For a bare local
    ledger with no registry account, ``epoch`` is the ledger ``token_version``
    and ``enrolled`` is ``False`` (legacy behavior preserved).
    """
    clean_id = db._sanitize_username(ledger_id)
    if not clean_id:
        raise SystemExit(f"error: unknown trainee ledger '{ledger_id}'.")
    account = db.get_active_account_by_username(clean_id)
    # An enrolled account may have a ledger id distinct from its (reused)
    # username; resolve the path through the account, never the username
    # (ADR 015/039). A bare local ledger has no account and uses its username.
    ledger_id = account["ledger_id"] if account is not None else clean_id
    if not db.ledger_exists(ledger_id):
        raise SystemExit(f"error: unknown trainee ledger '{ledger_id}'.")
    try:
        auth_service.validate_password(new_password)
    except ValueError as exc:
        raise SystemExit(f"error: {exc}")
    with db.open_ledger(ledger_id) as ledger:
        ledger.set_password_hash(auth_service.hash_password(new_password))
        ledger_epoch = ledger.bump_token_version()
        if account is not None:
            epoch = db.bump_account_session_epoch(account["account_id"])
            if epoch is None:
                raise SystemExit(
                    "error: could not advance the account registry epoch; sessions were NOT revoked."
                )
        else:
            epoch = ledger_epoch
        ledger.prune_revoked_tokens(datetime.now(UTC).isoformat())
    return ledger_id, epoch, account is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Admin reset of a trainee password (revokes all sessions).")
    parser.add_argument("ledger_id", help="Trainee ID / username of the ledger.")
    parser.add_argument("--password", default=None, help="New password (otherwise prompted securely).")
    parser.add_argument("--catalog", default=os.getenv("CATALOG_PATH", str(DEFAULT_CATALOG_PATH)))
    parser.add_argument("--users-dir", dest="ledgers_dir", default=os.getenv("USERS_DIR", str(DEFAULT_LEDGERS_DIR)))
    parser.add_argument("--backups-dir", default=os.getenv("BACKUPS_DIR", str(DEFAULT_BACKUPS_DIR)))
    args = parser.parse_args(argv)

    new_password = args.password or getpass.getpass("New password (8-128 chars): ")
    if not args.password:
        confirm = getpass.getpass("Confirm new password: ")
        if new_password != confirm:
            print("error: passwords do not match.")
            return 2

    # A fresh store is built per run, so custom dirs apply even in long-lived shells.
    db = DatabaseManager(catalog_path=args.catalog, ledgers_dir=args.ledgers_dir, backups_dir=args.backups_dir)
    try:
        clean_id, epoch, enrolled = reset_password(db, args.ledger_id, new_password)
    finally:
        db.catalog_conn.close()
    if enrolled:
        logger.info("Password reset for '%s' (registry session epoch now v%s). All sessions revoked.", clean_id, epoch)
        print(f"Password reset for '{clean_id}'. Registry session epoch now v{epoch}; all sessions revoked.")
    else:
        logger.info("Password reset for '%s' (legacy ledger token version now v%s). All sessions revoked.", clean_id, epoch)
        print(f"Password reset for '{clean_id}'. Legacy ledger token version now v{epoch}; all sessions revoked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
