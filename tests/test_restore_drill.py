import sqlite3
from pathlib import Path

import pytest

from database.backup import CATALOG_SNAPSHOT_NAME, LEDGERS_SUBDIR
from scripts.restore_drill import run_drill


def _database(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES (?)", (value,))


def test_daily_restore_drill_checks_fixture_catalog_and_each_ledger(tmp_path):
    snapshot = tmp_path / "backups" / "daily" / "20261101"
    _database(snapshot / CATALOG_SNAPSHOT_NAME, "catalog")
    _database(snapshot / LEDGERS_SUBDIR / "alice.db", "alice")
    _database(snapshot / LEDGERS_SUBDIR / "bob-123abc.db", "bob")

    report = run_drill(
        tmp_path / "scratch",
        source="daily",
        backups_dir=tmp_path / "backups",
        live_data_dir=tmp_path / "live",
    )

    assert report["count"] == 3
    assert [result for _, result, _ in report["results"]] == ["ok", "ok", "ok"]
    assert all(size > 0 for _, _, size in report["results"])
    assert report["duration"] >= 0


@pytest.mark.parametrize("target_kind", ["live", "contains-db"])
def test_restore_drill_refuses_live_or_mayos_data_directory(tmp_path, target_kind):
    live = tmp_path / "live"
    live.mkdir()
    target = live if target_kind == "live" else tmp_path / "has-data"
    if target_kind == "contains-db":
        _database(target / "users" / "alice.db", "live")

    with pytest.raises(ValueError, match="Refusing restore target"):
        run_drill(
            target,
            source="daily",
            backups_dir=tmp_path / "backups",
            live_data_dir=live,
        )
