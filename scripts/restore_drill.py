"""Restore backups into an isolated scratch directory and verify SQLite integrity."""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.backup import CATALOG_SNAPSHOT_NAME, LEDGERS_SUBDIR, list_daily_backups
from database.database_manager import DEFAULT_BACKUPS_DIR
from scripts.litestream_restore import restore_litestream


def _contains_mayos_databases(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(
        item.is_file() and item.name in {"catalog.db", "deletions.db"}
        or item.is_file() and item.parent.name == "users" and item.suffix == ".db"
        for item in path.rglob("*.db")
    )


def _validate_target(target: Path, live_data_dir: Path) -> None:
    target = target.resolve()
    live = live_data_dir.resolve()
    if target == live or live in target.parents:
        raise ValueError(f"Refusing restore target at or inside live data directory: {target}")
    if _contains_mayos_databases(target):
        raise ValueError(f"Refusing restore target that already contains MAYOS databases: {target}")
    if target.exists() and (not target.is_dir() or next(target.iterdir(), None) is not None):
        raise FileExistsError(f"Restore target must be a new or empty directory: {target}")


def _copy_daily_snapshot(snapshot: Path, target: Path) -> int:
    catalog = snapshot / CATALOG_SNAPSHOT_NAME
    if not catalog.is_file():
        raise FileNotFoundError(f"Daily snapshot has no {CATALOG_SNAPSHOT_NAME}: {snapshot}")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(catalog, target / CATALOG_SNAPSHOT_NAME)
    ledgers = sorted((snapshot / LEDGERS_SUBDIR).glob("*.db"))
    if ledgers:
        (target / "users").mkdir(parents=True, exist_ok=True)
        for ledger in ledgers:
            shutil.copy2(ledger, target / "users" / ledger.name)
    return 1 + len(ledgers)


def _integrity_results(target: Path) -> list[tuple[Path, str, int]]:
    databases = sorted(target.rglob("*.db"))
    if not databases:
        raise RuntimeError("Restore produced no databases.")
    results = []
    for database in databases:
        with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as connection:
            rows = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
        result = "; ".join(rows)
        results.append((database, result, database.stat().st_size))
    return results


def run_drill(target: Path, *, source: str, backups_dir: Path, live_data_dir: Path) -> dict:
    target = target.expanduser().absolute()
    _validate_target(target, live_data_dir)
    started = time.monotonic()
    target.parent.mkdir(parents=True, exist_ok=True)
    if source == "r2":
        count = restore_litestream(target)
    else:
        candidates = list_daily_backups(backups_dir)
        if not candidates:
            raise FileNotFoundError(f"No valid daily snapshots found under {backups_dir}.")
        count = _copy_daily_snapshot(candidates[-1], target)
    results = _integrity_results(target)
    duration = time.monotonic() - started
    return {"source": source, "target": target, "count": count, "results": results, "duration": duration}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore backups to scratch and run SQLite integrity checks.")
    parser.add_argument("target", type=Path, help="new or empty scratch directory")
    parser.add_argument("--source", choices=("r2", "daily"), default="r2", help="Litestream replicas or latest daily snapshot")
    parser.add_argument("--backups-dir", type=Path, default=DEFAULT_BACKUPS_DIR)
    parser.add_argument("--live-data-dir", type=Path, default=Path(os.getenv("MAYOS_DATA_DIR", "/data")))
    args = parser.parse_args(argv)
    try:
        report = run_drill(args.target, source=args.source, backups_dir=args.backups_dir, live_data_dir=args.live_data_dir)
    except (ValueError, FileExistsError, FileNotFoundError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"Restore source: {report['source']}")
    print(f"Restored databases: {report['count']}")
    for path, integrity, size in report["results"]:
        print(f"{path}: {size} bytes; integrity_check={integrity}")
    if report["source"] == "daily":
        print("Daily snapshots intentionally exclude deletions.db; see ADR 039/044.")
    print(f"Total duration: {report['duration']:.2f} seconds")
    return 0 if all(result == "ok" for _, result, _ in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
