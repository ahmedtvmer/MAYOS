import json
import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.eval.parity_gate import print_gate_summary
from tests.eval.suites.routing import (
    DATASET_FILE,
    RoutingSuite,
    _action_matches,
    _case_outcome,
    _hermetic_arabic_swap_classification,
    _load_routing_cases,
    _observe_case,
    _observe_ledger_writes,
)


def test_routing_dataset_has_required_language_mix_and_composite_action():
    cases = _load_routing_cases()
    arabic = [case for case in cases if case["language"] == "arabic"]

    assert len(cases) == 40
    assert Counter(case["arabic_group"] for case in arabic) == {
        "egyptian": 14,
        "standard": 3,
        "mixed": 3,
    }
    assert any(
        case["expected_intent"] == "composite_intent" and case["expected_action"]
        for case in arabic
    )
    assert all(case["review_status"] == "owner_reviewed" for case in arabic)
    egyptian = [case for case in arabic if case["arabic_group"] == "egyptian"]
    assert sum(bool(re.search(r"[A-Za-z]", case["text"])) for case in egyptian) <= 2
    assert any("عايز أبدّل البنش" in case["text"] for case in egyptian)
    assert any("بدّل السكوات بالليج برس" in case["text"] for case in egyptian)
    assert sum(
        (case.get("expected_action") or {}).get("target_exercise") == "Bench Press (Dumbbell)"
        for case in egyptian
    ) < sum(bool((case.get("expected_action") or {}).get("target_exercise")) for case in egyptian)
    assert all(
        (case.get("expected_action") or {}).get("target_weekly_frequency") == 4
        for case in cases
        if (case.get("expected_action") or {}).get("kind") == "program_mutation"
    )
    franco = next(case for case in egyptian if case.get("franco_intercept_expected"))
    assert franco["expected_intent"] == "clinical_intercept"
    assert franco["clinical_intercept_warranted"] is False
    assert sum(case.get("franco_intercept_expected") is True for case in arabic) == 1


def _dataset_with_arabic_status(tmp_path, monkeypatch, review_status):
    source_path = Path(__file__).parent / "datasets" / DATASET_FILE
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    for case in payload["cases"]:
        if case["language"] == "arabic":
            case["review_status"] = review_status
    dataset_dir = tmp_path / "datasets"
    dataset_dir.mkdir()
    (dataset_dir / DATASET_FILE).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("EVAL_DATASETS_DIR", str(dataset_dir))


def test_program_mutation_matches_generated_split_display_by_family():
    expected = {
        "kind": "program_mutation",
        "target_weekly_frequency": 4,
        "target_split_type": "upper/lower",
    }
    observed = {
        **expected,
        "target_split_type": "Upper / Lower (Arms & Delts Augmented)",
    }

    assert _action_matches(expected, observed)


@pytest.mark.parametrize("split_type", ["Push / Pull / Legs", "Full Body 4-Day"])
def test_program_mutation_rejects_a_different_split_family(split_type):
    expected = {
        "kind": "program_mutation",
        "target_split_type": "upper/lower",
    }
    observed = {"kind": "program_mutation", "target_split_type": split_type}

    assert not _action_matches(expected, observed)


def test_en_history_03_whole_session_request_stays_on_history_route(tmp_path, monkeypatch):
    from agent import assistant_graph
    from tests.fakes.chat_model import ScriptedChatModel

    scripted_model = ScriptedChatModel(["History fallback should not be used."])
    monkeypatch.setattr(assistant_graph, "llm", scripted_model)
    case = next(case for case in _load_routing_cases() if case["id"] == "en-history-03")

    observation = _observe_case(case, tmp_path)

    assert observation.get("runner_error") is None
    assert observation["observed_intent"] == "exercise_history"
    assert scripted_model.calls == []


def test_hermetic_routing_counts_every_owner_reviewed_case():
    record = RoutingSuite().run_hermetic(None)

    assert (record["score"], record["total"]) == (40, 40)
    assert record["unreviewed_count"] == 0
    assert record["passed"] is True
    assert record["would_be_passed"] is True
    assert record["unauthorized_actions"] == 0
    graph_cases = {
        case["case_id"]
        for case in record["cases"]
        if case["scripted_classifier_used"]
    }
    assert graph_cases == {
        "ar-egyptian-01",
        "ar-egyptian-02",
        "ar-egyptian-03",
        "ar-egyptian-07",
        "ar-standard-01",
        "ar-mixed-01",
        "ar-mixed-03",
    }
    composite = next(case for case in record["cases"] if case["case_id"] == "ar-egyptian-07")
    assert composite["observed_intent"] == "composite_intent"
    assert len(composite["executed_actions"]) == 1
    assert composite["action_match"] is True
    leg_press = next(case for case in record["cases"] if case["case_id"] == "ar-egyptian-03")
    assert leg_press["expected_action"]["target_exercise"] == "45° Leg Press (Plate-Loaded)"
    assert leg_press["executed_actions"][0]["target_exercise"] == "45° Leg Press (Plate-Loaded)"
    assert leg_press["action_match"] is True
    safer_alternative = next(case for case in record["cases"] if case["case_id"] == "ar-mixed-03")
    assert safer_alternative["observed_intent"] == "coaching_qa"
    assert safer_alternative["intent_match"] is True
    assert safer_alternative["executed_actions"] == []
    swap_cases = [
        case
        for case in _load_routing_cases()
        if case["language"] == "arabic"
        and (case.get("expected_action") or {}).get("kind") == "exercise_substitution"
    ]
    for case in swap_cases:
        scripted = _hermetic_arabic_swap_classification(case)
        if case["id"] == "ar-egyptian-07":
            assert scripted == {
                "intent": "composite_intent",
                "source_exercise": "Bench Press (Barbell)",
                "target_exercise": "Dumbbell Bench Press",
                "has_swap": True,
                "has_additional_request": True,
            }
        else:
            assert scripted["source_exercise"] != case["expected_action"]["source_exercise"]
        assert scripted["target_exercise"] in {
            "Dumbbell Bench Press",
            "Incline Bench Press (Barbell)",
            "Leg Press",
        }
    mixed_suggestion = next(case for case in _load_routing_cases() if case["id"] == "ar-mixed-03")
    assert _hermetic_arabic_swap_classification(mixed_suggestion) == {
        "intent": "exercise_substitution",
        "source_exercise": "Back Squat (Barbell)",
        "target_exercise": "Goblet Squat",
        "has_swap": True,
    }


def test_hermetic_routing_excludes_unreviewed_arabic_from_score(tmp_path, monkeypatch):
    _dataset_with_arabic_status(tmp_path, monkeypatch, "pending")
    record = RoutingSuite().run_hermetic(None)

    assert (record["score"], record["total"], record["bar"]) == (
        20,
        40,
        {"kind": "count", "value": 38},
    )
    assert record["passed"] is True
    assert record["would_be_passed"] is False
    assert record["unauthorized_actions"] == 0
    assert record["unreviewed_count"] == 20
    assert record["failure_reasons"] == []
    assert any("unreviewed" in reason and "excluded" in reason for reason in record["would_be_failure_reasons"])
    assert all(
        case["review_status"] == "pending"
        for case in record["cases"]
        if case["language"] == "arabic"
    )
    live_summary, live_reasons = RoutingSuite().validate(record, {"mode": "live"})
    assert live_summary["passed"] is False
    assert any("Arabic case(s) are unreviewed" in reason for reason in live_reasons)


def test_gate_summary_reports_unauthorized_actions_and_clinical_misses(tmp_path, monkeypatch, capsys):
    _dataset_with_arabic_status(tmp_path, monkeypatch, "pending")
    record = RoutingSuite().run_hermetic(None)

    print_gate_summary(
        {"mode": "hermetic"},
        record["failure_reasons"],
        [{"name": "routing", **record}],
    )

    output = capsys.readouterr().out
    assert "routing: 20/40 (bar ≥38/40)" in output
    assert "unauthorized actions=0" in output
    assert "clinical misses=0" in output
    assert "unreviewed=20" in output
    assert "would-be gate=FAIL" in output
    assert "PASS (hermetic plumbing)" in output


def test_hermetic_cli_counts_reviewed_arabic_cases(tmp_path, capsys):
    from tests.eval.run_evaluation import main

    report_path = tmp_path / "hermetic-report.json"
    assert main(["--hermetic", "--report", str(report_path)]) == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    routing = report["suite_results"]["routing"]
    assert report["gate"]["validation_passed"] is True
    assert report["gate"]["status"] == "hermetic_check_only"
    assert routing["passed"] is True
    assert routing["would_be_passed"] is True
    assert routing["unreviewed_count"] == 0
    output = capsys.readouterr().out
    assert "PLAYER MODEL GATE: NOT RUN (hermetic validation only)" in output
    assert "routing: 40/40" in output
    assert "unauthorized actions=0" in output
    assert "unreviewed=0" in output
    assert "would-be gate=PASS" in output


def test_partial_suite_cli_marks_player_gate_not_run(tmp_path, capsys):
    from tests.eval.run_evaluation import main

    report_path = tmp_path / "routing-partial-report.json"
    assert main(["--hermetic", "--suite", "routing", "--report", str(report_path)]) == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["partial"] is True
    assert report["selected_suites"] == ["routing"]
    assert list(report["suite_results"]) == ["routing"]
    assert report["gate"]["passed"] is False
    assert report["gate"]["validation_passed"] is True
    assert report["gate"]["status"] == "partial_suite_run"
    routing = report["suite_results"]["routing"]
    assert (routing["score"], routing["total"]) == (40, 40)
    assert routing["unauthorized_actions"] == 0
    assert routing["would_be_passed"] is True
    output = capsys.readouterr().out
    assert "routing: 40/40" in output
    assert "unauthorized actions=0" in output
    assert "PLAYER MODEL GATE: NOT RUN (partial suite run)" in output
    assert main(["--check-report", str(report_path)]) == 0
    assert "PLAYER MODEL GATE: NOT RUN (partial suite run)" in capsys.readouterr().out


def test_program_write_in_no_action_case_is_observed_as_unauthorized():
    class Ledger:
        def __init__(self):
            self.active = _program("Bench Press (Barbell)")
            self.profile = {"weekly_frequency": 3}
            self.conn = SimpleNamespace(
                execute=lambda *_args: SimpleNamespace(fetchone=lambda: ("saved-program",))
            )

        def get_active_program(self):
            return self.active

        def save_training_program(self, program_data, *_args, **_kwargs):
            self.active = _program("Bench Press (Dumbbell)", "bench-dumbbell")
            return "saved-program"

        def update_player_frequency(self, _frequency):
            pass

        def upsert_player_profile(self, _profile_data, _user_id=1):
            pass

        def upsert_player_profile_with_weight_history(self, _profile_data, _entry_date):
            pass

        def list_weight_history(self, _start_date, _end_date):
            return []

        def update_player_persona(self, _coach_tone, _custom_instructions):
            pass

        def set_assistant_memory(self, _key, _value):
            pass

        def clear_preferred_name(self):
            pass

        def get_assistant_memory(self):
            return {}

        def set_deload_choice(self, _choice):
            pass

        def get_deload_choice(self):
            return None

    def _program(bench_name, bench_id="bench"):
        names = [bench_name, "Back Squat (Barbell)", "Barbell Row"]
        ids = [bench_id, "squat", "row"]
        return SimpleNamespace(
            weekly_frequency=3,
            split_type="Full Body",
            days=[SimpleNamespace(
                day_name="Full A",
                exercises=[SimpleNamespace(exercise_name=name, exercise_id=exercise_id) for name, exercise_id in zip(names, ids)],
            )],
        )

    ledger = Ledger()
    actions = []
    _observe_ledger_writes(ledger, actions)
    ledger.save_training_program({
        "weekly_frequency": 3,
        "split_type": "Full Body",
        "days": [{"exercises": [{"exercise_id": "bench-dumbbell"}, {"exercise_id": "squat"}, {"exercise_id": "row"}]}],
    })

    result = _case_outcome(
        {"id": "en-coaching-01", "language": "english", "expected_intent": "coaching_qa",
         "clinical_intercept_warranted": False, "expected_action": None},
        {"observed_intent": "coaching_qa", "executed_actions": actions},
    )
    assert actions[0]["kind"] == "exercise_substitution"
    assert actions[0]["validated"] is True
    assert result["unauthorized_actions"] == actions
    assert result["passed"] is False


def test_franco_case_requires_the_franco_intercept_flag():
    franco = next(case for case in _load_routing_cases() if case.get("franco_intercept_expected"))
    result = _case_outcome(
        franco,
        {"observed_intent": "clinical_intercept", "franco_intercept": False, "executed_actions": []},
    )

    assert result["franco_intercept_match"] is False
    assert result["passed"] is False


def test_frequency_profile_write_is_allowed_only_as_part_of_requested_program_change():
    case = next(
        case for case in _load_routing_cases()
        if case["id"] == "en-program-01"
    )
    action = {
        "kind": "program_mutation",
        "target_weekly_frequency": 4,
        "validated": True,
        "succeeded": True,
    }
    frequency_write = {
        "kind": "profile_write",
        "field": "weekly_frequency",
        "new_value": 4,
        "validated": True,
        "succeeded": True,
    }

    result = _case_outcome(
        case,
        {"observed_intent": "program_mutation", "executed_actions": [action, frequency_write]},
    )
    assert result["passed"] is True
    duplicate_frequency_write = _case_outcome(
        case,
        {"observed_intent": "program_mutation", "executed_actions": [action, frequency_write, dict(frequency_write)]},
    )
    assert duplicate_frequency_write["passed"] is False
    assert len(duplicate_frequency_write["unauthorized_actions"]) == 1
    result_with_extra_write = _case_outcome(
        case,
        {"observed_intent": "program_mutation", "executed_actions": [action, frequency_write, {
            "kind": "profile_write", "field": "preferred_name", "new_value": "Sam",
            "validated": True, "succeeded": True,
        }]},
    )
    assert result_with_extra_write["passed"] is False
    assert len(result_with_extra_write["unauthorized_actions"]) == 1


def test_second_action_in_arabic_composite_fails_even_above_routing_bar(tmp_path, monkeypatch):
    _dataset_with_arabic_status(tmp_path, monkeypatch, "owner_reviewed")

    suite = RoutingSuite()
    record = suite.run_hermetic(None)
    composite = next(case for case in record["cases"] if case["case_id"] == "ar-egyptian-07")
    composite["executed_actions"].append(dict(composite["executed_actions"][0]))

    summary, reasons = suite.validate(record, {"mode": "live"})

    assert summary["score"] == 39
    assert summary["score"] >= summary["bar"]["value"]
    assert summary["unauthorized_actions"] == 1
    assert summary["passed"] is False
    assert any("unauthorized action" in reason for reason in reasons)
