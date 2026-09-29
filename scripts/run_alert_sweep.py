"""Manual run of the alert sweep from the ops console (tickets #31/#32, ADR 030/031).

The service runs this same sweep in-process once at startup and every
``MAYOS_ALERT_SWEEP_INTERVAL_SECONDS`` (default hourly). Run this script on the
always-on Machine to force an immediate pass after a schedule/pause change, a
check-in, or a late data correction.

Usage:
    python scripts/run_alert_sweep.py
    python scripts/run_alert_sweep.py --users-dir /data/users
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
from database.offsite_backup import configure_database_offsite_backup  # noqa: E402
from service import alert_sweep as alerts_service  # noqa: E402
from utils.logger import MyosLogger  # noqa: E402

logger = MyosLogger().get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the missed expected-day alert sweep once.")
    parser.add_argument("--catalog", default=os.getenv("CATALOG_PATH", str(DEFAULT_CATALOG_PATH)))
    parser.add_argument("--users-dir", dest="ledgers_dir", default=os.getenv("USERS_DIR", str(DEFAULT_LEDGERS_DIR)))
    parser.add_argument("--backups-dir", default=os.getenv("BACKUPS_DIR", str(DEFAULT_BACKUPS_DIR)))
    args = parser.parse_args(argv)

    db = DatabaseManager(catalog_path=args.catalog, ledgers_dir=args.ledgers_dir, backups_dir=args.backups_dir)
    configure_database_offsite_backup(db, log_disabled=True)
    try:
        counts = alerts_service.run_sweep(db)
    finally:
        db.catalog_conn.close()

    logger.info("Alert sweep complete: %s", counts)
    print(
        "Sweep complete: "
        f"{counts['evaluated']} evaluated, {counts['alerts_created']} alerts created, "
        f"{counts['alerts_resolved']} resolved, {counts['follow_ups_created']} follow-ups created, "
        f"{counts['errors']} errors."
    )
    return 1 if counts["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
