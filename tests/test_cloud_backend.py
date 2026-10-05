"""Hosted model configuration tests; model construction makes no network calls."""

import threading
import time

import pytest

from utils import model_downloader as md


def _reset_models():
    md._llm_instance = None
    md._judge_llm_instance = None
    md._coach_llm_instance = None


@pytest.fixture(autouse=True)
def _hosted_model_factory(hosted_model_builder):
    _reset_models()
    yield
    _reset_models()


@pytest.mark.parametrize(("setting", "value"), [("TESTING", "1"), ("SKIP_LLM_LOAD", "true")])
def test_test_environment_does_not_replace_hosted_factory(monkeypatch, setting, value):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv(setting, value)

    assert isinstance(md._build_cloud_llm("production"), md.SafeChatOpenAI)


def test_cloud_builds_configured_openai_models(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    for name in (
        "LLM_ENABLE_THINKING", "LLM_EXTRA_BODY", "JUDGE_EXTRA_BODY", "COACH_EXTRA_BODY",
        "LLM_MODEL", "LLM_MAX_TOKENS", "JUDGE_MODEL", "JUDGE_MAX_TOKENS", "COACH_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    player = md.get_llm()
    judge = md.get_judge_llm()
    coach = md.get_coach_llm()

    assert (player.model_name, player.max_tokens, player.streaming) == (
        "deepseek-ai/DeepSeek-V4-Flash", 200, True
    )
    assert (judge.model_name, judge.max_tokens, judge.streaming) == ("Qwen/Qwen3.5-27B", 700, False)
    assert (coach.model_name, coach.max_tokens, coach.streaming) == (
        "deepseek-ai/DeepSeek-V4-Flash", 512, True
    )
    assert player.extra_body is None
    assert judge.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert coach.extra_body is None


def test_cloud_model_ids_are_env_overridable(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "Qwen/Qwen3.5-4B-NonReasoning")
    monkeypatch.setenv("LLM_MAX_TOKENS", "321")
    monkeypatch.setenv("COACH_MODEL", "deepseek-ai/custom-coach")

    assert md.get_llm().model_name == "Qwen/Qwen3.5-4B-NonReasoning"
    assert md.get_llm().max_tokens == 321
    assert md._build_cloud_llm("coach").model_name == "deepseek-ai/custom-coach"


def test_hosted_judge_max_tokens_env_override(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("JUDGE_MAX_TOKENS", "900")
    assert md._build_cloud_llm("judge").max_tokens == 900


def test_thinking_can_be_enabled_via_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_ENABLE_THINKING", "true")
    assert md._build_cloud_llm("judge").extra_body is None


def test_extra_body_json_overrides_default(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_EXTRA_BODY", '{"player": true}')
    monkeypatch.delenv("JUDGE_EXTRA_BODY", raising=False)
    monkeypatch.delenv("LLM_ENABLE_THINKING", raising=False)

    assert md._build_cloud_llm("production").extra_body == {"player": True}
    assert md._build_cloud_llm("judge").extra_body == {"chat_template_kwargs": {"enable_thinking": False}}


def test_coach_extra_body_overrides_global_body_only_for_coach(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_EXTRA_BODY", '{"player": true}')
    monkeypatch.setenv("COACH_EXTRA_BODY", '{"coach": true}')

    assert md._build_cloud_llm("production").extra_body == {"player": True}
    assert md._build_cloud_llm("coach").extra_body == {"coach": True}


def test_judge_extra_body_overrides_only_judge(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_EXTRA_BODY", '{"player": true}')
    monkeypatch.setenv("JUDGE_EXTRA_BODY", '{"judge": true}')

    assert md._build_cloud_llm("production").extra_body == {"player": True}
    assert md._build_cloud_llm("judge").extra_body == {"judge": True}


@pytest.mark.parametrize(("raw", "message"), [("not-json", "valid JSON"), ("[]", "JSON object")])
def test_extra_body_invalid_json_raises(monkeypatch, raw, message):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_EXTRA_BODY", raw)
    with pytest.raises(ValueError, match=f"LLM_EXTRA_BODY.*{message}"):
        md._build_cloud_llm("production")


@pytest.mark.parametrize("setting,role", [("LLM_EXTRA_BODY", "production"), ("JUDGE_EXTRA_BODY", "judge"), ("COACH_EXTRA_BODY", "coach")])
def test_extra_body_non_object_json_raises(monkeypatch, setting, role):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv(setting, "[]")
    with pytest.raises(ValueError, match=f"{setting}.*JSON object"):
        md._build_cloud_llm(role)


def test_empty_judge_extra_body_disables_default_and_ignores_player_body(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_EXTRA_BODY", '{"player": true}')
    monkeypatch.setenv("JUDGE_EXTRA_BODY", "{}")

    assert md._build_cloud_llm("production").extra_body == {"player": True}
    assert md._build_cloud_llm("judge").extra_body is None


def test_empty_coach_extra_body_disables_extra_body(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("COACH_EXTRA_BODY", "{}")
    assert md._build_cloud_llm("coach").extra_body is None


@pytest.mark.parametrize("coach_body", [None, ""])
def test_unset_or_blank_coach_extra_body_sends_no_extra_body(monkeypatch, coach_body):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    if coach_body is None:
        monkeypatch.delenv("COACH_EXTRA_BODY", raising=False)
    else:
        monkeypatch.setenv("COACH_EXTRA_BODY", coach_body)
    assert md._build_cloud_llm("coach").extra_body is None


@pytest.mark.parametrize(("raw", "message"), [("not-json", "valid JSON"), ("[]", "JSON object")])
def test_invalid_coach_extra_body_fails_at_build(monkeypatch, raw, message):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("COACH_EXTRA_BODY", raw)
    with pytest.raises(ValueError, match=f"COACH_EXTRA_BODY.*{message}"):
        md._build_cloud_llm("coach")


def test_missing_api_key_fails_fast(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        md.get_llm()


def test_cloud_request_bounds_defaults(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    model = md._build_cloud_llm("production")
    assert model.request_timeout == md.DEFAULT_CLOUD_REQUEST_TIMEOUT
    assert model.max_retries == md.DEFAULT_CLOUD_MAX_RETRIES
    assert model.stream_chunk_timeout == md.DEFAULT_CLOUD_STREAM_CHUNK_TIMEOUT


def test_cloud_request_bounds_env_overrides(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT", "12.5")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    monkeypatch.setenv("LLM_STREAM_CHUNK_TIMEOUT", "7.5")
    model = md._build_cloud_llm("production")
    assert (model.request_timeout, model.max_retries, model.stream_chunk_timeout) == (12.5, 0, 7.5)


def test_cloud_request_bounds_invalid_input_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT", "nan")
    monkeypatch.setenv("LLM_MAX_RETRIES", "-2")
    monkeypatch.setenv("LLM_STREAM_CHUNK_TIMEOUT", "inf")
    model = md._build_cloud_llm("production")
    assert model.request_timeout == md.DEFAULT_CLOUD_REQUEST_TIMEOUT
    assert model.max_retries == md.DEFAULT_CLOUD_MAX_RETRIES
    assert model.stream_chunk_timeout == md.DEFAULT_CLOUD_STREAM_CHUNK_TIMEOUT


def test_unknown_cloud_model_type_rejected(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    with pytest.raises(ValueError, match="Unknown model_type"):
        md._build_cloud_llm("unknown")


def test_concurrent_first_build_creates_one_model(monkeypatch):
    calls = []

    def slow_constructor(**_kwargs):
        calls.append(1)
        time.sleep(0.1)
        return object()

    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setattr(md, "SafeChatOpenAI", slow_constructor)
    results = []
    threads = [threading.Thread(target=lambda: results.append(md.get_llm())) for _ in range(4)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 1
    assert all(result is results[0] for result in results)


def test_lazy_hosted_proxies_never_build_on_repr_or_dunder():
    assert md._llm_instance is None and md._judge_llm_instance is None
    assert "loaded=False" in repr(md.llm)
    assert "loaded=False" in repr(md.judge_llm)
    assert md._llm_instance is None and md._judge_llm_instance is None
    with pytest.raises(AttributeError):
        _ = md.llm.__wrapped__
    assert md._llm_instance is None


def test_hosted_model_ids_are_the_only_configured_ids(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "custom/player")
    monkeypatch.setenv("JUDGE_MODEL", "custom/judge")
    monkeypatch.setenv("COACH_MODEL", "custom/coach")

    assert md.configured_model_ids() == {"custom/player", "custom/judge", "custom/coach"}
    assert md.model_identity("coach") == ("custom/coach", "openai")


def test_hosted_role_output_budgets_are_scoped():
    assert md.CLOUD_MODEL_REGISTRY["judge"]["default_max_tokens"] == 700
    assert md.CLOUD_MODEL_REGISTRY["production"]["default_max_tokens"] == 200
    assert md.CLOUD_MODEL_REGISTRY["coach"]["default_max_tokens"] == 512


def test_unload_role_models_and_unload_all_release_built_instances(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    player = md.get_llm()
    judge = md.get_judge_llm()
    coach = md.get_coach_llm()
    assert (md._llm_instance, md._judge_llm_instance, md._coach_llm_instance) == (
        player,
        judge,
        coach,
    )

    md.unload_llm()
    assert md._llm_instance is None
    md.unload_judge_llm()
    assert md._judge_llm_instance is None
    md.unload_coach_llm()
    assert md._coach_llm_instance is None

    md.get_llm()
    md.get_judge_llm()
    md.get_coach_llm()
    from svc.llm import unload_all

    unload_all()
    assert md._llm_instance is None
    assert md._judge_llm_instance is None
    assert md._coach_llm_instance is None


def test_max_concurrent_parsing(monkeypatch):
    from svc import llm as gateway

    monkeypatch.setenv("LLM_MAX_CONCURRENT", "4")
    assert gateway._max_concurrent() == 4
    monkeypatch.setenv("LLM_MAX_CONCURRENT", "0")
    assert gateway._max_concurrent() == 1
    monkeypatch.setenv("LLM_MAX_CONCURRENT", "invalid")
    assert gateway._max_concurrent() == 1
    monkeypatch.delenv("LLM_MAX_CONCURRENT", raising=False)
    assert gateway._max_concurrent() == 1
