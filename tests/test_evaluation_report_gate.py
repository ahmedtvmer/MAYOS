"""Public behavior shared by the Coach AI and Checkpoint review gates."""

from __future__ import annotations

import json

import pytest

from service import checkpoint_review_ai, coach_ai


@pytest.mark.parametrize(
    ("gate", "enabled_flag", "report_var", "identity", "prompt_hash"),
    [
        (
            coach_ai,
            "COACH_AI_ENABLED",
            "COACH_AI_EVAL_REPORT",
            coach_ai.coach_model_identity,
            coach_ai.prompt_version_hash,
        ),
        (
            checkpoint_review_ai,
            "CHECKPOINT_REVIEW_AI_ENABLED",
            "CHECKPOINT_REVIEW_EVAL_REPORT",
            checkpoint_review_ai.checkpoint_review_model_identity,
            checkpoint_review_ai.prompt_version_hash,
        ),
    ],
)
def test_live_report_enables_only_its_configured_feature(
    gate, enabled_flag, report_var, identity, prompt_hash, monkeypatch, tmp_path
):
    model, backend = identity()
    report = {
        "report_version": gate.REPORT_VERSION,
        "suite": "coach_assistant" if gate is coach_ai else "checkpoint_review",
        "mode": "live",
        "prompt_hash": prompt_hash(),
        "model": model,
        "backend": backend,
        "gates": {
            "privacy": {"pass": True},
            "evaluation": {"pass": True, "threshold": 1},
        },
        "runs": [{"case_id": "one", "passed": True, "checks": {}}],
        "pass": True,
    }
    report_path = tmp_path / "live-evaluation-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setenv(enabled_flag, "true")
    monkeypatch.setenv(report_var, str(report_path))

    status = gate.resolve_enable_gate()

    assert status.requested is True
    assert status.enabled is True


@pytest.mark.parametrize(
    ("gate", "enabled_flag", "report_var"),
    [
        (coach_ai, "COACH_AI_ENABLED", "COACH_AI_EVAL_REPORT"),
        (
            checkpoint_review_ai,
            "CHECKPOINT_REVIEW_AI_ENABLED",
            "CHECKPOINT_REVIEW_EVAL_REPORT",
        ),
    ],
)
def test_mock_report_never_enables_feature(gate, enabled_flag, report_var, monkeypatch, tmp_path):
    report_path = tmp_path / "mock-report.json"
    report_path.write_text(
        json.dumps(
            {
                "report_version": gate.REPORT_VERSION,
                "mode": "mock",
                "prompt_hash": gate.prompt_version_hash(),
                "model": gate.coach_model_identity()[0]
                if gate is coach_ai
                else gate.checkpoint_review_model_identity()[0],
                "backend": gate.coach_model_identity()[1]
                if gate is coach_ai
                else gate.checkpoint_review_model_identity()[1],
                "gates": {
                    "privacy": {"pass": True},
                    "evaluation": {"pass": True, "threshold": 1},
                },
                "runs": [{"case_id": "one", "passed": True, "checks": {}}],
                "pass": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(enabled_flag, "true")
    monkeypatch.setenv(report_var, str(report_path))

    assert gate.resolve_enable_gate().enabled is False
