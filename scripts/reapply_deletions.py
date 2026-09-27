"""Full deletion-record replay for the restore path (ADR 015/039).

Run this after restoring ``catalog.db``/ledgers from a backup while keeping the
CURRENT ``deletions.db``. It force-deletes every recorded account and removes any
ledger the restored catalog reintroduced, so a pre-deletion catalog snapshot
cannot resurrect a deleted identity.

Usage:
    python scripts/reapply_deletions.py
    python scripts/reapply_deletions.py --catalog /data/catalog.db --users-dir /data/users
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
    DEFAULT_USERS_DIR,
    DatabaseManager,
)
from utils.logger import MyosLogger  # noqa: E402

logger = MyosLogger().get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reapply every durable account-deletion record.")
    parser.add_argument("--catalog", default=os.getenv("CATALOG_PATH", str(DEFAULT_CATALOG_PATH)))
    parser.add_argument("--users-dir", default=os.getenv("USERS_DIR", str(DEFAULT_USERS_DIR)))
    parser.add_argument("--backups-dir", default=os.getenv("BACKUPS_DIR", str(DEFAULT_BACKUPS_DIR)))
    args = parser.parse_args(argv)

    db = DatabaseManager(catalog_path=args.catalog, users_dir=args.users_dir, backups_dir=args.backups_dir)
    try:
        applied = db.reapply_deletions()
    finally:
        db.catalog_conn.close()

    logger.info("Deletion replay complete: %s record(s) rechecked.", applied)
    print(f"Deletion replay complete: {applied} record(s) rechecked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
