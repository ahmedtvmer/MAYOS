"""Best-effort off-site daily snapshots in Cloudflare R2.

The API uses :class:`OffsiteBackupStore` as a narrow seam. Its S3 adapter only
stores finished local snapshots, marks a snapshot complete after every object
has uploaded, and keeps deletion cleanup and restore on the same interface.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from database.backup import OffsiteBackupStore, clamp_backup_retention_days
from database.litestream import LEDGER_ID_RE, litestream_ledger_replica_path, litestream_replica_path
from utils.logger import MyosLogger
from utils.r2 import R2_ENV_NAMES as _R2_ENV_NAMES
from utils.r2 import create_r2_client_from_environment as _create_r2_client_from_environment

logger = MyosLogger().get_logger(__name__)

DAILY_PREFIX = "daily/"
COMPLETE_MARKER = "_COMPLETE.json"
SNAPSHOT_DATE_RE = re.compile(r"^\d{8}$")
LEDGER_FILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*\.db$")


class R2BackupStore:
    """Cloudflare R2 adapter using the S3 API; no credentials are logged."""

    def __init__(self, client: Any, bucket: str, lock_path: Path | None = None):
        self._client = client
        self._bucket = bucket
        self._lock = threading.RLock()
        self._lock_path = Path(lock_path) if lock_path is not None else None

    @classmethod
    def from_environment(cls, lock_path: Path | None = None) -> R2BackupStore | None:
        """Build the R2 adapter when all four configured secrets are present."""
        connection = _create_r2_client_from_environment()
        if connection is None:
            return None
        client, bucket = connection
        return cls(client, bucket, lock_path)

    def upload_snapshot(self, snapshot_dir: Path, snapshot_date: str) -> None:
        """Uploads all database files and puts the completion marker last.

        A snapshot with a valid marker is left alone. A partial upload has no
        marker and a rerun overwrites each expected file.
        """
        prefix = self._snapshot_prefix(snapshot_date)
        marker_key = f"{prefix}{COMPLETE_MARKER}"
        snapshot_dir = Path(snapshot_dir)
        files = self._snapshot_files(snapshot_dir)
        if not any(relative == "catalog.db" for relative, _ in files):
            raise FileNotFoundError(f"Snapshot has no catalog.db: {snapshot_dir}")

        with self._operation_lock():
            existing_manifest = self._read_manifest(snapshot_date)
            if existing_manifest is not None and existing_manifest.get("version") == 2:
                return
            self._delete_keys([marker_key])
            self._delete_stale_objects(prefix, files, marker_key)
            manifest = {"version": 2, "date": snapshot_date, "files": self._upload_files(prefix, files)}
            self._write_manifest(snapshot_date, manifest)

    def is_snapshot_complete(self, snapshot_date: str) -> bool:
        """True only when R2 has a valid marker for every uploaded object."""
        with self._operation_lock():
            manifest = self._read_manifest(snapshot_date)
            return manifest is not None and manifest.get("version") == 2

    def remove_ledger(self, ledger_id: str) -> None:
        """Deletes one account's ledger copies from snapshots and Litestream.

        Completed manifests are updated after object deletion so valid snapshots
        remain restorable without the deleted ledger. A failed marker update is
        safe: restore rejects the missing listed object and deletion replay can
        retry the cleanup. Litestream uses one exact prefix per database file.
        """
        if not LEDGER_ID_RE.fullmatch(str(ledger_id)):
            return
        with self._operation_lock():
            keys = self._list_keys(DAILY_PREFIX)
            targets = self._ledger_object_keys(keys, ledger_id)
            self._delete_keys(targets)
            self._remove_ledger_from_manifests(keys, ledger_id)
            replica_prefix = f"{litestream_ledger_replica_path(ledger_id)}/"
            self._delete_keys(self._list_keys(replica_prefix))

    def list_litestream_ledger_ids(self) -> list[str]:
        """List ledger ids with a Litestream replica beneath the watched directory."""
        directory_prefix = f"{litestream_replica_path('users')}/"
        with self._operation_lock():
            keys = self._list_keys(directory_prefix)
        ledger_ids = set()
        for key in keys:
            remainder = key[len(directory_prefix) :]
            filename, separator, replica_object = remainder.partition("/")
            ledger_id = filename.removesuffix(".db")
            if separator and replica_object and filename.endswith(".db") and LEDGER_ID_RE.fullmatch(ledger_id):
                ledger_ids.add(ledger_id)
        return sorted(ledger_ids)

    def prune_snapshots(self, *, retention_days: int, now: datetime | None = None) -> list[str]:
        """Deletes every R2 snapshot older than the local bounded retention."""
        days = clamp_backup_retention_days(retention_days)
        cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
        with self._operation_lock():
            keys = self._list_keys(DAILY_PREFIX)
            old_dates = sorted(
                {
                    snapshot_date
                    for key in keys
                    if (snapshot_date := self._snapshot_date_in_key(key)) is not None
                    and datetime.strptime(snapshot_date, "%Y%m%d").replace(tzinfo=UTC) < cutoff
                }
            )
            for snapshot_date in old_dates:
                self._delete_keys([key for key in keys if key.startswith(f"daily/{snapshot_date}/")])
        return old_dates

    def download_snapshot(self, snapshot_date: str, destination: Path) -> Path:
        """Fetches and validates a complete snapshot into a local directory."""
        destination = Path(destination)
        if destination.exists():
            raise FileExistsError(f"Restore destination already exists: {destination}")
        with self._operation_lock():
            manifest = self._read_manifest(snapshot_date)
            if manifest is None:
                raise FileNotFoundError(f"No complete R2 snapshot for {snapshot_date}.")
            staging = destination.with_name(f".{destination.name}.staging-{uuid.uuid4().hex}")
            self._download_manifest_files(snapshot_date, manifest, staging, destination)
        return destination

    @contextmanager
    def _operation_lock(self) -> Iterator[None]:
        with self._lock:
            if self._lock_path is None:
                yield
                return
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _download_manifest_files(
        self,
        snapshot_date: str,
        manifest: dict[str, Any],
        staging: Path,
        destination: Path,
    ) -> None:
        try:
            staging.mkdir(parents=True)
            for entry in manifest["files"]:
                self._download_manifest_file(snapshot_date, entry, staging)
            os.replace(staging, destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _download_manifest_file(self, snapshot_date: str, entry: dict[str, Any], staging: Path) -> None:
        relative = self._safe_relative_path(entry["path"])
        target = staging.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        key = f"{self._snapshot_prefix(snapshot_date)}{relative}"
        self._client.download_file(self._bucket, key, str(target))
        if target.stat().st_size != int(entry["size"]):
            raise IOError(f"Downloaded snapshot file has the wrong size: {relative}")
        expected_digest = entry.get("sha256")
        if expected_digest is not None and self._sha256_file(target) != expected_digest:
            raise IOError(f"Downloaded snapshot file failed its SHA-256 check: {relative}")

    def _delete_stale_objects(self, prefix: str, files: list[tuple[str, Path]], marker_key: str) -> None:
        expected = {f"{prefix}{relative}" for relative, _ in files}
        stale = [key for key in self._list_keys(prefix) if key not in expected and key != marker_key]
        self._delete_keys(stale)

    def _upload_files(self, prefix: str, files: list[tuple[str, Path]]) -> list[dict[str, Any]]:
        manifest_files = []
        for relative, path in files:
            self._client.upload_file(str(path), self._bucket, f"{prefix}{relative}")
            manifest_files.append(
                {"path": relative, "size": path.stat().st_size, "sha256": self._sha256_file(path)}
            )
        return manifest_files

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _ledger_object_keys(keys: list[str], ledger_id: str) -> list[str]:
        target_re = re.compile(rf"^daily/\d{{8}}/ledgers/{re.escape(ledger_id)}\.db(?:-(?:wal|shm))?$")
        return [key for key in keys if target_re.fullmatch(key)]

    def _remove_ledger_from_manifests(self, keys: list[str], ledger_id: str) -> None:
        marker_re = re.compile(r"^daily/(\d{8})/_COMPLETE\.json$")
        dates = {match.group(1) for key in keys if (match := marker_re.fullmatch(key))}
        ledger_path = f"ledgers/{ledger_id}.db"
        for snapshot_date in dates:
            manifest = self._read_manifest(snapshot_date)
            if manifest is None:
                continue
            manifest["files"] = [entry for entry in manifest["files"] if entry["path"] != ledger_path]
            self._write_manifest(snapshot_date, manifest)

    @staticmethod
    def _snapshot_prefix(snapshot_date: str) -> str:
        if not SNAPSHOT_DATE_RE.fullmatch(str(snapshot_date)):
            raise ValueError("Snapshot date must use YYYYMMDD.")
        try:
            datetime.strptime(str(snapshot_date), "%Y%m%d")
        except ValueError as exc:
            raise ValueError("Snapshot date must be a valid calendar date.") from exc
        return f"{DAILY_PREFIX}{snapshot_date}/"

    @staticmethod
    def _snapshot_date_in_key(key: str) -> str | None:
        match = re.match(r"^daily/(\d{8})/", key)
        if match is None:
            return None
        try:
            datetime.strptime(match.group(1), "%Y%m%d")
        except ValueError:
            return None
        return match.group(1)

    @staticmethod
    def _safe_relative_path(relative_path: Any) -> str:
        if not isinstance(relative_path, str):
            raise ValueError("Invalid path in R2 snapshot completion marker.")
        path = PurePosixPath(relative_path)
        if (
            path.is_absolute()
            or str(path) != relative_path
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("Invalid path in R2 snapshot completion marker.")
        if relative_path != "catalog.db" and not (
            relative_path.startswith("ledgers/") and LEDGER_FILE_RE.fullmatch(path.name) and len(path.parts) == 2
        ):
            raise ValueError("Invalid path in R2 snapshot completion marker.")
        return relative_path

    @staticmethod
    def _snapshot_files(snapshot_dir: Path) -> list[tuple[str, Path]]:
        files: list[tuple[str, Path]] = []
        catalog = snapshot_dir / "catalog.db"
        if catalog.is_file():
            files.append(("catalog.db", catalog))
        ledger_dir = snapshot_dir / "ledgers"
        if ledger_dir.is_dir():
            for path in sorted(ledger_dir.glob("*.db")):
                if LEDGER_FILE_RE.fullmatch(path.name):
                    files.append((f"ledgers/{path.name}", path))
        return files

    def _read_manifest(self, snapshot_date: str) -> dict[str, Any] | None:
        key = f"{self._snapshot_prefix(snapshot_date)}{COMPLETE_MARKER}"
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            if self._is_missing_object(exc):
                return None
            raise
        body = response["Body"].read()
        try:
            manifest = json.loads(body)
        except (TypeError, ValueError, UnicodeDecodeError):
            return None
        if not self._manifest_is_valid(manifest, snapshot_date):
            return None
        return manifest

    def _manifest_is_valid(self, manifest: Any, snapshot_date: str) -> bool:
        if (
            not isinstance(manifest, dict)
            or manifest.get("version") not in {1, 2}
            or manifest.get("date") != snapshot_date
            or not isinstance(manifest.get("files"), list)
        ):
            return False
        try:
            paths = [self._safe_relative_path(entry.get("path")) for entry in manifest["files"]]
            if len(paths) != len(set(paths)) or "catalog.db" not in paths:
                return False
            for entry in manifest["files"]:
                if isinstance(entry.get("size"), bool) or int(entry.get("size")) < 0:
                    return False
                digest = entry.get("sha256")
                if manifest["version"] == 2 and not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
                    return False
                if digest is not None and not re.fullmatch(r"[0-9a-f]{64}", digest):
                    return False
        except (AttributeError, TypeError, ValueError):
            return False
        return True

    def _write_manifest(self, snapshot_date: str, manifest: dict[str, Any]) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=f"{self._snapshot_prefix(snapshot_date)}{COMPLETE_MARKER}",
            Body=json.dumps(manifest, separators=(",", ":")).encode("utf-8"),
            ContentType="application/json",
        )

    def _list_keys(self, prefix: str) -> list[str]:
        paginator = self._client.get_paginator("list_objects_v2")
        return [
            object_description["Key"]
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix)
            for object_description in page.get("Contents", [])
        ]

    def _delete_keys(self, keys: list[str]) -> None:
        for offset in range(0, len(keys), 1000):
            batch = keys[offset : offset + 1000]
            if batch:
                response = self._client.delete_objects(
                    Bucket=self._bucket,
                    Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
                )
                if response.get("Errors"):
                    raise RuntimeError("R2 object deletion was incomplete.")

    @staticmethod
    def _is_missing_object(exc: Exception) -> bool:
        response = getattr(exc, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        return code in {"404", "NoSuchKey", "NotFound"}


def configure_r2_backup(
    *, lock_path: Path | None = None, log_disabled: bool = False
) -> OffsiteBackupStore | None:
    """Build the configured provider and emit one non-sensitive startup line."""
    if not all(os.getenv(name, "").strip() for name in _R2_ENV_NAMES):
        if log_disabled:
            logger.info("Off-site R2 backups disabled; set R2_ENDPOINT, R2_BUCKET, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY.")
        return None
    try:
        store = R2BackupStore.from_environment(lock_path)
    except Exception as exc:
        logger.error("Off-site R2 backups unavailable during startup (%s); local backups remain enabled.", type(exc).__name__)
        return None
    if log_disabled:
        logger.info("Off-site R2 backups enabled.")
    return store


def configure_database_offsite_backup(
    db: Any | None = None,
    *,
    backups_dir: Path | None = None,
    store: OffsiteBackupStore | None = None,
    log_disabled: bool = False,
) -> OffsiteBackupStore | None:
    """Create or attach the configured store using the shared backup lock."""
    if db is None and backups_dir is None:
        raise ValueError("Pass a database or backups directory to configure off-site backups.")
    directory = Path(backups_dir if backups_dir is not None else db.backups_dir)
    if store is None:
        store = configure_r2_backup(
            lock_path=directory / ".offsite-r2.lock",
            log_disabled=log_disabled,
        )
    if db is not None:
        db.offsite_backup = store
    return store
