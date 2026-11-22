# tests/test_clinical_semantic_guard.py
import pytest
from langchain_core.messages import HumanMessage
from agent import clinical_guard
from agent.assistant_graph import router_node
from agent.clinical_guard import (
    CLINICAL_ANCHOR_VECTORS,
    EMBED_MODEL,
    cosine_similarity,
    evaluate_clinical_semantic_guard,
)


class FixedEmbedder:
    def __init__(self, vector):
        self.vector = vector

    def embed_query(self, _text):
        return self.vector


def _force_clinical_similarity(monkeypatch, *, arabic):
    # Since #754 the Arabic path is deterministic; a code-switched message
    # with no Arabic clinical wording falls through to the English similarity
    # tier, so forcing that tier covers both languages.
    del arabic
    monkeypatch.setattr(
        clinical_guard,
        "EMBED_MODEL",
        FixedEmbedder(clinical_guard.CLINICAL_ANCHOR_VECTORS[0]),
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


@pytest.mark.parametrize(
    ("query", "arabic_embedding", "expected_intent"),
    [
        (
            "swap Preacher Curl (Barbell) for Incline Curl (Dumbbell)",
            False,
            "exercise_substitution",
        ),
        (
            "بدل Preacher Curl (Barbell) بـ Incline Curl (Dumbbell)",
            True,
            "arabic_swap_clarification",
        ),
        (
            "3ayez abadel Preacher Curl (Barbell) bel Incline Curl (Dumbbell)",
            False,
            "exercise_substitution",
        ),
    ],
)
def test_issue_738_validated_catalog_swaps_bypass_false_positive_semantic_match(
    query, arabic_embedding, expected_intent, fresh_store, monkeypatch
):
    _force_clinical_similarity(monkeypatch, arabic=arabic_embedding)

    assert clinical_guard.evaluate_clinical_semantic_guard(query)[0] is True

    result = router_node(
        {"messages": [HumanMessage(content=query)], "telemetry_context": ""},
        {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}},
    )

    assert result["intent"] == expected_intent


@pytest.mark.parametrize(
    ("query", "arabic_embedding"),
    [
        ("swap Preacher Curl (Barbell) for Not A Catalog Exercise", False),
        ("swap Not A Catalog Exercise for Incline Curl (Dumbbell)", False),
        (
            "swap Preacher Curl (Barbell) for Incline Curl (Dumbbell) because my knee is killing me",
            False,
        ),
        (
            "بدل Preacher Curl (Barbell) بـ Incline Curl (Dumbbell) بس my knee is killing me",
            True,
        ),
        (
            "3ayez abadel Preacher Curl (Barbell) bel Incline Curl (Dumbbell) because my knee is killing me",
            False,
        ),
    ],
)
def test_issue_738_unvalidated_swap_still_runs_semantic_guard(
    query, arabic_embedding, fresh_store, monkeypatch
):
    _force_clinical_similarity(monkeypatch, arabic=arabic_embedding)

    result = router_node(
        {"messages": [HumanMessage(content=query)], "telemetry_context": ""},
        {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}},
    )

    assert result["intent"] == "clinical_intercept"


def test_issue_738_composite_message_cannot_exempt_its_named_swap_clause(
    fresh_store, monkeypatch
):
    class ClauseSensitiveEmbedder:
        def embed_query(self, text):
            return [1.0, 0.0] if "and also" not in text.casefold() else [0.0, 1.0]

    monkeypatch.setattr(clinical_guard, "EMBED_MODEL", ClauseSensitiveEmbedder())
    monkeypatch.setattr(clinical_guard, "CLINICAL_ANCHOR_VECTORS", [[1.0, 0.0]])
    result = router_node(
        {
            "messages": [
                HumanMessage(
                    content=(
                        "swap Preacher Curl (Barbell) for Incline Curl (Dumbbell) "
                        "and also what rep range should I use?"
                    )
                )
            ],
            "telemetry_context": "",
        },
        {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}},
    )

    assert result["intent"] == "clinical_intercept"


@pytest.mark.parametrize("query", ["ache", "aches", "aching", "headache", "backache"])
def test_issue_738_ache_inflections_remain_clinical_signals(query):
    assert clinical_guard.has_deterministic_clinical_signal(query)


@pytest.mark.parametrize(
    "query",
    [
        "Preacher Curl (Barbell)",
        "بدل Preacher Curl (Barbell) بـ Incline Curl (Dumbbell)",
        "3ayez abadel Preacher Curl (Barbell) bel Incline Curl (Dumbbell)",
    ],
)
def test_issue_738_preacher_name_is_not_an_ache_signal(query):
    assert not clinical_guard.has_deterministic_clinical_signal(query)


@pytest.mark.parametrize(
    "query",
    ["بache", "بheadache", "وجعpain", "painوجع", "ظهرbackache", "backacheوجع"],
)
def test_issue_738_arabic_and_latin_glued_symptoms_still_match(query):
    assert clinical_guard.has_deterministic_clinical_signal(query)


@pytest.mark.parametrize(
    "query",
    [
        "ركبتي hurtsجامد", "ركبتي hurtingجامد", "ركبتي painfulجامد",
        "ركبتي achesجامد", "ركبتي achingجامد",
    ],
)
def test_issue_738_glued_symptom_inflections_intercept_below_semantic_threshold(
    query, fresh_store, monkeypatch
):
    assert clinical_guard.has_deterministic_clinical_signal(query)
    result = router_node(
        {"messages": [HumanMessage(content=query)], "telemetry_context": ""},
        {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}},
    )

    assert result["intent"] == "clinical_intercept"


@pytest.mark.parametrize(
    "target",
    [
        "alternative", "an alternative", "what", "eh", "eih", "eh tani",
        "something better", "a better one",
    ],
)
def test_issue_738_english_non_exercise_swap_target_is_an_advice_request(
    target, fresh_store, monkeypatch
):
    monkeypatch.setattr(clinical_guard, "EMBED_MODEL", FixedEmbedder([1.0, 0.0]))
    monkeypatch.setattr(clinical_guard, "CLINICAL_ANCHOR_VECTORS", [[0.0, 1.0]])
    result = router_node(
        {
            "messages": [
                HumanMessage(content=f"swap Preacher Curl (Barbell) for {target}")
            ],
            "telemetry_context": "",
        },
        {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}},
    )

    assert result["intent"] == "coaching_qa"
    assert result["intent_metadata"]["advice_request"] is True


@pytest.mark.parametrize(
    "target",
    [
        "alternative", "an alternative", "eh", "what", "eih", "eh tani",
        "something better", "a better one",
    ],
)
def test_issue_738_franco_placeholder_target_routes_to_advice_request(
    target, fresh_store, monkeypatch
):
    monkeypatch.setattr(clinical_guard, "EMBED_MODEL", FixedEmbedder([1.0, 0.0]))
    monkeypatch.setattr(clinical_guard, "CLINICAL_ANCHOR_VECTORS", [[0.0, 1.0]])
    result = router_node(
        {
            "messages": [
                HumanMessage(content=f"3ayez abadel Preacher Curl (Barbell) bel {target}")
            ],
            "telemetry_context": "",
        },
        {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}},
    )

    assert result["intent"] == "coaching_qa"
    assert result["intent_metadata"]["advice_request"] is True


def test_issue_738_whole_word_catalog_target_keeps_a_direct_swap(
    fresh_store, monkeypatch
):
    assert fresh_store.find_unique_exercise_id_by_exact_name("Incline Curl") is None
    monkeypatch.setattr(clinical_guard, "EMBED_MODEL", FixedEmbedder([1.0, 0.0]))
    monkeypatch.setattr(clinical_guard, "CLINICAL_ANCHOR_VECTORS", [[0.0, 1.0]])

    result = router_node(
        {
            "messages": [
                HumanMessage(content="swap Preacher Curl (Barbell) for Incline Curl")
            ],
            "telemetry_context": "",
        },
        {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}},
    )

    assert result["intent"] == "exercise_substitution"
    assert result["intent_metadata"]["mode"] == "direct_swap"


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

