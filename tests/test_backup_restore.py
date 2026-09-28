"""Daily online backups and safe restore (issue #41, ADR 015/044).

Behavioral tests at the public FastAPI seam, using real temporary SQLite
catalogs and player ledgers with a mocked model. They cover: consistent,
retriable snapshots of the catalog and live-account ledgers; bounded retention; the
user-specific ledger copy being removed with an account; and a
deletion-and-restore drill proving old tokens and accounts stay invalid.
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from database.backup import (
    CATALOG_SNAPSHOT_NAME,
    LEDGERS_SUBDIR,
    ORPHANS_SUBDIR,
    MAX_BACKUP_RETENTION_DAYS,
    apply_pending_restore,
    backup_retention_days,
    create_daily_backup,
    daily_backups_root,
    list_daily_backups,
    prune_daily_backups,
    restore_daily_backup,
    restore_pending_path,
    schedule_restore,
)
from database.database_manager import DatabaseManager
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    # Keep the in-process loops from touching the shared data root during tests.
    monkeypatch.setenv("MAYOS_ALERT_SWEEP_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("MAYOS_DAILY_BACKUP_INTERVAL_SECONDS", "0")
    from svc.rate_limit import limiter

    limiter._storage.reset()
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    for exercise_id, name in (("sq", "Squat"), ("bp", "Bench Press"), ("row", "Row")):
        cat_conn.execute("INSERT INTO exercises (id, name) VALUES (?, ?)", (exercise_id, name))
    cat_conn.commit()
    cat_conn.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        default_ledger_id="bootstrap",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db, tmp_path
    finally:
        db.catalog_conn.close()


def _register(client, username, password="correct-horse-1", remember_me=False):
    resp = client.post(
        "/auth/register",
        json={"trainee_id": username, "password": password, "remember_me": remember_me},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _subject(token):
    return pyjwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])["sub"]


def _delete(client, token, password):
    return client.request("DELETE", "/auth/account", headers=_authed(token), json={"password": password})


def _ledger_copy(day_dir: Path, ledger_id: str) -> Path:
    return day_dir / LEDGERS_SUBDIR / f"{ledger_id}.db"


# --------------------------------------------------------------------------
# 1. Snapshot contents, retriability, and idempotence
# --------------------------------------------------------------------------


def test_daily_backup_covers_catalog_and_live_account_ledgers(api):
    client, db, tmp_path = api
    _register(client, "alice")
    _register(client, "bob")

    summary = create_daily_backup(db)
    assert summary["created"] is True
    assert set(summary["ledgers"]) == {"alice", "bob"}

    day_dir = Path(summary["path"])
    assert (day_dir / CATALOG_SNAPSHOT_NAME).is_file()
    assert _ledger_copy(day_dir, "alice").is_file()
    assert _ledger_copy(day_dir, "bob").is_file()
    # Ledger copies live under ledgers/, never beside the catalog copy, so a
    # ledger id of "catalog" cannot collide with catalog.db (defect #1).
    assert not (day_dir / "alice.db").exists()
    assert not (day_dir / "catalog" / "catalog.db").exists()

    # Each snapshot is a real, queryable SQLite database with the copied rows.
    with sqlite3.connect(_ledger_copy(day_dir, "alice")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] > 0
    with sqlite3.connect(day_dir / CATALOG_SNAPSHOT_NAME) as conn:
        assert conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0] == 3


def test_ledger_named_catalog_does_not_collide_with_the_catalog_copy(api):
    """A player whose ledger id is "catalog" must not overwrite catalog.db (#1)."""
    client, db, tmp_path = api
    _register(client, "catalog")

    summary = create_daily_backup(db)
    day_dir = Path(summary["path"])
    assert (day_dir / CATALOG_SNAPSHOT_NAME).is_file()
    assert _ledger_copy(day_dir, "catalog").is_file()

    # The catalog copy is still the catalog: it has the exercise rows, while the
    # ledger copy has the ledger's own shape.
    with sqlite3.connect(day_dir / CATALOG_SNAPSHOT_NAME) as conn:
        assert conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0] == 3
    with sqlite3.connect(_ledger_copy(day_dir, "catalog")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] > 0

    # A restore writes the ledger into users/, never over the live catalog.
    restore_daily_backup(day_dir, db=db)
    assert db.ledger_exists("catalog")
    with sqlite3.connect(tmp_path / "catalog.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0] == 3


def test_backup_is_idempotent_per_day_and_rerunnable(api):
    client, db, _ = api
    _register(client, "alice")
    first = create_daily_backup(db)
    second = create_daily_backup(db)
    assert second["created"] is False
    assert second["skipped"] is True
    assert second["path"] == first["path"]


def test_failed_backup_publishes_nothing_and_can_retry(api, monkeypatch):
    client, db, _ = api
    _register(client, "alice")

    original_catalog_locked = db.catalog_locked
    monkeypatch.setattr(db, "catalog_locked", lambda: (_ for _ in ()).throw(RuntimeError("disk gone")))
    with pytest.raises(RuntimeError):
        create_daily_backup(db)

    root = daily_backups_root(db.backups_dir)
    if root.is_dir():
        assert [entry for entry in root.iterdir() if not entry.name.startswith(".")] == []
        assert not any(entry.name.startswith(".staging-") for entry in root.iterdir())

    # The same day can be retried once the failure clears.
    monkeypatch.setattr(db, "catalog_locked", original_catalog_locked)
    retried = create_daily_backup(db)
    assert retried["created"] is True
    assert Path(retried["path"]).is_dir()
    assert (Path(retried["path"]) / CATALOG_SNAPSHOT_NAME).is_file()


def test_deletion_during_backup_is_not_republished(api, monkeypatch):
    """A deletion landing between staging and publish must drop the stale copy (#2)."""
    client, db, _ = api
    registered = _register(client, "alice")
    token = registered["access_token"]
    account_id = _subject(token)
    _register(client, "bob")

    import database.backup as backup_module

    real_snapshot_ledger = backup_module._snapshot_ledger_file
    deleted = {"done": False}

    def delete_mid_run(source_path, dest_path):
        real_snapshot_ledger(source_path, dest_path)
        if not deleted["done"]:
            deleted["done"] = True
            # Simulate a concurrent account deletion after the ledger was staged:
            # the catalog row is marked deleted and the account's files (including
            # daily copies) are removed, all before this run publishes.
            db.delete_account(account_id, ledger_id="alice")

    monkeypatch.setattr(backup_module, "_snapshot_ledger_file", delete_mid_run)

    summary = create_daily_backup(db)
    day_dir = Path(summary["path"])
    assert summary["created"] is True
    # The deleted account's staged copy was dropped before os.replace published.
    assert not (day_dir / LEDGERS_SUBDIR / "alice.db").exists()
    assert (day_dir / LEDGERS_SUBDIR / "bob.db").is_file()
    assert "alice" not in summary["ledgers"]


# --------------------------------------------------------------------------
# 2. Bounded retention (ADR 015 disclosure window)
# --------------------------------------------------------------------------


def test_retention_is_bounded_and_documented_window_is_enforced(api):
    client, db, _ = api
    _register(client, "alice")
    root = daily_backups_root(db.backups_dir)
    root.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 9, 28, tzinfo=UTC)
    for offset in (0, 5, 40):
        stale = root / (now - timedelta(days=offset)).strftime("%Y%m%d")
        stale.mkdir()
        (stale / CATALOG_SNAPSHOT_NAME).write_bytes(b"x")

    pruned = prune_daily_backups(root, retention_days=30, now=now)
    assert pruned == [(now - timedelta(days=40)).strftime("%Y%m%d")]
    remaining = {entry.name for entry in root.iterdir() if entry.is_dir()}
    assert now.strftime("%Y%m%d") in remaining
    assert (now - timedelta(days=5)).strftime("%Y%m%d") in remaining

    # A longer configured window is clamped to ADR 015's 30-day ceiling.
    assert backup_retention_days("90") == MAX_BACKUP_RETENTION_DAYS
    assert backup_retention_days("14") == 14
    assert backup_retention_days("garbage") == 30


def test_list_daily_backups_ignores_partial_staging_dirs(api):
    client, db, _ = api
    root = daily_backups_root(db.backups_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "20260928").mkdir()
    (root / "20260928" / CATALOG_SNAPSHOT_NAME).write_bytes(b"catalog")
    (root / ".staging-20260928-abc").mkdir()
    (root / "20260929-nofile").mkdir()

    assert [entry.name for entry in list_daily_backups(db.backups_dir)] == ["20260928"]


# --------------------------------------------------------------------------
# 3. User-specific copies are removed with the account
# --------------------------------------------------------------------------


def test_account_deletion_removes_ledger_copy_from_daily_snapshots(api):
    client, db, _ = api
    registered = _register(client, "alice")
    token = registered["access_token"]
    _register(client, "bob")
    create_daily_backup(db)

    day_dir = next(daily_backups_root(db.backups_dir).iterdir())
    assert _ledger_copy(day_dir, "alice").is_file()
    assert _ledger_copy(day_dir, "bob").is_file()

    assert _delete(client, token, "correct-horse-1").status_code == 200

    # Alice's copy is gone from the snapshot; Bob's survives; the catalog
    # snapshot itself (the documented restricted exception) is untouched.
    assert not _ledger_copy(day_dir, "alice").exists()
    assert _ledger_copy(day_dir, "bob").is_file()
    assert (day_dir / CATALOG_SNAPSHOT_NAME).is_file()


def test_replay_also_removes_daily_ledger_copy(api):
    client, db, _ = api
    registered = _register(client, "alice")
    token = registered["access_token"]
    create_daily_backup(db)
    day_dir = next(daily_backups_root(db.backups_dir).iterdir())
    assert _ledger_copy(day_dir, "alice").is_file()

    assert _delete(client, token, "correct-horse-1").status_code == 200
    # Simulate a stale copy reappearing after the deletion (for example a snapshot
    # published by a run that started before the deletion committed): the full
    # replay must remove the user-specific copy.
    _ledger_copy(day_dir, "alice").write_bytes(b"stray")
    assert db.reapply_deletions() >= 1
    assert not _ledger_copy(day_dir, "alice").exists()


# --------------------------------------------------------------------------
# 4. Deletion-and-restore drill
# --------------------------------------------------------------------------


def test_deletion_and_restore_drill_keeps_identity_deleted(api):
    client, db, tmp_path = api
    registered = _register(client, "alice", remember_me=True)
    token = registered["access_token"]
    account_id = _subject(token)

    # The player records a workout so the ledger has real content to restore.
    with db.open_ledger("alice") as ledger:
        ledger.upsert_player_profile({"current_goal": "Strength"})
    assert client.get("/profile", headers=_authed(token)).status_code == 200

    snapshot = create_daily_backup(db)
    assert _ledger_copy(Path(snapshot["path"]), "alice").is_file()

    # Delete the account after the snapshot was taken.
    assert _delete(client, token, "correct-horse-1").status_code == 200
    assert not db.ledger_exists("alice")
    assert client.get("/auth/me", headers=_authed(token)).json() == {"error": "account_deleted"}

    # Restore the pre-deletion snapshot, then reapply the current deletions
    # record. The catalog is rolled back, but the durable record lives outside
    # the snapshot, so the identity stays deleted.
    result = restore_daily_backup(Path(snapshot["path"]), db=db)
    assert result["deletions_reapplied"] >= 1
    assert db.get_account(account_id)["deleted_at"] is not None
    assert not db.ledger_exists("alice")
    assert not (tmp_path / "users" / "alice.db").exists()

    # Old tokens stay invalid, login fails, and the account is not recreated.
    me = client.get("/auth/me", headers=_authed(token))
    assert me.status_code == 401
    assert me.json() == {"error": "account_deleted"}
    bad_login = client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"})
    assert bad_login.status_code == 401
    assert db.get_active_account_by_username("alice") is None

    # Registering the name again creates a distinct immutable account with an
    # empty ledger, and the restored pre-deletion data is not visible to it.
    fresh = _register(client, "alice")
    fresh_id = _subject(fresh["access_token"])
    assert fresh_id != account_id
    assert client.get("/profile", headers=_authed(fresh["access_token"])).status_code == 404


def test_restore_quarantines_orphaned_ledgers_and_frees_the_username(api):
    """An account created after the snapshot must not be stranded (#3)."""
    client, db, tmp_path = api
    _register(client, "alice")
    snapshot = create_daily_backup(db)

    # B is created after the snapshot, so the restored catalog has no row for B.
    b = _register(client, "bob")
    b_id = _subject(b["access_token"])
    assert db.ledger_exists("bob")

    result = restore_daily_backup(Path(snapshot["path"]), db=db)

    # B's ledger row is gone from the restored catalog and B's live ledger was
    # quarantined, not deleted, so the owner can recover it.
    assert db.get_account(b_id) is None
    assert not db.ledger_exists("bob")
    assert "bob" in result["quarantined_ledgers"]
    quarantine = tmp_path / "backups" / ORPHANS_SUBDIR
    moved = list(quarantine.rglob("bob.db"))
    assert len(moved) == 1
    assert moved[0].stat().st_size > 0
    # The account's -wal/-shm companions move with it when present.

    # The username can be registered again (the ledger file no longer blocks it).
    fresh = _register(client, "bob")
    assert _subject(fresh["access_token"]) != b_id


def test_restore_does_not_quarantine_live_account_ledgers(api):
    client, db, _ = api
    _register(client, "alice")
    snapshot = create_daily_backup(db)
    result = restore_daily_backup(Path(snapshot["path"]), db=db)
    assert result["quarantined_ledgers"] == []
    assert db.ledger_exists("alice")


# --------------------------------------------------------------------------
# 5. Boot-time scheduled restore (Fly: the only volume-owning writer)
# --------------------------------------------------------------------------


def test_schedule_restore_writes_a_pending_marker(api):
    client, db, _ = api
    _register(client, "alice")
    snapshot = Path(create_daily_backup(db)["path"])

    marker = schedule_restore(db.backups_dir, snapshot)
    assert marker == restore_pending_path(db.backups_dir)
    assert marker.is_file()
    payload = json.loads(marker.read_text())
    assert payload["snapshot"] == str(snapshot.resolve())
    # The marker lives beside the snapshots, never inside one.
    assert marker.parent == Path(db.backups_dir)
    assert not (snapshot / marker.name).exists()


def test_schedule_restore_refuses_a_missing_snapshot(api):
    client, db, tmp_path = api
    with pytest.raises(FileNotFoundError):
        schedule_restore(db.backups_dir, tmp_path / "does-not-exist")
    assert not restore_pending_path(db.backups_dir).exists()


def test_pending_restore_applies_once_and_clears_marker(api):
    client, db, _ = api
    registered = _register(client, "alice")
    token = registered["access_token"]
    assert client.post(
        "/auth/email", headers=_authed(token), json={"email": "alice@example.com"}
    ).status_code == 200
    snapshot = Path(create_daily_backup(db)["path"])
    schedule_restore(db.backups_dir, snapshot)
    assert restore_pending_path(db.backups_dir).is_file()

    result = apply_pending_restore(db)
    assert result is not None
    assert result["snapshot"] == str(snapshot.resolve())
    # Applied exactly once: the marker is gone and a second call does nothing.
    assert not restore_pending_path(db.backups_dir).exists()
    assert apply_pending_restore(db) is None
    # The account survived the restore.
    assert db.get_account_email(_subject(token)) == "alice@example.com"


def test_boot_restore_of_pre_deletion_snapshot_keeps_identity_deleted(api):
    """The deletion-and-restore drill, run through the boot-time path."""
    client, db, tmp_path = api
    registered = _register(client, "alice", remember_me=True)
    token = registered["access_token"]
    account_id = _subject(token)
    with db.open_ledger("alice") as ledger:
        ledger.upsert_player_profile({"current_goal": "Strength"})

    snapshot = Path(create_daily_backup(db)["path"])
    assert _delete(client, token, "correct-horse-1").status_code == 200
    assert not db.ledger_exists("alice")

    # Schedule the restore an operator would use on Fly, then boot.
    schedule_restore(db.backups_dir, snapshot)
    result = apply_pending_restore(db)
    assert result is not None
    assert result["deletions_reapplied"] >= 1

    assert not restore_pending_path(db.backups_dir).exists()
    assert db.get_account(account_id)["deleted_at"] is not None
    assert not db.ledger_exists("alice")
    assert not (tmp_path / "users" / "alice.db").exists()
    me = client.get("/auth/me", headers=_authed(token))
    assert me.status_code == 401
    assert me.json() == {"error": "account_deleted"}
    assert client.post("/auth/login", json={"trainee_id": "alice", "password": "correct-horse-1"}).status_code == 401
    assert db.get_active_account_by_username("alice") is None


def test_pending_restore_failure_leaves_the_marker(api, monkeypatch):
    client, db, _ = api
    _register(client, "alice")
    snapshot = Path(create_daily_backup(db)["path"])
    schedule_restore(db.backups_dir, snapshot)

    def failing_restore(*args, **kwargs):
        raise RuntimeError("simulated restore failure")

    monkeypatch.setattr("database.backup.restore_daily_backup", failing_restore)
    with pytest.raises(RuntimeError):
        apply_pending_restore(db)

    # The marker stays so the next boot retries; nothing pretends to be restored.
    assert restore_pending_path(db.backups_dir).is_file()


def test_unreadable_marker_fails_closed(api):
    client, db, _ = api
    marker = restore_pending_path(db.backups_dir)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unreadable"):
        apply_pending_restore(db)
    # A corrupt marker is left for an operator to inspect rather than guessed at.
    assert marker.is_file()

