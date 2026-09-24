"""Owner issuance of a single-use coach invitation (closed-trial only).

The owner runs this from the ops console to enable the coach capability for a
specific, already-registered account. The printed code is account-bound,
single-use, and expiring; hand it to the invited person out of band. Only the
token's SHA-256 hash is stored, so re-running this script is the only way to see
a fresh code. There is deliberately no public HTTP issuance endpoint.

Usage:
    python scripts/issue_coach_invite.py <username> [--ttl-minutes 1440]
    python scripts/issue_coach_invite.py <username> --users-dir /data/users
"""

import argparse
import os
import sys
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.database_manager import (  # noqa: E402
    DEFAULT_BACKUPS_DIR,
    DEFAULT_CATALOG_PATH,
    DEFAULT_USERS_DIR,
    DatabaseManager,
)
from service import coach as coach_service  # noqa: E402
from utils.logger import MyosLogger  # noqa: E402

logger = MyosLogger().get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Issue a single-use, account-bound coach invite.")
    parser.add_argument("username", help="Username of the account receiving the coach capability.")
    parser.add_argument(
        "--ttl-minutes",
        type=int,
        default=None,
        help="Invite lifetime in minutes, 5–43200 (default: COACH_INVITE_TTL_MINUTES or 1440).",
    )
    parser.add_argument("--catalog", default=os.getenv("CATALOG_PATH", str(DEFAULT_CATALOG_PATH)))
    parser.add_argument("--users-dir", default=os.getenv("USERS_DIR", str(DEFAULT_USERS_DIR)))
    parser.add_argument("--backups-dir", default=os.getenv("BACKUPS_DIR", str(DEFAULT_BACKUPS_DIR)))
    args = parser.parse_args(argv)

    if args.ttl_minutes is not None and args.ttl_minutes <= 0:
        parser.error("--ttl-minutes must be a positive number of minutes.")

    # Fresh singleton state so custom dirs apply even in long-lived shells.
    DatabaseManager._instance = None
    DatabaseManager._local = threading.local()
    db = DatabaseManager(catalog_path=args.catalog, users_dir=args.users_dir, backups_dir=args.backups_dir)
    try:
        result = coach_service.issue_coach_invite(db, args.username, ttl_minutes=args.ttl_minutes)
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()

    if not result["ok"]:
        print(f"error: {result['error']}")
        return 2
    logger.info("Issued coach invite for account %s (expires %s).", result["account_id"], result["expires_at"])
    print(f"Coach invite for '{result['username']}' (account {result['account_id']}).")
    print(f"Expires at: {result['expires_at']}")
    print("Give this one-time code to the invited person:")
    print(result["token"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
