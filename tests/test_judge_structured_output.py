"""The player gate records structured verdicts from both hosted judges."""

from tests.eval.parity_gate import RetryPolicy
from tests.eval.run_evaluation import evaluate_case
from tests.fakes.chat_model import ScriptedChatModel


def _passing_judgment() -> dict:
    return {
        name: {"score": 5, "rationale": "The response is safe and grounded."}
        for name in (
            "groundedness",
            "biomechanical_validity",
            "clinical_safety",
            "structural_budget",
            "persona_adherence",
        )
    }


def test_player_case_records_both_structured_judge_verdicts():
    qwen = ScriptedChatModel([_passing_judgment()])
    glm = ScriptedChatModel([_passing_judgment()])
    judges = [
        {"name": "judge_1", "model": "Qwen/Qwen3.5-27B", "client": qwen},
        {"name": "judge_2", "model": "zai-org/GLM-5.3", "client": glm},
    ]

    result = evaluate_case(
        {"id": "qa_case", "query": "How should I train?", "telemetry": "No workout logged."},
        "Use controlled reps.",
        judges,
        RetryPolicy(max_attempts=1),
    )

    assert result["passed"] is True
    assert {name: verdict["passed"] for name, verdict in result["judges"].items()} == {
        "judge_1": True,
        "judge_2": True,
    }
    assert all(verdict["judgment"]["clinical_safety"]["score"] == 5 for verdict in result["judges"].values())
    assert qwen.calls[0]["kwargs"]["method"] == "function_calling"
    assert glm.calls[0]["kwargs"]["method"] == "function_calling"
