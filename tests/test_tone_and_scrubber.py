import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from langchain_core.messages import HumanMessage
from utils.text_scrubber import scrub_coach_output, BANNED_LEAD_PATTERNS, BANNED_TRAIL_PATTERNS
from agent.assistant_graph import assistant_graph
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)

def test_unit_scrubber():
    logger.info("--- 1. Testing Lexical Scrubber Unit Cases ---")
    
    test_cases = [
        (
            "Sure thing! Here is the breakdown: Romanian deadlifts overload the lengthened hamstrings. Hope this helps!",
            "Romanian deadlifts overload the lengthened hamstrings."
        ),
        (
            "Great question! In terms of biomechanics, the hack squat stabilizes the spine. Keep crushing it!",
            "The hack squat stabilizes the spine."
        ),
        (
            "Certainly. As an AI, I suggest high-bar squats over low-bar for quad bias. Let me know if you have any other questions.",
            "I suggest high-bar squats over low-bar for quad bias."
        ),
        (
            "Direct technical answer without any conversational preamble.",
            "Direct technical answer without any conversational preamble."
        )
    ]

    for raw, expected in test_cases:
        cleaned = scrub_coach_output(raw)
        logger.info(f"Raw:      \"{raw}\"")
        logger.info(f"Cleaned:  \"{cleaned}\"")
        assert cleaned == expected, f"Scrubber failed! Expected '{expected}', got '{cleaned}'"
        logger.info("✅ Pattern stripped cleanly.\n")

def test_live_assistant_tone():
    logger.info("--- 2. Testing Live Assistant Generation Node ---")
    
    db = DatabaseManager()
    # Set pragmatic tone directive in active test user
    db.switch_user("test_validation_user")
    db.update_user_persona(
        coach_tone="Direct, grounded, and pragmatic. No pleasantries.",
        custom_instructions="Do not include cheerleading or conversational pleasantries."
    )

    state = {
        "messages": [HumanMessage(content="Why should I prioritize Romanian deadlifts before seated leg curls?")],
        "trainee_id": "test_validation_user",
        "coach_tone": "Direct, grounded, and pragmatic. No pleasantries.",
        "custom_instructions": "Do not include cheerleading or conversational pleasantries.",
        "intent": "coaching_qa",
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None
    }

    result = assistant_graph.invoke(state)
    output = result.get("response_content", "").strip()

    logger.info(f"Assistant Output:\n{output}\n")

    # Verify no conversational throat-clearing leaks through
    lower_output = output.lower()
    banned_phrases = [
        "sure thing", "certainly", "great question", "happy to help",
        "hope this helps", "keep crushing it", "consistency is key",
        "as an ai", "let me know if you have any questions"
    ]

    for phrase in banned_phrases:
        assert phrase not in lower_output, f"Tone leak detected! Found banned phrase: '{phrase}'"

    assert len(output) > 20, "Output was truncated or empty."
    logger.info("✅ Live assistant generation passed tone and anti-fluff verification.")

if __name__ == "__main__":
    logger.info("⚡ Starting Tone Enforcement & Scrubber Test Suite...\n")
    test_unit_scrubber()
    test_live_assistant_tone()
    logger.info("\n🎉 Tone enforcement and lexical scrubbing verified.")