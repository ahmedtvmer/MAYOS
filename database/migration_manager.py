# database/migration_manager.py
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)

# Current target schema version for all user ledgers
CURRENT_USER_SCHEMA_VERSION: int = 3


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Adds auth_credentials for password hashes (legacy ledgers stay unclaimed)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auth_credentials (
            id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            password_hash TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Adds per-ledger token_version so password changes/resets revoke all sessions."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(auth_credentials)").fetchall()}
    if "token_version" not in columns:
        conn.execute("ALTER TABLE auth_credentials ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1")


def get_user_schema_version(conn: sqlite3.Connection) -> int:
    """Reads the current user_version PRAGMA from the SQLite connection."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA user_version;")
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def set_user_schema_version(conn: sqlite3.Connection, version: int) -> None:
    """Sets the user_version PRAGMA integer."""
    conn.execute(f"PRAGMA user_version = {int(version)};")


def create_atomic_backup(
    conn: sqlite3.Connection,
    backup_path: Path,
) -> Path:
    """Creates a consistent, online point-in-time snapshot using the SQLite backup API.

    Safely drains WAL pages into the target file without taking the database offline.
    """
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    dest_conn = sqlite3.connect(str(backup_path))
    try:
        conn.backup(dest_conn)
    finally:
        dest_conn.close()

    logger.info(f"Atomic snapshot created: {backup_path.name}")
    return backup_path


def restore_atomic_backup(
    backup_path: Path,
    target_conn: sqlite3.Connection,
) -> None:
    """Restores database state from a backup snapshot into an active SQLite connection."""
    if not backup_path.is_file():
        raise FileNotFoundError(f"Backup snapshot not found: {backup_path}")

    src_conn = sqlite3.connect(str(backup_path))
    try:
        src_conn.backup(target_conn)
    finally:
        src_conn.close()

    logger.warning(f"Database successfully restored from snapshot: {backup_path.name}")


def prune_user_backups(user_backup_dir: Path, max_rolling: int = 3) -> None:
    """Enforces the 3+1 retention policy:

    - Keeps all immutable pre-migration snapshots (*_pre_v*).
    - Retains only the most recent `max_rolling` (default: 3) automated snapshots.
    """
    if not user_backup_dir.is_dir():
        return

    rolling_snapshots = []
    for f in user_backup_dir.glob("*.db"):
        if "_pre_v" not in f.name:
            rolling_snapshots.append(f)

    # Sort ascending by modification time (oldest first)
    rolling_snapshots.sort(key=lambda p: p.stat().st_mtime)

    # Prune oldest if exceeding retention
    while len(rolling_snapshots) > max_rolling:
        oldest = rolling_snapshots.pop(0)
        try:
            oldest.unlink()
            logger.info(f"Pruned expired rolling snapshot: {oldest.name}")
        except OSError as e:
            logger.warning(f"Failed to prune snapshot {oldest}: {e}")


# ---------------------------------------------------------------------------
# Migration Registry & Upgrade Handlers
# ---------------------------------------------------------------------------

MigrationCallable = Callable[[sqlite3.Connection], None]

# Migration map: from_version -> migration function to reach (from_version + 1)
# Example: 1: migrate_v1_to_v2
MIGRATION_REGISTRY: dict[int, MigrationCallable] = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
}


def apply_lazy_migrations(
    conn: sqlite3.Connection,
    username: str,
    users_dir: Path,
    backups_dir: Path,
    target_version: int = CURRENT_USER_SCHEMA_VERSION,
) -> None:
    """Evaluates and executes lazy migrations on the mounted user database.

    Execution Flow:
    1. Check PRAGMA user_version.
    2. If version == 0 and tables exist (pre-migration legacy DB), stamp to v1.
    3. If version == 0 and empty, the caller initializes baseline schema and sets v1.
    4. If version < target_version, snapshot the DB, run sequential migrations in a
       transaction, and update user_version.
    5. If an error occurs, rollback and restore snapshot.
    """
    current_version = get_user_schema_version(conn)

    # Handle legacy databases initialized prior to PRAGMA user_version tracking
    if current_version == 0:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_profile';")
        if cursor.fetchone():
            # Existing legacy v1 database detected
            set_user_schema_version(conn, 1)
            conn.commit()
            current_version = 1
        else:
            # Fresh database: caller will provision baseline v1 schema
            return

    if current_version == target_version:
        return

    if current_version > target_version:
        raise RuntimeError(
            f"User ledger '{username}' has schema version {current_version}, which is "
            f"newer than the engine's target version {target_version}. Please update Myos."
        )

    # Migration required: current_version < target_version
    user_backup_dir = backups_dir / username
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    snapshot_path = user_backup_dir / f"{username}_pre_v{current_version}_to_v{target_version}_{timestamp}.db"

    create_atomic_backup(conn, snapshot_path)

    try:
        conn.execute("BEGIN IMMEDIATE;")
        step_version = current_version
        while step_version < target_version:
            if step_version not in MIGRATION_REGISTRY:
                raise NotImplementedError(
                    f"Missing migration step from schema version {step_version} to {step_version + 1}."
                )
            logger.info(f"Applying migration v{step_version} -> v{step_version + 1} for '{username}'...")
            MIGRATION_REGISTRY[step_version](conn)
            step_version += 1

        set_user_schema_version(conn, target_version)
        conn.commit()
        logger.info(f"Successfully migrated '{username}' ledger to schema v{target_version}.")
    except Exception as exc:
        conn.rollback()
        logger.error(f"Migration failed for '{username}': {exc}. Triggering atomic rollback...")
        restore_atomic_backup(snapshot_path, conn)
        raise RuntimeError(f"Database migration aborted and reverted for '{username}': {exc}") from exc
