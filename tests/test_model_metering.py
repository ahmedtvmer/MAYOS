"""Model metering, per-account limits, spend alerts, and owner reporting (#39, ADR 038).

No network or real model: every HTTP path is driven with a LangChain chat model
double that emits usage metadata and fires the same metering callback the cloud
and local builders attach. The catalog ledger is a temporary SQLite file.
"""

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableLambda

from agent import assistant_graph
from agent import onboarding_graph as onboarding_module
from database.database_manager import DatabaseManager
from service import coach as coach_service
from service import coach_programs as coach_programs_service
from service import model_metering as metering_service
from service.model_limits import ModelLimitExceeded, admit_model_request, reset_model_limits
from svc.app import create_app
from svc.dependencies import get_db
from svc.llm import InferenceScope, run_inference_sync
from utils import model_metering as utils_metering
from utils.model_metering import MeteringCallback

TEST_JWT_SECRET = "test-secret-key-0123456789abcdef"
CHAT_MESSAGE = "How should I cue my bench?"


class _UsageFakeChatModel(BaseChatModel):
    """A chat model double that emits provider usage and fires callbacks."""

    model_id: str = "Qwen/Qwen3.5-9B"
    reply: str = "Keep the elbows tucked."
    input_tokens: int = 120
    output_tokens: int = 30
    emit_usage: bool = True

    @property
    def _llm_type(self) -> str:
        return "usage-fake"

    def _usage(self) -> dict[str, int] | None:
        if not self.emit_usage:
            return None
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
        }

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        message = AIMessage(content=self.reply, usage_metadata=self._usage())
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
        chunk = ChatGenerationChunk(message=AIMessageChunk(content=self.reply))
        if run_manager:
            run_manager.on_llm_new_token(self.reply, chunk=chunk)
        yield chunk
        if self.emit_usage:
            final = ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=self._usage()))
            if run_manager:
                run_manager.on_llm_new_token("", chunk=final)
            yield final

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        def _call(messages: Any, config: Any = None) -> Any:
            return self.invoke(messages, config)

        return RunnableLambda(_call)


def _fake_model(
    model_id: str = "Qwen/Qwen3.5-9B",
    *,
    input_tokens: int = 120,
    output_tokens: int = 30,
    emit_usage: bool = True,
) -> _UsageFakeChatModel:
    return _UsageFakeChatModel(
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        emit_usage=emit_usage,
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
        users_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
        active_user="bootstrap",
    )
    from database.store import set_store

    set_store(db)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client, db
    if db.user_conn is not None:
        db.user_conn.close()
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


def _post_chat(client, token: str):
    return client.post("/chat/messages", headers=_authed(token), json={"content": CHAT_MESSAGE})


def _make_coach(client, db, username: str, capacity: int = 5) -> dict[str, str]:
    token = _register(client, username)
    headers = _authed(token)
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


def test_chat_streamed_call_is_metered(api, monkeypatch):
    client, db = api
    token = _register(client, "player1")
    monkeypatch.setattr(assistant_graph, "llm", _fake_model("Qwen/Qwen3.5-9B"))

    resp = _post_chat(client, token)
    assert resp.status_code == 200, resp.text

    rows = _usage_rows(db, _account_id(db, "player1"))
    assert len(rows) == 1
    assert rows[0]["role"] == "player"
    assert rows[0]["model"] == "Qwen/Qwen3.5-9B"
    assert rows[0]["requests"] == 1
    assert rows[0]["input_tokens"] == 120 and rows[0]["output_tokens"] == 30
    assert rows[0]["estimated_calls"] == 0


def test_multicall_turn_records_every_call(api):
    client, db = api
    _register(client, "player1")
    account_id = _account_id(db, "player1")
    fake = _fake_model()

    def work():
        fake.invoke("first")
        fake.invoke("second")

    run_inference_sync(work, scope=InferenceScope(account_id=account_id, role="player", purpose="test_multicall"))

    rows = _usage_rows(db, account_id)
    assert len(rows) == 1
    assert rows[0]["requests"] == 2


def test_onboarding_step_is_metered(api, monkeypatch):
    client, db = api
    token = _register(client, "player1")
    fake = _fake_model()

    class _FakeGraph:
        def invoke(self, state):
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


def test_coach_program_publish_is_metered(api, monkeypatch):
    from agent.ProgramState import GeneratedProgramSchema, ProgramDaySchema, ProgramExerciseSchema

    client, db = api
    coach_headers, _player_headers, assignment_id = _assigned_player(client, db)
    fake = _fake_model("Qwen/Qwen3.5-27B")

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

    def _wrapped(*args, **kwargs):
        fake.invoke("coach program")
        program = _stub_program()
        db.save_training_program(
            program.model_dump(),
            published_by_coach_account_id=kwargs.get("published_by_coach_account_id"),
        )
        return program, ""

    monkeypatch.setattr(coach_programs_service, "generate_program_pipeline", _wrapped)

    resp = client.post(
        f"/coach/assignments/{assignment_id}/program", headers=coach_headers, json={}
    )
    assert resp.status_code == 200, resp.text

    rows = _usage_rows(db, _account_id(db, "coach"))
    assert rows and rows[0]["role"] == "coach"
    assert rows[0]["model"] == "Qwen/Qwen3.5-27B"


def test_cost_computed_from_pricing_json(api, monkeypatch):
    client, db = api
    _register(client, "player1")
    account_id = _account_id(db, "player1")
    monkeypatch.setenv("MODEL_PRICING_JSON", json.dumps({"test-model": {"input": 1.0, "output": 2.0}}))
    fake = _fake_model("test-model", input_tokens=1_000_000, output_tokens=500_000)

    run_inference_sync(lambda: fake.invoke("x"), scope=InferenceScope(account_id=account_id, role="player", purpose="pricing"))

    rows = _usage_rows(db, account_id)
    assert rows[0]["model"] == "test-model"
    assert rows[0]["cost_usd"] == pytest.approx(2.0)


def test_unknown_model_cost_is_zero():
    from utils.model_pricing import compute_cost

    assert compute_cost("nobody/unknown-model", 1_000_000, 1_000_000) == 0.0
    assert compute_cost("Qwen/Qwen3.5-9B", 1_000_000, 0) == pytest.approx(0.10)


def test_missing_provider_usage_is_flagged_estimated(api):
    client, db = api
    _register(client, "player1")
    account_id = _account_id(db, "player1")
    fake = _fake_model(emit_usage=False)

    run_inference_sync(
        lambda: fake.invoke("a reasonably long prompt"),
        scope=InferenceScope(account_id=account_id, role="player", purpose="est"),
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
    client, _db = api
    token = _register(client, "player1")
    monkeypatch.setattr(assistant_graph, "llm", _fake_model())
    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "2")
    reset_model_limits()

    assert _post_chat(client, token).status_code == 200
    assert _post_chat(client, token).status_code == 200
    refused = _post_chat(client, token)
    assert refused.status_code == 429
    assert refused.json()["detail"]


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
    client, _db = api
    token = _register(client, "player1")
    monkeypatch.setattr(assistant_graph, "llm", _fake_model(input_tokens=100, output_tokens=50))
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "100")
    reset_model_limits()

    assert _post_chat(client, token).status_code == 200  # records 150 tokens
    refused = _post_chat(client, token)
    assert refused.status_code == 429
    assert "daily" in refused.json()["detail"].lower()


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
            admit_model_request(account_id, guard=False)
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
    run_inference_sync(noop, scope=InferenceScope(account_id=account_id, role="player", purpose="one"))
    # Same reusable context, same account: the limit must be enforced again.
    with pytest.raises(ModelLimitExceeded):
        run_inference_sync(noop, scope=InferenceScope(account_id=account_id, role="player", purpose="two"))


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
