# tests/test_assistant_pipeline.py
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from langchain_core.messages import HumanMessage

from agent.assistant_graph import (
    RE_ACTION_HINT,
    STATIC_SYSTEM_CORE,
    exercise_substitution_node,
    router_node,
    stream_assistant_turn,
)
from utils.logger import MyosLogger
from tests.fakes.chat_model import ScriptedChatModel
from utils.model_downloader import llm

logger = MyosLogger().get_logger(__name__)


def test_phase1_engine_configuration():
    """Validates model parameters and system prompt token budget constraints."""
    logger.info("Verifying Phase 1 Engine Configuration & Directives...")

    assert getattr(llm, "max_tokens", None) == 200, (
        f"Expected llm.max_tokens == 200, found {getattr(llm, 'max_tokens', None)}"
    )

    assert "Output Budget & Structural Constraints:" in STATIC_SYSTEM_CORE
    assert "up to 90 words" in STATIC_SYSTEM_CORE
    assert "brief natural prose for conversation or clarification" in STATIC_SYSTEM_CORE
    logger.info("✅ Phase 1 configuration & prompt budgeting verified.")

def test_phase1_tier1_explicit_swaps():
    """Validates two-way deterministic exercise swaps."""
    queries = [
        ("swap hack squat for leg press", "hack squat", "leg press"),
        ("replace barbell bench press with dumbbell press", "barbell bench press", "dumbbell press"),
        ("substitute pull-ups to lat pulldown", "pull-ups", "lat pulldown"),
        ("switch out seated cable row instead of chest supported row", "seated cable row", "chest supported row"),
    ]

    for q, expected_src, expected_tgt in queries:
        state = {"messages": [HumanMessage(content=q)]}
        res = router_node(state)  # type: ignore

        assert res["intent"] == "exercise_substitution", f"Failed intent for: {q}"
        meta = res["intent_metadata"]
        assert meta["mode"] == "direct_swap"
        assert meta["source_exercise"].lower() == expected_src.lower(), (
            f"Source mismatch on '{q}': got {meta['source_exercise']}"
        )
        assert meta["target_exercise"].lower() == expected_tgt.lower(), (
            f"Target mismatch on '{q}': got {meta['target_exercise']}"
        )

    logger.info("✅ Phase 1 Tier 1: Two-way explicit swaps verified.")


def test_phase1_tier1_single_swaps():
    """Validates one-way candidate lookup swaps."""
    queries = [
        ("swap hack squat", "hack squat"),
        ("alternative for leg extension", "leg extension"),
        ("substitute dips", "dips"),
        ("replace standing calf raise", "standing calf raise"),
    ]

    for q, expected_src in queries:
        state = {"messages": [HumanMessage(content=q)]}
        res = router_node(state)  # type: ignore

        assert res["intent"] == "exercise_substitution", f"Failed intent for: {q}"
        meta = res["intent_metadata"]
        assert meta["mode"] == "lookup_candidates"
        assert meta["source_exercise"].lower() == expected_src.lower()
        assert meta["target_exercise"] is None

    logger.info("✅ Phase 1 Tier 1: One-way swap candidate lookups verified.")


def test_phase1_tier1_program_mutations():
    """Validates split rebuilds and frequency capture."""
    queries = [
        ("rebuild program", None),
        ("switch split to 3 days", 3),
        ("change routine to 5 d/wk", 5),
        ("new split 4 days a week", 4),
    ]

    for q, expected_freq in queries:
        state = {"messages": [HumanMessage(content=q)]}
        res = router_node(state)  # type: ignore

        assert res["intent"] == "program_mutation", f"Failed intent for: {q}"
        assert res["intent_metadata"]["target_frequency"] == expected_freq

    logger.info("✅ Phase 1 Tier 1: Program mutations & frequencies verified.")


def test_deload_choice_routing_is_deterministic_in_english_and_arabic(monkeypatch, scripted_chat_model):
    cases = [
        ("undo the deload", "undo"),
        ("apply the deload", "apply"),
        ("can you undo the deload?", "undo"),
        ("undo deload for today", "undo"),
        ("please undo the deload for my next workout", "undo"),
        ("skip my deload this workout", "undo"),
        ("undo the deload please", "undo"),
        ("please apply the deload", "apply"),
        ("skip the deload next workout", "undo"),
        ("ألغِ التخفيف", "undo"),
        ("طبّق التخفيف", "apply"),
    ]
    monkeypatch.setattr("agent.assistant_graph.llm", scripted_chat_model)
    for query, choice in cases:
        routed = router_node({"messages": [HumanMessage(content=query)]})
        assert routed["intent"] == "deload_choice"
        assert routed["intent_metadata"]["choice"] == choice
    assert scripted_chat_model.calls == []


def test_deload_routing_does_not_override_clinical_or_negated_requests():
    # The clinical guard keeps its own rules; a pain message must never become a Deload command.
    routed = router_node({"messages": [HumanMessage(content="عندي ألم حاد في الركبة، كيف أطبق التخفيف؟")]})
    assert routed["intent"] == "clinical_intercept"
    for query in ("my knee hurts, can I undo the deload?", "my shoulder is injured, apply the deload"):
        routed = router_node({"messages": [HumanMessage(content=query)]})
        assert routed["intent"] != "deload_choice"

    non_commands = [
        "التخفيف من الألم بعد الغداء",
        "هل الديلود ضروري؟ لا تطبق شيء الآن",
        "don't apply the deload",
    ]
    for query in non_commands:
        routed = router_node({"messages": [HumanMessage(content=query)]})
        assert routed["intent"] != "deload_choice"


def test_deload_pipeline_says_nothing_to_change_in_both_wrong_directions(fresh_store):
    from types import SimpleNamespace

    from agent.assistant_graph import stream_assistant_turn

    ledger = fresh_store.ledger
    ledger.get_active_program = MagicMock(
        return_value=SimpleNamespace(days=[SimpleNamespace(day_order=1, exercises=[])])
    )
    cases = [
        ("apply the deload", "applied"),
        ("undo the deload", "suggested"),
    ]
    for query, current_state in cases:
        state = {
            "messages": [HumanMessage(content=query)],
            "trainee_id": "test_user",
            "player_account_id": None,
            "coach_tone": "Direct and pragmatic",
            "custom_instructions": "",
            "telemetry_context": "",
            "intent": None,
            "intent_metadata": {},
            "program_updated": False,
            "response_content": None,
        }
        prescription = {"deload": {"state": current_state}}
        with patch("service.workouts.build_prescription", return_value=prescription):
            rendered = "".join(stream_assistant_turn(state, ledger=ledger, store=fresh_store))
        assert "There is nothing to change." in rendered
        assert state["program_updated"] is False


def test_phase1_tier1_catalog_search():
    """Validates catalog movement searches."""
    queries = [
        ("search incline dumbbell press", "incline dumbbell press"),
        ("find cable chest fly", "cable chest fly"),
        ("lookup seated leg curl", "seated leg curl"),
        ("list exercises lateral raise", "lateral raise"),
    ]

    for q, expected_term in queries:
        state = {"messages": [HumanMessage(content=q)]}
        res = router_node(state)  # type: ignore

        assert res["intent"] == "catalog_search", f"Failed intent for: {q}"
        assert res["intent_metadata"]["search_query"].lower() == expected_term.lower()

    logger.info("✅ Phase 1 Tier 1: Catalog search tokens verified.")


def test_phase1_tier2_coaching_qa_passthrough():
    """Validates that standard coaching queries bypass LLM classification in <0.5ms."""
    queries = [
        "How should I tuck my elbows on the close grip bench press?",
        "What is the best rep range for calf hypertrophy?",
        "My lower back feels fatigued from stiff-legged deadlifts.",
        "Can you explain lengthened-position mechanical tension?",
    ]

    for q in queries:
        assert not RE_ACTION_HINT.search(q), f"Query accidentally triggered action hint: {q}"
        state = {"messages": [HumanMessage(content=q)]}
        res = router_node(state)  # type: ignore

        assert res["intent"] == "coaching_qa", f"Failed pass-through on: {q}"
        assert res["intent_metadata"] == {}

    logger.info("✅ Phase 1 Tier 2: Zero-LLM coaching Q&A pass-through verified.")


def test_phase2_streaming_generator_qa(fresh_store, monkeypatch):
    """Validates token streaming, chunk yielding, and in-place state mutation for Q&A."""
    model = ScriptedChatModel(
        ["Keep your elbows tucked. Use controlled reps."],
        chunk_size=len("Keep your elbows tucked. "),
    )
    state = {
        "messages": [HumanMessage(content="How should I cue the close grip bench press?")],
        "trainee_id": "test_user",
        "coach_tone": "Direct and pragmatic",
        "custom_instructions": "",
        "telemetry_context": "Sample telemetry snapshot",
        "intent": None,
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None,
    }

    monkeypatch.setattr("agent.assistant_graph.llm", model)
    generator = stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store)
    first = next(generator)
    assert first == "Keep your elbows tucked."
    yielded_tokens = [first, *generator]
    assert "".join(yielded_tokens) == "Keep your elbows tucked. Use controlled reps."
    assert len(model.calls) == 1
    assert state["messages"][-1].content == "".join(yielded_tokens)
    assert state["intent"] == "coaching_qa"
    assert state["program_updated"] is False
    assert state["response_content"] == "".join(yielded_tokens)

    logger.info("✅ Phase 2: Conversational token streaming & state updates verified.")


def test_phase2_streaming_generator_programmatic_bypass(fresh_store, monkeypatch, scripted_chat_model):
    """Validates that programmatic nodes stream confirmation without invoking llm.stream()."""
    state = {
        "messages": [HumanMessage(content="switch split to 3 days")],
        "trainee_id": "test_user",
        "coach_tone": "Direct and pragmatic",
        "custom_instructions": "",
        "telemetry_context": "Sample telemetry",
        "intent": None,
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None,
    }

    monkeypatch.setattr("agent.assistant_graph.llm", scripted_chat_model)
    with patch("agent.assistant_graph.program_mutation_node") as mock_mutation:
        mock_mutation.return_value = {"program_updated": True, "response_content": "Rebuilt routine for 3 days/week."}

        generator = stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store)
        output = list(generator)

        assert scripted_chat_model.calls == []
        mock_mutation.assert_called_once()
        assert len(output) > 0
        assert "".join(output) == "Rebuilt routine for 3 days/week."
        assert state["program_updated"] is True

    logger.info("✅ Phase 2: Programmatic zero-LLM streaming bypass verified.")


def test_phase3_substitution_lookup_candidates(fresh_store):
    """Validates that 'lookup_candidates' returns top 3 movements without mutating routine."""
    state = {
        "messages": [HumanMessage(content="alternative for hack squat")],
        "trainee_id": "test_user",
        "coach_tone": "Direct and pragmatic",
        "custom_instructions": "",
        "telemetry_context": "",
        "intent": "exercise_substitution",
        "intent_metadata": {"mode": "lookup_candidates", "source_exercise": "hack squat", "target_exercise": None},
        "program_updated": False,
        "response_content": None,
    }

    mock_ex = MagicMock(exercise_id="ex_123", exercise_name="Hack Squat")
    mock_day = MagicMock(day_name="Lower A", day_order=1, exercises=[mock_ex])
    mock_prog = MagicMock(days=[mock_day])

    mock_cur_instance = MagicMock()
    mock_cur_instance.fetchone.return_value = ("quadriceps", "quadriceps", "machine")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur_instance

    with (
        patch.object(fresh_store.ledger, "get_active_program", return_value=mock_prog),
        patch.object(fresh_store, "catalog_conn", mock_conn),
        patch.object(fresh_store, "search_similar_exercises") as mock_search,
        patch("agent.assistant_graph.substitute_program_exercise") as mock_substitute,
    ):
        mock_search.return_value = [
            {
                "id": "ex_999",
                "name": "Leg Press",
                "target_muscle": "quadriceps",
                "body_part": "quadriceps",
                "equipment": "machine",
            },
            {
                "id": "ex_888",
                "name": "Pendulum Squat",
                "target_muscle": "quadriceps",
                "body_part": "quadriceps",
                "equipment": "machine",
            },
            {
                "id": "ex_777",
                "name": "Front Squat",
                "target_muscle": "quadriceps",
                "body_part": "quadriceps",
                "equipment": "barbell",
            },
        ]

        result = exercise_substitution_node(state, {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}})

        mock_substitute.assert_not_called()
        assert result["program_updated"] is False
        assert "Leg Press" in result["response_content"]
        assert "Pendulum Squat" in result["response_content"]
        assert "Front Squat" in result["response_content"]
        assert "To commit a swap, reply:" in result["response_content"]

    logger.info("✅ Phase 3: Exercise substitution candidate lookups verified.")


def test_phase3_substitution_direct_swap(fresh_store):
    """Validates that a resolved direct swap targets its resolved training day."""
    state = {
        "messages": [HumanMessage(content="swap hack squat for leg press")],
        "trainee_id": "test_user",
        "coach_tone": "Direct and pragmatic",
        "custom_instructions": "",
        "telemetry_context": "",
        "intent": "exercise_substitution",
        "intent_metadata": {"mode": "direct_swap", "source_exercise": "hack squat", "target_exercise": "leg press"},
        "program_updated": False,
        "response_content": None,
    }

    mock_ex = MagicMock(exercise_id="ex_123", exercise_name="Hack Squat")
    mock_day = MagicMock(day_name="Lower A", day_order=1, exercises=[mock_ex])
    mock_prog = MagicMock(days=[mock_day])

    mock_cur_instance = MagicMock()
    mock_cur_instance.fetchone.return_value = ("quadriceps", "quadriceps", "machine")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur_instance

    replacement = {
        "id": "ex_999",
        "name": "Leg Press",
        "target_muscle": "quadriceps",
        "body_part": "quadriceps",
        "equipment": "machine",
        "instructions": "Press through your feet.",
        "image_path": None,
        "gif_path": None,
    }
    with (
        patch.object(fresh_store.ledger, "get_active_program", return_value=mock_prog),
        patch.object(fresh_store, "catalog_conn", mock_conn),
        patch.object(fresh_store, "find_exercises_by_name") as mock_find,
        patch.object(fresh_store, "search_similar_exercises") as mock_search,
        patch("agent.assistant_graph.substitute_program_exercise") as mock_substitute,
    ):
        mock_find.return_value = [
            {
                **replacement,
            }
        ]
        mock_search.return_value = [
            {
                **replacement,
            }
        ]
        mock_substitute.return_value = {
            "ok": True,
            "replacement": replacement,
            "replaced_count": 1,
            "day_names": ["Lower A"],
        }

        result = exercise_substitution_node(state, {"configurable": {"ledger": fresh_store.ledger, "store": fresh_store}})

        mock_substitute.assert_called_once()
        requested = mock_substitute.call_args.args[3]
        assert requested.day_name == "Lower A"
        assert requested.exercise_id == "ex_123"
        assert requested.replacement_exercise_id == "ex_999"

        assert result["program_updated"] is True
        assert "Installed:" in result["response_content"]
        assert "Leg Press" in result["response_content"]

    logger.info("✅ Phase 3: Direct exercise substitution & ledger mutation verified.")


def test_component1_medical_red_flag_interceptor(fresh_store, monkeypatch, scripted_chat_model):
    """Validates that acute trauma / injury phrases trigger immediate zero-LLM intercept."""
    red_flag_queries = [
        "I felt a sharp pop in my shoulder during the top set",
        "My lower back has shooting pain down my left leg",
        "I have severe numbness and tingling in my triceps",
        "I think I tore my pectoral tendon on bench press",
        "My knee has painful swelling and joint clicking with pain",
    ]

    monkeypatch.setattr("agent.assistant_graph.llm", scripted_chat_model)
    for q in red_flag_queries:
        state = {
            "messages": [HumanMessage(content=q)],
            "trainee_id": "test_user",
            "coach_tone": "Direct and pragmatic",
            "custom_instructions": "",
            "telemetry_context": "",
            "intent": None,
            "intent_metadata": {},
            "program_updated": False,
            "response_content": None,
        }

        tokens = list(stream_assistant_turn(state, ledger=fresh_store.ledger, store=fresh_store))
        full_response = "".join(tokens)
        assert "Clinical Safeguard Triggered" in full_response
        assert "Cease training the affected movement immediately" in full_response
        assert state["intent"] == "clinical_intercept"

    assert scripted_chat_model.calls == []

    logger.info("✅ Component 1: Medical red-flag zero-LLM interceptor verified.")


def test_component1_biomechanical_catalog_exclusion(fresh_store):
    """Validates that high-risk movement patterns are filtered out of catalog searches."""
    test_vec = [0.0] * 384

    # Run catalog search
    candidates = fresh_store.search_similar_exercises(test_vec, limit=20)

    for c in candidates:
        name_lower = c["name"].lower()
        assert "behind neck" not in name_lower, f"Found blacklisted exercise: {c['name']}"
        assert "behind the neck" not in name_lower, f"Found blacklisted exercise: {c['name']}"
        assert "upright row" not in name_lower, f"Found blacklisted exercise: {c['name']}"

    logger.info("✅ Component 1: Biomechanical catalog exclusions verified.")


def run_all_tests():
    logger.info("⚡ Running Zero-LLM Fast Routing, UI Token Streaming & Deterministic Exercise Substitution...\n")
    test_phase1_engine_configuration()
    test_phase1_tier1_explicit_swaps()
    test_phase1_tier1_single_swaps()
    test_phase1_tier1_program_mutations()
    test_phase1_tier1_catalog_search()
    test_phase1_tier2_coaching_qa_passthrough()
    test_phase2_streaming_generator_qa()
    test_phase2_streaming_generator_programmatic_bypass()
    test_phase3_substitution_lookup_candidates()
    test_phase3_substitution_direct_swap()
    test_component1_medical_red_flag_interceptor()
    test_component1_biomechanical_catalog_exclusion()
    logger.info(
        "\n🎉 Zero-LLM Fast Routing, UI Token Streaming & Deterministic Exercise Substitution Unit Tests Passed Successfully."
    )


if __name__ == "__main__":
    run_all_tests()
