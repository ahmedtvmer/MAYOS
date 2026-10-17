"""HTTP privacy and metering boundary for Coach roster questions (#311)."""

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import coach_roster_ai
from service import evaluation_report_gate
from service import roster_snapshot as roster_snapshot_service
from svc.app import create_app
from svc.dependencies import get_db
from svc.routers.coach_ai import _stream_error_payload
from tests.fakes.chat_model import ScriptedChatModel
from utils import model_downloader
from utils.model_metering import MeteringCallback

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
PLAYER_USERNAME = "private_roster_username_17a2"
PLAYER_NAME = "PRIVATE_ROSTER_NAME_82cd"
PLAYER_EMAIL = "private-roster-player@example.test"
PLAYER_PHONE = "PRIVATE_ROSTER_PHONE_4c10"
NOTE = "PRIVATE_ROSTER_NOTE_1b7d do not forward this note"
REQUEST_REASON = "PRIVATE_ROSTER_REQUEST_REASON_390a wants more volume"
PLAYER_CHAT = "PRIVATE_ROSTER_PLAYER_CHAT_7f3a asked for advice"
COACH_NAME = "PRIVATE_ROSTER_COACH_NAME_6f8b"
COACH_BIO = "PRIVATE_ROSTER_COACH_BIO_42d0"
COACH_USERNAME = "rosterprivacycoach"
COACH_MODEL_ID = "deepseek-ai/DeepSeek-V4-Flash"


def _capturing_model(monkeypatch, turns: int = 1) -> ScriptedChatModel:
    model = ScriptedChatModel(
        [
            "The first player in the supplied Roster urgency order needs attention."
        ]
        * turns,
        usage_metadata={"input_tokens": 100, "output_tokens": 24, "total_tokens": 124},
        callbacks=[MeteringCallback(COACH_MODEL_ID)],
    )
    monkeypatch.setattr(model_downloader, "get_coach_llm", lambda *args, **kwargs: model)
    return model


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.delenv("COACH_AI_ENABLED", raising=False)
    monkeypatch.delenv("COACH_AI_EVAL_REPORT", raising=False)
    monkeypatch.delenv("COACH_ROSTER_AI_ENABLED", raising=False)
    monkeypatch.delenv("COACH_ROSTER_AI_EVAL_REPORT", raising=False)
    from service.model_limits import reset_model_limits
    from svc.rate_limit import limiter

    limiter._storage.reset()
    reset_model_limits()
    evaluation_report_gate._report_cache.clear()
    catalog_path = tmp_path / "catalog.db"
    catalog = sqlite3.connect(catalog_path)
    catalog.execute(
        "CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, body_part TEXT, target_muscle TEXT,"
        " equipment TEXT, image_path TEXT, gif_path TEXT, instructions TEXT);"
    )
    catalog.execute(
        "CREATE TABLE exercise_secondary_muscles (exercise_id TEXT, muscle TEXT);"
    )
    catalog.commit()
    catalog.close()
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
            yield client, db, tmp_path, monkeypatch
    finally:
        if db.ledger_conn is not None:
            db.ledger_conn.close()
        db.catalog_conn.close()


def _register(client, username):
    response = client.post(
        "/auth/register", json={"trainee_id": username, "password": "correct-horse-1"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_coach(client, db):
    registered = _register(client, COACH_USERNAME)
    headers = _auth(registered["access_token"])
    invite = coach_service.issue_coach_invite(
        db, COACH_USERNAME, actor="cli"
    )
    assert invite["ok"]
    redeemed = client.post(
        "/coach/invite/redeem", headers=headers, json={"token": invite["token"]}
    )
    assert redeemed.status_code == 200, redeemed.text
    updated = client.put(
        "/coach/profile",
        headers=headers,
        json={
            "display_name": COACH_NAME,
            "bio": COACH_BIO,
            "specialization": "",
            "capacity": 20,
        },
    )
    assert updated.status_code == 200, updated.text
    return headers, db.get_active_account_by_username(COACH_USERNAME)["account_id"]


def _assign(client, db, coach_headers, username):
    invite = client.post("/coach/assignments/invites", headers=coach_headers)
    assert invite.status_code == 200, invite.text
    registered = _register(client, username)
    player_headers = _auth(registered["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite.json()["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    account = db.get_active_account_by_username(username)
    return {
        "headers": player_headers,
        "account_id": account["account_id"],
        "ledger_id": account["ledger_id"],
        "assignment_id": redeemed.json()["assignment"]["assignment_id"],
    }


def _enable(monkeypatch, tmp_path: Path) -> Path:
    config = coach_roster_ai._EVALUATION_REPORT_CONFIG
    model_id, backend = config.model_identity()
    expected_cases = 10
    runs = [
        {
            "case_id": f"case_{index}",
            "question": "q",
            "answer": "a",
            "checks": {},
            "passed": True,
        }
        for index in range(expected_cases)
    ]
    report = {
        "report_version": config.report_version,
        "suite": config.suite_name,
        "mode": "live",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "coach_roster_assistant_cases.json",
        "prompt_hash": config.prompt_hash(),
        "context_version": coach_roster_ai.CONTEXT_VERSION,
        "model": model_id,
        "backend": backend,
        "gates": {
            "privacy": {
                "pass": True,
                "suite": "tests/test_coach_roster_ai_privacy.py",
            },
            "evaluation": {
                "pass": True,
                "total": expected_cases,
                "passed": expected_cases,
                "threshold": expected_cases,
            },
        },
        "run": {
            "total": expected_cases,
            "passed": expected_cases,
            "expected": expected_cases,
            "failed_cases": [],
        },
        "reasons": [],
        "runs": runs,
        "pass": True,
    }
    path = tmp_path / "coach_roster_ai_eval.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setenv("COACH_ROSTER_AI_ENABLED", "true")
    monkeypatch.setenv("COACH_ROSTER_AI_EVAL_REPORT", str(path))
    evaluation_report_gate._report_cache.clear()
    return path


def _seed_private_data(client, db, coach_headers, player, coach_id):
    assert client.post(
        "/auth/email", headers=player["headers"], json={"email": PLAYER_EMAIL}
    ).status_code == 200
    today = datetime.now(UTC).date().isoformat()
    checkin = client.post(
        f"/coach/assignments/{player['assignment_id']}/check-ins",
        headers=coach_headers,
        json={"checked_in_on": today, "channel": "phone", "note": f"{NOTE} {PLAYER_PHONE}"},
    )
    assert checkin.status_code == 200, checkin.text
    db.create_program_request(
        "private-roster-request",
        player["assignment_id"],
        coach_id,
        player["account_id"],
        "exercise_substitution",
        1,
        "Full A",
        "sq",
        "bp",
        None,
        None,
        REQUEST_REASON,
        datetime.now(UTC).isoformat(),
    )
    with db.open_ledger(player["ledger_id"]) as ledger:
        ledger.set_assistant_memory("preferred_name", PLAYER_NAME)
        ledger.add_chat_message("user", PLAYER_CHAT)
        ledger.add_chat_message("assistant", "private player assistant reply")


def _dump_tables(conn):
    names = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return {
        name: sorted(
            (tuple(row) for row in conn.execute(f'SELECT * FROM "{name}"')),
            key=repr,
        )
        for (name,) in names
    }


def _changed_tables(before, after):
    return {
        name
        for name in set(before) | set(after)
        if before.get(name) != after.get(name)
    }


def test_roster_payload_is_deidentified_and_only_usage_is_persisted(api, monkeypatch):
    client, db, tmp_path, _ = api
    coach_headers, coach_id = _make_coach(client, db)
    eligible = _assign(client, db, coach_headers, PLAYER_USERNAME)
    _seed_private_data(client, db, coach_headers, eligible, coach_id)
    legacy = _assign(client, db, coach_headers, "private_legacy_username_11ab")
    with db._catalog_lock:
        db.catalog_conn.execute(
            "UPDATE assignments SET roster_ai_disclosure_version = NULL, "
            "roster_ai_disclosed_at = NULL WHERE assignment_id = ?",
            (legacy["assignment_id"],),
        )
        db.catalog_conn.commit()
    _enable(monkeypatch, tmp_path)
    account_response = client.get("/auth/me", headers=coach_headers)
    assert account_response.status_code == 200
    assert account_response.json()["coach_roster_ai_enabled"] is True
    model = _capturing_model(monkeypatch)

    catalog_before = _dump_tables(db.catalog_conn)
    with db.open_ledger(eligible["ledger_id"]) as ledger:
        ledger_before = _dump_tables(ledger.conn)
    response = client.post(
        "/coach/assistant/roster",
        headers=coach_headers,
        json={
            "question": "Who needs my attention today?",
            "history": [
                {"role": "coach", "content": "Which player was highest?"},
                {"role": "assistant", "content": "P1 was highest."},
            ],
        },
    )
    assert response.status_code == 200, response.text
    reply = response.json()
    assert reply["answer"].startswith(
        "The first player in the supplied Roster urgency order needs attention."
    )
    assert "1 active assignment(s) excluded" in reply["coverage_summary"]
    assert "active assignment(s) excluded" not in reply["answer"]
    assert reply["excluded_for_missing_disclosure"] == 1
    assert reply["left_out_for_budget"] == 0
    assert len(reply["client_mapping"]) == 1
    assert re.fullmatch(r"P[0-9a-f]{12}", reply["client_mapping"][0]["player_id"])
    assert reply["client_mapping"][0]["assignment_id"] == eligible["assignment_id"]
    assert reply["client_mapping"][0]["player_display_name"] == PLAYER_NAME

    messages = model.calls[0]["messages"]
    payload = "\n".join(str(message.content) for message in messages)
    assert "[ROSTER SIGNAL SNAPSHOT]" in messages[0].content
    assert reply["client_mapping"][0]["player_id"] in messages[0].content
    assert "Which player was highest?" in payload
    assert "P1 was highest." in payload
    assert "client_mapping" not in payload
    identifiers = (
        PLAYER_USERNAME,
        PLAYER_NAME,
        PLAYER_EMAIL,
        PLAYER_PHONE,
        eligible["account_id"],
        eligible["assignment_id"],
        legacy["account_id"],
        legacy["assignment_id"],
        COACH_NAME,
        COACH_BIO,
        NOTE,
        REQUEST_REASON,
        PLAYER_CHAT,
        COACH_USERNAME,
        coach_id,
        legacy["headers"]["Authorization"],
    )
    for identifier in identifiers:
        assert identifier not in payload

    catalog_after = _dump_tables(db.catalog_conn)
    with db.open_ledger(eligible["ledger_id"]) as ledger:
        ledger_after = _dump_tables(ledger.conn)
    assert _changed_tables(catalog_before, catalog_after) == {"model_usage"}
    assert _changed_tables(ledger_before, ledger_after) == set()
    usage = [
        row
        for row in db.summarize_model_usage("2000-01-01")
        if row["account_id"] == coach_id
    ]
    assert usage and usage[0]["role"] == "coach"
    usage_text = json.dumps(usage[0])
    assert "Who needs my attention today?" not in usage_text
    assert "highest Roster urgency rank" not in usage_text


def test_roster_answer_returns_projected_coach_allowance(api, monkeypatch):
    client, db, tmp_path, _ = api
    coach_headers, _coach_id = _make_coach(client, db)
    _assign(client, db, coach_headers, "rosterallowancereply")
    _enable(monkeypatch, tmp_path)
    monkeypatch.setenv("AI_LAUNCH_ALLOWANCES_ENABLED", "true")
    for plan in ("FREE", "PRO"):
        monkeypatch.setenv(f"COACH_AI_{plan}_DAILY_REQUESTS", "3")
        monkeypatch.setenv(f"COACH_AI_{plan}_DAILY_RESOURCE_TOKENS", "1000")
    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "0")
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "200000")
    _capturing_model(monkeypatch)

    response = client.post(
        "/coach/assistant/roster",
        headers=coach_headers,
        json={"question": "Who needs my attention today?"},
    )

    assert response.status_code == 200, response.text
    allowance = response.json()["coach_ai_allowance"]
    assert allowance["request_limit"] == 3
    assert allowance["requests_used"] == 1
    assert allowance["requests_remaining"] == 2
    assert allowance["resource_used"] == 124


def test_roster_route_is_off_without_its_separate_enable_gate(api, monkeypatch):
    client, db, _tmp_path, _ = api
    coach_headers, _coach_id = _make_coach(client, db)
    _assign(client, db, coach_headers, "rosterdisabledplayer")
    model = _capturing_model(monkeypatch)
    monkeypatch.delenv("COACH_ROSTER_AI_ENABLED", raising=False)

    response = client.post(
        "/coach/assistant/roster",
        headers=coach_headers,
        json={"question": "Who needs attention?"},
    )
    assert response.status_code == 404
    assert response.json()["message_code"] == "coach.roster_ai_unavailable.v1"
    assert model.calls == []


def test_roster_route_requires_effective_coach_pro_after_closed_trial(api, monkeypatch):
    client, db, tmp_path, _ = api
    coach_headers, _coach_id = _make_coach(client, db)
    _assign(client, db, coach_headers, "rosterfreeplayer")
    _enable(monkeypatch, tmp_path)
    monkeypatch.setenv("COACH_CLOSED_TRIAL_OVERRIDE", "false")
    model = _capturing_model(monkeypatch)

    response = client.post(
        "/coach/assistant/roster",
        headers=coach_headers,
        json={"question": "Who needs attention?"},
    )
    assert response.status_code == 403
    assert "Coach Pro" in response.json()["detail"]
    assert response.json()["message_code"] == "coach.roster_ai_pro_required.v1"
    assert model.calls == []


def test_auth_me_reuses_cached_roster_report_verdict(api, monkeypatch):
    client, db, tmp_path, _ = api
    coach_headers, _coach_id = _make_coach(client, db)
    _enable(monkeypatch, tmp_path)
    validation_calls = []
    validate_report = coach_roster_ai._validate_report_file

    def track_validation(path):
        validation_calls.append(path)
        return validate_report(path)

    monkeypatch.setattr(coach_roster_ai, "_validate_report_file", track_validation)

    for _ in range(3):
        response = client.get("/auth/me", headers=coach_headers)
        assert response.status_code == 200, response.text
        assert response.json()["coach_roster_ai_enabled"] is True

    assert len(validation_calls) == 1


def test_closed_trial_coach_without_a_plan_row_can_ask_roster_questions(
    api, monkeypatch
):
    client, db, tmp_path, _ = api
    coach_headers, coach_id = _make_coach(client, db)
    assert db.list_plans(coach_id) == []
    monkeypatch.setenv("COACH_CLOSED_TRIAL_OVERRIDE", "true")
    _enable(monkeypatch, tmp_path)
    account = client.get("/auth/me", headers=coach_headers)
    assert account.status_code == 200
    assert account.json()["coach_roster_ai_available"] is True
    assert account.json()["plans"]["coach"]["plan"] == "pro"
    _capturing_model(monkeypatch)

    response = client.post(
        "/coach/assistant/roster",
        headers=coach_headers,
        json={"question": "Who needs my attention today?"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["answer"].startswith(
        "The first player in the supplied Roster urgency order needs attention."
    )


def test_roster_route_refuses_when_coach_allowance_is_exhausted(api, monkeypatch):
    client, db, tmp_path, _ = api
    coach_headers, coach_id = _make_coach(client, db)
    _assign(client, db, coach_headers, "rosterallowanceplayer")
    _enable(monkeypatch, tmp_path)
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "100")
    db.record_model_usage(
        account_id=coach_id,
        role="coach",
        model=COACH_MODEL_ID,
        input_tokens=60,
        output_tokens=40,
        cost_usd=0.0,
        estimated=False,
        purpose="seed",
        created_at=datetime.now(UTC).isoformat(),
    )
    _capturing_model(monkeypatch)
    snapshot_calls = []
    build_snapshot = roster_snapshot_service.roster_signal_snapshot

    def track_snapshot(*args, **kwargs):
        snapshot_calls.append((args, kwargs))
        return build_snapshot(*args, **kwargs)

    monkeypatch.setattr(
        roster_snapshot_service, "roster_signal_snapshot", track_snapshot
    )

    response = client.post(
        "/coach/assistant/roster",
        headers=coach_headers,
        json={"question": "Who needs my attention today?"},
    )

    assert response.status_code == 429
    assert response.json()["message_code"] == "ai_limit.daily_usage.v1"
    assert snapshot_calls == []


def test_roster_model_failure_uses_the_one_player_chat_error_shape(
    api, monkeypatch
):
    client, db, tmp_path, _ = api
    coach_headers, _coach_id = _make_coach(client, db)
    _assign(client, db, coach_headers, "rosterfailureplayer")
    _enable(monkeypatch, tmp_path)
    model = ScriptedChatModel([RuntimeError("model failed")])
    monkeypatch.setattr(model_downloader, "get_coach_llm", lambda *args, **kwargs: model)

    response = client.post(
        "/coach/assistant/roster",
        headers=coach_headers,
        json={"question": "Who needs my attention today?"},
    )

    assert response.status_code == 503
    assert response.json() == _stream_error_payload()


def test_roster_route_rate_limits_calls(api, monkeypatch):
    client, db, tmp_path, _ = api
    coach_headers, _coach_id = _make_coach(client, db)
    _assign(client, db, coach_headers, "rosterratelimitplayer")
    _enable(monkeypatch, tmp_path)
    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "0")
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "0")
    from svc.rate_limit import limiter

    limiter._storage.reset()
    _capturing_model(monkeypatch, turns=30)

    responses = [
        client.post(
            "/coach/assistant/roster",
            headers=coach_headers,
            json={"question": "Who needs my attention today?"},
        )
        for _ in range(31)
    ]

    assert [response.status_code for response in responses].count(200) == 30
    limited = responses[-1]
    assert limited.status_code == 429
    assert limited.json()["message_code"] == "http.rate_limited.v1"


def test_roster_route_reports_budget_truncation(api, monkeypatch):
    client, db, tmp_path, _ = api
    coach_headers, _coach_id = _make_coach(client, db)
    _assign(client, db, coach_headers, "rosterbudgetplayer")
    _assign(client, db, coach_headers, "rosterbudgetsecond")
    _enable(monkeypatch, tmp_path)
    original_prepare = coach_roster_ai.prepare_roster_question

    def one_player_budget(snapshot, question, history):
        response_snapshot = snapshot["snapshot"]
        first = coach_roster_ai._allowlisted_signal(
            response_snapshot["players"][0]
        )
        first["player_id"] = coach_roster_ai.player_alias(first["player_id"])
        one_player_snapshot = {
            "as_of": response_snapshot["as_of"],
            "stall_threshold_weeks": response_snapshot["stall_threshold_weeks"],
            "players": [first],
        }
        budget = coach_roster_ai._snapshot_token_count(one_player_snapshot)
        return original_prepare(
            snapshot, question, history, token_budget=budget
        )

    monkeypatch.setattr(
        coach_roster_ai, "prepare_roster_question", one_player_budget
    )
    _capturing_model(monkeypatch)

    response = client.post(
        "/coach/assistant/roster",
        headers=coach_headers,
        json={"question": "Who needs my attention today?"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["left_out_for_budget"] == 1
    assert (
        response.json()["client_mapping"][0]["player_display_name"]
        == "rosterbudgetplayer"
    )
    assert "1 eligible player(s) left out" in response.json()["coverage_summary"]
    assert len(response.json()["client_mapping"]) == 1
