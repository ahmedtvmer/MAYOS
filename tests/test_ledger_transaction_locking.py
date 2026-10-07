"""Ledger write-lock scope regressions for issue #368."""

import threading
from pathlib import Path

import pytest

from database.database_manager import DatabaseManager


@pytest.fixture
def store(tmp_path: Path):
    db = DatabaseManager(
        catalog_path=tmp_path / "catalog.db",
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
    )
    try:
        yield db
    finally:
        db.catalog_conn.close()


def _set_busy_timeout(store: DatabaseManager, *ledgers, milliseconds: int) -> None:
    store.catalog_conn.execute(f"PRAGMA busy_timeout = {milliseconds}")
    for ledger in ledgers:
        ledger.conn.execute(f"PRAGMA busy_timeout = {milliseconds}")


def test_issue_368_ledger_transactions_do_not_lock_other_ledgers_or_catalog(store):
    player_a = store.open_ledger("player-a")
    player_b = store.open_ledger("player-b")
    _set_busy_timeout(store, player_a, player_b, milliseconds=100)
    player_b_finished = threading.Event()
    player_b_errors: list[Exception] = []

    def commit_player_b() -> None:
        try:
            with player_b.ledger_transaction():
                pass
        except Exception as exc:  # surfaced in the owning test thread
            player_b_errors.append(exc)
        finally:
            player_b_finished.set()

    player_b_thread = threading.Thread(target=commit_player_b)
    try:
        with player_a.ledger_transaction():
            player_b_thread.start()
            assert player_b_finished.wait(timeout=2)
            assert not player_b_errors
            with store.catalog_transaction(immediate=True):
                store.catalog_conn.execute("UPDATE main.exercises SET id = id WHERE 0")
        player_b_thread.join(timeout=2)
        assert not player_b_thread.is_alive()
        assert not player_b_errors
    finally:
        player_a.close()
        player_b.close()


def test_issue_368_same_ledger_transactions_wait_for_the_first_commit(store):
    first_handle = store.open_ledger("same-player")
    second_handle = store.open_ledger("same-player")
    _set_busy_timeout(store, first_handle, second_handle, milliseconds=1000)
    first_holds_transaction = threading.Event()
    release_first_transaction = threading.Event()
    second_starting = threading.Event()
    second_entered = threading.Event()
    first_errors: list[Exception] = []
    second_errors: list[Exception] = []

    def hold_first_transaction() -> None:
        try:
            with first_handle.ledger_transaction():
                first_holds_transaction.set()
                release_first_transaction.wait(timeout=2)
        except Exception as exc:  # surfaced in the owning test thread
            first_errors.append(exc)

    def commit_second_transaction() -> None:
        first_holds_transaction.wait(timeout=2)
        second_starting.set()
        try:
            with second_handle.ledger_transaction():
                second_entered.set()
        except Exception as exc:  # surfaced in the owning test thread
            second_errors.append(exc)

    first_thread = threading.Thread(target=hold_first_transaction)
    second_thread = threading.Thread(target=commit_second_transaction)
    try:
        first_thread.start()
        assert first_holds_transaction.wait(timeout=2)
        second_thread.start()
        assert second_starting.wait(timeout=2)

        release_timer = threading.Timer(0.15, release_first_transaction.set)
        release_timer.start()
        assert not second_entered.wait(timeout=0.05)
        assert second_entered.wait(timeout=2)
        first_thread.join(timeout=2)
        second_thread.join(timeout=2)
        release_timer.join(timeout=2)

        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert not first_errors
        assert not second_errors
    finally:
        release_first_transaction.set()
        if first_thread.ident is not None:
            first_thread.join(timeout=2)
        if second_thread.ident is not None:
            second_thread.join(timeout=2)
        first_handle.close()
        second_handle.close()
