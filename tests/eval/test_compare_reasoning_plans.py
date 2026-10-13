import pytest

from tests.eval.compare_reasoning_plans import _comparison_report


def _comparison_case(index, judge_two_vote, latency_delta, baseline_errors=(), reasoned_errors=()):
    reasoned_first = index % 2 == 0
    option_order = {
        "first": "reasoned" if reasoned_first else "baseline",
        "second": "baseline" if reasoned_first else "reasoned",
    }
    judge_two_choice = (
        "tie"
        if judge_two_vote == "tie"
        else "first" if (judge_two_vote == "reasoned") == reasoned_first else "second"
    )
    return {
        "case_id": f"split-{index}",
        "option_order": option_order,
        "generation_error": None,
        "baseline": {"status": "parsed", "validation_errors": list(baseline_errors), "generation_seconds": 20.0},
        "reasoned": {
            "status": "parsed",
            "validation_errors": list(reasoned_errors),
            "generation_seconds": 20.0 + latency_delta,
        },
        "judges": {"judge_1": {"preferred": "first" if reasoned_first else "second"}, "judge_2": {"preferred": judge_two_choice}},
    }


@pytest.mark.parametrize(
    ("judge_two_votes", "latency_delta", "expected_pass"),
    [
        (["reasoned", "reasoned", "reasoned", "baseline", "tie"], 15.0, True),
        (["reasoned", "reasoned", "baseline", "baseline", "tie"], 10.0, False),
        (["reasoned", "reasoned", "reasoned", "baseline", "tie"], 15.1, False),
    ],
)
def test_paired_comparison_gate_requires_both_judges_and_latency(
    judge_two_votes, latency_delta, expected_pass
):
    cases = [_comparison_case(index, vote, latency_delta) for index, vote in enumerate(judge_two_votes)]
    report = _comparison_report(cases, metadata=[])

    assert report["passed"] is expected_pass


SANITIZED = "DynamicSplitPlan required sanitizing or deterministic fallback"
VOTES = ["reasoned", "reasoned", "reasoned", "baseline", "tie"]


@pytest.mark.parametrize(
    ("baseline_errors", "reasoned_errors", "expected_pass"),
    [
        ((SANITIZED,), (), True),
        ((SANITIZED,), (SANITIZED,), True),
        ((), (SANITIZED,), False),
        ((), ("DynamicSplitPlan must contain 4 non-empty days",), False),
    ],
)
def test_sanitized_baseline_plans_are_still_compared(baseline_errors, reasoned_errors, expected_pass):
    cases = [
        _comparison_case(index, vote, 5.0, baseline_errors, reasoned_errors)
        for index, vote in enumerate(VOTES)
    ]
    report = _comparison_report(cases, metadata=[])

    assert report["passed"] is expected_pass


def test_pairs_are_judged_when_the_baseline_plan_needed_sanitizing(monkeypatch):
    import tests.eval.compare_reasoning_plans as module

    arm = {"status": "parsed", "validation_errors": [SANITIZED], "program": {"days": []}}
    record = {"baseline": arm, "reasoned": {**arm, "validation_errors": []}, "judges": {}}
    context = type("Context", (), {"judges": [{"name": "judge_1"}]})()
    judged = []

    monkeypatch.setattr(
        module, "_judge_pair", lambda judge, *_: judged.append(judge["name"]) or {"preferred": "first"}
    )
    result = module._judge_valid_pair({}, record, module.BlindProgramPair({}, {}, {}), context)

    assert judged == ["judge_1"]
    assert "generation_error" not in result


class _ScriptedPlanModel:
    model_name = "deepseek-ai/DeepSeek-V4-Flash"

    def __init__(self, plan):
        self.plan = plan

    def with_structured_output(self, _schema, **_options):
        return self

    def bind(self, **_options):
        return self

    def invoke(self, _prompt):
        from langchain_core.messages import AIMessage

        return {
            "raw": AIMessage(content="", response_metadata={"finish_reason": "stop"}),
            "parsed": self.plan,
            "parsing_error": None,
        }


def test_generation_arm_validates_a_realistic_plan_end_to_end(fresh_store):
    from agent.program_rules import get_default_split
    from tests.eval.compare_reasoning_plans import ComparisonContext, _generation_arm
    from tests.eval.parity_gate import RetryPolicy
    from tests.eval.suites import structured_output

    case = structured_output._load_cases()["split_plans"][0]
    model = _ScriptedPlanModel(get_default_split(case["frequency"], case["gender"]))
    context = ComparisonContext(model, fresh_store, [], RetryPolicy(max_attempts=1))

    for arm in ("baseline", "reasoned"):
        result = _generation_arm(case, context, arm)

        assert result["status"] == "parsed"
        assert result["validation_errors"] == []
        assert len(result["program"]["days"]) == case["frequency"]
