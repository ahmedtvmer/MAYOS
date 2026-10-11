"""Provider smoke command — offline behavior only (no live calls)."""

import json

from langchain_core.messages import AIMessage, AIMessageChunk
import pytest

from scripts import provider_smoke as smoke
from tests.fakes.chat_model import ScriptedChatModel, ToolCallsTurn
from utils.model_metering import UsageContext, current_usage_context, record_usage, usage_context


def _requester(model="Qwen/Qwen3.5-4B", reasoning=""):
    def request(payload, timeout):
        return {
            "model": model,
            "choices": [{"message": {"content": "ready", "reasoning_content": reasoning}}],
        }

    return request


def _fake_model(model_name="Qwen/Qwen3.5-4B", extra_body=None, *, tool_name="get_weather", boom=None):
    return ScriptedChatModel(
        turns=[
            boom or "ready",
            {"result": "ready"},
            ToolCallsTurn(
                [{"name": tool_name, "args": {"city": "Berlin"}, "id": "call_1"}]
                if tool_name
                else []
            ),
        ],
        model_name=model_name,
        extra_body=extra_body,
    )


def test_not_run_when_key_missing_exits_nonzero(monkeypatch, capsys):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert smoke.main([]) == 2
    out = capsys.readouterr().out
    assert "not_run" in out
    assert "LLM_API_KEY not set" in out


def test_missing_key_never_writes_a_measurement_report(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    assert smoke.main(["--baseline", "--report", str(tmp_path / "never.md")]) == 2
    assert list(tmp_path.iterdir()) == []


def test_report_requires_a_measurement_mode(monkeypatch):
    monkeypatch.setattr(smoke, "configured_api_key", lambda: "test")

    with pytest.raises(SystemExit, match="2"):
        smoke.main(["--report", "provider-smoke.md"])


def test_run_smoke_passes_all_checks():
    report = smoke.run_smoke(
        _fake_model(extra_body={"chat_template_kwargs": {"enable_thinking": False}}),
        expected_model="Qwen/Qwen3.5-4B",
        api_base="https://example.invalid/v1/openai",
        api_key="sk-secret",
        requester=_requester(),
    )
    assert report.status == "pass"
    assert {check.name for check in report.checks} >= {
        "model_id", "request_body_config", "streaming", "structured_output", "tool_calls"
    }


def test_deepseek_default_allows_no_extra_body():
    report = smoke.run_smoke(
        _fake_model(model_name=smoke.DEEPSEEK_PLAYER, extra_body=None),
        expected_model=smoke.DEEPSEEK_PLAYER,
        api_base="https://example.invalid/v1/openai",
        requester=_requester(model=smoke.DEEPSEEK_PLAYER),
    )
    assert report.status == "pass"
    assert next(c for c in report.checks if c.name == "request_body_config").passed


def test_run_smoke_detects_reasoning_content():
    report = smoke.run_smoke(
        _fake_model(extra_body={"chat_template_kwargs": {"enable_thinking": False}}),
        expected_model="Qwen/Qwen3.5-4B",
        api_base="https://example.invalid/v1/openai",
        api_key="sk-secret",
        requester=_requester(reasoning="let me think..."),
    )
    assert report.status == "fail"
    no_leaked_reasoning = next(c for c in report.checks if c.name == "non_reasoning_response")
    assert not no_leaked_reasoning.passed


def test_run_smoke_detects_missing_tool_calls():
    report = smoke.run_smoke(
        _fake_model(tool_name=None, extra_body={"chat_template_kwargs": {"enable_thinking": False}}),
        expected_model="Qwen/Qwen3.5-4B",
        api_base="https://example.invalid/v1/openai",
        api_key="sk-secret",
        requester=_requester(),
    )
    assert report.status == "fail"
    assert not next(c for c in report.checks if c.name == "tool_calls").passed


def test_run_smoke_detects_model_mismatch():
    report = smoke.run_smoke(
        _fake_model(model_name="some/other-model", extra_body={"chat_template_kwargs": {"enable_thinking": False}}),
        expected_model="Qwen/Qwen3.5-4B",
        api_base="https://example.invalid/v1/openai",
        api_key="sk-secret",
        requester=_requester(),
    )
    assert report.status == "fail"
    assert not next(c for c in report.checks if c.name == "model_id").passed


def test_nested_chat_template_shape_is_accepted():
    model = _fake_model(extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    report = smoke.run_smoke(
        model,
        expected_model="Qwen/Qwen3.5-4B",
        api_base="https://example.invalid/v1/openai",
        api_key="sk-secret",
        requester=_requester(),
    )
    assert next(c for c in report.checks if c.name == "request_body_config").passed


def test_report_never_leaks_the_api_key():
    secret = "sk-super-secret-123"
    report = smoke.run_smoke(
        _fake_model(boom=RuntimeError(f"auth failed for {secret}")),
        expected_model="Qwen/Qwen3.5-4B",
        api_base="https://example.invalid/v1/openai",
        api_key=secret,
        requester=_requester(),
    )
    rendered = smoke.render_report(report, secret)
    assert secret not in rendered
    assert "REDACTED" in rendered


def test_json_report_never_leaks_the_api_key():
    secret = "sk-super-secret-123"
    report = smoke.run_smoke(
        _fake_model(boom=RuntimeError(f"auth failed for {secret}")),
        expected_model="Qwen/Qwen3.5-4B",
        api_base="https://example.invalid/v1/openai",
        api_key=secret,
        requester=_requester(),
    )
    rendered = smoke.render_json(report, secret)
    assert secret not in rendered
    assert "REDACTED" in rendered
    import json

    assert json.loads(rendered)["status"] == "fail"


def test_thinking_disabled_detection():
    assert smoke._thinking_disabled({"enable_thinking": False}) is True
    assert smoke._thinking_disabled({"chat_template_kwargs": {"enable_thinking": False}}) is True
    assert smoke._thinking_disabled({"enable_thinking": True}) is False
    assert smoke._thinking_disabled(None) is False


def test_live_model_factory_applies_timeout_and_disables_hidden_retries(monkeypatch, hosted_model_builder):
    from utils import model_downloader

    monkeypatch.setenv("LLM_API_KEY", "sk-test-only")
    monkeypatch.setenv("LLM_API_BASE", "https://example.invalid/v1/openai")

    model = model_downloader.build_player_llm(timeout=12.5, max_retries=0)

    assert model.request_timeout == 12.5
    assert model.stream_chunk_timeout == 12.5
    assert model.max_retries == 0


class _TextStreamFake:
    model_name = smoke.DEEPSEEK_PLAYER
    extra_body = None

    def __init__(self):
        self.prompts = []
        self.usage_contexts = []

    def stream(self, prompt):
        self.prompts.append(prompt)
        self.usage_contexts.append(current_usage_context())
        yield AIMessageChunk(content="First ")
        yield AIMessageChunk(content="token stream")


class _BoundStreamFake:
    def __init__(self, turns):
        self.turns = iter(turns)
        self.messages = []
        self.usage_contexts = []

    def stream(self, messages):
        self.messages.append(messages)
        self.usage_contexts.append(current_usage_context())
        yield from next(self.turns)


class _ToolStreamFake:
    model_name = smoke.DEEPSEEK_PLAYER
    extra_body = None

    def __init__(self, turns):
        self.bound = _BoundStreamFake(turns)

    def bind_tools(self, tools):
        self.tools = tools
        return self.bound


def _tool_delta(name, args, call_id, index):
    return AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"name": name, "args": args, "id": call_id, "index": index, "type": "tool_call_chunk"}
        ],
    )


def _successful_tool_model():
    return _ToolStreamFake(
        [
            [
                _tool_delta("get_profile", '{"field":"goal"}', "call_1", 0),
            ],
            [
                AIMessageChunk(content="The goal is to build strength. "),
                AIMessageChunk(content="Your last session improved."),
            ],
            [
                _tool_delta("get_profile", '{"field":"goal"}', "call_2", 0),
                _tool_delta("get_last_session", '{"exercise":"Bench Press"}', "call_3", 1),
            ],
            [
                AIMessageChunk(content="Your goal is strength, and "),
                AIMessageChunk(content="your last Bench Press was 80 kg for 5 reps."),
            ],
        ]
    )


def test_ttft_baseline_uses_fixed_english_and_arabic_prompts_and_reports_categories():
    model = _TextStreamFake()
    clock_values = iter(index / 100 for index in range(200))
    baseline = smoke.run_ttft_baseline(model, repeats=2, clock=lambda: next(clock_values))

    assert len(model.prompts) == len(smoke.BASELINE_PROMPTS) * 2
    assert {prompt.language for prompt in smoke.BASELINE_PROMPTS} == {"en", "ar"}
    assert {result.category for result in baseline.categories} == {
        "profile", "history", "last_session", "free_form_coaching"
    }
    assert len(baseline.categories) == 8
    assert all(result.sample_count == 2 for result in baseline.categories)
    assert all(result.median_seconds == pytest.approx(0.01) for result in baseline.categories)
    assert all(result.p90_seconds == pytest.approx(0.01) for result in baseline.categories)
    assert all(len(sample.attempts) == 1 for sample in baseline.samples)
    assert all(isinstance(prompt, list) for prompt in model.prompts)
    assert "Training age: 3 years" in model.prompts[0][0].content
    assert "Recent history:" not in model.prompts[0][0].content
    assert "Recent history:" in model.prompts[2][0].content
    assert "Session comparison:" in model.prompts[4][0].content
    assert {sample.category for sample in baseline.samples} == {
        "profile", "history", "last_session", "free_form_coaching"
    }
    assert all(context.account_id is None and context.role == "operator" for context in model.usage_contexts)
    assert all(context.purpose == "provider_smoke_ttft" for context in model.usage_contexts)


def test_ttft_timeout_and_retry_are_recorded_and_excluded_from_statistics():
    class OneTimeoutModel(_TextStreamFake):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def stream(self, prompt):
            self.calls += 1
            if self.calls == 1:
                self.prompts.append(prompt)
                raise TimeoutError("provider timeout")
            yield from super().stream(prompt)

    model = OneTimeoutModel()
    clock_values = iter(index / 100 for index in range(100))
    baseline = smoke.run_ttft_baseline(model, repeats=1, clock=lambda: next(clock_values))

    first = baseline.samples[0]
    assert first.status == "timeout_retried"
    assert first.timed_out and first.retried
    assert len(first.attempts) == 2
    assert baseline.categories[0].sample_count == 0
    assert baseline.categories[0].timeout_count == 1
    assert baseline.categories[0].retry_count == 1
    assert first.ttft_seconds is None


def test_registered_service_metering_writes_unattributed_operator_rows():
    store = smoke.SmokeUsageStore()
    smoke._register_operator_metering(store)
    try:
        with usage_context(UsageContext(
            account_id=None, role="operator", purpose="provider_smoke_ttft", store=store
        )):
            record_usage(smoke.DEEPSEEK_PLAYER, 10, 5, False)

        row = store.connection.execute(
            "SELECT account_id, role, purpose, input_tokens, output_tokens FROM model_usage"
        ).fetchone()
        assert row == (None, "operator", "provider_smoke_ttft", 10, 5)
        assert store.count_operator_rows() == 1
    finally:
        smoke.set_recorder(None)
        store.close()


def test_p90_uses_nearest_rank_percentile():
    assert smoke._nearest_rank_p90(list(range(1, 11))) == 9


def test_tool_call_check_streams_single_and_parallel_calls_then_final_answer():
    model = _successful_tool_model()
    results = smoke.run_tool_call_check(model)

    assert [result.name for result in results] == ["single", "parallel"]
    assert all(result.passed for result in results)
    assert results[0].tool_names == ["get_profile"]
    assert set(results[1].tool_names) == {"get_profile", "get_last_session"}
    assert all(result.final_text_chunks == 2 for result in results)
    assert all(result.final_chars > 0 for result in results)
    tool_results = [message for transcript in model.bound.messages for message in transcript if message.type == "tool"]
    assert [message.tool_call_id for message in tool_results] == ["call_1", "call_2", "call_3"]
    assert [message.content for message in tool_results] == [
        "goal: build strength.",
        "goal: build strength.",
        "Bench Press: 80 kg for 5 reps.",
    ]
    assert all(context.account_id is None and context.role == "operator" for context in model.bound.usage_contexts)
    assert all(context.purpose == "provider_smoke_tool_calls" for context in model.bound.usage_contexts)


def test_tool_call_check_fails_with_raw_summary_when_calls_are_missing():
    model = _ToolStreamFake([[AIMessageChunk(content="I can answer that.")]])

    result = smoke.run_tool_call_check(model)[0]

    assert not result.passed
    assert result.final_text_chunks == 0
    assert "tool_deltas=0" in result.summary
    assert "missing" in result.summary


def test_tool_call_check_fails_on_malformed_tool_call_deltas():
    model = _ToolStreamFake(
        [[_tool_delta("get_profile", "not-json", "call_bad", 0)]]
    )

    result = smoke.run_tool_call_check(model)[0]

    assert not result.passed
    assert "malformed" in result.summary


def test_tool_call_check_fails_when_provider_does_not_stream_tool_deltas():
    response = AIMessage(
        content="",
        tool_calls=[{"name": "get_profile", "args": {"field": "goal"}, "id": "call_1"}],
    )
    model = _ToolStreamFake([[response]])

    result = smoke.run_tool_call_check(model)[0]

    assert not result.passed
    assert "not streamed" in result.summary


def test_tool_call_check_fails_when_final_answer_is_not_streamed_in_chunks():
    model = _ToolStreamFake(
        [
            [_tool_delta("get_profile", '{"field":"goal"}', "call_1", 0)],
            [AIMessageChunk(content="The goal is strength.")],
        ]
    )

    result = smoke.run_tool_call_check(model)[0]

    assert not result.passed
    assert "final answer chunks=1" in result.summary


def test_tool_call_check_reports_tool_binding_failures_clearly():
    class UnbindableModel:
        def bind_tools(self, tools):
            raise RuntimeError("provider rejected tools")

    results = smoke.run_tool_call_check(UnbindableModel())

    assert len(results) == 2
    assert all(not result.passed for result in results)
    assert all("bind_tools failed" in result.summary for result in results)


def test_baseline_mode_writes_versioned_report_without_leaking_key(tmp_path, monkeypatch):
    secret = "sk-test-secret-do-not-write"
    monkeypatch.setattr(smoke, "configured_api_key", lambda: secret)
    monkeypatch.setattr(smoke, "configured_model", lambda: smoke.DEEPSEEK_PLAYER)
    monkeypatch.setattr(smoke, "configured_api_base", lambda: "https://example.invalid/v1/openai")
    monkeypatch.setattr(smoke, "_build_smoke_model", lambda timeout: _TextStreamFake())
    monkeypatch.setattr(smoke, "_measured_code_metadata", lambda: ("abc123", "digest"))
    report_path = tmp_path / "provider-smoke.md"

    assert smoke.main(["--baseline", "--repeats", "1", "--report", str(report_path)]) == 0

    markdown_reports = list(tmp_path.glob("provider-smoke-*.md"))
    json_reports = list(tmp_path.glob("provider-smoke-*.json"))
    assert len(markdown_reports) == len(json_reports) == 1
    rendered = markdown_reports[0].read_text(encoding="utf-8")
    machine = json.loads(json_reports[0].read_text(encoding="utf-8"))
    assert "## TTFT baseline" in rendered
    assert "| profile | en | 1 |" in rendered
    assert "## Comment for #264" in rendered
    assert secret not in rendered
    assert secret not in json_reports[0].read_text(encoding="utf-8")
    assert machine["git_commit_sha"] == "abc123"
    assert machine["measured_code_sha256"] == "digest"
    assert len(machine["baseline_samples"]) == 8
    assert "T" in markdown_reports[0].stem


def test_versioned_report_includes_measurement_metadata_and_issue_comment():
    report = smoke.SmokeReport(
        status="pass",
        model=smoke.DEEPSEEK_PLAYER,
        base_url="https://example.invalid/v1/openai",
        measured_at="2026-10-11T12:00:00Z",
        baseline=[smoke.BaselineCategory("profile", "en", 5, 0.1, 0.2)],
        tool_calls=[smoke.ToolCallCheck("single", True, ["get_profile"], 1, 2, 20, "ok")],
        run_id="abcd1234",
        report_markdown_path="reports/provider-smoke/report.md",
        report_json_path="reports/provider-smoke/report.json",
    )

    rendered = smoke.render_versioned_report(report)

    assert "2026-10-11" in rendered
    assert smoke.DEEPSEEK_PLAYER in rendered
    assert "https://example.invalid/v1/openai" in rendered
    assert "## Comment for #264" in rendered
    assert "median" in rendered.lower()
    assert "profile/en: median 100.0 ms, p90 200.0 ms, n=5" in rendered
