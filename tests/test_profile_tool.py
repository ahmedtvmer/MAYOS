import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from agent.tools import save_user_profile
from database.database_manager import DatabaseManager
from utils.logger import MyosLogger

logger = MyosLogger().get_logger(__name__)

db = DatabaseManager()

def test_profile_flow():
    # Simulate messy LLM outputs with units and strings
    raw_payload = {
        "proportions": "My lower body is taller",
        "age": "21 years",
        "weight_kg": "80 kg",
        "height_cm": "183 cm",
        "current_goal": "Hypertrophy",
        "long_term_goal": "Aesthetic strength",
        "weekly_frequency": "4 days",
        "training_age_years": "3 years",
        "equipment_access": "Commercial gym",
        "injuries_or_limitations": "Occasional lower back tightness",
        "stress_and_sleep": "Medium stress, 7 hours sleep"
    }

    result = save_user_profile.invoke(raw_payload)
    logger.info(f"Tool Output: {result}")

    saved = db.get_user_profile()
    logger.info("\nSaved SQLite Record:")
    for k, v in saved.items():
        logger.info(f"  {k}: {v}")

    assert saved["proportions"] == "long_legs"
    assert saved["weight_kg"] == 80
    assert saved["height_cm"] == 183.0
    assert saved["weekly_frequency"] == 4
    logger.info("\nAll assertions passed.")

if __name__ == "__main__":
    test_profile_flow()