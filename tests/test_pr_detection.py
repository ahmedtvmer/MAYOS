"""Deterministic personal record detection: comparison rules, session reduction, debrief lines."""

import sqlite3
from types import SimpleNamespace

import pytest

from agent.debrief import generate_session_debrief
from agent.progression_engine import calculate_e1rm, check_and_record_pr, evaluate_session_prs


@pytest.fixture
def pr_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        ATTACH DATABASE ':memory:' AS catalog;
        CREATE TABLE catalog.exercises (id TEXT PRIMARY KEY, name TEXT);
        INSERT INTO catalog.exercises VALUES ('squat', 'Barbell Squat');
        CREATE TABLE workout_sessions (id TEXT PRIMARY KEY);
        INSERT INTO workout_sessions VALUES ('s1'), ('s2'), ('s3');
        CREATE TABLE personal_records (
            id TEXT PRIMARY KEY,
            exercise_id TEXT NOT NULL,
            record_type TEXT NOT NULL CHECK (record_type IN ('max_weight', 'max_e1rm')),
            reps INTEGER,
            value REAL NOT NULL,
            prev_value REAL,
            achieved_at TEXT NOT NULL,
            session_id TEXT,
            FOREIGN KEY(session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE
        );
    """)
    database = SimpleNamespace(conn=conn, user_conn=conn)
    try:
        yield database, conn
    finally:
        conn.close()


def _counts(conn):
    rows = conn.execute(
        "SELECT record_type || ':' || COALESCE(reps, 0) AS key, COUNT(*) AS n FROM personal_records GROUP BY 1"
    ).fetchall()
    return {row["key"]: row["n"] for row in rows}


def test_baseline_then_tie_then_strict_beat(pr_db):
    db, _ = pr_db
    base_e1rm = calculate_e1rm(100.0, 5, 8.5)

    first = check_and_record_pr(db, "squat", 100.0, 5, base_e1rm, session_id="s1", achieved_at="2026-01-01T00:00:00+00:00")
    assert {event["record_type"] for event in first} == {"max_weight", "max_e1rm"}
    assert all(event["prev_value"] is None for event in first)

    tie = check_and_record_pr(db, "squat", 100.0, 5, base_e1rm, session_id="s2", achieved_at="2026-01-02T00:00:00+00:00")
    assert tie == []

    beat_e1rm = calculate_e1rm(102.5, 5, 8.5)
    beat = check_and_record_pr(
        db, "squat", 102.5, 5, beat_e1rm, session_id="s3", achieved_at="2026-01-03T00:00:00+00:00"
    )
    assert {event["record_type"] for event in beat} == {"max_weight", "max_e1rm"}
    weight_event = next(event for event in beat if event["record_type"] == "max_weight")
    assert weight_event["value"] == 102.5
    assert weight_event["prev_value"] == 100.0


def test_weight_records_are_scoped_to_exact_rep_count(pr_db):
    db, conn = pr_db
    check_and_record_pr(db, "squat", 80.0, 10, calculate_e1rm(80.0, 10, 8.5), session_id="s1")

    events = check_and_record_pr(db, "squat", 85.0, 8, calculate_e1rm(85.0, 8, 8.5), session_id="s2")
    weight_event = next(event for event in events if event["record_type"] == "max_weight")
    assert weight_event["reps"] == 8

    # A lighter set at a different rep count is not compared against the 10-rep record.
    lighter = check_and_record_pr(db, "squat", 70.0, 12, calculate_e1rm(70.0, 12, 8.5), session_id="s3")
    assert all(event["record_type"] == "max_weight" for event in lighter)
    assert _counts(conn) == {
        "max_weight:10": 1,
        "max_weight:8": 1,
        "max_weight:12": 1,
        "max_e1rm:10": 1,
        "max_e1rm:8": 1,
    }


def test_evaluate_session_records_one_row_per_type(pr_db):
    db, conn = pr_db
    sets = [
        {"weight_kg": 100.0, "reps": 5, "rpe": 8.0},
        {"weight_kg": 102.5, "reps": 5, "rpe": 8.0},
        {"weight_kg": 90.0, "reps": 12, "rpe": 8.0},
    ]
    events = evaluate_session_prs(db, "s1", "squat", sets, exercise_name="Barbell Squat")

    # Heaviest set per rep count + the best-e1RM set (90x12), never the transient 100x5.
    assert _counts(conn) == {"max_weight:5": 1, "max_weight:12": 1, "max_e1rm:12": 1}
    assert all(event["name"] == "Barbell Squat" for event in events)
    assert conn.execute("SELECT value FROM personal_records WHERE record_type='max_weight' AND reps=5").fetchone()[0] == 102.5


def test_second_session_populates_prev_value(pr_db):
    db, _ = pr_db
    evaluate_session_prs(db, "s1", "squat", [{"weight_kg": 100.0, "reps": 5, "rpe": 8.5}])

    events = evaluate_session_prs(
        db, "s2", "squat", [{"weight_kg": 105.0, "reps": 5, "rpe": 8.5}], achieved_at="2026-02-01T00:00:00+00:00"
    )
    weight_event = next(event for event in events if event["record_type"] == "max_weight")
    assert weight_event["value"] == 105.0
    assert weight_event["prev_value"] == 100.0
    assert weight_event["achieved_at"] == "2026-02-01T00:00:00+00:00"


def test_warmup_and_invalid_sets_ignored(pr_db):
    db, conn = pr_db
    events = evaluate_session_prs(
        db,
        "s1",
        "squat",
        [
            {"weight_kg": 60.0, "reps": 5, "rpe": 8.0, "is_warmup": True},
            {"weight_kg": 0.0, "reps": 5, "rpe": 8.0},
            {"weight_kg": 100.0, "reps": 0, "rpe": 8.0},
        ],
    )
    assert events == []
    assert conn.execute("SELECT COUNT(*) FROM personal_records").fetchone()[0] == 0


def test_debrief_injects_deterministic_pr_lines():
    summaries = [{"name": "Bench Press", "volume_load": 2500.0, "current_e1rm": 126.4, "e1rm_delta": 2.5}]
    pr_events = [
        {
            "exercise_id": "bp",
            "name": "Bench Press",
            "record_type": "max_weight",
            "reps": 5,
            "value": 102.5,
            "prev_value": 100.0,
            "achieved_at": "2026-01-01T00:00:00+00:00",
            "session_id": "s1",
        },
        {
            "exercise_id": "bp",
            "name": "Bench Press",
            "record_type": "max_e1rm",
            "reps": 5,
            "value": 126.4,
            "prev_value": None,
            "achieved_at": "2026-01-01T00:00:00+00:00",
            "session_id": "s1",
        },
    ]
    output = generate_session_debrief(
        "Upper", 4, "", summaries, total_tonnage=2500.0, pr_events=pr_events
    )
    assert "🏆 New PR: Bench Press — 102.5 kg × 5 (prev 100 kg) | e1RM 126.4 kg (first record)" in output
    assert "**Overload Deltas**" in output
    assert "**Fatigue & CNS Check**" in output
    assert "**Next Session Directives**" in output


def test_debrief_without_pr_events_unchanged():
    summaries = [{"name": "Bench Press", "volume_load": 2500.0, "current_e1rm": 126.4, "e1rm_delta": 2.5}]
    output = generate_session_debrief("Upper", 4, "", summaries, total_tonnage=2500.0)
    assert "🏆" not in output
