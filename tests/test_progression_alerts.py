"""Deload and performance-regression alert tests (ticket #33, ADR 032).

Exercises the pure signal derivation, the transition-based episode/dedupe rules
at session commit, idempotent re-processing, the commit hook, and the coach-side
visibility contract for the two progression kinds.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.ProgramState import ProgramDaySchema, ProgramExerciseSchema
from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import progression_alerts as progression
from service import workouts as workouts_service
from service.assignments import DENIED_ERROR
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
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
        " ('sq', 'Squat', 'Upper Legs', 'Quads'), ('bp', 'Bench Press', 'Chest', 'Chest');"
    )
    cat_conn.commit()
    cat_conn.close()
    db = DatabaseManager(
        catalog_path=catalog_path,
        users_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        active_user="bootstrap",
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        if db.user_conn is not None:
            db.user_conn.close()
        db.catalog_conn.close()


def _register(client, username, password="correct-horse-1"):
    resp = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _make_coach(client, db, username, capacity=10):
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username)
    assert issued["ok"], issued
    assert client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code == 200
    assert (
        client.put(
            "/coach/profile",
            headers=headers,
            json={"display_name": f"Coach {username}", "bio": "b", "specialization": "s", "capacity": capacity},
        ).status_code
        == 200
    )
    return headers


def _assign(api, coach_name="coach", player_name="p1"):
    client, db = api
    coach_headers = _make_coach(client, db, coach_name)
    token = client.post("/coach/assignments/invites", headers=coach_headers).json()["token"]
    player = _register(client, player_name)
    player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem", headers=player_headers, json={"token": token, "consent": True}
    )
    assert redeemed.status_code == 200, redeemed.text
    assignment_id = redeemed.json()["assignment"]["assignment_id"]
    coach_account_id = db.get_active_account_by_username(coach_name)["account_id"]
    player_account_id = db.get_active_account_by_username(player_name)["account_id"]
    return coach_headers, player_headers, assignment_id, coach_account_id, player_account_id


def _summary(exercise_id, name="Bench Press", **overrides):
    summary = {
        "exercise_id": exercise_id,
        "name": name,
        "top_load": 100.0,
        "top_reps": 5,
        "top_rpe": 9.0,
        "current_e1rm": 100.0,
        "e1rm_delta": 0.0,
        "action": "hold",
        "status_badge": "CONSOLIDATING",
    }
    summary.update(overrides)
    return summary


def _deload_fatigue():
    return {
        "deload_recommended": True,
        "severity": "HIGH",
        "reason": "Rolling readiness crash (avg 1.7/5 across last 3 sessions).",
        "volume_multiplier": 0.5,
        "intensity_cap_rpe": 7.0,
        "recent_readiness_avg": 1.67,
    }


def _recovered():
    return {
        "deload_recommended": False,
        "severity": "NORMAL",
        "reason": "Fatigue within recoverable limits.",
        "volume_multiplier": 1.0,
        "intensity_cap_rpe": None,
        "recent_readiness_avg": 4.0,
    }


def _regression_alert(db, coach_account_id, subject=None, states=("new",)):
    return [
        alert
        for alert in db.list_coach_alerts(coach_account_id, states)
        if alert["kind"] == progression.REGRESSION_KIND
        and (subject is None or alert["dedupe_key"].startswith(f"{subject}:"))
    ]


def _deload_alerts(db, coach_account_id, states=("new",)):
    return [
        alert
        for alert in db.list_coach_alerts(coach_account_id, states)
        if alert["kind"] == progression.DELOAD_KIND
    ]


# --------------------------------------------------------------------------
# A. Pure signal derivation
# --------------------------------------------------------------------------


def test_deload_signal_from_fatigue_verdict():
    signals = progression.signals_from_commit(
        [], _deload_fatigue(), session_id="s1", session_date="2026-09-20"
    )
    assert len(signals) == 1
    signal = signals[0]
    assert signal.kind == progression.DELOAD_KIND
    assert signal.subject == ""
    assert signal.details["reason"] == "Rolling readiness crash (avg 1.7/5 across last 3 sessions)."
    assert signal.details["severity"] == "HIGH"
    assert signal.details["session_id"] == "s1"
    assert signal.details["session_date"] == "2026-09-20"


def test_regression_signal_on_overshoot_deload_action():
    signals = progression.signals_from_commit(
        [_summary("bp", action="deload", status_badge="OVERSHOOT", e1rm_delta=-3.0, current_e1rm=97.0)],
        _recovered(),
        session_id="s1",
        session_date="2026-09-20",
    )
    assert [signal.kind for signal in signals] == [progression.REGRESSION_KIND]
    assert signals[0].subject == "bp"
    assert signals[0].details["status_badge"] == "OVERSHOOT"
    assert signals[0].details["exercise_name"] == "Bench Press"


def test_regression_signal_on_five_percent_e1rm_drop():
    signals = progression.signals_from_commit(
        [_summary("bp", e1rm_delta=-5.0, current_e1rm=95.0)],
        _recovered(),
        session_id="s1",
        session_date="2026-09-20",
    )
    assert len(signals) == 1
    assert signals[0].subject == "bp"


def test_regression_below_threshold_does_not_fire():
    signals = progression.signals_from_commit(
        [_summary("bp", e1rm_delta=-4.9, current_e1rm=95.1)],
        _recovered(),
        session_id="s1",
        session_date="2026-09-20",
    )
    assert signals == []


def test_baseline_exercise_never_fires():
    signals = progression.signals_from_commit(
        [_summary("bp", action="hold", status_badge="BASELINE", e1rm_delta=None, current_e1rm=100.0)],
        _recovered(),
        session_id="s1",
        session_date="2026-09-20",
    )
    assert signals == []


def test_both_signals_can_fire_in_one_commit():
    signals = progression.signals_from_commit(
        [_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)],
        _deload_fatigue(),
        session_id="s1",
        session_date="2026-09-20",
    )
    assert {signal.kind for signal in signals} == {
        progression.DELOAD_KIND,
        progression.REGRESSION_KIND,
    }


def test_projection_rpe_overshoot_fires_even_on_a_load_increase():
    # A top set at RPE 10 with a heavier load: the badge is LOAD INCREASE and the
    # e1RM rose, but the projection is RPE_OVERSHOOT_DELOAD, so it must fire.
    signals = progression.signals_from_commit(
        [
            _summary(
                "bp",
                action="increase",
                status_badge="LOAD INCREASE",
                projection_status="RPE_OVERSHOOT_DELOAD",
                e1rm_delta=2.0,
                current_e1rm=106.0,
            )
        ],
        _recovered(),
        session_id="s1",
        session_date="2026-09-20",
    )
    assert [signal.kind for signal in signals] == [progression.REGRESSION_KIND]
    assert signals[0].subject == "bp"


def test_baseline_rpe_overshoot_never_fires():
    signals = progression.signals_from_commit(
        [
            _summary(
                "bp",
                action="hold",
                status_badge="BASELINE",
                projection_status="RPE_OVERSHOOT_DELOAD",
                e1rm_delta=None,
                current_e1rm=100.0,
            )
        ],
        _recovered(),
        session_id="s1",
        session_date="2026-09-20",
    )
    assert signals == []



# --------------------------------------------------------------------------
# B. Episode / dedupe transitions
# --------------------------------------------------------------------------


def test_commit_opens_one_alert_and_reprocessing_is_a_no_op(api):
    _, _, assignment_id, coach_account_id, player_account_id = _assign(api)
    _, db = api
    kwargs = dict(
        account_id=player_account_id,
        session_id="s1",
        session_date="2026-09-20",
        exercise_summaries=[_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)],
        fatigue_post=_recovered(),
    )
    first = progression.evaluate_commit(db, **kwargs)
    second = progression.evaluate_commit(db, **kwargs)

    assert first["alerts_created"] == 1
    assert second["alerts_created"] == 0
    alerts = _regression_alert(db, coach_account_id)
    assert len(alerts) == 1
    assert alerts[0]["dedupe_key"] == "bp:s1"
    state = db.get_alert_signal_state(assignment_id, progression.REGRESSION_KIND, "bp")
    assert state["active"] == 1
    assert state["episode_key"] == "s1"
    notices = [
        notice
        for notice in db.list_assignment_notices(coach_account_id)
        if notice["kind"] == progression.REGRESSION_KIND
    ]
    assert len(notices) == 1


def test_continuing_episode_updates_the_single_open_alert(api):
    _, _, assignment_id, coach_account_id, player_account_id = _assign(api)
    _, db = api
    progression.evaluate_commit(
        db, player_account_id, "s1", "2026-09-20",
        [_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)], _recovered(),
    )
    progression.evaluate_commit(
        db, player_account_id, "s2", "2026-09-22",
        [_summary("bp", e1rm_delta=-7.0, current_e1rm=93.0)], _recovered(),
    )

    alerts = _regression_alert(db, coach_account_id)
    assert len(alerts) == 1
    assert alerts[0]["dedupe_key"] == "bp:s1"
    assert alerts[0]["details"]["latest_session_id"] == "s2"
    assert alerts[0]["details"]["latest_session_date"] == "2026-09-22"
    assert alerts[0]["details"]["session_id"] == "s1"


def test_non_firing_commit_closes_and_system_resolves(api):
    _, _, assignment_id, coach_account_id, player_account_id = _assign(api)
    _, db = api
    progression.evaluate_commit(
        db, player_account_id, "s1", "2026-09-20",
        [_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)], _recovered(),
    )
    result = progression.evaluate_commit(
        db, player_account_id, "s2", "2026-09-22",
        [_summary("bp", e1rm_delta=1.0, current_e1rm=101.0)], _recovered(),
    )

    assert result["alerts_resolved"] == 1
    assert _regression_alert(db, coach_account_id, states=("new", "acknowledged")) == []
    resolved = _regression_alert(db, coach_account_id, states=("resolved",))
    assert len(resolved) == 1
    assert resolved[0]["resolved_by"] == "system"
    state = db.get_alert_signal_state(assignment_id, progression.REGRESSION_KIND, "bp")
    assert state["active"] == 0


def test_commit_without_the_exercise_leaves_its_episode_unchanged(api):
    _, _, assignment_id, coach_account_id, player_account_id = _assign(api)
    _, db = api
    progression.evaluate_commit(
        db, player_account_id, "s1", "2026-09-20",
        [_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)], _recovered(),
    )
    # A commit for a different exercise must not close the bench-press episode.
    progression.evaluate_commit(
        db, player_account_id, "s2", "2026-09-22",
        [_summary("sq", name="Squat")], _recovered(),
    )

    assert len(_regression_alert(db, coach_account_id)) == 1
    assert db.get_alert_signal_state(assignment_id, progression.REGRESSION_KIND, "bp")["active"] == 1


def test_exercises_have_independent_episodes(api):
    _, _, assignment_id, coach_account_id, player_account_id = _assign(api)
    _, db = api
    progression.evaluate_commit(
        db, player_account_id, "s1", "2026-09-20",
        [
            _summary("bp", e1rm_delta=-6.0, current_e1rm=94.0),
            _summary("sq", name="Squat", e1rm_delta=-10.0, current_e1rm=140.0),
        ],
        _recovered(),
    )
    assert len(_regression_alert(db, coach_account_id)) == 2
    # Only bench recovers; the squat still regresses and stays open.
    progression.evaluate_commit(
        db, player_account_id, "s2", "2026-09-22",
        [_summary("bp", e1rm_delta=1.0, current_e1rm=101.0), _summary("sq", name="Squat", e1rm_delta=-9.0, current_e1rm=141.0)],
        _recovered(),
    )
    remaining = _regression_alert(db, coach_account_id)
    assert len(remaining) == 1
    assert remaining[0]["dedupe_key"] == "sq:s1"
    assert db.get_alert_signal_state(assignment_id, progression.REGRESSION_KIND, "bp")["active"] == 0
    assert db.get_alert_signal_state(assignment_id, progression.REGRESSION_KIND, "sq")["active"] == 1


def test_coach_resolved_alert_stays_resolved_until_a_new_episode(api):
    coach_headers, _, assignment_id, coach_account_id, player_account_id = _assign(api)
    client, db = api
    progression.evaluate_commit(
        db, player_account_id, "s1", "2026-09-20",
        [_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)], _recovered(),
    )
    alert = _regression_alert(db, coach_account_id)[0]
    resolved = client.post(f"/coach/alerts/{alert['alert_id']}/resolve", headers=coach_headers)
    assert resolved.status_code == 200
    assert resolved.json()["state"] == "resolved"

    # The episode is still active: a later firing commit must not reopen it.
    progression.evaluate_commit(
        db, player_account_id, "s2", "2026-09-22",
        [_summary("bp", e1rm_delta=-7.0, current_e1rm=93.0)], _recovered(),
    )
    assert _regression_alert(db, coach_account_id, states=("new", "acknowledged")) == []
    assert len(_regression_alert(db, coach_account_id, states=("resolved",))) == 1

    # Close the episode, then a genuinely new episode creates a fresh alert.
    progression.evaluate_commit(
        db, player_account_id, "s3", "2026-09-24",
        [_summary("bp", e1rm_delta=1.0, current_e1rm=101.0)], _recovered(),
    )
    progression.evaluate_commit(
        db, player_account_id, "s4", "2026-09-26",
        [_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)], _recovered(),
    )
    open_alerts = _regression_alert(db, coach_account_id)
    assert len(open_alerts) == 1
    assert open_alerts[0]["dedupe_key"] == "bp:s4"


def test_deload_episode_opens_and_closes(api):
    _, _, assignment_id, coach_account_id, player_account_id = _assign(api)
    _, db = api
    opened = progression.evaluate_commit(
        db, player_account_id, "s1", "2026-09-20", [], _deload_fatigue()
    )
    assert opened["alerts_created"] == 1
    alert = _deload_alerts(db, coach_account_id)[0]
    assert alert["dedupe_key"] == "s1"
    assert alert["details"]["reason"].startswith("Rolling readiness crash")

    # Still firing: no second alert.
    progression.evaluate_commit(db, player_account_id, "s2", "2026-09-22", [], _deload_fatigue())
    assert len(_deload_alerts(db, coach_account_id, states=("new", "acknowledged"))) == 1

    closed = progression.evaluate_commit(db, player_account_id, "s3", "2026-09-24", [], _recovered())
    assert closed["alerts_resolved"] == 1
    assert _deload_alerts(db, coach_account_id, states=("new", "acknowledged")) == []
    assert db.get_alert_signal_state(assignment_id, progression.DELOAD_KIND, "")["active"] == 0


def test_evaluate_commit_without_active_assignment_is_a_no_op(api):
    client, db = api
    _register(client, "loner")
    account_id = db.get_active_account_by_username("loner")["account_id"]
    result = progression.evaluate_commit(
        db, account_id, "s1", "2026-09-20", [_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)], _recovered()
    )
    assert result["evaluated"] is False
    assert result["alerts_created"] == 0


def test_reprocessing_an_older_session_is_a_no_op(api):
    _, _, assignment_id, coach_account_id, player_account_id = _assign(api)
    _, db = api
    progression.evaluate_commit(
        db, player_account_id, "s1", "2026-09-20",
        [_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)], _recovered(),
    )
    progression.evaluate_commit(
        db, player_account_id, "s2", "2026-09-22",
        [_summary("bp", e1rm_delta=-7.0, current_e1rm=93.0)], _recovered(),
    )
    # s3 stops firing, closing the episode.
    progression.evaluate_commit(
        db, player_account_id, "s3", "2026-09-24",
        [_summary("bp", e1rm_delta=1.0, current_e1rm=101.0)], _recovered(),
    )

    again = progression.evaluate_commit(
        db, player_account_id, "s2", "2026-09-22",
        [_summary("bp", e1rm_delta=-7.0, current_e1rm=93.0)], _recovered(),
    )

    assert again["evaluated"] is False
    assert len(_regression_alert(db, coach_account_id, states=("resolved",))) == 1
    assert _regression_alert(db, coach_account_id, states=("new", "acknowledged")) == []
    # The old session did not overwrite the closed episode's recorded evidence.
    closed = _regression_alert(db, coach_account_id, states=("resolved",))[0]
    assert closed["details"]["latest_session_id"] == "s2"
    assert db.get_alert_signal_state(assignment_id, progression.REGRESSION_KIND, "bp")["active"] == 0


def test_reprocessing_an_older_session_after_a_reopen_is_a_no_op(api):
    _, _, assignment_id, coach_account_id, player_account_id = _assign(api)
    _, db = api
    progression.evaluate_commit(
        db, player_account_id, "s1", "2026-09-20",
        [_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)], _recovered(),
    )
    progression.evaluate_commit(
        db, player_account_id, "s2", "2026-09-22",
        [_summary("bp", e1rm_delta=-7.0, current_e1rm=93.0)], _recovered(),
    )
    progression.evaluate_commit(
        db, player_account_id, "s3", "2026-09-24",
        [_summary("bp", e1rm_delta=1.0, current_e1rm=101.0)], _recovered(),
    )
    progression.evaluate_commit(
        db, player_account_id, "s4", "2026-09-26",
        [_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)], _recovered(),
    )

    # Re-processing s2 must not close s4's episode nor reopen/overwrite anything.
    again = progression.evaluate_commit(
        db, player_account_id, "s2", "2026-09-22",
        [_summary("bp", e1rm_delta=-7.0, current_e1rm=93.0)], _recovered(),
    )

    assert again["evaluated"] is False
    open_alerts = _regression_alert(db, coach_account_id)
    assert len(open_alerts) == 1
    assert open_alerts[0]["dedupe_key"] == "bp:s4"
    state = db.get_alert_signal_state(assignment_id, progression.REGRESSION_KIND, "bp")
    assert state["active"] == 1
    assert state["episode_key"] == "s4"


def test_failed_evaluation_rolls_back_and_can_be_retried(api, monkeypatch):
    _, _, assignment_id, coach_account_id, player_account_id = _assign(api)
    _, db = api
    calls = {"n": 0}
    real_upsert = db.upsert_alert_signal_state

    def flaky_upsert(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected state-upsert failure")
        return real_upsert(*args, **kwargs)

    monkeypatch.setattr(db, "upsert_alert_signal_state", flaky_upsert)
    with pytest.raises(RuntimeError, match="injected state-upsert failure"):
        progression.evaluate_commit(
            db, player_account_id, "s1", "2026-09-20",
            [_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)], _recovered(),
        )

    # The failed attempt left no alert, no state change, and no processed marker.
    assert _regression_alert(db, coach_account_id, states=("new", "acknowledged", "resolved")) == []
    assert db.get_alert_signal_state(assignment_id, progression.REGRESSION_KIND, "bp") is None
    assert db.is_progression_session_processed(assignment_id, "s1") is False

    # Restoring the write and retrying the same commit creates exactly one alert.
    monkeypatch.setattr(db, "upsert_alert_signal_state", real_upsert)
    result = progression.evaluate_commit(
        db, player_account_id, "s1", "2026-09-20",
        [_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)], _recovered(),
    )
    assert result["alerts_created"] == 1
    assert len(_regression_alert(db, coach_account_id)) == 1
    assert db.is_progression_session_processed(assignment_id, "s1") is True


# --------------------------------------------------------------------------
# C. Commit hook
# --------------------------------------------------------------------------


def test_commit_session_hook_creates_a_deload_alert(api):
    _, _, _, coach_account_id, player_account_id = _assign(api)
    _, db = api
    db.switch_user("p1")
    db.upsert_user_profile({"current_goal": "Strength"})
    day_plan = ProgramDaySchema(
        day_name="Full A",
        day_order=1,
        exercises=[
            ProgramExerciseSchema(exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8),
            ProgramExerciseSchema(exercise_id="bp", exercise_name="Bench Press", target_reps_min=5, target_reps_max=8),
            ProgramExerciseSchema(exercise_id="row", exercise_name="Row", target_reps_min=5, target_reps_max=8),
        ],
    )

    result = workouts_service.commit_session(
        db,
        "p1",
        day_plan,
        readiness=1,
        session_notes="",
        sets_by_exercise=[],
        account_id=player_account_id,
        today_date="2026-09-20",
    )

    assert result.body["fatigue_post"]["deload_recommended"] is True
    alerts = _deload_alerts(db, coach_account_id)
    assert len(alerts) == 1
    assert alerts[0]["details"]["session_id"] == result.body["session_id"]


def test_commit_session_hook_creates_a_regression_alert(api):
    _, _, _, coach_account_id, player_account_id = _assign(api)
    _, db = api
    db.switch_user("p1")
    db.upsert_user_profile({"current_goal": "Strength"})
    bench = ProgramExerciseSchema(
        exercise_id="bp", exercise_name="Bench Press", target_reps_min=5, target_reps_max=8, target_rpe=8.5
    )
    day_plan = ProgramDaySchema(
        day_name="Full A",
        day_order=1,
        exercises=[
            ProgramExerciseSchema(exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8),
            bench,
            ProgramExerciseSchema(exercise_id="row", exercise_name="Row", target_reps_min=5, target_reps_max=8),
        ],
    )
    # A top set at RPE 10 against a previous performance: the OVERSHOOT rule fires.
    result = workouts_service.commit_session(
        db,
        "p1",
        day_plan,
        readiness=4,
        session_notes="",
        sets_by_exercise=[
            {
                "exercise": bench,
                "sets": [{"weight_kg": 90.0, "reps": 5, "rpe": 10.0}],
                "previous_perf": [{"weight_kg": 100.0, "reps": 5, "rpe": 8.5}],
            }
        ],
        account_id=player_account_id,
        today_date="2026-09-20",
    )

    summary = result.body["exercise_summaries"][0]
    assert summary["exercise_id"] == "bp"
    assert summary["action"] == "deload"
    alerts = _regression_alert(db, coach_account_id)
    assert len(alerts) == 1
    assert alerts[0]["dedupe_key"] == f"bp:{result.body['session_id']}"
    assert alerts[0]["details"]["exercise_id"] == "bp"


# --------------------------------------------------------------------------
# D. Visibility & console
# --------------------------------------------------------------------------


def test_active_coach_sees_acks_and_resolves_a_regression_alert(api):
    coach_headers, _, _, coach_account_id, player_account_id = _assign(api)
    client, db = api
    progression.evaluate_commit(
        db, player_account_id, "s1", "2026-09-20",
        [_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)], _recovered(),
    )

    listing = client.get("/coach/alerts", headers=coach_headers)
    assert listing.status_code == 200
    rows = listing.json()["alerts"]
    assert len(rows) == 1
    assert rows[0]["kind"] == progression.REGRESSION_KIND
    assert rows[0]["exercise_name"] == "Bench Press"
    assert rows[0]["e1rm_delta"] == -6.0
    assert rows[0]["status_badge"] == "CONSOLIDATING"

    alert_id = rows[0]["alert_id"]
    ack = client.post(f"/coach/alerts/{alert_id}/acknowledge", headers=coach_headers)
    assert ack.status_code == 200
    assert ack.json()["state"] == "acknowledged"
    resolved = client.post(f"/coach/alerts/{alert_id}/resolve", headers=coach_headers)
    assert resolved.status_code == 200
    assert resolved.json()["resolved_by"] == "coach"


def test_unrelated_former_and_new_coach_see_nothing(api):
    coach_headers, player_headers, assignment_id, coach_account_id, player_account_id = _assign(api)
    client, db = api
    progression.evaluate_commit(
        db, player_account_id, "s1", "2026-09-20",
        [_summary("bp", e1rm_delta=-6.0, current_e1rm=94.0)], _recovered(),
    )
    alert = _regression_alert(db, coach_account_id)[0]

    # An unrelated coach cannot act on or list the alert.
    intruder_headers = _make_coach(client, db, "intruder")
    denied = client.post(f"/coach/alerts/{alert['alert_id']}/resolve", headers=intruder_headers)
    assert denied.status_code == 403
    assert denied.json()["detail"] == DENIED_ERROR
    assert client.get("/coach/alerts", headers=intruder_headers).json()["alerts"] == []

    # The former coach loses access the moment the player ends the assignment.
    assert client.post("/assignments/me/end", headers=player_headers).status_code == 200
    ended = client.post(f"/coach/alerts/{alert['alert_id']}/resolve", headers=coach_headers)
    assert ended.status_code == 403
    assert ended.json()["detail"] == DENIED_ERROR
    assert client.get("/coach/alerts", headers=coach_headers).json()["alerts"] == []

    # A new coach does not see the previous assignment's alerts.
    coach_b_headers = _make_coach(client, db, "coachB")
    token_b = client.post("/coach/assignments/invites", headers=coach_b_headers).json()["token"]
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": token_b, "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    assert client.get("/coach/alerts", headers=coach_b_headers).json()["alerts"] == []


def test_roster_badge_counts_progression_alerts(api):
    coach_headers, _, _, _, player_account_id = _assign(api)
    client, db = api
    progression.evaluate_commit(
        db, player_account_id, "s1", "2026-09-20", [], _deload_fatigue()
    )
    roster = client.get("/coach/assignments", headers=coach_headers).json()["assignments"]
    assert roster[0]["alerts_new"] == 1


def test_alert_signal_state_episode_columns_exist(api):
    _, db = api
    columns = {
        str(row[1])
        for row in db.catalog_conn.execute("PRAGMA table_info(alert_signal_state)").fetchall()
    }
    assert columns == {
        "assignment_id",
        "kind",
        "subject",
        "active",
        "episode_key",
        "updated_at",
    }
