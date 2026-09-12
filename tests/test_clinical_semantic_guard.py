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
