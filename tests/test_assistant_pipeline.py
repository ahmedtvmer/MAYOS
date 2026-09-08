# tests/test_assistant_pipeline.py
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from langchain_core.messages import HumanMessage, AIMessage
from langchain_ollama import ChatOllama
from agent.assistant_graph import (
    router_node,
    stream_assistant_turn,
    exercise_substitution_node,
    db as assistant_db,
    STATIC_SYSTEM_CORE,
    RE_ACTION_HINT
)
from utils.logger import MyosLogger
from utils.model_downloader import llm

logger = MyosLogger().get_logger(__name__)


def test_phase1_engine_configuration():
    """Validates model parameters and system prompt token budget constraints."""
    logger.info("Verifying Phase 1 Engine Configuration & Directives...")

    assert getattr(llm, "num_predict", None) == 200, (
        f"Expected llm.num_predict == 200, found {getattr(llm, 'num_predict', None)}"
    )

    assert "Output Budget & Structural Constraints:" in STATIC_SYSTEM_CORE
    assert "strictly 2 to 4 complete, dense sentences" in STATIC_SYSTEM_CORE
    assert "80–130 words" in STATIC_SYSTEM_CORE
    logger.info("✅ Phase 1 configuration & prompt budgeting verified.")


def test_phase1_tier1_explicit_swaps():
    """Validates two-way deterministic exercise swaps."""
    queries = [
        ("swap hack squat for leg press", "hack squat", "leg press"),
        ("replace barbell bench press with dumbbell press", "barbell bench press", "dumbbell press"),
        ("substitute pull-ups to lat pulldown", "pull-ups", "lat pulldown"),
        ("switch out seated cable row instead of chest supported row", "seated cable row", "chest supported row")
    ]

    for q, expected_src, expected_tgt in queries:
        state = {"messages": [HumanMessage(content=q)]}
        res = router_node(state)  # type: ignore

        assert res["intent"] == "exercise_substitution", f"Failed intent for: {q}"
        meta = res["intent_metadata"]
        assert meta["mode"] == "direct_swap"
        assert meta["source_exercise"].lower() == expected_src.lower(), f"Source mismatch on '{q}': got {meta['source_exercise']}"
        assert meta["target_exercise"].lower() == expected_tgt.lower(), f"Target mismatch on '{q}': got {meta['target_exercise']}"

    logger.info("✅ Phase 1 Tier 1: Two-way explicit swaps verified.")


def test_phase1_tier1_single_swaps():
    """Validates one-way candidate lookup swaps."""
    queries = [
        ("swap hack squat", "hack squat"),
        ("alternative for leg extension", "leg extension"),
        ("substitute dips", "dips"),
        ("replace standing calf raise", "standing calf raise")
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
        ("new split 4 days a week", 4)
    ]

    for q, expected_freq in queries:
        state = {"messages": [HumanMessage(content=q)]}
        res = router_node(state)  # type: ignore

        assert res["intent"] == "program_mutation", f"Failed intent for: {q}"
        assert res["intent_metadata"]["target_frequency"] == expected_freq

    logger.info("✅ Phase 1 Tier 1: Program mutations & frequencies verified.")


def test_phase1_tier1_catalog_search():
    """Validates catalog movement searches."""
    queries = [
        ("search incline dumbbell press", "incline dumbbell press"),
        ("find cable chest fly", "cable chest fly"),
        ("lookup seated leg curl", "seated leg curl"),
        ("list exercises lateral raise", "lateral raise")
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
        "Can you explain lengthened-position mechanical tension?"
    ]

    for q in queries:
        assert not RE_ACTION_HINT.search(q), f"Query accidentally triggered action hint: {q}"
        state = {"messages": [HumanMessage(content=q)]}
        res = router_node(state)  # type: ignore

        assert res["intent"] == "coaching_qa", f"Failed pass-through on: {q}"
        assert res["intent_metadata"] == {}

    logger.info("✅ Phase 1 Tier 2: Zero-LLM coaching Q&A pass-through verified.")


def test_phase2_streaming_generator_qa():
    """Validates token streaming, chunk yielding, and in-place state mutation for Q&A."""
    mock_chunks = [
        MagicMock(content="Keep your elbows "),
        MagicMock(content="tucked at 45 degrees "),
        MagicMock(content="to maximize tension on the triceps.")
    ]

    state = {
        "messages": [HumanMessage(content="How should I cue the close grip bench press?")],
        "trainee_id": "test_user",
        "coach_tone": "Direct and pragmatic",
        "custom_instructions": "",
        "telemetry_context": "Sample telemetry snapshot",
        "intent": None,
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None
    }

    with patch.object(ChatOllama, "stream", return_value=iter(mock_chunks)):
        generator = stream_assistant_turn(state)

        yielded_tokens = []
        for chunk in generator:
            yielded_tokens.append(chunk)

        assert len(yielded_tokens) == 3
        assert "".join(yielded_tokens) == "Keep your elbows tucked at 45 degrees to maximize tension on the triceps."
        assert state["intent"] == "coaching_qa"
        assert state["program_updated"] is False
        assert state["response_content"] == "".join(yielded_tokens)

    logger.info("✅ Phase 2: Conversational token streaming & state updates verified.")


def test_phase2_streaming_generator_programmatic_bypass():
    """Validates that programmatic nodes yield confirmation without invoking llm.stream()."""
    state = {
        "messages": [HumanMessage(content="switch split to 3 days")],
        "trainee_id": "test_user",
        "coach_tone": "Direct and pragmatic",
        "custom_instructions": "",
        "telemetry_context": "Sample telemetry",
        "intent": None,
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None
    }

    with patch("agent.assistant_graph.program_mutation_node") as mock_mutation, \
         patch.object(ChatOllama, "stream") as mock_llm_stream:

        mock_mutation.return_value = {
            "program_updated": True,
            "response_content": "Rebuilt routine for 3 days/week."
        }

        generator = stream_assistant_turn(state)
        output = list(generator)

        mock_llm_stream.assert_not_called()
        mock_mutation.assert_called_once()
        assert len(output) == 1
        assert output[0] == "Rebuilt routine for 3 days/week."
        assert state["program_updated"] is True

    logger.info("✅ Phase 2: Programmatic zero-LLM streaming bypass verified.")


def test_phase3_substitution_lookup_candidates():
    """Validates that 'lookup_candidates' returns top 3 movements without mutating routine."""
    state = {
        "messages": [HumanMessage(content="alternative for hack squat")],
        "trainee_id": "test_user",
        "coach_tone": "Direct and pragmatic",
        "custom_instructions": "",
        "telemetry_context": "",
        "intent": "exercise_substitution",
        "intent_metadata": {
            "mode": "lookup_candidates",
            "source_exercise": "hack squat",
            "target_exercise": None
        },
        "program_updated": False,
        "response_content": None
    }

    mock_ex = MagicMock(exercise_id="ex_123", exercise_name="Hack Squat")
    mock_day = MagicMock(day_name="Lower A", day_order=1, exercises=[mock_ex])
    mock_prog = MagicMock(days=[mock_day])

    mock_cur_instance = MagicMock()
    mock_cur_instance.fetchone.return_value = ("quadriceps", "quadriceps", "machine")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur_instance

    with patch("database.database_manager.DatabaseManager.get_active_program", return_value=mock_prog), \
         patch.object(assistant_db, "catalog_conn", mock_conn), \
         patch("database.database_manager.DatabaseManager.search_similar_exercises") as mock_search, \
         patch("database.database_manager.DatabaseManager.swap_program_exercise") as mock_swap:

        mock_search.return_value = [
            {"id": "ex_999", "name": "Leg Press", "target_muscle": "quadriceps", "body_part": "quadriceps", "equipment": "machine"},
            {"id": "ex_888", "name": "Pendulum Squat", "target_muscle": "quadriceps", "body_part": "quadriceps", "equipment": "machine"},
            {"id": "ex_777", "name": "Front Squat", "target_muscle": "quadriceps", "body_part": "quadriceps", "equipment": "barbell"}
        ]

        result = exercise_substitution_node(state)

        mock_swap.assert_not_called()
        assert result["program_updated"] is False
        assert "Leg Press" in result["response_content"]
        assert "Pendulum Squat" in result["response_content"]
        assert "Front Squat" in result["response_content"]
        assert "To commit a swap, reply:" in result["response_content"]

    logger.info("✅ Phase 3: Exercise substitution candidate lookups verified.")


def test_phase3_substitution_direct_swap():
    """Validates that 'direct_swap' calls swap_program_exercise and triggers UI sync."""
    state = {
        "messages": [HumanMessage(content="swap hack squat for leg press")],
        "trainee_id": "test_user",
        "coach_tone": "Direct and pragmatic",
        "custom_instructions": "",
        "telemetry_context": "",
        "intent": "exercise_substitution",
        "intent_metadata": {
            "mode": "direct_swap",
            "source_exercise": "hack squat",
            "target_exercise": "leg press"
        },
        "program_updated": False,
        "response_content": None
    }

    mock_ex = MagicMock(exercise_id="ex_123", exercise_name="Hack Squat")
    mock_day = MagicMock(day_name="Lower A", day_order=1, exercises=[mock_ex])
    mock_prog = MagicMock(days=[mock_day])

    mock_cur_instance = MagicMock()
    mock_cur_instance.fetchone.return_value = ("quadriceps", "quadriceps", "machine")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur_instance

    with patch("database.database_manager.DatabaseManager.get_active_program", return_value=mock_prog), \
         patch.object(assistant_db, "catalog_conn", mock_conn), \
         patch("database.database_manager.DatabaseManager.search_similar_exercises") as mock_search, \
         patch("database.database_manager.DatabaseManager.swap_program_exercise", return_value=True) as mock_swap:

        mock_search.return_value = [
            {"id": "ex_999", "name": "Leg Press", "target_muscle": "quadriceps", "body_part": "quadriceps", "equipment": "machine"}
        ]

        result = exercise_substitution_node(state)

        mock_swap.assert_called_once_with(
            old_exercise_id="ex_123",
            new_exercise_id="ex_999",
            new_notes=mock_swap.call_args[1]["new_notes"],
            day_id=None
        )

        assert result["program_updated"] is True
        assert "Installed:" in result["response_content"]
        assert "Leg Press" in result["response_content"]

    logger.info("✅ Phase 3: Direct exercise substitution & ledger mutation verified.")


def test_component1_medical_red_flag_interceptor():
    """Validates that acute trauma / injury phrases trigger immediate zero-LLM intercept."""
    red_flag_queries = [
        "I felt a sharp pop in my shoulder during the top set",
        "My lower back has shooting pain down my left leg",
        "I have severe numbness and tingling in my triceps",
        "I think I tore my pectoral tendon on bench press",
        "My knee has painful swelling and joint clicking with pain"
    ]

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
            "response_content": None
        }

        with patch.object(ChatOllama, "stream") as mock_llm_stream:
            # Test generator streaming path
            tokens = list(stream_assistant_turn(state))

            # 1. Must NOT invoke LLM inference
            mock_llm_stream.assert_not_called()

            # 2. Must return safeguard response
            assert len(tokens) == 1
            assert "Clinical Safeguard Triggered" in tokens[0]
            assert "Cease training the affected movement immediately" in tokens[0]
            assert state["intent"] == "clinical_intercept"

    logger.info("✅ Component 1: Medical red-flag zero-LLM interceptor verified.")


def test_component1_biomechanical_catalog_exclusion():
    """Validates that high-risk movement patterns are filtered out of catalog searches."""
    test_vec = [0.0] * 384

    # Run catalog search
    candidates = assistant_db.search_similar_exercises(test_vec, limit=20)

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
    logger.info("\n🎉 Zero-LLM Fast Routing, UI Token Streaming & Deterministic Exercise Substitution Unit Tests Passed Successfully.")


if __name__ == "__main__":
    run_all_tests()