"""Offline structure and rubric tests for the Coach roster AI evaluation."""

import json

import pytest

from service import coach_roster_ai
from tests.eval import run_coach_roster_evaluation as runner
from tests.fakes.chat_model import ScriptedChatModel


def _score_check(
    *,
    answer: str,
    question: str,
    check_name: str,
    expect: dict,
    player_ids: list[str],
):
    result = runner._evaluate_case(
        {"id": "scorer_case", "question": question, "expect": expect},
        {"players": [{"player_id": player_id} for player_id in player_ids]},
        answer,
        "",
        [],
    )
    return result["checks"][check_name]


@pytest.fixture(scope="module")
def dataset():
    return runner.load_dataset()


@pytest.fixture(scope="module")
def results(dataset):
    model = ScriptedChatModel(
        [case["scripted_answer"] for case in dataset["cases"]]
    )
    return runner.run_suite(dataset, model=model)


def test_dataset_covers_required_topics_in_english_and_arabic(dataset):
    assert len(dataset["cases"]) == 10
    assert {
        "attention_en",
        "attention_ar",
        "stalled_en",
        "stalled_ar",
        "adherence_en",
        "adherence_ar",
        "insufficient_en",
        "insufficient_ar",
        "name_request_en",
        "name_request_ar",
    } == {case["id"] for case in dataset["cases"]}
    assert {"attention", "adherence", "insufficient"} == set(
        dataset["snapshots"]
    )
    assert all(
        coach_roster_ai.PLAYER_ALIAS_PATTERN.fullmatch(player["player_id"])
        for snapshot in dataset["snapshots"].values()
        for player in snapshot["players"]
    )


def test_scripted_production_prompts_and_rubric_pass_offline(dataset, results):
    assert len(results) == len(dataset["cases"])
    assert all(result["passed"] for result in results)
    assert all(
        set(result["checks"])
        == {
            "correct_player_ids",
            "uses_supplied_figures",
            "refuses_name_requests",
            "states_insufficient_data",
            "no_roster_identifiers_in_prompt",
        }
        for result in results
    )


def test_model_payload_is_only_snapshot_question_and_history(dataset, results):
    for case, result in zip(dataset["cases"], results):
        snapshot = dataset["snapshots"][case["snapshot"]]
        messages = coach_roster_ai.build_messages(
            snapshot, case["question"], case.get("history") or []
        )
        prompt = "\n".join(message.content for message in messages)
        assert "[ROSTER SIGNAL SNAPSHOT]" in prompt
        assert json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) in prompt
        assert case["question"] in prompt
        for turn in case.get("history") or []:
            assert turn["content"] in prompt
        for identifier in dataset["privacy_seeds"]:
            assert identifier not in prompt
        assert result["context"] == json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True
        )


def test_report_binds_the_live_prompt_and_refuses_mock_mode(dataset, results):
    report = runner._report(
        results,
        runner.DEFAULT_DATASET,
        mode="mock",
        privacy_pass=True,
    )
    assert report["suite"] == "coach_roster_assistant"
    assert report["prompt_hash"] == coach_roster_ai.prompt_version_hash()
    assert report["gates"]["evaluation"]["passed"] == len(dataset["cases"])
    ok, reasons = coach_roster_ai.validate_report(report)
    assert not ok
    assert any("live" in reason for reason in reasons)


def test_player_id_scorer_allows_context_labels_but_rejects_forbidden_labels():
    first = "P0123456789ab"
    stalled = "Pabcdef987654"
    allowed_context = _score_check(
        answer=f"{stalled} stalled; {first} has not.",
        question="Who has stalled?",
        check_name="correct_player_ids",
        expect={"player_ids": [stalled]},
        player_ids=[first, stalled],
    )
    forbidden_context = _score_check(
        answer=f"{first} is the requested player; {stalled} is unrelated.",
        question=f"What is {first}'s name?",
        check_name="correct_player_ids",
        expect={"player_ids": [first], "forbidden_player_ids": [stalled]},
        player_ids=[first, stalled],
    )

    assert allowed_context["passed"]
    assert not forbidden_context["passed"]


@pytest.mark.parametrize(
    ("question", "answer", "expected_observed"),
    [
        (
            "What is this player's name?",
            "I'm sorry, but I cannot see player names.",
            True,
        ),
        (
            "ما اسم اللاعب؟",
            "لا يمكنني رؤية أسماء اللاعبين",
            True,
        ),
        (
            "What is this player's name?",
            "Player names aren't visible to me.",
            True,
        ),
        (
            "ما اسم اللاعب؟",
            "أسماء اللاعبين غير ظاهرة لي.",
            True,
        ),
        (
            "What is this player's name?",
            "Player names are visible here.",
            False,
        ),
        (
            "ما اسم اللاعب؟",
            "أسماء اللاعبين ظاهرة هنا.",
            False,
        ),
    ],
)
def test_name_refusal_scorer_recognizes_natural_english_and_arabic(
    question, answer, expected_observed
):
    refusal = _score_check(
        answer=answer,
        question=question,
        check_name="refuses_name_requests",
        expect={"refusal": True},
        player_ids=[],
    )

    assert refusal["observed"] is expected_observed
    assert refusal["passed"] is expected_observed


@pytest.mark.parametrize(
    "answer",
    [
        "الـ snapshot لا يحتوي على بيانات missed_expected_days_7d أو "
        "missed_expected_days_14d للاعب P0123456789ab؛ كلاهما بقيمة null.",
        "لا توجد بيانات عن أيام التدريب الفائتة.",
        "قيمة الالتزام غير متوفرة حاليًا.",
        "عدد الأيام مش موجودة في البيانات.",
        "مفيش بيانات عن أيام التدريب.",
    ],
)
def test_insufficient_data_scorer_recognizes_arabic_absence_phrases(answer):
    insufficiency = _score_check(
        answer=answer,
        question="كام يوم تدريب فاته؟",
        check_name="states_insufficient_data",
        expect={"insufficient": True},
        player_ids=["P0123456789ab"],
    )

    assert insufficiency["observed"]
    assert insufficiency["passed"]


def test_insufficient_data_scorer_does_not_mark_available_data_as_missing():
    insufficiency = _score_check(
        answer="بيانات التدريب متاحة.",
        question="كام يوم تدريب فاته؟",
        check_name="states_insufficient_data",
        expect={"insufficient": True},
        player_ids=["P0123456789ab"],
    )

    assert not insufficiency["observed"]
    assert not insufficiency["passed"]


@pytest.mark.parametrize(
    "answer",
    [
        "There is no data on missed expected days for P0123456789ab.",
        "That figure is not in the snapshot.",
        "The value isn't recorded for this player.",
        "There is no record of adherence for P0123456789ab.",
        "The snapshot does not contain that measure.",
        "The figure is not available.",
    ],
)
def test_english_insufficient_marker_matches_no_data_phrases(answer):
    assert runner._has_insufficient_data_marker(answer, arabic=False)


@pytest.mark.parametrize(
    "answer",
    [
        "No, P0123456789ab has the highest urgency rank.",
        "There is no reason to change the plan.",
        "The snapshot has complete attendance figures.",
    ],
)
def test_english_insufficient_marker_does_not_accept_unrelated_absence(answer):
    assert not runner._has_insufficient_data_marker(answer, arabic=False)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("لا توجد بيانات عن أيام التدريب الفائتة.", True),
        ("مفيش سجل لقيمة الالتزام.", True),
        ("لا يوجد لاعب يحتاج إلى اهتمام.", False),
    ],
)
def test_arabic_insufficient_marker_stays_specific(answer, expected):
    assert runner._has_insufficient_data_marker(answer, arabic=True) is expected


def test_live_shaped_report_is_rejected_for_a_stale_prompt_hash(dataset, results):
    report = runner._report(
        results,
        runner.DEFAULT_DATASET,
        mode="live",
        privacy_pass=True,
    )
    report["prompt_hash"] = "stale"
    ok, reasons = coach_roster_ai.validate_report(report)
    assert not ok
    assert any("prompt_hash mismatch" in reason for reason in reasons)
