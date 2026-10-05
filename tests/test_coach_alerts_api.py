"""Coach missed-day alert centre and roster badge contract tests (ticket #31, ADR 030).

Exercises the public FastAPI surface: catalog-only alert listing across the new /
acknowledged / resolved states, acknowledge and resolve transitions with
idempotency, roster badge fields, the generic denial for unknown/foreign/ended
assignments, and that no alert or roster read mounts a player ledger.
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import alert_sweep
from service import coach as coach_service
from service.assignments import DENIED_ERROR
from svc.app import create_app
from svc.dependencies import get_db

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
ALL_DAYS = [1, 2, 3, 4, 5, 6, 7]


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


def _register(client, username, password="correct-horse-1"):
    resp = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authed(token):
    return {"Authorization": f"Bearer {token}"}


def _make_coach(client, db, username, capacity=10):
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username, actor="cli")
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
    return coach_headers, player_headers, assignment_id, coach_account_id


def _seed_alert(api, days_ago=5, coach_name="coach", player_name="p1"):
    client, db = api
    coach_headers, player_headers, assignment_id, coach_account_id = _assign(
        api, coach_name=coach_name, player_name=player_name
    )
    now = datetime.now(UTC)
    started = now - timedelta(days=days_ago)
    db.catalog_conn.execute(
        "UPDATE assignments SET started_at = ? WHERE assignment_id = ?",
        (started.isoformat(), assignment_id),
    )
    db.catalog_conn.commit()
    db.switch_user(player_name)
    db.ledger.append_training_schedule(
        player_name,
        ALL_DAYS,
        "UTC",
        (started.date() - timedelta(days=1)).isoformat(),
        "2026-01-01T00:00:00+00:00",
    )
    counts = alert_sweep.run_sweep(db, now=now)
    assert counts["alerts_created"] == 1, counts
    alert = [
        row
        for row in db.list_coach_alerts(coach_account_id, ("new",))
        if row["kind"] == "missed_expected_days"
    ][0]
    return coach_headers, player_headers, assignment_id, coach_account_id, alert


def test_list_alerts_defaults_to_new_and_acknowledged(api):
    coach_headers, _, _, _, alert = _seed_alert(api)
    client, db = api

    default = client.get("/coach/alerts", headers=coach_headers)
    assert default.status_code == 200, default.text
    alerts = default.json()["alerts"]
    assert [row["alert_id"] for row in alerts] == [alert["alert_id"]]
    assert alerts[0]["state"] == "new"
    assert alerts[0]["player_username"] == "p1"
    assert alerts[0]["missed_count"] == 4
    assert alerts[0]["streak_start_date"] == alert["details"]["streak_start_date"]

    resolved = client.get("/coach/alerts?state=resolved", headers=coach_headers)
    assert resolved.status_code == 200
    assert resolved.json()["alerts"] == []

    assert client.get("/coach/alerts?state=bogus", headers=coach_headers).status_code == 400


def test_acknowledge_and_resolve_transitions_are_idempotent(api):
    coach_headers, _, _, _, alert = _seed_alert(api)
    client, db = api
    base = f"/coach/alerts/{alert['alert_id']}"

    acknowledged = client.post(f"{base}/acknowledge", headers=coach_headers)
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["state"] == "acknowledged"
    assert acknowledged.json()["acknowledged_at"] is not None
    assert acknowledged.json()["message_code"] == "coach_alert.missed_expected_days.v1"
    again = client.post(f"{base}/acknowledge", headers=coach_headers)
    assert again.status_code == 200
    assert again.json()["state"] == "acknowledged"
    assert again.json()["acknowledged_at"] == acknowledged.json()["acknowledged_at"]
    assert again.json()["message_params"] == acknowledged.json()["message_params"]

    resolved = client.post(f"{base}/resolve", headers=coach_headers)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["state"] == "resolved"
    assert resolved.json()["resolved_by"] == "coach"
    assert resolved.json()["message_code"] == "coach_alert.missed_expected_days.v1"
    assert resolved.json()["message_params"] == acknowledged.json()["message_params"]
    resolved_again = client.post(f"{base}/resolve", headers=coach_headers)
    assert resolved_again.status_code == 200
    assert resolved_again.json()["state"] == "resolved"
    # A resolved alert stays resolved even when acknowledged again.
    still_resolved = client.post(f"{base}/acknowledge", headers=coach_headers)
    assert still_resolved.status_code == 200
    assert still_resolved.json()["state"] == "resolved"


def test_roster_entries_expose_badge_fields(api):
    coach_headers, _, _, _, _ = _seed_alert(api)
    client, db = api

    roster = client.get("/coach/assignments", headers=coach_headers)
    assert roster.status_code == 200, roster.text
    rows = roster.json()["assignments"]
    assert len(rows) == 1
    assert rows[0]["alerts_new"] == 1
    assert rows[0]["alerts_acknowledged"] == 0
    assert rows[0]["current_missed_streak"] == 4


def test_alert_and_roster_reads_never_open_a_player_ledger(api, monkeypatch):
    coach_headers, _, _, _, alert = _seed_alert(api)
    client, db = api

    mounted: list[str] = []
    real_open_ledger = db.open_ledger

    def spy(ledger_id):
        mounted.append(str(ledger_id))
        return real_open_ledger(ledger_id)

    monkeypatch.setattr(db, "open_ledger", spy)

    assert client.get("/coach/alerts", headers=coach_headers).status_code == 200
    assert client.get("/coach/assignments", headers=coach_headers).status_code == 200
    assert client.post(f"/coach/alerts/{alert['alert_id']}/acknowledge", headers=coach_headers).status_code == 200
    assert client.post(f"/coach/alerts/{alert['alert_id']}/resolve", headers=coach_headers).status_code == 200

    assert "p1" not in mounted
    assert mounted == ["coach"] * len(mounted)


def test_unknown_foreign_and_ended_alerts_deny_generically(api):
    coach_headers, _, assignment_id, _, alert = _seed_alert(api)
    client, db = api
    base = f"/coach/alerts/{alert['alert_id']}"

    unknown = client.post("/coach/alerts/does-not-exist/acknowledge", headers=coach_headers)
    assert unknown.status_code == 403
    assert unknown.json()["detail"] == DENIED_ERROR

    intruder_headers = _make_coach(client, db, "intruder")
    foreign_acknowledged = client.post(f"{base}/acknowledge", headers=intruder_headers)
    assert foreign_acknowledged.status_code == 403
    assert foreign_acknowledged.json()["detail"] == DENIED_ERROR
    foreign = client.post(f"{base}/resolve", headers=intruder_headers)
    assert foreign.status_code == 403
    assert foreign.json()["detail"] == DENIED_ERROR
    assert client.get("/coach/alerts", headers=intruder_headers).json()["alerts"] == []

    assert client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers).status_code == 200
    ended_acknowledged = client.post(f"{base}/acknowledge", headers=coach_headers)
    assert ended_acknowledged.status_code == 403
    assert ended_acknowledged.json()["detail"] == DENIED_ERROR
    ended = client.post(f"{base}/resolve", headers=coach_headers)
    assert ended.status_code == 403
    assert ended.json()["detail"] == DENIED_ERROR
    # The ended assignment's alert disappears from the listing entirely.
    assert client.get("/coach/alerts?state=new&state=acknowledged&state=resolved", headers=coach_headers).json()["alerts"] == []


def test_unknown_kind_and_invalid_alert_evidence_use_safe_api_fallbacks(api):
    coach_headers, _, assignment_id, coach_account_id, _ = _seed_alert(api)
    client, db = api
    player_account_id = db.get_active_account_by_username("p1")["account_id"]
    now_iso = datetime.now(UTC).isoformat()
    db.insert_coach_alert(
        "unknown-kind-alert",
        assignment_id,
        coach_account_id,
        player_account_id,
        "future_alert_kind",
        "unknown-kind",
        {},
        now_iso,
    )
    db.insert_coach_alert(
        "invalid-deload-alert",
        assignment_id,
        coach_account_id,
        player_account_id,
        "deload_recommended",
        "invalid-deload",
        {
            "reason_code": ["private_future_reason"],
            "reason": "System fatigue",
            "recent_readiness_avg": 2.2,
            "player_deload_choice": {"choice": ["invalid"]},
        },
        now_iso,
    )
    db.insert_coach_alert(
        "missing-regression-name-alert",
        assignment_id,
        coach_account_id,
        player_account_id,
        "performance_regression",
        "missing-regression-name",
        {"e1rm_delta": -2.1, "status_badge": "OVERSHOOT"},
        now_iso,
    )

    response = client.get("/coach/alerts", headers=coach_headers)
    assert response.status_code == 200, response.text
    alerts = {row["alert_id"]: row for row in response.json()["alerts"]}

    unknown_kind = alerts["unknown-kind-alert"]
    assert unknown_kind["message_code"] is None
    assert unknown_kind["message_params"] == {}
    assert unknown_kind["message_fallback"] == "Alert details are unavailable."

    invalid_evidence = alerts["invalid-deload-alert"]
    assert invalid_evidence["message_code"] is None
    assert invalid_evidence["message_params"] == {}
    assert invalid_evidence["message_fallback"] == "Deload recommended — System fatigue"
    assert "private_future_reason" not in str(invalid_evidence)

    missing_regression_name = alerts["missing-regression-name-alert"]
    assert missing_regression_name["message_code"] is None
    assert missing_regression_name["message_params"] == {}
    assert missing_regression_name["message_fallback"] == (
        "Performance regression — Exercise: e1RM −2.1 kg (OVERSHOOT)"
    )


def test_non_coach_cannot_read_alerts(api):
    client, db = api
    player = _register(client, "p1")
    response = client.get("/coach/alerts", headers=_authed(player["access_token"]))
    assert response.status_code == 403
    assert response.json()["detail"] == "Coach capability required."


def _seed_training_profile(db, player_name="p1", **fields):
    db.switch_user(player_name)
    db.ledger.upsert_player_profile(fields)


def _stub_profile_rebuild(monkeypatch):
    monkeypatch.setattr("service.profile.generate_program_draft_pipeline", lambda _request, **kwargs: (None, None))


def _profile_alerts(client, coach_headers, states=None):
    path = "/coach/alerts"
    if states:
        path += "?" + "&".join(f"state={state}" for state in states)
    response = client.get(path, headers=coach_headers)
    assert response.status_code == 200, response.text
    return [alert for alert in response.json()["alerts"] if alert["kind"] == "profile_change"]


def test_profile_change_alert_projects_only_changed_training_profile_fields(api, monkeypatch):
    client, db = api
    coach_headers, player_headers, _, _ = _assign(api)
    _seed_training_profile(
        db,
        equipment_access="Commercial gym",
        injuries_or_limitations="None",
        current_goal="Get stronger",
        weight_kg=70,
    )
    _stub_profile_rebuild(monkeypatch)

    response = client.put("/profile", headers=player_headers, json={
        "equipment_access": "Home gym",
        "injuries_or_limitations": "Left knee pain",
        "current_goal": "Build muscle",
        "weight_kg": 74,
    })

    assert response.status_code == 200, response.text
    alerts = _profile_alerts(client, coach_headers)
    assert len(alerts) == 1
    assert alerts[0]["profile_changes"] == {
        "equipment_access": {"before": "Commercial gym", "after": "Home gym"},
        "injuries_or_limitations": {"before": "None", "after": "Left knee pain"},
    }
    assert alerts[0]["message_code"] == "coach_alert.profile_change.v1"
    assert alerts[0]["message_params"] == {
        "changed_fields": ["injuries_or_limitations", "equipment_access"]
    }
    assert alerts[0]["message_fallback"] == "Training profile changed."
    assert "Left knee pain" not in str(alerts[0]["message_params"])
    assert "Left knee pain" not in alerts[0]["message_fallback"]
    assert not ({"current_goal", "weight_kg"} & alerts[0].keys())


def test_profile_change_episode_deduplicates_and_starts_new_episode_after_resolution(api, monkeypatch):
    client, db = api
    coach_headers, player_headers, assignment_id, _ = _assign(api)
    _seed_training_profile(db, equipment_access="Commercial gym", injuries_or_limitations="None")
    _stub_profile_rebuild(monkeypatch)

    for access in ("Home gym", "Bodyweight only"):
        response = client.put("/profile", headers=player_headers, json={"equipment_access": access})
        assert response.status_code == 200, response.text
    alerts = _profile_alerts(client, coach_headers)
    assert len(alerts) == 1
    assert alerts[0]["profile_changes"] == {
        "equipment_access": {"before": "Commercial gym", "after": "Bodyweight only"},
    }

    resolved = client.post(f"/coach/alerts/{alerts[0]['alert_id']}/resolve", headers=coach_headers)
    assert resolved.status_code == 200
    reopened = client.put("/profile", headers=player_headers, json={"equipment_access": "Home gym"})
    assert reopened.status_code == 200, reopened.text
    all_alerts = _profile_alerts(client, coach_headers, ("new", "resolved"))
    assert len(all_alerts) == 2
    assert {alert["state"] for alert in all_alerts} == {"new", "resolved"}
    assert len({alert["alert_id"] for alert in all_alerts}) == 2


def test_profile_change_revert_system_resolves_empty_episode(api, monkeypatch):
    client, db = api
    coach_headers, player_headers, _, _ = _assign(api)
    _seed_training_profile(db, equipment_access="Commercial gym", injuries_or_limitations="None")
    _stub_profile_rebuild(monkeypatch)

    for access in ("Home gym", "Commercial gym"):
        response = client.put("/profile", headers=player_headers, json={"equipment_access": access})
        assert response.status_code == 200, response.text

    assert _profile_alerts(client, coach_headers) == []
    resolved = _profile_alerts(client, coach_headers, ("resolved",))
    assert len(resolved) == 1
    assert resolved[0]["resolved_by"] == "system"
    assert resolved[0]["profile_changes"] == {}


def test_profile_change_from_unset_injury_value_fires_and_ai_excludes_evidence(api, monkeypatch):
    client, db = api
    coach_headers, player_headers, _, coach_account_id = _assign(api)
    _seed_training_profile(db, equipment_access="Commercial gym")
    _stub_profile_rebuild(monkeypatch)

    response = client.put(
        "/profile", headers=player_headers, json={"injuries_or_limitations": "Left knee pain"}
    )
    assert response.status_code == 200, response.text
    alerts = _profile_alerts(client, coach_headers)
    assert len(alerts) == 1
    assert alerts[0]["profile_changes"]["injuries_or_limitations"] == {
        "before": "None", "after": "Left knee pain"
    }

    from service import coach_ai

    assert "profile_changes" not in coach_ai._ALERT_EVIDENCE_FIELDS
    rendered = coach_ai._render_alerts({"alerts": alerts})
    assert "Left knee pain" not in "\n".join(rendered)
    assert coach_account_id == db.get_active_account_by_username("coach")["account_id"]


def test_profile_change_does_not_fire_for_goal_weight_or_unassigned_player(api, monkeypatch):
    client, db = api
    coach_headers, player_headers, _, _ = _assign(api)
    _seed_training_profile(
        db,
        equipment_access="Commercial gym",
        injuries_or_limitations="None",
        current_goal="Get stronger",
        weight_kg=70,
    )
    _stub_profile_rebuild(monkeypatch)
    for body in ({"current_goal": "Build muscle"}, {"weight_kg": 72}):
        assert client.put("/profile", headers=player_headers, json=body).status_code == 200
    assert _profile_alerts(client, coach_headers) == []

    unassigned = _register(client, "unassigned")
    unassigned_headers = _authed(unassigned["access_token"])
    _seed_training_profile(db, "unassigned", equipment_access="Commercial gym")
    response = client.put(
        "/profile", headers=unassigned_headers, json={"injuries_or_limitations": "Shoulder limitation"}
    )
    assert response.status_code == 200, response.text
    assert _profile_alerts(client, coach_headers) == []


def test_profile_alert_write_failure_does_not_block_training_profile_edit(api, monkeypatch):
    client, db = api
    _, player_headers, _, _ = _assign(api)
    _seed_training_profile(db, equipment_access="Commercial gym", injuries_or_limitations="None")
    _stub_profile_rebuild(monkeypatch)
    monkeypatch.setattr(db, "insert_coach_alert", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError()))

    response = client.put("/profile", headers=player_headers, json={"equipment_access": "Home gym"})

    assert response.status_code == 200, response.text
    assert response.json()["profile"]["equipment_access"] == "Home gym"


def test_profile_change_compares_structured_equipment_values_by_value():
    from service.profile_change_alerts import changed_fields

    before = {"equipment_access": {"gym": "home", "options": ["rack", "bench"]}}
    after = {"equipment_access": {"options": ["rack", "bench"], "gym": "home"}}

    assert changed_fields(before, after) == {}
    assert changed_fields(
        {"equipment_access": None}, {"equipment_access": "Home gym"}
    ) == {"equipment_access": {"before": None, "after": "Home gym"}}
