"""Behavioral tests for revision-backed active-program caching."""

import shutil
import sqlite3
import copy
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.migration_manager import (
    CURRENT_LEDGER_SCHEMA_VERSION,
    get_ledger_schema_version,
    restore_atomic_backup,
)
from database.program_cache import ReadOnlyDict, ReadOnlyList, active_program
from svc.app import create_app
from svc.dependencies import get_db


def test_program_state_source_has_no_utf8_bom():
    source = Path(__file__).parents[1] / "agent" / "ProgramState.py"
    assert not source.read_bytes().startswith(b"\xef\xbb\xbf")


def test_readonly_containers_deepcopy_with_or_without_memo():
    frozen_list = ReadOnlyList([ReadOnlyDict({"name": "program"})])
    for memo in (None, {}):
        mutable_list = frozen_list.__deepcopy__() if memo is None else frozen_list.__deepcopy__(memo)
        assert type(mutable_list) is list
        assert type(mutable_list[0]) is dict
        mutable_list[0]["name"] = "mutable"


def _program(exercise_id="squat", name="Cache test"):
    return {
        "program_name": name,
        "weekly_frequency": 1,
        "split_type": "custom",
        "days": [{
            "day_name": "Day 1",
            "day_order": 1,
            "exercises": [{
                "exercise_id": exercise_id,
                "target_sets": 3,
                "target_reps_min": 5,
                "target_reps_max": 8,
                "target_rpe": 8.5,
                "rest_seconds": 120,
            }],
        }],
    }


def _seed_program(ledger, exercise_id="squat"):
    library_row = ledger.conn.execute(
        "SELECT 1 FROM exercises WHERE id=?", (exercise_id,)
    ).fetchone()
    coach_row = ledger.conn.execute(
        "SELECT 1 FROM catalog.coach_exercises WHERE id=?", (exercise_id,)
    ).fetchone()
    if library_row is None and coach_row is None:
        ledger.conn.execute(
            "INSERT INTO catalog.exercises(id,name,body_part,target_muscle,equipment) "
            "VALUES(?, 'Cache exercise', 'Chest', 'Chest', 'barbell')",
            (exercise_id,),
        )
        ledger.conn.commit()
    ledger.save_training_program(_program(exercise_id))


def test_cached_program_is_read_only_and_refreshes_after_player_write(fresh_store):
    ledger = fresh_store.ledger
    _seed_program(ledger)
    first = ledger.get_active_program_view()
    assert isinstance(first.days, list)
    assert isinstance(first.days[0].exercises, list)
    assert isinstance(first.model_dump()["days"], list)
    with pytest.raises((TypeError, AttributeError, ValueError)):
        first.program_name = "Changed in caller"
    with pytest.raises((TypeError, AttributeError)):
        first.days[0].exercises.append(first.days[0].exercises[0])
    with pytest.raises((TypeError, AttributeError, ValueError)):
        first.days[0].exercises[0].exercise_name = "Changed in caller"
    with pytest.raises(TypeError):
        del first.program_name
    with pytest.raises(TypeError):
        del first.days[0].exercises[0].exercise_name

    deep = copy.deepcopy(first)
    assert deep.model_dump() == first.model_dump()
    deep.days[0].exercises.append(deep.days[0].exercises[0])
    deep.program_name = "Mutable copy"
    assert first.program_name == "Cache test"
    assert len(first.days[0].exercises) == 1
    model_deep = first.model_copy(deep=True)
    model_deep.days[0].exercises.append(model_deep.days[0].exercises[0])
    assert len(first.days[0].exercises) == 1
    shallow = first.model_copy()
    with pytest.raises((TypeError, AttributeError)):
        shallow.days[0].exercises.append(shallow.days[0].exercises[0])

    mutable = ledger.get_active_program()
    mutable.program_name = "Fresh mutable load"
    mutable.days[0].exercises.append(mutable.days[0].exercises[0])
    assert ledger.get_active_program_view().program_name == "Cache test"

    ledger.save_training_program(_program(name="Player edit"))
    assert ledger.get_active_program_view().program_name == "Player edit"


def test_active_program_api_reads_the_revision_backed_store(fresh_store, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-0123456789abcdef")
    app = create_app()
    app.dependency_overrides[get_db] = lambda: fresh_store
    with TestClient(app) as client:
        registered = client.post(
            "/auth/register",
            json={"trainee_id": "cache-api-player", "password": "correct-horse-1"},
        )
        assert registered.status_code == 201, registered.text
        headers = {"Authorization": f"Bearer {registered.json()['access_token']}"}
        account = fresh_store.get_active_account_by_username("cache-api-player")
        ledger = fresh_store.open_ledger(account["ledger_id"])
        try:
            _seed_program(ledger)
            first = client.get("/programs/active", headers=headers)
            assert first.status_code == 200, first.text
            assert first.json()["program_name"] == "Cache test"
            ledger.save_training_program(_program(name="API sees write"))
            second = client.get("/programs/active", headers=headers)
            assert second.status_code == 200, second.text
            assert second.json()["program_name"] == "API sees write"
            fresh_store.catalog_conn.execute(
                "INSERT INTO exercises(id,name,body_part,target_muscle,equipment) "
                "VALUES('cache-replacement','Replacement','Chest','Chest','barbell')"
            )
            fresh_store.catalog_conn.commit()
            substitution = client.post(
                "/programs/active/substitutions",
                headers=headers,
                json={
                    "day_name": "Day 1",
                    "exercise_id": "squat",
                    "replacement_exercise_id": "cache-replacement",
                },
            )
            assert substitution.status_code == 200, substitution.text
            assert ledger.get_active_program_view().days[0].exercises[0].exercise_id == "cache-replacement"
            after_substitution = client.get("/programs/active", headers=headers)
            assert after_substitution.status_code == 200, after_substitution.text
            assert after_substitution.json()["days"][0]["exercises"][0]["exercise_id"] == "cache-replacement"
        finally:
            ledger.close()
        deleted = client.request("DELETE", "/auth/account", headers=headers, json={"password": "correct-horse-1"})
        assert deleted.status_code == 200, deleted.text
        replacement = client.post(
            "/auth/register",
            json={"trainee_id": "cache-api-player", "password": "correct-horse-1"},
        )
        assert replacement.status_code == 201, replacement.text
        new_account = fresh_store.get_active_account_by_username("cache-api-player")
        new_ledger = fresh_store.open_ledger(new_account["ledger_id"])
        try:
            assert new_ledger.get_active_program_view() is None
        finally:
            new_ledger.close()


def test_raw_sql_and_catalog_display_name_writes_refresh_program(fresh_store):
    ledger = fresh_store.ledger
    _seed_program(ledger)
    assert ledger.get_active_program_view().days[0].exercises[0].exercise_name == "Cache exercise"

    fresh_store.catalog_conn.execute(
        "INSERT OR REPLACE INTO exercise_display_names(exercise_id,display_name) VALUES(?,?)",
        ("squat", "Curated cache name"),
    )
    fresh_store.catalog_conn.commit()
    assert ledger.get_active_program_view().days[0].exercises[0].exercise_name == "Curated cache name"

    ledger.conn.execute("UPDATE program_exercises SET notes='raw SQL edit'")
    ledger.conn.commit()
    assert ledger.get_active_program_view().days[0].exercises[0].notes == "raw SQL edit"


def test_coach_exercise_rename_refreshes_program(fresh_store):
    ledger = fresh_store.ledger
    coach_id = fresh_store.catalog_conn.execute("SELECT account_id FROM accounts LIMIT 1").fetchone()
    owner_id = str(coach_id[0]) if coach_id else "cache-coach"
    fresh_store.catalog_conn.execute(
        "INSERT INTO coach_exercises(id,coach_account_id,name,body_part,equipment,created_at) "
        "VALUES(?,?,?,?,?,?)",
        ("coach-cache-ex", owner_id, "Before rename", "Chest", "barbell", "2026-11-01"),
    )
    fresh_store.catalog_conn.commit()
    _seed_program(ledger, "coach-cache-ex")
    assert ledger.get_active_program_view().days[0].exercises[0].exercise_name == "Before rename"

    fresh_store.catalog_conn.execute(
        "UPDATE coach_exercises SET name='After rename' WHERE id='coach-cache-ex'"
    )
    fresh_store.catalog_conn.commit()
    assert ledger.get_active_program_view().days[0].exercises[0].exercise_name == "After rename"


def test_rolled_back_program_load_is_not_cached(fresh_store):
    ledger = fresh_store.ledger
    _seed_program(ledger)
    ledger.get_active_program_view()
    with pytest.raises(RuntimeError, match="rollback"):
        with ledger.ledger_transaction():
            ledger.conn.execute("UPDATE program_exercises SET notes='rolled back'")
            assert ledger.get_active_program_view().days[0].exercises[0].notes == "rolled back"
            raise RuntimeError("rollback")

    ledger.conn.execute("UPDATE program_exercises SET notes='committed later'")
    ledger.commit_ledger()
    assert ledger.get_active_program_view().days[0].exercises[0].notes == "committed later"


def test_open_current_ledger_recreates_revision_schema_without_version_bump(fresh_store):
    ledger = fresh_store.ledger
    ledger_id = ledger.ledger_id
    before_version = get_ledger_schema_version(ledger.conn)
    assert before_version == CURRENT_LEDGER_SCHEMA_VERSION
    ledger.conn.execute("DROP TABLE program_revision")
    ledger.conn.commit()
    ledger.close()

    reopened = fresh_store.open_ledger(ledger_id)
    try:
        assert reopened.conn.execute("SELECT 1 FROM program_revision WHERE id=1").fetchone()
        assert reopened.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='program_revision_program_exercises_update'"
        ).fetchone()
        assert get_ledger_schema_version(reopened.conn) == before_version
    finally:
        reopened.close()


def test_program_cache_kill_switch_rebuilds_each_time(fresh_store, monkeypatch):
    ledger = fresh_store.ledger
    _seed_program(ledger)
    monkeypatch.setenv("MAYOS_PROGRAM_CACHE", "off")
    loads = 0
    original = ledger._load_program

    def count_loads(*args, **kwargs):
        nonlocal loads
        loads += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(ledger, "_load_program", count_loads)
    ledger.get_active_program_view()
    ledger.get_active_program_view()
    assert loads == 2


def test_program_cache_lru_bound_and_restore_replacement(fresh_store, tmp_path, monkeypatch):
    monkeypatch.setenv("MAYOS_PROGRAM_CACHE_SIZE", "1")
    first = fresh_store.ledger
    _seed_program(first)
    first.get_active_program_view()
    ledger_path = fresh_store.ledgers_dir / f"{first.ledger_id}.db"
    replacement = tmp_path / "replacement.db"
    backup_conn = sqlite3.connect(replacement)
    first.conn.backup(backup_conn)
    backup_conn.close()
    first.close()
    shutil.copyfile(replacement, ledger_path)
    reopened = fresh_store.open_ledger(first.ledger_id)
    load_count = 0
    original_loader = reopened._load_program

    def count_loads(*args, **kwargs):
        nonlocal load_count
        load_count += 1
        return original_loader(*args, **kwargs)

    monkeypatch.setattr(reopened, "_load_program", count_loads)
    try:
        reopened.conn.execute("UPDATE program_exercises SET notes='restored file'")
        reopened.commit_ledger()
        assert reopened.get_active_program_view().days[0].exercises[0].notes == "restored file"
        second = fresh_store.open_ledger("cache-lru-second")
        try:
            _seed_program(second)
            second.get_active_program_view()
        finally:
            second.close()
        reopened.get_active_program_view()
        assert load_count == 2
    finally:
        reopened.close()


def test_slow_miss_does_not_block_warmed_ledger_hit():
    from database import program_cache

    program_cache._entries.clear()

    class FakeLedger:
        def __init__(self, ledger_id):
            self.ledger_id = ledger_id

        def active_program_cache_state(self):
            return ("g", 1, "c", 1), False

    warmed = FakeLedger("warm")
    blocked = FakeLedger("blocked")
    active_program(warmed, lambda: {"name": "warm"})
    started = threading.Event()
    release = threading.Event()

    def slow_loader():
        started.set()
        release.wait(3)
        return {"name": "slow"}

    worker = threading.Thread(target=lambda: active_program(blocked, slow_loader))
    worker.start()
    assert started.wait(2)
    try:
        assert active_program(warmed, lambda: pytest.fail("cache hit should not load"))["name"] == "warm"
    finally:
        release.set()
        worker.join(3)
        program_cache._entries.clear()


def test_restore_rotates_revision_generation_before_next_write(fresh_store, tmp_path):
    ledger = fresh_store.ledger
    _seed_program(ledger)
    ledger.conn.execute("UPDATE program_revision SET counter=0 WHERE id=1")
    ledger.conn.commit()
    snapshot = tmp_path / "snapshot.db"
    snapshot_conn = sqlite3.connect(snapshot)
    ledger.conn.backup(snapshot_conn)
    snapshot_conn.close()
    ledger.conn.execute("UPDATE program_exercises SET notes='B'")
    ledger.conn.commit()
    cached_b = ledger.get_active_program_view()
    cached_revision = ledger.active_program_cache_state()[0]
    assert cached_b.days[0].exercises[0].notes == "B"
    restore_atomic_backup(snapshot, ledger.conn)
    ledger.conn.execute("UPDATE program_exercises SET notes='C'")
    ledger.conn.commit()
    assert ledger.active_program_cache_state()[0][1] == cached_revision[1]
    assert ledger.get_active_program_view().days[0].exercises[0].notes == "C"
