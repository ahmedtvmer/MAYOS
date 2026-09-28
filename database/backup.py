"""Daily online backups and safe restore (issue #41, ADR 015/044).

The owner must be able to restore trial data without reviving deleted
identities. Backups are consistent, online SQLite snapshots (``Connection.backup``,
never a raw copy of a WAL database) of the catalog and every ledger of a live
account, written under ``<backups_dir>/daily/<YYYYMMDD>/``. Ledger copies live in
the snapshot's ``ledgers/`` subdirectory so a ledger id of ``catalog`` can never
collide with the catalog copy. ``deletions.db`` lives outside every snapshot on
purpose: a restore keeps the *current* deletion record, then replays it, so a
pre-deletion catalog cannot resurrect a deleted account.

Each run stages into a hidden temp directory and atomically renames it into place,
so a failed or partial run is never counted as a valid snapshot and a rerun the
same day works. Retention is bounded (default and maximum 30 days, per ADR 015's
disclosed restricted whole-catalog recovery window), and an account deletion also
removes that account's ledger copy from every daily snapshot.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from database.migration_manager import restore_atomic_backup
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)

DAILY_BACKUPS_DIRNAME = "daily"
LEDGERS_SUBDIR = "ledgers"
ORPHANS_SUBDIR = "restore-orphans"
CATALOG_SNAPSHOT_NAME = "catalog.db"
#: Marker a boot-time restore reads; it lives beside the daily snapshots, never
#: inside one, so restoring a snapshot cannot restore away the request itself.
RESTORE_PENDING_NAME = "restore-pending.json"
DEFAULT_BACKUP_RETENTION_DAYS = 30
#: ADR 015 discloses restricted whole-catalog recovery retention of up to 30
#: days; a longer window would exceed what users were told.
MAX_BACKUP_RETENTION_DAYS = 30
#: A ledger id is safe to use as a file name when it is already canonical: the
#: sanitized value equals the raw value and it is not the reserved ``default``.
RESERVED_LEDGER_IDS = frozenset({"default"})


def daily_backups_root(backups_dir: Path) -> Path:
    """The daily-snapshot area under the migration/backup work root."""
    return Path(backups_dir) / DAILY_BACKUPS_DIRNAME


def restore_pending_path(backups_dir: Path) -> Path:
    """Path of the boot-time pending-restore marker (outside every snapshot)."""
    return Path(backups_dir) / RESTORE_PENDING_NAME


def _reserved_ledger_ids(db: Any) -> frozenset[str]:
    """Reserved engine ledger ids that are never account data.

    ``default`` is the engine's shared ledger; the store may also name a
    bootstrap id (tests/scripts). Neither belongs to an account, so neither is a
    backup target nor an orphan to quarantine.
    """
    bootstrap = str(getattr(db, "default_ledger_id", "") or "")
    return RESERVED_LEDGER_IDS | ({bootstrap} if bootstrap else set())


def _canonical_ledger_id(db: Any, value: Any) -> str | None:
    """The single canonical, non-reserved ledger-id guard.

    Returns the id when it is safe to use as a file name (already canonical and
    not reserved), else ``None``. Reuses the store's own sanitizer so this module
    and account deletion cannot drift apart.
    """
    raw = str(value)
    sanitized = db._sanitize_username(raw)
    if not sanitized or sanitized != raw or sanitized in _reserved_ledger_ids(db):
        return None
    return sanitized


def _live_ledger_ids(db: Any) -> list[str]:
    """Every ledger id owned by a live account, safe to use as a file name."""
    with db.catalog_locked() as conn:
        rows = conn.execute(
            "SELECT DISTINCT ledger_id FROM accounts WHERE status = 'active' AND deleted_at IS NULL"
        ).fetchall()
    ids = {cid for row in rows if (cid := _canonical_ledger_id(db, row[0])) is not None}
    return sorted(ids)


def _clamp_retention_days(days: int) -> int:
    return max(1, min(int(days), MAX_BACKUP_RETENTION_DAYS))


def backup_retention_days(raw: str | None = None) -> int:
    """Configured retention in days, appended to ADR 015's 30-day ceiling."""
    value = raw if raw is not None else os.getenv("MAYOS_BACKUP_RETENTION_DAYS", "")
    try:
        days = int(str(value).strip() or DEFAULT_BACKUP_RETENTION_DAYS)
    except (TypeError, ValueError):
        logger.warning("Invalid MAYOS_BACKUP_RETENTION_DAYS=%r; using the default.", value)
        days = DEFAULT_BACKUP_RETENTION_DAYS
    return _clamp_retention_days(days)


def _require_catalog_snapshot(snapshot_dir: Path) -> Path:
    """The one place the "snapshot has a catalog copy" rule lives."""
    snapshot = Path(snapshot_dir)
    catalog = snapshot / CATALOG_SNAPSHOT_NAME
    if not catalog.is_file():
        raise FileNotFoundError(f"Snapshot has no {CATALOG_SNAPSHOT_NAME}: {snapshot}")
    return catalog


def _snapshot_is_valid(snapshot_dir: Path) -> bool:
    return (snapshot_dir / CATALOG_SNAPSHOT_NAME).is_file()


def _snapshot_connection(source: sqlite3.Connection, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest = sqlite3.connect(str(dest_path))
    try:
        source.backup(dest)
    finally:
        dest.close()


def snapshot_sqlite_file(source_path: Path, dest_path: Path) -> None:
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    try:
        _snapshot_connection(source, dest_path)
    finally:
        source.close()


def create_daily_backup(
    db: Any,
    *,
    now: datetime | None = None,
    retention_days: int | None = None,
) -> dict[str, Any]:
    """Creates one consistent daily snapshot of the catalog and live-account ledgers.

    Idempotent per UTC day: a valid snapshot already covering ``now``'s date is
    left alone, so restarts and reruns do not pile up copies. On any component
    failure the staged directory is discarded and the error is re-raised, so a
    half-written snapshot is never published; a later run can retry.

    Immediately before publishing, the live ledger ids are re-read **under the
    catalog lock** and staged copies no longer owned by a live account are
    dropped, with the atomic rename done while still holding that lock. This
    closes a deletion/backup race: a deletion landing mid-run (which removes the
    account's daily copies) can no longer be undone by republishing its staged
    ledger copy. Returns a summary describing the snapshot, the ledgers it
    covered, and any prune.
    """
    moment = now or datetime.now(UTC)
    day = moment.astimezone(UTC).strftime("%Y%m%d")
    root = daily_backups_root(db.backups_dir)
    root.mkdir(parents=True, exist_ok=True)
    final_dir = root / day

    if _snapshot_is_valid(final_dir):
        return {
            "created": False,
            "skipped": True,
            "date": day,
            "path": str(final_dir),
            "catalog": True,
            "ledgers": sorted(p.stem for p in (final_dir / LEDGERS_SUBDIR).glob("*.db")),
            "pruned": [],
        }

    staging_dir = root / f".staging-{day}-{uuid.uuid4().hex}"
    staging_ledgers = staging_dir / LEDGERS_SUBDIR
    covered: list[str] = []
    try:
        staging_dir.mkdir(parents=True)
        with db.catalog_locked() as catalog_conn:
            _snapshot_connection(catalog_conn, staging_dir / CATALOG_SNAPSHOT_NAME)
        for ledger_id in _live_ledger_ids(db):
            source = Path(db.ledgers_dir) / f"{ledger_id}.db"
            if not source.is_file():
                continue
            snapshot_sqlite_file(source, staging_ledgers / f"{ledger_id}.db")
            covered.append(ledger_id)
        # Publish atomically, holding the catalog lock across the re-check and the
        # rename so a concurrent deletion cannot slip between them (defect #2).
        # The staging dir always carries a catalog file, so a crash before this
        # point leaves nothing under the day's name.
        with db.catalog_locked():
            live = set(_live_ledger_ids(db))
            for ledger_id in list(covered):
                if ledger_id not in live:
                    (staging_ledgers / f"{ledger_id}.db").unlink(missing_ok=True)
                    covered.remove(ledger_id)
            if final_dir.exists():
                shutil.rmtree(final_dir)
            os.replace(staging_dir, final_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        logger.exception("Daily backup for %s failed; no snapshot was published.", day)
        raise

    pruned = prune_daily_backups(daily_backups_root(db.backups_dir), retention_days=retention_days, now=moment)
    logger.info("Daily backup for %s covered catalog + %s ledger(s).", day, len(covered))
    return {
        "created": True,
        "skipped": False,
        "date": day,
        "path": str(final_dir),
        "catalog": True,
        "ledgers": covered,
        "pruned": pruned,
    }


def _snapshot_date(snapshot_dir: Path) -> datetime | None:
    try:
        return datetime.strptime(snapshot_dir.name, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        try:
            return datetime.fromtimestamp(snapshot_dir.stat().st_mtime, UTC)
        except OSError:
            return None


def _prune_dated_dirs(root: Path, retention_days: int | None, now: datetime | None) -> list[str]:
    """Removes dated snapshot/orphan dirs older than the bounded window."""
    root = Path(root)
    if not root.is_dir():
        return []
    days = _clamp_retention_days(retention_days if retention_days is not None else backup_retention_days())
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    pruned: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        created = _snapshot_date(entry)
        if created is not None and created < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
            pruned.append(entry.name)
            logger.info("Pruned backup dir older than %s days: %s", days, entry.name)
    return pruned


def prune_daily_backups(
    root: Path,
    *,
    retention_days: int | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Removes daily snapshots older than the bounded retention window."""
    return _prune_dated_dirs(root, retention_days, now)


def list_daily_backups(backups_dir: Path) -> list[Path]:
    """Valid daily snapshots, oldest first; staging/partial dirs are excluded."""
    root = daily_backups_root(backups_dir)
    if not root.is_dir():
        return []
    snapshots = [entry for entry in root.iterdir() if entry.is_dir() and _snapshot_is_valid(entry)]
    snapshots.sort(key=lambda entry: entry.name)
    return snapshots


def remove_ledger_from_daily_backups(db: Any, ledger_id: Any) -> list[str]:
    """Removes an account's ledger copy from every daily snapshot (ADR 015/039).

    Ledger copies live under each snapshot's ``ledgers/`` subdirectory, so this
    only ever touches ledger files, never the catalog copy. Whole-catalog rows in
    those snapshots remain the documented restricted recovery exception; it is the
    ledger copy that must go with the account. Returns the snapshot dirs touched.
    """
    safe = _canonical_ledger_id(db, ledger_id)
    if safe is None:
        return []
    root = daily_backups_root(db.backups_dir)
    if not root.is_dir():
        return []
    touched: list[str] = []
    for snapshot_dir in root.iterdir():
        if not snapshot_dir.is_dir():
            continue
        removed = False
        for suffix in ("", "-wal", "-shm"):
            path = snapshot_dir / LEDGERS_SUBDIR / f"{safe}.db{suffix}"
            if path.exists():
                path.unlink(missing_ok=True)
                removed = True
        if removed:
            touched.append(snapshot_dir.name)
    return touched


def _restore_ledger_file(snapshot_file: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_conn = sqlite3.connect(str(target_path))
    try:
        restore_atomic_backup(snapshot_file, target_conn)
    finally:
        target_conn.close()


def quarantine_orphaned_ledgers(db: Any, *, now: datetime | None = None) -> list[str]:
    """Moves live ledger files not owned by a live account into a quarantine area.

    After restoring an older snapshot, an account created after that snapshot has
    no catalog row but its ``users/<id>.db`` remains; its username is then
    stranded (registration refuses a username whose ledger exists, and there is
    no account to log in to or delete). Moving rather than deleting keeps the
    files recoverable by the owner, and frees the username for registration.

    Returns the moved ledger ids. Handles are closed by their owners before a
    restore (the API is not serving), so the files can be moved directly.
    """
    moment = now or datetime.now(UTC)
    live = set(_live_ledger_ids(db))
    ledgers_dir = Path(db.ledgers_dir)
    if not ledgers_dir.is_dir():
        return []
    candidates: set[str] = set()
    for entry in ledgers_dir.iterdir():
        if not entry.is_file():
            continue
        suffix = "".join(entry.suffixes)
        if suffix not in {".db", ".db-wal", ".db-shm"}:
            continue
        stem = entry.name.removesuffix("-wal").removesuffix("-shm").removesuffix(".db")
        safe = _canonical_ledger_id(db, stem)
        if safe is not None and safe not in live:
            candidates.add(safe)
    if not candidates:
        return []

    quarantine = Path(db.backups_dir) / ORPHANS_SUBDIR / moment.strftime("%Y%m%dT%H%M%SZ")
    quarantine.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for ledger_id in sorted(candidates):
        moved_any = False
        for suffix in ("", "-wal", "-shm"):
            source = ledgers_dir / f"{ledger_id}.db{suffix}"
            if source.exists():
                try:
                    os.replace(source, quarantine / source.name)
                    moved_any = True
                except OSError:
                    logger.exception("Failed to quarantine orphaned ledger file %s", source)
        if moved_any:
            moved.append(ledger_id)
    # Orphan quarantine obeys the same bounded retention as daily snapshots.
    _prune_dated_dirs(Path(db.backups_dir) / ORPHANS_SUBDIR, None, moment)
    if moved:
        logger.warning("Quarantined orphaned ledger(s) after restore: %s -> %s", moved, quarantine)
    return moved


def restore_daily_backup(snapshot: Path, *, db: Any) -> dict[str, Any]:
    """Restores one daily snapshot into the live data dir and reapplies deletions.

    Never touches ``deletions.db``: the *current* record is kept and replayed via
    :meth:`DatabaseManager.reapply_deletions`, so a pre-deletion snapshot cannot
    resurrect a deleted identity. ``db`` is the live :class:`DatabaseManager` whose
    catalog connection is restored in place and whose ledger directory receives
    the snapshot's ledgers. Ledgers with no live account in the restored catalog
    are quarantined (not deleted) so their usernames are not stranded.
    """
    snapshot = Path(snapshot)
    snapshot_catalog = _require_catalog_snapshot(snapshot)

    restore_atomic_backup(snapshot_catalog, db.catalog_conn)
    restored_ledgers: list[str] = []
    ledger_dir = snapshot / LEDGERS_SUBDIR
    if ledger_dir.is_dir():
        for entry in sorted(ledger_dir.glob("*.db")):
            if not re.match(r"^[a-z0-9][a-z0-9_-]*\.db$", entry.name):
                continue
            _restore_ledger_file(entry, Path(db.ledgers_dir) / entry.name)
            restored_ledgers.append(entry.stem)

    applied = db.reapply_deletions()
    quarantined = quarantine_orphaned_ledgers(db)
    logger.info(
        "Restored snapshot %s (catalog + %s ledger(s)); reapplied %s deletion(s); quarantined %s orphan(s).",
        snapshot.name,
        len(restored_ledgers),
        applied,
        len(quarantined),
    )
    return {
        "snapshot": str(snapshot),
        "restored_ledgers": restored_ledgers,
        "deletions_reapplied": applied,
        "quarantined_ledgers": quarantined,
    }


def schedule_restore(backups_dir: Path, snapshot: Path) -> Path:
    """Validates a snapshot and atomically writes a pending-restore marker.

    This makes restore a boot-time step of the API Machine: the operator cannot
    scale the only volume-owning writer to zero to run an offline restore, and
    restoring while it serves is unsafe. The marker is written atomically (temp
    file + ``os.replace``) so a crash cannot leave a half-written request, and
    it lives beside the daily snapshots, never inside one.
    """
    _require_catalog_snapshot(snapshot)
    marker = restore_pending_path(backups_dir)
    payload = {
        "snapshot": str(Path(snapshot).resolve()),
        "requested_at": datetime.now(UTC).isoformat(),
    }
    marker.parent.mkdir(parents=True, exist_ok=True)
    tmp = marker.with_name(f"{marker.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, marker)
    logger.warning("Pending restore scheduled from %s; it will apply on the next boot.", snapshot)
    return marker


def _read_pending_restore(backups_dir: Path) -> Path | None:
    marker = restore_pending_path(backups_dir)
    if not marker.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        raw = str(payload["snapshot"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"Pending-restore marker {marker} is unreadable; refusing to serve.") from exc
    return Path(raw)


def apply_pending_restore(db: Any) -> dict[str, Any] | None:
    """Applies a scheduled restore to ``db``, then clears the marker.

    Returns ``None`` when there is nothing pending. On success the marker is
    removed so the restore runs exactly once. On any failure the marker is left
    in place and the error propagates, so the caller can fail closed rather than
    serve a half-restored catalog; the next boot retries.
    """
    backups_dir = Path(db.backups_dir)
    snapshot = _read_pending_restore(backups_dir)
    if snapshot is None:
        return None
    result = restore_daily_backup(snapshot, db=db)
    restore_pending_path(backups_dir).unlink(missing_ok=True)
    logger.warning("Pending restore from %s applied at boot.", snapshot)
    return result
