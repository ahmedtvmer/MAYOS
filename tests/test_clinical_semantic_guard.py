# tests/test_clinical_semantic_guard.py
import pytest
from langchain_core.messages import HumanMessage
from agent.assistant_graph import router_node
from agent.clinical_guard import (
    CLINICAL_ANCHOR_VECTORS,
    EMBED_MODEL,
    cosine_similarity,
)

@pytest.mark.parametrize(
    "query",
    [
        "I felt like velcro was tearing deep inside my pec during the stretch",
        "Every time I lock out my elbows, my outer fingers get pins and needles and feel ice cold",
        "There is a deep hot glass sensation right behind my collarbone at the bottom of the dip",
        "My shoulder feels like the bone is slipping out of its socket when I externally rotate",
        "A dull toothache-type gnawing ache deep inside my hip capsule when squatting",
    ],
)
def test_colloquial_injuries_trigger_semantic_intercept(query: str):
    query_vec = EMBED_MODEL.embed_query(query)
    max_sim = max(cosine_similarity(query_vec, anchor) for anchor in CLINICAL_ANCHOR_VECTORS)

    assert max_sim >= 0.70, f"Query '{query}' scored {max_sim:.3f}, expected >= 0.70"

    state = {
        "messages": [HumanMessage(content=query)],
        "telemetry_context": "",
    }
    result = router_node(state)
    assert result["intent"] == "clinical_intercept", f"Expected clinical_intercept for '{query}', got {result['intent']}"


@pytest.mark.parametrize(
    "query",
    [
        "My quads have an insane metabolic burn during hack squats",
        "How do I maximize the deep stretch on dumbbell Romanian deadlifts?",
        "Should I push my last set of leg extensions to complete mechanical failure?",
        "Can I add a drop set to lateral raises for extra metabolic fatigue?",
    ],
)
def test_safe_biomechanics_do_not_trigger_false_positives(query: str):
    query_vec = EMBED_MODEL.embed_query(query)
    max_sim = max(cosine_similarity(query_vec, anchor) for anchor in CLINICAL_ANCHOR_VECTORS)

    assert max_sim < 0.70, f"Query '{query}' scored {max_sim:.3f}, triggering false positive"

    state = {
        "messages": [HumanMessage(content=query)],
        "telemetry_context": "",
    }
    result = router_node(state)
    assert result["intent"] != "clinical_intercept", f"False positive clinical intercept for '{query}'"


from agent.clinical_guard import evaluate_clinical_semantic_guard


@pytest.mark.parametrize(
    "query",
    [
        "malak",
        "hey",
        "asdasd",
        "hello there",
        "yo",
        "sup",
    ],
)
def test_short_unknown_inputs_bypass_clinical_guard(query: str):
    is_clinical, score = evaluate_clinical_semantic_guard(query)
    assert not is_clinical, f"Short input '{query}' falsely triggered clinical guard (score={score:.3f})"
    assert score == 0.0, f"Expected score 0.0 for pre-filtered '{query}', got {score:.3f}"


def test_short_injury_token_still_triggers():
    is_clinical, score = evaluate_clinical_semantic_guard("sharp pain")
    assert score > 0.0, "Short query with injury token should still run embedding check"


@pytest.mark.parametrize(
    "query",
    [
        "My rolling readiness is 1/5 and every joint feels cold and sluggish. Should I still push to an RPE 10 top set today?",
        "I'm feeling sluggish and low readiness today, should I still train?",
        "Systemic fatigue is high and my whole body feels drained",
    ],
)
def test_benign_systemic_fatigue_bypasses_clinical_guard(query: str):
    is_clinical, score = evaluate_clinical_semantic_guard(query)
    assert not is_clinical, f"Benign fatigue '{query}' falsely triggered clinical guard (score={score:.3f})"
    assert score == 0.0


@pytest.mark.parametrize(
    "query",
    [
        "I'm fatigued and my shoulder has sharp pain",
        "My legs are tired but my fingers are numb and tingling",
        "I feel drained and have radiating pain down my arm",
        "Systemic fatigue but my knee popped and is swollen",
    ],
)
def test_fatigue_with_acute_signals_stays_fail_closed(query: str):
    is_clinical, score = evaluate_clinical_semantic_guard(query)
    assert is_clinical, f"Acute signal in '{query}' must stay clinical (score={score:.3f})"
    result = router_node({"messages": [HumanMessage(content=query)], "telemetry_context": ""})
    assert result["intent"] == "clinical_intercept"

