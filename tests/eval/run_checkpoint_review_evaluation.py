"""Checkpoint review evaluation and live enablement report (issue #222)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(BASE_DIR))

from service.checkpoint_review_ai import (  # noqa: E402
    CONTEXT_VERSION,
    AssistantStylePreferences,
    bind_review_model,
    build_messages,
    extract_text,
    validate_report,
)
from service import checkpoint_review_ai as checkpoint_review_ai_service  # noqa: E402
from tests.eval import evaluation_runner  # noqa: E402
from tests.eval.checkpoint_review_rubric import evaluate_case  # noqa: E402

REPORT_VERSION = checkpoint_review_ai_service.REPORT_VERSION
checkpoint_review_model_identity = checkpoint_review_ai_service.checkpoint_review_model_identity
evaluate_gate = checkpoint_review_ai_service.evaluate_gate
prompt_version_hash = checkpoint_review_ai_service.prompt_version_hash

DEFAULT_DATASET = Path(__file__).resolve().parent / "datasets" / "checkpoint_review_cases.json"
PRIVACY_SUITE = "tests/test_checkpoint_review_ai_privacy.py"
RUNNER_CONFIG = evaluation_runner.EvaluationRunnerConfig(
    title="checkpoint review",
    description="Checkpoint review evaluation + enablement report (issue #222)",
    suite_name="checkpoint_review",
    dataset_path=DEFAULT_DATASET,
    dataset_label="checkpoint review",
    privacy_suite=PRIVACY_SUITE,
    report_config=checkpoint_review_ai_service._EVALUATION_REPORT_CONFIG,
    context_version=CONTEXT_VERSION,
    ensure_ascii=False,
    no_privacy_help="Skip privacy suite and record the gate as failed.",
    check_report_help="Validate an existing report without loading a model.",
)


def load_cases(dataset_path: Path = DEFAULT_DATASET) -> list[dict[str, Any]]:
    return evaluation_runner.load_cases(dataset_path, "checkpoint review")


def _prompt_text(messages: list[Any]) -> str:
    return "\n".join(str(getattr(message, "content", message)) for message in messages)


def run_suite(
    cases: list[dict[str, Any]] | None = None,
    *,
    model: Any = None,
    dataset_path: Path = DEFAULT_DATASET,
) -> list[dict[str, Any]]:
    if cases is None:
        cases = load_cases(dataset_path)
    if model is None:
        from utils.model_downloader import get_llm

        model = get_llm()
    bound_model = bind_review_model(model)
    results: list[dict[str, Any]] = []
    for case in cases:
        messages = build_messages(
            case.get("facts") or {}, list(case.get("rating") or []), str(case.get("language", "en")),
            preferences=AssistantStylePreferences(
                str(case.get("coach_tone", "direct")),
                str(case.get("custom_instructions", "")),
            ),
        )
        prompt = _prompt_text(messages)
        answer = extract_text(bound_model.invoke(messages))
        result = evaluate_case(case, prompt, answer)
        result["prompt"] = prompt
        results.append(result)
    return results


def run_privacy_suite(base_dir: Path = BASE_DIR) -> bool:
    return evaluation_runner.run_privacy_suite(PRIVACY_SUITE, base_dir)


def build_report(
    results: list[dict[str, Any]],
    *,
    mode: str,
    privacy_pass: bool,
    dataset_path: Path = DEFAULT_DATASET,
) -> dict[str, Any]:
    return evaluation_runner.build_report(
        results,
        mode=mode,
        privacy_pass=privacy_pass,
        dataset_path=dataset_path,
        config=RUNNER_CONFIG,
    )


def write_report(path: Path, report: dict[str, Any]) -> Path:
    return evaluation_runner.write_report(path, report, ensure_ascii=False)


def check_report(report_path: Path) -> tuple[bool, list[str]]:
    return evaluation_runner.check_report(report_path, validate_report, strict=RUNNER_CONFIG.report_config.strict)


def _mock_model():
    from tests.fakes.chat_model import ScriptedChatModel

    return ScriptedChatModel(default_turn="Your recorded training shows steady progress.")


def main(argv: list[str] | None = None) -> int:
    def run_cases(cases: list[dict[str, Any]], mock: bool, dataset_path: Path) -> list[dict[str, Any]]:
        return run_suite(
            cases,
            model=_mock_model() if mock else None,
            dataset_path=dataset_path,
        )

    return evaluation_runner.run_main(
        argv,
        config=RUNNER_CONFIG,
        base_dir=BASE_DIR,
        run_cases=run_cases,
        validator=validate_report,
    )


if __name__ == "__main__":
    raise SystemExit(main())
