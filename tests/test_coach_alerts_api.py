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
    again = client.post(f"{base}/acknowledge", headers=coach_headers)
    assert again.status_code == 200
    assert again.json()["state"] == "acknowledged"
    assert again.json()["acknowledged_at"] == acknowledged.json()["acknowledged_at"]

    resolved = client.post(f"{base}/resolve", headers=coach_headers)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["state"] == "resolved"
    assert resolved.json()["resolved_by"] == "coach"
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
    foreign = client.post(f"{base}/resolve", headers=intruder_headers)
    assert foreign.status_code == 403
    assert foreign.json()["detail"] == DENIED_ERROR

    assert client.post(f"/coach/assignments/{assignment_id}/revoke", headers=coach_headers).status_code == 200
    ended = client.post(f"{base}/resolve", headers=coach_headers)
    assert ended.status_code == 403
    assert ended.json()["detail"] == DENIED_ERROR
    # The ended assignment's alert disappears from the listing entirely.
    assert client.get("/coach/alerts?state=new&state=acknowledged&state=resolved", headers=coach_headers).json()["alerts"] == []


def test_non_coach_cannot_read_alerts(api):
    client, db = api
    player = _register(client, "p1")
    response = client.get("/coach/alerts", headers=_authed(player["access_token"]))
    assert response.status_code == 403
    assert response.json()["detail"] == "Coach capability required."
