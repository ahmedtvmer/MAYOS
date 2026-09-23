"""Provider smoke command — offline behavior only (no live calls)."""

from types import SimpleNamespace

from scripts import provider_smoke as smoke


class _FakeModel:
    def __init__(self, *, model_name="Qwen/Qwen3.5-4B", extra_body=None, chunks=("rea", "dy"), tool_name="get_weather", boom=None):
        self.model_name = model_name
        self.extra_body = {"enable_thinking": False} if extra_body is None else extra_body
        self._chunks = chunks
        self._tool_name = tool_name
        self._boom = boom

    def stream(self, prompt):
        if self._boom:
            raise self._boom
        for chunk in self._chunks:
            yield SimpleNamespace(content=chunk)

    def bind_tools(self, tools):
        return self

    def invoke(self, prompt):
        calls = [] if self._tool_name is None else [{"name": self._tool_name, "args": {"city": "Berlin"}}]
        return SimpleNamespace(tool_calls=calls)


def _requester(model="Qwen/Qwen3.5-4B", reasoning=""):
    def request(payload, timeout):
        return {
            "model": model,
            "choices": [{"message": {"content": "ready", "reasoning_content": reasoning}}],
        }

    return request


def test_not_run_when_backend_is_local_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setenv("LLM_BACKEND", "local")
    monkeypatch.setenv("LLM_API_KEY", "")
    # A not-run smoke must never be mistaken for a passed release gate.
    assert smoke.main([]) == 2
    out = capsys.readouterr().out
    assert "not_run" in out
    assert "LLM_BACKEND" in out


def test_not_run_when_key_missing_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert smoke.main([]) == 2
    out = capsys.readouterr().out
    assert "not_run" in out
    assert "LLM_API_KEY not set" in out


def test_run_smoke_passes_all_checks():
    report = smoke.run_smoke(
        _FakeModel(),
        expected_model="Qwen/Qwen3.5-4B",
        api_base="https://example.invalid/v1/openai",
        api_key="sk-secret",
        requester=_requester(),
    )
    assert report.status == "pass"
    assert {check.name for check in report.checks} >= {"model_id", "non_reasoning_config", "streaming", "tool_calls"}


def test_run_smoke_detects_reasoning_content():
    report = smoke.run_smoke(
        _FakeModel(),
        expected_model="Qwen/Qwen3.5-4B",
        api_base="https://example.invalid/v1/openai",
        api_key="sk-secret",
        requester=_requester(reasoning="let me think..."),
    )
    assert report.status == "fail"
    non_reasoning = next(c for c in report.checks if c.name == "non_reasoning_response")
    assert not non_reasoning.passed


def test_run_smoke_detects_missing_tool_calls():
    report = smoke.run_smoke(
        _FakeModel(tool_name=None),
        expected_model="Qwen/Qwen3.5-4B",
        api_base="https://example.invalid/v1/openai",
        api_key="sk-secret",
        requester=_requester(),
    )
    assert report.status == "fail"
    assert not next(c for c in report.checks if c.name == "tool_calls").passed


def test_run_smoke_detects_model_mismatch():
    report = smoke.run_smoke(
        _FakeModel(model_name="some/other-model"),
        expected_model="Qwen/Qwen3.5-4B",
        api_base="https://example.invalid/v1/openai",
        api_key="sk-secret",
        requester=_requester(),
    )
    assert report.status == "fail"
    assert not next(c for c in report.checks if c.name == "model_id").passed


def test_nested_chat_template_shape_is_accepted():
    model = _FakeModel(extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    report = smoke.run_smoke(
        model,
        expected_model="Qwen/Qwen3.5-4B",
        api_base="https://example.invalid/v1/openai",
        api_key="sk-secret",
        requester=_requester(),
    )
    assert next(c for c in report.checks if c.name == "non_reasoning_config").passed


def test_report_never_leaks_the_api_key():
    secret = "sk-super-secret-123"
    report = smoke.run_smoke(
        _FakeModel(boom=RuntimeError(f"auth failed for {secret}")),
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
        _FakeModel(boom=RuntimeError(f"auth failed for {secret}")),
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
