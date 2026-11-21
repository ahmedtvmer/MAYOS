"""XP, ranks and the weekly-streak award (#743, #795)."""

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from service import missed_day_alerts
from service import schedule as schedule_service
from service import training_status as training_status_service
from service import xp as xp_service
from tests.test_offline_workout_sync import (  # noqa: F401
    FIXED_NOW,
    _assign,
    _authed,
    _make_coach,
    _prepare_player,
    _seed_status_workouts,
    _sync_body,
    api,
)

# --- pure rules -------------------------------------------------------------


def test_rank_ladder_thresholds_and_progress():
    assert [rank.threshold for rank in xp_service.RANKS] == [0, 80, 240, 600, 1200, 2400, 4000]
    assert xp_service.rank_for(0).rank_id == "rookie"
    assert xp_service.rank_for(79).rank_id == "rookie"
    assert xp_service.rank_for(80).rank_id == "regular"
    assert xp_service.rank_for(4000).rank_id == "legend"
    progress = xp_service.rank_progress(120)
    assert progress["rank"]["id"] == "regular"
    assert progress["rank"]["name_ar"] == "منتظم"
    assert progress["next_rank"]["id"] == "committed"
    assert (progress["xp_into_rank"], progress["xp_for_next_rank"]) == (40, 160)
    top = xp_service.rank_progress(5000)
    assert top["next_rank"] is None and top["xp_for_next_rank"] is None


def _facts(**overrides):
    values = dict(
        planned=True,
        prescribed_sets=3,
        target_rpe_by_exercise={"sq": 8.0},
        working_sets=[{"exercise_id": "sq", "rpe": 8.0}] * 3,
        record_exercises=0,
        has_cardio=False,
    )
    values.update(overrides)
    return xp_service.SessionXpFacts(**values)


def _awards(facts):
    return dict(xp_service.award_session(facts))


def test_a_planned_workout_done_as_prescribed_earns_every_plan_award():
    assert _awards(_facts()) == {"planned_workout": 5, "all_sets": 2, "effort_in_range": 1}


def test_effort_above_the_target_earns_nothing_extra():
    # Going harder than the plan never pays: +0 for effort, nothing else lost.
    harder = _facts(working_sets=[{"exercise_id": "sq", "rpe": 9.0}] * 3)
    assert _awards(harder) == {"planned_workout": 5, "all_sets": 2}
    # Half an RPE step above the target still counts as in range.
    half_step = _facts(working_sets=[{"exercise_id": "sq", "rpe": 8.5}] * 3)
    assert "effort_in_range" in _awards(half_step)


def test_a_set_with_no_effort_logged_counts_as_rpe_10():
    unrated = _facts(working_sets=[{"exercise_id": "sq", "rpe": None}] * 3)
    assert "effort_in_range" not in _awards(unrated)


def test_missing_prescribed_sets_loses_only_the_all_sets_award():
    short = _facts(working_sets=[{"exercise_id": "sq", "rpe": 8.0}] * 2)
    assert _awards(short) == {"planned_workout": 5, "effort_in_range": 1}


def test_records_are_capped_and_cardio_counts():
    awards = _awards(_facts(record_exercises=3, has_cardio=True))
    assert awards["personal_record"] == 4
    assert awards["cardio"] == 2


def test_an_unplanned_workout_earns_only_records_and_cardio():
    awards = _awards(
        _facts(planned=False, prescribed_sets=None, target_rpe_by_exercise={},
               record_exercises=1, has_cardio=True)
    )
    assert awards == {"personal_record": 2, "cardio": 2}


def _exercise(exercise_id, *, target_sets=3, target_rpe=8.0, set_groups=None):
    return SimpleNamespace(
        exercise_id=exercise_id, target_sets=target_sets, target_rpe=target_rpe,
        set_groups=set_groups,
    )


def test_day_plan_targets_read_set_groups_and_rir():
    day = SimpleNamespace(exercises=[
        _exercise("sq", target_sets=4, target_rpe=8.0),
        _exercise("bp", set_groups=[
            SimpleNamespace(sets=2, target_rir=2.0),
            SimpleNamespace(sets=1, target_rir=1.0),
        ]),
    ])
    total, targets = xp_service.day_plan_targets(day)
    assert total == 7
    assert targets == {"sq": 8.0, "bp": 9.0}


def test_a_deload_day_done_as_prescribed_earns_full_xp():
    # A deload prescribes fewer sets at a lower effort; meeting that plan is
    # worth the same XP as any other planned workout.
    deload = SimpleNamespace(exercises=[_exercise("sq", target_sets=2, target_rpe=6.0)])
    total, targets = xp_service.day_plan_targets(deload)
    facts = _facts(prescribed_sets=total, target_rpe_by_exercise=targets,
                   working_sets=[{"exercise_id": "sq", "rpe": 6.0}] * 2)
    assert sum(_awards(facts).values()) == 8


# --- ledger and API ---------------------------------------------------------


def _freeze(monkeypatch, instant=FIXED_NOW):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.astimezone(tz)

    monkeypatch.setattr(training_status_service, "datetime", FixedDateTime)
    monkeypatch.setattr(schedule_service, "datetime", FixedDateTime)


def _xp_rows(db, username):
    db.switch_user(username)
    return [
        tuple(row)
        for row in db.ledger.conn.execute(
            "SELECT kind, xp, session_id IS NOT NULL, week_start FROM xp_awards ORDER BY id"
        )
    ]


def test_a_commit_returns_its_breakdown_and_a_replay_returns_it_unchanged(api, monkeypatch):
    client, db = api
    _freeze(monkeypatch)
    headers, version = _prepare_player(client, db)

    first = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert first.status_code == 201, first.text
    xp = first.json()["xp"]
    breakdown = {line["kind"]: line["xp"] for line in xp["breakdown"]}
    # Every rule is listed, a rule not met at 0 (one set per exercise against
    # three prescribed, efforts at or under target 8.5).
    assert list(breakdown) == list(xp_service.AWARD_RULES)
    assert breakdown["planned_workout"] == 5
    assert breakdown["all_sets"] == 0
    assert breakdown["effort_in_range"] == 1
    assert breakdown["cardio"] == 0
    db.switch_user("p1")
    records = db.ledger.conn.execute(
        "SELECT COUNT(DISTINCT exercise_id) FROM personal_records"
    ).fetchone()[0]
    assert breakdown["personal_record"] == 2 * min(records, 2)
    assert xp["counted"] is True
    assert xp["awarded"] == sum(breakdown.values()) == xp["xp_total"]
    assert xp["rank"]["id"] == "rookie" and xp["rank_up"] is None

    replay = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    assert replay.json()["xp"] == xp
    assert sum(row[1] for row in _xp_rows(db, "p1")) == xp["xp_total"]


def test_only_the_first_workout_on_a_local_day_earns_workout_xp(api, monkeypatch):
    client, db = api
    _freeze(monkeypatch)
    headers, version = _prepare_player(client, db)
    first = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    second = client.post(
        "/workouts/sessions", headers=headers,
        json=_sync_body(version=version, client_session_id="22222222-2222-4222-8222-222222222222"),
    )
    assert second.status_code == 201, second.text
    assert second.json()["xp"]["counted"] is False
    assert second.json()["xp"]["awarded"] == 0
    assert second.json()["xp"]["xp_total"] == first.json()["xp"]["xp_total"]


def test_all_prescribed_sets_earn_the_sets_award(api, monkeypatch):
    client, db = api
    _freeze(monkeypatch)
    headers, version = _prepare_player(client, db)
    body = _sync_body(version=version)
    for entry in body["sets"]:
        entry["sets"] = entry["sets"] * 3
    response = client.post("/workouts/sessions", headers=headers, json=body)
    assert response.status_code == 201, response.text
    breakdown = {line["kind"]: line["xp"] for line in response.json()["xp"]["breakdown"]}
    assert breakdown["all_sets"] == 2


def test_a_commit_that_crosses_a_threshold_reports_the_rank_up(api, monkeypatch):
    client, db = api
    _freeze(monkeypatch)
    headers, version = _prepare_player(client, db)
    db.switch_user("p1")
    with db.ledger.ledger_transaction():
        db.ledger.add_xp_award("weekly_streak", 78, now_iso="2026-09-01T00:00:00+00:00",
                               week_start="2026-01-03")
    response = client.post("/workouts/sessions", headers=headers, json=_sync_body(version=version))
    xp = response.json()["xp"]
    assert xp["xp_total"] >= 80
    assert xp["rank_up"]["id"] == "regular"
    assert xp["rank"]["id"] == "regular"


def test_a_status_read_backfills_history_once_and_skips_imported_workouts(api, monkeypatch):
    client, db = api
    _freeze(monkeypatch)
    headers, _version = _prepare_player(client, db)
    # The oldest session is imported history; the next two are MAYOS workouts
    # in two finished weeks before today's week (Saturday 2026-09-26).
    _seed_status_workouts(db, "p1", ["2026-09-05", "2026-09-12", "2026-09-19"])
    monkeypatch.setattr(training_status_service, "imported_workout_count", lambda *_a, **_k: 1)

    status = client.get("/dashboard/training-status", headers=headers)
    assert status.status_code == 200, status.text
    again = client.get("/dashboard/training-status", headers=headers).json()

    rows = _xp_rows(db, "p1")
    weeks = sorted(row[3] for row in rows if row[0] == "weekly_streak")
    # Seeded sessions have no program day, so they earn no workout XP; each
    # finished week with a counted workout earns the streak award exactly once.
    assert weeks == ["2026-09-12", "2026-09-19"]
    assert all(row[0] == "weekly_streak" for row in rows)
    assert status.json()["xp_total"] == again["xp_total"] == 10
    db.switch_user("p1")
    imported = db.ledger.conn.execute(
        "SELECT counted FROM xp_sessions WHERE session_id = 'status-p1-0'"
    ).fetchone()
    assert imported is not None and imported[0] == 0


def test_the_status_read_returns_rank_and_both_streaks(api, monkeypatch):
    client, db = api
    _freeze(monkeypatch)
    headers, _version = _prepare_player(client, db)
    _seed_status_workouts(db, "p1", ["2026-09-12", "2026-09-19", "2026-09-26"])
    body = client.get("/dashboard/training-status", headers=headers).json()
    assert body["weekly_streak"] == 3
    assert body["longest_streak"] == 3
    assert body["this_week_done"] is True
    assert body["week_paused"] is False
    assert body["rank"]["id"] == "rookie"
    assert body["next_rank"]["id"] == "regular"


def test_the_roster_row_carries_the_players_rank_and_streak(api, monkeypatch):
    client, db = api
    _freeze(monkeypatch)
    player_headers, version = _prepare_player(client, db)
    coach_headers = _make_coach(client, db, "coach1")
    assignment_id = _assign(client, coach_headers, player_headers)
    client.post("/workouts/sessions", headers=player_headers, json=_sync_body(version=version))

    coach_account_id = db.get_active_account_by_username("coach1")["account_id"]
    assignment = db.get_active_assignment_for_coach(coach_account_id, assignment_id)
    missed_day_alerts.evaluate_assignment(db, assignment, FIXED_NOW)

    roster = client.get("/coach/assignments", headers=coach_headers)
    assert roster.status_code == 200, roster.text
    entry = next(row for row in roster.json()["assignments"] if row["assignment_id"] == assignment_id)
    assert entry["rank"]["id"] == "rookie"
    assert entry["weekly_streak"] == 1
    assert entry["week_paused"] is False


def test_the_v66_migration_adds_the_xp_tables(api):
    from database.migration_manager import set_ledger_schema_version

    client, db = api
    _prepare_player(client, db)
    with db.open_ledger("p1") as ledger:
        ledger.conn.execute("DROP TABLE xp_awards")
        ledger.conn.execute("DROP TABLE xp_sessions")
        set_ledger_schema_version(ledger.conn, 65)
        ledger._commit_ledger()
    with db.open_ledger("p1") as ledger:
        tables = {
            row[0]
            for row in ledger.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"xp_awards", "xp_sessions"} <= tables


@pytest.mark.parametrize("today, expected", [
    (date(2026, 9, 26), "2026-09-26"),
    (date(2026, 10, 2), "2026-09-26"),
])
def test_weeks_start_on_saturday(today, expected):
    assert xp_service.saturday_week_start(today).isoformat() == expected
