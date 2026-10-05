"""Provider smoke command — offline behavior only (no live calls)."""

from scripts import provider_smoke as smoke
from tests.fakes.chat_model import ScriptedChatModel, ToolCallsTurn


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
