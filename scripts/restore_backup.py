"""Restore a daily snapshot and reapply deletions (issue #41, ADR 015/039/044).

Two modes:

* **Scheduled boot-time restore (Fly).** ``--on-next-boot`` only validates the
  snapshot and atomically writes a pending-restore marker; the API Machine
  applies it on its next boot, before it serves. This is required on Fly because
  the single API Machine is the only writer that can mount ``/data`` and cannot
  be scaled to zero for an offline restore:

      python scripts/restore_backup.py --latest --on-next-boot
      fly machine restart <id>        # or: fly apps restart mayos-api

* **Immediate restore (local/offline).** Without ``--on-next-boot`` the snapshot
  is restored right now, for use when the API is stopped and holds no catalog.

Either way the CURRENT durable deletion record is kept and reapplied, never the
snapshot's copy, so a pre-deletion snapshot cannot resurrect a deleted identity.
"""

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.backup import (  # noqa: E402
    list_daily_backups,
    restore_daily_backup,
    schedule_restore,
)
from database.database_manager import (  # noqa: E402
    DEFAULT_BACKUPS_DIR,
    DEFAULT_CATALOG_PATH,
    DEFAULT_LEDGERS_DIR,
    DatabaseManager,
)
from utils.logger import MyosLogger  # noqa: E402

logger = MyosLogger().get_logger(__name__)


def _resolve_snapshot(args, parser) -> Path | None:
    if args.snapshot:
        return Path(args.snapshot)
    if args.latest:
        candidates = list_daily_backups(args.backups_dir)
        if not candidates:
            print(f"No daily snapshots found under {args.backups_dir}.")
            return None
        return candidates[-1]
    parser.error("provide a snapshot directory or --latest")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore a daily snapshot, then reapply deletions.")
    parser.add_argument("snapshot", nargs="?", help="Snapshot directory (default: newest with --latest)")
    parser.add_argument("--latest", action="store_true", help="Use the newest valid daily snapshot.")
    parser.add_argument(
        "--on-next-boot",
        dest="on_next_boot",
        action="store_true",
        help="Validate the snapshot and schedule it for the next API boot instead of restoring now.",
    )
    parser.add_argument("--catalog", default=os.getenv("CATALOG_PATH", str(DEFAULT_CATALOG_PATH)))
    parser.add_argument("--users-dir", dest="ledgers_dir", default=os.getenv("USERS_DIR", str(DEFAULT_LEDGERS_DIR)))
    parser.add_argument("--backups-dir", default=os.getenv("BACKUPS_DIR", str(DEFAULT_BACKUPS_DIR)))
    args = parser.parse_args(argv)

    snapshot = _resolve_snapshot(args, parser)
    if snapshot is None:
        return 1
    if not snapshot.is_dir():
        print(f"Snapshot not found: {snapshot}")
        return 1

    if args.on_next_boot:
        marker = schedule_restore(Path(args.backups_dir), snapshot)
        logger.info("Restore scheduled from %s (marker %s).", snapshot, marker)
        print(
            f"Restore scheduled from {snapshot}; it will apply on the next API boot. "
            f"Now restart the API Machine (fly machine restart <id>) and verify."
        )
        return 0

    db = DatabaseManager(catalog_path=args.catalog, ledgers_dir=args.ledgers_dir, backups_dir=args.backups_dir)
    try:
        summary = restore_daily_backup(snapshot, db=db)
    finally:
        db.catalog_conn.close()

    logger.info("Restore complete: %s", summary)
    print(
        f"Restored {snapshot} (catalog + {len(summary['restored_ledgers'])} ledger(s)); "
        f"reapplied {summary['deletions_reapplied']} deletion(s); "
        f"quarantined {len(summary['quarantined_ledgers'])} orphaned ledger(s). "
        "The current deletions.db was kept and is authoritative."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
