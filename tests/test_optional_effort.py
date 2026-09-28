"""Optional effort: RPE stays internal, RIR at the boundary, blank never defaulted (#111).

Covers the input schema, the RIR conversion, plain-Epley scoring of unrated
sets, and a session mixing rated and unrated sets through commit, progression,
deload detection and the progression alerts.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent.progression_engine import calculate_e1rm, evaluate_systemic_fatigue, project_next_load, set_e1rm
from database.database_manager import DatabaseManager
from service import progression_alerts as progression
from service import workouts as workouts_service
from service.sessions import export_session_log
from service.workouts import _to_rir
from svc.app import create_app
from svc.dependencies import get_db
from svc.schemas import WorkoutSetIn

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
FIXED_NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)

CLIENT_A = "11111111-1111-4111-8111-111111111111"
CLIENT_B = "22222222-2222-4222-8222-222222222222"


# --------------------------------------------------------------------------
# Input schema: effort is optional and bounded to RPE 5-10 (RIR 5-0)
# --------------------------------------------------------------------------


def test_workout_set_in_accepts_absent_and_full_rpe_range():
    assert WorkoutSetIn(weight_kg=100.0, reps=5).rpe is None  # blank effort
    assert WorkoutSetIn(weight_kg=100.0, reps=5, rpe=None).rpe is None
    assert WorkoutSetIn(weight_kg=100.0, reps=5, rpe=5.0).rpe == 5.0  # RIR 5
    assert WorkoutSetIn(weight_kg=100.0, reps=5, rpe=10.0).rpe == 10.0  # RIR 0
    assert WorkoutSetIn(weight_kg=100.0, reps=5, rpe=8.5).rpe == 8.5


@pytest.mark.parametrize("rpe", [4.9, 4.0, 0.0, -1.0])
def test_workout_set_in_rejects_rpe_below_five(rpe):
    with pytest.raises(ValidationError):
        WorkoutSetIn(weight_kg=100.0, reps=5, rpe=rpe)


@pytest.mark.parametrize("rpe", [10.1, 11.0, 12.0])
def test_workout_set_in_rejects_rpe_above_ten(rpe):
    with pytest.raises(ValidationError):
        WorkoutSetIn(weight_kg=100.0, reps=5, rpe=rpe)


# --------------------------------------------------------------------------
# Conversion: RIR = 10 - RPE at the display boundary only
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rpe", "rir"),
    [(10.0, 0.0), (9.5, 0.5), (8.5, 1.5), (8.0, 2.0), (5.0, 5.0), (None, None)],
)
def test_to_rir_conversion(rpe, rir):
    assert _to_rir(rpe) == rir


def test_unrated_set_scores_plain_epley_like_rir_zero():
    # Plain Epley: w * (1 + reps / 30), identical to RPE 10 / RIR 0.
    assert set_e1rm(100.0, 8, None) == calculate_e1rm(100.0, 8, 10.0)
    assert set_e1rm(100.0, 8, None) == pytest.approx(100.0 * (1 + 8 / 30))
    assert set_e1rm(100.0, 8, 10.0) == set_e1rm(100.0, 8, None)
    # Never the old assumed RPE 8.5, and never above an honest RIR 0 rating.
    assert set_e1rm(100.0, 8, None) != calculate_e1rm(100.0, 8, 8.5)
    assert set_e1rm(100.0, 8, None) <= set_e1rm(100.0, 8, 5.0)
    assert set_e1rm(0.0, 8, None) == 0.0


def test_session_export_scores_unrated_rows_with_plain_epley():
    rows = [
        {
            "session_id": "s1",
            "session_date": "2026-09-16",
            "split_name": "Upper 1",
            "readiness_score": 4,
            "session_notes": "",
            "started_at": "2026-09-16T10:00:00+00:00",
            "completed_at": "2026-09-16T11:00:00+00:00",
            "exercise_id": "bp",
            "exercise_name": "Bench Press",
            "set_index": 1,
            "weight_kg": 100.0,
            "reps": 8,
            "rpe": None,
            "is_warmup": 0,
            "logged_at": "2026-09-16T10:05:00+00:00",
        }
    ]
    ledger = SimpleNamespace(
        get_session_log=lambda: rows,
        get_session_debrief=lambda session_id: "",
    )
    _, payload = export_session_log(None, "alice", "json", ledger=ledger)
    entry = payload.decode("utf-8")
    assert '"rpe": null' in entry
    assert '"e1rm_kg": 126.67' in entry  # 100 x 8 plain Epley, not 131.67 (RPE 8.5)


# --------------------------------------------------------------------------
# Progression: a blank reading drives no effort-based rule
# --------------------------------------------------------------------------


def test_projection_with_no_effort_only_reads_the_rep_bracket():
    at_ceiling = project_next_load(
        last_weight=100.0, last_reps=8, last_rpe=None, target_reps_max=8, target_rpe=8.5
    )
    assert at_ceiling["status"] == "PROGRESSION_UP"
    assert at_ceiling["delta_kg"] == 2.5

    inside_bracket = project_next_load(
        last_weight=100.0, last_reps=5, last_rpe=None, target_reps_max=8, target_rpe=8.5
    )
    assert inside_bracket["status"] == "LOAD_MAINTAINED"
    assert inside_bracket["delta_kg"] == 0.0

    # No effort reading ever triggers an overshoot deload or an ease-based upscale.
    assert project_next_load(
        last_weight=100.0, last_reps=12, last_rpe=None, target_reps_max=8, target_rpe=7.0
    )["status"] == "PROGRESSION_UP"
    assert project_next_load(
        last_weight=100.0, last_reps=4, last_rpe=None, target_reps_max=8, target_rpe=7.0
    )["status"] == "LOAD_MAINTAINED"


def test_projection_with_a_rating_keeps_the_effort_rules():
    assert project_next_load(
        last_weight=100.0, last_reps=6, last_rpe=10.0, target_reps_max=8, target_rpe=8.0
    )["status"] == "RPE_OVERSHOOT_DELOAD"
    assert project_next_load(
        last_weight=100.0, last_reps=8, last_rpe=7.0, target_reps_max=8, target_rpe=8.5
    )["status"] == "PROGRESSION_UP"


# --------------------------------------------------------------------------
# Deload detection: unrated sets are excluded, never read as 0 or a default
# --------------------------------------------------------------------------

_DELOAD_SCHEMA = """
    CREATE TABLE workout_sessions (id TEXT PRIMARY KEY, session_date TEXT, readiness_score INTEGER);
    CREATE TABLE workout_sets (
        id TEXT PRIMARY KEY, session_id TEXT, exercise_id TEXT, set_index INTEGER,
        weight_kg REAL, reps INTEGER, rpe REAL, is_warmup INTEGER, logged_at TEXT
    );
"""


def _fatigue_db(session_sets):
    """A bare ledger-shaped connection: ``{session_id: [(rpe, is_warmup), ...]}``."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(_DELOAD_SCHEMA)
    for index, (session_id, readiness, sets) in enumerate(session_sets):
        conn.execute(
            "INSERT INTO workout_sessions VALUES (?, ?, ?)",
            (session_id, f"2026-09-{10 + index:02d}", readiness),
        )
        for set_index, (rpe, is_warmup) in enumerate(sets, start=1):
            conn.execute(
                "INSERT INTO workout_sets VALUES (?, ?, 'bp', ?, 100.0, 5, ?, ?, '2026-09-10T10:00:00')",
                (f"{session_id}-{set_index}", session_id, set_index, rpe, is_warmup),
            )
    conn.commit()
    return SimpleNamespace(conn=conn, ledger_conn=conn)


def test_deload_never_reads_unrated_sets_as_effort():
    # Six rated sets at/above RPE 9.5 with declining readiness: the exertion
    # rule fires, and the seven unrated sets stay out of both sides of the ratio.
    db = _fatigue_db([
        ("s1", 3, [(9.5, 0)] * 2 + [(None, 0)] * 3),
        ("s2", 3, [(10.0, 0)] * 2 + [(None, 0)] * 2),
        ("s3", 3, [(9.5, 0)] * 2 + [(None, 0)] * 2),
    ])
    try:
        result = evaluate_systemic_fatigue(db)
        assert result["deload_recommended"] is True
        assert result["severity"] == "MODERATE"
        assert "rated sets" in result["reason"]
    finally:
        db.conn.close()


def test_deload_with_only_unrated_sets_never_fires_on_effort():
    db = _fatigue_db([
        ("s1", 3, [(None, 0)] * 3),
        ("s2", 3, [(None, 0)] * 3),
        ("s3", 3, [(None, 0)] * 3),
    ])
    try:
        result = evaluate_systemic_fatigue(db)
        # Readiness is healthy (3/5 average) and there is no rated effort at all,
        # so neither the readiness nor the exertion rule may fire.
        assert result["deload_recommended"] is False
        assert result["severity"] == "NORMAL"
    finally:
        db.conn.close()


def test_deload_still_fires_on_readiness_when_every_set_is_unrated():
    db = _fatigue_db([
        ("s1", 2, [(None, 0)] * 3),
        ("s2", 2, [(None, 0)] * 3),
        ("s3", 1, [(None, 0)] * 3),
    ])
    try:
        result = evaluate_systemic_fatigue(db)
        assert result["deload_recommended"] is True
        assert result["severity"] == "HIGH"
    finally:
        db.conn.close()


# --------------------------------------------------------------------------
# Commit: a session mixing rated and unrated sets
# --------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setattr(workouts_service, "_now", lambda: FIXED_NOW)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    catalog_path = tmp_path / "catalog.db"
    cat_conn = sqlite3.connect(catalog_path)
    cat_conn.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    cat_conn.execute("CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);")
    cat_conn.execute(
        "INSERT INTO exercises (id, name, body_part, target_muscle) VALUES"
        " ('sq', 'Squat', 'Upper Legs', 'Quads'), ('bp', 'Bench Press', 'Chest', 'Chest'),"
        " ('row', 'Row', 'Back', 'Back');"
    )
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
            yield client, db
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(client, username):
    resp = client.post("/auth/register", json={"trainee_id": username, "password": "correct-horse-1"})
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _exercise_payload(exercise_id, exercise_name):
    return {
        "exercise_id": exercise_id,
        "exercise_name": exercise_name,
        "target_sets": 3,
        "target_reps_min": 5,
        "target_reps_max": 8,
        "target_rpe": 8.5,
        "rest_seconds": 120,
        "notes": None,
    }


def _prepare_player(client, db, username="alice"):
    headers = _register(client, username)
    db.switch_user(username)
    db.ledger.upsert_player_profile({"current_goal": "Strength"})
    db.ledger.save_training_program(
        {
            "program_name": "Split",
            "weekly_frequency": 3,
            "split_type": "Full Body",
            "days": [
                {
                    "day_name": "Full A",
                    "day_order": 1,
                    "exercises": [
                        {
                            "exercise_id": ex_id,
                            "target_sets": 3,
                            "target_reps_min": 5,
                            "target_reps_max": 8,
                            "target_rpe": 8.5,
                        }
                        for ex_id in ("sq", "bp", "row")
                    ],
                }
            ],
        }
    )
    return headers, db.ledger.get_active_program().version


def _commit(client, headers, version, sets, *, client_session_id, performed_date, captured_at):
    resp = client.post(
        "/workouts/sessions",
        headers=headers,
        json={
            "day_order": 1,
            "readiness": 4,
            "session_notes": "",
            "sets": sets,
            "client_session_id": client_session_id,
            "performed_date": performed_date,
            "performed_timezone": "UTC",
            "program_version": version,
            "captured_at": captured_at,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _rated_and_unrated_sets():
    return [
        {
            "exercise": _exercise_payload("bp", "Bench Press"),
            "sets": [
                {"weight_kg": 40.0, "reps": 5, "rpe": 6.0, "is_warmup": True},
                {"weight_kg": 100.0, "reps": 5, "rpe": 8.0},
                {"weight_kg": 90.0, "reps": 8},  # blank effort
                {"weight_kg": 80.0, "reps": 10, "rpe": None},  # explicit null
            ],
        }
    ]


def test_commit_accepts_and_persists_a_mix_of_rated_and_unrated_sets(api):
    client, db = api
    headers, version = _prepare_player(client, db)

    first = _commit(
        client, headers, version, _rated_and_unrated_sets(),
        client_session_id=CLIENT_A, performed_date="2026-09-25", captured_at="2026-09-25T11:00:00+00:00",
    )
    assert first["new_prs"] == []  # first session is the baseline
    assert first["fatigue_post"]["deload_recommended"] is False

    summary = first["exercise_summaries"][0]
    assert summary["top_rpe"] == 8.0  # the heaviest working set is rated
    assert "RPE" not in first["debrief"]
    assert "Baseline logged" in summary["target_text"]

    # Stored exactly as sent: NULL for blank, the rating kept for the rest.
    stored = [
        row
        for row in db.conn.execute(
            "SELECT ws.weight_kg, ws.reps, ws.rpe FROM workout_sets ws"
            " JOIN workout_sessions s ON ws.session_id = s.id"
            " WHERE ws.exercise_id = 'bp' ORDER BY ws.set_index"
        ).fetchall()
    ]
    assert [row["rpe"] for row in stored] == [6.0, 8.0, None, None]

    second = _commit(
        client, headers, version,
        [{
            "exercise": _exercise_payload("bp", "Bench Press"),
            "sets": [{"weight_kg": 102.5, "reps": 5}],  # blank effort top set
        }],
        client_session_id=CLIENT_B, performed_date="2026-09-26", captured_at="2026-09-26T11:00:00+00:00",
    )
    summary = second["exercise_summaries"][0]
    assert summary["top_rpe"] is None
    # Unrated scoring is plain Epley; the load still rose, so the load badge fires
    # without ever consulting an effort reading.
    assert summary["current_e1rm"] == round(set_e1rm(102.5, 5, None), 2)
    assert summary["action"] == "increase"
    assert summary["status_badge"] == "LOAD INCREASE"
    # The follow-up target is spoken in RIR, converted from the stored RPE target.
    assert summary["target_text"].endswith("@ RIR 1.5.")

    # The same commit output feeds the progression alerts: no effort reading, no
    # effort-based regression signal.
    assert progression.signals_from_commit(
        second["exercise_summaries"],
        second["fatigue_post"],
        session_id=second["session_id"],
        session_date="2026-09-26",
    ) == []

    # Baselines expose effort as RIR, null when unrated.
    rows = {row["exercise_id"]: row for row in client.get("/workouts/baselines", headers=headers).json()["baselines"]}
    assert rows["bp"]["last_session"]["sets"] == [{"weight_kg": 102.5, "reps": 5, "rir": None}]

    # The blank-effort path continues through prescription/projection without a crash.
    prescription = client.get("/workouts/prescription", params={"day_order": 1}, headers=headers)
    assert prescription.status_code == 200, prescription.text
    target = next(t for t in prescription.json()["targets"] if t["exercise_id"] == "bp")
    assert target["last_perf"][-1]["rpe"] is None
    assert target["projection"]["status"] in {"LOAD_MAINTAINED", "PROGRESSION_UP"}


def test_a_rated_rpe_10_top_set_still_opens_a_regression_alert():
    """Control for the unrated case: the effort-based alert still works when rated."""
    rated = {
        "exercise_id": "bp",
        "name": "Bench Press",
        "action": "deload",
        "status_badge": "OVERSHOOT",
        "projection_status": "RPE_OVERSHOOT_DELOAD",
        "e1rm_delta": 0.0,
        "current_e1rm": 119.58,
        "top_load": 102.5,
        "top_reps": 5,
        "top_rpe": 10.0,
    }
    recovered = {"deload_recommended": False, "severity": "NORMAL", "intensity_cap_rpe": None}
    signals = progression.signals_from_commit(
        [rated], recovered, session_id="s3", session_date="2026-09-27"
    )
    assert [signal.kind for signal in signals] == [progression.REGRESSION_KIND]
    assert signals[0].subject == "bp"
