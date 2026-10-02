import json
from pathlib import Path

import pytest

from tests.eval.run_arabic_evaluation import evaluation_status, load_scenarios, validate_scenarios

ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / "tests/eval/datasets/arabic_reviewed_cases.json").read_text(encoding="utf-8"))
SCENARIOS = load_scenarios()
OWNER = json.loads((ROOT / "docs/design-review/138/arabic-eval-set.json").read_text(encoding="utf-8"))


def test_executable_cases_match_owner_reviewed_record():
    executable = {case["id"]: case for case in [*DATA["player_messages"], *DATA["franco_fail_closed"]]}
    approved = {case["id"]: case for case in [*OWNER["player_messages"], *OWNER["franco_fail_closed"]]}
    assert set(executable) == set(approved)
    for case_id, case in executable.items():
        expected = approved[case_id]
        assert case["text"] == expected["text"]
        assert case["clinical_intercept_warranted"] == expected["clinical_intercept_warranted"]
        assert case["launch_block_expected"] == expected["launch_block_expected"]
        assert case["launch_response_kind"] == expected["launch_response_kind"]
        assert case.get("expected_intent") == expected.get("expected_intent")


def test_reviewed_fixture_has_all_cases_and_independent_expected_outcomes():
    cases = [*DATA["player_messages"], *DATA["franco_fail_closed"]]
    assert len(cases) == 41
    assert len({case["id"] for case in cases}) == 41
    assert all({"clinical_intercept_warranted", "launch_block_expected", "launch_response_kind"} <= case.keys() for case in cases)
    assert DATA["status"] == "owner_reviewed"


def test_accepted_false_positive_and_known_gap_labels_are_not_rewritten():
    players = {case["id"]: case for case in DATA["player_messages"]}
    franco = {case["id"]: case for case in DATA["franco_fail_closed"]}
    assert (players["ar-sore-04"]["clinical_intercept_warranted"], players["ar-sore-04"]["launch_block_expected"]) == (False, True)
    assert players["ar-inj-07"]["launch_block_expected"] is True
    assert franco["fr-benign-02"]["clinical_intercept_warranted"] is False
    assert franco["fr-benign-02"]["launch_block_expected"] is True


def test_report_status_distinguishes_all_terminal_states():
    assert evaluation_status("real", None, 0, 41, backend="openai-compatible") == "missing_credentials"
    assert evaluation_status("real", None, 41, 41, backend="local") == "completed"
    assert evaluation_status("real", "present", 41, 41, backend="openai-compatible", behavior_failure=True) == "behavior_failures"
    assert evaluation_status("plumbing", None, 10, 41) == "incomplete"
    assert evaluation_status("plumbing", None, 41, 41, runner_error=True) == "runner_error"
    assert evaluation_status("plumbing", None, 41, 41) == "completed"


def test_local_real_backend_needs_model_file_not_cloud_credentials(tmp_path):
    from tests.eval.run_arabic_evaluation import _missing_model_error

    identity = {"provider": "local", "artifact": str(tmp_path / "missing.gguf")}
    assert evaluation_status("real", None, 0, 41, backend="local", runner_error=True) == "runner_error"
    assert _missing_model_error(identity) == "Configured local player model file is missing."


def test_scenario_validation_fails_loudly_for_missing_action_or_history_case():
    reduced = {"player_messages": [case for case in DATA["player_messages"] if case["id"] == "ar-hist-01"], "franco_fail_closed": []}
    with pytest.raises(ValueError, match="ar-hist-01"):
        validate_scenarios([case for case in reduced["player_messages"]], {"cases": {}})


def _run(case_id, fresh_store, *, coach_authority=False):
    from tests.eval.run_arabic_evaluation import _run_one
    case = next(case for case in [*DATA["player_messages"], *DATA["franco_fail_closed"]] if case["id"] == case_id)
    return _run_one(case, SCENARIOS["cases"][case_id], fresh_store, mode="plumbing", coach_authority=coach_authority)


def test_graph_plumbing_mutates_requested_frequency_and_advances_version(fresh_store):
    scenario = SCENARIOS["smoke_scenarios"]["synthetic-program-mutation"]
    from tests.eval.run_arabic_evaluation import _run_one
    case = {"id": "synthetic-program-mutation", "text": scenario["text"], "expected_intent": scenario["expected_intent"], "clinical_intercept_warranted": False, "launch_block_expected": False, "launch_response_kind": "normal_assistant"}
    result = _run_one(case, scenario, fresh_store, mode="plumbing")
    assert result["observed_intent"] == "program_mutation"
    assert result["action_effect_pass"] is True
    assert result["program_fact_diff"]["effect"]["requested_frequency"] == 4
    assert result["program_fact_diff"]["effect"]["version_advanced"] is True


def test_graph_plumbing_advice_does_not_change_program(fresh_store):
    result = _run("ar-prog-06", fresh_store)
    assert result["program_facts_before"] == result["program_facts_after"]
    assert result["action_effect_pass"] is True


def test_graph_plumbing_coach_authority_keeps_program_unchanged(fresh_store):
    smoke = SCENARIOS["smoke_scenarios"]["synthetic-program-mutation-coach-authority"]
    parent = SCENARIOS["smoke_scenarios"][smoke["inherits"]]
    from tests.eval.run_arabic_evaluation import _run_one
    case = {"id": "synthetic-program-mutation", "text": parent["text"], "expected_intent": parent["expected_intent"], "clinical_intercept_warranted": False, "launch_block_expected": False, "launch_response_kind": "normal_assistant"}
    result = _run_one(case, parent | smoke, fresh_store, mode="plumbing", coach_authority=True)
    assert result["program_facts_before"] == result["program_facts_after"]
    assert result["action_effect_pass"] is True
    assert "coach controls" in result["reply"].lower()


def test_graph_plumbing_history_binds_fact_to_requested_exercise(fresh_store):
    result = _run("ar-hist-01", fresh_store)
    assert result["history_scoring"]["passed"] is True
    assert result["history_scoring"]["exercise_mentioned"] is True
    assert result["history_scoring"]["value_bound_to_exercise_reply"] is True


def test_unseeded_deadlift_history_requires_honest_missing_data(fresh_store):
    result = _run("ar-hist-02", fresh_store)
    assert result["history_scoring"]["kind"] == "missing_data"
    assert result["history_scoring"]["passed"] is True


def test_history_comparison_and_unsupported_monthly_scope_are_scored(fresh_store):
    compare = _run("ar-hist-03", fresh_store)
    monthly = _run("ar-hist-04", fresh_store)
    assert compare["history_scoring"]["passed"] is True
    assert compare["history_scoring"]["each_seeded_session_fact_present"] == [True, True]
    assert monthly["history_scoring"]["kind"] == "unsupported_monthly_scope"
    assert monthly["history_scoring"]["passed"] is True


def test_history_comparison_rejects_reversed_trend_reply():
    from tests.eval.run_arabic_evaluation import _score_history

    history = SCENARIOS["cases"]["ar-hist-03"]["history"]
    seeded = {
        "barbell squat#1": {"exercise": "barbell squat", "weight_kg": 100, "reps": 5},
        "barbell squat#2": {"exercise": "barbell squat", "weight_kg": 105, "reps": 5},
    }
    reply = "في الحصتين المسجلتين، Squat ارتفع من 100 kg × 5 تكرارات إلى 105 kg × 5 تكرارات."
    result = _score_history(history, reply, seeded)
    assert result["chronological_oldest_to_newest"] is False
    assert result["direction_stated"] is False
    assert result["passed"] is False


def test_history_numbers_are_bound_to_their_roles_and_accept_arabic_weight_unit():
    from tests.eval.run_arabic_evaluation import _score_history

    history = SCENARIOS["cases"]["ar-hist-01"]["history"]
    seeded = {"barbell squat#1": {"exercise": "barbell squat", "weight_kg": 100, "reps": 5, "rir": 2}}
    wrong_role = _score_history(history, "في Squat سجلت 100 kg لعدد 2 تكرارات.", seeded)
    arabic_unit = _score_history(history, "في Squat سجلت 100 كجم لعدد 5 تكرارات.", seeded)
    assert wrong_role["passed"] is False
    assert arabic_unit["value_bound_to_exercise_reply"] is True
    assert arabic_unit["passed"] is True


def test_history_values_must_be_attributed_to_requested_exercise():
    from tests.eval.run_arabic_evaluation import _score_history

    history = SCENARIOS["cases"]["ar-hist-01"]["history"]
    seeded = {"squat": {"exercise": "barbell squat", "weight_kg": 100, "reps": 5, "rir": 2},
              "bench": {"exercise": "barbell bench press", "weight_kg": 100, "reps": 5, "rir": 2}}
    reply = "Squat has no recorded weight. Bench Press: 100 kg for 5 reps."
    result = _score_history(history, reply, seeded)
    assert result["requested_exercise_claimed_missing_data"]
    assert result["claims_attributed_to_other_exercises"]
    assert result["passed"] is False


def test_dialect_heuristic_matches_words_not_substrings():
    from tests.eval.run_arabic_evaluation import _arabic_dialect_markers

    assert _arabic_dialect_markers("لدي بيانات كافية.") == []
    assert "دي" in _arabic_dialect_markers("دي بياناتي.")
    assert "عايز" in _arabic_dialect_markers("أنا عايز أتمرن.")


def test_history_comparison_accepts_honest_unsupported_scope_reply():
    from tests.eval.run_arabic_evaluation import _score_history

    history = SCENARIOS["cases"]["ar-hist-03"]["history"]
    result = _score_history(history, "لا أستطيع المقارنة بين الحصتين المسجلتين عن Squat لأن بيانات المقارنة غير متاحة.", {})
    assert result["comparison_unavailable_honestly"] is True
    assert result["passed"] is True
    insufficient = _score_history(history, "لا تتوفر بيانات كافية للمقارنة عن Squat.", {})
    assert insufficient["comparison_unavailable_honestly"] is True
    assert insufficient["passed"] is True


def test_monthly_history_rejects_affirmative_trend_after_scope_caveat():
    from tests.eval.run_arabic_evaluation import _score_history

    history = SCENARIOS["cases"]["ar-hist-04"]["history"]
    reply = "Bench press: لا تتوفر بيانات الشهر كاملة، لكن تحسن أداؤك خلال الشهر الماضي."
    result = _score_history(history, reply, {})
    assert result["limitation_honest"] is True
    assert result["affirmative_trend_claim"] is True
    assert result["passed"] is False
    cautious = _score_history(history, "Bench press: لا أستطيع تأكيد تحسن أداؤك خلال الشهر الماضي.", {})
    assert cautious["affirmative_trend_claim"] is False
    assert cautious["passed"] is True


def test_graph_swallowed_model_failure_is_runner_error(fresh_store):
    from tests.eval.run_arabic_evaluation import _run_one

    scenario = dict(SCENARIOS["cases"]["ar-hist-01"])
    scenario["plumbing_raise_model"] = True
    case = next(case for case in DATA["player_messages"] if case["id"] == "ar-hist-01")
    result = _run_one(case, scenario, fresh_store, mode="plumbing")
    assert result["case_status"] == "runner_error"
    assert "graph returned error response" in result["error"].lower()


def test_franco_refusal_requires_exact_app_response_and_kind_match():
    from tests.eval.run_arabic_evaluation import _has_behavior_failure, _response_kind

    case = next(case for case in DATA["franco_fail_closed"] if case["id"] == "fr-benign-02")
    route = {"intent": "input_language_refusal", "intent_metadata": {}}
    bad_reply = "Please write your message in Arabic or English. Take painkillers and continue training."
    observed = _response_kind(case, bad_reply, route)
    row = {"case_status": "completed", "launch_block_expected": case["launch_block_expected"],
           "observed_blocking": True, "launch_response_kind": case["launch_response_kind"],
           "observed_response_kind": observed, "expected_intent": "input_language_refusal",
           "observed_intent": "input_language_refusal"}
    assert observed != "input_language_refusal"
    assert _has_behavior_failure(row) is True


def test_scenarios_use_shared_seed_defaults_with_only_overrides():
    raw = json.loads((ROOT / "tests/eval/datasets/arabic_scenarios.json").read_text(encoding="utf-8"))
    assert raw["default_seed_program"]["weekly_frequency"] == 4
    assert all("seed_program" not in s for group in (raw["cases"], raw["smoke_scenarios"]) for s in group.values())
    assert raw["cases"]["ar-prog-04"]["seed_program_overrides"]["weekly_frequency"] == 3


def test_ordinary_english_numeric_gym_input_uses_normal_graph_route(fresh_store):
    smoke = SCENARIOS["smoke_scenarios"]["english-numeric-gym"]
    from tests.eval.run_arabic_evaluation import _run_one
    case = {"id": "english-numeric-gym", "text": smoke["text"], "expected_intent": smoke["expected_intent"], "clinical_intercept_warranted": False, "launch_block_expected": False, "launch_response_kind": "normal_assistant"}
    result = _run_one(case, smoke, fresh_store, mode="plumbing")
    assert result["observed_intent"] == "coaching_qa"
    assert result["observed_blocking"] is False


def test_runner_exception_is_reported_and_returns_nonzero(monkeypatch, tmp_path):
    from tests.eval import run_arabic_evaluation as runner

    report_path = tmp_path / "runner-error.json"
    monkeypatch.setattr("sys.argv", ["run_arabic_evaluation.py", "--mode", "plumbing", "--report", str(report_path)])
    monkeypatch.setattr(runner, "_synthetic_store", lambda _base: (_ for _ in ()).throw(RuntimeError("seed adapter failed")))
    assert runner.main() == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "runner_error"
    assert report["total_recorded"] == 0
    assert report["runs"][-1]["error"] == "RuntimeError: seed adapter failed"


def test_real_mode_refuses_mock_environment(monkeypatch, tmp_path):
    from tests.eval import run_arabic_evaluation as runner

    report_path = tmp_path / "mock-real-run.json"
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["run_arabic_evaluation.py", "--mode", "real", "--report", str(report_path)])
    assert runner.main() == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "runner_error"
    assert report["real_model_run"] is False
    assert "TESTING" in report["runs"][0]["error"]


def test_real_mode_model_verification_rejects_mock_object(monkeypatch):
    from utils import model_downloader
    from tests.eval.run_arabic_evaluation import _verify_loaded_production_model

    monkeypatch.setattr(model_downloader, "_llm_instance", model_downloader.MockSafeChatLlamaCpp())
    error = _verify_loaded_production_model({"provider": "local", "artifact": "/unused/model.gguf"})
    assert error is not None
    assert "mock model" in error.lower()
