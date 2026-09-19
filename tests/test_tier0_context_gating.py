"""Tier-0 context gating: DOMS slang passes; injury-context trauma still intercepts.

Unconditional Tier-0a signals (sharp pain, numbness, dislocation...) remain
fail-closed. DOMS-ambiguous tokens (swelling/tear/tore/torn/pop/tweaked) only
intercept with explicit injury context (mechanism perception, anatomical
proximity, or body-part objects) and otherwise reach the Tier-1 semantic guard.
"""

import pytest
from langchain_core.messages import HumanMessage

from agent import assistant_graph as graph

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
]

MUST_PASS_TIER0 = [
    "my quads are swollen and torn up from leg day",
    "chest feels torn to shreds after that bench session",
    "hamstrings are swollen from the good mornings",
    "i tweaked my program to add more volume",
    "glutes are torn up from hip thrusts",
    "my knees pop when i squat, is that normal?",
]


@pytest.mark.parametrize("query", MUST_INTERCEPT)
def test_injury_context_phrases_hit_tier0(query):
    assert graph._acute_injury_hit(query) is True


@pytest.mark.parametrize("query", MUST_PASS_TIER0)
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
