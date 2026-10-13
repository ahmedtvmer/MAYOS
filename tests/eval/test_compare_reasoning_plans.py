import pytest

from tests.eval.compare_reasoning_plans import _comparison_report


def _comparison_case(index, judge_two_vote, latency_delta):
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
        "baseline": {"status": "parsed", "validation_errors": [], "generation_seconds": 20.0},
        "reasoned": {"status": "parsed", "validation_errors": [], "generation_seconds": 20.0 + latency_delta},
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
