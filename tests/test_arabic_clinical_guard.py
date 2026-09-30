import json
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from agent import assistant_graph as graph
from agent import clinical_guard
from agent.prompts import (
    ARABIC_CLINICAL_SAFEGUARD_RESPONSE,
    ARABIC_DIAGNOSIS_SAFEGUARD_RESPONSE,
    CLINICAL_SAFEGUARD_RESPONSE,
    FRANCO_ARABIC_INPUT_RESPONSE,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "issue_138_arabic_guard.json"
ISSUE_138_FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _state(query: str) -> dict:
    return {"messages": [HumanMessage(content=query)], "telemetry_context": "", "intent_metadata": {}}


@pytest.mark.parametrize(
    "query",
    [
        "وَجَــعٌ في كتفي",
        "آلام كتفي",
        "إصابة في الركبة",
        "اتلوى كاحلي",
        "وبالوجع في كتفي",
        "بيوجعني أثناء السكوات",
        "للألم في الركبة",
        "ركبتي طقت وبتوجعني",
        "كتفي متورم",
        "اتقطعت عضلة الساق",
        "اتكسر إصبعي",
        "انكسر العظم",
        "كسور في الركبة",
        "عملية جراحية في الكتف",
    ],
)
def test_arabic_normalization_and_attached_affixes_trigger(query):
    assert clinical_guard.evaluate_clinical_semantic_guard(query) == (True, 1.0)


def test_normalize_arabic_text_removes_marks_and_unifies_letter_variants():
    assert clinical_guard.normalize_arabic_text("أَإِآـىة") == "ااايه"


def test_arabic_safeguards_use_latin_mayos_brand():
    assert "MAYOS" in ARABIC_CLINICAL_SAFEGUARD_RESPONSE
    assert "MAYOS" in ARABIC_DIAGNOSIS_SAFEGUARD_RESPONSE
    assert "مايوس" not in ARABIC_CLINICAL_SAFEGUARD_RESPONSE
    assert "مايوس" not in ARABIC_DIAGNOSIS_SAFEGUARD_RESPONSE


@pytest.mark.parametrize(
    "query",
    [
        "ركبتي بتوجعني after squat",
        "I felt a sharp pop in my knee أثناء السكوات",
    ],
)
def test_mixed_arabic_and_english_clinical_messages_intercept(query):
    assert graph.router_node(_state(query))["intent"] == "clinical_intercept"


def test_arabic_injury_uses_arabic_clinical_safeguard():
    route = graph.router_node(_state("ركبتي بتوجعني أثناء السكوات"))
    response = graph.clinical_intercept_node({**_state("ركبتي بتوجعني أثناء السكوات"), **route})

    assert route["intent"] == "clinical_intercept"
    assert response["response_content"] == ARABIC_CLINICAL_SAFEGUARD_RESPONSE


def test_arabic_diagnosis_uses_arabic_diagnosis_safeguard():
    query = "ما الذي يسبب ألم الرسغ عندي؟"
    route = graph.router_node(_state(query))
    response = graph.clinical_intercept_node({**_state(query), **route})

    assert route["intent_metadata"]["mode"] == "diagnosis"
    assert response["response_content"] == ARABIC_DIAGNOSIS_SAFEGUARD_RESPONSE


def test_english_clinical_reply_is_unchanged():
    query = "I felt a sharp pop in my shoulder"
    reply = graph.clinical_intercept_node(
        {**_state(query), "intent_metadata": {"raw_query": query}}
    )

    assert reply["response_content"] == CLINICAL_SAFEGUARD_RESPONSE


def test_arabic_path_fails_closed_when_normalization_raises(monkeypatch):
    def raise_error(_text):
        raise RuntimeError("normalization failed")

    monkeypatch.setattr(clinical_guard, "normalize_arabic_text", raise_error)

    assert clinical_guard.evaluate_clinical_semantic_guard("رسالة عربية عادية") == (True, 1.0)
    assert graph.router_node(_state("رسالة عربية عادية"))["intent"] == "clinical_intercept"


@pytest.mark.parametrize(
    "entry",
    [entry for entry in ISSUE_138_FIXTURE["player_messages"] if entry["guard_should_trigger"]],
    ids=lambda entry: entry["id"],
)
def test_issue_138_arabic_injuries_are_intercepted(entry):
    route = graph.router_node(_state(entry["text"]))
    assert route["intent"] == "clinical_intercept"


def test_issue_138_benign_arabic_false_positive_ids():
    benign_messages = [entry for entry in ISSUE_138_FIXTURE["player_messages"] if not entry["guard_should_trigger"]]
    false_positives = []
    for entry in benign_messages:
        route = graph.router_node(_state(entry["text"]))
        if route["intent"] == "clinical_intercept":
            false_positives.append(entry["id"])

    assert false_positives == []


@pytest.mark.parametrize(
    "query",
    [
        "عايز أعرف قطعة الفراخ فيها كام بروتين",
        "أنا في مرحلة تقطيع",
        "أنا في فترة نفخ",
        "كسرت الرقم في السكوات النهارده",
        "عملية التضخيم ماشية كويس",
    ],
)
def test_arabic_gym_and_diet_phrases_are_not_clinical_hits(query):
    assert clinical_guard.evaluate_clinical_semantic_guard(query) == (False, 0.0)
    assert graph.router_node(_state(query))["intent"] != "clinical_intercept"


@pytest.mark.parametrize(
    "entry",
    ISSUE_138_FIXTURE["franco_fail_closed"],
    ids=lambda entry: entry["id"],
)
def test_issue_138_franco_messages_get_fixed_reply(entry):
    route = graph.router_node(_state(entry["text"]))
    response = graph.clinical_intercept_node({**_state(entry["text"]), **route})

    assert route["intent"] == "clinical_intercept"
    assert route["intent_metadata"]["franco"] is True
    assert response["response_content"] == FRANCO_ARABIC_INPUT_RESPONSE


@pytest.mark.parametrize(
    "query",
    [
        "ana 3ayez split keda",
        "bet-waga3ny",
        "wa3 ba2a",
        "mesh 7aga ba2a",
        "gamed 7aga ba2a",
    ],
)
def test_common_franco_words_and_digit_words_intercept(query):
    route = graph.router_node(_state(query))
    assert route["intent"] == "clinical_intercept"
    assert route["intent_metadata"]["franco"] is True


@pytest.mark.parametrize(
    "query",
    [
        "3x10",
        "5kg",
        "rpe8",
        "day2",
        "W3",
        "2 sets of 8",
        "80kg x 5",
        "did 3 sets at 5kg around 6am",
        "I did 5kg curls at 6am",
        "2nd set felt heavy, 3rd too",
        "5x5 then 3x8 at 7pm",
        "b2b sessions",
        "The mesh shirt fits well",
        "I gamed the system",
    ],
)
def test_ordinary_english_gym_digits_are_not_franco(query):
    assert graph.is_franco_arabic(query) is False
    assert graph.router_node(_state(query))["intent"] != "clinical_intercept"
