"""Judge configuration, generic suite seam, and retry contracts."""

import json

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError
from pydantic import BaseModel, ValidationError

from tests.eval.parity_gate import (
    RetryPolicy,
    call_with_retry,
    configured_judges,
    evaluate_report,
    retry_policy_from_env,
)
from utils.model_downloader import CLOUD_MODEL_REGISTRY, JUDGE_MODEL_ROLES


class ProviderError(RuntimeError):
    def __init__(self, status_code: int):
        super().__init__(f"provider returned {status_code}")
        self.status_code = status_code


def test_judge_configuration_defaults_come_from_the_shared_registry():
    judges = configured_judges({})

    assert [judge["model"] for judge in judges] == [
        CLOUD_MODEL_REGISTRY[role]["default_model"] for role in JUDGE_MODEL_ROLES
    ]
    assert [judge["family"] for judge in judges] == ["qwen", "glm"]


def test_judge_configuration_rejects_same_family_models():
    with pytest.raises(ValueError, match="different model families"):
        configured_judges({"JUDGE_MODEL": "Qwen/Qwen3.5-27B", "JUDGE_SECONDARY_MODEL": "Qwen/Qwen3.5-9B"})


def test_retry_policy_reads_attempt_and_backoff_settings():
    policy = retry_policy_from_env(
        {
            "EVAL_JUDGE_MAX_ATTEMPTS": "3",
            "EVAL_JUDGE_RETRY_BASE_SECONDS": "0.25",
            "EVAL_JUDGE_RETRY_MAX_SECONDS": "1",
        }
    )

    assert policy == RetryPolicy(3, 0.25, 1.0)


def test_provider_429_and_5xx_retry_with_exponential_backoff():
    calls, waits = 0, []

    def invoke():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ProviderError(429 if calls == 1 else 503)
        return "judgment"

    result = call_with_retry(invoke, RetryPolicy(4, 1.0, 3.0), waits.append)

    assert result.response == "judgment"
    assert result.attempts == 3
    assert result.error is None
    assert waits == [1.0, 2.0]


@pytest.mark.parametrize(
    "failure",
    [
        APITimeoutError(request=httpx.Request("GET", "https://example.test")),
        APIConnectionError(message="connection failed", request=httpx.Request("GET", "https://example.test")),
        httpx.ReadTimeout("read timeout"),
        httpx.ConnectError("connect failed"),
        TimeoutError("timed out"),
        ConnectionError("connection lost"),
    ],
)
def test_transport_failures_retry(failure):
    calls = 0

    def invoke():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise failure
        return "judgment"

    result = call_with_retry(invoke, RetryPolicy(2, 0, 0), lambda _seconds: None)

    assert result.response == "judgment"
    assert result.attempts == 2


def test_structured_output_parse_failure_gets_one_retry():
    class Payload(BaseModel):
        count: int

    with pytest.raises(ValidationError) as raised:
        Payload(count="not-an-integer")
    calls = 0

    def invoke():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise raised.value
        return "parsed judgment"

    result = call_with_retry(invoke, RetryPolicy(max_attempts=1), lambda _seconds: None)

    assert result.response == "parsed judgment"
    assert result.attempts == 2


def test_repeated_structured_output_parse_failure_stops_after_one_retry():
    class Payload(BaseModel):
        count: int

    with pytest.raises(ValidationError) as raised:
        Payload(count="not-an-integer")
    calls = 0

    def invoke():
        nonlocal calls
        calls += 1
        raise raised.value

    result = call_with_retry(invoke, RetryPolicy(max_attempts=4), lambda _seconds: None)

    assert result.response is None
    assert result.attempts == 2
    assert "count" in result.error
    assert calls == 2


@pytest.mark.parametrize("status_code", [400, 401, 404])
def test_non_transient_provider_errors_fail_without_retry(status_code):
    calls = 0

    def invoke():
        nonlocal calls
        calls += 1
        raise ProviderError(status_code)

    result = call_with_retry(invoke, RetryPolicy(4, 1.0, 3.0), lambda _seconds: None)

    assert result.response is None
    assert result.attempts == 1
    assert result.error == f"provider returned {status_code}"
    assert calls == 1


def test_error_message_is_redacted_and_truncated(monkeypatch):
    secret = "sk-live-secret-1234567890"
    monkeypatch.setenv("LLM_API_KEY", secret)
    result = call_with_retry(
        lambda: (_ for _ in ()).throw(RuntimeError(f"failed {secret}; " + "x" * 600)),
        RetryPolicy(max_attempts=1),
    )

    assert secret not in result.error
    assert "[REDACTED]" in result.error
    assert len(result.error) == 500


def test_judge_failure_message_is_retained_in_the_case_record():
    from tests.eval.run_evaluation import evaluate_case

    class FailedJudgeClient:
        def with_structured_output(self, *_args, **_kwargs):
            return self

        def invoke(self, _messages):
            raise RuntimeError("provider detail: temporary overload")

    case = evaluate_case(
        {"id": "case-1", "query": "Question"},
        "Reply",
        [{"name": "judge_1", "model": "Qwen/Qwen3.5-27B", "client": FailedJudgeClient()}],
        RetryPolicy(max_attempts=1),
    )

    assert case["judges"]["judge_1"]["error"] == "provider detail: temporary overload"
    assert case["judges"]["judge_1"]["passed"] is False


class DeterministicSuite:
    name = "deterministic"

    def run(self, _context):
        return self.run_hermetic(None)

    def run_hermetic(self, _context):
        return {
            "score": 9,
            "total": 10,
            "bar": {"kind": "percent", "value": 90},
            "passed": True,
            "failure_reasons": [],
            "unreviewed_count": 0,
        }

    def validate(self, recorded, _report):
        valid = (
            isinstance(recorded, dict)
            and recorded.get("score") == 9
            and recorded.get("total") == 10
            and recorded.get("bar") == {"kind": "percent", "value": 90}
            and recorded.get("passed") is True
            and recorded.get("unreviewed_count") == 0
            and recorded.get("failure_reasons") == []
        )
        reasons = [] if valid else ["deterministic suite result is invalid or has unreviewed cases"]
        return (recorded if isinstance(recorded, dict) else {}), reasons


def test_generic_report_gate_accepts_deterministic_percentage_suite_and_requires_it():
    suite = DeterministicSuite()
    report = {"suite_results": {suite.name: suite.run_hermetic(None)}}

    passed, reasons, summaries = evaluate_report(report, (suite,))
    missing_passed, missing_reasons, _ = evaluate_report({"suite_results": {}}, (suite,))

    assert passed is True
    assert reasons == []
    assert summaries[0]["bar"] == {"kind": "percent", "value": 90}
    assert missing_passed is False
    assert "deterministic" in missing_reasons[0]


def test_suite_can_fail_from_its_own_reason_even_when_its_bar_is_met():
    suite = DeterministicSuite()
    record = suite.run_hermetic(None)
    record["unreviewed_count"] = 1

    passed, reasons, _ = evaluate_report({"suite_results": {suite.name: record}}, (suite,))

    assert passed is False
    assert "unreviewed cases" in reasons[0]


def test_player_generation_exception_is_written_as_a_failed_report(tmp_path, monkeypatch, capsys):
    from tests.eval import run_evaluation
    from utils import model_downloader

    datasets = tmp_path / "datasets"
    datasets.mkdir()
    (datasets / "one_case.json").write_text('[{"id":"case-1","query":"A coaching question."}]')
    monkeypatch.setenv("EVAL_DATASETS_DIR", str(datasets))
    metadata = configured_judges({})
    context = run_evaluation.GateContext(
        judges=[{**judge, "client": None} for judge in metadata],
        judge_metadata=metadata,
        retry_policy=RetryPolicy(max_attempts=1),
    )
    suite = run_evaluation.CoachingQASuite("coaching_qa", "one_case.json", 1, run_evaluation.ScoreBar("count", 1))
    monkeypatch.setattr(run_evaluation, "SUITES", (suite,))
    monkeypatch.setattr(run_evaluation, "_build_live_context", lambda: context)
    monkeypatch.setattr(
        run_evaluation,
        "_generate_reply",
        lambda _case: (_ for _ in ()).throw(RuntimeError("player backend timed out")),
    )
    monkeypatch.setattr(model_downloader, "model_identity", lambda _role: ("test/player", "openai"))
    report_path = tmp_path / "report.json"

    exit_code = run_evaluation.main(["--report", str(report_path)])

    assert exit_code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    recorded_case = report["suite_results"]["coaching_qa"]["runs"][0]["cases"][0]
    assert recorded_case["generation_error"] == "player backend timed out"
    assert recorded_case["judges"]["judge_1"]["error"] == "Player generation failed: player backend timed out"
    assert report["gate"]["passed"] is False
    assert "Report written:" in capsys.readouterr().out
