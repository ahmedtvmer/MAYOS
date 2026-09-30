"""Tier-0 trauma and intensified movement-pain gating while DOMS slang passes.

Unconditional Tier-0a signals (sharp pain, numbness, dislocation...) remain
fail-closed. DOMS-ambiguous tokens (swelling/tear/tore/torn/pop/tweaked) only
intercept with explicit injury context (mechanism perception, anatomical
proximity, or body-part objects), while intensified joint pain during movement
also intercepts; benign fatigue and unrelated intensity wording pass.
"""

import pytest
from langchain_core.messages import HumanMessage

from agent import assistant_graph as graph

INTENSIFIED_MOVEMENT_PAIN = [
    "I get strong shoulder pain when I raise my arm overhead.",
    "My knee hurts really bad when I squat.",
    "I have a lot of pain in my elbow when I press.",
    "Severe hip pain when I bend down.",
    "Bad wrist pain during push-ups.",
    "My back hurts a lot when I lift.",
    "my lower back pain is really bad when I deadlift",
    "not sure why, but my knee hurts a lot when I squat",
    "no idea, my knee hurts really bad when I lunge",
    "it's not the weight, my wrist hurts a lot when I press",
    "my elbow is really painful when I curl",
    "my back hurts. Really bad when I lift",
]

MUST_INTERCEPT = [
    "I felt a sharp pop in my shoulder",
    "My pec is swollen and tore on bench",
    "I think I tore my pectoral tendon on bench press",
    "My knee has painful swelling and joint clicking with pain",
    "i felt a pop in my knee during squats",
    "my shoulder is swollen and tender",
    "swollen ankle, should i skip training?",
    "i tweaked my back deadlifting",
    "there was a tearing sensation in my groin",
    "my elbow popped and it hurts",
] + INTENSIFIED_MOVEMENT_PAIN

BENIGN_TIER0_PHRASES = [
    "my quads are swollen and torn up from leg day",
    "chest feels torn to shreds after that bench session",
    "hamstrings are swollen from the good mornings",
    "i tweaked my program to add more volume",
    "glutes are torn up from hip thrusts",
    "my knees pop when i squat, is that normal?",
    "my shoulders are sore from yesterday's press",
    "I feel strong after my workout",
    "my shoulder feels strong now",
    "I have bad shoulder pain, but overhead presses feel fine.",
    "does bad form cause knee pain when squatting?",
    "bad form on squat, my back hurts",
    "is it bad if my hips ache a bit when squatting?",
    "really, does my knee hurting when squatting mean anything?",
    "lifting is really helping my back pain",
    "pressing helps my shoulder pain a lot",
    "my shoulder pain is a lot better when I press",
    "shoulder pain isn't bad when I press anymore",
    "I used to have bad knee pain when squatting, it's gone now",
    "my knee doesn't hurt a lot when I squat",
    "how bad is back pain when lifting generally?",
    "my back hurts a lot on pull day? no, I mean my lats are sore",
]


@pytest.mark.parametrize("query", MUST_INTERCEPT)
def test_injury_context_phrases_hit_tier0(query):
    assert graph._acute_injury_hit(query) is True


@pytest.mark.parametrize("query", INTENSIFIED_MOVEMENT_PAIN)
def test_intensified_joint_pain_during_movement_routes_to_clinical_intercept(query, monkeypatch):
    monkeypatch.setattr(graph, "evaluate_clinical_semantic_guard", lambda text, **kwargs: (False, 0.0))
    assert graph.router_node(_state(query))["intent"] == "clinical_intercept"


@pytest.mark.parametrize("query", BENIGN_TIER0_PHRASES)
def test_benign_phrases_do_not_route_to_tier0_intercept(query, monkeypatch):
    monkeypatch.setattr(graph, "evaluate_clinical_semantic_guard", lambda text, **kwargs: (False, 0.0))
    assert graph.router_node(_state(query))["intent"] != "clinical_intercept"


def test_doms_soreness_after_press_reaches_coaching_qa(monkeypatch):
    monkeypatch.setattr(graph, "evaluate_clinical_semantic_guard", lambda text, **kwargs: (False, 0.0))
    query = "my shoulders are sore from yesterday's press"
    assert graph.router_node(_state(query))["intent"] == "coaching_qa"


@pytest.mark.parametrize("query", BENIGN_TIER0_PHRASES)
def test_fatigue_slang_passes_tier0(query):
    assert graph._acute_injury_hit(query) is False


def _state(query: str) -> dict:
    return {"messages": [HumanMessage(content=query)], "telemetry_context": "", "intent_metadata": {}}


def test_router_routes_doms_slang_to_coaching_qa(monkeypatch):
    # Isolate Tier-0 gating; the Tier-1 semantic layer is a separate safety net.
    monkeypatch.setattr(graph, "evaluate_clinical_semantic_guard", lambda text, **kwargs: (False, 0.0))
    assert graph.router_node(_state("my quads are swollen and torn up from leg day"))["intent"] != "clinical_intercept"


def test_router_intercepts_mechanism_pop(monkeypatch):
    monkeypatch.setattr(graph, "evaluate_clinical_semantic_guard", lambda text, **kwargs: (False, 0.0))
    assert graph.router_node(_state("i felt a pop in my knee during squats"))["intent"] == "clinical_intercept"


def test_clean_phrase_still_reaches_coaching_qa(monkeypatch):
    monkeypatch.setattr(graph, "evaluate_clinical_semantic_guard", lambda text, **kwargs: (False, 0.0))
    assert graph.router_node(_state("how do i perform rdl?"))["intent"] == "coaching_qa"
