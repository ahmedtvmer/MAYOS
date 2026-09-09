import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from langchain_core.messages import HumanMessage

from agent.assistant_graph import assistant_graph
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger
from utils.text_scrubber import scrub_coach_output

logger = MyosLogger().get_logger(__name__)


def test_unit_scrubber():
    test_cases = [
        (
            "Sure thing! Here is the breakdown: Romanian deadlifts overload the lengthened hamstrings. Hope this helps!",
            "Romanian deadlifts overload the lengthened hamstrings.",
        ),
        (
            "Great question! In terms of biomechanics, the hack squat stabilizes the spine. Keep crushing it!",
            "The hack squat stabilizes the spine.",
        ),
        (
            "Certainly. As an AI, I suggest high-bar squats over low-bar for quad bias. Let me know if you have any other questions.",
            "I suggest high-bar squats over low-bar for quad bias.",
        ),
        (
            "Direct technical answer without any conversational preamble.",
            "Direct technical answer without any conversational preamble.",
        ),
    ]
    for raw, expected in test_cases:
        cleaned = scrub_coach_output(raw)
        assert cleaned == expected, f"Scrubber failed! Expected '{expected}', got '{cleaned}'"
    logger.info("✅ Unit scrubber verified.")


def test_live_assistant_tone():
    db = DatabaseManager()
    db.switch_user("test_validation_user")
    db.update_user_persona(
        coach_tone="Direct, grounded, and pragmatic. No pleasantries.",
        custom_instructions="Do not include cheerleading or conversational pleasantries.",
    )
    state = {
        "messages": [HumanMessage(content="Why should I prioritize Romanian deadlifts before seated leg curls?")],
        "trainee_id": "test_validation_user",
        "coach_tone": "Direct, grounded, and pragmatic. No pleasantries.",
        "custom_instructions": "Do not include cheerleading or conversational pleasantries.",
        "intent": "coaching_qa",
        "intent_metadata": {},
        "program_updated": False,
        "response_content": None,
    }
    result = assistant_graph.invoke(state)
    output = result.get("response_content", "").strip().lower()
    banned = [
        "sure thing",
        "certainly",
        "great question",
        "happy to help",
        "hope this helps",
        "keep crushing it",
        "as an ai",
    ]
    for phrase in banned:
        assert phrase not in output, f"Tone leak: '{phrase}'"
    logger.info("✅ Live tone enforcement verified.")


if __name__ == "__main__":
    test_unit_scrubber()
    test_live_assistant_tone()
