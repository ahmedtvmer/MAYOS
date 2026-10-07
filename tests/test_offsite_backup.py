"""Hermetic Cloudflare R2 adapter and restore/deletion coverage (#164)."""

import io
import fcntl
import hashlib
import json
import logging
import os
import sqlite3
import sys
import threading
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest

from database.backup import create_daily_backup, restore_daily_backup
from database.offsite_backup import (
    COMPLETE_MARKER,
    R2BackupStore,
    configure_r2_backup,
)

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"


class MissingObject(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class FakePaginator:
    def __init__(self, client):
        self.client = client

    def paginate(self, *, Bucket, Prefix):
        keys = sorted(key for key in self.client.objects if key.startswith(Prefix))
        return [{"Contents": [{"Key": key} for key in keys]}]


class FakeS3Client:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail_upload_containing: str | None = None

    def get_paginator(self, operation):
        assert operation == "list_objects_v2"
        return FakePaginator(self)

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise MissingObject()
        return {"Body": io.BytesIO(self.objects[Key])}

    def upload_file(self, filename, bucket, key):
        self.calls.append(("upload", key))
        if self.fail_upload_containing and self.fail_upload_containing in key:
            self.fail_upload_containing = None
            raise OSError("simulated object upload failure")
        self.objects[key] = Path(filename).read_bytes()

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.calls.append(("put", Key))
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.read()

    def download_file(self, bucket, key, filename):
        if key not in self.objects:
            raise MissingObject()
        Path(filename).write_bytes(self.objects[key])

    def delete_objects(self, *, Bucket, Delete):
        for object_entry in Delete["Objects"]:
            self.calls.append(("delete", object_entry["Key"]))
            self.objects.pop(object_entry["Key"], None)
        return {"Deleted": Delete["Objects"]}


def _snapshot(root: Path, date: str, ledgers: tuple[str, ...] = ("alice", "bob")) -> Path:
    snapshot = root / date
    (snapshot / "ledgers").mkdir(parents=True)
    (snapshot / "catalog.db").write_bytes(b"catalog")
    for ledger_id in ledgers:
        (snapshot / "ledgers" / f"{ledger_id}.db").write_bytes(f"{ledger_id}-ledger".encode())
    return snapshot


def test_r2_upload_marks_complete_last_and_is_idempotent(tmp_path):
    client = FakeS3Client()
    store = R2BackupStore(client, "private-bucket")
    snapshot = _snapshot(tmp_path, "20260929")

    assert store.is_snapshot_complete("20260929") is False
    store.upload_snapshot(snapshot, "20260929")
    assert store.is_snapshot_complete("20260929") is True
    marker = "daily/20260929/" + COMPLETE_MARKER
    assert client.calls[-1] == ("put", marker)
    assert set(client.objects) == {
        marker,
        "daily/20260929/catalog.db",
        "daily/20260929/ledgers/alice.db",
        "daily/20260929/ledgers/bob.db",
    }
    manifest = json.loads(client.objects[marker])
    assert manifest["date"] == "20260929"
    call_count = len(client.calls)
    store.upload_snapshot(snapshot, "20260929")
    assert len(client.calls) == call_count


def test_partial_r2_upload_has_no_completion_marker_and_rerun_finishes(tmp_path):
    client = FakeS3Client()
    client.fail_upload_containing = "ledgers/alice.db"
    store = R2BackupStore(client, "private-bucket")
    snapshot = _snapshot(tmp_path, "20260929")

    with pytest.raises(OSError):
        store.upload_snapshot(snapshot, "20260929")
    assert "daily/20260929/" + COMPLETE_MARKER not in client.objects

    store.upload_snapshot(snapshot, "20260929")
    assert "daily/20260929/" + COMPLETE_MARKER in client.objects
    assert set(client.objects) == {
        "daily/20260929/" + COMPLETE_MARKER,
        "daily/20260929/catalog.db",
        "daily/20260929/ledgers/alice.db",
        "daily/20260929/ledgers/bob.db",
    }


def test_r2_pruning_uses_a_30_day_maximum(tmp_path):
    client = FakeS3Client()
    store = R2BackupStore(client, "private-bucket")
    for day in ("20260701", "20260829", "20260830", "20260929"):
        snapshot = _snapshot(tmp_path, day, ledgers=())
        store.upload_snapshot(snapshot, day)
    client.objects["daily/20261399/catalog.db"] = b"malformed legacy key"

    pruned = store.prune_snapshots(retention_days=90, now=datetime(2026, 9, 29, tzinfo=UTC))
    assert pruned == ["20260701", "20260829"]
    assert "daily/20260701/catalog.db" not in client.objects
    assert "daily/20260829/catalog.db" not in client.objects
    assert "daily/20260830/catalog.db" in client.objects
    assert "daily/20261399/catalog.db" in client.objects


def test_r2_operations_share_a_filesystem_lock(tmp_path):
    lock_path = tmp_path / "backups" / ".offsite-r2.lock"
    client = FakeS3Client()
    store = R2BackupStore(client, "private-bucket", lock_path=lock_path)

    store.upload_snapshot(_snapshot(tmp_path, "20260929"), "20260929")

    assert lock_path.is_file()
    assert store.is_snapshot_complete("20260929")


def test_r2_deletion_removes_ledger_from_every_snapshot_and_manifest(tmp_path):
    client = FakeS3Client()
    store = R2BackupStore(client, "private-bucket")
    older = _snapshot(tmp_path, "20260928")
    current = _snapshot(tmp_path, "20260929")
    for snapshot, day in ((older, "20260928"), (current, "20260929")):
        store.upload_snapshot(snapshot, day)
    replica_prefix = "litestream/users/alice.db/"
    client.objects[replica_prefix + "ltx/0000/0000000000000001-0000000000000001.ltx"] = b"replica"

    store.remove_ledger("alice")
    for day in ("20260928", "20260929"):
        assert f"daily/{day}/ledgers/alice.db" not in client.objects
        marker = json.loads(client.objects[f"daily/{day}/{COMPLETE_MARKER}"])
        assert "ledgers/alice.db" not in {entry["path"] for entry in marker["files"]}
        assert f"daily/{day}/ledgers/bob.db" in client.objects
        assert f"daily/{day}/catalog.db" in client.objects
    assert not any(key.startswith(replica_prefix) for key in client.objects)


def test_r2_download_requires_a_complete_manifest_and_fetches_to_staging(tmp_path):
    client = FakeS3Client()
    store = R2BackupStore(client, "private-bucket")
    with pytest.raises(FileNotFoundError, match="complete R2 snapshot"):
        store.download_snapshot("20260929", tmp_path / "restore")

    source = _snapshot(tmp_path, "20260929")
    store.upload_snapshot(source, "20260929")
    downloaded = store.download_snapshot("20260929", tmp_path / "restore")
    assert (downloaded / "catalog.db").read_bytes() == b"catalog"
    assert (downloaded / "ledgers/alice.db").read_bytes() == b"alice-ledger"
    assert not list(tmp_path.glob(".restore.staging-*"))


def test_r2_download_rejects_same_size_corruption_before_publish(tmp_path):
    client = FakeS3Client()
    store = R2BackupStore(client, "private-bucket")
    snapshot = _snapshot(tmp_path, "20260929")
    store.upload_snapshot(snapshot, "20260929")
    client.objects["daily/20260929/catalog.db"] = b"corrupt"

    with pytest.raises(IOError, match="SHA-256"):
        store.download_snapshot("20260929", tmp_path / "restore")

    assert not (tmp_path / "restore").exists()
    assert not list(tmp_path.glob(".restore.staging-*"))


def test_legacy_manifest_remains_restorable_and_rerun_upgrades_it(tmp_path):
    client = FakeS3Client()
    store = R2BackupStore(client, "private-bucket")
    snapshot = _snapshot(tmp_path, "20260929")
    store.upload_snapshot(snapshot, "20260929")
    marker_key = f"daily/20260929/{COMPLETE_MARKER}"
    manifest = json.loads(client.objects[marker_key])
    manifest["version"] = 1
    for entry in manifest["files"]:
        entry.pop("sha256")
    client.objects[marker_key] = json.dumps(manifest).encode()

    assert store.is_snapshot_complete("20260929") is False
    downloaded = store.download_snapshot("20260929", tmp_path / "legacy-restore")
    assert (downloaded / "catalog.db").read_bytes() == b"catalog"

    store.upload_snapshot(snapshot, "20260929")
    upgraded = json.loads(client.objects[marker_key])
    assert upgraded["version"] == 2
    assert all("sha256" in entry for entry in upgraded["files"])


def test_r2_configuration_uses_only_the_four_named_secrets(monkeypatch):
    captured = {}

    def fake_client(service, **kwargs):
        captured["service"] = service
        captured.update(kwargs)
        return FakeS3Client()

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=fake_client))
    monkeypatch.setenv("R2_ENDPOINT", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_BUCKET", "backup-bucket")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "never-log-this-id")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "never-log-this-secret")

    store = configure_r2_backup()
    assert isinstance(store, R2BackupStore)
    config = captured.pop("config")
    assert captured == {
        "service": "s3",
        "region_name": "auto",
        "endpoint_url": "https://example.r2.cloudflarestorage.com",
        "aws_access_key_id": "never-log-this-id",
        "aws_secret_access_key": "never-log-this-secret",
    }
    assert config.connect_timeout == 5
    assert config.read_timeout == 30
    assert config.retries == {"mode": "standard", "max_attempts": 3}
    assert config.signature_version == "s3v4"


def test_missing_r2_configuration_skips_provider(monkeypatch, caplog):
    for name in ("R2_ENDPOINT", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert configure_r2_backup(log_disabled=True) is None
    matching = [record for record in caplog.records if "Off-site R2 backups disabled" in record.getMessage()]
    assert len(matching) == 1


def test_restore_cli_fetches_the_requested_r2_snapshot_before_scheduling(tmp_path, monkeypatch):
    client = FakeS3Client()
    source = _snapshot(tmp_path, "20260929")
    R2BackupStore(client, "backup-bucket").upload_snapshot(source, "20260929")
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda service, **kwargs: client))
    monkeypatch.setenv("R2_ENDPOINT", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_BUCKET", "backup-bucket")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret-key")

    from database.backup import restore_pending_path
    from scripts.restore_backup import main

    backups_dir = tmp_path / "backups"
    assert main([
        "--r2", "20260929", "--on-next-boot",
        "--backups-dir", str(backups_dir),
        "--catalog", str(tmp_path / "catalog.db"),
        "--users-dir", str(tmp_path / "users"),
    ]) == 0
    payload = json.loads(restore_pending_path(backups_dir).read_text(encoding="utf-8"))
    restored = Path(payload["snapshot"])
    assert restored.name.startswith("20260929-")
    assert payload["r2_snapshot_date"] == "20260929"
    assert (restored / "catalog.db").read_bytes() == b"catalog"


def _set_fake_r2_environment(monkeypatch, client):
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda service, **kwargs: client))
    monkeypatch.setenv("R2_ENDPOINT", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_BUCKET", "backup-bucket")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret-key")


@pytest.mark.parametrize("fail_restore", [False, True], ids=["success", "failure"])
def test_r2_restore_cli_removes_download_after_immediate_restore(tmp_path, monkeypatch, fail_restore):
    client = FakeS3Client()
    source = _snapshot(tmp_path, "20260929")
    R2BackupStore(client, "backup-bucket").upload_snapshot(source, "20260929")
    _set_fake_r2_environment(monkeypatch, client)

    import scripts.restore_backup as restore_cli

    class FakeDatabase:
        def __init__(self, **kwargs):
            self.backups_dir = Path(kwargs["backups_dir"])
            self.catalog_conn = types.SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(restore_cli, "DatabaseManager", FakeDatabase)

    def restore(snapshot, *, db):
        assert (Path(snapshot) / "catalog.db").is_file()
        if fail_restore:
            raise RuntimeError("simulated restore failure")
        return {
            "restored_ledgers": [],
            "deletions_reapplied": 0,
            "quarantined_ledgers": [],
            "deletion_facts": [],
        }

    monkeypatch.setattr(restore_cli, "restore_daily_backup", restore)
    backups_dir = tmp_path / "backups"
    argv = [
        "--r2", "20260929",
        "--backups-dir", str(backups_dir),
        "--catalog", str(tmp_path / "catalog.db"),
        "--users-dir", str(tmp_path / "users"),
    ]
    if fail_restore:
        with pytest.raises(RuntimeError, match="simulated restore failure"):
            restore_cli.main(argv)
    else:
        assert restore_cli.main(argv) == 0

    assert not list((backups_dir / "r2-restore").glob("*"))


@pytest.fixture
def r2_api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("MAYOS_ALERT_SWEEP_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("MAYOS_DAILY_BACKUP_INTERVAL_SECONDS", "0")
    from database.database_manager import DatabaseManager

    catalog_path = tmp_path / "catalog.db"
    with sqlite3.connect(catalog_path) as conn:
        conn.execute(
            "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
            " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
        )
        conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
        conn.execute("INSERT INTO exercises (id, name) VALUES ('sq', 'Squat')")
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    client = FakeS3Client()
    db.offsite_backup = R2BackupStore(client, "private-bucket", tmp_path / "backups" / ".offsite-r2.lock")
    try:
        yield db, client, tmp_path
    finally:
        db.catalog_conn.close()


def _register(db, username):
    from service.auth import register_player
    from svc.auth import create_access_token

    registration = register_player(db, username, "correct-horse-1")
    assert registration["ok"] is True
    token = create_access_token(registration["account_id"], token_version=registration["session_epoch"])
    return {"account_id": registration["account_id"], "ledger_id": registration["trainee_id"], "token": token}


def test_r2_restore_replays_current_deletions_and_keeps_old_token_invalid(r2_api):
    db, r2, tmp_path = r2_api
    registered = _register(db, "alice")
    token = registered["token"]
    account_id = registered["account_id"]

    summary = create_daily_backup(db, now=datetime(2026, 9, 29, tzinfo=UTC))
    snapshot_date = summary["date"]
    ledger_key = f"daily/{snapshot_date}/ledgers/alice.db"
    marker_key = f"daily/{snapshot_date}/{COMPLETE_MARKER}"
    assert ledger_key in r2.objects

    db.delete_account(account_id, datetime.now(UTC).isoformat(), ledger_id=registered["ledger_id"])
    assert ledger_key in r2.objects
    assert db.list_account_deletions()[0]["applied_at"] is None
    assert db.replay_deletions() == 1
    assert ledger_key not in r2.objects
    manifest = json.loads(r2.objects[marker_key])
    assert "ledgers/alice.db" not in {entry["path"] for entry in manifest["files"]}

    restored = db.backups_dir / "r2-restore" / snapshot_date
    db.offsite_backup.download_snapshot(snapshot_date, restored)
    restore_summary = restore_daily_backup(restored, db=db)
    assert restore_summary["deletions_reapplied"] >= 1
    assert db.get_account(account_id)["deleted_at"] is not None
    assert not db.ledger_exists("alice")
    from service.auth import login_player
    from svc.auth import token_claims, token_version_of
    from svc.dependencies import AccountDeletedError, _authorize_account

    claims = token_claims(token)
    with pytest.raises(AccountDeletedError):
        _authorize_account(db, claims["sub"], token_version_of(claims))
    assert login_player(db, "alice", "correct-horse-1")["ok"] is False


def test_pending_boot_r2_restore_cleans_copy_after_success_and_failure(r2_api, monkeypatch):
    db, _, _ = r2_api
    summary = create_daily_backup(db, now=datetime(2026, 9, 29, tzinfo=UTC))
    snapshot_date = summary["date"]
    downloaded = db.backups_dir / "r2-restore" / f"{snapshot_date}-initial"
    db.offsite_backup.download_snapshot(snapshot_date, downloaded)

    from database import backup

    backup.schedule_restore(db.backups_dir, downloaded, r2_snapshot_date=snapshot_date)

    def fail_restore(snapshot, *, db):
        raise RuntimeError("simulated boot restore failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(backup, "restore_daily_backup", fail_restore)
        with pytest.raises(RuntimeError, match="simulated boot restore failure"):
            backup.apply_pending_restore(db)
    assert not downloaded.exists()
    assert backup.restore_pending_path(db.backups_dir).is_file()

    result = backup.apply_pending_restore(db)
    assert result is not None
    assert not list((db.backups_dir / "r2-restore").glob("*"))
    assert not backup.restore_pending_path(db.backups_dir).exists()


def test_local_daily_backup_succeeds_without_an_r2_store(r2_api):
    db, _, _ = r2_api
    db.offsite_backup = None

    summary = create_daily_backup(db, now=datetime(2026, 9, 29, tzinfo=UTC))

    assert summary["created"] is True
    assert summary["offsite"] is None
    assert (Path(summary["path"]) / "catalog.db").is_file()


def test_same_day_retry_completes_failed_r2_upload_without_impacting_local_backup(r2_api):
    db, r2, _ = r2_api
    _register(db, "alice")
    r2.fail_upload_containing = "ledgers/alice.db"

    first = create_daily_backup(db, now=datetime(2026, 9, 29, tzinfo=UTC))
    assert first["created"] is True
    assert first["offsite"]["complete"] is False
    assert (Path(first["path"]) / "catalog.db").is_file()
    assert f"daily/{first['date']}/{COMPLETE_MARKER}" not in r2.objects

    retry = create_daily_backup(db, now=datetime(2026, 9, 29, tzinfo=UTC))
    assert retry["created"] is False
    assert retry["offsite"]["complete"] is True
    assert f"daily/{retry['date']}/{COMPLETE_MARKER}" in r2.objects


def test_deletion_replay_retries_r2_cleanup(r2_api):
    db, r2, _ = r2_api
    registered = _register(db, "alice")
    summary = create_daily_backup(db, now=datetime(2026, 9, 29, tzinfo=UTC))
    db.record_account_deletion(registered["account_id"], registered["ledger_id"])
    assert db.replay_deletions() >= 1

    # Recreate a stray copy and stale manifest as if a previous cleanup failed.
    day = summary["date"]
    key = f"daily/{day}/ledgers/alice.db"
    marker = f"daily/{day}/{COMPLETE_MARKER}"
    r2.objects[key] = b"stray deleted account ledger"
    content = json.loads(r2.objects[marker])
    content["files"].append(
        {
            "path": "ledgers/alice.db",
            "size": len(r2.objects[key]),
            "sha256": hashlib.sha256(r2.objects[key]).hexdigest(),
        }
    )
    r2.objects[marker] = json.dumps(content).encode()

    assert db.reapply_deletions() >= 1
    assert key not in r2.objects
    assert "ledgers/alice.db" not in {entry["path"] for entry in json.loads(r2.objects[marker])["files"]}


def test_r2_deletion_failure_keeps_record_pending_until_replay_succeeds(r2_api, monkeypatch, caplog):
    db, r2, _ = r2_api
    registered = _register(db, "alice")
    summary = create_daily_backup(db, now=datetime(2026, 9, 29, tzinfo=UTC))
    ledger_key = f"daily/{summary['date']}/ledgers/alice.db"
    litestream_key = "litestream/users/alice.db/ltx/0000/0000000000000001-0000000000000001.ltx"
    r2.objects[litestream_key] = b"replica"
    offsite = db.offsite_backup
    remove_remote_ledger = offsite.remove_ledger

    def fail_remote_delete(ledger_id):
        raise OSError("simulated R2 outage")

    monkeypatch.setattr(offsite, "remove_ledger", fail_remote_delete)
    from service.account_deletion import delete_account

    deletion = delete_account(db, registered["account_id"], "correct-horse-1")
    assert deletion["ok"] is True
    assert ledger_key in r2.objects
    assert litestream_key in r2.objects
    assert db.list_account_deletions()[0]["applied_at"] is None
    assert db.replay_deletions() == 0
    assert any(
        record.levelno >= logging.WARNING and record.name == "myos.database.account_deletion"
        for record in caplog.records
    )

    monkeypatch.setattr(offsite, "remove_ledger", remove_remote_ledger)
    assert db.replay_deletions() >= 1
    assert ledger_key not in r2.objects
    assert litestream_key not in r2.objects
    assert db.list_account_deletions()[0]["applied_at"] is not None


def test_litestream_restore_listing_includes_only_ledger_replica_prefixes(r2_api, monkeypatch):
    db, r2, _ = r2_api
    monkeypatch.setenv("LITESTREAM_R2_PREFIX", "rehearsal/litestream")
    r2.objects.update(
        {
            "rehearsal/litestream/users/alice.db/ltx/0001.ltx": b"alice",
            "rehearsal/litestream/users/bob-123abc.db/ltx/0002.ltx": b"bob",
            "rehearsal/litestream/users/not a username.db/ltx/0003.ltx": b"invalid",
            "rehearsal/litestream/catalog.db/ltx/0004.ltx": b"catalog",
        }
    )

    assert db.offsite_backup.list_litestream_ledger_ids() == ["alice", "bob-123abc"]


def test_external_deletion_and_username_reuse_keep_replica_paths_separate(r2_api):
    db, r2, _ = r2_api
    old = _register(db, "alice")
    old_prefix = f"litestream/users/{old['ledger_id']}.db/"
    old_key = old_prefix + "ltx/0000/old.ltx"
    r2.objects[old_key] = b"old account"

    from service.account_deletion import delete_account_by_username

    assert delete_account_by_username(db, "alice", "correct-horse-1")["ok"] is True
    assert old_key in r2.objects
    assert db.replay_deletions() == 1
    assert old_key not in r2.objects

    new = _register(db, "alice")
    new_prefix = f"litestream/users/{new['ledger_id']}.db/"
    new_key = new_prefix + "ltx/0000/new.ltx"
    r2.objects[new_key] = b"new account"
    assert new["ledger_id"] != old["ledger_id"]
    assert new_prefix != old_prefix

    assert db.replay_deletions() == 0
    assert new_key in r2.objects


def test_account_delete_returns_while_r2_flock_is_held_then_replay_cleans(r2_api):
    db, r2, tmp_path = r2_api
    registered = _register(db, "alice")
    summary = create_daily_backup(db, now=datetime(2026, 9, 29, tzinfo=UTC))
    ledger_key = f"daily/{summary['date']}/ledgers/alice.db"
    lock_fd = os.open(tmp_path / "backups" / ".offsite-r2.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    result = []
    error = []

    def delete():
        try:
            result.append(db.delete_account(
                registered["account_id"],
                datetime.now(UTC).isoformat(),
                ledger_id=registered["ledger_id"],
            ))
        except Exception as exc:
            error.append(exc)

    worker = threading.Thread(target=delete)
    try:
        worker.start()
        worker.join(timeout=1)
        returned_while_locked = not worker.is_alive()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    worker.join(timeout=5)

    assert returned_while_locked
    assert not error
    assert result[0]["ok"] is True
    assert ledger_key in r2.objects
    assert db.list_account_deletions()[0]["applied_at"] is None
    assert db.replay_deletions() == 1
    assert ledger_key not in r2.objects


def test_full_replay_marks_failed_remote_cleanup_pending_again(r2_api, monkeypatch):
    db, r2, _ = r2_api
    registered = _register(db, "alice")
    summary = create_daily_backup(db, now=datetime(2026, 9, 29, tzinfo=UTC))
    db.record_account_deletion(registered["account_id"], registered["ledger_id"])
    assert db.replay_deletions() == 1
    assert db.list_account_deletions()[0]["applied_at"] is not None

    ledger_key = f"daily/{summary['date']}/ledgers/alice.db"
    marker_key = f"daily/{summary['date']}/{COMPLETE_MARKER}"
    r2.objects[ledger_key] = b"stray deleted account ledger"
    manifest = json.loads(r2.objects[marker_key])
    manifest["files"].append(
        {
            "path": "ledgers/alice.db",
            "size": len(r2.objects[ledger_key]),
            "sha256": hashlib.sha256(r2.objects[ledger_key]).hexdigest(),
        }
    )
    r2.objects[marker_key] = json.dumps(manifest).encode()

    offsite = db.offsite_backup
    remove_remote_ledger = offsite.remove_ledger

    def fail_remote_delete(ledger_id):
        raise OSError("simulated R2 outage")

    monkeypatch.setattr(offsite, "remove_ledger", fail_remote_delete)
    assert db.reapply_deletions() == 0
    assert db.list_account_deletions()[0]["applied_at"] is None

    monkeypatch.setattr(offsite, "remove_ledger", remove_remote_ledger)
    assert db.replay_deletions() == 1
    assert ledger_key not in r2.objects
    assert db.list_account_deletions()[0]["applied_at"] is not None
