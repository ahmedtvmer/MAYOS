"""Evaluation CLI gate — process exit codes over produced report fixtures.

These run the real command as a subprocess. ``--check-report`` short-circuits
before the model-heavy imports, so no LLM/embedding model is loaded.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
EVAL_PATH = BASE_DIR / "tests" / "eval" / "run_evaluation.py"

STANDARD = {"coaching_qa": 25, "debrief": 25, "onboarding": 15}
GENERALIZATION = {"coaching_qa": 5, "debrief": 5, "onboarding": 5}


def _result(index: int, passed: bool, safety: int = 5, judgment: Any = "auto") -> dict:
    if judgment == "auto":
        judgment = {"clinical_safety": {"score": safety}}
    return {"case_id": f"case-{index}", "passed": passed, "judgment": judgment}


def _runs(counts: dict[str, int], passed_total: int, *, safety: int = 5, qa_judgment: Any = "auto") -> dict:
    runs: dict[str, list] = {}
    remaining = passed_total
    index = 0
    for module, count in counts.items():
        results = []
        for _ in range(count):
            passed = remaining > 0
            remaining -= 1
            if module == "coaching_qa":
                results.append(_result(index, passed, safety=safety, judgment=qa_judgment))
            else:
                results.append(_result(index, passed))
            index += 1
        runs[module] = results
    return runs


def _write_report(tmp_path: Path, runs: dict) -> Path:
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"timestamp": "fixture", "runs": runs}), encoding="utf-8")
    return path


def _check(report_path: Path, suite: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "TESTING": "1", "SKIP_LLM_LOAD": "true", **(extra_env or {})}
    return subprocess.run(
        [sys.executable, str(EVAL_PATH), "--check-report", str(report_path), "--suite", suite],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BASE_DIR),
        timeout=60,
    )


def test_standard_report_at_threshold_exits_zero(tmp_path):
    result = _check(_write_report(tmp_path, _runs(STANDARD, 62)), "standard")
    assert result.returncode == 0, result.stderr
    assert "PASSED" in result.stdout


def test_standard_report_below_threshold_exits_nonzero(tmp_path):
    result = _check(_write_report(tmp_path, _runs(STANDARD, 61)), "standard")
    assert result.returncode != 0
    assert "below required" in result.stderr


def test_standard_report_clinical_safety_below_five_exits_nonzero(tmp_path):
    result = _check(_write_report(tmp_path, _runs(STANDARD, 65, safety=4)), "standard")
    assert result.returncode != 0
    assert "clinical_safety=4" in result.stderr


def test_standard_report_unparseable_judgment_exits_nonzero(tmp_path):
    result = _check(_write_report(tmp_path, _runs(STANDARD, 65, qa_judgment=None)), "standard")
    assert result.returncode != 0
    assert "no parseable judgment" in result.stderr


def test_standard_report_missing_module_exits_nonzero(tmp_path):
    runs = _runs(STANDARD, 65)
    del runs["debrief"]
    result = _check(_write_report(tmp_path, runs), "standard")
    assert result.returncode != 0
    assert "missing results" in result.stderr


def test_generalization_report_perfect_exits_zero(tmp_path):
    result = _check(_write_report(tmp_path, _runs(GENERALIZATION, 15)), "generalization")
    assert result.returncode == 0, result.stderr
    assert "PASSED" in result.stdout


def test_generalization_report_below_perfect_exits_nonzero(tmp_path):
    result = _check(_write_report(tmp_path, _runs(GENERALIZATION, 14)), "generalization")
    assert result.returncode != 0


def test_missing_report_file_exits_nonzero(tmp_path):
    result = _check(tmp_path / "nope.json", "standard")
    assert result.returncode != 0
    assert "report not found" in result.stderr


def test_invalid_report_json_exits_nonzero(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not-json", encoding="utf-8")
    result = _check(path, "standard")
    assert result.returncode != 0
    assert "not valid JSON" in result.stderr


def test_missing_generalization_dataset_exits_nonzero(tmp_path):
    missing_dir = tmp_path / "empty-datasets"
    missing_dir.mkdir()
    env = {**os.environ, "EVAL_DATASETS_DIR": str(missing_dir), "TESTING": "1", "SKIP_LLM_LOAD": "true"}
    result = subprocess.run(
        [sys.executable, str(EVAL_PATH), "--generalize"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BASE_DIR),
        timeout=60,
    )
    assert result.returncode != 0
    assert "Generalization dataset not found" in result.stderr
