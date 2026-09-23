"""Cloud (OpenAI-compatible) backend unit tests — no network, no GGUF loads."""

import pytest

from utils import model_downloader as md


def _reset_singletons():
    md._llm_instance = None
    md._judge_llm_instance = None
    md._coach_llm_instance = None


def test_backend_defaults_to_local(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    assert md._llm_backend() == "local"
    assert md.uses_cloud_backend() is False


def test_backend_openai_detected(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "openai")
    assert md.uses_cloud_backend() is True
    monkeypatch.setenv("LLM_BACKEND", "OPENAI")
    assert md.uses_cloud_backend() is True


def test_cloud_mock_on_testing_regardless_of_key(monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("LLM_API_KEY", "sk-present")
    assert md._should_use_cloud_mock() is True


def test_cloud_mock_without_key_in_test_context(monkeypatch):
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    # pytest is imported, so the fallback context is active and the key is empty.
    assert md._should_use_cloud_mock() is True


def test_cloud_not_mocked_when_key_present(monkeypatch):
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "sk-present")
    assert md._should_use_cloud_mock() is False


def test_cloud_getters_return_mock_in_testing(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("TESTING", "1")
    _reset_singletons()
    try:
        assert isinstance(md.get_llm(), md.MockSafeChatLlamaCpp)
        assert isinstance(md.get_judge_llm(), md.MockSafeChatLlamaCpp)
        assert isinstance(md.get_coach_llm(), md.MockSafeChatLlamaCpp)
    finally:
        _reset_singletons()


@pytest.mark.skipif(md.SafeChatOpenAI is None, reason="langchain-openai not installed")
def test_cloud_builds_configured_openai_models(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_API_BASE", "https://api.deepinfra.com/v1/openai")
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("LLM_ENABLE_THINKING", raising=False)
    monkeypatch.delenv("LLM_EXTRA_BODY", raising=False)
    _reset_singletons()
    try:
        prod = md.get_llm()
        judge = md.get_judge_llm()
        coach = md.get_coach_llm()
        assert prod.model_name == "Qwen/Qwen3.5-9B"
        assert prod.max_tokens == 200 and prod.streaming is True
        assert judge.model_name == "Qwen/Qwen3.5-27B"
        assert judge.max_tokens == 700 and judge.streaming is False
        assert coach.model_name == "Qwen/Qwen3.5-27B"
        assert coach.max_tokens == 512 and coach.streaming is True
        # Thinking disabled by default (DeepInfra's documented nested shape)
        # keeps the tight output budget productive.
        assert prod.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    finally:
        _reset_singletons()


@pytest.mark.skipif(md.SafeChatOpenAI is None, reason="langchain-openai not installed")
def test_cloud_model_ids_are_env_overridable(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "Qwen/Qwen3.5-4B-NonReasoning")
    monkeypatch.setenv("LLM_MAX_TOKENS", "321")
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("CI", raising=False)
    _reset_singletons()
    try:
        prod = md.get_llm()
        assert prod.model_name == "Qwen/Qwen3.5-4B-NonReasoning"
        assert prod.max_tokens == 321
    finally:
        _reset_singletons()


@pytest.mark.skipif(md.SafeChatOpenAI is None, reason="langchain-openai not installed")
def test_thinking_can_be_enabled_via_env(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_ENABLE_THINKING", "true")
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("LLM_EXTRA_BODY", raising=False)
    _reset_singletons()
    try:
        assert md.get_llm().extra_body is None
    finally:
        _reset_singletons()


@pytest.mark.skipif(md.SafeChatOpenAI is None, reason="langchain-openai not installed")
def test_extra_body_json_overrides_default(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_EXTRA_BODY", '{"chat_template_kwargs": {"enable_thinking": false}}')
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("CI", raising=False)
    _reset_singletons()
    try:
        assert md.get_llm().extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    finally:
        _reset_singletons()


def test_extra_body_invalid_json_raises(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_EXTRA_BODY", "not-json")
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("CI", raising=False)
    _reset_singletons()
    try:
        with pytest.raises(ValueError, match="LLM_EXTRA_BODY"):
            md.get_llm()
    finally:
        _reset_singletons()


@pytest.mark.skipif(md.SafeChatOpenAI is None, reason="langchain-openai not installed")
def test_extra_body_non_object_json_raises(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_EXTRA_BODY", "[]")
    with pytest.raises(ValueError, match="JSON object"):
        md._build_cloud_llm("production")


@pytest.mark.skipif(md.SafeChatOpenAI is None, reason="langchain-openai not installed")
def test_missing_api_key_fails_fast(monkeypatch):
    """A cloud backend without a key must fail at build, not per-request 401."""
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        md._build_cloud_llm("production")


@pytest.mark.skipif(md.SafeChatOpenAI is None, reason="langchain-openai not installed")
def test_cloud_request_bounds_defaults(monkeypatch):
    """A stalled provider must be bounded out of the box (finite timeout + retries)."""
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    for var in ("LLM_REQUEST_TIMEOUT", "LLM_MAX_RETRIES", "LLM_STREAM_CHUNK_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)
    model = md._build_cloud_llm("production")
    assert model.request_timeout == md.DEFAULT_CLOUD_REQUEST_TIMEOUT
    assert model.max_retries == md.DEFAULT_CLOUD_MAX_RETRIES
    assert model.stream_chunk_timeout == md.DEFAULT_CLOUD_STREAM_CHUNK_TIMEOUT


@pytest.mark.skipif(md.SafeChatOpenAI is None, reason="langchain-openai not installed")
def test_cloud_request_bounds_env_overrides(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT", "12.5")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")  # zero retries is valid (minimal)
    monkeypatch.setenv("LLM_STREAM_CHUNK_TIMEOUT", "7.5")
    model = md._build_cloud_llm("production")
    assert model.request_timeout == 12.5
    assert model.max_retries == 0
    assert model.stream_chunk_timeout == 7.5


@pytest.mark.skipif(md.SafeChatOpenAI is None, reason="langchain-openai not installed")
def test_cloud_request_bounds_invalid_input_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT", "abc")
    monkeypatch.setenv("LLM_MAX_RETRIES", "-2")
    monkeypatch.setenv("LLM_STREAM_CHUNK_TIMEOUT", "0")
    model = md._build_cloud_llm("production")
    assert model.request_timeout == md.DEFAULT_CLOUD_REQUEST_TIMEOUT
    assert model.max_retries == md.DEFAULT_CLOUD_MAX_RETRIES
    assert model.stream_chunk_timeout == md.DEFAULT_CLOUD_STREAM_CHUNK_TIMEOUT

    # Non-finite values are not sensible bounds either.
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT", "nan")
    monkeypatch.setenv("LLM_STREAM_CHUNK_TIMEOUT", "inf")
    model = md._build_cloud_llm("production")
    assert model.request_timeout == md.DEFAULT_CLOUD_REQUEST_TIMEOUT
    assert model.stream_chunk_timeout == md.DEFAULT_CLOUD_STREAM_CHUNK_TIMEOUT


def test_hosted_judge_token_budget_is_sufficient_and_scoped():
    """Hosted judge needs room for schema JSON; player/coach budgets are unchanged."""
    assert md.CLOUD_MODEL_REGISTRY["judge"]["default_max_tokens"] == 700
    assert md.CLOUD_MODEL_REGISTRY["production"]["default_max_tokens"] == 200
    assert md.CLOUD_MODEL_REGISTRY["coach"]["default_max_tokens"] == 512


@pytest.mark.skipif(md.SafeChatOpenAI is None, reason="langchain-openai not installed")
def test_hosted_judge_max_tokens_env_override(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("JUDGE_MAX_TOKENS", "900")
    assert md._build_cloud_llm("judge").max_tokens == 900


def test_unknown_cloud_model_type_rejected(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(ValueError, match="Unknown cloud model_type"):
        md._build_cloud_llm("nope")


def test_local_coach_reuses_production(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "local")
    monkeypatch.setenv("TESTING", "1")
    _reset_singletons()
    try:
        assert md.get_coach_llm() is md.get_llm()
    finally:
        _reset_singletons()


def test_serial_lock_only_for_local_backend(monkeypatch):
    from svc import llm as gateway

    monkeypatch.setenv("LLM_BACKEND", "local")
    assert gateway._uses_serial_lock() is True
    monkeypatch.setenv("LLM_BACKEND", "openai")
    assert gateway._uses_serial_lock() is False


def test_max_concurrent_parsing(monkeypatch):
    from svc import llm as gateway

    monkeypatch.setenv("LLM_MAX_CONCURRENT", "4")
    assert gateway._max_concurrent() == 4
    monkeypatch.setenv("LLM_MAX_CONCURRENT", "0")
    assert gateway._max_concurrent() == 1
    monkeypatch.setenv("LLM_MAX_CONCURRENT", "garbage")
    assert gateway._max_concurrent() == 1
    monkeypatch.delenv("LLM_MAX_CONCURRENT", raising=False)
    assert gateway._max_concurrent() == 1
