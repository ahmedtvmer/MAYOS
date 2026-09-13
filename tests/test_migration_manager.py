# tests/test_migration_manager.py
import sqlite3
from pathlib import Path

import pytest
from database.database_manager import DatabaseManager
from database.migration_manager import (
    CURRENT_USER_SCHEMA_VERSION,
    MIGRATION_REGISTRY,
    apply_lazy_migrations,
    create_atomic_backup,
    get_user_schema_version,
    prune_user_backups,
    restore_atomic_backup,
    set_user_schema_version,
)


@pytest.fixture
def temp_db_env(tmp_path: Path):
    catalog_path = tmp_path / "catalog.db"
    users_dir = tmp_path / "users"
    backups_dir = tmp_path / "backups"

    # Create dummy catalog
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute("CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT);")
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.commit()
    cat_conn.close()

    db = DatabaseManager(
        catalog_path=catalog_path,
        users_dir=users_dir,
        backups_dir=backups_dir,
        active_user="alice",
    )
    return db, users_dir, backups_dir


def test_schema_version_stamping(temp_db_env):
    db, users_dir, _ = temp_db_env
    version = get_user_schema_version(db.conn)
    assert version == CURRENT_USER_SCHEMA_VERSION == 1


def test_atomic_backup_and_restore(temp_db_env):
    db, users_dir, backups_dir = temp_db_env
    db.add_chat_message("user", "Hello backup test")

    snapshot_path = backups_dir / "alice" / "test_snap.db"
    create_atomic_backup(db.conn, snapshot_path)
    assert snapshot_path.is_file()

    # Clear chat in active DB
    db.clear_chat_history()
    assert len(db.get_chat_history()) == 0

    # Restore from snapshot
    restore_atomic_backup(snapshot_path, db.conn)
    history = db.get_chat_history()
    assert len(history) == 1
    assert history[0]["content"] == "Hello backup test"


def test_rolling_backup_pruning(tmp_path: Path):
    user_backup_dir = tmp_path / "backups" / "bob"
    user_backup_dir.mkdir(parents=True)

    # Create 5 rolling backups and 1 immutable pre-migration backup
    for i in range(5):
        f = user_backup_dir / f"bob_auto_20260901_0{i}.db"
        f.write_text("test")
    pre_mig = user_backup_dir / "bob_pre_v1_to_v2_20260901_00.db"
    pre_mig.write_text("pre-migration")

    prune_user_backups(user_backup_dir, max_rolling=3)

    remaining = list(user_backup_dir.glob("*.db"))
    assert pre_mig in remaining  # Immutable backup preserved
    rolling = [f for f in remaining if "_pre_v" not in f.name]
    assert len(rolling) == 3


def test_lazy_migration_execution_and_rollback(temp_db_env, monkeypatch):
    db, users_dir, backups_dir = temp_db_env

    # Simulate an upgrade from v1 to v2
    def mock_migrate_v1_to_v2(conn: sqlite3.Connection):
        conn.execute("ALTER TABLE user_profile ADD COLUMN test_column TEXT DEFAULT 'migrated';")

    MIGRATION_REGISTRY[1] = mock_migrate_v1_to_v2
    try:
        # Reset version to 1 to simulate pending migration to v2
        set_user_schema_version(db.conn, 1)
        db.conn.commit()

        apply_lazy_migrations(
            conn=db.conn,
            username="alice",
            users_dir=users_dir,
            backups_dir=backups_dir,
            target_version=2,
        )

        assert get_user_schema_version(db.conn) == 2
        cursor = db.conn.cursor()
        cursor.execute("SELECT test_column FROM user_profile LIMIT 1;")
        # Should succeed without error

        # Test failure rollback: migration raises exception
        def failing_v2_to_v3(conn: sqlite3.Connection):
            conn.execute("INVALID SQL SYNTAX HERE;")

        MIGRATION_REGISTRY[2] = failing_v2_to_v3
        with pytest.raises(RuntimeError, match="Database migration aborted and reverted"):
            apply_lazy_migrations(
                conn=db.conn,
                username="alice",
                users_dir=users_dir,
                backups_dir=backups_dir,
                target_version=3,
            )

        # Version must have rolled back to 2
        assert get_user_schema_version(db.conn) == 2
    finally:
        MIGRATION_REGISTRY.pop(1, None)
        MIGRATION_REGISTRY.pop(2, None)
