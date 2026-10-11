"""Hosted judge structured-output dispatch without provider traffic."""

from tests.fakes.chat_model import ScriptedChatModel


def _evaluation_module():
    from tests.eval import run_evaluation

    return run_evaluation


def test_hosted_judge_uses_function_calling():
    ev = _evaluation_module()
    judge = ScriptedChatModel(['"judged"'])
    schema = str
    assert ev.safe_invoke_judge(judge, "system", "user", schema) == "judged"
    assert len(judge.calls) == 1
    assert judge.calls[0]["mode"] == "structured"
    assert judge.calls[0]["kwargs"]["method"] == "function_calling"


def test_removed_onboarding_cases_are_skipped_without_changing_count():
    ev = _evaluation_module()

    skipped = ev.skip_onboarding_cases([{"id": "onb-1"}, {"id": "onb-2"}])

    assert len(skipped) == 2
    assert all(item["skipped"] and not item["passed"] for item in skipped)
    assert all(
        item["skip_reason"] == "removed by #188, cases deleted in #189"
        for item in skipped
    )
