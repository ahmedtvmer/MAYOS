import json
from pathlib import Path

from langchain_core.messages import HumanMessage

from agent import assistant_graph as graph
from agent import clinical_guard
from agent.prompts import FRANCO_ARABIC_INPUT_RESPONSE


FIXTURE_PATH = Path(__file__).parent / "eval" / "datasets" / "franco_reviewed_cases.json"
FRANCO_CASES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
ARABIC_BASELINE_PATH = Path(__file__).parent / "eval" / "datasets" / "arabic_reviewed_cases.json"
ENGLISH_NEGATIVES_PATH = Path(__file__).parent / "eval" / "datasets" / "franco_english_negatives.json"
ENGLISH_NEGATIVES = json.loads(ENGLISH_NEGATIVES_PATH.read_text(encoding="utf-8"))


def _state(query):
    return {"messages": [HumanMessage(content=query)], "telemetry_context": "", "intent_metadata": {}}


def _franco_clinical(text):
    detector = graph.is_franco_arabic(text)
    guard = (
        clinical_guard.is_franco_clinical_franco_message
        if detector else clinical_guard.is_franco_clinical
    )
    return guard(text)


def _assert_reviewed_split(split_name):
    cases = FRANCO_CASES["splits"][split_name]
    assert cases
    for case in cases:
        assert _franco_clinical(case["text"]) is case["clinical_intercept_warranted"], case["id"]
        route = graph.router_node(_state(case["text"]))
        if case["launch_block_expected"]:
            assert route["intent"] == "clinical_intercept", case["id"]
            assert route["intent_metadata"]["franco"] is True, case["id"]
            response = graph.clinical_intercept_node({**_state(case["text"]), **route})
            assert response["response_content"] == FRANCO_ARABIC_INPUT_RESPONSE, case["id"]
        else:
            assert route["intent"] != "clinical_intercept", case["id"]


def test_reviewed_franco_fixture_has_owner_accepted_splits_and_separate_adversarial_holdout():
    splits = FRANCO_CASES["splits"]
    tuning_ids = {case["id"] for case in splits["tuning"]}
    held_out_ids = {case["id"] for case in splits["held_out"]}
    baseline = json.loads(ARABIC_BASELINE_PATH.read_text(encoding="utf-8"))["franco_fail_closed"]
    baseline_cases = {
        case["id"]: case for case in splits["tuning"]
        if case["source"] == "arabic_reviewed_cases.json:franco_fail_closed"
    }
    supplemental = [
        case for case in [*splits["tuning"], *splits["held_out"]]
        if case["source"].startswith("docs/specs/franco-arabic-input-343.md")
    ]

    assert FRANCO_CASES["status"] == "owner_reviewed"
    assert FRANCO_CASES["reviewed_on"] == "2026-10-17"
    assert set(baseline_cases) == {case["id"] for case in baseline}
    for case in baseline:
        copied = baseline_cases[case["id"]]
        assert copied["text"] == case["text"]
        assert copied["clinical_intercept_warranted"] == case["clinical_intercept_warranted"]
        assert copied["launch_block_expected"] == case["launch_block_expected"]
        assert copied["launch_response_kind"] == case["launch_response_kind"]
    assert len(supplemental) == 26
    assert len(tuning_ids & held_out_ids) == 0
    assert all(case["review_status"] == "OWNER_REVIEWED" for case in [*splits["tuning"], *splits["held_out"]])
    assert all(case["status"] == "UNREVIEWED" and case["gate"] is False for case in FRANCO_CASES["unreviewed_adversarial_holdout"])
    assert not ({case["id"] for case in FRANCO_CASES["unreviewed_adversarial_holdout"]} & (tuning_ids | held_out_ids))


def test_reviewed_tuning_split_meets_clinical_and_launch_expectations():
    _assert_reviewed_split("tuning")


def test_reviewed_held_out_split_meets_clinical_and_launch_expectations():
    _assert_reviewed_split("held_out")


def test_reviewed_clinical_cases_are_intercepted_when_script_detection_misses():
    reviewed = {
        case["id"]: case
        for split in FRANCO_CASES["splits"].values()
        for case in split
    }
    for case_id in ("fx-inj-01", "fx-variant-02"):
        case = reviewed[case_id]
        assert case["clinical_intercept_warranted"] is True
        assert graph.is_franco_arabic(case["text"]) is False
        route = graph.router_node(_state(case["text"]))
        assert route["intent"] == "clinical_intercept"
        assert route["intent_metadata"]["franco"] is True


def test_candidate_clinical_match_intercepts_when_franco_detector_is_false():
    query = "masken after bench"

    assert graph.is_franco_arabic(query) is False
    assert clinical_guard.is_franco_clinical(query) is True
    route = graph.router_node(_state(query))
    assert route["intent"] == "clinical_intercept"
    assert route["intent_metadata"]["franco"] is True


def test_a_single_ambiguous_common_word_does_not_trigger_franco_refusal():
    for query in ("ana", "leh", "wa3", "mesh", "gamed"):
        assert graph.is_franco_arabic(query) is False
        assert graph.router_node(_state(query))["intent"] != "clinical_intercept"


def test_two_common_franco_words_provide_corroborating_evidence():
    assert graph.is_franco_arabic("ana leh") is True
    route = graph.router_node(_state("ana leh"))
    assert route["intent"] == "clinical_intercept"
    assert route["intent_metadata"]["franco"] is True


def test_ordinary_english_gym_and_digit_ending_words_are_not_intercepted():
    queries = [
        "3x10", "5kg", "rpe8", "day2", "W3", "2 sets of 8", "80kg x 5",
        "2nd set", "5x5 then 3x8", "b2b sessions", "The mesh shirt fits well",
        "I gamed the system", "Zone2", "omega3", "Phase2", "plan2", "Bench2",
        "squat2", "Program2", "LDL3", "mp3", "week12", "top10",
        "did 3 sets of 8 at 60kg", "3x10 bench then 5x5 squat",
        "RPE 8 on day 2, felt strong",
    ]

    for query in queries:
        assert graph.is_franco_arabic(query) is False, query
        assert clinical_guard.is_franco_clinical(query) is False, query
        assert graph.router_node(_state(query))["intent"] != "clinical_intercept", query


def test_large_english_negative_set_matches_master_interception_results():
    cases = ENGLISH_NEGATIVES["cases"]
    texts = {case["text"] for case in cases}
    required = {
        "form", "form check", "perform", "format", "warm", "warm up", "warm-up", "worm",
        "took", "T2 vs T3 split", "omega3", "H2O", "e2e", "Zone2", "plan2", "mp3",
        "week12", "top10", "b2b", "1RM", "3RM", "x3", "PR", "rack pull", "RDL",
        "Romanian deadlift", "deload", "rest day", "sore after legs", "Ahmed", "Omar",
        "Karim", "Hossam", "Tamer", "Mona", "Sara", "ok", "thanks", "pt2", "Phase2",
        "Bench2", "squat2", "Program2", "LDL3", "my form was off on bench",
        "took omega3 and creatine",
    }

    assert ENGLISH_NEGATIVES["master_commit"] == "dcfb0b04"
    assert len(cases) >= 150
    assert required <= texts
    mismatches = [
        case["id"] for case in cases
        if (graph._clinical_turn_metadata(case["text"]) is not None) is not case["master_intercepted"]
    ]
    assert not mismatches, mismatches


def test_franco_normalization_errors_fail_closed_to_the_fixed_refusal(monkeypatch):
    def fail_normalization(_text):
        raise RuntimeError("normalization failed")

    monkeypatch.setattr(clinical_guard, "normalize_arabic_text", fail_normalization)
    route = graph.router_node(_state("masken after bench"))

    assert route["intent"] == "clinical_intercept"
    assert route["intent_metadata"]["franco"] is True
    response = graph.clinical_intercept_node({**_state("masken after bench"), **route})
    assert response["response_content"] == FRANCO_ARABIC_INPUT_RESPONSE
