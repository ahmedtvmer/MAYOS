"""Litestream connection and operational restore guarantees for #372."""

import sqlite3
from pathlib import Path

import pytest

from database.database_manager import DatabaseManager
from database.litestream import litestream_ledger_replica_path, litestream_replica_path


def _pragma(connection: sqlite3.Connection, name: str) -> int:
    return int(connection.execute(f"PRAGMA {name}").fetchone()[0])


@pytest.mark.parametrize(
    ("setting", "expected_autocheckpoint"),
    [(None, 1000), ("true", 0), ("1", 0), ("yes", 0), ("TRUE", 0), ("on", 0), ("no", 1000)],
)
def test_api_database_connections_gate_auto_checkpoint_on_litestream_setting(
    tmp_path: Path, monkeypatch, setting: str | None, expected_autocheckpoint: int
):
    if setting is None:
        monkeypatch.delenv("MAYOS_LITESTREAM", raising=False)
    else:
        monkeypatch.setenv("MAYOS_LITESTREAM", setting)

    db = DatabaseManager(
        catalog_path=tmp_path / "catalog.db",
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    try:
        with db.open_ledger("alice") as ledger:
            connections = (db.catalog_conn, db.deletions_conn, ledger.conn)
            assert [_pragma(connection, "wal_autocheckpoint") for connection in connections] == [
                expected_autocheckpoint
            ] * 3
            assert [_pragma(connection, "busy_timeout") for connection in connections] == [5000, 5000, 5000]
    finally:
        db.deletions_conn.close()
        db.catalog_conn.close()


def test_litestream_replica_paths_follow_the_data_root_relative_layout(monkeypatch):
    monkeypatch.setenv("LITESTREAM_R2_PREFIX", "rehearsal/litestream")

    assert litestream_replica_path("catalog.db") == "rehearsal/litestream/catalog.db"
    assert litestream_replica_path("deletions.db") == "rehearsal/litestream/deletions.db"
    assert litestream_ledger_replica_path("alice-123abc") == "rehearsal/litestream/users/alice-123abc.db"


def test_restore_refuses_a_non_empty_target_before_contacting_r2(tmp_path):
    from scripts import litestream_restore

    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="empty directory"):
        litestream_restore.restore_litestream(target)

    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_restore_runs_once_for_catalog_deletions_and_every_ledger(tmp_path, monkeypatch):
    from scripts import litestream_restore

    class ReplicaListing:
        @classmethod
        def from_environment(cls):
            return cls()

        def list_litestream_ledger_ids(self):
            return ["alice", "bob-123abc"]

    commands = []
    configs = []

    def fake_litestream(command, *, check):
        commands.append(command)
        output = Path(command[command.index("-o") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"restored sqlite")
        configs.append(Path(command[command.index("-config") + 1]).read_text(encoding="utf-8"))

    monkeypatch.setattr(litestream_restore.R2BackupStore, "from_environment", ReplicaListing.from_environment)
    monkeypatch.setattr(litestream_restore.subprocess, "run", fake_litestream)
    monkeypatch.setenv("LITESTREAM_R2_PREFIX", "litestream")

    target = tmp_path / "restored"
    target.mkdir()
    assert litestream_restore.restore_litestream(target) == 4

    assert {path.relative_to(target).as_posix() for path in target.rglob("*.db")} == {
        "catalog.db",
        "deletions.db",
        "users/alice.db",
        "users/bob-123abc.db",
    }
    assert len(commands) == 4
    assert any('path: "litestream/users/alice.db"' in config for config in configs)
    assert all("${R2_ACCESS_KEY_ID}" in config and "${R2_SECRET_ACCESS_KEY}" in config for config in configs)
