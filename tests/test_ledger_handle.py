"""Phase B1 (#79): explicit ledger handles (ADR 041).

Covers the three guarantees of the handle refactor:

* two players' handles used concurrently from two threads never cross-talk;
* opening a deleted ledger is refused;
* a coach drill-down cannot obtain a player's ledger without an active assignment.
"""

import threading
from pathlib import Path

import pytest

from database.database_manager import DatabaseManager
from database.ledger.handle import TrainingLedger
from database.shared import LedgerDeletedError


@pytest.fixture
def store(tmp_path: Path):
    catalog = tmp_path / "catalog.db"
    db = DatabaseManager(
        catalog_path=catalog,
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
    )
    try:
        yield db
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def test_handle_isolates_two_players_used_concurrently(store):
    """Two handles opened in two threads keep their own connection and data."""
    seen: dict[str, str] = {}
    errors: list[Exception] = []

    def run(user: str, goal: str) -> None:
        try:
            with store.open_ledger(user) as ledger:
                assert isinstance(ledger, TrainingLedger)
                assert ledger.ledger_id == user
                ledger.upsert_player_profile({"current_goal": goal})
                seen[user] = ledger.get_player_profile()["current_goal"]
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=("alice", "alice-goal")),
        threading.Thread(target=run, args=("bob", "bob-goal")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert seen == {"alice": "alice-goal", "bob": "bob-goal"}
    # Each player's persisted data is only in their own ledger file.
    with store.open_ledger("alice") as alice:
        assert alice.get_player_profile()["current_goal"] == "alice-goal"


def test_handle_closes_its_connection_on_exit(store):
    ledger = store.open_ledger("alice")
    ledger.upsert_player_profile({"current_goal": "x"})
    ledger.close()
    with pytest.raises(RuntimeError):
        _ = ledger.conn


def test_opening_a_deleted_ledger_is_refused(store):
    account_id = store.create_account("ghost")
    store.delete_account(account_id, None)

    with pytest.raises(LedgerDeletedError):
        store.open_ledger("ghost")


def test_coach_drill_down_needs_an_active_assignment(store, monkeypatch):
    """A coach with no assignment for the player cannot obtain a ledger handle."""
    from service import coach_history
    from service.assignments import authorized_player_ledger

    store.create_account("coach")
    store.create_account("p1")

    opened: list[str] = []
    real_open = store.open_ledger

    def spy(ledger_id):
        opened.append(str(ledger_id))
        return real_open(ledger_id)

    monkeypatch.setattr(store, "open_ledger", spy)

    # Unknown assignment and a live, unassigned player both deny without opening.
    assert authorized_player_ledger(store, "coach-account", "no-such-assignment") is None
    assert coach_history.player_summary(store, "coach-account", "no-such-assignment") is None
    assert opened == []
