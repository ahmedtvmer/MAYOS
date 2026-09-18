# tests/test_fitness_abbreviations.py
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage

from agent.fitness_abbreviations import (
    expand_fitness_abbreviations,
    resolve_unknown_abbreviation_with_llm,
    AbbreviationExpansion,
)
from agent.assistant_graph import (
    AssistantState,
    exercise_substitution_node,
    router_node,
)
from database.database_manager import DatabaseManager


def test_expand_fitness_abbreviations_lexicon():
    """Verifies that common gym acronyms and equipment shorthand expand to full movement names."""
    test_cases = [
        ("swap machine seated good morning for RDLs", "swap machine seated good morning for romanian deadlift"),
        ("replace bench press with OHP", "replace bench press with overhead press"),
        ("switch out squats for BSS", "switch out squats for single leg split squat"),
        ("do SLDLs instead of deadlifts", "do stiff leg deadlift instead of deadlift"),
        ("replace triceps press with CGBP", "replace triceps press with close grip bench press"),
        ("can i do skull crushers", "can i do lying triceps extension skull crusher"),
        ("use DB instead of BB", "use dumbbell instead of barbell"),
        ("do EZ bar curls", "do ez bar curls"),
        ("try GHR for hamstrings", "try glute ham raise for hamstrings"),
        ("swap for JM press", "swap for barbell jm press"),
    ]
    for text, expected in test_cases:
        assert expand_fitness_abbreviations(text).lower() == expected.lower()


def test_expand_fitness_abbreviations_word_boundaries():
    """Verifies that substrings inside regular words are not falsely replaced."""
    text = "The middle treadmill was occupied by a runner with good form"
    expanded = expand_fitness_abbreviations(text)
    assert expanded == text


def test_resolve_unknown_abbreviation_with_llm_validation():
    """Verifies that non-acronyms are rejected without invoking LLM."""
    assert resolve_unknown_abbreviation_with_llm("") is None
    assert resolve_unknown_abbreviation_with_llm("a") is None
    assert resolve_unknown_abbreviation_with_llm("thisisaverylongwordthatisnotanacronym") is None
    assert resolve_unknown_abbreviation_with_llm("word with spaces") is None
    assert resolve_unknown_abbreviation_with_llm("1234") is None


def test_resolve_unknown_abbreviation_with_llm_mock():
    """Verifies structured LLM resolution with positive and negative outputs."""
    with patch("agent.fitness_abbreviations.llm") as mock_llm:
        mock_structured = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured

        # Case 1: Valid fitness acronym
        mock_structured.invoke.return_value = AbbreviationExpansion(
            is_fitness_movement=True,
            canonical_name="Romanian Deadlift",
        )
        res = resolve_unknown_abbreviation_with_llm("RDL")
        assert res == "romanian deadlift"

        # Case 2: Gibberish / non-fitness acronym
        mock_structured.invoke.return_value = AbbreviationExpansion(
            is_fitness_movement=False,
            canonical_name=None,
        )
        res_gibberish = resolve_unknown_abbreviation_with_llm("XYZ")
        assert res_gibberish is None

        # Case 3: LLM error gracefully handled
        mock_structured.invoke.side_effect = RuntimeError("Model timeout")
        res_error = resolve_unknown_abbreviation_with_llm("ABC")
        assert res_error is None


@pytest.fixture(scope="module")
def db_with_good_morning():
    """Sets up a test program in DatabaseManager with Machine Seated Good Morning."""
    db = DatabaseManager()
    profile = {
        "gender": "male",
        "proportions": "balanced",
        "experience": "intermediate",
        "equipment": "commercial_gym",
        "target_frequency": 4,
        "primary_goal": "hypertrophy",
        "coach_tone": "Direct, grounded, and pragmatic",
    }
    db.upsert_user_profile(profile)

    # Generate a baseline 4-day split
    from agent.program_generator import generate_program_pipeline
    generate_program_pipeline(user_split_override=None, frequency_override=4)

    # Ensure Day 2 (Lower) or Day 1 has machine seated good morning (ID 3759)
    active = db.get_active_program()
    assert active is not None

    # Replace the first exercise of Day 1 with Machine Seated Good Morning for reliable testing
    target_day = active.days[0]
    target_ex = target_day.exercises[0]

    db.swap_program_exercise(
        old_exercise_id=target_ex.exercise_id,
        new_exercise_id="3759",  # machine seated good morning (glutes / upper legs)
        new_notes="Hinge at the hips with neutral spine",
    )
    return db


def test_substitution_rdls_confident_install(db_with_good_morning):
    """Verifies that 'swap machine seated good morning for RDLs' confidently installs Barbell Romanian Deadlift."""
    state: AssistantState = {
        "messages": [HumanMessage(content="swap machine seated good morning for RDLs")],
        "trainee_id": "default",
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": None,
        "intent": "exercise_substitution",
        "intent_metadata": {
            "mode": "direct_swap",
            "source_exercise": "machine seated good morning",
            "target_exercise": "RDLs",
        },
        "active_intents": None,
        "program_updated": False,
        "response_content": None,
    }

    res = exercise_substitution_node(state)
    assert res["program_updated"] is True, f"Failed swap: {res.get('response_content')}"
    assert "barbell romanian deadlift" in res["response_content"].lower()
    assert "low glute bridge" not in res["response_content"].lower()

    # Check database program slot
    active_after = db_with_good_morning.get_active_program()
    first_ex = active_after.days[0].exercises[0]
    assert first_ex.exercise_name.lower() == "barbell romanian deadlift"


def test_substitution_db_rdl_explicit_variant(db_with_good_morning):
    """Verifies that 'swap barbell romanian deadlift for dumbbell RDL' installs Dumbbell Romanian Deadlift."""
    state: AssistantState = {
        "messages": [HumanMessage(content="swap barbell romanian deadlift for dumbbell RDL")],
        "trainee_id": "default",
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": None,
        "intent": "exercise_substitution",
        "intent_metadata": {
            "mode": "direct_swap",
            "source_exercise": "barbell romanian deadlift",
            "target_exercise": "dumbbell RDL",
        },
        "active_intents": None,
        "program_updated": False,
        "response_content": None,
    }

    res = exercise_substitution_node(state)
    assert res["program_updated"] is True, f"Failed swap: {res.get('response_content')}"
    assert "dumbbell romanian deadlift" in res["response_content"].lower()

    # Check database program slot
    active_after = db_with_good_morning.get_active_program()
    first_ex = active_after.days[0].exercises[0]
    assert first_ex.exercise_name.lower() == "dumbbell romanian deadlift"


def test_substitution_unknown_abbreviation_asks_illustration(db_with_good_morning):
    """Verifies that an unknown abbreviation prompts for further illustration without modifying the ledger."""
    state: AssistantState = {
        "messages": [HumanMessage(content="swap dumbbell romanian deadlift for XYZ")],
        "trainee_id": "default",
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": None,
        "intent": "exercise_substitution",
        "intent_metadata": {
            "mode": "direct_swap",
            "source_exercise": "dumbbell romanian deadlift",
            "target_exercise": "XYZ",
        },
        "active_intents": None,
        "program_updated": False,
        "response_content": None,
    }

    res = exercise_substitution_node(state)
    assert res["program_updated"] is False
    assert "could you provide further illustration" in res["response_content"].lower()
    assert "did you mean one of these alternatives?" in res["response_content"].lower()

    # Verify the database was NOT mutated
    active_after = db_with_good_morning.get_active_program()
    first_ex = active_after.days[0].exercises[0]
    assert first_ex.exercise_name.lower() == "dumbbell romanian deadlift"


def test_end_to_end_router_with_abbreviation(db_with_good_morning):
    """Verifies that the router parses abbreviation query and routes to substitution correctly."""
    query = "swap dumbbell romanian deadlift for OHP"
    state: AssistantState = {
        "messages": [HumanMessage(content=query)],
        "trainee_id": "default",
        "coach_tone": "Direct",
        "custom_instructions": "",
        "telemetry_context": None,
        "intent": None,
        "intent_metadata": {},
        "active_intents": None,
        "program_updated": False,
        "response_content": None,
    }

    routed = router_node(state)
    assert routed.get("intent") == "exercise_substitution"
    assert routed["intent_metadata"]["source_exercise"].lower() == "dumbbell romanian deadlift"
    assert routed["intent_metadata"]["target_exercise"].lower() == "ohp"

