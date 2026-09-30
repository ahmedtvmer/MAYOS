# tests/test_migration_manager.py
import sqlite3
from pathlib import Path

import pytest

from agent.progression_engine import set_e1rm
from database.database_manager import DatabaseManager
from database.migration_manager import (
    CURRENT_LEDGER_SCHEMA_VERSION,
    MIGRATION_REGISTRY,
    apply_lazy_migrations,
    create_atomic_backup,
    get_ledger_schema_version,
    prune_ledger_backups,
    restore_atomic_backup,
    set_ledger_schema_version,
)


@pytest.fixture
def temp_db_env(tmp_path: Path, monkeypatch):
    catalog_path = tmp_path / "catalog.db"
    ledgers_dir = tmp_path / "users"
    backups_dir = tmp_path / "backups"

    # Create dummy catalog
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute("CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT);")
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.commit()
    cat_conn.close()

    db = DatabaseManager(
        catalog_path=catalog_path,
        ledgers_dir=ledgers_dir,
        backups_dir=backups_dir,
        default_ledger_id="alice",
    )
    try:
        assert db.catalog_path == catalog_path
        assert db.ledgers_dir == ledgers_dir
        assert db.backups_dir == backups_dir
        yield db, ledgers_dir, backups_dir
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def test_schema_version_stamping(temp_db_env):
    db, ledgers_dir, _ = temp_db_env
    version = get_ledger_schema_version(db.conn)
    assert version == CURRENT_LEDGER_SCHEMA_VERSION


def test_atomic_backup_and_restore(temp_db_env):
    db, ledgers_dir, backups_dir = temp_db_env
    db.ledger.add_chat_message("user", "Hello backup test")

    snapshot_path = backups_dir / "alice" / "test_snap.db"
    create_atomic_backup(db.conn, snapshot_path)
    assert snapshot_path.is_file()

    # Clear chat in active DB
    db.ledger.clear_chat_history()
    assert len(db.ledger.get_chat_history()) == 0

    # Restore from snapshot
    restore_atomic_backup(snapshot_path, db.conn)
    history = db.ledger.get_chat_history()
    assert len(history) == 1
    assert history[0]["content"] == "Hello backup test"


def test_rolling_backup_pruning(tmp_path: Path):
    ledger_backup_dir = tmp_path / "backups" / "bob"
    ledger_backup_dir.mkdir(parents=True)

    # Create 5 rolling backups and 1 immutable pre-migration backup
    for i in range(5):
        f = ledger_backup_dir / f"bob_auto_20260901_0{i}.db"
        f.write_text("test")
    pre_mig = ledger_backup_dir / "bob_pre_v1_to_v2_20260901_00.db"
    pre_mig.write_text("pre-migration")

    prune_ledger_backups(ledger_backup_dir, max_rolling=3)

    remaining = list(ledger_backup_dir.glob("*.db"))
    assert pre_mig in remaining  # Immutable backup preserved
    rolling = [f for f in remaining if "_pre_v" not in f.name]
    assert len(rolling) == 3


def test_lazy_migration_execution_and_rollback(temp_db_env, monkeypatch):
    db, ledgers_dir, backups_dir = temp_db_env

    # Simulate an upgrade from v1 to v2
    def mock_migrate_v1_to_v2(conn: sqlite3.Connection):
        conn.execute("ALTER TABLE user_profile ADD COLUMN test_column TEXT DEFAULT 'migrated';")

    saved_entry = MIGRATION_REGISTRY.get(1)
    saved_v2_entry = MIGRATION_REGISTRY.get(2)
    MIGRATION_REGISTRY[1] = mock_migrate_v1_to_v2
    try:
        # Reset version to 1 to simulate pending migration to v2
        set_ledger_schema_version(db.conn, 1)
        db.conn.commit()

        apply_lazy_migrations(
            conn=db.conn,
            username="alice",
            ledgers_dir=ledgers_dir,
            backups_dir=backups_dir,
            target_version=2,
        )

        assert get_ledger_schema_version(db.conn) == 2
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
                ledgers_dir=ledgers_dir,
                backups_dir=backups_dir,
                target_version=3,
            )

        # Version must have rolled back to 2
        assert get_ledger_schema_version(db.conn) == 2
    finally:
        if saved_entry is None:
            MIGRATION_REGISTRY.pop(1, None)
        else:
            MIGRATION_REGISTRY[1] = saved_entry
        if saved_v2_entry is None:
            MIGRATION_REGISTRY.pop(2, None)
        else:
            MIGRATION_REGISTRY[2] = saved_v2_entry


def test_assistant_memory_persistence_and_user_separation(temp_db_env):
    db, ledgers_dir, _ = temp_db_env
    db.ledger.upsert_player_profile({})
    profile = db.ledger.get_player_profile()
    assert db.ledger.get_assistant_memory() == {}
    db.ledger.set_assistant_memory("preferred_name", "Alice")
    db.ledger.set_assistant_memory("preferred_name", "O'Connor")
    assert db.ledger.get_assistant_memory() == {"preferred_name": "O'Connor"}
    assert db._test_ledger_id == "alice"
    assert db.ledger.get_player_profile() == profile
    assert sorted(path.name for path in ledgers_dir.glob("*.db")) == ["alice.db"]
    db.ledger.clear_chat_history()
    db.create_ledger_schema()
    assert db.ledger.get_assistant_memory() == {"preferred_name": "O'Connor"}
    db.switch_user("bob")
    assert db.ledger.get_assistant_memory() == {}
    db.ledger.set_assistant_memory("preferred_name", "Bob")
    db.switch_user("alice")
    assert db.ledger.get_assistant_memory() == {"preferred_name": "O'Connor"}
    db.switch_user("bob")
    assert db.ledger.get_assistant_memory() == {"preferred_name": "Bob"}


@pytest.mark.parametrize("key", ["name", "username", "custom_instructions", "", "preferred_name'; --"])
def test_assistant_memory_rejects_unsupported_keys(temp_db_env, key):
    db, _, _ = temp_db_env
    with pytest.raises(ValueError, match="Unsupported"):
        db.ledger.set_assistant_memory(key, "Alice")
    assert db.ledger.get_assistant_memory() == {}


@pytest.mark.parametrize("value", [None, 12, True, {}, [], "", "   ", "A" * 61, "Alice\nBob", "A\x00B"])
def test_assistant_memory_rejects_invalid_values(temp_db_env, value):
    db, _, _ = temp_db_env
    db.ledger.set_assistant_memory("preferred_name", "Alice")
    with pytest.raises(ValueError, match="Preferred name"):
        db.ledger.set_assistant_memory("preferred_name", value)
    assert db.ledger.get_assistant_memory() == {"preferred_name": "Alice"}


@pytest.mark.parametrize("value", ["A", "A" * 60, "Élodie", "Anne-Marie", "O'Connor"])
def test_assistant_memory_accepts_bounded_names(temp_db_env, value):
    db, _, _ = temp_db_env
    db.ledger.set_assistant_memory("preferred_name", value)
    assert db.ledger.get_assistant_memory() == {"preferred_name": value}


@pytest.mark.parametrize("version", [0, CURRENT_LEDGER_SCHEMA_VERSION])
def test_existing_ledger_gets_assistant_memory_idempotently(temp_db_env, version):
    db, _, _ = temp_db_env
    db.ledger.upsert_player_profile({})
    profile = db.ledger.get_player_profile()
    db.ledger.add_chat_message("user", "Preserve history")
    db.ledger.log_workout_session("old", "2026-09-16", "Upper", "2026-09-16T10:00:00", None)
    db.ledger.log_workout_set("old-set", "old", "missing", 1, 10.0, 8, 8.0)
    db.conn.execute("DROP TABLE assistant_memory")
    set_ledger_schema_version(db.conn, version)
    db.conn.commit()
    db.switch_user("bob")
    db.switch_user("alice")
    assert db.ledger.get_assistant_memory() == {}
    db.ledger.set_assistant_memory("preferred_name", "Alice")
    db.create_ledger_schema()
    db.create_ledger_schema()
    assert db.ledger.get_assistant_memory() == {"preferred_name": "Alice"}
    assert db.ledger.get_player_profile() == profile
    assert db.ledger.get_chat_history()[0]["content"] == "Preserve history"
    assert db.ledger.get_latest_session_summary()["sets_count"] == 1
    assert get_ledger_schema_version(db.conn) == CURRENT_LEDGER_SCHEMA_VERSION


def test_latest_session_summary_uses_real_working_sets(temp_db_env):
    db, _, _ = temp_db_env
    db.catalog_conn.executemany(
        "INSERT INTO exercises (id, name) VALUES (?, ?)",
        [("bench", "Bench press"), ("row", "Row"), ("warmup", "Warmup only")],
    )
    db.catalog_conn.commit()
    db.ledger.log_workout_session("old", "2026-09-15", "Old", "2026-09-15T12:00:00", None)
    db.ledger.log_workout_set("old-set", "old", "bench", 1, 200, 20, 8)
    db.ledger.log_workout_session("latest'; --", "2026-09-16", "Upper", "2026-09-16T12:00:00", None, 3)
    for set_id, exercise_id, index, weight, reps, warmup in [
        ("b1", "bench", 1, 100, 8, 0),
        ("b2", "bench", 2, 90, 10, 0),
        ("r1", "row", 1, 50, 12, 0),
        ("bw", "bench", 0, 20, 15, 1),
        ("w1", "warmup", 1, 30, 10, 1),
        ("m1", "missing", 1, 0, 10, 0),
    ]:
        db.ledger.log_workout_set(set_id, "latest'; --", exercise_id, index, weight, reps, 8, warmup)
    expected = {
        "session_id": "latest'; --",
        "session_date": "2026-09-16",
        "split_name": "Upper",
        "readiness_score": 3,
        "program_version": None,
        "active_program_version_at_sync": None,
        "uploaded_at": None,
        "edited_at": None,
        "corrections": [],
        "sets_count": 4,
        "total_volume_kg": 2300.0,
        "exercises": [
            {"name": "Bench press", "sets": 2, "reps": 18, "volume_kg": 1700.0},
            {"name": "missing", "sets": 1, "reps": 10, "volume_kg": 0.0},
            {"name": "Row", "sets": 1, "reps": 12, "volume_kg": 600.0},
        ],
        "divergences": [],
        "warmup_movements": [],
    }
    assert db.ledger.get_latest_session_summary() == expected
    db.switch_user("bob")
    assert db.ledger.get_latest_session_summary() is None
    db.ledger.log_workout_session("bob", "2026-09-17", "Lower", "2026-09-17T12:00:00", None)
    assert db.ledger.get_latest_session_summary()["split_name"] == "Lower"
    db.switch_user("alice")
    assert db.ledger.get_latest_session_summary() == expected


def test_latest_session_summary_empty_and_warmup_only(temp_db_env):
    db, _, _ = temp_db_env
    assert db.ledger.get_latest_session_summary() is None
    db.ledger.log_workout_session("old", "2026-09-15", "Old", "2026-09-15T12:00:00", None)
    db.ledger.log_workout_set("old-set", "old", "bench", 1, 100, 8, 8)
    db.ledger.log_workout_session("empty", "2026-09-16", "Empty", "2026-09-16T12:00:00", None, None)
    expected = {
        "session_id": "empty",
        "session_date": "2026-09-16",
        "split_name": "Empty",
        "readiness_score": None,
        "program_version": None,
        "active_program_version_at_sync": None,
        "uploaded_at": None,
        "edited_at": None,
        "corrections": [],
        "sets_count": 0,
        "total_volume_kg": 0.0,
        "exercises": [],
        "divergences": [],
        "warmup_movements": [],
    }
    assert db.ledger.get_latest_session_summary() == expected
    db.ledger.log_workout_set("warmup", "empty", "bench", 1, 20, 10, 5, 1)
    assert db.ledger.get_latest_session_summary() == expected


def test_latest_session_summary_deterministic_ordering(temp_db_env):
    db, _, _ = temp_db_env
    for session_id, date, started_at in [
        ("latest-date", "2026-09-16", "2026-09-16T08:00:00"),
        ("backdated", "2026-09-15", "2026-09-17T12:00:00"),
    ]:
        db.ledger.log_workout_session(session_id, date, session_id, started_at, None)
    assert db.ledger.get_latest_session_summary()["split_name"] == "latest-date"
    db.ledger.log_workout_session("later-start", "2026-09-16", "Later start", "2026-09-16T10:00:00", None)
    db.ledger.log_workout_session("early-start", "2026-09-16", "Early start", "2026-09-16T07:00:00", None)
    assert db.ledger.get_latest_session_summary()["split_name"] == "Later start"
    db.ledger.log_workout_session("tie", "2026-09-16", "Tie", "2026-09-16T10:00:00", None)
    assert db.ledger.get_latest_session_summary()["split_name"] == "Tie"
    assert db.ledger.get_latest_session_summary()["split_name"] == "Tie"


def test_session_comparison_empty_and_user_isolation(temp_db_env):
    db, _, _ = temp_db_env
    assert db.ledger.get_session_comparison_context() is None
    db.ledger.log_workout_session("empty", "2026-09-16", "Upper", "2026-09-16T08:00:00", None, None, "Rested")
    expected = {
        "best_set_convention": "heaviest weight, then most reps, then earliest set_index",
        "session": {
            "id": "empty",
            "session_date": "2026-09-16",
            "started_at": "2026-09-16T08:00:00",
            "split_name": "Upper",
            "readiness_score": None,
            "session_notes": "Rested",
        },
        "previous_session": None,
        "exercises": [],
    }
    assert db.ledger.get_session_comparison_context() == expected
    db.ledger.log_workout_set("warmup", "empty", "bench", 0, 20, 10, 5, 1)
    assert db.ledger.get_session_comparison_context() == expected
    db.switch_user("bob")
    assert db.ledger.get_session_comparison_context() is None
    db.switch_user("alice")
    assert db.ledger.get_session_comparison_context() == expected


def test_session_comparison_exact_baselines_and_bounded_queries(temp_db_env):
    db, _, _ = temp_db_env
    db.catalog_conn.executemany(
        "INSERT INTO exercises (id, name) VALUES (?, ?)",
        [("bench", "Press"), ("variant", "Press"), ("row", "Row")],
    )
    db.catalog_conn.commit()
    for session_id, date, start in [
        ("older", "2026-09-14", "2026-09-14T10:00:00"),
        ("baseline", "2026-09-16", "2026-09-16T08:00:00"),
        ("global-previous", "2026-09-16", "2026-09-16T09:00:00"),
        ("current'; --", "2026-09-16", "2026-09-16T10:00:00"),
        ("backdated", "2026-09-15", "2026-09-17T12:00:00"),
    ]:
        db.ledger.log_workout_session(session_id, date, session_id, start, None, 3, session_id + " notes")
    for set_id, session_id, exercise_id, index, weight, reps, rpe, warmup in [
        ("older", "older", "bench", 1, 150, 20, 8, 0),
        ("b2", "baseline", "bench", 2, 90, 8, 8, 0),
        ("b1", "baseline", "bench", 1, 90, 8, 9, 0),
        ("bw", "baseline", "bench", 0, 300, 30, 8, 1),
        ("variant", "global-previous", "variant", 1, 200, 20, 8, 0),
        ("warm-bench", "global-previous", "bench", 0, 200, 20, 8, 1),
        ("row", "global-previous", "row", 1, 50, 10, 8, 0),
        ("c3", "current'; --", "bench", 3, 100, 10, 7, 0),
        ("c2", "current'; --", "bench", 2, 100, 10, 8, 0),
        ("c1", "current'; --", "bench", 1, 100, 8, 8, 0),
        ("c4", "current'; --", "bench", 4, 80, 30, 8, 0),
        ("cw", "current'; --", "bench", 0, 400, 40, 8, 1),
        ("warm-only", "current'; --", "warm-only", 0, 20, 10, 8, 1),
        ("new", "current'; --", "missing'; --", 1, 0, 10, None, 0),
        ("current-row", "current'; --", "row", 1, 50, 10, 8, 0),
        ("backdated-set", "backdated", "bench", 1, 500, 50, 8, 0),
    ]:
        db.ledger.log_workout_set(set_id, session_id, exercise_id, index, weight, reps, rpe, warmup)
    summary = db.ledger.get_latest_session_summary()
    queries = []
    db.conn.set_trace_callback(queries.append)
    try:
        context = db.ledger.get_session_comparison_context()
    finally:
        db.conn.set_trace_callback(None)
    assert db.ledger.get_latest_session_summary() == summary
    assert context["session"]["id"] == "current'; --"
    assert context["session"]["session_notes"] == "current'; -- notes"
    assert context["previous_session"]["id"] == "global-previous"
    assert [e["exercise_id"] for e in context["exercises"]] == ["missing'; --", "bench", "row"]
    missing, bench, row = context["exercises"]
    assert missing["name"] == "missing'; --"
    assert missing["previous"] is None
    assert missing["status"] == "insufficient_data"
    assert missing["deltas"] == dict.fromkeys(["load_kg", "reps", "sets", "volume_kg", "e1rm"])
    assert bench["previous"]["session"]["id"] == "baseline"
    assert bench["previous"]["session"]["session_notes"] == "baseline notes"
    assert bench["previous"]["best_set"] == {"set_index": 1, "weight_kg": 90, "reps": 8, "rpe": 9}
    assert bench["current"] == {
        "sets": [
            {"set_index": 1, "weight_kg": 100, "reps": 8, "rpe": 8},
            {"set_index": 2, "weight_kg": 100, "reps": 10, "rpe": 8},
            {"set_index": 3, "weight_kg": 100, "reps": 10, "rpe": 7},
            {"set_index": 4, "weight_kg": 80, "reps": 30, "rpe": 8},
        ],
        "sets_count": 4,
        "total_reps": 58,
        "volume_kg": 5200,
        "best_set": {"set_index": 2, "weight_kg": 100, "reps": 10, "rpe": 8},
        "e1rm": pytest.approx(140),
    }
    assert bench["deltas"] == {
        "load_kg": 10, "reps": 2, "sets": 2, "volume_kg": 3760, "e1rm": pytest.approx(23),
    }
    assert bench["status"] == "improvement"
    assert row["previous"]["session"] == context["previous_session"]
    assert row["status"] == "unchanged"
    assert set(bench) == {"exercise_id", "name", "current", "previous", "deltas", "status"}
    assert set(bench["previous"]) == set(bench["current"]) | {"session"}
    normalized = [" ".join(query.lower().split()) for query in queries]
    assert normalized[0].endswith("limit 2")
    baseline_queries = [query for query in normalized if "and exists" in query]
    assert len(baseline_queries) == 3
    assert all("(s.session_date, s.started_at, s.rowid) <" in query and query.endswith("limit 1") for query in baseline_queries)
    set_queries = [query for query in normalized if query.startswith("select ws.set_index")]
    assert len(set_queries) == 5
    assert all("ws.session_id =" in query and "ws.exercise_id =" in query for query in set_queries)


def test_session_comparison_same_day_rowid_ties(temp_db_env):
    db, _, _ = temp_db_env
    for session_id, start in [("first", "10:00:00"), ("earlier", "07:00:00"), ("tie", "10:00:00")]:
        db.ledger.log_workout_session(session_id, "2026-09-16", "Upper", "2026-09-16T" + start, None)
        db.ledger.log_workout_set(session_id, session_id, "bench", 1, 100, 8, 8)
    context = db.ledger.get_session_comparison_context()
    assert context["session"]["id"] == "tie"
    assert context["previous_session"]["id"] == "first"
    assert context["exercises"][0]["previous"]["session"]["id"] == "first"
    assert db.ledger.get_session_comparison_context() == context


@pytest.mark.parametrize(
    "previous,current,status",
    [
        ((100, 8, 8), (110, 9, 8), "improvement"),
        ((100, 8, 8), (90, 7, 8), "decline"),
        ((100, 8, 8), (100, 8, 8), "unchanged"),
        ((100, 8, 8), (110, 7, 8), "mixed"),
        ((100, 8, 8), (100, 8, 7), "improvement"),
        ((100, 8, 8), (100, 8, 9), "decline"),
        ((100, 8, 6), (100, 9, 10), "mixed"),
        # An unrated best set is scored with set_e1rm (plain Epley), so the
        # comparison reports its real status instead of refusing (#111).
        ((100, 8, None), (110, 9, 8), "improvement"),
        ((100, 8, 8), (110, 9, None), "improvement"),
        ((100, 8, None), (110, 9, None), "improvement"),
        ((0, 8, 8), (0, 9, 8), "improvement"),
        ((0, 8, None), (0, 9, None), "improvement"),
    ],
)
def test_session_comparison_strength_scores_unrated_best_sets_too(temp_db_env, previous, current, status):
    db, _, _ = temp_db_env
    for session_id, date, values in [("previous", "2026-09-15", previous), ("current", "2026-09-16", current)]:
        db.ledger.log_workout_session(session_id, date, "Upper", date + "T10:00:00", None)
        db.ledger.log_workout_set(session_id, session_id, "bench", 1, *values)
        db.ledger.log_workout_set(session_id + "-backoff", session_id, "bench", 2, 0, 1, 8)
    exercise = db.ledger.get_session_comparison_context()["exercises"][0]
    assert exercise["status"] == status
    assert exercise["deltas"]["load_kg"] == current[0] - previous[0]
    assert exercise["deltas"]["reps"] == current[1] - previous[1]
    assert exercise["deltas"]["volume_kg"] == current[0] * current[1] - previous[0] * previous[1]
    for key, values in [("previous", previous), ("current", current)]:
        if values[0] <= 0:
            # No load, no e1RM.
            assert exercise[key]["e1rm"] is None
        else:
            # Rated or not, a set with a load is scored through set_e1rm; an
            # unrated one is plain Epley (#111).
            assert exercise[key]["e1rm"] == pytest.approx(
                set_e1rm(values[0], values[1], values[2]), abs=0.01
            )
    if exercise["previous"]["e1rm"] is None or exercise["current"]["e1rm"] is None:
        assert exercise["deltas"]["e1rm"] is None


@pytest.mark.parametrize("extra_session", ["previous", "current"])
def test_session_comparison_volume_and_sets_do_not_decide_strength(temp_db_env, extra_session):
    db, _, _ = temp_db_env
    for session_id, date in [("previous", "2026-09-15"), ("current", "2026-09-16")]:
        db.ledger.log_workout_session(session_id, date, "Upper", date + "T10:00:00", None)
        db.ledger.log_workout_set(session_id, session_id, "bench", 1, 100, 8, 8)
    db.ledger.log_workout_set("extra", extra_session, "bench", 2, 80, 10, 8)
    exercise = db.ledger.get_session_comparison_context()["exercises"][0]
    sign = 1 if extra_session == "current" else -1
    assert exercise["deltas"] == {"load_kg": 0, "reps": 0, "sets": sign, "volume_kg": sign * 800, "e1rm": 0}
    assert exercise["status"] == "unchanged"


def test_v1_to_v2_adds_password_hash_preserving_data(temp_db_env):

    from database.migration_manager import CURRENT_LEDGER_SCHEMA_VERSION, get_ledger_schema_version

    db, ledgers_dir, _ = temp_db_env
    # Craft a legacy v1 ledger: no password_hash column, stamped v1.
    legacy_path = ledgers_dir / "legacy.db"
    conn = sqlite3.connect(legacy_path)
    conn.execute(
        "CREATE TABLE user_profile (id INTEGER PRIMARY KEY, current_goal TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO user_profile VALUES (1, 'Strength', '2026-01-01T00:00:00+00:00')")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    # Fresh manager so the legacy file migrates on mount.
    migrated = DatabaseManager(
        catalog_path=db.catalog_path, ledgers_dir=ledgers_dir, backups_dir=db.backups_dir, default_ledger_id="legacy"
    )
    try:
        assert get_ledger_schema_version(migrated.conn) == CURRENT_LEDGER_SCHEMA_VERSION
        tables = {row[0] for row in migrated.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "auth_credentials" in tables
        assert migrated.ledger.get_player_profile()["current_goal"] == "Strength"
        assert migrated.ledger.get_password_hash() is None
        assert migrated.ledger.get_token_version() == 1
    finally:
        if migrated.ledger_conn is not None:
            migrated.ledger_conn.close()
        migrated.catalog_conn.close()


def test_v2_to_v3_adds_token_version_preserving_hash(temp_db_env):

    from database.migration_manager import CURRENT_LEDGER_SCHEMA_VERSION, get_ledger_schema_version

    db, ledgers_dir, _ = temp_db_env
    # Craft a v2 ledger: auth_credentials without token_version, stamped v2.
    legacy_path = ledgers_dir / "v2user.db"
    conn = sqlite3.connect(legacy_path)
    conn.execute(
        "CREATE TABLE user_profile (id INTEGER PRIMARY KEY, current_goal TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO user_profile VALUES (1, 'Strength', '2026-01-01T00:00:00+00:00')")
    conn.execute(
        "CREATE TABLE auth_credentials (id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),"
        " password_hash TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO auth_credentials VALUES (1, '$2b$12$fakehash', '2026-01-01T00:00:00+00:00')")
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()
    migrated = DatabaseManager(
        catalog_path=db.catalog_path, ledgers_dir=ledgers_dir, backups_dir=db.backups_dir, default_ledger_id="v2user"
    )
    try:
        assert get_ledger_schema_version(migrated.conn) == CURRENT_LEDGER_SCHEMA_VERSION
        assert migrated.ledger.get_password_hash() == "$2b$12$fakehash"
        assert migrated.ledger.get_token_version() == 1
        assert migrated.ledger.bump_token_version() == 2
        assert migrated.ledger.get_token_version() == 2
        assert migrated.ledger.get_password_hash() == "$2b$12$fakehash"
    finally:
        if migrated.ledger_conn is not None:
            migrated.ledger_conn.close()
        migrated.catalog_conn.close()


def test_v3_to_v4_backfills_personal_records(temp_db_env):

    from database.migration_manager import CURRENT_LEDGER_SCHEMA_VERSION, get_ledger_schema_version

    db, ledgers_dir, _ = temp_db_env
    legacy_path = ledgers_dir / "v3lifter.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript("""
        CREATE TABLE user_profile (id INTEGER PRIMARY KEY, current_goal TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO user_profile VALUES (1, 'Strength', '2026-01-01T00:00:00+00:00');
        CREATE TABLE auth_credentials (
            id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1), password_hash TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        INSERT INTO auth_credentials VALUES (1, '$2b$12$fakehash', '2026-01-01T00:00:00+00:00');
        CREATE TABLE workout_sessions (id TEXT PRIMARY KEY, session_date TEXT, started_at TEXT);
        INSERT INTO workout_sessions VALUES ('s1', '2026-01-01', '2026-01-01T10:00:00+00:00');
        INSERT INTO workout_sessions VALUES ('s2', '2026-02-01', '2026-02-01T10:00:00+00:00');
        CREATE TABLE workout_sets (
            id TEXT PRIMARY KEY, session_id TEXT, exercise_id TEXT, set_index INTEGER,
            weight_kg REAL, reps INTEGER, rpe REAL, is_warmup INTEGER, logged_at TEXT
        );
        INSERT INTO workout_sets VALUES ('w1', 's1', 'squat', 1, 100, 5, 8.0, 0, '2026-01-01T10:05:00+00:00');
        INSERT INTO workout_sets VALUES ('w2', 's2', 'squat', 1, 100, 5, 8.0, 0, '2026-02-01T10:05:00+00:00');
        INSERT INTO workout_sets VALUES ('w3', 's2', 'squat', 2, 105, 3, 9.0, 0, '2026-02-01T10:10:00+00:00');
        INSERT INTO workout_sets VALUES ('w4', 's1', 'squat', 0, 60, 5, 8.0, 1, '2026-01-01T10:00:00+00:00');
    """)
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()

    migrated = DatabaseManager(
        catalog_path=db.catalog_path, ledgers_dir=ledgers_dir, backups_dir=db.backups_dir, default_ledger_id="v3lifter"
    )
    try:
        assert get_ledger_schema_version(migrated.conn) == CURRENT_LEDGER_SCHEMA_VERSION
        rows = migrated.conn.execute("""
            SELECT record_type, reps, value, prev_value, achieved_at, session_id
            FROM personal_records
            ORDER BY record_type, reps
        """).fetchall()
        assert [(r["record_type"], r["reps"]) for r in rows] == [
            ("max_e1rm", 5),
            ("max_weight", 3),
            ("max_weight", 5),
        ]
        # Oldest e1RM/5-rep exposure wins the tie: first-achievement semantics at s1.
        e1rm_row = rows[0]
        assert e1rm_row["value"] == pytest.approx(100 * (1 + 7.0 / 30), abs=0.01)
        assert e1rm_row["session_id"] == "s1"
        assert e1rm_row["achieved_at"] == "2026-01-01T10:05:00+00:00"
        three_rep = rows[1]
        assert three_rep["value"] == 105
        assert three_rep["session_id"] == "s2"
        # Warmups never seed records.
        assert all(r["prev_value"] is None for r in rows)
        assert len(rows) == 3
    finally:
        if migrated.ledger_conn is not None:
            migrated.ledger_conn.close()
        migrated.catalog_conn.close()


def test_v4_to_v5_adds_program_slot_and_warmup_columns(temp_db_env):

    db, ledgers_dir, _ = temp_db_env
    legacy_path = ledgers_dir / "v4lifter.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript("""
        CREATE TABLE user_profile (id INTEGER PRIMARY KEY, current_goal TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO user_profile VALUES (1, 'Strength', '2026-01-01T00:00:00+00:00');
        CREATE TABLE training_programs (
            id TEXT PRIMARY KEY, program_name TEXT NOT NULL, name TEXT NOT NULL,
            split_type TEXT NOT NULL, weekly_frequency INTEGER NOT NULL,
            is_active INTEGER DEFAULT 1, created_at TEXT NOT NULL
        );
        INSERT INTO training_programs VALUES ('p1', 'Legacy', 'Legacy', 'Upper/Lower', 4, 1, '2026-01-01T00:00:00+00:00');
        CREATE TABLE program_days (
            id TEXT PRIMARY KEY, program_id TEXT NOT NULL, day_name TEXT NOT NULL, day_order INTEGER NOT NULL
        );
        INSERT INTO program_days VALUES ('d1', 'p1', 'Upper', 1);
        CREATE TABLE program_exercises (
            id TEXT PRIMARY KEY, day_id TEXT NOT NULL, exercise_id TEXT NOT NULL, order_in_day INTEGER NOT NULL,
            target_sets INTEGER NOT NULL, target_reps_min INTEGER NOT NULL, target_reps_max INTEGER NOT NULL,
            target_rpe REAL, rest_seconds INTEGER DEFAULT 120, notes TEXT
        );
        INSERT INTO program_exercises VALUES ('e1', 'd1', 'bench', 1, 3, 6, 10, 8.5, 120, 'cue');
    """)
    conn.execute("PRAGMA user_version = 4")
    conn.commit()
    conn.close()

    migrated = DatabaseManager(
        catalog_path=db.catalog_path, ledgers_dir=ledgers_dir, backups_dir=db.backups_dir, default_ledger_id="v4lifter"
    )
    try:
        assert get_ledger_schema_version(migrated.conn) == CURRENT_LEDGER_SCHEMA_VERSION
        program_cols = {r[1] for r in migrated.conn.execute("PRAGMA table_info(training_programs)")}
        assert "instructions" in program_cols
        day_cols = {r[1] for r in migrated.conn.execute("PRAGMA table_info(program_days)")}
        assert {"warmup_json", "cardio"}.issubset(day_cols)
        exercise_cols = {r[1] for r in migrated.conn.execute("PRAGMA table_info(program_exercises)")}
        assert {"slot_key", "warmup_sets"}.issubset(exercise_cols)
        legacy = migrated.conn.execute("SELECT exercise_id, target_sets FROM program_exercises").fetchall()
        assert legacy[0]["exercise_id"] == "bench"
    finally:
        if migrated.ledger_conn is not None:
            migrated.ledger_conn.close()
        migrated.catalog_conn.close()


def test_v5_to_v6_backfills_stable_program_versions(temp_db_env):

    from database.migration_manager import CURRENT_LEDGER_SCHEMA_VERSION, get_ledger_schema_version

    db, ledgers_dir, _ = temp_db_env
    legacy_path = ledgers_dir / "v5lifter.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript("""
        CREATE TABLE user_profile (id INTEGER PRIMARY KEY, current_goal TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO user_profile VALUES (1, 'Strength', '2026-01-01T00:00:00+00:00');
        CREATE TABLE training_programs (
            id TEXT PRIMARY KEY, program_name TEXT NOT NULL, name TEXT NOT NULL,
            split_type TEXT NOT NULL, weekly_frequency INTEGER NOT NULL,
            instructions TEXT DEFAULT '', is_active INTEGER DEFAULT 1, created_at TEXT NOT NULL
        );
        INSERT INTO training_programs VALUES ('p2', 'Second', 'Second', 'Upper/Lower', 4, '', 1, '2026-02-01T00:00:00+00:00');
        INSERT INTO training_programs VALUES ('p1', 'First', 'First', 'Full Body', 3, '', 0, '2026-01-01T00:00:00+00:00');
        INSERT INTO training_programs VALUES ('p3', 'Third', 'Third', 'PPL', 5, '', 0, '2026-03-01T00:00:00+00:00');
    """)
    conn.execute("PRAGMA user_version = 5")
    conn.commit()
    conn.close()

    migrated = DatabaseManager(
        catalog_path=db.catalog_path, ledgers_dir=ledgers_dir, backups_dir=db.backups_dir, default_ledger_id="v5lifter"
    )
    try:
        assert get_ledger_schema_version(migrated.conn) == CURRENT_LEDGER_SCHEMA_VERSION
        program_cols = {r[1] for r in migrated.conn.execute("PRAGMA table_info(training_programs)")}
        assert {"version", "published_by_coach_account_id"}.issubset(program_cols)
        rows = migrated.conn.execute(
            "SELECT id, version, published_by_coach_account_id FROM training_programs ORDER BY version ASC"
        ).fetchall()
        # Sequential by created_at, stable, and self-service provenance stays NULL.
        assert [(r[0], int(r[1])) for r in rows] == [("p1", 1), ("p2", 2), ("p3", 3)]
        assert all(r[2] is None for r in rows)
    finally:
        if migrated.ledger_conn is not None:
            migrated.ledger_conn.close()
        migrated.catalog_conn.close()


def test_v6_to_v7_adds_session_divergences(temp_db_env):

    from database.migration_manager import CURRENT_LEDGER_SCHEMA_VERSION, get_ledger_schema_version

    db, ledgers_dir, _ = temp_db_env
    legacy_path = ledgers_dir / "v6lifter.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript("""
        CREATE TABLE user_profile (id INTEGER PRIMARY KEY, current_goal TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO user_profile VALUES (1, 'Strength', '2026-01-01T00:00:00+00:00');
        CREATE TABLE workout_sessions (id TEXT PRIMARY KEY, session_date TEXT, started_at TEXT);
        INSERT INTO workout_sessions VALUES ('s1', '2026-01-01', '2026-01-01T10:00:00+00:00');
        CREATE TABLE workout_sets (
            id TEXT PRIMARY KEY, session_id TEXT, exercise_id TEXT, set_index INTEGER,
            weight_kg REAL, reps INTEGER, rpe REAL, is_warmup INTEGER, logged_at TEXT
        );
        INSERT INTO workout_sets VALUES ('w1', 's1', 'squat', 1, 100, 5, 8.0, 0, '2026-01-01T10:05:00+00:00');
    """)
    conn.execute("PRAGMA user_version = 6")
    conn.commit()
    conn.close()

    migrated = DatabaseManager(
        catalog_path=db.catalog_path, ledgers_dir=ledgers_dir, backups_dir=db.backups_dir, default_ledger_id="v6lifter"
    )
    try:
        assert get_ledger_schema_version(migrated.conn) == CURRENT_LEDGER_SCHEMA_VERSION
        tables = {row[0] for row in migrated.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "session_divergences" in tables
        migrated.ledger.record_session_divergences(
            "s1",
            [{"kind": "skipped", "exercise_id": "bench", "exercise_name": "Bench Press"}],
            "2026-01-01T10:06:00+00:00",
        )
        rows = migrated.ledger.list_session_divergences("s1")
        assert [(r["kind"], r["exercise_id"], r["exercise_name"]) for r in rows] == [
            ("skipped", "bench", "Bench Press")
        ]
        # Divergences are session history: deleting the session cascades them away.
        migrated.conn.execute("DELETE FROM workout_sessions WHERE id = 's1'")
        migrated.conn.commit()
        assert migrated.ledger.list_session_divergences("s1") == []
    finally:
        if migrated.ledger_conn is not None:
            migrated.ledger_conn.close()
        migrated.catalog_conn.close()


def test_v7_to_v8_adds_training_schedules_and_pauses(temp_db_env):

    from database.migration_manager import CURRENT_LEDGER_SCHEMA_VERSION, get_ledger_schema_version

    db, ledgers_dir, _ = temp_db_env
    legacy_path = ledgers_dir / "v7lifter.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript("""
        CREATE TABLE user_profile (id INTEGER PRIMARY KEY, current_goal TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO user_profile VALUES (1, 'Strength', '2026-01-01T00:00:00+00:00');
        CREATE TABLE workout_sessions (id TEXT PRIMARY KEY, session_date TEXT, started_at TEXT);
        INSERT INTO workout_sessions VALUES ('s1', '2026-01-01', '2026-01-01T10:00:00+00:00');
        CREATE TABLE session_divergences (
            session_id TEXT NOT NULL, exercise_id TEXT NOT NULL, exercise_name TEXT NOT NULL,
            kind TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (session_id, exercise_id, kind)
        );
    """)
    conn.execute("PRAGMA user_version = 7")
    conn.commit()
    conn.close()

    migrated = DatabaseManager(
        catalog_path=db.catalog_path, ledgers_dir=ledgers_dir, backups_dir=db.backups_dir, default_ledger_id="v7lifter"
    )
    try:
        assert get_ledger_schema_version(migrated.conn) == CURRENT_LEDGER_SCHEMA_VERSION
        tables = {row[0] for row in migrated.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {"training_schedules", "training_pauses"} <= tables
        migrated.ledger.append_training_schedule("v7lifter", [1, 3], "UTC", "2026-01-01", "2026-01-01T00:00:00+00:00")
        assert migrated.ledger.get_schedule_effective_on("v7lifter", "2026-02-01")["weekdays"] == [1, 3]
        migrated.ledger.schedule_training_pause("v7lifter", "2026-02-01", "2026-02-03", "2026-01-31T00:00:00+00:00")
        active = migrated.ledger.list_active_or_upcoming_training_pauses("v7lifter", "2026-02-02")
        assert [(p["starts_on"], p["ends_on"]) for p in active] == [("2026-02-01", "2026-02-03")]
    finally:
        if migrated.ledger_conn is not None:
            migrated.ledger_conn.close()
        migrated.catalog_conn.close()


def test_v8_to_v9_adds_offline_sync_columns_and_session_commits(temp_db_env):

    from database.migration_manager import CURRENT_LEDGER_SCHEMA_VERSION, get_ledger_schema_version

    db, ledgers_dir, _ = temp_db_env
    legacy_path = ledgers_dir / "v8lifter.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript("""
        CREATE TABLE user_profile (id INTEGER PRIMARY KEY, current_goal TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO user_profile VALUES (1, 'Strength', '2026-01-01T00:00:00+00:00');
        CREATE TABLE workout_sessions (
            id TEXT PRIMARY KEY, session_date TEXT NOT NULL, split_name TEXT NOT NULL,
            started_at TEXT NOT NULL, completed_at TEXT, session_notes TEXT,
            readiness_score INTEGER, coach_debrief TEXT
        );
        INSERT INTO workout_sessions VALUES ('legacy', '2026-01-01', 'Full A', '2026-01-01T10:00:00+00:00', NULL, NULL, 4, NULL);
        CREATE TABLE training_schedules (
            id TEXT PRIMARY KEY, trainee_id TEXT NOT NULL, weekdays TEXT NOT NULL,
            timezone TEXT NOT NULL, effective_from TEXT NOT NULL, created_at TEXT NOT NULL
        );
    """)
    conn.execute("PRAGMA user_version = 8")
    conn.commit()
    conn.close()

    migrated = DatabaseManager(
        catalog_path=db.catalog_path, ledgers_dir=ledgers_dir, backups_dir=db.backups_dir, default_ledger_id="v8lifter"
    )
    try:
        assert get_ledger_schema_version(migrated.conn) == CURRENT_LEDGER_SCHEMA_VERSION
        columns = {r[1] for r in migrated.conn.execute("PRAGMA table_info(workout_sessions)")}
        assert {"client_session_id", "performed_timezone", "program_version", "captured_at", "uploaded_at"} <= columns
        tables = {row[0] for row in migrated.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "session_commits" in tables
        # Legacy rows keep NULL sync fields, so the partial unique index allows them.
        assert migrated.conn.execute(
            "SELECT client_session_id FROM workout_sessions WHERE id = 'legacy'"
        ).fetchone()[0] is None
        migrated.ledger.record_session_commit("client-1", "legacy", '{"session_id": "legacy"}', "2026-01-01T10:01:00+00:00")
        assert migrated.ledger.get_session_commit("client-1")["response_json"] == '{"session_id": "legacy"}'
        assert migrated.ledger.get_session_commit("nope") is None
        # Re-initialising the schema is idempotent.
        migrated.create_ledger_schema()
        assert migrated.ledger.get_session_commit("client-1")["session_id"] == "legacy"
    finally:
        if migrated.ledger_conn is not None:
            migrated.ledger_conn.close()
        migrated.catalog_conn.close()


def test_v9_to_v10_adds_active_program_version_at_sync(temp_db_env):

    from database.migration_manager import CURRENT_LEDGER_SCHEMA_VERSION, get_ledger_schema_version

    db, ledgers_dir, _ = temp_db_env
    legacy_path = ledgers_dir / "v9lifter.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript("""
        CREATE TABLE user_profile (id INTEGER PRIMARY KEY, current_goal TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO user_profile VALUES (1, 'Strength', '2026-01-01T00:00:00+00:00');
        CREATE TABLE workout_sessions (
            id TEXT PRIMARY KEY, session_date TEXT NOT NULL, split_name TEXT NOT NULL,
            started_at TEXT NOT NULL, completed_at TEXT, session_notes TEXT,
            readiness_score INTEGER, coach_debrief TEXT, client_session_id TEXT,
            performed_timezone TEXT, program_version INTEGER, captured_at TEXT, uploaded_at TEXT
        );
        INSERT INTO workout_sessions (id, session_date, split_name, started_at, program_version)
            VALUES ('legacy', '2026-01-01', 'Full A', '2026-01-01T10:00:00+00:00', 2);
    """)
    conn.execute("PRAGMA user_version = 9")
    conn.commit()
    conn.close()

    migrated = DatabaseManager(
        catalog_path=db.catalog_path, ledgers_dir=ledgers_dir, backups_dir=db.backups_dir, default_ledger_id="v9lifter"
    )
    try:
        assert get_ledger_schema_version(migrated.conn) == CURRENT_LEDGER_SCHEMA_VERSION
        columns = {r[1] for r in migrated.conn.execute("PRAGMA table_info(workout_sessions)")}
        assert "active_program_version_at_sync" in columns
        # Existing rows keep a NULL active version, so they are never read as historical.
        row = migrated.conn.execute(
            "SELECT program_version, active_program_version_at_sync FROM workout_sessions WHERE id = 'legacy'"
        ).fetchone()
        assert row["program_version"] == 2
        assert row["active_program_version_at_sync"] is None
        # Re-initialising the schema is idempotent.
        migrated.create_ledger_schema()
        assert "active_program_version_at_sync" in {
            r[1] for r in migrated.conn.execute("PRAGMA table_info(workout_sessions)")
        }
    finally:
        if migrated.ledger_conn is not None:
            migrated.ledger_conn.close()
        migrated.catalog_conn.close()


def test_v10_to_v11_adds_edited_at_and_performed_date_corrections(temp_db_env):

    from database.migration_manager import CURRENT_LEDGER_SCHEMA_VERSION, get_ledger_schema_version

    db, ledgers_dir, _ = temp_db_env
    legacy_path = ledgers_dir / "v10lifter.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript("""
        CREATE TABLE user_profile (id INTEGER PRIMARY KEY, current_goal TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO user_profile VALUES (1, 'Strength', '2026-01-01T00:00:00+00:00');
        CREATE TABLE workout_sessions (
            id TEXT PRIMARY KEY, session_date TEXT NOT NULL, split_name TEXT NOT NULL,
            started_at TEXT NOT NULL, completed_at TEXT, session_notes TEXT,
            readiness_score INTEGER, coach_debrief TEXT, client_session_id TEXT,
            performed_timezone TEXT, program_version INTEGER, active_program_version_at_sync INTEGER,
            captured_at TEXT, uploaded_at TEXT
        );
        INSERT INTO workout_sessions (id, session_date, split_name, started_at, captured_at, uploaded_at)
            VALUES ('legacy', '2026-01-01', 'Full A', '2026-01-01T10:00:00+00:00',
                    '2026-01-01T10:00:00+00:00', '2026-01-01T10:05:00+00:00');
    """)
    conn.execute("PRAGMA user_version = 10")
    conn.commit()
    conn.close()

    migrated = DatabaseManager(
        catalog_path=db.catalog_path, ledgers_dir=ledgers_dir, backups_dir=db.backups_dir, default_ledger_id="v10lifter"
    )
    try:
        assert get_ledger_schema_version(migrated.conn) == CURRENT_LEDGER_SCHEMA_VERSION
        columns = {r[1] for r in migrated.conn.execute("PRAGMA table_info(workout_sessions)")}
        assert "edited_at" in columns
        tables = {row[0] for row in migrated.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "performed_date_corrections" in tables
        # Legacy rows have no edit; the capture/upload timestamps stay intact.
        row = migrated.conn.execute(
            "SELECT uploaded_at, edited_at FROM workout_sessions WHERE id = 'legacy'"
        ).fetchone()
        assert row["uploaded_at"] == "2026-01-01T10:05:00+00:00"
        assert row["edited_at"] is None
        # A correction records previous/corrected dates and cascades with its session.
        migrated.ledger.update_session_performed_date("legacy", "2026-01-02", "2026-01-02T09:00:00+00:00")
        migrated.ledger.record_performed_date_correction(
            "legacy", "2026-01-01", "2026-01-02", "2026-01-02T09:00:00+00:00"
        )
        corrections = migrated.ledger.list_performed_date_corrections("legacy")
        assert [(c["previous_date"], c["corrected_date"]) for c in corrections] == [
            ("2026-01-01", "2026-01-02")
        ]
        migrated.conn.execute("DELETE FROM workout_sessions WHERE id = 'legacy'")
        migrated.conn.commit()
        assert migrated.ledger.list_performed_date_corrections("legacy") == []
        # Re-initialising the schema is idempotent.
        migrated.create_ledger_schema()
        assert "performed_date_corrections" in {
            row[0] for row in migrated.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        if migrated.ledger_conn is not None:
            migrated.ledger_conn.close()
        migrated.catalog_conn.close()


def test_v11_to_v12_adds_structured_intake_tables(temp_db_env):
    from database.migration_manager import CURRENT_LEDGER_SCHEMA_VERSION, get_ledger_schema_version

    db, ledgers_dir, _ = temp_db_env
    legacy_path = ledgers_dir / "v11lifter.db"
    conn = sqlite3.connect(legacy_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE user_profile (id INTEGER PRIMARY KEY, gender TEXT, updated_at TEXT NOT NULL);
        INSERT INTO user_profile VALUES (1, 'male', '2026-01-01T00:00:00+00:00');
    """
    )
    conn.execute("PRAGMA user_version = 11")
    conn.commit()
    conn.close()

    migrated = DatabaseManager(
        catalog_path=db.catalog_path, ledgers_dir=ledgers_dir, backups_dir=db.backups_dir, default_ledger_id="v11lifter"
    )
    try:
        assert get_ledger_schema_version(migrated.conn) == CURRENT_LEDGER_SCHEMA_VERSION
        tables = {row[0] for row in migrated.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {"intake_answers", "intake_state"} <= tables
        # The new ledger helpers round-trip through the migrated tables.
        migrated.ledger.save_intake_answer("gender", "female", prefilled=True)
        answers = migrated.ledger.load_intake_answers()
        assert answers["gender"]["value"] == "female"
        assert answers["gender"]["prefilled"] is True
        migrated.ledger.save_intake_state(disclosure_acknowledged=1)
        assert migrated.ledger.get_intake_state()["disclosure_acknowledged"] is True
        # Re-initialising the schema is idempotent.
        migrated.create_ledger_schema()
        assert "intake_answers" in {
            row[0] for row in migrated.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        if migrated.ledger_conn is not None:
            migrated.ledger_conn.close()
        migrated.catalog_conn.close()


def test_v12_to_v13_adds_session_warmup_sets(temp_db_env):
    from database.migration_manager import CURRENT_LEDGER_SCHEMA_VERSION, get_ledger_schema_version

    db, ledgers_dir, _ = temp_db_env
    legacy_path = ledgers_dir / "v12lifter.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript(
        """
        CREATE TABLE user_profile (id INTEGER PRIMARY KEY, gender TEXT, updated_at TEXT NOT NULL);
        INSERT INTO user_profile VALUES (1, 'male', '2026-01-01T00:00:00+00:00');
        CREATE TABLE workout_sessions (
            id TEXT PRIMARY KEY, session_date TEXT NOT NULL, split_name TEXT NOT NULL,
            started_at TEXT NOT NULL, client_session_id TEXT
        );
        INSERT INTO workout_sessions VALUES (
            'session-1', '2026-01-01', 'Upper', '2026-01-01T10:00:00+00:00', NULL
        );
        """
    )
    conn.execute("PRAGMA user_version = 12")
    conn.commit()
    conn.close()

    migrated = DatabaseManager(
        catalog_path=db.catalog_path,
        ledgers_dir=ledgers_dir,
        backups_dir=db.backups_dir,
        default_ledger_id="v12lifter",
    )
    try:
        assert get_ledger_schema_version(migrated.conn) == CURRENT_LEDGER_SCHEMA_VERSION
        migrated.ledger.log_session_warmup_movements(
            "session-1",
            [
                {
                    "exercise_id": None,
                    "exercise_name": "Cat-Cow",
                    "sets": [{"weight_kg": None, "reps": 10}],
                }
            ],
            "2026-01-02T00:00:00+00:00",
        )
        assert migrated.ledger.list_session_warmup_movements("session-1") == [
            {
                "exercise_id": None,
                "exercise_name": "Cat-Cow",
                "sets": [{"weight_kg": None, "reps": 10}],
            }
        ]
        migrated.conn.execute("DELETE FROM workout_sessions WHERE id = 'session-1'")
        migrated.conn.commit()
        assert migrated.ledger.list_session_warmup_movements("session-1") == []
    finally:
        if migrated.ledger_conn is not None:
            migrated.ledger_conn.close()
        migrated.catalog_conn.close()


def test_onboarding_state_roundtrip_and_clear(temp_db_env):
    db, _, _ = temp_db_env
    assert db.ledger.load_onboarding_state() is None
    db.ledger.save_onboarding_state({"intake_step": 2, "is_complete": False, "profile_data": {"age": 30}, "messages": [{"role": "assistant", "content": "Q?"}]})
    loaded = db.ledger.load_onboarding_state()
    assert loaded == {"intake_step": 2, "is_complete": False, "profile_data": {"age": 30}, "messages": [{"role": "assistant", "content": "Q?"}]}
    db.ledger.save_onboarding_state({"intake_step": 3, "is_complete": True, "profile_data": None, "messages": []})
    assert db.ledger.load_onboarding_state()["intake_step"] == 3
    db.ledger.clear_onboarding_state()
    assert db.ledger.load_onboarding_state() is None
