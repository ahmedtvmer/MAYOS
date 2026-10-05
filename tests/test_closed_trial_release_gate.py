"""One public-contract story through the closed-trial release gates.

The test uses a temporary SQLite catalog and ledgers, with model generation
made deterministic at the same public FastAPI routes used by the clients.
"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from agent.program_rules import get_default_split
from database.backup import create_daily_backup, restore_daily_backup
from service import alert_sweep
from service import assignments as assignments_service
from service import check_ins as check_ins_service
from service import coach as coach_service
from service import schedule as schedule_service
from service import workouts as workouts_service
from scripts.trial_gate_report import build_trial_gate_report, read_assignment_evidence
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
FIXED_NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
LATE_NOW = FIXED_NOW + timedelta(days=8)


class _FrozenDatetime(datetime):
    instant = FIXED_NOW

    @classmethod
    def now(cls, tz=None):
        return cls.instant.astimezone(tz) if tz is not None else cls.instant.replace(tzinfo=None)


@pytest.fixture
def api(fresh_store, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setattr(workouts_service, "_now", lambda: FIXED_NOW)
    monkeypatch.setattr(check_ins_service, "_now", lambda: FIXED_NOW)
    monkeypatch.setattr(schedule_service, "datetime", _FrozenDatetime)
    from svc.rate_limit import limiter

    limiter._storage.reset()
    db = fresh_store
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client, db


def _register(client, username: str) -> dict:
    response = client.post(
        "/auth/register",
        json={"trainee_id": username, "password": "correct-horse-1"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _account_id(token: str) -> str:
    return jwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])["sub"]


def _make_coach(client, db, username: str, capacity: int = 5) -> tuple[dict, dict]:
    registered = _register(client, username)
    headers = _headers(registered["access_token"])
    owner_invite = coach_service.issue_coach_invite(db, username, actor="cli")
    assert owner_invite["ok"] is True
    redeemed = client.post(
        "/coach/invite/redeem",
        headers=headers,
        json={"token": owner_invite["token"]},
    )
    assert redeemed.status_code == 200, redeemed.text
    profile = client.put(
        "/coach/profile",
        headers=headers,
        json={
            "display_name": f"Coach {username}",
            "bio": "Strength coaching.",
            "specialization": "Strength",
            "capacity": capacity,
        },
    )
    assert profile.status_code == 200, profile.text
    return headers, registered


def _exercise(exercise_id: str, name: str) -> dict:
    return {
        "exercise_id": exercise_id,
        "exercise_name": name,
        "target_sets": 3,
        "target_reps_min": 5,
        "target_reps_max": 8,
        "target_rpe": 8.5,
        "rest_seconds": 120,
        "notes": None,
    }


def _offline_body(
    *,
    client_session_id: str,
    version: int,
    performed_date: str,
    exercises: list[dict[str, str]],
    readiness: int = 4,
) -> dict:
    return {
        "day_order": 1,
        "readiness": readiness,
        "session_notes": "",
        "sets": [
            {
                "exercise": _exercise(exercise["exercise_id"], exercise["exercise_name"]),
                "sets": [{"weight_kg": 45, "reps": 6, "rpe": 8}],
            }
            for exercise in exercises
        ],
        "client_session_id": client_session_id,
        "performed_date": performed_date,
        "performed_timezone": "America/Los_Angeles",
        "program_version": version,
        "captured_at": LATE_NOW.isoformat(),
        "captured_offline": True,
    }


def _substitution_choice(program: dict, *, excluded: set[str] | None = None) -> tuple[dict, dict, dict]:
    excluded = excluded or set()
    for day in program["days"]:
        for exercise in day["exercises"]:
            if exercise["exercise_id"] in excluded:
                continue
            substitutes = exercise.get("suggested_substitutes") or []
            if substitutes:
                return day, exercise, substitutes[0]
    raise AssertionError("generated program has no exercise substitution candidate")


def _unplanned_catalog_exercise(db, planned_ids: set[str]) -> dict[str, str]:
    placeholders = ", ".join("?" for _ in planned_ids)
    with db.catalog_locked() as conn:
        row = conn.execute(
            f"SELECT id, name FROM exercises WHERE id NOT IN ({placeholders})"
            " AND LOWER(body_part) != 'cardio' ORDER BY id LIMIT 1",
            tuple(planned_ids),
        ).fetchone()
    assert row is not None, "temporary exercise catalog needs one movement outside the plan"
    return {"exercise_id": str(row[0]), "exercise_name": str(row[1])}


def _divergence_tuples(entries: list[dict]) -> list[tuple[str, str, str]]:
    return sorted(
        (entry["kind"], entry["exercise_id"], entry["exercise_name"])
        for entry in entries
    )


def _acknowledge_and_resolve_alert(client, headers: dict[str, str], alert_id: str) -> None:
    acknowledged = client.post(
        f"/coach/alerts/{alert_id}/acknowledge", headers=headers
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["state"] == "acknowledged"
    resolved = client.post(f"/coach/alerts/{alert_id}/resolve", headers=headers)
    assert resolved.status_code == 200
    assert resolved.json()["state"] == "resolved"


def test_closed_trial_release_gate_story(api, monkeypatch, scripted_chat_model):
    client, db = api

    # Player and coach registrations both have player capability; an owner
    # invite adds the independent coach capability and profile capacity.
    player = _register(client, "trial-player")
    player_headers = _headers(player["access_token"])
    coach_headers, coach = _make_coach(client, db, "trial-coach", capacity=3)
    unrelated_coach_headers, unrelated_coach = _make_coach(
        client, db, "other-coach", capacity=2
    )
    coach_me = client.get("/auth/me", headers=coach_headers)
    assert coach_me.status_code == 200
    assert coach_me.json()["capabilities"] == {"player": True, "coach": True}
    profile = client.get("/coach/profile", headers=coach_headers)
    assert profile.status_code == 200
    assert profile.json()["capacity"] == 3
    assert profile.json()["display_name"] == "Coach trial-coach"

    invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert invite.status_code == 200, invite.text
    assert invite.json()["capacity"] == 3
    assignment_token = invite.json()["token"]

    # The player sees coach identity and the complete access terms before
    # explicit consent; preview leaves the single-use invitation unconsumed.
    preview = client.post(
        "/assignments/invites/preview",
        headers=player_headers,
        json={"token": assignment_token},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["coach"]["display_name"] == "Coach trial-coach"
    assert preview.json()["access"] == {
        "scope": "current_and_historical_training_data",
        "includes_current_history": True,
        "includes_historical_history": True,
        "active_while_assigned": True,
        "description": (
            "While this assignment is active, your coach can view all of your training data, "
            "both current and historical. Your coach loses that access immediately when the "
            "assignment ends. Your conversations with the player assistant stay private."
        ),
    }
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": assignment_token, "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    assignment_id = redeemed.json()["assignment"]["assignment_id"]
    replay = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": assignment_token, "consent": True},
    )
    assert replay.status_code == 400
    assert client.get("/assignments/me", headers=player_headers).json()["status"] == "active"
    coach_notices = client.get("/coach/assignments/notices", headers=coach_headers)
    assert coach_notices.status_code == 200
    assert any(row["kind"] == "assignment_redeemed" for row in coach_notices.json()["notices"])

    assigned_summary = client.get(
        f"/coach/assignments/{assignment_id}/player/summary", headers=coach_headers
    )
    assert assigned_summary.status_code == 200, assigned_summary.text
    unrelated_read = client.get(
        f"/coach/assignments/{assignment_id}/player/summary",
        headers=unrelated_coach_headers,
    )
    assert unrelated_read.status_code == 403
    assert unrelated_read.json()["detail"] == assignments_service.DENIED_ERROR

    # Seed only the completed intake profile; program generation and its custom
    # split response exercise the real generator and scripted model path.
    player_account = db.get_active_account_by_username("trial-player")
    with db.open_ledger(player_account["ledger_id"]) as ledger:
        ledger.upsert_player_profile(
            {
                "gender": "male",
                "weekly_frequency": 3,
                "rep_preference": "balanced",
                "equipment_access": "Commercial gym",
                "injuries_or_limitations": "None",
                "stress_and_sleep": "normal",
                "training_age_years": 2,
                "current_goal": "hypertrophy",
                "long_term_goal": "progressive overload",
            }
        )
    scripted_chat_model.reset([get_default_split(3), get_default_split(3)])
    custom_split = "upper emphasis with recovery-friendly accessories"
    generated = client.post(
        "/programs/generate",
        headers=player_headers,
        json={"user_split_override": custom_split},
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["player_controls_program"] is True
    active_automatic = client.get("/programs/active", headers=player_headers)
    assert active_automatic.status_code == 200, active_automatic.text
    automatic_version = active_automatic.json()["version"]
    automatic_day, automatic_exercise, automatic_substitute = _substitution_choice(active_automatic.json())
    edited = client.post(
        "/programs/active/substitutions",
        headers=player_headers,
        json={
            "day_name": automatic_day["day_name"],
            "exercise_id": automatic_exercise["exercise_id"],
            "replacement_exercise_id": automatic_substitute["exercise_id"],
            "expected_active_version": automatic_version,
        },
    )
    assert edited.status_code == 200, edited.text
    captured_old_version = edited.json()["version"]
    assert captured_old_version == automatic_version + 1

    # Player schedule is explicit and effective-dated. First sweep sees only
    # a due follow-up; expected weekdays are not missed before their 24-hour
    # local grace expires.
    with db.catalog_locked() as conn:
        conn.execute(
            "UPDATE assignments SET started_at = ? WHERE assignment_id = ?",
            ((FIXED_NOW - timedelta(days=10)).isoformat(), assignment_id),
        )
    scheduled = client.put(
        "/profile/schedule",
        headers=player_headers,
        json={
            "weekdays": [1, 3, 5],
            "timezone": "America/Los_Angeles",
        },
    )
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["current"]["weekdays"] == [1, 3, 5]
    first_sweep = alert_sweep.run_sweep(db, now=FIXED_NOW)
    assert first_sweep["follow_ups_created"] == 1
    assert not [row for row in client.get("/coach/alerts", headers=coach_headers).json()["alerts"] if row["kind"] == "missed_expected_days"]

    first_check_in = client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": FIXED_NOW.date().isoformat(), "channel": "phone", "note": "Weekly call."},
    )
    assert first_check_in.status_code == 200, first_check_in.text
    assert first_check_in.json()["next_follow_up_on"] == "2026-10-03"
    assert not [
        alert
        for alert in db.list_coach_alerts(_account_id(coach["access_token"]), ("new", "acknowledged"))
        if alert["kind"] == "follow_up_due"
    ]

    # First coach publication transfers program authority. Player writes fail,
    # while exact substitution and split-change requests enter the coach queue.
    generated_draft = client.post(
        f"/coach/assignments/{assignment_id}/program-draft/generate",
        headers=coach_headers,
        json={"user_split_override": custom_split},
    )
    assert generated_draft.status_code == 200, generated_draft.text
    published = client.post(
        f"/coach/assignments/{assignment_id}/program-draft/publish",
        headers=coach_headers,
    )
    assert published.status_code == 200, published.text
    published_version = published.json()["version"]
    assert published.json()["published_by_coach_account_id"] == _account_id(coach["access_token"])
    active_coach_program = client.get("/programs/active", headers=player_headers)
    assert active_coach_program.status_code == 200, active_coach_program.text
    assert active_coach_program.json()["player_controls_program"] is False
    request_day, request_exercise, request_substitute = _substitution_choice(active_coach_program.json())
    declined_day, declined_exercise, declined_substitute = _substitution_choice(
        active_coach_program.json(), excluded={request_exercise["exercise_id"]}
    )

    refused_write = client.post(
        "/programs/active/substitutions",
        headers=player_headers,
        json={
            "day_name": request_day["day_name"],
            "exercise_id": request_exercise["exercise_id"],
            "replacement_exercise_id": request_substitute["exercise_id"],
            "expected_active_version": published_version,
        },
    )
    assert refused_write.status_code == 403
    substitution = client.post(
        "/assignments/me/program-requests",
        headers=player_headers,
        json={
            "kind": "exercise_substitution",
            "day_name": request_day["day_name"],
            "exercise_id": request_exercise["exercise_id"],
            "replacement_exercise_id": request_substitute["exercise_id"],
            "reason": "I prefer overhead press.",
        },
    )
    declined_substitution = client.post(
        "/assignments/me/program-requests",
        headers=player_headers,
        json={
            "kind": "exercise_substitution",
            "day_name": declined_day["day_name"],
            "exercise_id": declined_exercise["exercise_id"],
            "replacement_exercise_id": declined_substitute["exercise_id"],
            "reason": "Dumbbell press feels better.",
        },
    )
    split_change = client.post(
        "/assignments/me/program-requests",
        headers=player_headers,
        json={
            "kind": "split_change",
            "desired_weekly_frequency": 4,
            "desired_split_preference": "Upper/Lower",
            "reason": "I would like four training days.",
        },
    )
    assert substitution.status_code == declined_substitution.status_code == split_change.status_code == 200
    assert split_change.json()["kind"] == "split_change"
    queue = client.get(
        f"/coach/assignments/{assignment_id}/program-requests", headers=coach_headers
    )
    assert queue.status_code == 200
    assert {row["kind"] for row in queue.json()["requests"]} == {"exercise_substitution", "split_change"}
    applied = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{substitution.json()['request_id']}/apply",
        headers=coach_headers,
    )
    declined = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{declined_substitution.json()['request_id']}/decline",
        headers=coach_headers,
        json={"response": "Keep the current press for now."},
    )
    assert applied.status_code == 200 and applied.json()["status"] == "applied"
    assert declined.status_code == 200 and declined.json()["status"] == "declined"

    # After the expected-weekday grace expires in the player's timezone, the
    # daily sweep raises the missed-day alert. The Check-in resets its follow-up
    # date; coach alert actions transition new → acknowledged → resolved.
    monkeypatch.setattr(_FrozenDatetime, "instant", LATE_NOW)
    monkeypatch.setattr(check_ins_service, "_now", lambda: LATE_NOW)
    monkeypatch.setattr(workouts_service, "_now", lambda: LATE_NOW)
    late_sweep = alert_sweep.run_sweep(db, now=LATE_NOW)
    assert late_sweep["alerts_created"] >= 1
    alerts = client.get("/coach/alerts", headers=coach_headers).json()["alerts"]
    missed_day = next(row for row in alerts if row["kind"] == "missed_expected_days")
    assert missed_day["missed_count"] == 3
    assert missed_day["streak_start_date"] == "2026-09-28"
    _acknowledge_and_resolve_alert(client, coach_headers, missed_day["alert_id"])

    second_check_in = client.post(
        f"/coach/assignments/{assignment_id}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": LATE_NOW.date().isoformat(), "channel": "in_app"},
    )
    assert second_check_in.status_code == 200
    assert second_check_in.json()["next_follow_up_on"] == "2026-10-11"
    assert len(client.get("/assignments/me/check-ins", headers=player_headers).json()["check_ins"]) == 2
    assignment_evidence = read_assignment_evidence(db.catalog_path)
    trial_report = build_trial_gate_report(assignment_evidence, as_of=LATE_NOW)
    assignment_report = next(
        row for row in trial_report["assignments"] if row["assignment_id"] == assignment_id
    )
    assert assignment_report["coach_published_program"] is True
    assert assignment_report["check_ins"] == 2

    # Offline delivery is idempotent. Ignore the first response as if it were
    # lost, reconcile by client id, and replay the same draft once.
    active_before_sync = client.get("/programs/active", headers=player_headers)
    assert active_before_sync.status_code == 200, active_before_sync.text
    historical_day = next(
        day for day in edited.json()["days"] if day["day_order"] == 1
    )
    planned_exercises = historical_day["exercises"]
    unplanned_exercise = _unplanned_catalog_exercise(
        db, {exercise["exercise_id"] for exercise in planned_exercises}
    )
    offline_exercises = [planned_exercises[0], unplanned_exercise]
    first_session_id = str(uuid.uuid4())
    offline = _offline_body(
        client_session_id=first_session_id,
        version=captured_old_version,
        performed_date="2026-10-03",
        exercises=offline_exercises,
        readiness=1,
    )
    _ = client.post("/workouts/sessions", headers=player_headers, json=offline)
    reconciled = client.get(
        f"/workouts/sessions/by-client-id/{first_session_id}", headers=player_headers
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["is_historical_program"] is True
    assert reconciled.json()["program_version"] == captured_old_version
    assert reconciled.json()["active_program_version_at_sync"] == active_before_sync.json()["version"]
    assert {row["kind"] for row in reconciled.json()["divergences"]} == {"skipped", "unplanned"}
    retry = client.post("/workouts/sessions", headers=player_headers, json=offline)
    assert retry.status_code == 200
    assert retry.json()["session_id"] == reconciled.json()["session_id"]
    with db.open_ledger(player_account["ledger_id"]) as ledger:
        assert ledger.conn.execute("SELECT COUNT(*) FROM workout_sessions").fetchone()[0] == 1
        assert ledger.conn.execute("SELECT COUNT(*) FROM session_commits").fetchone()[0] == 1
        assert ledger.get_active_program().version == active_before_sync.json()["version"]

    coach_history = client.get(
        f"/coach/assignments/{assignment_id}/player/summary", headers=coach_headers
    )
    assert coach_history.status_code == 200
    coach_latest = coach_history.json()["latest_session"]
    assert coach_latest["is_historical_program"] is True
    assert _divergence_tuples(coach_latest["divergences"]) == _divergence_tuples(
        reconciled.json()["divergences"]
    )

    corrected = client.patch(
        f"/workouts/sessions/{reconciled.json()['session_id']}/performed-date",
        headers=player_headers,
        json={"performed_date": "2026-10-04"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["changed"] is True
    assert corrected.json()["session_date"] == "2026-10-04"
    assert client.get(
        f"/workouts/sessions/by-client-id/{first_session_id}", headers=player_headers
    ).json()["session_date"] == "2026-10-04"

    deload = next(row for row in client.get("/coach/alerts", headers=coach_headers).json()["alerts"] if row["kind"] == "deload_recommended")
    _acknowledge_and_resolve_alert(client, coach_headers, deload["alert_id"])

    # Coach revocation is immediate, including for later offline activity.
    revoked = client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers)
    assert revoked.status_code == 200, revoked.text
    denied_after_revoke = client.get(
        f"/coach/assignments/{assignment_id}/player/summary", headers=coach_headers
    )
    assert denied_after_revoke.status_code == 403
    retained = client.get("/programs/active", headers=player_headers)
    assert retained.status_code == 200
    assert retained.json()["published_by_coach_account_id"] == _account_id(coach["access_token"])
    regained_day, regained_exercise, regained_substitute = _substitution_choice(retained.json())
    regained_edit = client.post(
        "/programs/active/substitutions",
        headers=player_headers,
        json={
            "day_name": regained_day["day_name"],
            "exercise_id": regained_exercise["exercise_id"],
            "replacement_exercise_id": regained_substitute["exercise_id"],
            "expected_active_version": retained.json()["version"],
        },
    )
    assert regained_edit.status_code == 200, regained_edit.text
    second_session_id = str(uuid.uuid4())
    after_revoke = _offline_body(
        client_session_id=second_session_id,
        version=captured_old_version,
        performed_date="2026-10-04",
        exercises=offline_exercises,
    )
    after_revoke_result = client.post(
        "/workouts/sessions", headers=player_headers, json=after_revoke
    )
    assert after_revoke_result.status_code == 201, after_revoke_result.text
    denied_after_sync = client.get(
        f"/coach/assignments/{assignment_id}/player/summary", headers=coach_headers
    )
    assert denied_after_sync.status_code == 403

    # The previously unrelated Coach may invite the Player after revocation;
    # the Player can also end that Assignment and immediately cut access again.
    second_invite = client.post("/coach/assignments/invites", headers=unrelated_coach_headers)
    assert second_invite.status_code == 200
    second_assignment = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": second_invite.json()["token"], "consent": True},
    )
    assert second_assignment.status_code == 200
    second_assignment_id = second_assignment.json()["assignment"]["assignment_id"]
    assert client.get(
        f"/coach/assignments/{second_assignment_id}/player/summary",
        headers=unrelated_coach_headers,
    ).status_code == 200
    ended_by_player = client.post("/assignments/me/end", headers=player_headers)
    assert ended_by_player.status_code == 200
    assert client.get(
        f"/coach/assignments/{second_assignment_id}/player/summary",
        headers=unrelated_coach_headers,
    ).status_code == 403

    # Take a recovery snapshot before deletion; restore must preserve the
    # durable deletion record outside the snapshot.
    snapshot = create_daily_backup(db, now=LATE_NOW)
    assert Path(snapshot["path"]).is_dir()
    player_account_id = _account_id(player["access_token"])
    deleted = client.request(
        "DELETE",
        "/auth/account",
        headers=player_headers,
        json={"password": "correct-horse-1"},
    )
    assert deleted.status_code == 200, deleted.text
    assert client.get("/auth/me", headers=player_headers).status_code == 401
    assert client.get("/auth/me", headers=player_headers).json() == {"error": "account_deleted"}
    restored = restore_daily_backup(Path(snapshot["path"]), db=db)
    assert restored["deletions_reapplied"] >= 1
    assert db.get_account(player_account_id)["deleted_at"] is not None
    assert not db.ledger_exists(player_account["ledger_id"])
    coach_account_id = _account_id(coach["access_token"])
    unrelated_coach_account_id = _account_id(unrelated_coach["access_token"])
    for account_id in (coach_account_id, unrelated_coach_account_id):
        surviving_coach = db.get_account(account_id)
        assert surviving_coach is not None
        assert surviving_coach["status"] == "active"
        assert surviving_coach["deleted_at"] is None
    with db.catalog_locked() as conn:
        rows = conn.execute(
            "SELECT assignment_id, status FROM assignments WHERE assignment_id IN (?, ?) ",
            (assignment_id, second_assignment_id),
        ).fetchall()
    assert {row[0]: row[1] for row in rows} == {
        assignment_id: "ended",
        second_assignment_id: "ended",
    }
    unrelated_profile = client.get("/coach/profile", headers=unrelated_coach_headers)
    assert unrelated_profile.status_code == 200
    assert unrelated_profile.json()["display_name"] == "Coach other-coach"
    assert client.get("/auth/me", headers=player_headers).status_code == 401
    reused = _register(client, "trial-player")
    assert _account_id(reused["access_token"]) != player_account_id
    assert client.get("/profile", headers=_headers(reused["access_token"])).status_code == 404
