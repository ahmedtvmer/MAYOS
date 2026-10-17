import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))
os.environ["TESTING"] = "1"
os.environ["SKIP_LLM_LOAD"] = "true"
os.chdir(BASE_DIR / "agent")

from agent import assistant_graph as graph
from agent import clinical_guard

DATASET_DIR = BASE_DIR / "tests" / "eval" / "datasets"
REPORT_DIR = BASE_DIR / "docs" / "design-review" / "419"
CASE_PATH = DATASET_DIR / "franco_reviewed_cases.json"
NEGATIVE_PATH = DATASET_DIR / "franco_english_negatives.json"


def _observe_franco(text):
    detector_observed = graph.is_franco_arabic(text)
    clinical_check = (
        clinical_guard.is_franco_clinical_franco_message
        if detector_observed else clinical_guard.is_franco_clinical
    )
    return clinical_check(text), detector_observed


def _score_case(case):
    text = case["text"]
    clinical_observed, detector_observed = _observe_franco(text)
    intercepted = graph._clinical_turn_metadata(text) is not None
    return {
        "id": case["id"],
        "clinical_expected": case["clinical_intercept_warranted"],
        "clinical_observed": clinical_observed,
        "detector_observed": detector_observed,
        "launch_block_expected": case["launch_block_expected"],
        "intercepted": intercepted,
        "pass": intercepted is case["launch_block_expected"]
        and clinical_observed is case["clinical_intercept_warranted"],
    }


def _score_split(cases):
    results = [_score_case(case) for case in cases]
    clinical = [case for case in results if case["clinical_expected"]]
    return {
        "case_count": len(results),
        "clinical_case_count": len(clinical),
        "clinical_intercepted_count": sum(case["clinical_observed"] for case in clinical),
        "intercept_misses": [case["id"] for case in clinical if not case["clinical_observed"]],
        "failures": [case["id"] for case in results if not case["pass"]],
        "cases": results,
    }


def _score_english_negatives(cases):
    results = []
    for case in cases:
        intercepted = graph._clinical_turn_metadata(case["text"]) is not None
        results.append({"id": case["id"], "master_intercepted": case["master_intercepted"], "intercepted": intercepted})
    mismatches = [case["id"] for case in results if case["master_intercepted"] is not case["intercepted"]]
    return {
        "case_count": len(results),
        "master_intercepted_count": sum(case["master_intercepted"] for case in results),
        "current_intercepted_count": sum(case["intercepted"] for case in results),
        "matches_master_count": len(results) - len(mismatches),
        "new_interception_count": sum(
            case["intercepted"] and not case["master_intercepted"] for case in results
        ),
        "mismatches": mismatches,
    }


def _reviewed_case_rows(report):
    lines = []
    for split_name in ("tuning", "held_out"):
        for case in report["splits"][split_name]["cases"]:
            clinical = f"{case['clinical_expected']} / {case['clinical_observed']}"
            intercept = f"{case['launch_block_expected']} / {case['intercepted']}"
            lines.append(
                f"| {split_name} | `{case['id']}` | {clinical} | {case['detector_observed']} | {intercept} | {'PASS' if case['pass'] else 'FAIL'} |"
            )
    return lines


def _adversarial_rows(cases):
    return [
        f"| `{case['id']}` | {case['clinical_observed']} | {case['detector_observed']} | UNREVIEWED |"
        for case in cases
    ]


def _reviewed_section(report):
    return [
        "## Reviewed cases", "",
        "Clinical means the Franco clinical guard result; intercept means the launch route refuses the input.", "",
        "| Split | ID | Clinical expected / observed | Detector | Launch intercept expected / observed | Result |",
        "| --- | --- | --- | --- | --- | --- |",
        *_reviewed_case_rows(report),
    ]


def _english_section(english):
    return [
        "## English negative regression set", "",
        f"{english['matches_master_count']}/{english['case_count']} cases match master `"
        f"{english['master_commit']}`; "
        f"{english['new_interception_count']} new interceptions; "
        f"{english['current_intercepted_count']} current interceptions "
        f"({english['master_intercepted_count']} on master).",
    ]


def _adversarial_section(cases):
    return [
        "## Unreviewed adversarial probes", "",
        "These observations are excluded from the pass/fail gate.", "",
        "| ID | Clinical guard | Franco detector | Status |",
        "| --- | --- | --- | --- |",
        *_adversarial_rows(cases),
    ]


def _markdown(report):
    header = [
        "# Franco clinical guard evaluation", "",
        f"- Guard version: `{report['guard_version']}`",
        f"- Guard commit: `{report['guard_commit']}`",
        "- Held-out was scored after tuning: **yes**",
        "- Scoring order: tuning, then held-out",
        "- Franco safety is deterministic; no external model/provider calls were made.",
        "",
    ]
    sections = [
        *_reviewed_section(report), "", *_english_section(report["english_negative_set"]), "",
        *_adversarial_section(report["unreviewed_adversarial_holdout"]), "",
        "## Regenerate", "",
        "Run `python tests/eval/write_franco_guard_report.py` from the repository root.",
    ]
    return "\n".join([*header, *sections]) + "\n"


def _score_unreviewed(case):
    clinical_observed, detector_observed = _observe_franco(case["text"])
    return {
        "id": case["id"],
        "clinical_observed": clinical_observed,
        "detector_observed": detector_observed,
        "status": case["status"],
        "gate": case["gate"],
    }


def _score_reviewed_splits(splits):
    tuning = _score_split(splits["tuning"])
    held_out = _score_split(splits["held_out"])
    return {"tuning": tuning, "held_out": held_out}


def _build_report(dataset, negatives):
    return {
        "report_version": 1,
        "guard_version": clinical_guard.FRANCO_GUARD_VERSION,
        "base_commit": "68b35cc9",
        "guard_commit": "uncommitted correction on base 68b35cc9",
        "held_out_scored_after_tuning": True,
        "scoring_order": ["tuning", "held_out"],
        "splits": _score_reviewed_splits(dataset["splits"]),
        "english_negative_set": {
            **_score_english_negatives(negatives["cases"]),
            "master_commit": negatives["master_commit"],
        },
        "unreviewed_adversarial_holdout": [
            _score_unreviewed(case) for case in dataset["unreviewed_adversarial_holdout"]
        ],
    }


def _write_report_outputs(report):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "franco-guard-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (REPORT_DIR / "franco-guard-report.md").write_text(_markdown(report), encoding="utf-8")
    print(REPORT_DIR / "franco-guard-report.json")
    print(REPORT_DIR / "franco-guard-report.md")


def write_report():
    dataset = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    negatives = json.loads(NEGATIVE_PATH.read_text(encoding="utf-8"))
    _write_report_outputs(_build_report(dataset, negatives))


if __name__ == "__main__":
    write_report()
