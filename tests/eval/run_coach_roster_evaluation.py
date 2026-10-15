"""Offline-testable evaluation runner for the Coach roster assistant (#311)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from service import coach_roster_ai as roster_ai  # noqa: E402
from service.coach_ai import extract_answer  # noqa: E402
from tests.eval import evaluation_runner  # noqa: E402

DEFAULT_DATASET = (
    Path(__file__).resolve().parent
    / "datasets"
    / "coach_roster_assistant_cases.json"
)
PRIVACY_SUITE = "tests/test_coach_roster_ai_privacy.py"
_EN_NAME_REFUSAL = re.compile(
    r"\b(?:can(?:not|'t)\s+(?:see|access)\s+(?:the\s+)?(?:player\s+)?names?"
    r"|(?:player\s+)?names?\s+(?:aren't|are not|not)\s+"
    r"(?:currently\s+)?(?:visible|available|shown)"
    r"|(?:player\s+)?names?\s+(?:are\s+)?unavailable)\b",
    re.IGNORECASE,
)
_AR_NAME_REFUSAL_PATTERNS = (
    re.compile(
        r"لا\s+(?:أستطيع|استطيع|يمكنني)\s+(?:رؤية|مشاهدة|الوصول\s+إلى)\s+"
        r"(?:الأسماء|الاسماء|أسماء|اسماء)(?:\s+اللاعبين)?"
    ),
    re.compile(
        r"(?:الأسماء|الاسماء|أسماء|اسماء)(?:\s+اللاعبين)?\s+"
        r"(?:غير\s+(?:ظاهرة|متاحة|متوفرة|مرئية)|مش\s+(?:ظاهرة|متاحة|متوفرة)|"
        r"ليست\s+(?:ظاهرة|متاحة|متوفرة))"
    ),
)
_EN_INSUFFICIENT_MARKER = re.compile(
    r"\b(?:no data|not available|does not contain|not in (?:the )?snapshot|"
    r"isn't recorded|is not recorded|no record)\b",
    re.IGNORECASE,
)
_AR_INSUFFICIENT_MARKERS = (
    "لا يحتوي",
    "لا توجد بيانات",
    "لا يوجد سجل",
    "لا توجد سجلات",
    "غير متوفر",
    "غير مسجل",
    "مش موجود",
    "مش متاح",
    "مش متسجل",
    "مفيش بيانات",
    "مفيش سجل",
)


def load_dataset(path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    """Loads the roster eval's snapshot-indexed fixture format."""
    dataset = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(dataset, dict) or not isinstance(dataset.get("cases"), list):
        raise ValueError(f"Invalid coach roster eval dataset: {path}")
    if not dataset["cases"] or not isinstance(dataset.get("snapshots"), dict):
        raise ValueError(f"Coach roster eval dataset is incomplete: {path}")
    return dataset


def _load_cases_for_runner(
    path: Path, dataset_label: str
) -> list[dict[str, Any]]:
    """Adapts snapshot-indexed fixtures to the shared Evaluation runner."""
    if dataset_label != "coach roster":
        raise ValueError(f"Unexpected roster eval dataset label: {dataset_label}")
    dataset = load_dataset(path)
    return [
        {
            **case,
            "_snapshot": dataset["snapshots"][case["snapshot"]],
            "_privacy_seeds": dataset.get("privacy_seeds") or [],
        }
        for case in dataset["cases"]
    ]


RUNNER_CONFIG = evaluation_runner.EvaluationRunnerConfig(
    title="Coach roster",
    description="Coach roster assistant evaluation + enablement report (issue #311)",
    suite_name="coach_roster_assistant",
    dataset_path=DEFAULT_DATASET,
    dataset_label="coach roster",
    privacy_suite=PRIVACY_SUITE,
    report_config=roster_ai._EVALUATION_REPORT_CONFIG,
    context_version=roster_ai.CONTEXT_VERSION,
    ensure_ascii=False,
    no_privacy_help="Do not run the privacy suite; records the privacy gate as failed.",
    case_loader=_load_cases_for_runner,
    check_title="coach roster",
)


def _prompt_text(messages: list[Any]) -> str:
    return "\n".join(
        str(getattr(message, "content", message)) for message in messages
    )


def _evaluate_case(
    case: dict[str, Any],
    snapshot: dict[str, Any],
    answer: str,
    prompt_text: str,
    privacy_seeds: list[str],
) -> dict[str, Any]:
    expected = case.get("expect") or {}
    found_ids = set(roster_ai.PLAYER_ALIAS_PATTERN.findall(answer))
    snapshot_ids = {str(row["player_id"]) for row in snapshot.get("players", [])}
    expected_ids = set(expected.get("player_ids") or [])
    forbidden_ids = set(expected.get("forbidden_player_ids") or [])
    forbidden_observed = found_ids & forbidden_ids
    id_check = {
        "passed": (
            expected_ids <= found_ids
            and found_ids <= snapshot_ids
            and not forbidden_observed
        ),
        "expected": sorted(expected_ids),
        "forbidden": sorted(forbidden_ids),
        "observed_forbidden": sorted(forbidden_observed),
        "observed": sorted(found_ids),
    }
    missing_figures = [
        figure for figure in expected.get("figures", []) if figure not in answer
    ]
    figure_check = {"passed": not missing_figures, "missing": missing_figures}
    refusal_observed = (
        bool(_EN_NAME_REFUSAL.search(answer))
        if case["question"].isascii()
        else any(pattern.search(answer) for pattern in _AR_NAME_REFUSAL_PATTERNS)
    )
    refusal_check = {
        "passed": refusal_observed is bool(expected.get("refusal")),
        "expected": bool(expected.get("refusal")),
        "observed": refusal_observed,
    }
    insufficient_observed = _has_insufficient_data_marker(
        answer, arabic=not case["question"].isascii()
    )
    insufficient_check = {
        "passed": insufficient_observed is bool(expected.get("insufficient")),
        "expected": bool(expected.get("insufficient")),
        "observed": insufficient_observed,
    }
    leaked = [seed for seed in privacy_seeds if seed and seed in prompt_text]
    privacy_check = {"passed": not leaked, "leaked": leaked}
    checks = {
        "correct_player_ids": id_check,
        "uses_supplied_figures": figure_check,
        "refuses_name_requests": refusal_check,
        "states_insufficient_data": insufficient_check,
        "no_roster_identifiers_in_prompt": privacy_check,
    }
    return {
        "case_id": case["id"],
        "question": case["question"],
        "answer": answer,
        "checks": checks,
        "passed": all(check["passed"] for check in checks.values()),
        "context": json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
    }


def _has_insufficient_data_marker(answer: str, *, arabic: bool) -> bool:
    """Matches bounded no-data phrases without treating a bare "no" as enough."""
    if arabic:
        lowered = answer.casefold()
        return any(marker in lowered for marker in _AR_INSUFFICIENT_MARKERS)
    return _EN_INSUFFICIENT_MARKER.search(answer) is not None


def _cases_for_run(dataset: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(dataset, list):
        return dataset
    if not isinstance(dataset.get("cases"), list) or not isinstance(
        dataset.get("snapshots"), dict
    ):
        raise ValueError("Coach roster eval dataset must include cases and snapshots.")
    return [
        {
            **case,
            "_snapshot": dataset["snapshots"][case["snapshot"]],
            "_privacy_seeds": dataset.get("privacy_seeds") or [],
        }
        for case in dataset["cases"]
    ]


def run_suite(
    dataset: dict[str, Any] | list[dict[str, Any]] | None = None,
    *,
    model: Any = None,
) -> list[dict[str, Any]]:
    """Builds production roster prompts and evaluates scripted or live replies."""
    if dataset is None:
        dataset = load_dataset()
    cases = _cases_for_run(dataset)
    if model is None:
        from utils.model_downloader import get_coach_llm

        model = get_coach_llm()
    results = []
    for case in cases:
        snapshot = case["_snapshot"]
        messages = roster_ai.build_messages(
            snapshot,
            str(case["question"]),
            list(case.get("history") or []),
        )
        answer = extract_answer(model.invoke(messages))
        results.append(
            _evaluate_case(
                case,
                snapshot,
                answer,
                _prompt_text(messages),
                list(case.get("_privacy_seeds") or []),
            )
        )
    return results


def _report(
    results: list[dict[str, Any]],
    dataset_path: Path,
    *,
    mode: str,
    privacy_pass: bool,
) -> dict[str, Any]:
    """Builds a roster report through the shared runner workflow."""
    return evaluation_runner.build_report(
        results,
        mode=mode,
        privacy_pass=privacy_pass,
        dataset_path=dataset_path,
        config=RUNNER_CONFIG,
    )


def run_privacy_suite(base_dir: Path = BASE_DIR) -> bool:
    """Runs the roster privacy suite through the shared runner."""
    return evaluation_runner.run_privacy_suite(PRIVACY_SUITE, base_dir)


def main(argv: list[str] | None = None) -> int:
    """Runs the shared Evaluation CLI for mock and report generation."""
    def run_cases(
        cases: list[dict[str, Any]], mock: bool, _dataset_path: Path
    ) -> list[dict[str, Any]]:
        model = None
        if mock:
            from tests.fakes.chat_model import ScriptedChatModel

            model = ScriptedChatModel(
                [case["scripted_answer"] for case in cases]
            )
        return run_suite(cases, model=model)

    return evaluation_runner.run_main(
        argv,
        config=RUNNER_CONFIG,
        base_dir=BASE_DIR,
        run_cases=run_cases,
        validator=roster_ai.validate_report,
    )


if __name__ == "__main__":
    raise SystemExit(main())
