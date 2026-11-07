"""Inference monitoring counts every consent choice without changing analytics (#637)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import HumanMessage
from openai import APITimeoutError

from service import analytics, coach_ai, inference_metrics
from service.ai_usage_analytics import AIRequestContext, capture_ai_request_completed
from svc.llm import InferenceScope, bound_stream, inference_turn, run_inference_sync
from svc.monitoring.runtime import Monitoring, MonitoringView
from svc.monitoring.store import MetricsStore
from svc.monitoring.tiles.inference import create_provider
from svc.request_metrics import RequestMetrics
from tests.fakes.chat_model import ScriptedChatModel, StreamErrorTurn


@pytest.fixture
def provider(monkeypatch):
    # Restore the previous app's sink when the test finishes.
    monkeypatch.setattr(inference_metrics, "_recorder", None)
    return create_provider(None)


@pytest.mark.parametrize("purpose", [
    "chat", "onboarding", "onboarding_complete", "program_active", "program_generate",
    "profile_rebuild", "coach_generate_draft", "coach_program_import", "coach_program_request",
    "coach_assistant", "coach_roster_assistant", "checkpoint_review",
])
def test_each_metered_purpose_counts_one_completed_turn(provider, monkeypatch, purpose):
    clock = iter((10.0, 10.125))
    monkeypatch.setattr("svc.llm.time.perf_counter", lambda: next(clock))
    scope = InferenceScope(purpose=purpose, admit=False)
    with inference_turn(scope) as turn:
        assert run_inference_sync(lambda: "Answer", scope=scope) == "Answer"
    turn.emit()  # Response/background completion must not count the turn twice.

    rows = provider.measurements.snapshot()
    assert len(rows) == 1
    assert rows[0]["dimensions"] == {"purpose": purpose, "outcome": "ok"}
    assert rows[0]["metric"] == "latency"
    assert rows[0]["count"] == 1
    assert rows[0]["total"] == turn.latency_ms == 125


@pytest.mark.parametrize("analytics_allowed", [True, False])
def test_consent_does_not_change_monitoring_or_the_existing_event_payload(
    provider, fresh_store, recording_analytics, monkeypatch, analytics_allowed,
):
    monkeypatch.setenv("MAYOS_ENV", "development")
    monkeypatch.setenv("MODEL_RATE_LIMIT_REQUESTS", "20")
    monkeypatch.setenv("MODEL_DAILY_TOKEN_LIMIT", "200000")
    monkeypatch.setenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
    account_id = fresh_store.create_account("private-inference-ledger")
    fresh_store.set_account_analytics_allowed(account_id, analytics_allowed)
    analytics.override_analytics_preference_reader(fresh_store.analytics_preference_allows)
    turn_id = "a" * 32
    fresh_store.record_model_usage(
        account_id, "player", "deepseek-ai/DeepSeek-V4-Flash", 20, 5, 0.002, False,
        purpose="chat", turn_id=turn_id,
    )
    context = AIRequestContext(
        account_id=account_id, turn_id=turn_id, role="player", purpose="chat", store=fresh_store,
        client=analytics.ClientContext("web/1.2.3"), latency_ms=125, outcome="error", finish_reason="stop",
        ttft_ms=25, monitoring_outcome="timeout",
    )
    capture_ai_request_completed(context)

    rows = provider.measurements.snapshot()
    assert {(row["metric"], row["total"], row["count"]) for row in rows} == {
        ("latency", 125, 1), ("ttft", 25, 1),
    }
    assert all(row["dimensions"] == {"purpose": "chat", "outcome": "timeout"} for row in rows)
    assert account_id not in repr(rows) and turn_id not in repr(rows)
    completed = [event for event in recording_analytics.events if event["event"] == "ai_request_completed"]
    if not analytics_allowed:
        assert completed == []
        return
    assert completed == [{
        "distinct_id": account_id,
        "event": "ai_request_completed",
        "uuid": analytics.deterministic_event_uuid("ai_request_completed", turn_id),
        "properties": {
            "role": "player", "platform": "web", "app_version": "1.2.3", "env": "development",
            "plan": "free", "use_case": "chat", "models": ["deepseek-ai/DeepSeek-V4-Flash"],
            "model_count": 1, "input_tokens": 20, "output_tokens": 5, "tokens": 25,
            "cost_usd": 0.002, "estimated": False, "latency_ms": 125, "outcome": "error",
            "finish_reason": "stop", "turns_today": 1, "requests_per_minute_limit": 20,
            "tokens_today": 25, "tokens_daily_limit": 200000,
        },
    }]


@pytest.mark.parametrize(("error", "outcome"), [
    (RuntimeError("provider failed before usage"), "error"),
    (TimeoutError("inference queue full"), "timeout"),
    (httpx.ReadTimeout("provider stalled"), "timeout"),
    (APITimeoutError(request=httpx.Request("POST", "https://provider.invalid")), "timeout"),
])
def test_failed_and_timed_out_turns_count_without_committed_usage(provider, error, outcome):
    scope = InferenceScope(purpose="checkpoint_review", admit=False)

    def fail_model():
        raise error

    with pytest.raises(type(error)):
        with inference_turn(scope):
            run_inference_sync(fail_model, scope=scope)

    rows = provider.measurements.snapshot()
    assert len(rows) == 1
    assert rows[0]["count"] == 1
    assert rows[0]["dimensions"] == {"purpose": "checkpoint_review", "outcome": outcome}
    assert rows[0]["metric"] == "latency"  # No first token must not become a zero TTFT.


@pytest.mark.parametrize("fails_after_token", [False, True])
def test_player_stream_reuses_first_token_timing_and_counts_caught_errors(
    provider, fresh_store, monkeypatch, fails_after_token,
):
    from agent import assistant_graph

    answer = "Keep the elbows tucked."
    scripted_turn = StreamErrorTurn(answer, RuntimeError("provider stopped")) if fails_after_token else answer
    monkeypatch.setattr(assistant_graph, "llm", ScriptedChatModel([scripted_turn]))
    state = {"messages": [HumanMessage(content="Cue machine chest press")], "trainee_id": "default"}
    scope = InferenceScope(purpose="chat", admit=False)
    with inference_turn(scope) as turn:
        chunks = list(bound_stream(
            assistant_graph.stream_assistant_turn, state,
            ledger=fresh_store.ledger, store=fresh_store, scope=scope,
        ))

    assert answer in "".join(chunks)
    rows = {row["metric"]: row for row in provider.measurements.snapshot()}
    assert rows["ttft"]["count"] == rows["latency"]["count"] == 1
    assert rows["ttft"]["total"] == turn.ttft_ms
    assert rows["ttft"]["total"] > 0
    assert rows["latency"]["total"] == turn.latency_ms
    assert rows["latency"]["dimensions"]["outcome"] == ("error" if fails_after_token else "ok")


def test_coach_stream_records_first_chunk_and_not_each_subsequent_token(provider, scripted_chat_model):
    answer = "Use controlled reps and a comfortable range of motion."
    scripted_chat_model.reset([answer])
    scope = InferenceScope(purpose="coach_assistant", admit=False)
    with inference_turn(scope) as turn:
        chunks = list(bound_stream(coach_ai.stream_answer, [HumanMessage(content="Form cues?")], scope=scope))

    assert chunks[-1] == ("done", answer)
    rows = {row["metric"]: row for row in provider.measurements.snapshot()}
    assert rows["ttft"]["count"] == rows["latency"]["count"] == 1
    assert rows["ttft"]["total"] == turn.ttft_ms
    assert rows["ttft"]["total"] > 0
    assert rows["ttft"]["dimensions"]["purpose"] == "coach_assistant"


def test_failed_monitoring_sink_preserves_the_answer_and_original_error(provider):
    def unavailable_sink(*_measurements):
        raise OSError("measurement unavailable")

    inference_metrics.set_recorder(unavailable_sink)
    scope = InferenceScope(purpose="chat", admit=False)
    with inference_turn(scope):
        assert run_inference_sync(lambda: "Answer", scope=scope) == "Answer"
    original_error = RuntimeError("original provider error")

    def fail_model():
        raise original_error

    with pytest.raises(RuntimeError) as raised:
        with inference_turn(scope):
            run_inference_sync(fail_model, scope=scope)
    assert raised.value is original_error


def test_tile_merges_histograms_by_purpose_and_uses_turns_as_the_rate_denominator(provider):
    for outcome, latency, count in (("ok", 5, 50), ("error", 10, 45), ("timeout", 25, 4), ("interrupted", 120001, 1)):
        for _ in range(count):
            inference_metrics.record_turn("chat", outcome, latency, 5 if outcome != "interrupted" else None)
    inference_metrics.record_turn("checkpoint_review", "ok", 120001, None)
    page = provider.render(MonitoringView(24, datetime.now(UTC), provider.measurements.snapshot()))
    player = page.split('<th scope="row">Player chat</th>', 1)[1].split("</tr>", 1)[0]
    assert player == (
        '<td>100</td><td>~5 ms</td><td>~10 ms</td><td>~25 ms</td>'
        '<td>~5 ms</td><td>~5 ms</td><td>~5 ms</td><td>49.00%</td><td>4.00%</td>'
    )
    checkpoint = page.split('<th scope="row">Checkpoint review</th>', 1)[1].split("</tr>", 1)[0]
    assert checkpoint.count("&gt;120 s") == 3
    assert checkpoint.count("No samples") == 3


def test_discovered_tile_persists_only_bounded_dimensions_and_timings(provider, tmp_path):
    app = SimpleNamespace(state=SimpleNamespace(request_metrics=RequestMetrics()))
    monitoring = Monitoring(app)
    monitoring.store = MetricsStore(tmp_path / "monitoring.db")
    context = AIRequestContext(
        account_id="PRIVATE_ACCOUNT", turn_id="PRIVATE_LEDGER", role="player",
        purpose="PRIVATE_PROMPT", store=None, client=analytics.UNKNOWN_CLIENT,
        latency_ms=500, outcome="PRIVATE_COMPLETION", finish_reason=None, ttft_ms=100,
    )
    capture_ai_request_completed(context)
    monitoring.flush()
    monitoring.flush()
    rows = [row for row in monitoring.store.history("restart", datetime.now(UTC) - timedelta(hours=1))
            if row["provider"] == "inference"]
    assert len(rows) == 2
    assert sum(row["count"] for row in rows if row["metric"] == "latency") == 1
    assert all(row["dimensions"] == {"purpose": "other", "outcome": "other"} for row in rows)
    assert "PRIVATE_" not in repr(rows)
    assert "Inference latency</h2>" in monitoring.render(1)


def test_empty_tile_shows_no_inference_samples(provider):
    page = provider.render(MonitoringView(1, datetime.now(UTC), []))
    assert "No inference turns recorded yet." in page
    assert "0.00%" not in page
