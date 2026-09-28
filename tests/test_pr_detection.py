"""Deterministic personal records: exercise-wide aggregates, baselines, history rows, debrief lines."""

import sqlite3

import pytest

from agent.debrief import generate_session_debrief
from agent.progression_engine import calculate_e1rm, evaluate_session_prs
from database.ledger.handle import TrainingLedger


@pytest.fixture
def pr_db(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        ATTACH DATABASE ':memory:' AS catalog;
        CREATE TABLE catalog.exercises (id TEXT PRIMARY KEY, name TEXT);
        INSERT INTO catalog.exercises VALUES ('squat', 'Barbell Squat');
        CREATE TABLE workout_sessions (
            id TEXT PRIMARY KEY,
            session_date TEXT,
            started_at TEXT
        );
        INSERT INTO workout_sessions (id, session_date, started_at)
            VALUES ('s1', '2026-01-01', '2026-01-01T10:00:00+00:00'),
                   ('s2', '2026-01-02', '2026-01-02T10:00:00+00:00'),
                   ('s3', '2026-01-03', '2026-01-03T10:00:00+00:00'),
                   ('s4', '2026-01-04', '2026-01-04T10:00:00+00:00');
        CREATE TABLE workout_sets (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            exercise_id TEXT NOT NULL,
            set_index INTEGER NOT NULL,
            weight_kg REAL NOT NULL,
            reps INTEGER NOT NULL,
            rpe REAL,
            is_warmup INTEGER DEFAULT 0,
            logged_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES workout_sessions(id) ON DELETE CASCADE
        );
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
    database = TrainingLedger(conn=conn, ledger_id="pr-test", backups_dir=tmp_path)
    try:
        yield database, conn
    finally:
        conn.close()


def _evaluate(db, session_id, sets, exercise_id="squat", **kwargs):
    """Commits one session's sets (as a real commit does), then evaluates its records."""
    conn = db.conn
    conn.execute(
        "INSERT OR IGNORE INTO workout_sessions (id, session_date, started_at) VALUES (?, ?, ?)",
        (session_id, f"2026-02-{len(session_id):02d}", f"2026-02-{len(session_id):02d}T10:00:00+00:00"),
    )
    for index, spec in enumerate(sets, start=1):
        conn.execute(
            """
            INSERT INTO workout_sets (
                id, session_id, exercise_id, set_index, weight_kg, reps, rpe, is_warmup, logged_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{session_id}-{exercise_id}-{index}",
                session_id,
                exercise_id,
                index,
                float(spec["weight_kg"]),
                int(spec["reps"]),
                spec.get("rpe"),
                1 if spec.get("is_warmup") else 0,
                f"{session_id}T00:00:00+00:00",
            ),
        )
    conn.commit()
    return evaluate_session_prs(db, session_id, exercise_id, sets, **kwargs)


def _counts(conn):
    rows = conn.execute(
        "SELECT record_type || ':' || COALESCE(reps, 0) AS key, COUNT(*) AS n FROM personal_records GROUP BY 1"
    ).fetchall()
    return {row["key"]: row["n"] for row in rows}


def _event(events, record_type):
    matched = [event for event in events if event["record_type"] == record_type]
    assert len(matched) <= 1, f"at most one {record_type} event per exercise: {events}"
    return matched[0] if matched else None


def test_first_session_is_baseline_not_a_record(pr_db):
    db, conn = pr_db
    events = _evaluate(db, "s1", [{"weight_kg": 100.0, "reps": 5, "rpe": 8.5}])

    assert events == []
    assert conn.execute("SELECT COUNT(*) FROM personal_records").fetchone()[0] == 0


def test_heaviest_weight_beaten_then_tied(pr_db):
    db, conn = pr_db
    _evaluate(db, "s1", [{"weight_kg": 100.0, "reps": 5, "rpe": 8.5}])

    tied = _evaluate(db, "s2", [{"weight_kg": 100.0, "reps": 5, "rpe": 8.5}])
    assert tied == []

    beat = _evaluate(db, "s3", [{"weight_kg": 102.5, "reps": 5, "rpe": 8.5}])
    weight_event = _event(beat, "max_weight")
    assert weight_event["value"] == 102.5
    assert weight_event["prev_value"] == 100.0
    e1rm_event = _event(beat, "max_e1rm")
    assert e1rm_event["value"] == round(calculate_e1rm(102.5, 5, 8.5), 2)
    assert e1rm_event["prev_value"] == round(calculate_e1rm(100.0, 5, 8.5), 2)


def test_heaviest_weight_is_exercise_wide_across_rep_counts(pr_db):
    db, conn = pr_db
    _evaluate(db, "s1", [{"weight_kg": 100.0, "reps": 5, "rpe": 8.5}])

    # Heavier at a different rep count than the previous best: still a record.
    events = _evaluate(db, "s2", [{"weight_kg": 105.0, "reps": 3, "rpe": 8.5}])
    weight_event = _event(events, "max_weight")
    assert weight_event["value"] == 105.0
    assert weight_event["prev_value"] == 100.0
    assert weight_event["reps"] == 3

    # Lighter at a new rep count: never a heaviest-weight record, though the
    # ADR 009 per-rep-count history row is still stored.
    lighter = _evaluate(db, "s3", [{"weight_kg": 90.0, "reps": 12, "rpe": 8.5}])
    assert _event(lighter, "max_weight") is None
    assert _counts(conn)["max_weight:12"] == 1
    assert all(event["record_type"] != "max_weight" for event in lighter)


def test_best_e1rm_with_mixed_rated_and_unrated_sets(pr_db):
    db, _ = pr_db
    _evaluate(db, "s1", [{"weight_kg": 100.0, "reps": 5, "rpe": 8.5}])

    events = _evaluate(
        db,
        "s2",
        [
            {"weight_kg": 90.0, "reps": 8, "rpe": 9.0},
            {"weight_kg": 100.0, "reps": 6, "rpe": None},
        ],
    )
    e1rm_event = _event(events, "max_e1rm")
    # The unrated set scores with the current formula's default effort (RPE 8.5).
    assert e1rm_event["value"] == 125.0
    assert e1rm_event["prev_value"] == round(calculate_e1rm(100.0, 5, 8.5), 2)
    assert e1rm_event["reps"] == 6
    # The heaviest weight ties at 100 kg, so only the e1RM record is announced.
    assert _event(events, "max_weight") is None
    assert len(events) == 1


def test_warmup_sets_are_ignored(pr_db):
    db, conn = pr_db
    baseline = _evaluate(
        db,
        "s1",
        [
            {"weight_kg": 90.0, "reps": 5, "rpe": 7.0, "is_warmup": True},
            {"weight_kg": 100.0, "reps": 5, "rpe": 8.5},
        ],
    )
    assert baseline == []
    assert conn.execute("SELECT COUNT(*) FROM personal_records").fetchone()[0] == 0

    # A warm-up heavier than every previous working set must not produce a record.
    events = _evaluate(
        db,
        "s2",
        [
            {"weight_kg": 150.0, "reps": 5, "rpe": 7.0, "is_warmup": True},
            {"weight_kg": 100.0, "reps": 5, "rpe": 8.5},
        ],
    )
    # The working sets only tie the baseline: no event, and a tie stores no
    # history row either (rows are compared against the same aggregate).
    assert events == []
    assert conn.execute("SELECT COUNT(*) FROM personal_records").fetchone()[0] == 0

    # A later working set beats the baseline; the warm-up never can.
    beaten = _evaluate(
        db,
        "s3",
        [
            {"weight_kg": 150.0, "reps": 5, "rpe": 7.0, "is_warmup": True},
            {"weight_kg": 105.0, "reps": 5, "rpe": 8.5},
        ],
    )
    assert _event(beaten, "max_weight")["value"] == 105.0
    assert _event(beaten, "max_weight")["prev_value"] == 100.0
    assert _counts(conn) == {"max_weight:5": 1, "max_e1rm:5": 1}
    stored = conn.execute(
        "SELECT value FROM personal_records WHERE record_type = 'max_weight'"
    ).fetchall()
    assert [row["value"] for row in stored] == [105.0]


def test_lighter_second_session_adds_no_history_row(pr_db):
    """A later, lighter session must never store a lower "best" (#122 review).

    The first session stores no row, so a history row compared against the
    empty ``personal_records`` table would record the lighter value with a
    NULL ``prev_value`` and read as a best in the history views.
    """
    db, conn = pr_db
    _evaluate(db, "s1", [{"weight_kg": 100.0, "reps": 5, "rpe": 8.5}])
    lighter = _evaluate(db, "s2", [{"weight_kg": 90.0, "reps": 5, "rpe": 8.5}])
    assert lighter == []
    assert conn.execute("SELECT COUNT(*) FROM personal_records").fetchone()[0] == 0

    # The session that does beat the baseline compares against the aggregate:
    # ``prev_value`` is the first session's best, not the empty table.
    beat = _evaluate(db, "s3", [{"weight_kg": 105.0, "reps": 5, "rpe": 8.5}])
    weight_row = conn.execute(
        "SELECT value, prev_value FROM personal_records WHERE record_type = 'max_weight'"
    ).fetchone()
    assert (weight_row["value"], weight_row["prev_value"]) == (105.0, 100.0)
    e1rm_row = conn.execute(
        "SELECT value, prev_value FROM personal_records WHERE record_type = 'max_e1rm'"
    ).fetchone()
    assert e1rm_row["value"] == round(calculate_e1rm(105.0, 5, 8.5), 2)
    assert e1rm_row["prev_value"] == round(calculate_e1rm(100.0, 5, 8.5), 2)
    assert _event(beat, "max_weight")["prev_value"] == 100.0


def test_exercise_logged_only_with_zero_load_sets_is_still_a_baseline(pr_db):
    """A 0 kg set is not a working set under the one shared definition (#122)."""
    db, conn = pr_db
    assert _evaluate(db, "s1", [{"weight_kg": 0.0, "reps": 8, "rpe": 8.0}]) == []

    # The first session with a real load is still the exercise's baseline.
    second = _evaluate(db, "s2", [{"weight_kg": 60.0, "reps": 8, "rpe": 8.0}])
    assert second == []
    assert conn.execute("SELECT COUNT(*) FROM personal_records").fetchone()[0] == 0

    third = _evaluate(db, "s3", [{"weight_kg": 65.0, "reps": 8, "rpe": 8.0}])
    weight_event = _event(third, "max_weight")
    assert (weight_event["value"], weight_event["prev_value"]) == (65.0, 60.0)


def test_one_event_per_exercise_per_record_type(pr_db):
    db, conn = pr_db
    _evaluate(db, "s1", [{"weight_kg": 100.0, "reps": 5, "rpe": 8.5}])

    events = _evaluate(
        db,
        "s2",
        [
            {"weight_kg": 105.0, "reps": 5, "rpe": 8.5},
            {"weight_kg": 110.0, "reps": 3, "rpe": 9.0},
            {"weight_kg": 100.0, "reps": 12, "rpe": 8.5},
        ],
        exercise_name="Barbell Squat",
    )

    assert len(events) == 2
    assert {event["record_type"] for event in events} == {"max_weight", "max_e1rm"}
    assert all(event["exercise_id"] == "squat" for event in events)
    assert all(event["name"] == "Barbell Squat" for event in events)
    weight_event = _event(events, "max_weight")
    assert (weight_event["value"], weight_event["reps"], weight_event["prev_value"]) == (110.0, 3, 100.0)
    e1rm_event = _event(events, "max_e1rm")
    assert e1rm_event["value"] == round(calculate_e1rm(100.0, 12, 8.5), 2)

    # ADR 009 history rows keep one row per rep count, outside ``new_prs``.
    assert _counts(conn) == {
        "max_weight:5": 1,
        "max_weight:3": 1,
        "max_weight:12": 1,
        "max_e1rm:12": 1,
    }


def test_second_session_populates_prev_value(pr_db):
    db, _ = pr_db
    _evaluate(db, "s1", [{"weight_kg": 100.0, "reps": 5, "rpe": 8.5}])

    events = _evaluate(
        db,
        "s2",
        [{"weight_kg": 105.0, "reps": 5, "rpe": 8.5}],
        achieved_at="2026-02-01T00:00:00+00:00",
    )
    weight_event = _event(events, "max_weight")
    assert weight_event["value"] == 105.0
    assert weight_event["prev_value"] == 100.0
    assert weight_event["achieved_at"] == "2026-02-01T00:00:00+00:00"


def test_history_rows_stay_scoped_to_exact_rep_count(pr_db):
    db, conn = pr_db
    _evaluate(db, "s1", [{"weight_kg": 80.0, "reps": 10, "rpe": 8.5}])
    _evaluate(db, "s2", [{"weight_kg": 85.0, "reps": 8, "rpe": 8.5}])
    events = _evaluate(db, "s3", [{"weight_kg": 70.0, "reps": 12, "rpe": 8.5}])

    # The new session announces only exercise-wide records: 70 kg beats neither
    # the previous best weight nor the previous best e1RM, so nothing is said,
    # while the per-rep-count history row is still stored.
    assert events == []
    assert _counts(conn) == {
        "max_weight:8": 1,
        "max_weight:12": 1,
        "max_e1rm:8": 1,
    }
    stored = conn.execute(
        "SELECT value FROM personal_records WHERE record_type = 'max_weight' AND reps = 12"
    ).fetchone()
    assert stored[0] == 70.0


def test_invalid_sets_ignored(pr_db):
    db, conn = pr_db
    events = _evaluate(
        db,
        "s1",
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
            "prev_value": 100.0,
            "achieved_at": "2026-01-01T00:00:00+00:00",
            "session_id": "s1",
        },
    ]
    output = generate_session_debrief(
        "Upper", 4, "", summaries, total_tonnage=2500.0, pr_events=pr_events
    )
    # The heaviest-weight line is exercise-wide: it may mention the reps the
    # weight was lifted for, but it never reads as a "× reps" record.
    assert "🏆 New PR: Bench Press — heaviest 102.5 kg for 5 reps (prev 100 kg) | e1RM 126.4 kg (prev 100 kg)" in output
    assert "kg × " not in output
    assert "**Overload Deltas**" in output
    assert "**Fatigue & CNS Check**" in output
    assert "**Next Session Directives**" in output


def test_debrief_without_pr_events_unchanged():
    summaries = [{"name": "Bench Press", "volume_load": 2500.0, "current_e1rm": 126.4, "e1rm_delta": 2.5}]
    output = generate_session_debrief("Upper", 4, "", summaries, total_tonnage=2500.0)
    assert "🏆" not in output
