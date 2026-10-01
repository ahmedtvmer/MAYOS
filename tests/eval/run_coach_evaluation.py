# tests/eval/run_coach_evaluation.py
"""Coach assistant evaluation runner and enablement report (issue #45, ADR 049).

Two gates decide whether ``COACH_AI_ENABLED`` may turn the feature on:

1. **Privacy** — ``tests/test_coach_ai_privacy.py`` (hermetic, mock LLM).
2. **Evaluation** — this runner, which builds the *production* prompt for each
   fixture case (``service.coach_ai.render_context`` + ``build_messages``),
   asks the coach model, and scores the answer with the deterministic rubric in
   ``tests/eval/coach_rubric.py``.

``--write-report PATH`` runs both gates and records the JSON the service checks
at startup (``COACH_AI_EVAL_REPORT``): ``pass``, the current ``prompt_hash``,
the configured coach ``model``/``backend``, and both gate results. The service
re-derives the verdict from the recorded runs with the *same*
``service.coach_ai.evaluate_gate`` this runner uses, so the report and the gate
can never disagree. ``--check-report PATH`` re-checks an existing report
without loading any model (it calls the same shared validator);
``--mock`` is a plumbing run against the in-repo mock model and is what pytest
exercises; the real-model run is what the owner records.

Usage::

    python tests/eval/run_coach_evaluation.py --check-report reports/coach_ai_eval.json
    python tests/eval/run_coach_evaluation.py --mock
    python tests/eval/run_coach_evaluation.py --write-report reports/coach_ai_eval.json
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from service.coach_ai import (  # noqa: E402  (path bootstrap first, mirrors run_evaluation.py)
    CONTEXT_VERSION,
    build_messages,
    extract_answer,
    render_context,
    validate_report,
)
from service import coach_ai as coach_ai_service  # noqa: E402
from tests.eval import evaluation_runner  # noqa: E402
from tests.eval.coach_rubric import evaluate_case  # noqa: E402

REPORT_VERSION = coach_ai_service.REPORT_VERSION
coach_model_identity = coach_ai_service.coach_model_identity
evaluate_gate = coach_ai_service.evaluate_gate
prompt_version_hash = coach_ai_service.prompt_version_hash

DEFAULT_DATASET = Path(__file__).resolve().parent / "datasets" / "coach_assistant_cases.json"
PRIVACY_SUITE = "tests/test_coach_ai_privacy.py"
RUNNER_CONFIG = evaluation_runner.EvaluationRunnerConfig(
    title="coach assistant",
    description="Coach assistant evaluation + enablement report (issue #45)",
    suite_name="coach_assistant",
    dataset_path=DEFAULT_DATASET,
    dataset_label="coach",
    privacy_suite=PRIVACY_SUITE,
    report_config=coach_ai_service._EVALUATION_REPORT_CONFIG,
    context_version=CONTEXT_VERSION,
    ensure_ascii=True,
    no_privacy_help="Do not run the privacy suite; records the privacy gate as failed.",
    check_title="coach",
    check_report_help="Re-check an existing report without loading any model.",
)


def load_cases(dataset_path: Path = DEFAULT_DATASET) -> list[dict[str, Any]]:
    return evaluation_runner.load_cases(dataset_path, "coach")


def _prompt_text(messages: list[Any]) -> str:
    return "\n".join(str(getattr(message, "content", message)) for message in messages)


def run_suite(
    cases: list[dict[str, Any]] | None = None,
    *,
    model: Any = None,
    dataset_path: Path = DEFAULT_DATASET,
) -> list[dict[str, Any]]:
    """Builds the production prompt per case, asks the model, and rubrics the answer."""
    if cases is None:
        cases = load_cases(dataset_path)
    if model is None:
        from utils.model_downloader import get_coach_llm

        model = get_coach_llm()

    results: list[dict[str, Any]] = []
    for case in cases:
        context_text = render_context(case.get("facts") or {})
        messages = build_messages(
            context_text, str(case.get("question", "")), list(case.get("history") or [])
        )
        # Production applies the same extraction/finalization to the reply (ADR 049).
        answer = extract_answer(model.invoke(messages))
        result = evaluate_case(case, context_text, answer, prompt_text=_prompt_text(messages))
        result["context"] = context_text
        results.append(result)
    return results


def run_privacy_suite(base_dir: Path = BASE_DIR) -> bool:
    """Runs the hermetic privacy suite in a subprocess; records its verdict."""
    return evaluation_runner.run_privacy_suite(PRIVACY_SUITE, base_dir)


def build_report(
    results: list[dict[str, Any]],
    *,
    mode: str,
    privacy_pass: bool,
    dataset_path: Path = DEFAULT_DATASET,
) -> dict[str, Any]:
    """Assembles the enablement report: provenance, both gates, and the runs."""
    return evaluation_runner.build_report(
        results,
        mode=mode,
        privacy_pass=privacy_pass,
        dataset_path=dataset_path,
        config=RUNNER_CONFIG,
    )


def write_report(path: Path, report: dict[str, Any]) -> Path:
    return evaluation_runner.write_report(path, report, ensure_ascii=True)


def check_report(report_path: Path) -> tuple[bool, list[str]]:
    """Re-checks a produced report without loading any model.

    Delegates to the service's shared validator, so ``--check-report`` and the
    startup gate accept and reject exactly the same reports.
    """
    return evaluation_runner.check_report(report_path, validate_report, strict=RUNNER_CONFIG.report_config.strict)


def _mock_model():
    from utils.model_downloader import MockSafeChatLlamaCpp

    return MockSafeChatLlamaCpp()


def main(argv: list[str] | None = None) -> int:
    def run_cases(cases: list[dict[str, Any]], mock: bool, dataset_path: Path) -> list[dict[str, Any]]:
        return run_suite(cases, model=_mock_model() if mock else None, dataset_path=dataset_path)

    return evaluation_runner.run_main(
        argv,
        config=RUNNER_CONFIG,
        base_dir=BASE_DIR,
        run_cases=run_cases,
        validator=validate_report,
    )


if __name__ == "__main__":
    raise SystemExit(main())
