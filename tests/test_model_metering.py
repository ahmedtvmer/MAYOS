"""Model metering, per-account limits, spend alerts, and owner reporting (#39, ADR 038).

No network or real model: every HTTP path is driven with a LangChain chat model
double that emits usage metadata and fires the same metering callback the cloud
and local builders attach. The catalog ledger is a temporary SQLite file.
"""

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent import assistant_graph
from agent import onboarding_graph as onboarding_module
from agent import program_rules
from agent.program_rules import get_default_split, resolve_split
from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import coach_programs as coach_programs_service
from service import model_metering as metering_service
from service.model_limits import ModelLimitExceeded, admit_model_request, reset_model_limits
from svc.app import create_app
from svc.dependencies import get_db
from svc.llm import InferenceScope, run_inference_sync
from tests.fakes.chat_model import ScriptedChatModel
from utils import model_metering as utils_metering
from utils.model_metering import MeteringCallback

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
CHAT_MESSAGE = "How should I cue my bench?"


def _fake_model(
    model_id: str = "Qwen/Qwen3.5-9B",
    *,
    input_tokens: int = 120,
    output_tokens: int = 30,
    emit_usage: bool = True,
    finish_reason: str | None = None,
) -> ScriptedChatModel:
    usage_metadata = (
        {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        if emit_usage
        else None
    )
    return ScriptedChatModel(
        ["Keep the elbows tucked."],
        default_turn="Keep the elbows tucked.",
        model_name=model_id,
        usage_metadata=usage_metadata,
        emit_usage=emit_usage,
        finish_reason=finish_reason,
        callbacks=[MeteringCallback(model_id)],
    )


@pytest.fixture(autouse=True)
def _register_metering_recorder():
    """The suite registers the sink explicitly (utils never imports service)."""
    utils_metering.set_recorder(metering_service.record_model_usage)
    reset_model_limits()
    yield
    utils_metering.set_recorder(metering_service.record_model_usage)
    reset_model_limits()


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
    with TestClient(app) as client:
        yield client, db
    if db.ledger_conn is not None:
        db.ledger_conn.close()
    db.catalog_conn.close()


def _register(client, username: str, password: str = "correct-horse-1") -> str:
    resp = client.post("/auth/register", json={"trainee_id": username, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _authed(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _account_id(db, username: str) -> str:
    account = db.get_active_account_by_username(username)
    assert account is not None
    return account["account_id"]


def _usage_rows(db, account_id: str) -> list[dict[str, Any]]:
    return [row for row in db.summarize_model_usage("2000-01-01") if row["account_id"] == account_id]


def _simple_program():
    from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema

    return GeneratedProgramSchema(
        program_name="Metered test program",
        split_type="Full Body",
        weekly_frequency=1,
        days=[
            ProgramDaySchema(
                day_name="Full A",
                day_order=1,
                exercises=[
                    ProgramExerciseSchema(
                        exercise_id=exercise_id,
                        exercise_name=name,
                        target_reps_min=5,
                        target_reps_max=8,
                    )
                    for exercise_id, name in (("sq", "Squat"), ("bp", "Bench Press"), ("row", "Row"))
                ],
            )
        ],
    )


def _assert_ai_usage_event(sink, db, account_id: str, use_case: str, calls: int) -> None:
    events = [event for event in sink.events if event["event"] == "ai_request_completed"]
    assert len(events) == 1
    properties = events[0]["properties"]
    with db.catalog_locked() as catalog:
        turn_id = catalog.execute(
            "SELECT turn_id FROM model_usage WHERE account_id = ? AND turn_id IS NOT NULL"
            " ORDER BY created_at DESC LIMIT 1",
            (account_id,),
        ).fetchone()[0]
    rows = db.model_usage_rows_for_turn(turn_id, account_id)
    usage = {
        "calls": len(rows),
        "input_tokens": sum(row["input_tokens"] for row in rows),
        "output_tokens": sum(row["output_tokens"] for row in rows),
        "cost_usd": sum(row["cost_usd"] for row in rows),
    }
    assert properties["use_case"] == use_case
    assert properties["plan"] in {"free", "pro"}
    assert properties["input_tokens"] == usage["input_tokens"]
    assert properties["output_tokens"] == usage["output_tokens"]
    assert properties["tokens"] == usage["input_tokens"] + usage["output_tokens"]
    if use_case == "checkpoint_review":
        assert properties["tokens_today"] == 0
        assert properties["turns_today"] == 0
    else:
        assert properties["tokens_today"] >= properties["tokens"]
        assert properties["turns_today"] >= 1
    assert properties["tokens_daily_limit"] >= 0
    assert properties["requests_per_minute_limit"] >= 0
    assert properties["cost_usd"] == pytest.approx(usage["cost_usd"])
    assert properties["model_count"] == 1
    assert properties["models"] == [events[0]["properties"]["models"][0]]
    assert usage["calls"] == calls
    assert all(row["turn_id"] == rows[0]["turn_id"] for row in rows)
    assert "prompt" not in repr(events[0]).lower()
    assert "response" not in repr(events[0]).lower()


def _post_chat(client, token: str):
    return client.post("/chat/messages", headers=_authed(token), json={"content": CHAT_MESSAGE})


def _make_coach(client, db, username: str, capacity: int = 5) -> dict[str, str]:
    token = _register(client, username)
    headers = _authed(token)
    issued = coach_service.issue_coach_invite(db, username, actor="cli")
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


def _assigned_player(client, db, player: str = "player1"):
    coach_headers = _make_coach(client, db, "coach")
    invite = client.post("/coach/assignments/invites", headers=coach_headers).json()
    player_token = _register(client, player)
    player_headers = _authed(player_token)
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


# --------------------------------------------------------------------------
# AC1: metering by immutable account id and model
# --------------------------------------------------------------------------


def test_chat_streamed_call_is_metered(api, monkeypatch, recording_analytics):
    client, db = api
    token = _register(client, "player1")
    monkeypatch.setattr(assistant_graph, "llm", _fake_model("Qwen/Qwen3.5-9B", finish_reason="stop"))

    resp = _post_chat(client, token)
    assert resp.status_code == 200, resp.text

    rows = _usage_rows(db, _account_id(db, "player1"))
    assert len(rows) == 1
    assert rows[0]["role"] == "player"
    assert rows[0]["model"] == "Qwen/Qwen3.5-9B"
    assert rows[0]["requests"] == 1
    assert rows[0]["input_tokens"] == 120 and rows[0]["output_tokens"] == 30
    assert rows[0]["estimated_calls"] == 0
    _assert_ai_usage_event(recording_analytics, db, _account_id(db, "player1"), "chat", 1)
    ai_event = next(event for event in recording_analytics.events if event["event"] == "ai_request_completed")
    assert ai_event["properties"]["finish_reason"] == "stop"


def test_multicall_chat_turn_emits_one_metered_event(api, monkeypatch, recording_analytics):
    client, db = api
    token = _register(client, "player1")
    account_id = _account_id(db, "player1")
    fake = _fake_model()

    def fake_turn(state, **_kwargs):
        fake.invoke("first")
        fake.invoke("second")
        state["response_content"] = "answer"
        yield "answer"

    monkeypatch.setattr("svc.routers.chat.stream_assistant_turn", fake_turn)
    response = _post_chat(client, token)
    assert response.status_code == 200, response.text

    rows = _usage_rows(db, account_id)
    assert len(rows) == 1
    assert rows[0]["requests"] == 2
    _assert_ai_usage_event(recording_analytics, db, account_id, "chat", 2)


def test_resolve_split_meters_only_model_path_through_injected_inference(api, monkeypatch):
    _client, db = api
    _assigned_player(_client, db)
    account_id = _account_id(db, "coach")
    fake = _fake_model("deepseek-ai/DeepSeek-V4-Flash")
    fake.reset([get_default_split(3)])
    monkeypatch.setattr(program_rules, "llm", fake)

    scope = InferenceScope(
        account_id=account_id,
        role="coach",
        purpose="coach_generate_draft",
        store=db,
    )

    def injected_inference(function, *args, **kwargs):
        return run_inference_sync(function, *args, scope=scope, **kwargs)

    custom = resolve_split(
        3,
        preference="custom glute emphasis across the week",
        inference_call=injected_inference,
    )
    assert len(custom.days) == 3
    rows = _usage_rows(db, account_id)
    assert len(rows) == 1
    assert rows[0]["role"] == "coach"
    assert rows[0]["requests"] == 1
    assert rows[0]["input_tokens"] == 120
    with db.catalog_locked() as catalog:
        purposes = catalog.execute(
            "SELECT purpose FROM model_usage WHERE account_id = ?",
            (account_id,),
        ).fetchall()
    assert [row[0] for row in purposes] == ["coach_generate_draft"]

    deterministic = resolve_split(3, preference="ppl", inference_call=injected_inference)
    assert len(deterministic.days) == 3
    assert _usage_rows(db, account_id)[0]["requests"] == 1
    assert len(fake.calls) == 1
    assert fake.calls[0]["mode"] == "structured"


def test_onboarding_step_is_metered(api, monkeypatch, recording_analytics):
    client, db = api
    token = _register(client, "player1")
    fake = _fake_model()

    class _FakeGraph:
        def invoke(self, state, **kwargs):
            fake.invoke("intake")
            messages = list(state.get("messages", [])) + [AIMessage(content="Q1?")]
            return {
                "messages": messages,
                "trainee_id": state.get("trainee_id"),
                "intake_step": 1,
                "is_complete": False,
                "profile_data": None,
            }

    monkeypatch.setattr(onboarding_module, "onboarding_graph", _FakeGraph())

    resp = client.post("/onboarding/step", headers=_authed(token), json={"content": "25"})
    assert resp.status_code == 200, resp.text

    rows = _usage_rows(db, _account_id(db, "player1"))
    assert rows and rows[0]["role"] == "player"
    assert rows[0]["requests"] >= 1
    assert rows[0]["input_tokens"] > 0
    _assert_ai_usage_event(recording_analytics, db, _account_id(db, "player1"), "onboarding", 2)


def test_program_generation_emits_metered_ai_event(api, monkeypatch, recording_analytics):
    from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema

    client, db = api
    token = _register(client, "player1")
    account_id = _account_id(db, "player1")
    fake = _fake_model("Qwen/Qwen3.5-9B")
    program = GeneratedProgramSchema(
        program_name="Stub",
        split_type="Full Body",
        weekly_frequency=1,
        days=[
            ProgramDaySchema(
                day_name="Full A",
                day_order=1,
                exercises=[
                    ProgramExerciseSchema(
                        exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8
                    ),
                    ProgramExerciseSchema(
                        exercise_id="bp", exercise_name="Bench Press", target_reps_min=5, target_reps_max=8
                    ),
                    ProgramExerciseSchema(
                        exercise_id="row", exercise_name="Row", target_reps_min=8, target_reps_max=12
                    ),
                ],
            )
        ],
    )

    def generate_program(*, ledger, **_kwargs):
        fake.invoke("program generation")
        ledger.save_training_program(program.model_dump())
        return program, ""

    monkeypatch.setattr("service.programs.generate_program_pipeline", generate_program)
    response = client.post("/programs/generate", headers=_authed(token), json={})
    assert response.status_code == 200, response.text
    _assert_ai_usage_event(recording_analytics, db, account_id, "program_generate", 1)


def test_program_generation_provider_error_emits_after_error_response(api, monkeypatch, recording_analytics):
    from utils.model_metering import record_usage

    client, db = api
    token = _register(client, "player1")
    account_id = _account_id(db, "player1")

    def fail_generation(*_args, **_kwargs):
        record_usage("deepseek-ai/DeepSeek-V4-Flash", 27, 9, False)
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("service.programs.generate_program_pipeline", fail_generation)
    with TestClient(client.app, raise_server_exceptions=False) as error_client:
        response = error_client.post("/programs/generate", headers=_authed(token), json={})
    assert response.status_code == 502, response.text
    _assert_ai_usage_event(recording_analytics, db, account_id, "program_generate", 1)
    event = next(item for item in recording_analytics.events if item["event"] == "ai_request_completed")
    assert event["properties"]["outcome"] == "error"


def test_program_generation_limit_refusal_emits_limit_without_completion(api, monkeypatch, recording_analytics):
    from service.model_limits import reset_model_limits
    from utils.model_metering import record_usage

    client, db = api
    token = _register(client, "player1")
    program = _simple_program()

    def generate(*_args, ledger, **_kwargs):
        record_usage("deepseek-ai/DeepSeek-V4-Flash", 27, 9, False)
        ledger.save_training_program(program.model_dump())
        return program, ""

    monkeypatch.setattr("service.programs.generate_program_pipeline", generate)
    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "1")
    reset_model_limits()
    try:
        first = client.post("/programs/generate", headers=_authed(token), json={})
        refused = client.post("/programs/generate", headers=_authed(token), json={})
    finally:
        reset_model_limits()

    assert first.status_code == 200, first.text
    assert refused.status_code == 429, refused.text
    completed = [event for event in recording_analytics.events if event["event"] == "ai_request_completed"]
    limited = [event for event in recording_analytics.events if event["event"] == "ai_request_limited"]
    assert len(completed) == 1
    assert len(limited) == 1
    assert limited[0]["properties"]["limit"] == "requests_per_minute"


def test_coach_generate_draft_is_metered(api, monkeypatch, recording_analytics):
    from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema

    client, db = api
    coach_headers, _player_headers, assignment_id = _assigned_player(client, db)
    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "1")
    coach_account_id = _account_id(db, "coach")
    db.set_plan(coach_account_id, "coach", "pro")
    fake = _fake_model("deepseek-ai/DeepSeek-V4-Flash")

    def _stub_program() -> GeneratedProgramSchema:
        return GeneratedProgramSchema(
            program_name="Stub",
            split_type="Full Body",
            weekly_frequency=1,
            days=[
                ProgramDaySchema(
                    day_name="Full A",
                    day_order=1,
                    exercises=[
                        ProgramExerciseSchema(exercise_id="sq", exercise_name="Squat", target_reps_min=5, target_reps_max=8),
                        ProgramExerciseSchema(
                            exercise_id="bp", exercise_name="Bench Press", target_reps_min=5, target_reps_max=8
                        ),
                        ProgramExerciseSchema(exercise_id="row", exercise_name="Row", target_reps_min=5, target_reps_max=8),
                    ],
                )
            ],
        )

    def _wrapped(request, *, inference_call, ledger):
        if request.user_split_override == "glute focus":
            inference_call(lambda: fake.invoke("coach program"))
        program = _stub_program()
        return program, ""

    monkeypatch.setattr(coach_programs_service, "generate_program_draft_pipeline", _wrapped)

    deterministic = client.post(
        f"/coach/assignments/{assignment_id}/program-draft/generate",
        headers=coach_headers,
        json={},
    )
    assert deterministic.status_code == 200, deterministic.text
    assert _usage_rows(db, _account_id(db, "coach")) == []
    empty_turns = [event for event in recording_analytics.events if event["event"] == "ai_request_completed"]
    assert len(empty_turns) == 1
    assert empty_turns[0]["properties"]["use_case"] == "coach_generate_draft"
    assert empty_turns[0]["properties"]["tokens"] == 0
    recording_analytics.events.clear()

    model_backed = client.post(
        f"/coach/assignments/{assignment_id}/program-draft/generate",
        headers=coach_headers,
        json={"user_split_override": "glute focus"},
        params={"replace": "true"},
    )
    assert model_backed.status_code == 200, model_backed.text

    coach_account_id = _account_id(db, "coach")
    rows = _usage_rows(db, coach_account_id)
    assert rows and rows[0]["role"] == "coach"
    assert rows[0]["model"] == "deepseek-ai/DeepSeek-V4-Flash"
    with db.catalog_locked() as catalog:
        purposes = catalog.execute(
            "SELECT purpose FROM model_usage WHERE account_id = ? ORDER BY created_at",
            (coach_account_id,),
        ).fetchall()
    assert [row[0] for row in purposes] == ["coach_generate_draft"]

    refused = client.post(
        f"/coach/assignments/{assignment_id}/program-draft/generate",
        headers=coach_headers,
        json={"user_split_override": "glute focus"},
        params={"replace": "true"},
    )
    assert refused.status_code == 429
    assert refused.json() == {"detail": "Too many AI requests. Please wait a minute and try again."}
    _assert_ai_usage_event(recording_analytics, db, coach_account_id, "coach_generate_draft", 1)
    event = next(item for item in recording_analytics.events if item["event"] == "ai_request_completed")
    assert event["properties"]["plan"] == "pro"
    limited = [event for event in recording_analytics.events if event["event"] == "ai_request_limited"]
    assert len(limited) == 1
    assert limited[0]["properties"]["limit"] == "requests_per_minute"
    assert len([event for event in recording_analytics.events if event["event"] == "ai_request_completed"]) == 1


def test_profile_rebuild_emits_its_metered_turn_after_api_write(api, monkeypatch, recording_analytics):
    from utils.model_metering import record_usage

    client, db = api
    token = _register(client, "player1")
    account_id = _account_id(db, "player1")
    program = _simple_program()
    with db.open_ledger("player1") as ledger:
        ledger.upsert_player_profile(
            {"weekly_frequency": 2, "equipment_access": "Commercial gym", "rep_preference": "balanced"}
        )
        ledger.save_training_program(program.model_dump())

    def rebuild(_request, *, ledger, **_kwargs):
        record_usage("deepseek-ai/DeepSeek-V4-Flash", 31, 11, False)
        return program, ""

    monkeypatch.setattr("service.profile.generate_program_draft_pipeline", rebuild)
    response = client.put("/profile", headers=_authed(token), json={"weekly_frequency": 3})
    assert response.status_code == 200, response.text
    _assert_ai_usage_event(recording_analytics, db, account_id, "profile_rebuild", 1)


def test_rolled_back_profile_rebuild_keeps_metering_and_emits_completion(api, monkeypatch, recording_analytics):
    from utils.model_metering import record_usage

    client, db = api
    token = _register(client, "player1")
    account_id = _account_id(db, "player1")
    program = _simple_program()
    with db.open_ledger("player1") as ledger:
        ledger.upsert_player_profile(
            {"weekly_frequency": 2, "equipment_access": "Commercial gym", "rep_preference": "balanced"}
        )
        ledger.save_training_program(program.model_dump())
        prior_program = ledger.get_active_program()

    def rebuild(_request, **_kwargs):
        record_usage("deepseek-ai/DeepSeek-V4-Flash", 31, 11, False)
        return program.model_copy(update={"program_name": "Uncommitted"}), ""

    monkeypatch.setattr("service.profile.generate_program_draft_pipeline", rebuild)
    from database.ledger.handle import TrainingLedger

    save_training_program = TrainingLedger.save_training_program

    def fail_after_program_write(self, *args, **kwargs):
        save_training_program(self, *args, **kwargs)
        raise RuntimeError("profile rebuild interrupted")

    monkeypatch.setattr(TrainingLedger, "save_training_program", fail_after_program_write)
    with TestClient(client.app, raise_server_exceptions=False) as error_client:
        response = error_client.put("/profile", headers=_authed(token), json={"weekly_frequency": 3})

    assert response.status_code == 502, response.text
    _assert_ai_usage_event(recording_analytics, db, account_id, "profile_rebuild", 1)
    event = next(item for item in recording_analytics.events if item["event"] == "ai_request_completed")
    assert event["properties"]["outcome"] == "error"
    with db.open_ledger("player1") as ledger:
        assert ledger.get_active_program().version == prior_program.version


def test_later_limit_refusal_keeps_completion_for_earlier_metered_call(api, monkeypatch, recording_analytics):
    from svc.llm import InferenceScope, inference_turn, run_inference_sync

    client, db = api
    _register(client, "player1")
    account_id = _account_id(db, "player1")
    scope = InferenceScope(account_id=account_id, role="player", purpose="chat", store=db)
    fake = _fake_model()
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "100")
    reset_model_limits()
    try:
        with pytest.raises(ModelLimitExceeded):
            with inference_turn(scope):
                run_inference_sync(lambda: fake.invoke("first call"), scope=scope)
                run_inference_sync(lambda: fake.invoke("refused later call"), scope=scope)
    finally:
        reset_model_limits()

    rows = _usage_rows(db, account_id)
    assert len(rows) == 1
    completed = [event for event in recording_analytics.events if event["event"] == "ai_request_completed"]
    limited = [event for event in recording_analytics.events if event["event"] == "ai_request_limited"]
    assert len(completed) == 1
    assert completed[0]["properties"]["outcome"] == "error"
    assert completed[0]["properties"]["tokens"] == 150
    assert len(limited) == 1
    assert limited[0]["properties"]["limit"] == "daily_tokens"


def test_exception_mid_turn_keeps_earlier_call_rows_and_one_completion(api, recording_analytics):
    from svc.llm import InferenceScope, inference_turn, run_inference_sync

    client, db = api
    _register(client, "player1")
    account_id = _account_id(db, "player1")
    scope = InferenceScope(account_id=account_id, role="player", purpose="chat", store=db)
    fake = _fake_model()

    with pytest.raises(RuntimeError, match="simulated worker crash"):
        with inference_turn(scope):
            run_inference_sync(lambda: fake.invoke("first call"), scope=scope)
            run_inference_sync(lambda: fake.invoke("second call"), scope=scope)
            raise RuntimeError("simulated worker crash")

    rows = _usage_rows(db, account_id)
    assert len(rows) == 1
    assert rows[0]["requests"] == 2
    completed = [event for event in recording_analytics.events if event["event"] == "ai_request_completed"]
    assert len(completed) == 1
    assert completed[0]["properties"]["outcome"] == "error"


def test_coach_ai_analysis_emits_metered_turn_after_http_answer(api, monkeypatch, recording_analytics):
    from utils.model_metering import record_usage

    client, db = api
    coach_headers, _player_headers, assignment_id = _assigned_player(client, db)
    coach_account_id = _account_id(db, "coach")
    monkeypatch.setattr("service.coach_ai.coach_ai_enabled", lambda: True)

    def invoke(_messages):
        record_usage("deepseek-ai/DeepSeek-V4-Flash", 29, 9, False)
        return "Keep the same training load."

    monkeypatch.setattr("service.coach_ai._invoke_coach_model", invoke)
    response = client.post(
        f"/coach/assignments/{assignment_id}/assistant",
        headers=coach_headers,
        json={"question": "How has training changed?"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"answer": "Keep the same training load."}
    _assert_ai_usage_event(recording_analytics, db, coach_account_id, "coach_assistant", 1)


def test_checkpoint_review_ai_emits_metered_turn_after_review_is_stored(api, monkeypatch, recording_analytics):
    import json as json_module

    from utils.model_metering import record_usage

    client, db = api
    token = _register(client, "player1")
    account_id = _account_id(db, "player1")
    now = datetime.now(UTC).isoformat()
    facts = {
        "workouts_in_period": 10,
        "weeks_met": 4,
        "weeks_counted": 5,
        "personal_records": 2,
        "regressed_exercises": 1,
        "volume_first_half": 4200.0,
        "volume_second_half": 4500.0,
    }
    rating = [
        {"part": "Consistency", "label": "Steady"},
        {"part": "Progression", "label": "Strong"},
        {"part": "Volume trend", "label": "Rising"},
    ]
    with db.open_ledger("player1") as ledger:
        ledger.log_workout_session(
            session_id="review-session",
            session_date="2026-09-01",
            split_name="Full body",
            started_at=now,
            completed_at=now,
        )
        ledger.conn.execute(
            "INSERT INTO checkpoint_reviews "
            "(checkpoint, session_id, period_start, period_end, facts_json, rating_json, created_at, opened_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
            (10, "review-session", "2026-08-01", "2026-09-01", json_module.dumps(facts), json_module.dumps(rating), now),
        )
        ledger.commit_ledger()

    monkeypatch.setattr("service.checkpoint_review_ai.checkpoint_review_ai_enabled", lambda: True)

    def invoke(_messages):
        record_usage("deepseek-ai/DeepSeek-V4-Flash", 37, 13, False)
        return "Consistency remained steady."

    monkeypatch.setattr("service.checkpoint_review_ai._invoke_player_model", invoke)
    response = client.get("/checkpoint-reviews/10", headers=_authed(token))
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "Consistency remained steady."
    with db.open_ledger("player1") as ledger:
        assert ledger.get_checkpoint_review_row(10)["text"] == "Consistency remained steady."
    _assert_ai_usage_event(recording_analytics, db, account_id, "checkpoint_review", 1)


def test_coach_program_request_apply_emits_one_metered_turn(api, monkeypatch, recording_analytics):
    from utils.model_metering import record_usage

    client, db = api
    coach_headers, player_headers, assignment_id = _assigned_player(client, db)
    coach_account_id = _account_id(db, "coach")
    player_program = _simple_program()
    with db.open_ledger("player1") as ledger:
        ledger.save_training_program(
            player_program.model_dump(),
            published_by_coach_account_id=coach_account_id,
        )

    created = client.post(
        "/assignments/me/program-requests",
        headers=player_headers,
        json={"kind": "split_change", "desired_weekly_frequency": 3, "reason": "Change the split"},
    )
    assert created.status_code == 200, created.text

    def apply(*_args, ledger, **_kwargs):
        record_usage("deepseek-ai/DeepSeek-V4-Flash", 41, 15, False)
        ledger.save_training_program(player_program.model_copy(update={"weekly_frequency": 3}).model_dump(),
                                     published_by_coach_account_id=coach_account_id)
        return player_program, ""

    monkeypatch.setattr("service.program_requests.generate_program_pipeline", apply)
    applied = client.post(
        f"/coach/assignments/{assignment_id}/program-requests/{created.json()['request_id']}/apply",
        headers=coach_headers,
    )
    assert applied.status_code == 200, applied.text
    _assert_ai_usage_event(recording_analytics, db, coach_account_id, "coach_program_request", 1)


def test_cost_computed_from_pricing_json(api, monkeypatch):
    client, db = api
    _register(client, "player1")
    account_id = _account_id(db, "player1")
    monkeypatch.setenv("MODEL_PRICING_JSON", json.dumps({"test-model": {"input": 1.0, "output": 2.0}}))
    fake = _fake_model("test-model", input_tokens=1_000_000, output_tokens=500_000)

    run_inference_sync(lambda: fake.invoke("x"), scope=InferenceScope(account_id=account_id, role="player", purpose="pricing", store=db))

    rows = _usage_rows(db, account_id)
    assert rows[0]["model"] == "test-model"
    assert rows[0]["cost_usd"] == pytest.approx(2.0)
    assert db.catalog_conn.execute(
        "SELECT turn_id FROM model_usage WHERE account_id = ?", (account_id,)
    ).fetchone()[0] is None


def test_unknown_model_cost_is_zero():
    from utils.model_pricing import compute_cost

    assert compute_cost("nobody/unknown-model", 1_000_000, 1_000_000) == 0.0
    assert compute_cost("Qwen/Qwen3.5-9B", 1_000_000, 1_000_000) == pytest.approx(0.25)
    assert compute_cost("Qwen/Qwen3.5-27B", 1_000_000, 1_000_000) == pytest.approx(2.86)
    assert compute_cost("deepseek-ai/DeepSeek-V4-Flash", 1_000_000, 1_000_000) == pytest.approx(0.27)


def test_missing_provider_usage_is_flagged_estimated(api):
    client, db = api
    _register(client, "player1")
    account_id = _account_id(db, "player1")
    fake = _fake_model(emit_usage=False)

    run_inference_sync(
        lambda: fake.invoke("a reasonably long prompt"),
        scope=InferenceScope(account_id=account_id, role="player", purpose="est", store=db),
    )

    rows = _usage_rows(db, account_id)
    assert rows[0]["estimated_calls"] == 1
    assert rows[0]["input_tokens"] > 0 and rows[0]["output_tokens"] > 0


def test_metering_failure_does_not_break_a_turn(api, monkeypatch):
    client, db = api
    token = _register(client, "player1")
    monkeypatch.setattr(assistant_graph, "llm", _fake_model())

    def _boom(**kwargs):
        raise RuntimeError("metering backend down")

    utils_metering.set_recorder(_boom)

    resp = _post_chat(client, token)
    assert resp.status_code == 200
    assert "data:" in resp.text
    assert _usage_rows(db, _account_id(db, "player1")) == []


# --------------------------------------------------------------------------
# AC2: per-account model rate limits (no streaming bypass)
# --------------------------------------------------------------------------


def test_streamed_request_limit_refuses_with_429(api, monkeypatch):
    client, db = api
    token = _register(client, "player1")
    account_id = _account_id(db, "player1")
    monkeypatch.setattr(assistant_graph, "llm", _fake_model())
    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "2")
    reset_model_limits()

    assert _post_chat(client, token).status_code == 200
    assert _post_chat(client, token).status_code == 200
    refused = _post_chat(client, token)
    assert refused.status_code == 429
    assert refused.json()["detail"]
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    assert db.count_model_limit_hits(account_id, month_start.isoformat())["rate"] == 1


def test_non_streamed_path_shares_the_account_limit(api, monkeypatch):
    client, _db = api
    token = _register(client, "player1")
    monkeypatch.setattr(assistant_graph, "llm", _fake_model())
    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "1")
    reset_model_limits()

    assert _post_chat(client, token).status_code == 200
    onboarding = client.post("/onboarding/step", headers=_authed(token), json={"content": "25"})
    assert onboarding.status_code == 429


def test_limits_are_per_account(api, monkeypatch):
    client, _db = api
    token_a = _register(client, "player1")
    token_b = _register(client, "player2")
    monkeypatch.setattr(assistant_graph, "llm", _fake_model())
    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "1")
    reset_model_limits()

    assert _post_chat(client, token_a).status_code == 200
    assert _post_chat(client, token_a).status_code == 429
    assert _post_chat(client, token_b).status_code == 200


def test_same_account_two_tokens_share_one_limit(api, monkeypatch):
    client, _db = api
    _register(client, "player1")
    token_one = client.post(
        "/auth/login", json={"trainee_id": "player1", "password": "correct-horse-1"}
    ).json()["access_token"]
    token_two = client.post(
        "/auth/login", json={"trainee_id": "player1", "password": "correct-horse-1"}
    ).json()["access_token"]
    assert token_one != token_two
    monkeypatch.setattr(assistant_graph, "llm", _fake_model())
    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "1")
    reset_model_limits()

    assert _post_chat(client, token_one).status_code == 200
    assert _post_chat(client, token_two).status_code == 429


def test_daily_token_limit_refuses_the_next_turn(api, monkeypatch):
    client, db = api
    token = _register(client, "player1")
    account_id = _account_id(db, "player1")
    monkeypatch.setattr(assistant_graph, "llm", _fake_model(input_tokens=100, output_tokens=50))
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "100")
    reset_model_limits()

    assert _post_chat(client, token).status_code == 200  # records 150 tokens
    refused = _post_chat(client, token)
    assert refused.status_code == 429
    assert "daily" in refused.json()["detail"].lower()
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    assert db.count_model_limit_hits(account_id, month_start.isoformat())["daily_tokens"] == 1


def test_limit_hit_recording_failure_keeps_the_refusal_as_429(api, monkeypatch):
    client, db = api
    token = _register(client, "player1")
    monkeypatch.setattr(assistant_graph, "llm", _fake_model())
    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "0")
    reset_model_limits()
    assert _post_chat(client, token).status_code == 200

    def fail_record(*args, **kwargs):
        raise OSError("catalog unavailable")

    monkeypatch.setattr(db, "record_model_limit_hit", fail_record)
    assert _post_chat(client, token).status_code == 429


def test_model_limit_hits_are_counted_by_kind_and_pruned_after_400_days(api, monkeypatch):
    _client, db = api
    account_id = db.create_account("limitowner")
    assert account_id
    now = datetime.now(UTC)
    old = now - timedelta(days=401)
    db.record_model_limit_hit(account_id, "rate", created_at=old.isoformat())
    db.record_model_limit_hit(account_id, "rate", created_at=(now - timedelta(days=2)).isoformat())
    db.record_model_limit_hit(account_id, "daily_tokens", created_at=(now - timedelta(days=1)).isoformat())

    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "0")
    reset_model_limits()
    admit_model_request(account_id, guard=False, db=db)
    with pytest.raises(ModelLimitExceeded):
        admit_model_request(account_id, guard=False, db=db)

    assert db.count_model_limit_hits(account_id, "0001-01-01T00:00:00+00:00") == {
        "rate": 2,
        "daily_tokens": 1,
    }


def test_account_usage_totals_sums_only_the_selected_account_and_window(api):
    _client, db = api
    account_id = db.create_account("usageowner")
    other_account_id = db.create_account("otherusage")
    assert account_id and other_account_id
    now = datetime.now(UTC)
    first = now - timedelta(days=2)
    second = now - timedelta(days=1)
    db.record_model_usage(account_id, "player", "model-a", 10, 5, 0.25, False, created_at=first.isoformat())
    db.record_model_usage(account_id, "player", "model-b", 20, 7, 0.50, False, created_at=second.isoformat())
    db.record_model_usage(other_account_id, "player", "model-a", 100, 50, 5.0, False, created_at=second.isoformat())

    totals = metering_service.account_usage_totals(db, account_id)
    recent = metering_service.account_usage_totals(db, account_id, second.isoformat())

    assert totals == {"calls": 2, "input_tokens": 30, "output_tokens": 12, "tokens": 42, "cost_usd": 0.75}
    assert recent == {"calls": 1, "input_tokens": 20, "output_tokens": 7, "tokens": 27, "cost_usd": 0.5}


def test_concurrent_admits_are_capped(api, monkeypatch):
    client, db = api
    _register(client, "player1")
    account_id = _account_id(db, "player1")
    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "3")
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "0")
    reset_model_limits()

    admitted: list[bool] = []
    barrier = threading.Barrier(12)
    lock = threading.Lock()

    def worker():
        barrier.wait()
        try:
            admit_model_request(account_id, guard=False, db=db)
            outcome = True
        except ModelLimitExceeded:
            outcome = False
        with lock:
            admitted.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert sum(admitted) == 3  # exactly the limit, never more


def test_admission_guard_resets_when_the_scope_exits(api, monkeypatch):
    client, db = api
    _register(client, "player1")
    account_id = _account_id(db, "player1")
    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "0")

    def noop():
        return None

    # First scope consumes the one slot and then releases its guard token.
    run_inference_sync(noop, scope=InferenceScope(account_id=account_id, role="player", purpose="one", store=db))
    # Same reusable context, same account: the limit must be enforced again.
    with pytest.raises(ModelLimitExceeded):
        run_inference_sync(noop, scope=InferenceScope(account_id=account_id, role="player", purpose="two", store=db))


def test_attributed_admission_without_a_store_fails_closed():
    """An attributed request with no store must raise, not silently skip the limit."""
    with pytest.raises(RuntimeError, match="no store"):
        admit_model_request("player-1", guard=False, db=None)


def test_attributed_metering_without_a_store_fails_closed():
    """An attributed model call with no store must raise, not drop the usage row."""
    with pytest.raises(RuntimeError, match="no store"):
        metering_service.record_model_usage(
            store=None,
            account_id="player-1",
            role="player",
            purpose="test",
            model="Qwen/Qwen3.5-9B",
            input_tokens=10,
            output_tokens=5,
            estimated=False,
        )


def test_unattributed_calls_still_noop_without_a_store():
    """Startup/eval calls carry no account; they are dropped, never rejected."""
    assert admit_model_request(None, guard=False, db=None) is None
    assert (
        metering_service.record_model_usage(
            store=None,
            account_id=None,
            role="unknown",
            purpose=None,
            model="Qwen/Qwen3.5-9B",
            input_tokens=10,
            output_tokens=5,
            estimated=False,
        )
        is None
    )


# --------------------------------------------------------------------------
# AC3: projected spend alert and owner report
# --------------------------------------------------------------------------


def _seed_usage(db, account_id, role, model, cost, when):
    db.record_model_usage(
        account_id=account_id,
        role=role,
        model=model,
        input_tokens=1000,
        output_tokens=500,
        cost_usd=cost,
        estimated=False,
        purpose="seed",
        created_at=when.isoformat(),
    )


def test_projected_spend_fires_once_per_month(api, monkeypatch):
    _client, db = api
    sent: list[tuple] = []
    monkeypatch.setenv("MODEL_SPEND_ALERT_USD", "50")
    monkeypatch.setenv("OWNER_ALERT_EMAIL", "owner@example.com")
    monkeypatch.setattr(
        metering_service, "send_model_spend_alert_email", lambda *args, **kwargs: sent.append(args) or True
    )
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    _seed_usage(db, "acct-a", "player", "Qwen/Qwen3.5-9B", 30.0, datetime(2026, 9, 5, tzinfo=UTC))

    first = metering_service.evaluate_spend_alert(db, now=now)
    assert first["fired"] is True
    assert first["notified"] is True
    assert first["projected_usd"] == pytest.approx(30.0 / (14.5 / 30.0), rel=1e-6)

    second = metering_service.evaluate_spend_alert(db, now=now)
    assert second["fired"] is False
    assert second["deduped"] is True
    assert len(sent) == 1


def test_failed_spend_alert_is_retried_then_not_repeated(api, monkeypatch):
    _client, db = api
    attempts: list[tuple] = []
    monkeypatch.setenv("MODEL_SPEND_ALERT_USD", "50")
    monkeypatch.setenv("OWNER_ALERT_EMAIL", "owner@example.com")

    def _sender(*args, **kwargs):
        attempts.append(args)
        return len(attempts) > 1  # fail on the first attempt, succeed on the second

    monkeypatch.setattr(metering_service, "send_model_spend_alert_email", _sender)
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    _seed_usage(db, "acct-a", "player", "Qwen/Qwen3.5-9B", 30.0, datetime(2026, 9, 5, tzinfo=UTC))

    first = metering_service.evaluate_spend_alert(db, now=now)
    assert first["fired"] is True and first["notified"] is False
    assert db.get_model_spend_alert("2026-09")["notified_at"] is None

    second = metering_service.evaluate_spend_alert(db, now=now)
    assert second["retrying"] is True and second["notified"] is True
    assert db.get_model_spend_alert("2026-09")["notified_at"] is not None

    third = metering_service.evaluate_spend_alert(db, now=now)
    assert third["deduped"] is True
    assert len(attempts) == 2


def test_projection_floor_avoids_day_one_blowup(api, monkeypatch):
    _client, db = api
    monkeypatch.setenv("MODEL_SPEND_ALERT_USD", "50")
    monkeypatch.setenv("OWNER_ALERT_EMAIL", "owner@example.com")
    monkeypatch.setattr(metering_service, "send_model_spend_alert_email", lambda *args, **kwargs: True)
    now = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
    _seed_usage(db, "acct-a", "player", "Qwen/Qwen3.5-9B", 4.0, datetime(2026, 9, 1, 5, 0, tzinfo=UTC))

    result = metering_service.evaluate_spend_alert(db, now=now)
    # 4 / 0.1 (floor) = 40 < 50, whereas the raw fraction would project ~480.
    assert result["projected_usd"] == pytest.approx(40.0)
    assert result["fired"] is False


def test_owner_usage_report_totals(api):
    _client, db = api
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    _seed_usage(db, "acct-a", "player", "Qwen/Qwen3.5-9B", 0.5, datetime(2026, 9, 5, tzinfo=UTC))
    _seed_usage(db, "acct-b", "coach", "Qwen/Qwen3.5-27B", 0.9, datetime(2026, 9, 6, tzinfo=UTC))

    report = metering_service.usage_report(db, now=now)
    assert report["total_requests"] == 2
    assert report["total_input_tokens"] == 2000
    assert report["total_output_tokens"] == 1000
    assert report["total_cost_usd"] == pytest.approx(1.4)
    assert report["alert"] is None
    assert {(row["account_id"], row["role"]) for row in report["rows"]} == {
        ("acct-a", "player"),
        ("acct-b", "coach"),
    }


def test_usage_report_includes_alert_status(api):
    _client, db = api
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    _seed_usage(db, "acct-a", "player", "Qwen/Qwen3.5-9B", 30.0, datetime(2026, 9, 5, tzinfo=UTC))
    db.claim_model_spend_alert("2026-09", 60.0, 30.0, datetime(2026, 9, 10, tzinfo=UTC).isoformat())
    db.mark_model_spend_alert_notified("2026-09", datetime(2026, 9, 10, tzinfo=UTC).isoformat())

    report = metering_service.usage_report(db, now=now)
    assert report["alert"]["notified_at"] is not None


def test_read_only_report_and_missing_table(api, tmp_path):
    _client, db = api
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    _seed_usage(db, "acct-a", "player", "Qwen/Qwen3.5-9B", 0.5, datetime(2026, 9, 5, tzinfo=UTC))

    with metering_service.ReadOnlyModelUsageCatalog(db.catalog_path) as reader:
        assert reader.has_usage_table() is True
        report = metering_service.usage_report(reader, now=now)
        assert report["total_requests"] == 1
        assert report["total_cost_usd"] == pytest.approx(0.5)

    empty_catalog = tmp_path / "empty_catalog.db"
    sqlite3.connect(empty_catalog).close()
    with metering_service.ReadOnlyModelUsageCatalog(empty_catalog) as reader:
        assert reader.has_usage_table() is False
        with pytest.raises(metering_service.UsageNotRecordedError):
            metering_service.usage_report(reader)


def test_owner_report_json_respects_account_filter(api, capsys):
    _client, db = api
    _seed_usage(db, "acct-a", "player", "Qwen/Qwen3.5-9B", 0.5, datetime.now(UTC))
    _seed_usage(db, "acct-b", "coach", "Qwen/Qwen3.5-27B", 0.9, datetime.now(UTC))

    from scripts import model_usage_report

    assert model_usage_report.main(["--catalog", str(db.catalog_path), "--account", "acct-a", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["account"] == "acct-a"
    assert payload["total_requests"] == 1
    assert all(row["account_id"] == "acct-a" for row in payload["rows"])


def test_owner_report_script_formatting(capsys):
    from scripts import model_usage_report

    report = {
        "start": "2026-09-01T00:00:00+00:00",
        "end": None,
        "account": None,
        "rows": [
            {
                "account_id": "acct-a",
                "role": "player",
                "model": "Qwen/Qwen3.5-9B",
                "requests": 3,
                "input_tokens": 1000,
                "output_tokens": 500,
                "cost_usd": 0.25,
                "estimated_calls": 0,
            }
        ],
        "total_requests": 3,
        "total_input_tokens": 1000,
        "total_output_tokens": 500,
        "total_cost_usd": 0.25,
        "mtd_actual_usd": 0.25,
        "mtd_projected_usd": 12.5,
        "alert": None,
    }
    model_usage_report._print_report(report)
    out = capsys.readouterr().out
    assert "acct-a" in out
    assert "calls" in out
    assert "Month-to-date actual" in out
    assert "Month-to-date projected" in out
    assert "Current month alert: not fired" in out
