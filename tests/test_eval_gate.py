"""Suite-owned report validation and CLI behavior without model calls."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
EVAL_PATH = BASE_DIR / "tests" / "eval" / "run_evaluation.py"
JUDGE_NAMES = ("judge_1", "judge_2")
JUDGES = [
    {"name": "judge_1", "model": "Qwen/Qwen3.5-27B", "family": "qwen"},
    {"name": "judge_2", "model": "zai-org/GLM-5.3", "family": "glm"},
]
COACHING_BAR = {"kind": "count", "value": 24}
GENERALIZATION_BAR = {"kind": "count", "value": 5}


def _judgment(safety: int = 5, groundedness: int = 5) -> dict:
    return {
        "clinical_safety": {"score": safety, "rationale": "Safe response."},
        "groundedness": {"score": groundedness, "rationale": "Grounded response."},
        "biomechanical_validity": {"score": 5, "rationale": "Valid mechanics."},
        "structural_budget": {"score": 5, "rationale": "Within response budget."},
        "persona_adherence": {"score": 5, "rationale": "Matches coach persona."},
    }


def _case(index: int, judge_passes: tuple[bool, bool] = (True, True), safety: int = 5) -> dict:
    judges = {
        name: {
            "model": JUDGES[offset]["model"],
            "passed": passed,
            "judgment": _judgment(safety, 5 if passed else 3),
            "attempts": 1,
            "error": None,
        }
        for offset, (name, passed) in enumerate(zip(JUDGE_NAMES, judge_passes, strict=True))
    }
    return {"case_id": f"case-{index}", "passed": all(judge_passes), "judges": judges}


def _run(run_number: int, count: int, score: int, bar: dict) -> dict:
    cases = [_case(index, (index < score, index < score)) for index in range(count)]
    judge_scores = {name: score for name in JUDGE_NAMES}
    reasons = [] if bar["value"] <= score else [
        f"score {score}/{count} below required bar {bar['value']}/{count}"
    ]
    return {
        "run": run_number,
        "cases": cases,
        "score": score,
        "total": count,
        "bar": bar,
        "judge_scores": judge_scores,
        "clinical_safety_failures": [],
        "passed": not reasons,
        "failure_reasons": reasons,
    }


def _suite_entry(count: int, bar: dict, scores: tuple[int, ...]) -> dict:
    runs = [_run(index, count, score, bar) for index, score in enumerate(scores, start=1)]
    reasons = [reason for run in runs for reason in run["failure_reasons"]]
    return {
        "score": min((run["score"] for run in runs), default=0),
        "total": count,
        "bar": bar,
        "passed": bool(runs) and all(run["passed"] for run in runs),
        "failure_reasons": reasons,
        "runs": runs,
    }


def _report(*, coaching_scores: tuple[int, ...] = (24, 24), generalization_score: int = 5) -> dict:
    return {
        "mode": "live",
        "player_model": "deepseek-ai/DeepSeek-V4-Flash",
        "judges": [judge.copy() for judge in JUDGES],
        "suite_results": {
            "coaching_qa": _suite_entry(25, COACHING_BAR, coaching_scores),
            "generalization": _suite_entry(5, GENERALIZATION_BAR, (generalization_score,)),
        },
    }


def _write_report(tmp_path: Path, report: dict) -> Path:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _check(report_path: Path) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "TESTING": "1",
        "SKIP_LLM_LOAD": "true",
        "JUDGE_MODEL": JUDGES[0]["model"],
        "JUDGE_SECONDARY_MODEL": JUDGES[1]["model"],
    }
    return subprocess.run(
        [sys.executable, str(EVAL_PATH), "--check-report", str(report_path)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BASE_DIR),
        timeout=60,
    )


def test_full_report_validates_each_suite_and_both_judges(tmp_path):
    result = _check(_write_report(tmp_path, _report(coaching_scores=(24, 25))))

    assert result.returncode == 0, result.stderr
    assert "coaching_qa run 1: 24/25 (bar ≥24/25)" in result.stdout
    assert "judge_1=24/25" in result.stdout
    assert "judge_2=24/25" in result.stdout
    assert "generalization run 1: 5/5 (bar ≥5/5)" in result.stdout
    assert "PLAYER MODEL GATE: PASSED" in result.stdout


def test_coaching_run_below_bar_fails_even_when_the_other_run_passes(tmp_path):
    result = _check(_write_report(tmp_path, _report(coaching_scores=(23, 25))))

    assert result.returncode != 0
    assert "coaching_qa run 1: 23/25" in result.stdout
    assert "below required bar" in result.stderr


def test_coaching_gate_requires_two_consecutive_runs(tmp_path):
    result = _check(_write_report(tmp_path, _report(coaching_scores=(24,))))

    assert result.returncode != 0
    assert "expected 2 run(s), got 1" in result.stderr


def test_generalization_requires_all_five_cases_from_both_judges(tmp_path):
    result = _check(_write_report(tmp_path, _report(generalization_score=4)))

    assert result.returncode != 0
    assert "generalization run 1: 4/5 (bar ≥5/5)" in result.stdout
    assert "PLAYER MODEL GATE: FAILED" in result.stdout


def test_coaching_gate_rejects_any_nonperfect_clinical_safety_score(tmp_path):
    report = _report()
    case = report["suite_results"]["coaching_qa"]["runs"][0]["cases"][0]
    case["judges"]["judge_2"]["judgment"] = _judgment(4)

    result = _check(_write_report(tmp_path, report))

    assert result.returncode != 0
    assert "clinical_safety=4" in result.stderr


def test_report_rederives_judge_verdict_from_dimension_names(tmp_path):
    report = _report()
    case = report["suite_results"]["coaching_qa"]["runs"][0]["cases"][0]
    case["judges"]["judge_1"]["judgment"]["groundedness"]["score"] = 3

    result = _check(_write_report(tmp_path, report))

    assert result.returncode != 0
    assert "verdict does not match dimension scores" in result.stderr


def test_clinical_safety_is_checked_by_dimension_name_not_position(tmp_path):
    report = _report()
    case = report["suite_results"]["coaching_qa"]["runs"][0]["cases"][0]
    judgment = _judgment(safety=4)
    case["judges"]["judge_1"]["judgment"] = {
        **{name: value for name, value in judgment.items() if name != "clinical_safety"},
        "clinical_safety": judgment["clinical_safety"],
    }

    result = _check(_write_report(tmp_path, report))

    assert result.returncode != 0
    assert "clinical_safety=4" in result.stderr


def test_each_case_must_pass_both_judges(tmp_path):
    report = _report()
    entry = report["suite_results"]["generalization"]
    entry["runs"][0]["cases"][0] = _case(0, (True, False))

    result = _check(_write_report(tmp_path, report))

    assert result.returncode != 0
    assert "generalization run 1: 4/5" in result.stdout


def test_suite_revalidates_run_and_suite_summaries(tmp_path):
    report = _report()
    report["suite_results"]["coaching_qa"]["runs"][0]["score"] = 25

    result = _check(_write_report(tmp_path, report))

    assert result.returncode != 0
    assert "recorded score does not match recomputed result" in result.stderr


@pytest.mark.parametrize("malformation", ["missing", "name", "model", "family"])
def test_malformed_judge_metadata_fails_without_crashing(tmp_path, malformation):
    report = _report()
    if malformation == "missing":
        report.pop("judges")
    elif malformation == "name":
        report["judges"][0].pop("name")
    else:
        report["judges"][0].pop(malformation)

    result = _check(_write_report(tmp_path, report))

    assert result.returncode != 0
    assert "PLAYER MODEL GATE: FAILED" in result.stdout
    assert "Traceback" not in result.stderr


def test_report_rejects_judges_from_the_same_model_family(tmp_path):
    report = _report()
    report["judges"][1] = {"name": "judge_2", "model": "Qwen/Qwen3.5-9B", "family": "qwen"}

    result = _check(_write_report(tmp_path, report))

    assert result.returncode != 0
    assert "different model families" in result.stderr


def test_hermetic_gate_reports_every_suite_and_can_revalidate_its_report(tmp_path):
    report_path = tmp_path / "hermetic.json"
    result = subprocess.run(
        [sys.executable, str(EVAL_PATH), "--hermetic", "--report", str(report_path)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "TESTING": "1",
            "SKIP_LLM_LOAD": "true",
            "JUDGE_MODEL": JUDGES[0]["model"],
            "JUDGE_SECONDARY_MODEL": JUDGES[1]["model"],
            "EVAL_DATASETS_DIR": str(BASE_DIR / "tests" / "eval" / "datasets"),
        },
        cwd=str(BASE_DIR),
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "coaching_qa run 1: 25/25 (bar ≥24/25)" in result.stdout
    assert "generalization run 1: 5/5 (bar ≥5/5)" in result.stdout
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["gate"]["passed"] is False
    assert report["gate"]["status"] == "hermetic_check_only"
    assert "PLAYER MODEL GATE: NOT RUN" in result.stdout

    checked = _check(report_path)
    assert checked.returncode == 0, checked.stderr
    assert "PLAYER MODEL GATE: NOT RUN" in checked.stdout


def test_hermetic_gate_fails_when_required_dataset_is_missing(tmp_path):
    result = subprocess.run(
        [sys.executable, str(EVAL_PATH), "--hermetic", "--report", str(tmp_path / "report.json")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "TESTING": "1",
            "JUDGE_MODEL": JUDGES[0]["model"],
            "JUDGE_SECONDARY_MODEL": JUDGES[1]["model"],
            "EVAL_DATASETS_DIR": str(tmp_path),
        },
        cwd=str(BASE_DIR),
        timeout=60,
    )

    assert result.returncode != 0
    assert "Evaluation dataset not found" in result.stderr


def test_missing_or_invalid_report_exits_nonzero(tmp_path):
    missing = _check(tmp_path / "missing.json")
    assert missing.returncode != 0
    assert "report not found" in missing.stderr

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("not-json", encoding="utf-8")
    invalid = _check(invalid_path)
    assert invalid.returncode != 0
    assert "not valid JSON" in invalid.stderr
