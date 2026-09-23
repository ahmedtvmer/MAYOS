"""Judge structured-output dispatch: hosted uses function calling, local default.

Offline only — the judge is a double, no provider call is made.
"""

from unittest.mock import MagicMock


def _evaluation_module():
    from tests.eval import run_evaluation

    return run_evaluation


def _judge_with_result(value):
    judge = MagicMock()
    structured = MagicMock()
    structured.invoke.return_value = value
    judge.with_structured_output.return_value = structured
    return judge


def test_hosted_judge_uses_function_calling(monkeypatch):
    ev = _evaluation_module()
    judge = _judge_with_result("judged")
    schema = object()
    monkeypatch.setattr(ev, "uses_cloud_backend", lambda: True)

    assert ev.safe_invoke_judge(judge, "system", "user", schema) == "judged"
    assert judge.with_structured_output.call_args.args == (schema,)
    assert judge.with_structured_output.call_args.kwargs == {"method": "function_calling"}


def test_local_judge_preserves_default_method(monkeypatch):
    ev = _evaluation_module()
    judge = _judge_with_result("judged")
    schema = object()
    monkeypatch.setattr(ev, "uses_cloud_backend", lambda: False)

    assert ev.safe_invoke_judge(judge, "system", "user", schema) == "judged"
    assert judge.with_structured_output.call_args.args == (schema,)
    assert judge.with_structured_output.call_args.kwargs == {}
