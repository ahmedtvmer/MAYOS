from copy import deepcopy

import pytest

from tests.eval.compare_player_chat import compare_reports


def _report():
    return {
        "mode": "live", "partial": False, "player_model": "same-player-model", "judges": [],
        "gate": {"passed": True},
        "suite_results": {
            "routing": {"cases": [{"case_id": "options", "passed": True}]},
            "coaching_qa": {"runs": [{"run": 1, "cases": [{"case_id": "safety", "passed": True,
                "judges": {"judge_1": {"judgment": {"clinical_safety": {"score": 5}}}}}]}]},
        },
    }


@pytest.mark.parametrize("failure", ["lost_task", "clinical_miss", "unauthorized", "before_confirmation", "judge_safety"])
def test_comparison_rejects_task_or_safety_regressions_even_when_candidate_gate_passes(failure):
    before = _report()
    after = deepcopy(before)
    case = after["suite_results"]["routing"]["cases"][0]
    if failure == "lost_task":
        case["passed"] = False
    elif failure == "clinical_miss":
        case["clinical_miss"] = True
    elif failure == "unauthorized":
        case["unauthorized_actions"] = [{"kind": "program_mutation"}]
    elif failure == "before_confirmation":
        case["preconfirmation_writes"] = [{"kind": "program_mutation"}]
    else:
        after["suite_results"]["coaching_qa"]["runs"][0]["cases"][0]["judges"]["judge_1"]["judgment"]["clinical_safety"]["score"] = 4

    result = compare_reports(before, after)

    assert result["passed"] is False
    assert result["regressions"]


def test_comparison_includes_repeated_qa_runs_without_merging_case_ids():
    report = _report()
    second = deepcopy(report["suite_results"]["coaching_qa"]["runs"][0])
    second["run"] = 2
    report["suite_results"]["coaching_qa"]["runs"].append(second)

    result = compare_reports(report, deepcopy(report))

    assert result["passed"] is True
    assert result["suites"]["coaching_qa"]["cases"] == 2


@pytest.mark.parametrize("mutation", ["partial", "hermetic", "different_cases"])
def test_comparison_refuses_incomparable_reports(mutation):
    before, after = _report(), _report()
    if mutation == "partial":
        after["partial"] = True
    elif mutation == "hermetic":
        before["mode"] = "hermetic"
    else:
        after["suite_results"]["routing"]["cases"][0]["case_id"] = "different"

    with pytest.raises(ValueError):
        compare_reports(before, after)
