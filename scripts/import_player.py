"""Owner-run, opt-in import of one consenting person's training ledger (#42, ADR 019).

Run this from the ops console for a single real person at a time. It takes a
consistent SQLite snapshot of one source ledger file, migrates it, creates a new
immutable account, and verifies per-table record counts before cutover. There is
no directory, glob, or bulk mode and no override for a source that looks like
development/test/fixture data.

On success the printed claim code is shown once. Give it to the person out of
band; they use it on the claim screen to set their first password. Only the
code's SHA-256 hash is stored, and it is single-use and expiring, so re-running
this script is the only way to see a fresh code.

Usage:
    python scripts/import_player.py db/users/realuser.db \\
        --username realuser \\
        --opt-in-reference "in-person 2026-09-28, signed consent note 12" \\
        [--ttl-hours 72]
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
from database.offsite_backup import configure_r2_backup  # noqa: E402
from service import imports as import_service  # noqa: E402
from utils.logger import MyosLogger  # noqa: E402

logger = MyosLogger().get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import one consenting person's training ledger under a new account identity."
    )
    parser.add_argument("source", help="Path to the single source ledger file to import.")
    parser.add_argument("--username", required=True, help="New username for the imported account.")
    parser.add_argument(
        "--opt-in-reference",
        required=True,
        dest="opt_in_reference",
        help="How and when the person explicitly consented (recorded in the import audit).",
    )
    parser.add_argument(
        "--ttl-hours",
        type=int,
        default=None,
        dest="ttl_hours",
        help="Claim-code lifetime in hours, 1–720 (default: 72).",
    )
    parser.add_argument("--catalog", default=os.getenv("CATALOG_PATH", str(DEFAULT_CATALOG_PATH)))
    parser.add_argument("--users-dir", dest="ledgers_dir", default=os.getenv("USERS_DIR", str(DEFAULT_LEDGERS_DIR)))
    parser.add_argument("--backups-dir", default=os.getenv("BACKUPS_DIR", str(DEFAULT_BACKUPS_DIR)))
    args = parser.parse_args(argv)

    source = Path(args.source)
    if source.is_dir():
        parser.error("source must be a single ledger file; directories and bulk import are not supported.")
    if args.ttl_hours is not None and not (
        import_service.MIN_CLAIM_TTL_HOURS <= args.ttl_hours <= import_service.MAX_CLAIM_TTL_HOURS
    ):
        parser.error(
            f"--ttl-hours must be between {import_service.MIN_CLAIM_TTL_HOURS} and "
            f"{import_service.MAX_CLAIM_TTL_HOURS} hours."
        )

    db = DatabaseManager(catalog_path=args.catalog, ledgers_dir=args.ledgers_dir, backups_dir=args.backups_dir)
    db.offsite_backup = configure_r2_backup(
        lock_path=Path(args.backups_dir) / ".offsite-r2.lock",
        log_disabled=True,
    )
    try:
        result = import_service.import_player(
            db,
            source,
            args.username,
            args.opt_in_reference,
            ttl_hours=args.ttl_hours,
        )
    finally:
        db.catalog_conn.close()

    if not result["ok"]:
        print(f"error: {result['error']}")
        return 2

    counts = ", ".join(f"{table}={count}" for table, count in sorted(result["counts"].items()))
    logger.info(
        "Imported %s as account %s (ledger %s).",
        source.name,
        result["account_id"],
        result["ledger_id"],
    )
    print(f"Imported {source.name} for '{result['username']}' (account {result['account_id']}).")
    print(f"Ledger: {result['ledger_id']}")
    print(f"Verified record counts: {counts}")
    print(f"Claim code expires at: {result['expires_at']}")
    print("Give this single-use claim code to the person out of band:")
    print(result["claim_code"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
