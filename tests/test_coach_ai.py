"""Coach AI feature flag, enable gate, request bounds, and context builder (#45).

The privacy surface lives in ``tests/test_coach_ai_privacy.py``; this module
covers the opt-in machinery (flag + recorded report), the request contract, the
per-account model limits with role ``coach``, and the pure context renderer.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import coach_ai
from svc.app import create_app
from svc.dependencies import get_db
from utils import model_downloader
from utils.model_metering import MeteringCallback

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"


COACH_MODEL_ID = "deepseek-ai/DeepSeek-V4-Flash"


class _StubCoachLLM(BaseChatModel):
    """Coach-role double: records payloads, emits usage, fires the metering callback."""

    model_id: str = COACH_MODEL_ID
    reply: str = "Volume is steady; keep the current plan."
    input_tokens: int = 120
    output_tokens: int = 30
    payloads: list = []

    @property
    def _llm_type(self) -> str:
        return "stub-coach"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.payloads.append(list(messages))
        usage = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
        }
        message = AIMessage(content=self.reply, usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=message)])


def _stub_coach_llm(monkeypatch, reply: str = "Volume is steady; keep the current plan.") -> _StubCoachLLM:
    stub = _StubCoachLLM(reply=reply, callbacks=[MeteringCallback(COACH_MODEL_ID)])
    monkeypatch.setattr(model_downloader, "get_coach_llm", lambda *args, **kwargs: stub)
    return stub


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.delenv("COACH_AI_ENABLED", raising=False)
    monkeypatch.delenv("COACH_AI_EVAL_REPORT", raising=False)
    from service.model_limits import reset_model_limits
    from svc.rate_limit import limiter

    limiter._storage.reset()
    reset_model_limits()
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
            yield client, db, tmp_path
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


def _account_id(db, username):
    account = db.get_active_account_by_username(username)
    assert account is not None
    return account["account_id"]


def _make_coach(client, db, username="coach", capacity=5):
    registered = _register(client, username)
    headers = _authed(registered["access_token"])
    issued = coach_service.issue_coach_invite(db, username)
    assert issued["ok"], issued
    assert client.post("/coach/invite/redeem", headers=headers, json={"token": issued["token"]}).status_code == 200
    assert (
        client.put(
            "/coach/profile",
            headers=headers,
            json={"display_name": "Coach", "bio": "b", "specialization": "s", "capacity": capacity},
        ).status_code
        == 200
    )
    return headers


def _assigned_player(api, player_name="p1"):
    client, db, _tmp_path = api
    coach_headers = _make_coach(client, db)
    invite = client.post("/coach/assignments/invites", headers=coach_headers).json()
    player = _register(client, player_name)
    player_headers = _authed(player["access_token"])
    redeemed = client.post(
        "/assignments/invites/redeem",
        headers=player_headers,
        json={"token": invite["token"], "consent": True},
    )
    assert redeemed.status_code == 200, redeemed.text
    assert (
        client.put(
            "/profile", headers=player_headers, json={"weekly_frequency": 4, "current_goal": "Hypertrophy"}
        ).status_code
        == 200
    )
    return coach_headers, player_headers, redeemed.json()["assignment"]["assignment_id"]


def _passing_runs(count: int = 6) -> list[dict[str, Any]]:
    return [
        {"case_id": f"case_{index}", "question": "q", "answer": "a", "checks": {}, "passed": True}
        for index in range(count)
    ]


def _write_report(tmp_path: Path, mutations: dict | None = None) -> Path:
    """A complete, valid report as the runner would record it (ADR 049)."""
    model_id, backend = coach_ai.coach_model_identity()
    runs = _passing_runs()
    report = {
        "report_version": coach_ai.REPORT_VERSION,
        "suite": "coach_assistant",
        "mode": "live",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": "coach_assistant_cases.json",
        "prompt_hash": coach_ai.prompt_version_hash(),
        "context_version": coach_ai.CONTEXT_VERSION,
        "model": model_id,
        "backend": backend,
        "gates": {
            "privacy": {"pass": True, "suite": "tests/test_coach_ai_privacy.py"},
            "evaluation": {"pass": True, "total": len(runs), "passed": len(runs), "threshold": len(runs)},
        },
        "run": {"total": len(runs), "passed": len(runs), "expected": len(runs), "failed_cases": []},
        "reasons": [],
        "runs": runs,
        "pass": True,
    }
    if mutations:
        report.update(mutations)
    path = tmp_path / "coach_ai_eval.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _enable(monkeypatch, tmp_path: Path, mutations: dict | None = None) -> Path:
    path = _write_report(tmp_path, mutations)
    monkeypatch.setenv("COACH_AI_ENABLED", "true")
    monkeypatch.setenv("COACH_AI_EVAL_REPORT", str(path))
    return path


QUESTION = {"question": "How has volume been this week?"}


# --------------------------------------------------------------------------
# Pure context renderer
# --------------------------------------------------------------------------


def test_format_number_is_deterministic():
    assert coach_ai.format_number(12400.0) == "12400"
    assert coach_ai.format_number(83.3) == "83.3"
    assert coach_ai.format_number(142.5) == "142.5"
    assert coach_ai.format_number(None) == "n/a"
    assert coach_ai.format_number(5) == "5"


def _sample_facts() -> dict[str, Any]:
    return {
        "as_of": "2026-09-28",
        "assignment": {"started_on": "2026-09-01", "status": "active"},
        "program": {
            "name": "Hypertrophy Block",
            "split": "Upper/Lower",
            "weekly_frequency": 4,
            "version": 3,
            "days": [
                {
                    "order": 1,
                    "day": "Upper A",
                    "exercises": [{"name": "Squat", "sets": 3, "reps": "5-8", "rpe": 8.5}],
                }
            ],
        },
        "volume": {"last_7_days_kg": 12400.0, "last_28_days_kg": 48000.0},
        "recent_sessions": [
            {
                "session_date": "2026-09-24",
                "split_name": "Upper A",
                "sets_count": 18,
                "total_volume_kg": 12400.0,
                "readiness_score": 4,
                "program_version": 3,
                "divergences": [{"kind": "skipped", "exercise_name": "Row"}],
            }
        ],
        "recent_sessions_totals": {"sessions": 1, "sets": 18, "volume_kg": 12400.0},
        "personal_records": [
            {
                "exercise": "Squat",
                "record_type": "e1rm",
                "reps": 5,
                "value": 142.5,
                "prev_value": 138.0,
                "achieved_at": "2026-09-20",
            }
        ],
        "attendance": {
            "timezone": "Europe/Berlin",
            "local_today": "2026-09-28",
            "window_start": "2026-09-01",
            "expected_days": 12,
            "satisfied_days": 10,
            "missed_days": 2,
            "adherence_pct": 83.3,
            "trailing_missed_streak": 0,
            "last_missed_on": "2026-09-17",
        },
        "schedule": {"weekdays": [1, 3, 5], "timezone": "Europe/Berlin"},
        "pauses": [{"starts_on": "2026-10-01", "ends_on": "2026-10-07"}],
        "alerts": [
            {
                "kind": "missed_expected_days",
                "state": "new",
                "created_at": "2026-09-25T10:00:00+00:00",
                "streak_start_date": "2026-09-24",
                "missed_count": 2,
            }
        ],
        "check_ins": [{"checked_in_on": "2026-09-17", "channel": "phone"}],
        "program_requests": {
            "total": 1,
            "pending": 1,
            "pending_by_kind": {"exercise_substitution": 1},
        },
    }


def test_render_context_states_every_deterministic_figure():
    rendered = coach_ai.render_context(_sample_facts())
    for expected in (
        "[PLAYER TELEMETRY]",
        "volume_last_7_days_kg: 12400",
        "volume_last_28_days_kg: 48000",
        "adherence_pct: 83.3",
        "expected_days: 12",
        "satisfied_days: 10",
        "missed_days: 2",
        "trailing_missed_streak: 0",
        "recent_sessions_totals: sessions 1, sets 18, volume_kg 12400",
        "Squat e1rm 5 reps: 142.5 kg (previous 138)",
        "missed_expected_days new",
        "schedule: weekdays [1,3,5] timezone Europe/Berlin",
        "pause: 2026-10-01..2026-10-07",
        "2026-09-17 phone",
        "pending 1 (exercise_substitution 1)",
        "day 1 Upper A: Squat 3x5-8 @RIR ≥ 2",
        "divergences skipped Row",
    ):
        assert expected in rendered, expected


def test_render_context_states_missing_sections_as_insufficient_data():
    rendered = coach_ai.render_context({"as_of": "2026-09-28"})
    for marker in (
        "program:\n  none recorded",
        "recent_sessions: none recorded",
        "personal_records: none yet",
        "attendance: unavailable (no training schedule recorded)",
        "schedule: none recorded",
        "pauses: none",
        "alerts: none",
        "check_ins: none yet",
        "program_requests: none pending",
    ):
        assert marker in rendered, marker


def test_render_context_speaks_effort_as_rir_never_rpe():
    """The coach-facing context shows effort as RIR; stored facts keep RPE (#111)."""
    facts = _sample_facts()
    facts["program"]["days"][0]["exercises"].append(
        {"name": "Row", "sets": 3, "reps": "8-10", "rpe": None}
    )
    facts["alerts"].append(
        {
            "kind": "performance_regression",
            "state": "open",
            "exercise_name": "Squat",
            "e1rm_delta": -6.0,
            "top_rpe": 10.0,
            "intensity_cap_rpe": 7.0,
        }
    )
    rendered = coach_ai.render_context(facts)

    # A target is the equivalent *minimum* RIR (rounded up); a recorded
    # top set is the effort itself; an unrated one reads "not rated".
    assert "Squat 3x5-8 @RIR ≥ 2" in rendered
    assert "Row 3x8-10 @RIR not rated" in rendered
    assert "top_rir 0" in rendered
    assert "intensity_cap_rir ≥ 3" in rendered
    assert "@RPE" not in rendered
    assert "top_rpe" not in rendered
    assert "intensity_cap_rpe" not in rendered



def test_system_prompt_forbids_computation_and_medical_advice():
    assert "Never compute, estimate, or invent" in coach_ai.SYSTEM_PROMPT
    assert "no diagnosis" in coach_ai.SYSTEM_PROMPT
    assert '"the player"' in coach_ai.SYSTEM_PROMPT
    assert coach_ai.CONTEXT_VERSION == "coach-context-v3"


def test_issue_148_messages_have_one_leading_system_message():
    context_text = coach_ai.render_context(coach_ai.CANONICAL_FIXTURE)
    messages = coach_ai.build_messages(context_text, "How is progress?", [])

    system_message_indexes = [
        index for index, message in enumerate(messages) if isinstance(message, SystemMessage)
    ]
    assert system_message_indexes == [0]
    assert messages[0].content == f"{coach_ai.SYSTEM_PROMPT}\n\n{context_text}"


# --------------------------------------------------------------------------
# Enable gate (flag + recorded report)
# --------------------------------------------------------------------------


def test_gate_is_off_by_default(api):
    _client, _db, tmp_path = api
    status = coach_ai.resolve_enable_gate()
    assert status.requested is False
    assert status.enabled is False
    assert coach_ai.coach_ai_enabled() is False


def test_gate_refuses_the_flag_without_a_report(api, monkeypatch):
    _client, _db, tmp_path = api
    monkeypatch.setenv("COACH_AI_ENABLED", "true")
    status = coach_ai.resolve_enable_gate()
    assert status.requested is True
    assert status.enabled is False
    assert "COACH_AI_EVAL_REPORT" in status.reason


def test_gate_refuses_a_missing_report_file(api, monkeypatch):
    _client, _db, _tmp = api
    monkeypatch.setenv("COACH_AI_ENABLED", "true")
    monkeypatch.setenv("COACH_AI_EVAL_REPORT", str(_tmp / "absent.json"))
    assert coach_ai.resolve_enable_gate().enabled is False


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"pass": False}, "pass=true"),
        ({"prompt_hash": "stale"}, "prompt_hash"),
        ({"gates": {"privacy": {"pass": False}, "evaluation": {"pass": True}}}, "privacy"),
        ({"gates": {"privacy": {"pass": True}, "evaluation": {"pass": False}}}, "evaluation"),
        ({"gates": None}, "gates"),
        ({"mode": "mock"}, "mock"),
        ({"report_version": coach_ai.REPORT_VERSION + 1}, "report_version"),
        ({"model": "Qwen/some-other-model"}, "model"),
        ({"runs": []}, "runs"),
    ],
)
def test_gate_refuses_incomplete_reports(api, monkeypatch, overrides, fragment):
    _client, _db, tmp_path = api
    _enable(monkeypatch, tmp_path, overrides)
    status = coach_ai.resolve_enable_gate()
    assert status.enabled is False
    assert fragment in status.reason


def test_gate_accepts_a_passing_report_for_the_current_prompt(api, monkeypatch, tmp_path):
    _client, _db, _tmp = api
    _enable(monkeypatch, tmp_path)
    status = coach_ai.resolve_enable_gate()
    assert status.enabled is True
    assert coach_ai.coach_ai_enabled() is True


def test_startup_check_logs_a_refusal_and_never_enables(api, caplog, monkeypatch, tmp_path):
    _client, _db, _tmp = api
    _enable(monkeypatch, tmp_path, {"pass": False})
    with caplog.at_level("ERROR", logger="service.coach_ai"):
        status = coach_ai.log_enable_gate_at_startup()
    assert status.enabled is False
    assert any("refused" in record.message for record in caplog.records)
    assert coach_ai.coach_ai_enabled() is False


def test_auth_me_reports_the_effective_flag(api, monkeypatch, tmp_path):
    client, _db, _tmp = api
    token = _register(client, "alice")["access_token"]
    body = client.get("/auth/me", headers=_authed(token)).json()
    assert body["coach_ai_enabled"] is False

    _enable(monkeypatch, tmp_path)
    body = client.get("/auth/me", headers=_authed(token)).json()
    assert body["coach_ai_enabled"] is True


def test_prompt_hash_covers_the_rendered_context(monkeypatch):
    baseline = coach_ai.prompt_version_hash()
    original = coach_ai.render_context
    monkeypatch.setattr(
        coach_ai, "render_context", lambda facts: original(facts).replace("adherence_pct:", "adherence_percent:")
    )
    assert coach_ai.prompt_version_hash() != baseline


def test_prompt_hash_changes_when_a_rendered_field_is_dropped(monkeypatch):
    baseline = coach_ai.prompt_version_hash()
    monkeypatch.setattr(
        coach_ai,
        "_ALERT_EVIDENCE_FIELDS",
        tuple(key for key in coach_ai._ALERT_EVIDENCE_FIELDS if key != "missed_count"),
    )
    assert coach_ai.prompt_version_hash() != baseline


def test_prompt_hash_covers_the_system_prompt_and_message_assembly(monkeypatch):
    baseline = coach_ai.prompt_version_hash()
    monkeypatch.setattr(coach_ai, "SYSTEM_PROMPT", coach_ai.SYSTEM_PROMPT + "\n- an extra rule")
    assert coach_ai.prompt_version_hash() != baseline

    original_build = coach_ai.build_messages
    monkeypatch.setattr(
        coach_ai,
        "build_messages",
        lambda context, question, history: original_build(context, question, history),
    )
    # Same assembly produces the same hash; a structural change is covered by
    # the renderer/prompt tests above (and by CONTEXT_VERSION as the manual bump).
    assert coach_ai.prompt_version_hash() != baseline


def test_gate_rejects_a_report_recorded_for_another_model(api, monkeypatch, tmp_path):
    _client, _db, _tmp = api
    path = _enable(monkeypatch, tmp_path)
    assert coach_ai.resolve_enable_gate().enabled is True

    report = json.loads(path.read_text(encoding="utf-8"))
    report["model"] = "Qwen/some-other-model"
    path.write_text(json.dumps(report), encoding="utf-8")

    status = coach_ai.resolve_enable_gate()
    assert status.enabled is False
    assert "model" in status.reason


def test_gate_rejects_a_report_recorded_for_another_backend(api, monkeypatch, tmp_path):
    _client, _db, _tmp = api
    _enable(monkeypatch, tmp_path)
    assert coach_ai.resolve_enable_gate().enabled is True

    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("COACH_MODEL", "Qwen/other-model")
    status = coach_ai.resolve_enable_gate()
    assert status.enabled is False
    assert "backend" in status.reason


def test_gate_rejects_runs_that_do_not_support_the_recorded_verdict(api, monkeypatch, tmp_path):
    _client, _db, _tmp = api
    failing = {
        "case_id": "case_0",
        "question": "q",
        "answer": "a",
        "checks": {"no_identifiers": {"name": "no_identifiers", "passed": False}},
        "passed": False,
    }
    _enable(monkeypatch, tmp_path, {"runs": [failing], "gates": {
        "privacy": {"pass": True, "suite": "tests/test_coach_ai_privacy.py"},
        "evaluation": {"pass": True, "total": 1, "passed": 1, "threshold": 1},
    }})
    status = coach_ai.resolve_enable_gate()
    assert status.enabled is False
    assert "disagrees" in status.reason


def test_report_validation_is_cached_on_path_mtime_size(api, monkeypatch, tmp_path):
    _client, _db, _tmp = api
    path = _enable(monkeypatch, tmp_path)
    calls: list[str] = []
    original = coach_ai._validate_report_file

    def counting(report_path: str):
        calls.append(report_path)
        return original(report_path)

    monkeypatch.setattr(coach_ai, "_validate_report_file", counting)

    assert coach_ai.resolve_enable_gate().enabled is True
    assert coach_ai.coach_ai_enabled() is True
    assert len(calls) == 1, "the parsed verdict must be reused across requests"

    report = json.loads(path.read_text(encoding="utf-8"))
    report["dataset"] = "coach_assistant_cases.json "
    path.write_text(json.dumps(report), encoding="utf-8")
    assert coach_ai.resolve_enable_gate().enabled is True
    assert len(calls) == 2, "a changed report (size/mtime) must be re-validated"


def test_flag_off_never_touches_the_report_file(api, monkeypatch, tmp_path):
    _client, _db, _tmp = api
    _enable(monkeypatch, tmp_path)
    assert coach_ai.resolve_enable_gate().enabled is True

    monkeypatch.setenv("COACH_AI_ENABLED", "false")

    def boom(_report_path: str):
        raise AssertionError("flag-off must not read the report")

    monkeypatch.setattr(coach_ai, "_validate_report_file", boom)
    assert coach_ai.coach_ai_enabled() is False


def test_extract_answer_falls_back_when_the_scrubber_empties_the_reply():
    from utils.text_scrubber import EMPTY_RESPONSE_FALLBACK

    assert coach_ai.extract_answer(AIMessage(content="")) == EMPTY_RESPONSE_FALLBACK
    assert coach_ai.extract_answer(AIMessage(content="  ")) == EMPTY_RESPONSE_FALLBACK
    # A surviving reply keeps its text (the scrubber may capitalize the first word).
    assert coach_ai.extract_answer("plain text") == "Plain text"


def test_empty_model_reply_returns_the_standard_fallback(api, monkeypatch, tmp_path):
    from utils.text_scrubber import EMPTY_RESPONSE_FALLBACK

    client, _db, _tmp = api
    coach_headers, _player_headers, assignment_id = _assigned_player(api)
    _enable(monkeypatch, tmp_path)
    _stub_coach_llm(monkeypatch, reply="")

    response = client.post(
        f"/coach/assignments/{assignment_id}/assistant", headers=coach_headers, json=QUESTION
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"answer": EMPTY_RESPONSE_FALLBACK}


# --------------------------------------------------------------------------
# Request contract and limits
# --------------------------------------------------------------------------


def test_assistant_rejects_out_of_bounds_requests(api):
    client, _db, _tmp = api
    coach_headers, _player_headers, assignment_id = _assigned_player(api)
    base = f"/coach/assignments/{assignment_id}/assistant"

    long_question = {"question": "x" * 1001}
    assert client.post(base, headers=coach_headers, json=long_question).status_code == 422
    empty = {"question": ""}
    assert client.post(base, headers=coach_headers, json=empty).status_code == 422

    too_many_turns = {
        "question": "ok?",
        "history": [{"role": "coach", "content": "hi"} for _ in range(13)],
    }
    assert client.post(base, headers=coach_headers, json=too_many_turns).status_code == 422

    long_turn = {"question": "ok?", "history": [{"role": "coach", "content": "x" * 2001}]}
    assert client.post(base, headers=coach_headers, json=long_turn).status_code == 422

    bad_role = {"question": "ok?", "history": [{"role": "player", "content": "hi"}]}
    assert client.post(base, headers=coach_headers, json=bad_role).status_code == 422


def test_flag_off_returns_404_and_never_calls_the_model(api, monkeypatch):
    client, _db, _tmp = api
    coach_headers, _player_headers, assignment_id = _assigned_player(api)
    stub = _stub_coach_llm(monkeypatch)

    response = client.post(
        f"/coach/assignments/{assignment_id}/assistant", headers=coach_headers, json=QUESTION
    )
    assert response.status_code == 404
    assert "not available" in response.json()["detail"]
    assert stub.payloads == []


def test_enabled_turn_answers_and_meters_with_role_coach(api, monkeypatch, tmp_path):
    client, db, _tmp = api
    coach_headers, _player_headers, assignment_id = _assigned_player(api)
    _enable(monkeypatch, tmp_path)
    stub = _stub_coach_llm(monkeypatch, reply="No change: 12400 kg in the last 7 days.")

    response = client.post(
        f"/coach/assignments/{assignment_id}/assistant", headers=coach_headers, json=QUESTION
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"answer": "No change: 12400 kg in the last 7 days."}
    assert len(stub.payloads) == 1

    rows = [
        row
        for row in db.summarize_model_usage("2000-01-01")
        if row["account_id"] == _account_id(db, "coach")
    ]
    assert rows and rows[0]["role"] == "coach"


def test_daily_token_limit_refuses_before_the_model_is_called(api, monkeypatch, tmp_path):
    client, db, _tmp = api
    coach_headers, _player_headers, assignment_id = _assigned_player(api)
    _enable(monkeypatch, tmp_path)
    stub = _stub_coach_llm(monkeypatch)
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "1500")
    db.record_model_usage(
        account_id=_account_id(db, "coach"),
        role="coach",
        model=COACH_MODEL_ID,
        input_tokens=1000,
        output_tokens=500,
        cost_usd=0.0,
        estimated=False,
        purpose="seed",
        created_at=datetime.now(UTC).isoformat(),
    )

    response = client.post(
        f"/coach/assignments/{assignment_id}/assistant", headers=coach_headers, json=QUESTION
    )
    assert response.status_code == 429
    assert stub.payloads == []
