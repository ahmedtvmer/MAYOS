"""Restore all Litestream databases into a new, empty data directory."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from database.litestream import litestream_ledger_replica_path, litestream_replica_path
from database.offsite_backup import R2BackupStore


def _require_empty_directory(target: Path) -> None:
    if target.exists() and (not target.is_dir() or next(target.iterdir(), None) is not None):
        raise FileExistsError(f"Restore target must be an empty directory: {target}")


def _restore_config(source_path: Path, replica_path: str) -> str:
    return "\n".join(
        (
            "dbs:",
            f"  - path: {json.dumps(str(source_path))}",
            "    replica:",
            "      type: s3",
            "      bucket: ${R2_BUCKET}",
            f"      path: {json.dumps(replica_path)}",
            "      endpoint: ${R2_ENDPOINT}",
            "      region: auto",
            "      access-key-id: ${R2_ACCESS_KEY_ID}",
            "      secret-access-key: ${R2_SECRET_ACCESS_KEY}",
            "",
        )
    )


def _restore_database(source_path: Path, target_path: Path, replica_path: str) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".yml", delete=False) as config_file:
        config_file.write(_restore_config(source_path, replica_path))
        config_path = Path(config_file.name)
    try:
        subprocess.run(
            ["litestream", "restore", "-config", str(config_path), "-o", str(target_path), str(source_path)],
            check=True,
        )
    finally:
        config_path.unlink(missing_ok=True)


def _restore_database_set(target: Path, source_root: Path, store: R2BackupStore) -> int:
    databases = [
        (PurePosixPath("catalog.db"), litestream_replica_path("catalog.db")),
        (PurePosixPath("deletions.db"), litestream_replica_path("deletions.db")),
    ]
    databases.extend(
        (PurePosixPath("users") / f"{ledger_id}.db", litestream_ledger_replica_path(ledger_id))
        for ledger_id in store.list_litestream_ledger_ids()
    )
    for relative_path, replica_path in databases:
        _restore_database(source_root / relative_path, target / relative_path, replica_path)
    return len(databases)


def _publish_restore(staging: Path, target: Path) -> None:
    if target.exists():
        if next(target.iterdir(), None) is not None:
            raise FileExistsError(f"Restore target became non-empty during restore: {target}")
        target.rmdir()
    os.replace(staging, target)


def restore_litestream(target: Path) -> int:
    """Restore catalog, deletion log, and every watched ledger into target."""
    target = Path(target).expanduser().absolute()
    _require_empty_directory(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    store = R2BackupStore.from_environment()
    if store is None:
        raise RuntimeError("R2_ENDPOINT, R2_BUCKET, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY are required.")
    source_root = Path(os.getenv("MAYOS_DATA_DIR", "/data")).expanduser().absolute()
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.litestream-", dir=target.parent))
    try:
        restored_count = _restore_database_set(staging, source_root, store)
        _publish_restore(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return restored_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore all Litestream replicas into an empty directory.")
    parser.add_argument("target", type=Path, help="new or empty destination data directory")
    args = parser.parse_args(argv)
    try:
        count = restore_litestream(args.target)
    except FileExistsError as exc:
        parser.error(str(exc))
    print(f"Restored {count} Litestream database(s) into {args.target}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
