"""Force one daily online backup from the ops console (issue #41).

The service runs this same job in-process once at startup and every
``MAYOS_DAILY_BACKUP_INTERVAL_SECONDS`` (default 86400; 0 disables). Run this
script on the always-on Machine to force an immediate pass after a large import
or before a risky migration. A valid snapshot for the current UTC day is left
alone, so running it twice in one day is safe.

Usage:
    python scripts/backup_now.py
    python scripts/backup_now.py --retention-days 14
"""

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.backup import backup_retention_days, create_daily_backup  # noqa: E402
from database.database_manager import (  # noqa: E402
    DEFAULT_BACKUPS_DIR,
    DEFAULT_CATALOG_PATH,
    DEFAULT_LEDGERS_DIR,
    DatabaseManager,
)
from utils.logger import MyosLogger  # noqa: E402

logger = MyosLogger().get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create one consistent daily backup (catalog + live-account ledgers).")
    parser.add_argument("--catalog", default=os.getenv("CATALOG_PATH", str(DEFAULT_CATALOG_PATH)))
    parser.add_argument("--users-dir", dest="ledgers_dir", default=os.getenv("USERS_DIR", str(DEFAULT_LEDGERS_DIR)))
    parser.add_argument("--backups-dir", default=os.getenv("BACKUPS_DIR", str(DEFAULT_BACKUPS_DIR)))
    parser.add_argument(
        "--retention-days",
        type=int,
        default=backup_retention_days(),
        help="Snapshots older than this are pruned (bounded to 30 days, per ADR 015).",
    )
    args = parser.parse_args(argv)

    db = DatabaseManager(catalog_path=args.catalog, ledgers_dir=args.ledgers_dir, backups_dir=args.backups_dir)
    try:
        summary = create_daily_backup(db, retention_days=args.retention_days)
    finally:
        db.catalog_conn.close()

    if summary["skipped"]:
        print(f"A valid backup already exists for {summary['date']}: {summary['path']}")
        return 0
    logger.info("Daily backup complete: %s", summary)
    print(
        f"Backup {summary['date']} written to {summary['path']} "
        f"(catalog + {len(summary['ledgers'])} ledger(s)); pruned {len(summary['pruned'])} old snapshot(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
