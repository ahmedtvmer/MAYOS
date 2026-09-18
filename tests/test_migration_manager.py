# tests/test_migration_manager.py
import sqlite3
import threading
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
def temp_db_env(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(DatabaseManager, "_instance", None)
    monkeypatch.setattr(DatabaseManager, "_local", threading.local())
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
    try:
        assert db.catalog_path == catalog_path
        assert db.users_dir == users_dir
        assert db.backups_dir == backups_dir
        yield db, users_dir, backups_dir
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


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


def test_assistant_memory_persistence_and_user_separation(temp_db_env):
    db, users_dir, _ = temp_db_env
    db.upsert_user_profile({})
    profile = db.get_user_profile()
    assert db.get_assistant_memory() == {}
    db.set_assistant_memory("preferred_name", "Alice")
    db.set_assistant_memory("preferred_name", "O'Connor")
    assert db.get_assistant_memory() == {"preferred_name": "O'Connor"}
    assert db.active_user == "alice"
    assert db.get_user_profile() == profile
    assert sorted(path.name for path in users_dir.glob("*.db")) == ["alice.db"]
    db.clear_chat_history()
    db.create_user_schema()
    assert db.get_assistant_memory() == {"preferred_name": "O'Connor"}
    db.switch_user("bob")
    assert db.get_assistant_memory() == {}
    db.set_assistant_memory("preferred_name", "Bob")
    db.switch_user("alice")
    assert db.get_assistant_memory() == {"preferred_name": "O'Connor"}
    db.switch_user("bob")
    assert db.get_assistant_memory() == {"preferred_name": "Bob"}


@pytest.mark.parametrize("key", ["name", "username", "custom_instructions", "", "preferred_name'; --"])
def test_assistant_memory_rejects_unsupported_keys(temp_db_env, key):
    db, _, _ = temp_db_env
    with pytest.raises(ValueError, match="Unsupported"):
        db.set_assistant_memory(key, "Alice")
    assert db.get_assistant_memory() == {}


@pytest.mark.parametrize("value", [None, 12, True, {}, [], "", "   ", "A" * 61, "Alice\nBob", "A\x00B"])
def test_assistant_memory_rejects_invalid_values(temp_db_env, value):
    db, _, _ = temp_db_env
    db.set_assistant_memory("preferred_name", "Alice")
    with pytest.raises(ValueError, match="Preferred name"):
        db.set_assistant_memory("preferred_name", value)
    assert db.get_assistant_memory() == {"preferred_name": "Alice"}


@pytest.mark.parametrize("value", ["A", "A" * 60, "Élodie", "Anne-Marie", "O'Connor"])
def test_assistant_memory_accepts_bounded_names(temp_db_env, value):
    db, _, _ = temp_db_env
    db.set_assistant_memory("preferred_name", value)
    assert db.get_assistant_memory() == {"preferred_name": value}


@pytest.mark.parametrize("version", [0, CURRENT_USER_SCHEMA_VERSION])
def test_existing_ledger_gets_assistant_memory_idempotently(temp_db_env, version):
    db, _, _ = temp_db_env
    db.upsert_user_profile({})
    profile = db.get_user_profile()
    db.add_chat_message("user", "Preserve history")
    db.log_workout_session("old", "2026-09-16", "Upper", "2026-09-16T10:00:00", None)
    db.log_workout_set("old-set", "old", "missing", 1, 10.0, 8, 8.0)
    db.conn.execute("DROP TABLE assistant_memory")
    set_user_schema_version(db.conn, version)
    db.conn.commit()
    db.switch_user("bob")
    db.switch_user("alice")
    assert db.get_assistant_memory() == {}
    db.set_assistant_memory("preferred_name", "Alice")
    db.create_user_schema()
    db.create_user_schema()
    assert db.get_assistant_memory() == {"preferred_name": "Alice"}
    assert db.get_user_profile() == profile
    assert db.get_chat_history()[0]["content"] == "Preserve history"
    assert db.get_latest_session_summary()["sets_count"] == 1
    assert get_user_schema_version(db.conn) == CURRENT_USER_SCHEMA_VERSION


def test_latest_session_summary_uses_real_working_sets(temp_db_env):
    db, _, _ = temp_db_env
    db.catalog_conn.executemany(
        "INSERT INTO exercises (id, name) VALUES (?, ?)",
        [("bench", "Bench press"), ("row", "Row"), ("warmup", "Warmup only")],
    )
    db.catalog_conn.commit()
    db.log_workout_session("old", "2026-09-15", "Old", "2026-09-15T12:00:00", None)
    db.log_workout_set("old-set", "old", "bench", 1, 200, 20, 8)
    db.log_workout_session("latest'; --", "2026-09-16", "Upper", "2026-09-16T12:00:00", None, 3)
    for set_id, exercise_id, index, weight, reps, warmup in [
        ("b1", "bench", 1, 100, 8, 0),
        ("b2", "bench", 2, 90, 10, 0),
        ("r1", "row", 1, 50, 12, 0),
        ("bw", "bench", 0, 20, 15, 1),
        ("w1", "warmup", 1, 30, 10, 1),
        ("m1", "missing", 1, 0, 10, 0),
    ]:
        db.log_workout_set(set_id, "latest'; --", exercise_id, index, weight, reps, 8, warmup)
    expected = {
        "session_date": "2026-09-16",
        "split_name": "Upper",
        "readiness_score": 3,
        "sets_count": 4,
        "total_volume_kg": 2300.0,
        "exercises": [
            {"name": "Bench press", "sets": 2, "reps": 18, "volume_kg": 1700.0},
            {"name": "missing", "sets": 1, "reps": 10, "volume_kg": 0.0},
            {"name": "Row", "sets": 1, "reps": 12, "volume_kg": 600.0},
        ],
    }
    assert db.get_latest_session_summary() == expected
    db.switch_user("bob")
    assert db.get_latest_session_summary() is None
    db.log_workout_session("bob", "2026-09-17", "Lower", "2026-09-17T12:00:00", None)
    assert db.get_latest_session_summary()["split_name"] == "Lower"
    db.switch_user("alice")
    assert db.get_latest_session_summary() == expected


def test_latest_session_summary_empty_and_warmup_only(temp_db_env):
    db, _, _ = temp_db_env
    assert db.get_latest_session_summary() is None
    db.log_workout_session("old", "2026-09-15", "Old", "2026-09-15T12:00:00", None)
    db.log_workout_set("old-set", "old", "bench", 1, 100, 8, 8)
    db.log_workout_session("empty", "2026-09-16", "Empty", "2026-09-16T12:00:00", None, None)
    expected = {
        "session_date": "2026-09-16",
        "split_name": "Empty",
        "readiness_score": None,
        "sets_count": 0,
        "total_volume_kg": 0.0,
        "exercises": [],
    }
    assert db.get_latest_session_summary() == expected
    db.log_workout_set("warmup", "empty", "bench", 1, 20, 10, 5, 1)
    assert db.get_latest_session_summary() == expected


def test_latest_session_summary_deterministic_ordering(temp_db_env):
    db, _, _ = temp_db_env
    for session_id, date, started_at in [
        ("latest-date", "2026-09-16", "2026-09-16T08:00:00"),
        ("backdated", "2026-09-15", "2026-09-17T12:00:00"),
    ]:
        db.log_workout_session(session_id, date, session_id, started_at, None)
    assert db.get_latest_session_summary()["split_name"] == "latest-date"
    db.log_workout_session("later-start", "2026-09-16", "Later start", "2026-09-16T10:00:00", None)
    db.log_workout_session("early-start", "2026-09-16", "Early start", "2026-09-16T07:00:00", None)
    assert db.get_latest_session_summary()["split_name"] == "Later start"
    db.log_workout_session("tie", "2026-09-16", "Tie", "2026-09-16T10:00:00", None)
    assert db.get_latest_session_summary()["split_name"] == "Tie"
    assert db.get_latest_session_summary()["split_name"] == "Tie"


def test_session_comparison_empty_and_user_isolation(temp_db_env):
    db, _, _ = temp_db_env
    assert db.get_session_comparison_context() is None
    db.log_workout_session("empty", "2026-09-16", "Upper", "2026-09-16T08:00:00", None, None, "Rested")
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
    assert db.get_session_comparison_context() == expected
    db.log_workout_set("warmup", "empty", "bench", 0, 20, 10, 5, 1)
    assert db.get_session_comparison_context() == expected
    db.switch_user("bob")
    assert db.get_session_comparison_context() is None
    db.switch_user("alice")
    assert db.get_session_comparison_context() == expected


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
        db.log_workout_session(session_id, date, session_id, start, None, 3, session_id + " notes")
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
        db.log_workout_set(set_id, session_id, exercise_id, index, weight, reps, rpe, warmup)
    summary = db.get_latest_session_summary()
    queries = []
    db.conn.set_trace_callback(queries.append)
    try:
        context = db.get_session_comparison_context()
    finally:
        db.conn.set_trace_callback(None)
    assert db.get_latest_session_summary() == summary
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
        db.log_workout_session(session_id, "2026-09-16", "Upper", "2026-09-16T" + start, None)
        db.log_workout_set(session_id, session_id, "bench", 1, 100, 8, 8)
    context = db.get_session_comparison_context()
    assert context["session"]["id"] == "tie"
    assert context["previous_session"]["id"] == "first"
    assert context["exercises"][0]["previous"]["session"]["id"] == "first"
    assert db.get_session_comparison_context() == context


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
        ((100, 8, None), (110, 9, 8), "insufficient_data"),
        ((100, 8, 8), (110, 9, None), "insufficient_data"),
        ((100, 8, None), (110, 9, None), "insufficient_data"),
        ((0, 8, 8), (0, 9, 8), "improvement"),
        ((0, 8, None), (0, 9, None), "insufficient_data"),
    ],
)
def test_session_comparison_strength_requires_best_set_rpe(temp_db_env, previous, current, status):
    db, _, _ = temp_db_env
    for session_id, date, values in [("previous", "2026-09-15", previous), ("current", "2026-09-16", current)]:
        db.log_workout_session(session_id, date, "Upper", date + "T10:00:00", None)
        db.log_workout_set(session_id, session_id, "bench", 1, *values)
        db.log_workout_set(session_id + "-backoff", session_id, "bench", 2, 0, 1, 8)
    exercise = db.get_session_comparison_context()["exercises"][0]
    assert exercise["status"] == status
    assert exercise["deltas"]["load_kg"] == current[0] - previous[0]
    assert exercise["deltas"]["reps"] == current[1] - previous[1]
    assert exercise["deltas"]["volume_kg"] == current[0] * current[1] - previous[0] * previous[1]
    for key, values in [("previous", previous), ("current", current)]:
        if values[2] is None or values[0] <= 0:
            assert exercise[key]["e1rm"] is None
    if exercise["previous"]["e1rm"] is None or exercise["current"]["e1rm"] is None:
        assert exercise["deltas"]["e1rm"] is None


@pytest.mark.parametrize("extra_session", ["previous", "current"])
def test_session_comparison_volume_and_sets_do_not_decide_strength(temp_db_env, extra_session):
    db, _, _ = temp_db_env
    for session_id, date in [("previous", "2026-09-15"), ("current", "2026-09-16")]:
        db.log_workout_session(session_id, date, "Upper", date + "T10:00:00", None)
        db.log_workout_set(session_id, session_id, "bench", 1, 100, 8, 8)
    db.log_workout_set("extra", extra_session, "bench", 2, 80, 10, 8)
    exercise = db.get_session_comparison_context()["exercises"][0]
    sign = 1 if extra_session == "current" else -1
    assert exercise["deltas"] == {"load_kg": 0, "reps": 0, "sets": sign, "volume_kg": sign * 800, "e1rm": 0}
    assert exercise["status"] == "unchanged"
