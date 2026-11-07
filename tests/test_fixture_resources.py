"""Regression for #580: fixture connections accumulated until EMFILE on Linux."""

import os
from pathlib import Path

import pytest

from database.database_manager import DatabaseManager


def _descriptor_count():
    with os.scandir("/proc/self/fd") as descriptors:
        return sum(1 for _ in descriptors)


@pytest.fixture(scope="module", autouse=True)
def _descriptor_sample(seeded_catalog):
    if not Path("/proc/self/fd").is_dir():
        pytest.skip("Open-file regression check requires Linux /proc/self/fd")
    # Seed/model startup precedes the measurement. Each parameter is a separate
    # pytest test, so the final sample includes all function fixture teardown.
    before = _descriptor_count()
    yield
    after = _descriptor_count()
    assert after <= before, f"Fixture descriptors grew across 32 tests: {before} -> {after}"


@pytest.mark.parametrize("sample", range(32))
def test_store_and_explicit_ledgers_leave_no_descriptors_between_tests(fresh_store, tmp_path, sample):
    # The shared lifecycle fixture owns these handles, including ones opened by
    # callers other than the convenience db.ledger binding. Do not call GC:
    # delayed sqlite finalizers would hide the leak this regression detects.
    store = DatabaseManager(
        catalog_path=tmp_path / "secondary.db",
        ledgers_dir=tmp_path / "secondary-users",
        backups_dir=tmp_path / "secondary-backups",
    )
    for database in (fresh_store, store):
        ledger = database.open_ledger(f"sample-{sample}")
        ledger.upsert_player_profile({"weekly_frequency": 3})
        assert ledger.get_player_profile()["weekly_frequency"] == 3
