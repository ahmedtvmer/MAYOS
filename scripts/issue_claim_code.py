"""Owner issuance of a single-use claim code for an enrolled password-less account.

An imported account (or one whose password hash was cleared) must claim with a
code before it can log in, and only the import path used to mint one. This script
lets the owner issue the same account-bound, single-use, expiring code for an
already-enrolled player account that has no password. The printed code is handed
to the person out of band; only its SHA-256 is stored, so re-running this script
is the only way to see a fresh code.

Refuses a username that is not a live player account or whose ledger already has
a password (use ``scripts/reset_password.py`` for that). There is deliberately no
public HTTP issuance endpoint.

Usage:
    python scripts/issue_claim_code.py <username> [--ttl-hours 72]
    python scripts/issue_claim_code.py <username> --users-dir /data/users
"""

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.database_manager import (  # noqa: E402
    DEFAULT_BACKUPS_DIR,
    DEFAULT_CATALOG_PATH,
    DEFAULT_LEDGERS_DIR,
    DatabaseManager,
)
from service import imports as import_service  # noqa: E402
from utils.logger import MyosLogger  # noqa: E402

logger = MyosLogger().get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Issue a single-use, account-bound claim code for a password-less player account."
    )
    parser.add_argument("username", help="Username of the password-less account to issue a claim code for.")
    parser.add_argument(
        "--ttl-hours",
        type=int,
        default=None,
        help="Claim-code lifetime in hours, 1–720 (default: 72).",
    )
    parser.add_argument("--catalog", default=os.getenv("CATALOG_PATH", str(DEFAULT_CATALOG_PATH)))
    parser.add_argument("--users-dir", dest="ledgers_dir", default=os.getenv("USERS_DIR", str(DEFAULT_LEDGERS_DIR)))
    parser.add_argument("--backups-dir", default=os.getenv("BACKUPS_DIR", str(DEFAULT_BACKUPS_DIR)))
    args = parser.parse_args(argv)

    if args.ttl_hours is not None and not (
        import_service.MIN_CLAIM_TTL_HOURS <= args.ttl_hours <= import_service.MAX_CLAIM_TTL_HOURS
    ):
        parser.error(
            f"--ttl-hours must be between {import_service.MIN_CLAIM_TTL_HOURS} and "
            f"{import_service.MAX_CLAIM_TTL_HOURS} hours."
        )

    # A fresh store is built per run, so custom dirs apply even in long-lived shells.
    db = DatabaseManager(catalog_path=args.catalog, ledgers_dir=args.ledgers_dir, backups_dir=args.backups_dir)
    try:
        result = import_service.issue_claim_code(db, args.username, ttl_hours=args.ttl_hours)
    finally:
        db.catalog_conn.close()

    if not result["ok"]:
        print(f"error: {result['error']}")
        return 2
    logger.info("Issued claim code for account %s (expires %s).", result["account_id"], result["expires_at"])
    print(f"Claim code for '{result['username']}' (account {result['account_id']}).")
    print(f"Expires at: {result['expires_at']}")
    print("Give this single-use code to the person out of band:")
    print(result["token"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
