"""Model comparison runner over recorded report fixtures; no models, no network."""

import json
from pathlib import Path

from tests.eval import compare_models

ROOT = Path(__file__).resolve().parents[2]
ARABIC_DATASET = json.loads(
    (ROOT / "tests/eval/datasets/arabic_reviewed_cases.json").read_text(encoding="utf-8")
)
JUDGE_METADATA = [
    {"name": "judge_1", "model": "google/gemma-4-31B-it", "family": "gemma"},
    {"name": "judge_2", "model": "zai-org/GLM-5.3", "family": "glm"},
]
JUDGE_IDS = {judge["name"]: judge["model"] for judge in JUDGE_METADATA}
REPLY_TEXT = "تمام، خلّينا نثبت السيتات ونزوّد العدّات بالتدريج."


def _judgment(safety: int = 5, groundedness: int = 5) -> dict:
    return {
        "clinical_safety": {"score": safety, "rationale": "Safe."},
        "groundedness": {"score": groundedness, "rationale": "Grounded."},
        "biomechanical_validity": {"score": 5, "rationale": "Valid."},
        "structural_budget": {"score": 5, "rationale": "Lean."},
        "persona_adherence": {"score": 5, "rationale": "In persona."},
    }


def _gate_case(case_id: str, judge_1: str = "passed", judge_2: str = "passed") -> dict:
    judges = {}
    for name, verdict in (("judge_1", judge_1), ("judge_2", judge_2)):
        if verdict == "unscored":
            judges[name] = {
                "model": JUDGE_IDS[name],
                "unscored": True,
                "judgment": None,
                "attempts": 2,
                "error": "unreadable answer",
            }
        else:
            judges[name] = {
                "model": JUDGE_IDS[name],
                "passed": verdict == "passed",
                "judgment": _judgment(groundedness=5 if verdict == "passed" else 3),
                "attempts": 1,
                "error": None,
            }
    return {"case_id": case_id, "passed": judge_1 == "passed" and judge_2 == "passed", "judges": judges}


def _arabic_reply_record(case_id: str) -> dict:
    case = next(case for case in ARABIC_DATASET["player_messages"] if case["id"] == case_id)
    return {
        "case_id": case_id,
        "query": case["text"],
        "generated_output": REPLY_TEXT,
        "expected_register": "egyptian",
        "mostly_arabic": True,
        "arabic_letter_share": 1.0,
        "arabic_quality": {},
        "generation_error": None,
        "judges": {
            name: {"model": JUDGE_IDS[name], "label": "egyptian", "rationale": "سجّل التدريب.", "attempts": 1, "error": None}
            for name in JUDGE_IDS
        },
    }


def _arabic_row(case_id: str, outcome: str = "passed") -> dict:
    row = {
        "case_id": case_id,
        "case_status": "completed",
        "observed_blocking": False,
        "launch_block_expected": False,
        "observed_response_kind": "normal_assistant",
        "launch_response_kind": "normal_assistant",
        "expected_intent": None,
        "observed_intent": None,
        "action_effect_pass": True,
        "history_scoring": None,
        "arabic_quality": {},
    }
    if outcome == "failed":
        row["observed_blocking"] = True
    elif outcome == "runner_error":
        row["case_status"] = "runner_error"
    return row


def _gate_report(player_model: str, coaching_runs: list[list[dict]], routing_passed: bool | None = None) -> dict:
    return {
        "mode": "live",
        "generated_at": "2026-11-23T00:00:00+00:00",
        "player_model": player_model,
        "judges": [dict(judge) for judge in JUDGE_METADATA],
        "suite_results": {
            "coaching_qa": {
                "score": 1,
                "total": len(coaching_runs[0]),
                "bar": {"kind": "count", "value": 1},
                "passed": True,
                "failure_reasons": [],
                "runs": [
                    {
                        "run": number,
                        "cases": cases,
                        "score": 1,
                        "total": len(cases),
                        "bar": {"kind": "count", "value": 1},
                        "judge_scores": {"judge_1": 1, "judge_2": 1},
                        "clinical_safety_failures": [],
                        "unscored": [],
                        "unreadable_in_failed_cases": [],
                        "passed": True,
                        "failure_reasons": [],
                    }
                    for number, cases in enumerate(coaching_runs, start=1)
                ],
            },
            "routing": {
                "score": 1,
                "total": 1,
                "bar": {"kind": "count", "value": 1},
                "passed": True,
                "failure_reasons": [],
                "cases": [
                    {
                        "case_id": "en-swap-02",
                        "passed": (player_model == "model-a") if routing_passed is None else routing_passed,
                        "intent_match": True,
                    }
                ],
            },
            "arabic_replies": {
                "score": 1,
                "total": 1,
                "bar": {"kind": "percent", "value": 90},
                "passed": True,
                "failure_reasons": [],
                "cases": [_arabic_reply_record("ar-sore-04")],
            },
        },
    }


def _arabic_report(player_model: str, rows: list[dict]) -> dict:
    return {
        "suite": "arabic_reviewed_41",
        "status": "completed",
        "mode": "real_configured_model",
        "real_model_run": True,
        "generated_at": "2026-11-23T00:00:00+00:00",
        "model": {"provider": "openai-compatible", "model": player_model, "revision": None},
        "runs": rows,
    }


def _understanding_row(case_id: str, *, passed: bool = True, counted: bool = True, wrong: tuple = ()) -> dict:
    return {
        "case_id": case_id, "passed": passed, "scored": True, "counted": counted, "wrong_changes": list(wrong),
    }


def _understanding_report(player_model: str, rows: list[dict], *, partial: bool = False) -> dict:
    return {
        "kind": "understanding", "real_model_run": True, "player_model": player_model,
        "partial": partial, "cases": rows,
    }


def _canonical_gate_report(player_model: str, run: int) -> dict:
    model_a = {
        1: {"qa-01": ("passed", "passed"), "qa-02": ("failed", "failed"), "qa-03": ("unscored", "unscored")},
        2: {"qa-01": ("unscored", "unscored"), "qa-02": ("failed", "failed"), "qa-03": ("unscored", "unscored")},
        3: {"qa-01": ("unscored", "unscored"), "qa-02": ("passed", "passed"), "qa-03": ("unscored", "unscored")},
    }
    model_b = {
        1: {"qa-01": ("passed", "passed"), "qa-02": ("passed", "passed"), "qa-03": ("failed", "failed")},
        2: {"qa-01": ("failed", "failed"), "qa-02": ("passed", "passed"), "qa-03": ("failed", "failed")},
        3: {"qa-01": ("failed", "failed"), "qa-02": ("failed", "failed"), "qa-03": ("failed", "failed")},
    }
    specs = (model_a if player_model == "model-a" else model_b)[run]
    cases = [_gate_case(case_id, judge_1=verdicts[0], judge_2=verdicts[1]) for case_id, verdicts in specs.items()]
    return _gate_report(player_model, coaching_runs=[cases, cases])


def _canonical_arabic_report(player_model: str, run: int) -> dict:
    injury = "failed" if player_model == "model-b" or run == 3 else "passed"
    return _arabic_report(player_model, [_arabic_row("ar-sore-04"), _arabic_row("ar-inj-07", outcome=injury)])


def _write_canonical_dir(tmp_path: Path) -> Path:
    for model_id in ("model-a", "model-b"):
        run_dir = tmp_path / compare_models.model_slug(model_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        for run in (1, 2, 3):
            (run_dir / f"gate_{run}.json").write_text(json.dumps(_canonical_gate_report(model_id, run)), encoding="utf-8")
            (run_dir / f"arabic_{run}.json").write_text(json.dumps(_canonical_arabic_report(model_id, run)), encoding="utf-8")
    return tmp_path


class _FakeCompleted:
    def __init__(self, returncode: int):
        self.returncode = returncode


def test_run_pins_player_model_runs_children_sequentially_and_records_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("MAYOS_BASE_COMMIT", "compare-commit-42")
    monkeypatch.setenv("COMPARE_CHILD_MARKER", "inherited")
    canned = {
        ("model-a", "gate", 1): _gate_report("model-a", coaching_runs=[[_gate_case("qa-01")]]),
        ("model-a", "gate", 2): _gate_report("model-a", coaching_runs=[[_gate_case("qa-01")]]),
        ("model-a", "arabic", 1): _arabic_report("model-a", [_arabic_row("ar-sore-04")]),
        ("model-a", "arabic", 2): _arabic_report("model-a", [_arabic_row("ar-sore-04")]),
        ("model-b", "gate", 1): _gate_report("model-b", coaching_runs=[[_gate_case("qa-01")]]),
        # model B's second gate child fails and writes no report.
        ("model-b", "gate", 2): None,
        ("model-b", "arabic", 1): _arabic_report("model-b", [_arabic_row("ar-sore-04")]),
        ("model-b", "arabic", 2): _arabic_report("model-b", [_arabic_row("ar-sore-04")]),
    }
    for model_id in ("model-a", "model-b"):
        for run in (1, 2):
            canned[(model_id, "understanding", run)] = _understanding_report(
                model_id, [_understanding_row("swap-en-01")]
            )
    kinds = {
        "run_evaluation.py": "gate",
        "run_arabic_evaluation.py": "arabic",
        "run_understanding_evaluation.py": "understanding",
    }
    calls = []

    def fake_run(command, env=None, cwd=None):
        kind = kinds[Path(command[1]).name]
        report_path = Path(command[command.index("--report") + 1])
        run_number = int(report_path.stem.split("_")[1])
        calls.append({"model": env["LLM_MODEL"], "kind": kind, "run": run_number, "env": dict(env), "command": list(command), "cwd": cwd})
        body = canned.get((env["LLM_MODEL"], kind, run_number))
        if body is None:
            return _FakeCompleted(1)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(body), encoding="utf-8")
        return _FakeCompleted(0)

    monkeypatch.setattr(compare_models.subprocess, "run", fake_run)

    exit_code = compare_models.main(
        ["run", "--model-a", "model-a", "--model-b", "model-b", "--runs", "2", "--out", str(tmp_path)]
    )

    assert exit_code == 0
    assert [(call["model"], call["kind"], call["run"]) for call in calls] == [
        ("model-a", "gate", 1),
        ("model-a", "arabic", 1),
        ("model-a", "understanding", 1),
        ("model-a", "gate", 2),
        ("model-a", "arabic", 2),
        ("model-a", "understanding", 2),
        ("model-b", "gate", 1),
        ("model-b", "arabic", 1),
        ("model-b", "understanding", 1),
        ("model-b", "gate", 2),
        ("model-b", "arabic", 2),
        ("model-b", "understanding", 2),
    ]
    assert all(call["env"]["LLM_MODEL"] == call["model"] for call in calls)
    assert all(call["env"]["COMPARE_CHILD_MARKER"] == "inherited" for call in calls)
    assert all(call["cwd"] == str(compare_models.BASE_DIR) for call in calls)
    arabic_calls = [call for call in calls if call["kind"] == "arabic"]
    assert all(call["command"][2:4] == ["--mode", "real"] for call in arabic_calls)
    assert json.loads((tmp_path / "models.json").read_text(encoding="utf-8")) == {
        "model_a": "model-a",
        "model_b": "model-b",
        "runs": 2,
        "evals": ["gate", "arabic", "understanding"],
    }

    comparison = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))
    qa01 = comparison["cases"]["coaching_qa/qa-01"]
    assert qa01["a"]["passes"] is True
    # The failed model B gate child counts as not passed for run 2.
    assert (qa01["b"]["pass_count"], qa01["b"]["scored_runs"]) == (1, 2)
    assert qa01["b"]["passes"] is False
    assert qa01["b"]["judges"]["judge_1"] == {"1": "passed", "2": "failed"}
    assert comparison["a_not_b"] == ["arabic_replies/ar-sore-04", "coaching_qa/qa-01", "routing/en-swap-02"]
    assert comparison["b_not_a"] == []
    assert comparison["invalid_runs"] == [
        {"model": "model-b", "eval": "gate", "run": 2, "reason": "report file is missing"}
    ]


def test_majority_is_taken_over_scored_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("MAYOS_BASE_COMMIT", "compare-commit-42")
    _write_canonical_dir(tmp_path)

    assert compare_models.main(["report", "--dir", str(tmp_path)]) == 0

    comparison = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))
    qa01 = comparison["cases"]["coaching_qa/qa-01"]["a"]
    # 1 passed run of 2 unscored: majority over the scored runs only.
    assert (qa01["pass_count"], qa01["scored_runs"], qa01["passes"]) == (1, 1, True)
    assert qa01["unscored_runs"] == [2, 3]
    assert qa01["judges"]["judge_1"] == {"1": "passed", "2": "unscored", "3": "unscored"}
    assert qa01["judges"]["judge_2"] == {"1": "passed", "2": "unscored", "3": "unscored"}
    qa02 = comparison["cases"]["coaching_qa/qa-02"]["a"]
    assert (qa02["pass_count"], qa02["scored_runs"], qa02["passes"]) == (1, 3, False)
    qa03 = comparison["cases"]["coaching_qa/qa-03"]["a"]
    assert (qa03["pass_count"], qa03["scored_runs"]) == (0, 0)
    assert qa03["passes"] is None
    assert qa03["unscored_runs"] == [1, 2, 3]
    assert comparison["cases"]["coaching_qa/qa-01"]["b"]["passes"] is False
    assert comparison["cases"]["routing/en-swap-02"]["a"]["passes"] is True
    assert comparison["cases"]["arabic_replies/ar-sore-04"]["a"]["passes"] is True
    assert comparison["cases"]["arabic_reviewed_41/ar-inj-07"]["a"]["passes"] is True


def test_a_not_b_and_b_not_a_lists(tmp_path):
    _write_canonical_dir(tmp_path)

    compare_models.main(["report", "--dir", str(tmp_path)])
    comparison = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))

    assert comparison["a_not_b"] == [
        "arabic_reviewed_41/ar-inj-07",
        "coaching_qa/qa-01",
        "routing/en-swap-02",
    ]
    assert comparison["b_not_a"] == ["coaching_qa/qa-02"]


def test_comparison_header_names_models_judges_and_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("MAYOS_BASE_COMMIT", "compare-commit-42")
    _write_canonical_dir(tmp_path)

    compare_models.main(["report", "--dir", str(tmp_path)])
    comparison = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))

    assert comparison["models"] == {"a": "model-a", "b": "model-b"}
    assert comparison["runs"] == 3
    assert comparison["judges"] == JUDGE_IDS
    assert comparison["commit"] == "compare-commit-42"
    markdown = (tmp_path / "comparison.md").read_text(encoding="utf-8")
    assert "- Model A: model-a" in markdown
    assert "- Model B: model-b" in markdown
    assert "judge_1=google/gemma-4-31B-it" in markdown
    assert "judge_2=zai-org/GLM-5.3" in markdown


def test_save_baseline_writes_sorted_passing_list_and_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("MAYOS_BASE_COMMIT", "compare-commit-42")
    _write_canonical_dir(tmp_path)
    compare_models.main(["report", "--dir", str(tmp_path)])
    baseline = tmp_path / "baseline.json"

    assert compare_models.main(["save-baseline", "--dir", str(tmp_path), "--model", "model-a", "--baseline", str(baseline)]) == 0

    payload = json.loads(baseline.read_text(encoding="utf-8"))
    assert payload["model"] == "model-a"
    assert payload["runs"] == 3
    assert payload["commit"] == "compare-commit-42"
    assert payload["judges"] == JUDGE_IDS
    assert payload["created_at"]
    assert payload["passing"] == [
        "arabic_replies/ar-sore-04",
        "arabic_reviewed_41/ar-inj-07",
        "arabic_reviewed_41/ar-sore-04",
        "coaching_qa/qa-01",
        "routing/en-swap-02",
    ]

    overwrite = compare_models.main(
        ["save-baseline", "--dir", str(tmp_path), "--model", "model-a", "--baseline", str(baseline)]
    )
    assert overwrite == 2
    assert json.loads(baseline.read_text(encoding="utf-8")) == payload
    forced = compare_models.main(
        ["save-baseline", "--dir", str(tmp_path), "--model", "model-a", "--baseline", str(baseline), "--force"]
    )
    assert forced == 0


def test_compare_passes_when_every_baseline_case_passes(tmp_path):
    _write_canonical_dir(tmp_path)
    compare_models.main(["report", "--dir", str(tmp_path)])
    baseline = tmp_path / "baseline.json"
    compare_models.main(["save-baseline", "--dir", str(tmp_path), "--model", "model-a", "--baseline", str(baseline)])

    exit_code = compare_models.main(["compare", "--dir", str(tmp_path), "--model", "model-a", "--baseline", str(baseline)])

    assert exit_code == 0
    payload = json.loads((tmp_path / "model-a_baseline_comparison.json").read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["baseline_cases_passed"] == [
        "arabic_replies/ar-sore-04",
        "arabic_reviewed_41/ar-inj-07",
        "arabic_reviewed_41/ar-sore-04",
        "coaching_qa/qa-01",
        "routing/en-swap-02",
    ]
    assert payload["baseline_gaps"] == []
    assert payload["baseline_unscored"] == []
    assert payload["baseline_missing"] == []
    assert payload["bonus_cases"] == []
    markdown = (tmp_path / "model-a_baseline_comparison.md").read_text(encoding="utf-8")
    assert "- Result: PASS" in markdown


def test_compare_fails_with_gaps_and_lists_bonus_without_counting_it(tmp_path):
    _write_canonical_dir(tmp_path)
    compare_models.main(["report", "--dir", str(tmp_path)])
    baseline = tmp_path / "baseline.json"
    compare_models.main(["save-baseline", "--dir", str(tmp_path), "--model", "model-a", "--baseline", str(baseline)])

    exit_code = compare_models.main(["compare", "--dir", str(tmp_path), "--model", "model-b", "--baseline", str(baseline)])

    assert exit_code == 1
    payload = json.loads((tmp_path / "model-b_baseline_comparison.json").read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert payload["baseline_cases_passed"] == ["arabic_replies/ar-sore-04", "arabic_reviewed_41/ar-sore-04"]
    assert payload["baseline_gaps"] == ["arabic_reviewed_41/ar-inj-07", "coaching_qa/qa-01", "routing/en-swap-02"]
    assert payload["baseline_unscored"] == []
    assert payload["baseline_missing"] == []
    assert payload["bonus_cases"] == ["coaching_qa/qa-02"]
    markdown = (tmp_path / "model-b_baseline_comparison.md").read_text(encoding="utf-8")
    assert "- Result: FAIL" in markdown
    assert "coaching_qa/qa-01" in markdown


def test_compare_lists_unscored_and_missing_baseline_cases(tmp_path):
    _write_canonical_dir(tmp_path)
    compare_models.main(["report", "--dir", str(tmp_path)])
    baseline = tmp_path / "hand-written-baseline.json"
    baseline.write_text(
        json.dumps({
            "model": "model-a",
            "runs": 3,
            "commit": "older-commit",
            "judges": JUDGE_IDS,
            "created_at": "2026-11-01T00:00:00+00:00",
            "passing": ["coaching_qa/qa-01", "coaching_qa/qa-03", "coaching_qa/qa-99"],
        }),
        encoding="utf-8",
    )

    exit_code = compare_models.main(["compare", "--dir", str(tmp_path), "--model", "model-a", "--baseline", str(baseline)])

    assert exit_code == 1
    payload = json.loads((tmp_path / "model-a_baseline_comparison.json").read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert payload["baseline_cases_passed"] == ["coaching_qa/qa-01"]
    assert payload["baseline_unscored"] == ["coaching_qa/qa-03"]
    assert payload["baseline_missing"] == ["coaching_qa/qa-99"]
    assert "routing/en-swap-02" in payload["bonus_cases"]


def test_invalid_runs_are_listed_and_count_as_not_passed(tmp_path):
    run_dir = tmp_path / compare_models.model_slug("model-a")
    run_dir.mkdir()
    (run_dir / "gate_1.json").write_text(json.dumps(_gate_report("model-a", coaching_runs=[[_gate_case("qa-01")]])), encoding="utf-8")
    hermetic = _gate_report("model-a", coaching_runs=[[_gate_case("qa-01")]])
    hermetic["mode"] = "hermetic"
    (run_dir / "gate_2.json").write_text(json.dumps(hermetic), encoding="utf-8")
    (run_dir / "arabic_1.json").write_text(json.dumps(_arabic_report("model-a", [_arabic_row("ar-sore-04")])), encoding="utf-8")
    # The Arabic runner exits 0 for missing credentials; real_model_run is False.
    missing_credentials = _arabic_report("model-a", [])
    missing_credentials["status"] = "missing_credentials"
    missing_credentials["real_model_run"] = False
    (run_dir / "arabic_2.json").write_text(json.dumps(missing_credentials), encoding="utf-8")

    assert compare_models.main(["report", "--dir", str(tmp_path)]) == 0

    comparison = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))
    assert comparison["invalid_runs"] == [
        {"model": "model-a", "eval": "gate", "run": 2, "reason": "gate report mode is 'hermetic', not live"},
        {"model": "model-a", "eval": "arabic", "run": 2, "reason": "arabic report is not a real configured-model run"},
    ]
    qa01 = comparison["cases"]["coaching_qa/qa-01"]["a"]
    assert (qa01["pass_count"], qa01["scored_runs"], qa01["passes"]) == (1, 2, False)
    assert qa01["judges"]["judge_1"] == {"1": "passed", "2": "failed"}
    sore04 = comparison["cases"]["arabic_reviewed_41/ar-sore-04"]["a"]
    assert (sore04["pass_count"], sore04["passes"]) == (1, False)
    markdown = (tmp_path / "comparison.md").read_text(encoding="utf-8")
    assert "## Invalid runs" in markdown
    assert "model-a gate run 2: gate report mode is 'hermetic', not live" in markdown
    assert "model-a arabic run 2: arabic report is not a real configured-model run" in markdown


def test_report_for_another_player_model_is_invalid(tmp_path):
    run_dir = tmp_path / compare_models.model_slug("model-a")
    run_dir.mkdir()
    (run_dir / "gate_1.json").write_text(json.dumps(_gate_report("model-a", coaching_runs=[[_gate_case("qa-01")]])), encoding="utf-8")
    for_model_z = _gate_report("model-z", coaching_runs=[[_gate_case("qa-01")]])
    (run_dir / "gate_2.json").write_text(json.dumps(for_model_z), encoding="utf-8")
    (run_dir / "arabic_1.json").write_text(json.dumps(_arabic_report("model-a", [_arabic_row("ar-sore-04")])), encoding="utf-8")
    (run_dir / "arabic_2.json").write_text(json.dumps(_arabic_report("model-a", [_arabic_row("ar-sore-04")])), encoding="utf-8")
    (tmp_path / "models.json").write_text(json.dumps({"model_a": "model-a", "model_b": None, "runs": 2}), encoding="utf-8")

    assert compare_models.main(["report", "--dir", str(tmp_path)]) == 0

    comparison = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))
    assert comparison["invalid_runs"] == [{
        "model": "model-a",
        "eval": "gate",
        "run": 2,
        "reason": "report player model is 'model-z', expected 'model-a'",
    }]
    assert comparison["models"] == {"a": "model-a", "b": None}
    # Run 2 was produced for another player model: its cases count as not passed.
    assert comparison["cases"]["coaching_qa/qa-01"]["a"]["passes"] is False
    assert (comparison["cases"]["coaching_qa/qa-01"]["a"]["pass_count"], comparison["cases"]["coaching_qa/qa-01"]["a"]["scored_runs"]) == (1, 2)


def test_report_uses_models_json_slot_order(tmp_path):
    for model_id in ("model-x", "model-a"):
        run_dir = tmp_path / compare_models.model_slug(model_id)
        run_dir.mkdir()
        verdicts = ("passed", "passed") if model_id == "model-x" else ("failed", "failed")
        (run_dir / "gate_1.json").write_text(
            json.dumps(_gate_report(model_id, coaching_runs=[[_gate_case("qa-01", *verdicts)]], routing_passed=True)),
            encoding="utf-8",
        )
    (tmp_path / "models.json").write_text(json.dumps({"model_a": "model-x", "model_b": "model-a", "runs": 1}), encoding="utf-8")

    compare_models.main(["report", "--dir", str(tmp_path)])
    comparison = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))
    assert comparison["models"] == {"a": "model-x", "b": "model-a"}
    assert comparison["a_not_b"] == ["coaching_qa/qa-01"]
    assert comparison["b_not_a"] == []

    compare_models.main(["report", "--dir", str(tmp_path), "--model-a", "model-a", "--model-b", "model-x"])
    comparison = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))
    assert comparison["models"] == {"a": "model-a", "b": "model-x"}
    assert comparison["a_not_b"] == []
    assert comparison["b_not_a"] == ["coaching_qa/qa-01"]


def test_save_baseline_refuses_invalid_runs_until_forced(tmp_path, capsys):
    run_dir = tmp_path / compare_models.model_slug("model-a")
    run_dir.mkdir()
    (run_dir / "gate_1.json").write_text(json.dumps(_gate_report("model-a", coaching_runs=[[_gate_case("qa-01")]])), encoding="utf-8")
    hermetic = _gate_report("model-a", coaching_runs=[[_gate_case("qa-01")]])
    hermetic["mode"] = "hermetic"
    (run_dir / "gate_2.json").write_text(json.dumps(hermetic), encoding="utf-8")
    (run_dir / "arabic_1.json").write_text(json.dumps(_arabic_report("model-a", [_arabic_row("ar-sore-04")])), encoding="utf-8")
    (run_dir / "arabic_2.json").write_text(json.dumps(_arabic_report("model-a", [_arabic_row("ar-sore-04")])), encoding="utf-8")
    baseline = tmp_path / "baseline.json"

    refused = compare_models.main(["save-baseline", "--dir", str(tmp_path), "--model", "model-a", "--baseline", str(baseline)])

    assert refused == 2
    assert not baseline.exists()
    message = capsys.readouterr().err
    assert "invalid runs" in message
    assert "gate run 2" in message

    forced = compare_models.main(
        ["save-baseline", "--dir", str(tmp_path), "--model", "model-a", "--baseline", str(baseline), "--force"]
    )
    assert forced == 0
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    assert payload["model"] == "model-a"
    assert payload["invalid_runs"] == [
        {"model": "model-a", "eval": "gate", "run": 2, "reason": "gate report mode is 'hermetic', not live"}
    ]


def test_compare_fails_when_the_compared_model_has_an_invalid_run(tmp_path):
    run_dir = tmp_path / compare_models.model_slug("model-a")
    run_dir.mkdir()
    (run_dir / "gate_1.json").write_text(json.dumps(_gate_report("model-a", coaching_runs=[[_gate_case("qa-01")]])), encoding="utf-8")
    hermetic = _gate_report("model-a", coaching_runs=[[_gate_case("qa-01")]])
    hermetic["mode"] = "hermetic"
    (run_dir / "gate_2.json").write_text(json.dumps(hermetic), encoding="utf-8")
    (run_dir / "arabic_1.json").write_text(json.dumps(_arabic_report("model-a", [_arabic_row("ar-sore-04")])), encoding="utf-8")
    (run_dir / "arabic_2.json").write_text(json.dumps(_arabic_report("model-a", [_arabic_row("ar-sore-04")])), encoding="utf-8")
    compare_models.main(["report", "--dir", str(tmp_path)])
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({
            "model": "model-a",
            "runs": 2,
            "commit": "c",
            "judges": JUDGE_IDS,
            "created_at": "now",
            "passing": ["coaching_qa/qa-01"],
        }),
        encoding="utf-8",
    )

    exit_code = compare_models.main(["compare", "--dir", str(tmp_path), "--model", "model-a", "--baseline", str(baseline)])

    assert exit_code == 1
    payload = json.loads((tmp_path / "model-a_baseline_comparison.json").read_text(encoding="utf-8"))
    assert payload["invalid_runs"] == [
        {"model": "model-a", "eval": "gate", "run": 2, "reason": "gate report mode is 'hermetic', not live"}
    ]
    assert payload["baseline_gaps"] == ["coaching_qa/qa-01"]
    assert payload["passed"] is False


def _write_understanding_dir(tmp_path: Path, rows: list[dict], *, partial: bool = False) -> Path:
    _write_canonical_dir(tmp_path)
    for model_id in ("model-a", "model-b"):
        for run in (1, 2, 3):
            path = tmp_path / compare_models.model_slug(model_id) / f"understanding_{run}.json"
            path.write_text(json.dumps(_understanding_report(model_id, rows, partial=partial)), encoding="utf-8")
    return tmp_path


def test_understanding_cases_count_only_after_review(tmp_path):
    _write_understanding_dir(
        tmp_path, [_understanding_row("swap-en-01"), _understanding_row("swap-egy-01", counted=False)]
    )

    assert compare_models.main(["report", "--dir", str(tmp_path)]) == 0

    comparison = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))
    assert comparison["cases"]["understanding/swap-en-01"]["a"]["passes"] is True
    assert "understanding/swap-egy-01" not in comparison["cases"]


def test_a_wrong_change_is_listed_and_fails_the_baseline_comparison_even_when_unreviewed(tmp_path):
    rows = [_understanding_row("swap-egy-01", passed=False, counted=False, wrong=("program",))]
    _write_understanding_dir(tmp_path, rows)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"passing": []}), encoding="utf-8")
    assert compare_models.main(["report", "--dir", str(tmp_path)]) == 0

    exit_code = compare_models.main(
        ["compare", "--dir", str(tmp_path), "--model", "model-a", "--baseline", str(baseline)]
    )

    comparison = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))
    assert comparison["wrong_changes_applied"]["model-a"]["1"] == ["swap-egy-01"]
    assert exit_code == 1


def test_a_partial_understanding_run_is_invalid(tmp_path):
    _write_understanding_dir(tmp_path, [_understanding_row("swap-en-01")], partial=True)

    assert compare_models.main(["report", "--dir", str(tmp_path)]) == 0

    comparison = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))
    reasons = {entry["reason"] for entry in comparison["invalid_runs"] if entry["eval"] == "understanding"}
    assert reasons == {"understanding report is a partial run"}
