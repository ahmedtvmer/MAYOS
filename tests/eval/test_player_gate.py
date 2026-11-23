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
from tests.eval.schemas import CoachingQAEvalJudgment
from utils.model_downloader import CLOUD_MODEL_REGISTRY, JUDGE_MODEL_ROLES

DIMENSION_NAMES = (
    "groundedness",
    "biomechanical_validity",
    "clinical_safety",
    "structural_budget",
    "persona_adherence",
)


def _judgment() -> dict:
    return {name: {"score": 5, "rationale": "Safe and grounded."} for name in DIMENSION_NAMES}


def _failing_judgment() -> dict:
    judgment = _judgment()
    judgment["groundedness"] = {"score": 3, "rationale": "Not grounded."}
    return judgment


def _passing_case(case_id: str) -> dict:
    return {
        "case_id": case_id,
        "passed": True,
        "judges": {
            "judge_1": {"model": "google/gemma-4-31B-it", "passed": True, "judgment": _judgment(), "attempts": 1, "error": None},
            "judge_2": {"model": "zai-org/GLM-5.3", "passed": True, "judgment": _judgment(), "attempts": 1, "error": None},
        },
    }


def _failing_case(case_id: str) -> dict:
    return {
        "case_id": case_id,
        "passed": False,
        "judges": {
            "judge_1": {"model": "google/gemma-4-31B-it", "passed": False, "judgment": _failing_judgment(), "attempts": 1, "error": None},
            "judge_2": {"model": "zai-org/GLM-5.3", "passed": False, "judgment": _failing_judgment(), "attempts": 1, "error": None},
        },
    }


def _partly_unscored_case(case_id: str) -> dict:
    """Judge 1 could not be read; judge 2 read and passed the case."""
    return {
        "case_id": case_id,
        "passed": False,
        "judges": {
            "judge_1": {"model": "google/gemma-4-31B-it", "unscored": True, "judgment": None, "attempts": 2, "error": "unreadable judge answer"},
            "judge_2": {"model": "zai-org/GLM-5.3", "passed": True, "judgment": _judgment(), "attempts": 1, "error": None},
        },
    }


def _partly_unscored_failing_case(case_id: str) -> dict:
    """Judge 1 could not be read; judge 2 read and failed the case ordinarily."""
    judgment = _judgment()
    judgment["structural_budget"] = {"score": 3, "rationale": "Over budget."}
    return {
        "case_id": case_id,
        "passed": False,
        "judges": {
            "judge_1": {"model": "google/gemma-4-31B-it", "unscored": True, "judgment": None, "attempts": 2, "error": "unreadable judge answer"},
            "judge_2": {"model": "zai-org/GLM-5.3", "passed": False, "judgment": judgment, "attempts": 1, "error": None},
        },
    }


class ProviderError(RuntimeError):
    def __init__(self, status_code: int):
        super().__init__(f"provider returned {status_code}")
        self.status_code = status_code


def test_judge_configuration_defaults_come_from_the_shared_registry():
    judges = configured_judges({})

    assert [judge["model"] for judge in judges] == [
        CLOUD_MODEL_REGISTRY[role]["default_model"] for role in JUDGE_MODEL_ROLES
    ]
    assert [judge["family"] for judge in judges] == ["gemma", "glm"]
    assert judges[0]["family"] != judges[1]["family"]


def test_gemma_model_ids_report_the_gemma_family():
    from tests.eval.parity_gate import _model_family

    assert _model_family("google/gemma-4-31B-it") == "gemma"


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


@pytest.mark.parametrize("bare", [5, "5"])
def test_bare_number_dimension_answers_parse_and_score(bare):
    judgment = CoachingQAEvalJudgment.model_validate({name: bare for name in DIMENSION_NAMES})

    assert judgment.is_passed is True
    assert judgment.clinical_safety.score == 5
    assert judgment.clinical_safety.rationale == ""


@pytest.mark.parametrize("bare", [0, 6, 4.5, True, "five"])
def test_ambiguous_bare_number_dimension_answers_stay_invalid(bare):
    with pytest.raises(ValidationError):
        CoachingQAEvalJudgment.model_validate({name: bare for name in DIMENSION_NAMES})


def test_unreadable_judge_answer_is_marked_unscored_not_failed():
    from tests.eval.run_evaluation import _score_case, evaluate_case

    class Payload(BaseModel):
        count: int

    with pytest.raises(ValidationError) as raised:
        Payload(count="not-an-integer")
    calls = 0

    class UnreadableJudgeClient:
        def with_structured_output(self, *_args, **_kwargs):
            return self

        def invoke(self, _messages):
            nonlocal calls
            calls += 1
            raise raised.value

    class PassingJudgeClient:
        def with_structured_output(self, *_args, **_kwargs):
            return self

        def invoke(self, _messages):
            return CoachingQAEvalJudgment.model_validate(_judgment())

    case = evaluate_case(
        {"id": "case-1", "query": "Question"},
        "Reply",
        [
            {"name": "judge_1", "model": "google/gemma-4-31B-it", "client": UnreadableJudgeClient()},
            {"name": "judge_2", "model": "zai-org/GLM-5.3", "client": PassingJudgeClient()},
        ],
        RetryPolicy(max_attempts=4),
    )

    unscored = case["judges"]["judge_1"]
    assert unscored["unscored"] is True
    assert "passed" not in unscored
    assert unscored["judgment"] is None
    assert unscored["attempts"] == 2
    assert "count" in unscored["error"]
    assert calls == 2
    assert case["judges"]["judge_2"]["passed"] is True

    case_score = _score_case(case, {"judge_1": "google/gemma-4-31B-it", "judge_2": "zai-org/GLM-5.3"})
    assert case_score.unscored_judges == {"judge_1": unscored["error"]}
    assert case_score.reasons == []


def test_transport_failure_after_retries_keeps_the_record_failed():
    from tests.eval.run_evaluation import evaluate_case

    calls = 0

    class TimeoutJudgeClient:
        def with_structured_output(self, *_args, **_kwargs):
            return self

        def invoke(self, _messages):
            nonlocal calls
            calls += 1
            raise httpx.ConnectError("connection failed")

    case = evaluate_case(
        {"id": "case-1", "query": "Question"},
        "Reply",
        [{"name": "judge_1", "model": "google/gemma-4-31B-it", "client": TimeoutJudgeClient()}],
        RetryPolicy(2, 0, 0),
    )

    record = case["judges"]["judge_1"]
    assert record["passed"] is False
    assert "unscored" not in record
    assert calls == 2


def test_unscored_cases_stay_out_of_the_score_bar_and_judge_scores():
    from tests.eval import run_evaluation

    suite = run_evaluation.CoachingQASuite(
        "coaching_qa", "unused.json", 2, run_evaluation.ScoreBar("percent", 100)
    )

    summary, reasons = run_evaluation._summarize_run(
        suite, 1, {"run": 1, "cases": [_partly_unscored_case("case-unscored"), _passing_case("case-passing")]}, {}
    )

    assert reasons == []
    assert summary["score"] == 1
    assert summary["total"] == 2
    assert summary["judge_scores"] == {"judge_1": 1, "judge_2": 1}
    assert summary["clinical_safety_failures"] == []
    assert summary["unscored"] == [
        {"case_id": "case-unscored", "judges": {"judge_1": "unreadable judge answer"}}
    ]
    # The 100% bar is checked against the scored cases only, so the unscored
    # case counts as neither a pass nor a fail.
    assert summary["passed"] is True


def test_count_bar_failure_allowance_ignores_unscored_cases():
    from tests.eval import run_evaluation

    suite = run_evaluation.CoachingQASuite("coaching_qa", "unused.json", 25, run_evaluation.ScoreBar("count", 22))
    cases = [
        *(_passing_case(f"case-pass-{index}") for index in range(18)),
        *(_failing_case(f"case-fail-{index}") for index in range(3)),
        *(_partly_unscored_case(f"case-unscored-{index}") for index in range(4)),
    ]

    summary, reasons = run_evaluation._summarize_run(suite, 1, {"run": 1, "cases": cases}, {})

    # The three scored failures use up the 22/25 allowance exactly; the four
    # unscored cases count as neither a pass nor a fail.
    assert reasons == []
    assert summary["score"] == 18
    assert summary["total"] == 25
    assert summary["judge_scores"] == {"judge_1": 18, "judge_2": 18}
    assert [entry["case_id"] for entry in summary["unscored"]] == [f"case-unscored-{index}" for index in range(4)]
    assert summary["passed"] is True


def test_count_bar_fails_when_scored_failures_exceed_the_allowance():
    from tests.eval import run_evaluation

    suite = run_evaluation.CoachingQASuite("coaching_qa", "unused.json", 25, run_evaluation.ScoreBar("count", 22))
    cases = [
        *(_passing_case(f"case-pass-{index}") for index in range(17)),
        *(_failing_case(f"case-fail-{index}") for index in range(4)),
        *(_partly_unscored_case(f"case-unscored-{index}") for index in range(4)),
    ]

    summary, reasons = run_evaluation._summarize_run(suite, 1, {"run": 1, "cases": cases}, {})

    assert summary["passed"] is False
    assert summary["score"] == 17
    assert summary["unscored"] == [
        {"case_id": f"case-unscored-{index}", "judges": {"judge_1": "unreadable judge answer"}} for index in range(4)
    ]
    assert reasons == ["coaching_qa run 1: score 17/21 below required bar 22/25 (4 unscored)"]


def test_run_with_only_unscored_cases_fails():
    from tests.eval import run_evaluation

    suite = run_evaluation.CoachingQASuite("coaching_qa", "unused.json", 2, run_evaluation.ScoreBar("count", 2))

    summary, reasons = run_evaluation._summarize_run(
        suite, 1, {"run": 1, "cases": [_partly_unscored_case("case-a"), _partly_unscored_case("case-b")]}, {}
    )

    assert summary["passed"] is False
    assert summary["score"] == 0
    assert len(summary["unscored"]) == 2
    assert reasons == ["coaching_qa run 1: score 0/0 below required bar 2/2 (2 unscored)"]


def test_readable_clinical_failure_is_not_hidden_by_an_unreadable_judge():
    from tests.eval import run_evaluation

    unsafe = _judgment()
    unsafe["clinical_safety"] = {"score": 2, "rationale": "Diagnosed an injury."}
    case = {
        "case_id": "case-1",
        "passed": False,
        "judges": {
            "judge_1": {"model": "google/gemma-4-31B-it", "unscored": True, "judgment": None, "attempts": 2, "error": "unreadable judge answer"},
            "judge_2": {"model": "zai-org/GLM-5.3", "passed": False, "judgment": unsafe, "attempts": 1, "error": None},
        },
    }

    case_score = run_evaluation._score_case(case, {})

    assert case_score.passed is False
    assert case_score.unscored_judges == {}
    assert case_score.unreadable_judges == {"judge_1": "unreadable judge answer"}
    assert case_score.safety_failures == [{"case_id": "case-1", "judge": "judge_2", "score": 2}]
    assert "case case-1: judge_2 clinical_safety=2, required 5" in case_score.reasons
    assert not any("unreadable" in reason for reason in case_score.reasons)

    suite = run_evaluation.CoachingQASuite("coaching_qa", "unused.json", 1, run_evaluation.ScoreBar("count", 1))
    summary, reasons = run_evaluation._summarize_run(suite, 1, {"run": 1, "cases": [case]}, {})

    assert summary["unscored"] == []
    assert summary["unreadable_in_failed_cases"] == [
        {"case_id": "case-1", "judges": {"judge_1": "unreadable judge answer"}}
    ]
    assert summary["clinical_safety_failures"] == [{"case_id": "case-1", "judge": "judge_2", "score": 2}]
    assert summary["score"] == 0
    assert summary["passed"] is False


def test_unreadable_judge_alongside_an_ordinary_failure_counts_as_one_failure():
    from tests.eval import run_evaluation

    suite = run_evaluation.CoachingQASuite("coaching_qa", "unused.json", 2, run_evaluation.ScoreBar("count", 1))

    summary, reasons = run_evaluation._summarize_run(
        suite,
        1,
        {"run": 1, "cases": [_partly_unscored_failing_case("case-a"), _passing_case("case-b")]},
        {},
    )

    # The readable failure uses up the one-failure allowance exactly; the
    # unreadable judge is recorded without failing the run.
    assert reasons == []
    assert summary["score"] == 1
    assert summary["total"] == 2
    assert summary["judge_scores"] == {"judge_1": 1, "judge_2": 1}
    assert summary["clinical_safety_failures"] == []
    assert summary["unscored"] == []
    assert summary["unreadable_in_failed_cases"] == [
        {"case_id": "case-a", "judges": {"judge_1": "unreadable judge answer"}}
    ]
    assert summary["passed"] is True


def test_stored_bare_number_judgments_rescore_from_dimension_scores():
    from tests.eval.run_evaluation import _score_case

    judge_models = {"judge_1": "google/gemma-4-31B-it", "judge_2": "zai-org/GLM-5.3"}
    case = {
        "case_id": "case-1",
        "passed": True,
        "judges": {
            name: {
                "model": model,
                "passed": True,
                "judgment": {dimension: 5 for dimension in DIMENSION_NAMES},
                "attempts": 1,
                "error": None,
            }
            for name, model in judge_models.items()
        },
    }

    case_score = _score_case(case, judge_models)

    assert case_score.passed is True
    assert case_score.reasons == []
    assert case_score.safety_failures == []


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
        lambda _case, _run_number: (_ for _ in ()).throw(RuntimeError("player backend timed out")),
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


def test_injury_saved_by_clinical_case_is_not_visible_to_next_case(monkeypatch):
    from types import SimpleNamespace

    from agent import assistant_graph as graph_module
    from database import database_manager
    from tests.eval import run_evaluation

    ledger_state = {}

    class Ledger:
        def __init__(self, trainee_id):
            self.injuries = ledger_state.setdefault(trainee_id, [])

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return False

    class Database:
        catalog_conn = SimpleNamespace(close=lambda: None)

        def open_ledger(self, trainee_id):
            return Ledger(trainee_id)

    def invoke(state, config):
        ledger = config["configurable"]["ledger"]
        if state["messages"][-1].content == "clinical injury":
            ledger.injuries.append("unknown body area")
        else:
            assert ledger.injuries == []
        return {"response_content": "Recorded."}

    monkeypatch.setattr(database_manager, "DatabaseManager", Database)
    monkeypatch.setattr(graph_module, "assistant_graph", SimpleNamespace(invoke=invoke))

    run_evaluation._generate_reply({"id": "clinical", "query": "clinical injury"})
    run_evaluation._generate_reply({"id": "stateless-follow-up", "query": "unrelated question"})

    assert sorted(ledger_state.values(), key=len) == [[], ["unknown body area"]]
