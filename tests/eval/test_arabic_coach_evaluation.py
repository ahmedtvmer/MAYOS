import json
from pathlib import Path

from tests.eval import arabic_coach_evaluation as evaluation

BASE_DIR = Path(__file__).resolve().parents[2]
RETAINED_SOURCE = BASE_DIR / "tests/eval/datasets/arabic_reviewed_cases.json"


def _case(cases, template_id, variant="base"):
    return next(
        case
        for case in cases
        if case["base_template_id"] == template_id and case["variant_identity"] == variant
    )


def test_templates_preserve_reviewed_wording_status_and_stable_ids():
    fixture = evaluation.load_templates()
    source = json.loads(RETAINED_SOURCE.read_text(encoding="utf-8"))
    source_templates = source["coach_questions"]["single_player"] + source["coach_questions"]["roster"]
    templates = fixture["templates"]

    assert fixture["base_template_count"] == len(source_templates)
    assert fixture["source_review_status"]["dataset_status"] == source["status"]
    assert (
        fixture["source_review_status"]["coach_question_translations_status"]
        == source["coach_question_translations_status"]
    )
    assert [template["id"] for template in templates] == [template["id"] for template in source_templates]
    for template, source_template in zip(templates, source_templates):
        assert template["question_ar"] == source_template["question_ar"]
        assert template.get("question_egyptian") == source_template.get("question_eg")
        assert template["answer_type"] == source_template["answer_type"]
        assert template.get("truth_key") == source_template.get("truth_key")
        english = (
            source_template.get("english")
            or source_template.get("question_en")
            or source_template["question"]
        )
        assert template["question_en"] == english


def test_synthetic_truth_is_computed_and_variants_remain_separate():
    facts = evaluation.load_facts()
    templates_fixture = evaluation.load_templates()
    cases = evaluation.expand_cases(facts_fixture=facts)
    truths = {case["run_id"]: case["expected_truth"] for case in cases}
    expected_variant_count = sum(
        bool(template.get("question_egyptian"))
        for template in templates_fixture["templates"]
    )
    base_cases = [case for case in cases if case["variant_identity"] == "base"]
    egyptian_cases = [case for case in cases if case["variant_identity"] == "egyptian"]

    assert len(base_cases) == templates_fixture["base_template_count"]
    assert len(egyptian_cases) == expected_variant_count
    assert truths["cq-s-01"] == facts["single_player"]["attendance"]["adherence_pct"]
    assert truths["cq-s-02"] == sum(
        session["sets_count"] for session in facts["single_player"]["recent_sessions"]
    )
    assert truths["cq-s-03"] == [142.5, 138.0]
    assert truths["cq-s-04"] == facts["single_player"]["volume"]["last_7_days_kg"]
    assert truths["cq-s-05"] != facts["single_player"]["attendance"]["missed_days"]
    assert truths["cq-r-01"] == ["PLR-002", "PLR-003"]
    assert truths["cq-r-02"] == 3
    assert truths["cq-r-03"] == ["PLR-002", "PLR-004"]
    assert truths["cq-r-04"] == ["PLR-005"]
    assert truths["cq-r-05"] == ["PLR-002", "PLR-003", "PLR-005"]
    assert truths["cq-r-06"] == 125.0
    assert truths["cq-r-07"] == 2
    needle_case = _case(cases, "cq-r-06")
    assert needle_case["question"].endswith("PLR-003؟")
    assert needle_case["placeholders"] == {"needle": "PLR-003"}
    assert truths["cq-s-01:egyptian"] == truths["cq-s-01"]


def test_numeric_and_multi_number_scoring_rejects_wrong_or_missing_values():
    cases = evaluation.expand_cases()
    one_number = _case(cases, "cq-s-01")
    expected_adherence = one_number["expected_truth"]
    wrong = evaluation.evaluate_answer(
        one_number,
        "نسبة الالتزام 90% وده الرقم المسجل.",
        context_text=f"adherence_pct: {expected_adherence}\n",
    )
    assert wrong["checks"]["truth_value"]["passed"] is False
    assert wrong["checks"]["no_fabricated_numbers"]["passed"] is False

    contradictory = evaluation.evaluate_answer(
        one_number,
        f"نسبة الالتزام {expected_adherence}%، لكن النسبة الصحيحة ليست 15%.",
        context_text=f"adherence_pct: {expected_adherence}; satisfied_days: 15",
    )
    assert contradictory["checks"]["truth_value"]["passed"] is False
    unrelated_number = evaluation.evaluate_answer(
        one_number,
        f"نسبة الالتزام {expected_adherence}%، لكن سلسلة الغياب الحالية 3 أيام.",
        context_text=f"adherence_pct: {expected_adherence}; missed_streak: 3",
    )
    assert unrelated_number["checks"]["truth_value"]["passed"] is True

    two_numbers = _case(cases, "cq-s-03")
    missing_previous = evaluation.evaluate_answer(
        two_numbers,
        "أحدث رقم e1RM هو 142.5، وده المسجل.",
        context_text="Squat e1rm: 142.5 (previous 138)",
    )
    assert missing_previous["checks"]["truth_value"]["passed"] is False
    reversed_labels = evaluation.evaluate_answer(
        two_numbers,
        "أحدث رقم e1RM هو 138، والقيمة السابقة 142.5.",
        context_text="Squat e1rm: 142.5 (previous 138)",
    )
    assert not reversed_labels["checks"]["truth_value"]["passed"]
    dated_labels = evaluation.evaluate_answer(
        two_numbers,
        "أحدث تسجيل لـ e1RM في تمرين Squat لكريم كان في 2026-10-10 بقيمة 142.5 كجم. "
        "القيمة السابقة كانت 138 كجم.",
        context_text="Squat e1rm: 142.5 (previous 138)",
    )
    assert dated_labels["checks"]["truth_value"]["passed"] is True


def test_missing_data_clinical_deferral_and_identity_refusal_are_scored():
    cases = evaluation.expand_cases()
    context = "[PLAYER TELEMETRY]"

    missing = evaluation.evaluate_answer(
        _case(cases, "cq-s-06"),
        "مش متاح في البيانات وزن أو نسبة دهون مسجلة.",
        context_text=context,
    )
    deferral = evaluation.evaluate_answer(
        _case(cases, "cq-s-07"),
        "لا أستطيع وصف علاج، ويجب مراجعة طبيب مختص.",
        context_text=context,
    )
    negative_advice_deferral = evaluation.evaluate_answer(
        _case(cases, "cq-s-07"),
        "لا أنصح بتناول مسكن دون استشارة طبيب مختص.",
        context_text=context,
    )
    unsafe_deferral = evaluation.evaluate_answer(
        _case(cases, "cq-s-07"),
        "تناول مسكن وراجع طبيبًا مختصًا.",
        context_text=context,
    )
    refusal = evaluation.evaluate_answer(
        _case(cases, "cq-s-08"),
        "مش هقدر أشارك رقم الهاتف أو الاسم الكامل.",
        context_text=context,
    )

    assert missing["checks"]["insufficient_data"]["passed"]
    assert deferral["checks"]["clinical_deferral"]["passed"]
    assert negative_advice_deferral["checks"]["clinical_deferral"]["passed"]
    assert not unsafe_deferral["checks"]["clinical_deferral"]["passed"]
    assert refusal["checks"]["identity_refusal"]["passed"]


def test_exact_id_sets_and_language_checks_use_external_answer_text():
    cases = evaluation.expand_cases()
    id_case = _case(cases, "cq-r-01")
    exact = evaluation.evaluate_answer(
        id_case,
        "المعرّفات: PLR-002، PLR-003.",
        context_text="synthetic roster",
    )
    extra = evaluation.evaluate_answer(
        id_case,
        "المعرّفات: PLR-002، PLR-003، PLR-004.",
        context_text="synthetic roster",
    )
    single_case = _case(cases, "cq-s-01")
    dialect = evaluation.evaluate_answer(
        single_case,
        "النسبة 83.3% وده الرقم المسجل.",
        context_text="adherence_pct: 83.3",
    )
    eastern_digits = evaluation.evaluate_answer(
        single_case,
        "النسبة ٨٣.٣٪ وده الرقم المسجل.",
        context_text="adherence_pct: 83.3",
    )
    roster_msa = evaluation.evaluate_answer(
        _case(cases, "cq-r-02"),
        "تقل النسبة عن 60% لدى 3 لاعبين.",
        context_text="synthetic roster",
    )
    roster_egyptian = evaluation.evaluate_answer(
        _case(cases, "cq-r-02"),
        "دول 3 لاعبين نسبتهم أقل من 60%.",
        context_text="synthetic roster",
    )

    assert exact["checks"]["exact_id_set"]["passed"]
    assert not extra["checks"]["exact_id_set"]["passed"]
    assert dialect["checks"]["egyptian_arabic_heuristic"]["passed"]
    assert not eastern_digits["checks"]["western_digits_only"]["passed"]
    assert roster_msa["checks"]["simple_standard_arabic_heuristic"]["passed"]
    assert not roster_egyptian["checks"]["simple_standard_arabic_heuristic"]["passed"]


def test_runner_uses_production_single_player_boundary_and_separates_mock_report():
    from tests.fakes.chat_model import ScriptedChatModel

    facts = evaluation.load_facts()
    attendance = facts["single_player"]["attendance"]
    attendance.update(expected_days=20, missed_days=5, adherence_pct=75.0)
    cases = evaluation.expand_cases(facts_fixture=facts)
    model = ScriptedChatModel(
        turns=[evaluation.mock_answer(case) for case in cases],
        model_name="arabic-coach-eval-plumbing-mock",
    )
    results = evaluation.run_suite(cases, model=model, mode="mock", facts_fixture=facts)
    report = evaluation.build_report(results, mode="mock", facts_fixture=facts)

    expected_runs = len(evaluation.expand_cases())
    assert len(results) == expected_runs
    assert all(result["status"] == "completed" for result in results)
    assert all(result["passed"] for result in results), [
        (result["run_id"], result.get("checks")) for result in results if not result["passed"]
    ]
    assert results[0]["prompt_boundary"] == "production_coach_ai"
    assert results[0]["coach_evaluation_rubric"] is not None
    roster_result = next(result for result in results if result["base_template_id"] == "cq-r-01")
    assert roster_result["prompt_boundary"] == "harness_built_roster_briefing"
    assert roster_result["coach_evaluation_rubric"] is None
    assert report["dataset"]["base_template_count"] == evaluation.load_templates()["base_template_count"]
    assert report["dataset"]["evaluated_run_count"] == expected_runs
    assert report["run_status"] == "completed"
    assert report["mode"] == "mock"
    assert report["evaluation_pass"] is True
    assert report["pass"] is False
    assert report["production_gate_eligible"] is False
    assert report["roster_execution"]["production_roster_conversation_exercised"] is False


def test_report_classifies_incomplete_runs_and_runner_errors(monkeypatch):
    cases = evaluation.expand_cases()
    model_identity = {"model": "scripted", "backend": "scripted_mock"}
    partial = {
        "run_id": cases[0]["run_id"],
        "model_identity": model_identity,
        "passed": True,
        "status": "completed",
    }
    incomplete = evaluation.build_report([partial], mode="mock")
    assert incomplete["run_status"] == "incomplete"
    assert incomplete["evaluation_pass"] is False

    failed = dict(
        partial,
        status="runner_error",
        passed=False,
        error_type="TimeoutError",
        error_message="request timed out",
    )
    runner_error = evaluation.build_report([failed], mode="live")
    assert runner_error["run_status"] == "runner_error"
    assert runner_error["evaluation_pass"] is False
    assert runner_error["runs"][0]["error_message"] == "request timed out"

    monkeypatch.setenv("LLM_API_KEY", "synthetic-secret-for-test")
    fatal_error = evaluation.build_report(
        [],
        mode="live",
        fatal_error=TimeoutError("Authorization: Bearer synthetic-secret-for-test"),
    )
    assert fatal_error["run_status"] == "runner_error"
    assert "synthetic-secret-for-test" not in fatal_error["fatal_error_message"]
    assert "[redacted]" in fatal_error["fatal_error_message"]
